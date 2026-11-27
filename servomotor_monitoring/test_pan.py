"""Essais d’asservissement PAN sans GPIO ni bus I²C."""

from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import Mock, call, patch

from . import pan
from .servo import Servo, ServoController


class PanPositionTest(TestCase):
    def setUp(self):
        self.now = self.rate = 0.0
        self.enterContext(patch.object(pan, "monotonic", side_effect=lambda: self.now))
        self.enterContext(patch.object(pan, "sleep", side_effect=self.advance))
        self.enterContext(patch.object(Servo.PAN, "angle", None))
        folder = Path(self.enterContext(TemporaryDirectory()))
        gyro = Mock()
        gyro.calibrate.return_value = 0.0
        gyro.rate.side_effect = lambda: self.rate
        self.guard = pan.PanGuard(gyro, folder / "pan.json")
        self.guard.reference(self.stop)
        self.controller = ServoController()
        self.enterContext(patch.object(self.controller, "_pan_guard", return_value=self.guard))
        self.enterContext(patch.object(self.controller, "_lock_bus"))
        self.enterContext(patch.object(self.controller, "_disable", side_effect=lambda _servo: self.stop()))
        self.enterContext(patch.object(self.controller, "_set_output", side_effect=self.drive))

    def advance(self, duration):
        self.now += duration

    def drive(self, _servo, fraction):
        self.rate = 240 * fraction

    def stop(self):
        self.rate = 0.0

    def test_aller_retour_et_persistance(self):
        self.assertIs(self.controller.set_angle(Servo.PAN, 90), pan.PanResult.TERMINE)
        self.assertLessEqual(abs(90 - Servo.PAN.angle), pan.TARGET_TOLERANCE_DEG)
        self.assertEqual(Servo.PAN.angle, self.guard.state().angle)
        self.assertIs(self.controller.set_angle(Servo.PAN, 0), pan.PanResult.TERMINE)
        self.assertLessEqual(abs(Servo.PAN.angle), pan.TARGET_TOLERANCE_DEG)
        self.assertEqual(self.rate, 0.0)

    def test_limite_avant_un_tour(self):
        self.assertIs(self.controller.set_angle(Servo.PAN, 360), pan.PanResult.LIMITE_HORAIRE)
        self.assertLess(self.guard.state().angle, 360)
        self.assertEqual(self.rate, 0.0)

    def test_positions_initiales_et_canal_tilt(self):
        monitor = Mock()
        with patch.object(self.controller, "set_angle", side_effect=[pan.PanResult.TERMINE, None, None]) as set_angle:
            self.assertIs(self.controller.reset_positions(monitor=monitor), pan.PanResult.TERMINE)
        self.assertEqual(set_angle.call_args_list, [
            call(Servo.PAN, 0, monitor=monitor), call(Servo.TILT, 90), call(Servo.ZOOM, 0),
        ])
        self.assertEqual(self.controller._channel_register(Servo.TILT), 0x36)

    def test_positions_initiales_stoppees_si_pan_echoue(self):
        with patch.object(self.controller, "set_angle", return_value=pan.PanResult.CIBLE_NON_ATTEINTE) as set_angle:
            self.assertIs(self.controller.reset_positions(), pan.PanResult.CIBLE_NON_ATTEINTE)
        set_angle.assert_called_once_with(Servo.PAN, 0, monitor=None)

    def test_interruption_invalide_la_position_et_stoppe_pan(self):
        def monitor():
            if self.rate:
                raise OSError("mesure indisponible")

        with self.assertRaises(OSError):
            self.controller.set_angle(Servo.PAN, 90, monitor=monitor)
        self.assertIsNone(Servo.PAN.angle)
        self.assertEqual(self.rate, 0.0)
        with self.assertRaises(RuntimeError):
            self.guard.state()

    def test_arret_batterie_conserve_position_pour_revenir_a_zero(self):
        result = self.controller.set_angle(Servo.PAN, 90, monitor=lambda: self.now < 0.5)
        self.assertIs(result, pan.PanResult.INTERROMPU)
        self.assertGreater(self.guard.state().angle, 20)
        self.assertEqual(self.rate, 0.0)
        self.assertIs(self.controller.set_angle(Servo.PAN, 0), pan.PanResult.TERMINE)
        self.assertLessEqual(abs(Servo.PAN.angle), pan.TARGET_TOLERANCE_DEG)
