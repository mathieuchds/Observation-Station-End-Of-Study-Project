"""Point d’entrée de l’automate de la station."""

import argparse
import signal
import sys
from functools import partial

from servomotor_monitoring.__main__ import interrupt, report_error
from servomotor_monitoring.servo import ServoController

from .battery import ADS1115_ADDRESS, check_battery
from .station import run_station


def main(*, motor_test: bool = False) -> int:
    description = "Tester les trois moteurs de la station." if motor_test else "Lancer l’automate de contrôle de la station."
    parser = argparse.ArgumentParser(description=description)
    parser.add_argument("--interval", type=float, default=5.0,
                        help="intervalle entre contrôles batterie en secondes (défaut 5)")
    parser.add_argument("--battery-debug", action="store_true", help="afficher chaque mesure détaillée de l’ADS1115")
    parser.add_argument("--zoom-speed", type=float,
                        help="limiter la progression de ZOOM en °/s (par défaut, consigne directe)")
    parser.add_argument("--pca-address", type=lambda value: int(value, 0), default=0x40,
                        help="adresse individuelle du PCA9685 (défaut 0x40)")
    parser.add_argument("--gyro-address", type=lambda value: int(value, 0), default=0x68,
                        help="adresse du MPU6050 (défaut 0x68)")
    if not motor_test:
        positioning = parser.add_mutually_exclusive_group()
        positioning.add_argument("--center-tilt", action="store_true", help="maintenir TILT à 90° pour le montage")
        positioning.add_argument("--init-zoom", action="store_true", help="maintenir ZOOM à son origine de 0°")
        positioning.add_argument("--initial-positions", action="store_true", help="placer PAN à 0°, TILT à 90° et ZOOM à 0°")
        parser.set_defaults(speed=None)
    else:
        parser.set_defaults(center_tilt=False, init_zoom=False, initial_positions=False)
        parser.add_argument("--speed", type=float,
                            help="vitesse en °/s pour les essais PAN et TILT")
    args = parser.parse_args()
    if args.pca_address == ADS1115_ADDRESS:
        parser.error(f"L’adresse {ADS1115_ADDRESS:#04x} est utilisée par l’ADS1115.")
    for signum in (signal.SIGTERM, signal.SIGHUP):
        signal.signal(signum, interrupt)
    try:
        with ServoController(address=args.pca_address, gyro_address=args.gyro_address) as controller:
            return run_station(controller, sys.stdin.fileno(), interval=args.interval,
                               motor_test=motor_test,
                               motor_speed=args.speed,
                               zoom_speed=args.zoom_speed,
                               center_tilt=args.center_tilt, init_zoom=args.init_zoom,
                               initial_positions=args.initial_positions,
                               battery_check=partial(check_battery, debug=args.battery_debug),
                               startup_battery_check=partial(check_battery, debug=args.battery_debug, startup=True))
    except KeyboardInterrupt as exc:
        report_error(exc, "Automate arrêté.")
        return 130
    except (ImportError, OSError, RuntimeError, ValueError) as exc:
        report_error(exc, f"Erreur de l’automate : {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
