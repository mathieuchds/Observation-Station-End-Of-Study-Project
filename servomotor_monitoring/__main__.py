"""Commandes de diagnostic et de pilotage depuis le terminal."""

import argparse
import signal
import sys
from math import isfinite
from time import sleep

from .pan import PAN_LIMIT_DEG, PanResult
from .servo import MAX_ANGLE, Direction, Servo, ServoController


def main() -> int:
    parser = argparse.ArgumentParser(description="Piloter et diagnostiquer trois servos sur un PCA9685.")
    parser.add_argument("--bus", type=int, default=1, help="numéro du bus I²C (défaut 1)")
    parser.add_argument("--address", type=lambda value: int(value, 0), default=0x40,
                        help="adresse I²C individuelle (défaut 0x40)")
    parser.add_argument("--gyro-address", type=lambda value: int(value, 0), default=0x68,
                        help="adresse I²C du MPU6050 (défaut 0x68)")
    commands = parser.add_subparsers(dest="command", required=True)
    check = commands.add_parser("check", help="vérifier la réponse I²C sans modifier les sorties")
    check.add_argument("--addresses", action="store_true", help="afficher les adresses de groupe du PCA9685")
    status = commands.add_parser("status", help="lire le PWM programmé sur chaque canal")
    status.add_argument("--watch", action="store_true", help="relire les canaux toutes les 250 ms")
    move = commands.add_parser("move", help="commander la vitesse de PAN ou la course de ZOOM/TILT")
    move.add_argument("servo", choices=[servo.name for servo in Servo])
    move.add_argument("power", type=float, help="consigne de vitesse ou de demi-course de 0 à 100 %%")
    move.add_argument("direction", choices=[direction.name for direction in Direction])
    move.add_argument("--duration", type=float, default=0.5, help="durée en secondes (défaut 0,5)")
    position = commands.add_parser("position", help="commander un angle absolu")
    position.add_argument("servo", choices=[servo.name for servo in Servo])
    position.add_argument("angle", type=float, help=f"0 à {MAX_ANGLE}° pour ZOOM/TILT, ±{PAN_LIMIT_DEG:g}° pour PAN")
    position.add_argument("--duration", type=float, default=1.0, help="maintien de ZOOM/TILT en secondes (défaut 1)")
    stop = commands.add_parser("stop", help="couper le PWM d'un servo")
    stop.add_argument("servo", choices=[servo.name for servo in Servo])
    commands.add_parser("pan-reference", help="enregistrer 0° une fois PAN placé au repère et immobile")
    commands.add_parser("pan-position", help="afficher la position signée enregistrée de PAN")
    args = parser.parse_args()

    if args.command in {"move", "position"}:
        if not isfinite(args.duration) or args.duration <= 0:
            parser.error("La durée doit être finie et strictement positive.")
        if args.command == "position":
            low, high = (-PAN_LIMIT_DEG, PAN_LIMIT_DEG) if args.servo == "PAN" else (0, MAX_ANGLE)
            if not isfinite(args.angle) or not low <= args.angle <= high:
                position.error(f"L’angle doit être compris entre {low:g}° et {high:g}°.")
        signal.signal(signal.SIGTERM, interrupt)

    try:
        with ServoController(bus=args.bus, address=args.address, gyro_address=args.gyro_address) as controller:
            if args.command == "check":
                mode, prescale = controller.check()
                print(f"Réponse I²C sur /dev/i2c-{args.bus} à 0x{args.address:02x} "
                      f"(MODE1=0x{mode:02x}, PRE_SCALE=0x{prescale:02x}).")
                if args.addresses:
                    for name, (address, enabled) in controller.group_addresses().items():
                        print(f"{name} {address:#04x} — {'actif' if enabled else 'inactif'}")
            elif args.command == "status":
                while True:
                    states = controller.status()
                    print(" | ".join(f"{servo.name} [{servo.value}] {state}"
                                     for servo, state in states.items()), flush=True)
                    if not args.watch:
                        break
                    sleep(0.25)
            elif args.command == "stop":
                controller.stop(Servo[args.servo])
            elif args.command == "position":
                result = controller.set_angle(Servo[args.servo], args.angle)
                if result is None:
                    sleep(args.duration)
                else:
                    print(f"{result.name} — PAN ≈ {Servo.PAN.angle:.1f}°")
                    return 0 if result is PanResult.TERMINE else 2
            elif args.command == "pan-reference":
                controller.reference_pan()
                print("Référence PAN enregistrée à 0°.")
            elif args.command == "pan-position":
                print(f"Position PAN enregistrée ≈ {controller.pan_position():+.1f}°")
            else:
                result = controller.move(
                    Servo[args.servo], args.power, Direction[args.direction], duration=args.duration
                )
                if result is not None:
                    print(result.value)
                elif args.power:
                    sleep(args.duration)
    except KeyboardInterrupt as exc:
        report_error(exc, "Commande interrompue.")
        return 130
    except (ImportError, OSError, ValueError, RuntimeError) as exc:
        report_error(exc, f"Erreur sur /dev/i2c-{args.bus} — {exc}")
        return 1
    return 0


def interrupt(_signum, _frame):
    raise KeyboardInterrupt


def report_error(exc: BaseException, message: str) -> None:
    print(message, file=sys.stderr)
    for note in getattr(exc, "__notes__", ()):
        print(note, file=sys.stderr)


if __name__ == "__main__":
    raise SystemExit(main())
