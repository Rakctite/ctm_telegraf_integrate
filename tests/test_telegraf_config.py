import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class TelegrafConfigTests(unittest.TestCase):
    def test_has_separate_measurement_and_status_mqtt_inputs(self):
        config = (ROOT / "telegraf.conf").read_text(encoding="utf-8")

        self.assertIn('name_override = "mqtt_measurement"', config)
        self.assertIn('topics = ["C-S/+/+/+/+/+/+/+"]', config)
        self.assertIn('name_override = "mqtt_status"', config)
        self.assertIn('topics = ["C-S/+/+/+/+/+/+/+/status"]', config)

    def test_routes_each_input_to_its_processor(self):
        config = (ROOT / "telegraf.conf").read_text(encoding="utf-8")

        self.assertRegex(
            config,
            re.compile(r'namepass = \["mqtt_measurement"\][\s\S]*measurement_processor\.py'),
        )
        self.assertRegex(
            config,
            re.compile(r'namepass = \["mqtt_status"\][\s\S]*status_processor\.py'),
        )

    def test_has_separate_measurement_and_status_outputs(self):
        config = (ROOT / "telegraf.conf").read_text(encoding="utf-8")

        self.assertIn('namepass = ["measurement"]', config)
        self.assertIn('namepass = ["sensor_status"]', config)
        self.assertIn('timestamp_column = "update_time"', config)

    def test_status_output_upserts_by_sensor_id(self):
        config = (ROOT / "telegraf.conf").read_text(encoding="utf-8")

        self.assertIn("pg_advisory_xact_lock(NEW.sensor_id::bigint)", config)
        self.assertIn("UPDATE core.sensor_status", config)
        self.assertIn("WHERE sensor_id = NEW.sensor_id", config)
        self.assertIn("IF FOUND THEN", config)
        self.assertIn("CREATE TRIGGER trg_sensor_status_upsert", config)
        self.assertNotIn("$$", config)
        self.assertNotIn("DELETE FROM core.sensor_status", config)
        self.assertNotIn("CREATE UNIQUE INDEX", config)

    def test_compose_runs_status_observer_as_separate_service(self):
        compose = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")

        self.assertIn("status_observer:", compose)
        self.assertIn("python3", compose)
        self.assertIn("/telegraf/telegraf_py/status_observer.py", compose)
        self.assertIn("STATUS_OBSERVER_OFFLINE_TIMEOUT_S", compose)

    def test_dockerfile_installs_status_observer_dependencies(self):
        dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")

        self.assertIn("python3-paho-mqtt", dockerfile)
        self.assertIn("status_observer.py", dockerfile)


if __name__ == "__main__":
    unittest.main()
