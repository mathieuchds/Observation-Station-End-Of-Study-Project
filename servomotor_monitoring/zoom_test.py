"""Test rapide du canal ZOOM avec python3 -m servomotor_monitoring.zoom_test."""

import argparse
import signal
from time import sleep

from .__main__ import interrupt, report_error
from .servo import Servo, ServoController


def main() -> int:
    parser = argparse.ArgumentParser(description="Tester directement ZOOM sur le PCA9685.")
    parser.parse_args()
    signal.signal(signal.SIGTERM, interrupt)
    try:
        with ServoController() as controller:
            controller.check()
            for angle in (90, 75, 105, 90):
                controller.set_angle(Servo.ZOOM, angle)
                print(f"ZOOM → {angle}°", flush=True)
                sleep(0.8)
    except KeyboardInterrupt as exc:
        report_error(exc, "Test ZOOM interrompu.")
        return 130
    except (ImportError, OSError, RuntimeError) as exc:
        report_error(exc, f"Test ZOOM impossible : {exc}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
