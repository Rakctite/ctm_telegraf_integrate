import importlib
import pathlib
import sys
import types
import unittest


ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "telegraf_py"))
sys.modules.setdefault("psycopg2", types.SimpleNamespace(connect=None))


class StatusProcessorTests(unittest.TestCase):
    def setUp(self):
        self.processor = importlib.import_module("status_processor")
        with self.processor.cache_lock:
            self.processor.mapping_cache = {
                "LO054:MC02:Temp_ST01_PL01": (211, 20),
                "LO054:MC02:Temp_ST01_PL02": (212, 20),
            }

    def test_routes_status_sensor_to_sensor_status(self):
        line = (
            'mqtt_status,equip_name=MC02,line_code=LO054,station=ST01,source=iot_temp,status_suffix=status '
            'sensor_code="Temp_ST01_PL01",conn_status="on",last_seen="2026-06-18 05:25:09.580+07",'
            'health_score=100,error_msg="",update_time="2026-06-18 05:25:10.210+07" '
            "1781735110210000000"
        )

        result = self.processor.process_line(line)

        self.assertEqual(
            result,
            'sensor_status sensor_id=211i,conn_status="on",'
            'last_seen="2026-06-18 05:25:09.580+07",health_score=100 '
            "1781735110210000000\n",
        )

    def test_rejects_status_without_status_suffix(self):
        line = (
            'mqtt_status,equip_name=MC02,line_code=LO054,station=ST01,source=iot_temp '
            'sensor_code="Temp_ST01_PL01",conn_status="on",update_time="2026-06-18 05:25:10.210+07"'
        )

        self.assertIsNone(self.processor.process_line(line))


if __name__ == "__main__":
    unittest.main()
