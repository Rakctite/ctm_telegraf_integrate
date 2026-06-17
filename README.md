# ctm_telegraf_integrate

Integrated Telegraf service for CTM measurement data and sensor status data.

## Image

```sh
docker build -t ctm_telegraf_integrate:1.0.0 .
```

Registry tag:

```text
203.228.107.184:5000/btx/ctm_telegraf_integrate:1.0.0
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

Both processors use `core.v_topic_mapping` with the existing mapping key:

```text
line_code:equip_name:sensor_code
```

The status payload field `sensor_code` is matched to `core.v_topic_mapping.sensor_code`, which is currently `sensor_mst.sensor_name AS sensor_code`.

## Compose

```sh
docker compose pull
docker compose up -d
```

The compose file includes PostgreSQL, Mosquitto, and the integrated Telegraf service.
