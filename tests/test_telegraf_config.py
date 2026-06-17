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


if __name__ == "__main__":
    unittest.main()
