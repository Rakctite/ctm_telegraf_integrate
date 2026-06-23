import importlib
import json
import os
import pathlib
import sys
import types
import unittest
from datetime import datetime, timedelta, timezone


ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "telegraf_py"))
sys.modules.setdefault("psycopg2", types.SimpleNamespace(connect=None))
sys.modules.setdefault("paho", types.SimpleNamespace())
sys.modules.setdefault("paho.mqtt", types.SimpleNamespace())
sys.modules.setdefault("paho.mqtt.client", types.SimpleNamespace(Client=None))


class FakeStore:
    def __init__(self):
        self.mappings = [
            {
                "sensor_id": 301,
                "equip_id": 20,
                "line_code": "LO054",
                "equip_name": "MC02",
                "sensor_code": "SYSTEM",
            },
            {
                "sensor_id": 211,
                "equip_id": 20,
                "line_code": "LO054",
                "equip_name": "MC02",
                "sensor_code": "Temp_ST01_PL01",
            },
        ]
        self.current = {
            301: {
                "conn_status": "on",
                "last_seen": datetime(2026, 6, 19, 10, 0, 0, tzinfo=timezone.utc),
            }
        }
        self.history = []
        self.offline_updates = []
        self.group_updates = []

    def fetch_sensor_mappings(self):
        return list(self.mappings)

    def fetch_current_status(self, sensor_ids):
        return {sensor_id: self.current.get(sensor_id, {}) for sensor_id in sensor_ids}

    def mark_sensor_offline(self, sensor_id, event_time, error_msg):
        self.offline_updates.append((sensor_id, event_time, error_msg))
        self.current[sensor_id] = {
            "conn_status": "off",
            "last_seen": self.current.get(sensor_id, {}).get("last_seen"),
        }

    def mark_group_offline(self, equip_id, exclude_sensor_id, event_time, error_msg):
        self.group_updates.append((equip_id, exclude_sensor_id, event_time, error_msg))


class StatusObserverTests(unittest.TestCase):
    def setUp(self):
        self.observer_module = importlib.import_module("status_observer")

    def test_default_system_sensor_code_is_system(self):
        old_value = os.environ.pop("STATUS_OBSERVER_SYSTEM_SENSOR_CODES", None)
        try:
            config = self.observer_module.ObserverConfig.from_env()
        finally:
            if old_value is not None:
                os.environ["STATUS_OBSERVER_SYSTEM_SENSOR_CODES"] = old_value

        self.assertEqual(config.system_sensor_codes, ("SYSTEM",))

    def test_timeout_marks_system_offline_and_cascades_child_sensors(self):
        store = FakeStore()
        observer = self.observer_module.StatusObserver(
            store,
            self.observer_module.ObserverConfig(
                system_sensor_codes=("SYSTEM",),
                offline_timeout_s=5,
                startup_grace_s=0,
            ),
        )
        observer.load_initial_state(datetime(2026, 6, 19, 10, 0, 1, tzinfo=timezone.utc))

        observer.check_timeouts(datetime(2026, 6, 19, 10, 0, 6, tzinfo=timezone.utc))

        self.assertEqual(store.offline_updates[0][0], 301)
        self.assertEqual(store.group_updates[0][0:2], (20, 301))
        self.assertEqual(store.history, [])
        self.assertEqual(observer.system_states[301].conn_status, "off")

        observer.check_timeouts(datetime(2026, 6, 19, 10, 0, 7, tzinfo=timezone.utc))

        self.assertEqual(len(store.history), 0)
        self.assertEqual(len(store.offline_updates), 1)

    def test_heartbeat_after_offline_records_recovery_once(self):
        store = FakeStore()
        store.current[301]["conn_status"] = "off"
        observer = self.observer_module.StatusObserver(
            store,
            self.observer_module.ObserverConfig(
                system_sensor_codes=("SYSTEM",),
                offline_timeout_s=5,
                startup_grace_s=0,
            ),
        )
        observer.load_initial_state(datetime(2026, 6, 19, 10, 0, 1, tzinfo=timezone.utc))

        payload = json.dumps(
            {
                "timestamp": "2026-06-19 10:00:02.000+00",
                "sensors": [
                    {
                        "sensor_code": "SYSTEM",
                        "conn_status": "on",
                        "last_seen": "2026-06-19 10:00:02.000+00",
                        "update_time": "2026-06-19 10:00:02.000+00",
                    }
                ],
            }
        )
        observer.handle_status_payload(
            "C-S/site/building/process/LO054/MC02/ST01/ctm_modbus_gathering/status",
            payload,
            datetime(2026, 6, 19, 10, 0, 2, tzinfo=timezone.utc),
        )
        observer.handle_status_payload(
            "C-S/site/building/process/LO054/MC02/ST01/ctm_modbus_gathering/status",
            payload,
            datetime(2026, 6, 19, 10, 0, 3, tzinfo=timezone.utc),
        )

        self.assertEqual(store.history, [])
        self.assertEqual(observer.system_states[301].conn_status, "on")

    def test_startup_grace_delays_timeout_judgement(self):
        store = FakeStore()
        observer = self.observer_module.StatusObserver(
            store,
            self.observer_module.ObserverConfig(
                system_sensor_codes=("SYSTEM",),
                offline_timeout_s=5,
                startup_grace_s=10,
            ),
        )
        started_at = datetime(2026, 6, 19, 10, 0, 1, tzinfo=timezone.utc)
        observer.load_initial_state(started_at)

        observer.check_timeouts(started_at + timedelta(seconds=6))

        self.assertEqual(store.history, [])
        self.assertEqual(store.offline_updates, [])


if __name__ == "__main__":
    unittest.main()
