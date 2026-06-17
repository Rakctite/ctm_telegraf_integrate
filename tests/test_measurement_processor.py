import importlib
import pathlib
import sys
import types
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "telegraf_py"))
sys.modules.setdefault("psycopg2", types.SimpleNamespace(connect=None))


class MeasurementProcessorTests(unittest.TestCase):
    def setUp(self):
        self.processor = importlib.import_module("measurement_processor")
        with self.processor.cache_lock:
            self.processor.mapping_cache = {
                "LO054:MC02:TEMP_BT": (10, 20),
                "LO054:MC02:STATUS": (11, 20),
            }

    def test_routes_numeric_value_to_measurement(self):
        line = (
            'mqtt_measurement,equip_name=MC02,line_code=LO054 '
            'timestamp="2026-06-17 10:11:12.123+09",TEMP_BT=123.45 '
            "1773359485704463059"
        )

        result = self.processor.process_line(line)

        self.assertEqual(
            result,
            'measurement sensor_id=10i,equip_id=20i,value=123.45,'
            'capture_dt="2026-06-17 10:11:12.123+09"\n',
        )

    def test_routes_text_value_to_value_txt(self):
        line = (
            'mqtt_measurement,equip_name=MC02,line_code=LO054 '
            'timestamp="2026-06-17 10:11:12.123+09",STATUS="RUN"'
        )

        result = self.processor.process_line(line)

        self.assertEqual(
            result,
            'measurement sensor_id=11i,equip_id=20i,value_txt="RUN",'
            'capture_dt="2026-06-17 10:11:12.123+09"\n',
        )


if __name__ == "__main__":
    unittest.main()
