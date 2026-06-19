import json
import os
import signal
import sys
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone

import psycopg2


DB_CONFIG = os.getenv(
    "DB_CONFIG",
    "host=hmi-db-postgres dbname=edge_hmi user=admin password=1q2w3e4r connect_timeout=5",
)
MQTT_HOST = os.getenv("MQTT_HOST", "mosquitto")
MQTT_PORT = int(os.getenv("MQTT_PORT", "1883"))
MQTT_TOPIC = os.getenv("STATUS_OBSERVER_TOPIC", "C-S/+/+/+/+/+/+/+/status")


@dataclass(frozen=True)
class ObserverConfig:
    system_sensor_codes: tuple[str, ...] = ("PYTHON_SYSTEM",)
    offline_timeout_s: float = 5.0
    check_interval_s: float = 1.0
    startup_grace_s: float = 5.0
    cascade_history_enabled: bool = False

    @classmethod
    def from_env(cls):
        return cls(
            system_sensor_codes=tuple(
                code.strip()
                for code in os.getenv("STATUS_OBSERVER_SYSTEM_SENSOR_CODES", "PYTHON_SYSTEM").split(",")
                if code.strip()
            ),
            offline_timeout_s=_float_env("STATUS_OBSERVER_OFFLINE_TIMEOUT_S", cls.offline_timeout_s),
            check_interval_s=_float_env("STATUS_OBSERVER_CHECK_INTERVAL_S", cls.check_interval_s),
            startup_grace_s=_float_env("STATUS_OBSERVER_STARTUP_GRACE_S", cls.startup_grace_s),
            cascade_history_enabled=_bool_env("STATUS_OBSERVER_CASCADE_HISTORY_ENABLED", False),
        )


@dataclass
class SystemState:
    sensor_id: int
    equip_id: int
    line_code: str
    equip_name: str
    sensor_code: str
    conn_status: str
    last_seen: datetime | None


class StatusObserver:
    def __init__(self, store, config: ObserverConfig):
        self.store = store
        self.config = config
        self.system_states: dict[int, SystemState] = {}
        self._system_by_key: dict[tuple[str, str, str], int] = {}
        self._started_at: datetime | None = None
        self._lock = threading.Lock()

    def load_initial_state(self, now: datetime | None = None):
        loaded_at = _utc_now() if now is None else now
        mappings = self.store.fetch_sensor_mappings()
        system_mappings = [
            row for row in mappings if row["sensor_code"] in self.config.system_sensor_codes
        ]
        current = self.store.fetch_current_status([row["sensor_id"] for row in system_mappings])

        states = {}
        key_index = {}
        for row in system_mappings:
            status = current.get(row["sensor_id"], {})
            state = SystemState(
                sensor_id=row["sensor_id"],
                equip_id=row["equip_id"],
                line_code=row["line_code"],
                equip_name=row["equip_name"],
                sensor_code=row["sensor_code"],
                conn_status=status.get("conn_status") or "unknown",
                last_seen=_coerce_datetime(status.get("last_seen")),
            )
            states[state.sensor_id] = state
            key_index[(state.line_code, state.equip_name, state.sensor_code)] = state.sensor_id

        with self._lock:
            self._started_at = loaded_at
            self.system_states = states
            self._system_by_key = key_index

    def handle_status_payload(self, topic: str, payload: str | bytes, received_at: datetime | None = None):
        now = _utc_now() if received_at is None else received_at
        topic_info = _parse_status_topic(topic)
        if topic_info is None:
            return

        try:
            data = json.loads(payload.decode("utf-8") if isinstance(payload, bytes) else payload)
        except (TypeError, json.JSONDecodeError, UnicodeDecodeError):
            return

        sensors = data.get("sensors")
        if not isinstance(sensors, list):
            return

        line_code = topic_info["line_code"]
        equip_name = topic_info["equip_name"]
        for sensor in sensors:
            sensor_code = str(sensor.get("sensor_code") or "")
            if not sensor_code:
                continue
            sensor_id = self._system_by_key.get((line_code, equip_name, sensor_code))
            if sensor_id is None:
                continue
            last_seen = _coerce_datetime(sensor.get("last_seen")) or _coerce_datetime(sensor.get("update_time")) or now
            conn_status = str(sensor.get("conn_status") or "on")
            self._mark_system_seen(sensor_id, conn_status, last_seen, now)

    def check_timeouts(self, now: datetime | None = None):
        check_time = _utc_now() if now is None else now
        with self._lock:
            if self._started_at is not None:
                grace_age = (check_time - self._started_at).total_seconds()
                if grace_age < self.config.startup_grace_s:
                    return
            states = list(self.system_states.values())

        for state in states:
            if state.last_seen is None:
                continue
            age = (check_time - state.last_seen).total_seconds()
            if age >= self.config.offline_timeout_s and state.conn_status != "off":
                error_msg = f"heartbeat timeout after {int(age)}s"
                self.store.mark_sensor_offline(state.sensor_id, check_time, error_msg)
                self.store.mark_group_offline(
                    state.equip_id,
                    state.sensor_id,
                    check_time,
                    "parent system heartbeat timeout",
                )
                with self._lock:
                    current = self.system_states.get(state.sensor_id)
                    if current is not None:
                        current.conn_status = "off"

    def _mark_system_seen(self, sensor_id: int, conn_status: str, last_seen: datetime, event_time: datetime):
        with self._lock:
            state = self.system_states.get(sensor_id)
            if state is None:
                return
            previous = state.conn_status
            state.conn_status = conn_status
            state.last_seen = last_seen


class PostgresStatusStore:
    def __init__(self, db_config: str = DB_CONFIG):
        self.db_config = db_config

    def fetch_sensor_mappings(self):
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute("SET search_path TO core, public")
                cur.execute(
                    """
                    SELECT l.line_code,
                           e.equip_name,
                           s.sensor_name AS sensor_code,
                           s.id AS sensor_id,
                           s.equip_id
                    FROM sensor_mst s
                    JOIN equip_mst e ON e.id = s.equip_id
                    JOIN line_mst l ON l.id = e.line_id
                    WHERE s.is_active IS TRUE;
                    """
                )
                return [
                    {
                        "line_code": row[0],
                        "equip_name": row[1],
                        "sensor_code": row[2],
                        "sensor_id": row[3],
                        "equip_id": row[4],
                    }
                    for row in cur.fetchall()
                ]

    def fetch_current_status(self, sensor_ids):
        if not sensor_ids:
            return {}
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute("SET search_path TO core, public")
                cur.execute(
                    "SELECT sensor_id, conn_status, last_seen "
                    "FROM sensor_status WHERE sensor_id = ANY(%s);",
                    (list(sensor_ids),),
                )
                return {
                    row[0]: {
                        "conn_status": row[1],
                        "last_seen": row[2],
                    }
                    for row in cur.fetchall()
                }

    def mark_sensor_offline(self, sensor_id, event_time, error_msg):
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute("SET search_path TO core, public")
                cur.execute(
                    """
                    UPDATE sensor_status
                    SET conn_status = 'off',
                        health_score = 0,
                        error_msg = %s,
                        update_time = %s
                    WHERE sensor_id = %s
                    """,
                    (error_msg, event_time, sensor_id),
                )

    def mark_group_offline(self, equip_id, exclude_sensor_id, event_time, error_msg):
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute("SET search_path TO core, public")
                cur.execute(
                    """
                    UPDATE sensor_status ss
                    SET conn_status = 'off',
                        health_score = 0,
                        error_msg = %s,
                        update_time = %s
                    FROM sensor_mst sm
                    WHERE ss.sensor_id = sm.id
                      AND sm.equip_id = %s
                      AND ss.sensor_id <> %s
                    """,
                    (error_msg, event_time, equip_id, exclude_sensor_id),
                )

    def _connect(self):
        return psycopg2.connect(self.db_config)


def run_observer():
    import paho.mqtt.client as mqtt

    stop_event = threading.Event()

    def _stop(_signum, _frame):
        stop_event.set()

    signal.signal(signal.SIGTERM, _stop)
    signal.signal(signal.SIGINT, _stop)

    config = ObserverConfig.from_env()
    observer = StatusObserver(PostgresStatusStore(), config)
    while True:
        try:
            observer.load_initial_state()
            break
        except Exception as exc:
            sys.stderr.write(f"[status_observer] initial load failed: {exc}\n")
            sys.stderr.flush()
            stop_event.wait(5)
            if stop_event.is_set():
                return

    client = mqtt.Client()
    client.on_connect = lambda c, _u, _f, rc: c.subscribe(MQTT_TOPIC, qos=1) if rc == 0 else None
    client.on_message = lambda _c, _u, msg: observer.handle_status_payload(msg.topic, msg.payload)
    client.connect(MQTT_HOST, MQTT_PORT, 60)
    client.loop_start()
    try:
        while not stop_event.wait(config.check_interval_s):
            observer.check_timeouts()
    finally:
        client.loop_stop()
        client.disconnect()


def _parse_status_topic(topic: str):
    parts = topic.strip("/").split("/")
    if len(parts) != 9 or parts[0] != "C-S" or parts[-1] != "status":
        return None
    return {
        "line_code": parts[4],
        "equip_name": parts[5],
        "station": parts[6],
        "source": parts[7],
    }


def _coerce_datetime(value):
    if value is None or isinstance(value, datetime):
        return value
    text = str(value).strip()
    if not text:
        return None
    if len(text) >= 3 and text[-3] in {"+", "-"} and text[-2:].isdigit():
        text = f"{text}00"
    for fmt in ("%Y-%m-%d %H:%M:%S.%f%z", "%Y-%m-%d %H:%M:%S%z"):
        try:
            return datetime.strptime(text, fmt).astimezone(timezone.utc)
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(text).astimezone(timezone.utc)
    except ValueError:
        return None


def _utc_now():
    return datetime.now(timezone.utc)


def _float_env(key: str, default: float):
    try:
        return float(os.getenv(key, default))
    except (TypeError, ValueError):
        return default


def _bool_env(key: str, default: bool):
    value = os.getenv(key)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


if __name__ == "__main__":
    run_observer()
