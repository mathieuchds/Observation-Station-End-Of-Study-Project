"""Cycle de fonctionnement de l’automate de la station."""

from collections.abc import Callable
from math import ceil, isfinite
from os import read
from select import select
from time import monotonic, sleep

from servomotor_monitoring.pan import PanResult
from servomotor_monitoring.servo import MAX_ANGLE, ZOOM_ORIGIN, Servo, ServoController

from .battery import BatteryStatus, check_battery


MOTOR_TEST_COMMANDS = {
    b"1": (Servo.PAN, 0, 90),
    b"2": (Servo.TILT, 90, 110),
}


def _move_test_axis(controller: ServoController, servo: Servo, current: float | None,
                    origin: float, target: float, speed: float,
                    monitor: Callable[[], bool]) -> PanResult | None:
    if current is None:
        controller.set_angle(servo, origin)
        current = origin
    distance = target - current
    # Les pas de PAN doivent dépasser sa tolérance de position de ±3°.
    max_step = 10.0 if servo is Servo.PAN else 2.0
    steps = max(1, ceil(abs(distance) / max_step))
    spacing = abs(distance) / steps / speed
    result = None
    for index in range(1, steps + 1):
        deadline = monotonic() + spacing
        while monitor():
            remaining = deadline - monotonic()
            if remaining <= 0:
                break
            sleep(min(remaining, 0.05))
        else:
            return PanResult.INTERROMPU
        angle = target if index == steps else current + distance * index / steps
        if servo is Servo.PAN:
            result = controller.set_angle(servo, angle, monitor=monitor)
            if result is not PanResult.TERMINE:
                return result
        else:
            controller.set_angle(servo, angle)
    return result


def _park_after_low_battery(controller: ServoController) -> None:
    """Positionne les axes fixes, même si le zéro de PAN est indisponible."""
    controller.center_tilt()
    controller.initialize_zoom()
    try:
        result = controller.set_angle(Servo.PAN, 0)
    except (OSError, RuntimeError) as exc:
        print(f"Retour de PAN impossible : {exc}", flush=True)
    else:
        if result is not PanResult.TERMINE:
            print(f"Retour de PAN incomplet ({result.name}).", flush=True)
    sleep(1.0)  # Laisser les servos positionnels atteindre leur consigne avant la coupure PWM.


def run_station(controller: ServoController, stdin_fd: int, *,
                interval: float = 5.0,
                motor_test: bool = False, center_tilt: bool = False, initial_positions: bool = False,
                init_zoom: bool = False,
                motor_speed: float | None = None,
                zoom_speed: float | None = None,
                battery_check: Callable[[], BatteryStatus] | None = None,
                startup_battery_check: Callable[[], BatteryStatus] | None = None) -> int:
    """Autorise les déplacements jusqu’à un défaut batterie ou à l’arrêt."""
    if not isfinite(interval) or interval <= 0:
        raise ValueError("L’intervalle de contrôle doit être fini et strictement positif.")
    for speed in (motor_speed, zoom_speed):
        if speed is not None and (not isfinite(speed) or speed <= 0):
            raise ValueError("Indiquez une vitesse finie et strictement positive.")

    controller.check()
    for servo in Servo:
        controller.stop(servo)
    if battery_check is None:
        battery_check = check_battery
        if startup_battery_check is None:
            startup_battery_check = lambda: check_battery(startup=True)
    status = (startup_battery_check or battery_check)()
    if status is not BatteryStatus.NORMAL:
        print(f"Défaut batterie ({status}) au démarrage. Déplacements bloqués.", flush=True)
        return 2
    next_check = monotonic() + interval

    positioning_only = center_tilt or init_zoom or initial_positions
    prompt = "0 <angle> pour ZOOM"
    if motor_test:
        prompt += ", 1 pour PAN, 2 pour TILT"
    pending = b""
    inputs = [stdin_fd]

    def monitor_battery() -> bool:
        nonlocal status, next_check
        if status is BatteryStatus.NORMAL and monotonic() >= next_check:
            status = battery_check()
            next_check = monotonic() + interval
        return status is BatteryStatus.NORMAL

    if initial_positions:
        result = controller.reset_positions(monitor=monitor_battery)
        if status is BatteryStatus.NORMAL:
            if result is not PanResult.TERMINE:
                raise RuntimeError(f"Retour au zéro de PAN interrompu ({result.name}).")
            print("Positions initiales commandées. Ctrl+C pour arrêter.", flush=True)
    elif center_tilt:
        controller.center_tilt()
        print(f"TILT, canal {Servo.TILT.value}, consigne 90° : {controller.output_status(Servo.TILT)}. "
              "Ctrl+C pour arrêter.", flush=True)
    elif init_zoom:
        controller.initialize_zoom()
        print(f"ZOOM maintenu à {ZOOM_ORIGIN}°. Ctrl+C pour arrêter.", flush=True)
    else:
        print(f"Tapez {prompt}, puis Entrée.", flush=True)

    while status is BatteryStatus.NORMAL:
        readable, _, _ = select(inputs, [], [], max(0.0, next_check - monotonic()))
        if not monitor_battery():
            break
        if not readable:
            continue
        chunk = read(stdin_fd, 4096)
        if not chunk:
            if motor_test or positioning_only:
                return 0
            inputs.clear()
            continue
        lines = (pending + chunk).split(b"\n")
        pending = lines.pop()
        for line in lines:
            fields = line.split()
            if positioning_only or not fields:
                continue
            if not monitor_battery():
                break
            if fields[0] == b"0":
                try:
                    angle = float(fields[1]) if len(fields) == 2 else float("nan")
                except ValueError:
                    angle = float("nan")
                if not 0 <= angle <= MAX_ANGLE:
                    print(f"ZOOM : tapez 0 suivi d’un angle de 0 à {MAX_ANGLE}°.", flush=True)
                    continue
                if zoom_speed is None:
                    controller.set_angle(Servo.ZOOM, angle)
                elif _move_test_axis(
                    controller, Servo.ZOOM, Servo.ZOOM.angle, ZOOM_ORIGIN, angle, zoom_speed, monitor_battery,
                ) is PanResult.INTERROMPU:
                    break
                print(f"ZOOM → {angle:g}°", flush=True)
                continue
            command = MOTOR_TEST_COMMANDS.get(fields[0]) if motor_test and len(fields) == 1 else None
            if command is None:
                continue
            if motor_speed is None:
                print("Relancez le test avec --speed pour commander PAN et TILT.", flush=True)
                continue
            servo, origin, endpoint = command
            current = controller.pan_position() if servo is Servo.PAN else servo.angle
            at_endpoint = current is not None and abs(current - endpoint) <= abs(current - origin)
            target = origin if at_endpoint else endpoint
            result = _move_test_axis(controller, servo, current, origin, target, motor_speed, monitor_battery)
            if status is not BatteryStatus.NORMAL:
                break
            if servo is Servo.PAN:
                print(f"PAN, cible {target}° : {result.name}, position estimée {servo.angle:.1f}°", flush=True)
            else:
                print(f"{servo.name} → {target}° (écart à l’origine {target - origin:+}°)", flush=True)

    print(f"Défaut batterie ({status}). Retour aux positions d’origine.", flush=True)
    _park_after_low_battery(controller)
    print("Déplacements bloqués.", flush=True)
    return 2
