# Session Notes

## Current Context
- Project path: `C:\Users\mingyu.shin\docker\0_services\ctm_telegraf_integrate`.
- Integrated workspace root: `C:\Users\mingyu.shin\docker`.
- This project integrates CTM MQTT measurement/status topics into PostgreSQL through Telegraf processors.
- Measurement data flows into `core.measurement`.
- Status data flows into `core.sensor_status`.
- When starting Codex here, also read the root `C:\Users\mingyu.shin\docker\SESSION.md` for integrated service context.

## Repositories
- Git remote: `https://github.com/Rakctite/ctm_telegraf_integrate`.
- Main branch: `main`.
- Latest observed commit: `cc3e865 Create integrated Telegraf service`.

## Session Discipline
- When Codex changes files in this project, update this `SESSION.md` in the same work session.
- Record the purpose of the change, key files touched, verification result, commit hash, and any remaining TODO.
- If work is done from another terminal, branch, or worktree, sync this file after the commit is merged or pushed to `main`.
- If the change affects integrated deployment behavior, also update the root `C:\Users\mingyu.shin\docker\SESSION.md`.

## Docker Image
- Last recorded pushed image: `203.228.107.184:5000/btx/ctm_telegraf_integrate:1.0.0`.
- Build source tag recorded in README: `ctm_telegraf_integrate:1.0.0`.

## Latest State
- 2026-06-18: Working tree was clean and tracking `origin/main`.
- 2026-06-18: Compose includes PostgreSQL, Mosquitto, and `ctm_telegraf_integrate`.
- 2026-06-18: Project README documents measurement and status data flows.
- 2026-06-19: Added a status observer design in this project only. It subscribes to 9-level status topics, keeps system heartbeat state in memory, loads DB state once on startup, and writes offline/recovery history on state transitions.

## Open TODO
- Confirm whether root compose or this service compose is authoritative for integrated deployments.
- Review Mosquitto port differences between root compose and this project compose.
- Confirm expected image tag after future processor changes.

## Work Log

### 2026-06-18
- Confirmed repository is clean on `main...origin/main`.
- Confirmed latest commit `cc3e865 Create integrated Telegraf service`.
- Reviewed README data flow:
  - `C-S/{plant}/{building}/{process}/{line_code}/{equip_name}/{station}/{source}` to `core.measurement`.
  - Same path with `/status` suffix to `core.sensor_status`.
- Recorded Docker image version from README and compose.

### 2026-06-19
- Added `telegraf_py/status_observer.py`.
- Observer startup behavior: loads watched system sensors from `core.v_topic_mapping` and current state from `core.sensor_status` once, then applies a startup grace window before timeout judgement.
- Observer runtime behavior: subscribes to `C-S/+/+/+/+/+/+/+/status`, tracks per-system `last_seen` in memory, records one `offline` event after timeout, cascades current status `off` to the same `line_code`/`equip_name` group, and records one `recovery` event on the first heartbeat after offline.
- Added compose service `status_observer` using the same `ctm_telegraf_integrate` image with command `python3 -u /telegraf/telegraf_py/status_observer.py`.
- Added Docker image dependency `python3-paho-mqtt`.
- Documented observer flow and settings in `README.md`.
- Added tests in `tests/test_status_observer.py` and expanded `tests/test_telegraf_config.py`.
- Verification: `python -m pytest` -> `13 passed`.
- Implementation commit: `d0bea38 Add MQTT status observer service`.
- 2026-06-19 Docker Desktop validation found the running `ctm_telegraf_integrate_local` image did not include `status_observer.py` or `paho`; rebuilt local test image `ctm_telegraf_integrate:observer-test` successfully.
- Live DB validation found observer history inserts were still using the old temporary schema (`conn_status`, `source`) while the applied hypertable uses `conn_status_before`, `conn_status_after`, `equip_id`, and `update_time`.
- Fixed observer responsibility split: observer now updates `core.sensor_status`; PostgreSQL trigger records history. Observer loads watched system sensors from `core.sensor_mst` joined to `core.equip_mst` and `core.line_mst`, not from `v_topic_mapping`.
- Verified against Docker Desktop DB with isolated test equip `CODEX_OBS_TEST`: timeout changed system and child current statuses to `off`, trigger wrote offline history, recovery update wrote recovery history, and cleanup removed all test rows. Final history count returned to `0`.
- Verification after fix: `python -m pytest` -> `13 passed`; `docker compose config` -> ok; `docker build -t ctm_telegraf_integrate:observer-test .` -> ok.
