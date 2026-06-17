import sys
import threading
import time
from calendar import timegm
from datetime import datetime

import psycopg2


DB_CONFIG = "host=hmi-db-postgres dbname=edge_hmi user=admin password=1q2w3e4r connect_timeout=5"
UPDATE_INTERVAL = 60
RETRY_INTERVAL = 10

STATUS_FIELDS = {
    "conn_status",
    "last_seen",
    "health_score",
    "error_msg",
}
REQUIRED_FIELDS = {"conn_status", "update_time"}

mapping_cache = {}
cache_lock = threading.Lock()


def _unquote_line_value(val):
    if len(val) >= 2 and val[0] == '"' and val[-1] == '"':
        return val[1:-1].replace('\\"', '"').replace("\\\\", "\\")
    return val


def _escape_line_string(val):
    return str(val).replace("\\", "\\\\").replace('"', '\\"')


def _split_unquoted(text, delimiter, maxsplit=-1):
    parts = []
    current = []
    in_quotes = False
    escaped = False
    splits = 0

    for char in text:
        if escaped:
            current.append(char)
            escaped = False
            continue

        if char == "\\":
            current.append(char)
            escaped = True
            continue

        if char == '"':
            in_quotes = not in_quotes
            current.append(char)
            continue

        if char == delimiter and not in_quotes and (maxsplit < 0 or splits < maxsplit):
            parts.append("".join(current))
            current = []
            splits += 1
            continue

        current.append(char)

    parts.append("".join(current))
    return parts


def format_int(val):
    return f"{int(val)}i"


def format_string(val):
    return f'"{_escape_line_string(_unquote_line_value(val))}"'


def format_float(val):
    raw = _unquote_line_value(val)
    if isinstance(raw, str) and raw.endswith("i"):
        raw = raw[:-1]
    try:
        float(raw)
        return str(raw)
    except (ValueError, TypeError):
        return None


def parse_timestamp_ns(val):
    raw = _unquote_line_value(val)
    if not raw:
        return None

    normalized = raw
    timezone_part = raw[-3:]
    if len(raw) >= 3 and timezone_part[0] in {"+", "-"} and timezone_part[1:].isdigit():
        normalized = f"{raw}00"

    for pattern in ("%Y-%m-%d %H:%M:%S.%f%z", "%Y-%m-%d %H:%M:%S%z"):
        try:
            dt = datetime.strptime(normalized, pattern)
            return str(timegm(dt.utctimetuple()) * 1_000_000_000 + dt.microsecond * 1_000)
        except ValueError:
            continue
    return None


def fetch_mapping_once():
    global mapping_cache
    conn = None
    try:
        conn = psycopg2.connect(DB_CONFIG)
        cur = conn.cursor()
        cur.execute("SET search_path TO core, public")
        cur.execute("SELECT line_code, equip_name, sensor_code, sensor_id, equip_id FROM v_topic_mapping;")
        rows = cur.fetchall()

        temp_cache = {}
        for row in rows:
            key = f"{row[0]}:{row[1]}:{row[2]}"
            temp_cache[key] = (row[3], row[4])

        with cache_lock:
            mapping_cache = temp_cache

        cur.close()
        conn.close()
        return True
    except Exception as exc:
        sys.stderr.write(f" [Error] DB connection/query failed: {exc}\n")
        if conn:
            conn.close()
        return False


def update_mapping():
    while True:
        time.sleep(UPDATE_INTERVAL)
        if not fetch_mapping_once():
            time.sleep(RETRY_INTERVAL)
            continue


def process_line(line):
    try:
        line = line.strip()
        if not line:
            return None

        parts = _split_unquoted(line, " ", 2)
        if len(parts) < 2:
            return None

        tags = dict(item.split("=", 1) for item in parts[0].split(",") if "=" in item)
        if tags.get("status_suffix") != "status":
            return None

        line_code = tags.get("line_code")
        equip_name = tags.get("equip_name")
        if not line_code or not equip_name:
            return None

        fields = dict(item.split("=", 1) for item in _split_unquoted(parts[1], ",") if "=" in item)
        if not REQUIRED_FIELDS.issubset(fields):
            return None

        sensor_code = _unquote_line_value(fields.get("sensor_code", ""))
        if not sensor_code:
            return None

        timestamp = parse_timestamp_ns(fields["update_time"])
        if timestamp is None:
            return None

        lookup_key = f"{line_code}:{equip_name}:{sensor_code}"
        with cache_lock:
            current_cache = mapping_cache.copy()
        if lookup_key not in current_cache:
            return None

        sensor_id, _equip_id = current_cache[lookup_key]
        out_fields = [f"sensor_id={format_int(sensor_id)}"]

        conn_status = _unquote_line_value(fields["conn_status"])
        out_fields.append(f"conn_status={format_string(conn_status)}")

        if "last_seen" in fields:
            last_seen = _unquote_line_value(fields["last_seen"])
            if last_seen:
                out_fields.append(f"last_seen={format_string(last_seen)}")

        if "health_score" in fields:
            health_score = format_float(fields["health_score"])
            if health_score is not None:
                out_fields.append(f"health_score={health_score}")

        if "error_msg" in fields:
            error_msg = _unquote_line_value(fields["error_msg"])
            if error_msg:
                out_fields.append(f"error_msg={format_string(error_msg)}")

        return f"sensor_status {','.join(out_fields)} {timestamp}\n"
    except Exception:
        return None


def main():
    while not fetch_mapping_once():
        time.sleep(RETRY_INTERVAL)

    thread = threading.Thread(target=update_mapping, daemon=True)
    thread.start()

    while True:
        try:
            line = sys.stdin.readline()
            if not line:
                time.sleep(1)
                continue

            result = process_line(line)
            if result:
                sys.stdout.write(result)
                sys.stdout.flush()
            else:
                sys.stderr.write("[sensor_status] Dropped malformed or unmapped metric\n")
                sys.stderr.flush()
        except KeyboardInterrupt:
            break
        except Exception as exc:
            sys.stderr.write(f"[sensor_status] Processor error: {exc}\n")
            sys.stderr.flush()
            time.sleep(1)


if __name__ == "__main__":
    main()
