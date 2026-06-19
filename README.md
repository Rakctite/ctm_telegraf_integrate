# ctm_telegraf_integrate

Integrated Telegraf service for CTM measurement data and sensor status data.

## Image

```sh
docker build -t ctm_telegraf_integrate:1.0.2 .
```

Registry tag:

```text
203.228.107.184:5000/btx/ctm_telegraf_integrate:1.0.2
```

## Data Flow

Measurement flow:

```text
C-S/{plant}/{building}/{process}/{line_code}/{equip_name}/{station}/{source}
  -> mqtt_measurement
  -> measurement_processor.py
  -> core.measurement
```

Status flow:

```text
C-S/{plant}/{building}/{process}/{line_code}/{equip_name}/{station}/{source}/status
  -> mqtt_status
  -> status_processor.py
  -> core.sensor_status
```

Status observer flow:

```text
C-S/{plant}/{building}/{process}/{line_code}/{equip_name}/{station}/{source}/status
  -> status_observer.py
  -> in-memory last_seen tracking
  -> core.sensor_status_history on offline/recovery
  -> core.sensor_status off update on timeout
```

Both processors use `core.v_topic_mapping` with the existing mapping key:

```text
line_code:equip_name:sensor_code
```

The status payload field `sensor_code` is matched to `core.v_topic_mapping.sensor_code`, which is currently `sensor_mst.sensor_name AS sensor_code`.

## Status Observer

`status_observer` runs as a separate compose service using the same image as
Telegraf. It subscribes to 9-level status topics directly and keeps per-system
`last_seen` state in memory. On startup it loads current system status from
PostgreSQL once, then uses MQTT messages for normal operation.

Default watched system sensor code:

```text
PYTHON_SYSTEM
```

Timeout behavior:

- repeated `on` heartbeats only refresh in-memory `last_seen`;
- no heartbeat for `STATUS_OBSERVER_OFFLINE_TIMEOUT_S` seconds records one `offline` event;
- system offline also sets sensors in the same `line_code` and `equip_name` group to `off`;
- the first heartbeat after offline records one `recovery` event.

Main settings:

```text
STATUS_OBSERVER_SYSTEM_SENSOR_CODES=PYTHON_SYSTEM
STATUS_OBSERVER_OFFLINE_TIMEOUT_S=5
STATUS_OBSERVER_CHECK_INTERVAL_S=1
STATUS_OBSERVER_STARTUP_GRACE_S=5
```

## Compose

```sh
docker compose pull
docker compose up -d
```

The compose file includes PostgreSQL, Mosquitto, and the integrated Telegraf service.
