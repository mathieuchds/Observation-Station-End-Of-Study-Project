"""Essais de l’automate sans Raspberry Pi ni servomoteur."""

from unittest import TestCase
from unittest.mock import ANY, Mock, call, patch

from servomotor_monitoring.pan import PanResult
from servomotor_monitoring.servo import Servo

from . import station
from .battery import BatteryStatus


class StationTest(TestCase):
    def setUp(self):
        self.now = 0.0
        for servo in Servo:
            self.enterContext(patch.object(servo, "angle", None))
        self.controller = Mock()
        self.controller.set_angle.side_effect = self.set_angle
        self.controller.pan_position.side_effect = lambda: Servo.PAN.angle
        self.sleep = self.enterContext(patch.object(station, "sleep", side_effect=self.advance))
        self.read = self.enterContext(patch.object(station, "read"))
        self.select = self.enterContext(patch.object(station, "select", side_effect=self.wait))
        self.enterContext(patch.object(station, "monotonic", side_effect=lambda: self.now))
        self.enterContext(patch.object(station, "print", create=True))

    def set_angle(self, servo, angle, **kwargs):
        servo.angle = angle
        return PanResult.TERMINE if servo is Servo.PAN else None

    def advance(self, duration):
        self.now += duration

    def wait(self, inputs, _writes, _errors, timeout):
        delay, readable = next(self.events)
        self.assertLessEqual(delay, timeout)
        self.now += delay
        return (inputs.copy() if readable else [], [], [])

    def test_angle_zoom_et_coupure_prioritaire(self):
        self.events = iter([(1, True), (1, True), (3, False), (5, True)])
        self.read.side_effect = [b"commande inconnue\n0 9", b"0\n0 180\n"]
        checks = []

        def battery_check():
            checks.append(self.now)
            return BatteryStatus.NORMAL if self.now < 10 else BatteryStatus.ANORMAL

        result = station.run_station(self.controller, 0, battery_check=battery_check)

        self.assertEqual(result, 2)
        self.assertEqual(checks, [0, 5, 10])
        self.assertEqual(self.controller.stop.call_args_list, [call(servo) for servo in Servo])
        self.assertEqual(self.controller.set_angle.call_args_list, [
            call(Servo.ZOOM, 90), call(Servo.ZOOM, 180), call(Servo.PAN, 0),
        ])
        self.assertEqual(self.read.call_count, 2)
        self.controller.center_tilt.assert_called_once()
        self.controller.initialize_zoom.assert_called_once()
        self.sleep.assert_called_once()

    def test_batterie_basse_avant_activation(self):
        result = station.run_station(self.controller, 0, battery_check=lambda: BatteryStatus.ANORMAL)

        self.assertEqual(result, 2)
        self.controller.set_angle.assert_not_called()
        self.controller.center_tilt.assert_not_called()
        self.select.assert_not_called()

    def test_controle_batterie_sans_terminal(self):
        self.events = iter([(0, True), (5, False)])
        self.read.return_value = b""
        battery_check = Mock(side_effect=[BatteryStatus.NORMAL, BatteryStatus.ANORMAL])
        result = station.run_station(self.controller, 0, battery_check=battery_check)

        self.assertEqual(result, 2)
        self.read.assert_called_once()
        self.controller.set_angle.assert_called_once_with(Servo.PAN, 0)
        self.controller.initialize_zoom.assert_called_once()

    def test_coupure_si_le_controle_batterie_echoue(self):
        self.events = iter([(2, False)])
        battery_check = Mock(side_effect=[BatteryStatus.NORMAL, OSError("mesure indisponible")])
        with self.assertRaises(OSError):
            station.run_station(self.controller, 0, interval=2, battery_check=battery_check)

        self.controller.set_angle.assert_not_called()

    def test_coupure_sur_interruption(self):
        self.select.side_effect = KeyboardInterrupt
        with self.assertRaises(KeyboardInterrupt):
            station.run_station(self.controller, 0, battery_check=lambda: BatteryStatus.NORMAL)

        self.controller.set_angle.assert_not_called()

    def test_trois_moteurs_et_coupure_sur_fin_du_terminal(self):
        Servo.PAN.angle = 0
        self.events = iter([(1, True), (1, True)])
        self.read.side_effect = [b"0 45\n1\n2\n0 0\n1\n2\n", b""]
        result = station.run_station(
            self.controller, 0, motor_test=True, motor_speed=1000, battery_check=lambda: BatteryStatus.NORMAL,
        )

        self.assertEqual(result, 0)
        angles_by_servo = {servo: [] for servo in Servo}
        for event in self.controller.set_angle.call_args_list:
            servo, angle = event.args
            angles_by_servo[servo].append(angle)
        self.assertEqual(angles_by_servo[Servo.TILT], list(range(90, 111, 2)) + list(range(108, 89, -2)))
        self.assertEqual(angles_by_servo[Servo.PAN], list(range(10, 91, 10)) + list(range(80, -1, -10)))
        self.assertEqual(angles_by_servo[Servo.ZOOM], [45, 0])
        self.controller.center_tilt.assert_not_called()

    def test_vitesse_espace_les_consigne_tilt(self):
        for speed in (10, 40):
            self.now = 0.0
            station._move_test_axis(self.controller, Servo.TILT, 90, 90, 110, speed, lambda: True)
            self.assertAlmostEqual(self.now, 20 / speed)

    def test_zoom_seul_valide_angle_et_accepte_une_rampe(self):
        self.events = iter([(0, True), (0, True)])
        self.read.side_effect = [b"0\n0 -1\n0 181\n0 NaN\n0 10 en trop\n1\n2\n0 6\n", b""]
        result = station.run_station(
            self.controller, 0, motor_test=True, zoom_speed=10, battery_check=lambda: BatteryStatus.NORMAL,
        )
        self.assertEqual(result, 0)
        self.assertEqual(self.controller.set_angle.call_args_list, [
            call(Servo.ZOOM, 0), call(Servo.ZOOM, 2), call(Servo.ZOOM, 4), call(Servo.ZOOM, 6),
        ])
        self.assertAlmostEqual(self.now, 0.6)

    def test_coupure_batterie_pendant_pan(self):
        Servo.PAN.angle = 0
        self.events = iter([(1, True)])
        self.read.return_value = b"1\n2\n"

        def rotate(servo, angle, *, monitor=None):
            if monitor is not None:
                self.now = 5
                self.assertFalse(monitor())
                return PanResult.INTERROMPU
            return self.set_angle(servo, angle)

        self.controller.set_angle.side_effect = rotate
        battery_check = Mock(side_effect=[BatteryStatus.NORMAL, BatteryStatus.ANORMAL])
        self.assertEqual(station.run_station(
            self.controller, 0, motor_test=True, motor_speed=30, battery_check=battery_check,
        ), 2)
        self.assertEqual(self.controller.set_angle.call_args_list, [
            call(Servo.PAN, 10, monitor=ANY), call(Servo.PAN, 0),
        ])
        self.controller.center_tilt.assert_called_once()
        self.controller.initialize_zoom.assert_called_once()

    def test_centrage_tilt_et_coupure_a_la_sortie(self):
        self.events = iter([(1, True), (1, True)])
        self.read.side_effect = [b"0\n1\n2\n", b""]

        self.assertEqual(station.run_station(
            self.controller, 0, center_tilt=True, battery_check=lambda: BatteryStatus.NORMAL,
        ), 0)
        self.controller.center_tilt.assert_called_once_with()
        self.controller.output_status.assert_called_once_with(Servo.TILT)
        self.controller.set_angle.assert_not_called()

    def test_initialisation_zoom_seul(self):
        self.events = iter([(1, True), (1, True)])
        self.read.side_effect = [b"0\n", b""]
        result = station.run_station(
            self.controller, 0, init_zoom=True, battery_check=lambda: BatteryStatus.NORMAL,
        )
        self.assertEqual(result, 0)
        self.controller.initialize_zoom.assert_called_once_with()
        self.controller.center_tilt.assert_not_called()
        self.controller.set_angle.assert_not_called()

    def test_retour_initial_surveille_la_batterie_pendant_pan(self):
        def reset(*, monitor):
            self.now = 5
            self.assertFalse(monitor())
            return PanResult.INTERROMPU

        self.controller.reset_positions.side_effect = reset
        battery_check = Mock(side_effect=[BatteryStatus.NORMAL, BatteryStatus.ANORMAL])
        self.assertEqual(station.run_station(self.controller, 0, initial_positions=True, battery_check=battery_check), 2)
        self.controller.center_tilt.assert_called_once()

    def test_batterie_basse_ramene_zoom_et_tilt_si_pan_est_inconnu(self):
        self.events = iter([(5, False)])
        self.controller.set_angle.side_effect = RuntimeError("PAN non référencé")
        battery_check = Mock(side_effect=[BatteryStatus.NORMAL, BatteryStatus.ANORMAL])
        self.assertEqual(station.run_station(self.controller, 0, battery_check=battery_check), 2)
        self.controller.set_angle.assert_called_once_with(Servo.PAN, 0)
        self.controller.initialize_zoom.assert_called_once()
        self.controller.center_tilt.assert_called_once()
        self.sleep.assert_called_once()
