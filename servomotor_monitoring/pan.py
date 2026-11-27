"""Suivi du déplacement signé de PAN et arrêt logiciel sur limite."""

import json
import os
from dataclasses import asdict, dataclass
from enum import Enum
from math import isfinite
from pathlib import Path
from struct import unpack
from tempfile import NamedTemporaryFile
from time import monotonic, sleep


PAN_LIMIT_DEG = 360.0
STOP_MARGIN_DEG = 15.0
STOP_DELAY_S = 0.06
SAMPLE_INTERVAL_S = 0.02
MAX_SAMPLE_GAP_S = 0.10
SETTLE_TIME_S = 0.20
MIN_MOVEMENT_DEG = 0.5
TARGET_TOLERANCE_DEG = 3.0


class PanResult(Enum):
    TERMINE = "TERMINE"
    INTERROMPU = "INTERROMPU"
    CIBLE_NON_ATTEINTE = "CIBLE_NON_ATTEINTE"
    LIMITE_HORAIRE = "LIMITE_HORAIRE"
    LIMITE_ANTIHORAIRE = "LIMITE_ANTIHORAIRE"


@dataclass(frozen=True)
class PanState:
    angle: float
    valid: bool
    blocked: int = 0


class MPU6050:
    # Monter le capteur sur la partie tournante, avec cet axe parallèle à PAN.
    AXIS = "Z"
    CLOCKWISE_SIGN = 1
    GYRO_REGISTER = {"X": 0x43, "Y": 0x45, "Z": 0x47}
    GYRO_SCALE = 32.8  # LSB/(°/s) pour la plage de ±1000 °/s.
    MODELS = {0x68: "MPU-6050", 0x70: "MPU-6500"}

    def __init__(self, bus, address: int):
        self.bus = bus
        self.address = address

    def identity(self) -> int:
        return self._transfer("lecture de WHO_AM_I", self.bus.read_byte_data, 0x75)

    def initialize(self) -> None:
        identity = self.identity()
        if identity not in self.MODELS:
            raise RuntimeError(f"Gyroscope non reconnu (WHO_AM_I={identity:#04x}).")
        self._transfer("réveil", self.bus.write_byte_data, 0x6B, 0x01)  # Horloge PLL.
        self._transfer("configuration du filtre", self.bus.write_byte_data, 0x1A, 0x03)
        self._transfer("configuration du gyroscope", self.bus.write_byte_data, 0x1B, 0x10)  # ±1000 °/s.
        sleep(0.10)

    def calibrate(self) -> float:
        self.initialize()
        samples = []
        for _ in range(15):
            samples.append(self.rate())
            sleep(SAMPLE_INTERVAL_S)
        if max(samples) - min(samples) > 3 or max(map(abs, samples)) > 15:
            raise RuntimeError("MPU6050 instable pendant la calibration. Immobilisez l’axe PAN.")
        return sum(samples) / len(samples)

    def rate(self) -> float:
        data = self._transfer("lecture des axes", self.bus.read_i2c_block_data, self.GYRO_REGISTER[self.AXIS], 2)
        rate = self.CLOCKWISE_SIGN * int.from_bytes(bytes(data), "big", signed=True) / self.GYRO_SCALE
        if abs(rate) >= 990:
            raise RuntimeError("Saturation du gyroscope. Position de PAN incertaine.")
        return rate

    def rates(self) -> tuple[float, float, float]:
        """Lit les trois axes bruts, sans appliquer le signe de correction de PAN."""
        data = self._transfer("lecture des axes", self.bus.read_i2c_block_data, self.GYRO_REGISTER["X"], 6)
        x, y, z = unpack(">hhh", bytes(data))
        return x / self.GYRO_SCALE, y / self.GYRO_SCALE, z / self.GYRO_SCALE

    def _transfer(self, step, operation, register, *args):
        try:
            return operation(self.address, register, *args)
        except OSError as exc:
            exc.add_note(f"Gyroscope à {self.address:#04x} — {step}, registre {register:#04x}.")
            raise


class PanGuard:
    def __init__(self, gyro: MPU6050, state_file: Path):
        self.gyro = gyro
        self.state_file = state_file

    def state(self) -> PanState:
        try:
            state = PanState(**json.loads(self.state_file.read_text(encoding="utf-8")))
            if (state.valid is not True or type(state.angle) not in (float, int)
                    or not isfinite(state.angle) or abs(state.angle) > PAN_LIMIT_DEG
                    or type(state.blocked) is not int or state.blocked not in (-1, 0, 1)):
                raise ValueError
        except (FileNotFoundError, TypeError, ValueError) as exc:
            raise RuntimeError("Position de PAN inconnue. Replacez PAN au repère puis lancez pan-reference.") from exc
        return state

    def _save(self, state: PanState) -> None:
        self.state_file.parent.mkdir(parents=True, exist_ok=True)
        with NamedTemporaryFile(mode="w", encoding="utf-8", dir=self.state_file.parent, delete=False) as temp:
            temporary_path = Path(temp.name)
            try:
                json.dump(asdict(state), temp)
                temp.flush()
                os.fsync(temp.fileno())
                os.replace(temporary_path, self.state_file)
                directory = os.open(self.state_file.parent, os.O_RDONLY | os.O_DIRECTORY)
                try:
                    os.fsync(directory)
                finally:
                    os.close(directory)
            finally:
                temporary_path.unlink(missing_ok=True)

    def reference(self, stop) -> None:
        self._save(PanState(0.0, False))
        stop()
        self.gyro.calibrate()
        self._save(PanState(0.0, True))

    def run(self, direction: int, duration: float, start, stop, *,
            target: float | None = None, monitor=None) -> PanResult:
        state = self.state()
        limit = PanResult.LIMITE_HORAIRE if direction > 0 else PanResult.LIMITE_ANTIHORAIRE
        if state.blocked == direction or direction * state.angle >= PAN_LIMIT_DEG - STOP_MARGIN_DEG:
            return limit

        stop()
        bias = self.gyro.calibrate()
        if monitor is not None and monitor() is False:
            return PanResult.INTERROMPU
        self._save(PanState(state.angle, False, state.blocked))
        angle = state.angle
        rate = 0.0
        last = 0.0

        def sample():
            nonlocal angle, rate, last
            next_rate = self.gyro.rate() - bias
            now = monotonic()
            elapsed = now - last
            if elapsed > MAX_SAMPLE_GAP_S:
                raise RuntimeError("Mesure du gyroscope trop tardive. Position de PAN incertaine.")
            angle += (rate + next_rate) * elapsed / 2
            rate, last = next_rate, now

        result = PanResult.TERMINE
        try:
            last = monotonic()
            start()
            started_at = monotonic()
            deadline = started_at + duration
            while True:
                sleep(min(SAMPLE_INTERVAL_S, max(0.0, deadline - monotonic())))
                sample()
                if monitor is not None and monitor() is False:
                    result = PanResult.INTERROMPU
                    break
                progress = direction * (angle - state.angle)
                if progress < -2:
                    raise RuntimeError("PAN tourne à l’envers. Vérifiez le sens du MPU6050 et du servo.")
                if monotonic() >= started_at + 0.35 and progress < MIN_MOVEMENT_DEG:
                    raise RuntimeError("Le MPU6050 ne confirme pas le mouvement de PAN.")
                remaining = PAN_LIMIT_DEG - direction * angle
                if remaining <= STOP_MARGIN_DEG + max(0.0, direction * rate) * STOP_DELAY_S:
                    result = limit
                    break
                if target is not None and direction * (target - angle) <= max(0.0, direction * rate) * SAMPLE_INTERVAL_S:
                    break
                if monotonic() >= deadline:
                    break
        finally:
            stop()

        settle_until = monotonic() + SETTLE_TIME_S
        while monotonic() < settle_until:
            sleep(SAMPLE_INTERVAL_S)
            sample()
            if result is PanResult.TERMINE and monitor is not None and monitor() is False:
                result = PanResult.INTERROMPU
        if abs(angle) > PAN_LIMIT_DEG or abs(rate) > 5:
            raise RuntimeError("PAN a dépassé la limite ou continue à tourner après la coupure du PWM.")
        if result is not PanResult.INTERROMPU and direction * (angle - state.angle) < MIN_MOVEMENT_DEG:
            raise RuntimeError("Le MPU6050 ne confirme pas le mouvement de PAN.")
        at_limit = result is limit or direction * angle >= PAN_LIMIT_DEG - STOP_MARGIN_DEG
        if at_limit and result is PanResult.TERMINE:
            result = limit
        self._save(PanState(angle, True, direction if at_limit else 0))
        if result is PanResult.TERMINE and target is not None and abs(target - angle) > TARGET_TOLERANCE_DEG:
            return PanResult.CIBLE_NON_ATTEINTE
        return result
