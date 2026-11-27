"""Mesure de la tension du pack LiPo 2S via l’entrée A3 de l’ADS1115."""

import argparse
import sys
from dataclasses import dataclass
from enum import Enum
from math import isfinite
from time import monotonic, sleep


I2C_BUS = 1
ADS1115_ADDRESS = 0x48  # ADDR relié à GND.
CONVERSION_REGISTER = 0x00
CONFIG_REGISTER = 0x01
CONVERSION_READY = 0x8000
# Conversion unique, AIN3/GND, ±4,096 V, 128 échantillons/s, comparateur désactivé.
ADS1115_CONFIG = 0xF383
VOLTS_PER_COUNT = 4.096 / 32768
R_TOP_OHMS = 10_000
R_BOTTOM_OHMS = 4_700
DIVIDER_GAIN = (R_TOP_OHMS + R_BOTTOM_OHMS) / R_BOTTOM_OHMS
CUTOFF_VOLTAGE = 7.0
MAX_PLAUSIBLE_PACK_VOLTAGE = 8.6


class BatteryStatus(Enum):
    NORMAL = 0
    ANORMAL = 1


@dataclass(frozen=True)
class BatteryReading:
    raw: int
    config: int

    @property
    def a3_voltage(self) -> float:
        return self.raw * VOLTS_PER_COUNT

    @property
    def pack_voltage(self) -> float:
        return max(self.a3_voltage, 0.0) * DIVIDER_GAIN

    @property
    def status(self) -> BatteryStatus:
        return BatteryStatus.ANORMAL if self.pack_voltage <= CUTOFF_VOLTAGE else BatteryStatus.NORMAL

    def describe(self) -> str:
        return (
            f"ADS1115 {ADS1115_ADDRESS:#04x} / I²C-{I2C_BUS} | config={self.config:#06x} | "
            f"brut={self.raw} (0x{self.raw & 0xffff:04x}) | A3={self.a3_voltage:.4f} V | "
            f"pack={self.pack_voltage:.3f} V (×{DIVIDER_GAIN:.4f}) | "
            f"coupure ≤ {CUTOFF_VOLTAGE:.2f} V (A3 ≤ {CUTOFF_VOLTAGE / DIVIDER_GAIN:.4f} V) | "
            f"max. plausible {MAX_PLAUSIBLE_PACK_VOLTAGE:.2f} V"
        )


def check_battery(*, debug: bool = False, startup: bool = False) -> BatteryStatus:
    """Signale une décharge, ou propage une erreur de mesure à l’automate."""
    reading = read_battery_measurement(prime=startup, debug=debug)
    status = reading.status
    if debug or status is BatteryStatus.ANORMAL:
        print(f"{reading.describe()} | {status.name}", file=sys.stderr, flush=True)
    return status


def read_battery_voltage() -> float:
    """Déclenche une conversion A3 et restitue la tension avant le pont diviseur."""
    return read_battery_measurement().pack_voltage


def read_battery_measurement(*, prime: bool = False, debug: bool = False) -> BatteryReading:
    """Relit la configuration effective et convertit le code signé de l’ADS1115."""
    from smbus2 import SMBus

    with SMBus(I2C_BUS) as bus:
        if prime:
            first = _convert_a3(bus)
            if debug:
                print(f"Amorçage : {first.describe()}", file=sys.stderr, flush=True)
        reading = _convert_a3(bus)

    # Quelques points négatifs sont possibles à zéro à cause de l’erreur d’offset.
    if reading.raw < -8 or reading.pack_voltage > MAX_PLAUSIBLE_PACK_VOLTAGE:
        raise RuntimeError(f"Tension batterie incohérente. {reading.describe()}")
    return reading


def _convert_a3(bus) -> BatteryReading:
    bus.write_i2c_block_data(ADS1115_ADDRESS, CONFIG_REGISTER, list(ADS1115_CONFIG.to_bytes(2, "big")))
    deadline = monotonic() + 0.1
    sleep(0.010)  # À 128 échantillons/s, laisser une période de conversion avant de vérifier OS.
    while True:
        config = int.from_bytes(bytes(bus.read_i2c_block_data(ADS1115_ADDRESS, CONFIG_REGISTER, 2)), "big")
        if (config & ~CONVERSION_READY) != (ADS1115_CONFIG & ~CONVERSION_READY):
            raise RuntimeError(f"Configuration ADS1115 inattendue (lue {config:#06x}, attendue {ADS1115_CONFIG:#06x}).")
        if config & CONVERSION_READY:
            break
        if monotonic() >= deadline:
            raise TimeoutError(f"Conversion ADS1115 non terminée (config={config:#06x}).")
        sleep(0.002)
    raw = int.from_bytes(bytes(bus.read_i2c_block_data(ADS1115_ADDRESS, CONVERSION_REGISTER, 2)),
                         "big", signed=True)
    return BatteryReading(raw, config)


def main() -> int:
    parser = argparse.ArgumentParser(description="Afficher la mesure détaillée du pack LiPo.")
    parser.add_argument("--samples", type=int, default=1, help="nombre de mesures")
    parser.add_argument("--interval", type=float, default=1.0, help="délai entre mesures en secondes")
    args = parser.parse_args()
    if args.samples < 1 or not isfinite(args.interval) or args.interval < 0:
        parser.error("Demandez au moins une mesure et un intervalle positif ou nul.")

    exit_code = 0
    try:
        for sample in range(args.samples):
            if sample:
                sleep(args.interval)
            reading = read_battery_measurement()
            print(f"{reading.describe()} | {reading.status.name}", flush=True)
            if reading.status is BatteryStatus.ANORMAL:
                exit_code = 2
    except KeyboardInterrupt:
        return 130
    except (ImportError, OSError, RuntimeError) as exc:
        print(f"Mesure ADS1115 impossible sur /dev/i2c-{I2C_BUS} à {ADS1115_ADDRESS:#04x} ({exc}).",
              file=sys.stderr)
        return 1

    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
