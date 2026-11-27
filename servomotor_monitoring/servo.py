"""Pilotage et lecture du signal PWM d'un PCA9685 dédié aux servos."""

from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum
from fcntl import LOCK_EX, LOCK_NB, flock
from math import isfinite
from pathlib import Path
from time import sleep

from .pan import MPU6050, PAN_LIMIT_DEG, TARGET_TOLERANCE_DEG, PanGuard, PanResult


class Servo(Enum):
    ZOOM = 0
    PAN = 1
    TILT = 12

    def __init__(self, _channel: int):
        self.angle: float | None = None


MAX_ANGLE = 180
ZOOM_ORIGIN = 0
PAN_POSITION_POWER = 0.25
PAN_POSITION_TIMEOUT = 8.0


class Direction(Enum):
    HORAIRE = 1
    ANTIHORAIRE = -1


@dataclass(frozen=True)
class Calibration:
    min_us: int = 1000
    neutral_us: int = 1500
    max_us: int = 2000
    inverted: bool = False


CALIBRATIONS = {
    Servo.ZOOM: Calibration(),
    Servo.PAN: Calibration(),
    Servo.TILT: Calibration(),
}

MODE1 = 0x00
MODE2 = 0x01
LED0_ON_L = 0x06
PRE_SCALE = 0xFE
AUTO_INCREMENT = 0x20
SLEEP = 0x10
FULL_OUTPUT = 0x10
OSCILLATOR_HZ = 25_000_000
PWM_STEPS = 4096
PWM_HZ = 50
PRESCALE = round(OSCILLATOR_HZ / (PWM_STEPS * PWM_HZ)) - 1


class ServoController:
    """Ouvre le bus à l'entrée du bloc with et coupe les PWM pilotés à sa sortie."""

    def __init__(self, bus: int = 1, address: int = 0x40, *, gyro_address: int = 0x68,
                 pan_state_file: Path | None = None):
        if bus < 0:
            raise ValueError("Le numéro du bus I²C doit être positif ou nul.")
        if not 0x40 <= address <= 0x77 or address == 0x70:
            raise ValueError("L’adresse du PCA9685 doit être comprise entre 0x40 et 0x77, hors All Call 0x70.")
        if gyro_address not in (0x68, 0x69):
            raise ValueError("L’adresse du MPU6050 doit être 0x68 ou 0x69.")
        if gyro_address == address:
            raise ValueError("Le PCA9685 et le gyroscope doivent avoir des adresses I²C distinctes.")
        self.bus = bus
        self.address = address
        self.gyro_address = gyro_address
        state_dir = Path.home() / ".local/state/servomotor_monitoring"
        self.pan_state_file = pan_state_file or state_dir / f"pan-{bus}-{address:02x}.json"
        self._device = None
        self._configured = False

    def __enter__(self):
        from smbus2 import SMBus

        if self._device is not None:
            raise RuntimeError("Ce contrôleur est déjà ouvert.")
        self._device = SMBus(self.bus)
        return self

    def __exit__(self, exc_type, exc, traceback):
        try:
            if self._configured:
                failure = None
                for servo in Servo:
                    try:
                        self._disable(servo)
                    except OSError as error:
                        failure = error
                if failure is not None:
                    if exc is None:
                        raise failure
                    exc.add_note(f"Échec de la coupure PWM sur le bus I²C : {failure}")
        finally:
            self._configured = False
            self._device.close()
            self._device = None

    def check(self) -> tuple[int, int]:
        """Lit MODE1 et PRE_SCALE pour vérifier la réponse de la carte."""
        return self._read(MODE1), self._read(PRE_SCALE)

    def group_addresses(self) -> dict[str, tuple[int, bool]]:
        """Lit les adresses de groupe sur 7 bits et leur état d’activation."""
        mode = self._read(MODE1)
        groups = ("SUBADR1", "SUBADR2", "SUBADR3", "ALLCALL")
        return {
            name: (self._read(0x02 + offset) >> 1, bool(mode & (0x08 >> offset)))
            for offset, name in enumerate(groups)
        }

    def status(self) -> dict[Servo, str]:
        """Lit les sorties programmées sur la carte, sans retour mécanique."""
        mode, prescale = self.check()
        return {servo: self._output_status(servo, mode, prescale) for servo in Servo}

    def output_status(self, servo: Servo) -> str:
        """Relit le PWM programmé pour un axe."""
        return self._output_status(servo, *self.check())

    def _output_status(self, servo: Servo, mode: int, prescale: int) -> str:
        register = self._channel_register(servo)
        if mode & AUTO_INCREMENT:
            on_low, on_high, off_low, off_high = self._device.read_i2c_block_data(self.address, register, 4)
        else:
            on_low, on_high, off_low, off_high = (
                self._read(register + offset) for offset in range(4)
            )
        if mode & SLEEP or off_high & FULL_OUTPUT:
            return "PWM désactivé"
        if on_high & FULL_OUTPUT:
            return "sortie active en continu"
        on_tick = on_low | ((on_high & 0x0F) << 8)
        off_tick = off_low | ((off_high & 0x0F) << 8)
        ticks = (off_tick - on_tick) % PWM_STEPS
        width_us = ticks * (prescale + 1) * 1_000_000 / OSCILLATOR_HZ
        return f"impulsion programmée ≈ {width_us:.0f} µs"

    def move(self, servo: Servo, power: float, direction: Direction, *,
             duration: float = 0.5) -> PanResult | None:
        """Surveille PAN pendant duration secondes ou fixe la cible de ZOOM/TILT."""
        if not isinstance(servo, Servo) or not isinstance(direction, Direction):
            raise TypeError("Les arguments servo et direction doivent être des membres de leurs enums.")
        if not isfinite(power) or not 0 <= power <= 100:
            raise ValueError("La puissance doit être comprise entre 0 et 100 %.")
        if power == 0:
            self.stop(servo)
            return PanResult.TERMINE if servo is Servo.PAN else None

        fraction = direction.value * power / 100
        if servo is Servo.PAN:
            if not isfinite(duration) or duration <= 0:
                raise ValueError("La durée de rotation de PAN doit être finie et strictement positive.")
            self._lock_bus()
            servo.angle = None
            guard = self._pan_guard()
            result = guard.run(
                direction.value, duration,
                start=lambda: self._set_output(Servo.PAN, fraction),
                stop=lambda: self._disable(Servo.PAN),
            )
            servo.angle = guard.state().angle
            return result
        self.set_angle(servo, (1 + fraction) * MAX_ANGLE / 2)
        return None

    def reference_pan(self) -> None:
        """Enregistre 0° après placement manuel au repère physique."""
        self._lock_bus()
        Servo.PAN.angle = None
        self._pan_guard().reference(lambda: self._disable(Servo.PAN))
        Servo.PAN.angle = 0.0

    def pan_position(self) -> float:
        """Renvoie la dernière position signée et validée, en degrés."""
        Servo.PAN.angle = None
        angle = self._pan_guard().state().angle
        Servo.PAN.angle = angle
        return angle

    def _pan_guard(self) -> PanGuard:
        return PanGuard(MPU6050(self._device, self.gyro_address), self.pan_state_file)

    def set_angle(self, servo: Servo, angle: float, *,
                  monitor: Callable[[], bool | None] | None = None) -> PanResult | None:
        """Commande un angle absolu. PAN utilise le gyroscope et renvoie son résultat."""
        if not isinstance(servo, Servo):
            raise TypeError("Le moteur doit être un membre de Servo.")
        if servo is Servo.PAN:
            if not isfinite(angle) or not -PAN_LIMIT_DEG <= angle <= PAN_LIMIT_DEG:
                raise ValueError(f"L’angle de PAN doit être dans la plage ±{PAN_LIMIT_DEG:g}°.")
            self._lock_bus()
            return self._position_pan(angle, monitor)
        if not isfinite(angle) or not 0 <= angle <= MAX_ANGLE:
            raise ValueError(f"L’angle doit être compris entre 0° et {MAX_ANGLE}°.")
        servo.angle = None
        self._set_output(servo, 2 * angle / MAX_ANGLE - 1)
        servo.angle = angle
        return None

    def center_tilt(self) -> None:
        """Maintient TILT à sa consigne centrale pendant le montage du palonnier."""
        self.set_angle(Servo.TILT, 90)

    def initialize_zoom(self) -> None:
        """Place ZOOM à son origine mécanique."""
        self.set_angle(Servo.ZOOM, ZOOM_ORIGIN)

    def reset_positions(self, *, monitor: Callable[[], bool | None] | None = None) -> PanResult:
        """Ramène PAN à son zéro, puis place TILT et ZOOM à leur origine."""
        result = self.set_angle(Servo.PAN, 0, monitor=monitor)
        if result is PanResult.TERMINE:
            self.center_tilt()
            self.initialize_zoom()
        return result

    def _position_pan(self, target: float, monitor: Callable[[], bool | None] | None) -> PanResult:
        guard = self._pan_guard()
        position = self.pan_position()
        for _ in range(3):
            error = target - position
            if abs(error) <= TARGET_TOLERANCE_DEG:
                return PanResult.TERMINE
            direction = 1 if error > 0 else -1
            Servo.PAN.angle = None
            result = guard.run(
                direction, PAN_POSITION_TIMEOUT,
                start=lambda: self._set_output(Servo.PAN, direction * PAN_POSITION_POWER),
                stop=lambda: self._disable(Servo.PAN),
                target=target, monitor=monitor,
            )
            position = guard.state().angle
            Servo.PAN.angle = position
            if result is not PanResult.CIBLE_NON_ATTEINTE:
                return result
        return PanResult.CIBLE_NON_ATTEINTE

    def _set_output(self, servo: Servo, fraction: float) -> None:
        calibration = CALIBRATIONS[servo]
        if calibration.inverted:
            fraction = -fraction
        limit = calibration.max_us if fraction >= 0 else calibration.min_us
        width_us = calibration.neutral_us + (limit - calibration.neutral_us) * abs(fraction)
        ticks = round(width_us * OSCILLATOR_HZ / ((PRESCALE + 1) * 1_000_000))

        if not self._configured:
            self._configure()
        self._device.write_i2c_block_data(
            self.address, self._channel_register(servo), [0, 0, ticks & 0xFF, ticks >> 8]
        )

    def stop(self, servo: Servo) -> None:
        """Coupe le PWM du canal sans modifier la fréquence du PCA9685."""
        self._lock_bus()
        self._disable(servo)

    @staticmethod
    def _channel_register(servo: Servo) -> int:
        return LED0_ON_L + 4 * servo.value

    def _read(self, register: int) -> int:
        if self._device is None:
            raise RuntimeError("Ouvrez le contrôleur avec with ServoController(...).")
        try:
            return self._device.read_byte_data(self.address, register)
        except OSError as exc:
            exc.add_note(f"PCA9685 à {self.address:#04x} — lecture du registre {register:#04x}.")
            raise

    def _write(self, register: int, value: int) -> None:
        try:
            self._device.write_byte_data(self.address, register, value)
        except OSError as exc:
            exc.add_note(f"PCA9685 à {self.address:#04x} — écriture du registre {register:#04x}.")
            raise

    def _disable(self, servo: Servo) -> None:
        self._write(self._channel_register(servo) + 3, FULL_OUTPUT)

    def _lock_bus(self) -> None:
        if self._device is None:
            raise RuntimeError("Ouvrez le contrôleur avec with ServoController(...).")
        try:
            flock(self._device.fd, LOCK_EX | LOCK_NB)
        except BlockingIOError as exc:
            raise RuntimeError(f"Une commande est déjà en cours sur /dev/i2c-{self.bus}.") from exc

    def _configure(self) -> None:
        self._lock_bus()
        self._configured = True
        for servo in Servo:
            self._disable(servo)
        self._write(MODE1, AUTO_INCREMENT | SLEEP)
        self._write(PRE_SCALE, PRESCALE)
        self._write(MODE2, 0x04)  # Sorties totem-pole, mise à jour à la condition STOP.
        for servo in Servo:
            self._disable(servo)
        self._write(MODE1, AUTO_INCREMENT)
        sleep(0.0005)
