"""Essais du convertisseur et de la coupure batterie sur un bus simulé."""

from types import SimpleNamespace
from contextlib import redirect_stderr
from io import StringIO
from unittest import TestCase
from unittest.mock import MagicMock, call, patch

from . import battery


class BatteryTest(TestCase):
    def setUp(self):
        self.bus = MagicMock()
        factory = MagicMock()
        factory.return_value.__enter__.return_value = self.bus
        self.enterContext(patch.dict("sys.modules", {"smbus2": SimpleNamespace(SMBus=factory)}))
        self.enterContext(patch.object(battery, "sleep"))

    def simulate_conversion(self, raw):
        self.bus.read_i2c_block_data.side_effect = [[0x73, 0x83], [0xF3, 0x83], list(raw.to_bytes(2, "big", signed=True))]

    def test_conversion_a3_et_pont_diviseur(self):
        self.simulate_conversion(18800)
        self.assertAlmostEqual(battery.read_battery_voltage(), 7.35)
        self.bus.write_i2c_block_data.assert_called_once_with(0x48, 0x01, [0xF3, 0x83])
        self.assertEqual(self.bus.read_i2c_block_data.call_args_list, [
            call(0x48, 0x01, 2), call(0x48, 0x01, 2), call(0x48, 0x00, 2),
        ])

    def test_seuil_de_coupure(self):
        self.simulate_conversion(17904)
        output = StringIO()
        with redirect_stderr(output):
            self.assertIs(battery.check_battery(), battery.BatteryStatus.ANORMAL)
        self.assertIn("A3=2.2380 V", output.getvalue())
        self.assertIn("ANORMAL", output.getvalue())
        self.simulate_conversion(17905)
        self.assertIs(battery.check_battery(), battery.BatteryStatus.NORMAL)

    def test_mesure_pres_de_la_tension_du_voltmetre(self):
        self.simulate_conversion(20480)
        reading = battery.read_battery_measurement()
        self.assertAlmostEqual(reading.a3_voltage, 2.56)
        self.assertAlmostEqual(reading.pack_voltage, 2.56 * 147 / 47)
        self.assertIs(reading.status, battery.BatteryStatus.NORMAL)
        self.assertIn("config=0xf383", reading.describe())

    def test_amorcage_et_confirmation_au_demarrage(self):
        self.bus.read_i2c_block_data.side_effect = [
            [0xF3, 0x83], [0, 0],
            [0xF3, 0x83], [0x50, 0],
        ]
        self.assertIs(battery.check_battery(startup=True), battery.BatteryStatus.NORMAL)
        self.assertEqual(self.bus.write_i2c_block_data.call_count, 2)

    def test_tension_confirmee_basse_interdit_le_demarrage(self):
        self.bus.read_i2c_block_data.side_effect = [
            [0xF3, 0x83], [0x50, 0],
            [0xF3, 0x83], [0x40, 0],
        ]
        with redirect_stderr(StringIO()):
            self.assertIs(battery.check_battery(startup=True), battery.BatteryStatus.ANORMAL)

    def test_conversion_non_terminee(self):
        self.bus.read_i2c_block_data.return_value = [0x73, 0x83]
        with patch.object(battery, "monotonic", side_effect=[0.0, 0.11]), self.assertRaises(TimeoutError):
            battery.read_battery_voltage()

    def test_tension_incoherente(self):
        self.simulate_conversion(30000)
        with self.assertRaises(RuntimeError):
            battery.read_battery_voltage()
