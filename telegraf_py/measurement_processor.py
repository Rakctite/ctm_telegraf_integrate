import sys
import threading
import time

import psycopg2


DB_CONFIG = "host=hmi-db-postgres dbname=edge_hmi user=admin password=1q2w3e4r connect_timeout=5"
UPDATE_INTERVAL = 60
RETRY_INTERVAL = 10

mapping_cache = {}
cache_lock = threading.Lock()


def _unquote_line_value(val):
    if len(val) >= 2 and val[0] == '"' and val[-1] == '"':
        return val[1:-1].replace('\\"', '"').replace("\\\\", "\\")
    return val


def _escape_line_string(val):
    return str(val).replace("\\", "\\\\").replace('"', '\\"')


def _numeric_line_value(val):
    raw = _unquote_line_value(val)
    if isinstance(raw, str) and raw.endswith("i"):
        raw = raw[:-1]
    try:
        float(raw)
        return str(raw)
    except (ValueError, TypeError):
        return None


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


def format_value(val):
    if val is None:
        return '""'

    if isinstance(val, int):
        return f"{val}i"
    try:
        float(val)
        if str(val).isdigit():
            return f"{val}i"
        return str(val)
    except (ValueError, TypeError):
        return f'"{_escape_line_string(val)}"'


def fetch_mapping_once():
    global mapping_cache
    conn = None
    try:
        conn = psycopg2.connect(DB_CONFIG)
        cur = conn.cursor()
        cur.execute("SET search_path TO core, public")

        query = "SELECT line_code, equip_name, sensor_code, sensor_id, equip_id FROM v_topic_mapping;"
        cur.execute(query)
        rows = cur.fetchall()

        temp_cache = {}
        for row in rows:
            key = f"{row[0]}:{row[1]}:{row[2]}"
            temp_cache[key] = (row[3], row[4])

        with cache_lock:
            mapping_cache = temp_cache

        cur.close()
        conn.close()
        sys.stderr.write(f" [Mapping] DB Fetch: {len(rows)} rows / cache: {len(mapping_cache)} rows\n")
        return True
    except Exception as e:
        sys.stderr.write(f" [Error] DB connection/query failed: {e}\n")
        if conn:
            conn.close()
        return False


def update_mapping():
    while True:
        time.sleep(UPDATE_INTERVAL)
        if not fetch_mapping_once():
            time.sleep(RETRY_INTERVAL)


def process_line(line):
    try:
        line = line.strip()
        if not line:
            return None

        parts = _split_unquoted(line, " ", 2)
        if len(parts) < 2:
            return None

        tags = dict(item.split("=", 1) for item in parts[0].split(",") if "=" in item)
        line_c = tags.get("line_code")
        equip_name = tags.get("equip_name")

        fields = dict(item.split("=", 1) for item in _split_unquoted(parts[1], ",") if "=" in item)
        capture_dt = fields.pop("timestamp", None)

        results = []
        with cache_lock:
            current_cache = mapping_cache.copy()

        for s_code, val in fields.items():
            if s_code == "time":
                continue

            lookup_key = f"{line_c}:{equip_name}:{s_code}"
            if lookup_key not in current_cache:
                continue

            s_id, e_id = current_cache[lookup_key]
            out_fields = [f"sensor_id={format_value(s_id)}", f"equip_id={format_value(e_id)}"]

            numeric_value = _numeric_line_value(val)
            if numeric_value is None:
                out_fields.append(f'value_txt="{_escape_line_string(_unquote_line_value(val))}"')
            else:
                out_fields.append(f"value={numeric_value}")

            if capture_dt is not None:
                out_fields.append(f'capture_dt="{_escape_line_string(_unquote_line_value(capture_dt))}"')

            # No metric timestamp here: Telegraf writes collection time into measurement.time.
            results.append(f"measurement {','.join(out_fields)}")

        return "\n".join(results) + "\n" if results else None
    except Exception:
        return None


def main():
    while not fetch_mapping_once():
        time.sleep(RETRY_INTERVAL)

    t = threading.Thread(target=update_mapping, daemon=True)
    t.start()

    while True:
        try:
            line = sys.stdin.readline()
            if not line:
                time.sleep(1)
                continue

            res = process_line(line)
            if res:
                sys.stdout.write(res)
                sys.stdout.flush()
        except KeyboardInterrupt:
            break
        except Exception as e:
            sys.stderr.write(f" [Fatal] main loop error: {e}\n")
            time.sleep(1)


if __name__ == "__main__":
    main()
