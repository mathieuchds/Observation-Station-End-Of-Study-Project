"""Diagnostic I²C des MPU-6050 et MPU-6500 sans commande des moteurs."""

import argparse
from fcntl import LOCK_EX, LOCK_NB, flock
from math import isfinite
from time import sleep

from .__main__ import report_error
from .pan import MPU6050


def main() -> int:
    parser = argparse.ArgumentParser(description="Détecter le MPU-6050 ou le MPU-6500 et afficher X, Y, Z en °/s.")
    parser.add_argument("--bus", type=int, default=1, help="numéro du bus I²C (défaut 1)")
    parser.add_argument("--address", type=lambda value: int(value, 0), choices=(0x68, 0x69), metavar="{0x68,0x69}",
                        help="adresse I²C à tester (par défaut 0x68 et 0x69)")
    parser.add_argument("--probe-only", action="store_true", help="lire uniquement l’identité du capteur")
    parser.add_argument("--samples", type=int, default=10, help="nombre de mesures par capteur (défaut 10)")
    parser.add_argument("--interval", type=float, default=0.25, help="pause entre les mesures en secondes")
    args = parser.parse_args()
    if args.bus < 0 or args.samples < 1 or not isfinite(args.interval) or args.interval < 0:
        parser.error("Utilisez un bus positif ou nul, au moins une mesure et un intervalle positif ou nul.")

    found = False
    try:
        from smbus2 import SMBus

        with SMBus(args.bus) as bus:
            if not args.probe_only:
                try:
                    flock(bus.fd, LOCK_EX | LOCK_NB)
                except BlockingIOError as exc:
                    raise RuntimeError("Bus occupé. Arrêtez l’automate avant de lire les axes.") from exc
            addresses = (args.address,) if args.address is not None else (0x68, 0x69)
            for address in addresses:
                gyro = MPU6050(bus, address)
                try:
                    identity = gyro.identity()
                except OSError as exc:
                    print(f"{address:#04x} — aucune réponse I²C ({exc})", flush=True)
                    continue
                model = MPU6050.MODELS.get(identity)
                print(f"{address:#04x} — WHO_AM_I={identity:#04x} ({model or 'capteur non reconnu'})", flush=True)
                if model is None:
                    continue
                found = True
                if args.probe_only:
                    continue
                gyro.initialize()
                for index in range(args.samples):
                    if index:
                        sleep(args.interval)
                    x, y, z = gyro.rates()
                    print(f"{index + 1:3d}  X={x:+7.2f}  Y={y:+7.2f}  Z={z:+7.2f} °/s", flush=True)
    except KeyboardInterrupt:
        return 130
    except (ImportError, OSError, RuntimeError) as exc:
        report_error(exc, f"Diagnostic MPU6050 impossible sur /dev/i2c-{args.bus} — {exc}")
        return 1
    return 0 if found else 1


if __name__ == "__main__":
    raise SystemExit(main())
