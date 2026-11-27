# Pilotage et suivi PWM des servomoteurs

Le PCA9685 génère les impulsions à environ 50 Hz pour deux servos positionnels de 180° (`ZOOM` et `TILT`) et un servo 360° supposé à rotation continue (`PAN`). Le PCA9685 expose les valeurs programmées. Mesurer la position, la vitesse réelle ou le courant demande un capteur supplémentaire.

| Raspberry Pi 5 | Broche physique | PCA9685 | Module MPU6050 |
| --- | ---: | --- | --- |
| 3,3 V | 1 | VCC (logique) | VCC / VIN si le module accepte 3,3 V |
| GPIO2 / SDA | 3 | SDA | SDA |
| GPIO3 / SCL | 5 | SCL | SCL |
| GND | 6 | GND | GND |

Alimenter les servos sur `V+` avec une alimentation externe dimensionnée pour les trois modèles, à leur tension nominale. Relier la masse de l’alimentation à `GND` sur la carte. Brancher les signaux aux connecteurs marqués `0` pour ZOOM, `1` pour PAN et `12` pour TILT. La fréquence est commune aux 16 canaux. Dédier la carte aux servos. [Brochage officiel Raspberry Pi](https://www.raspberrypi.com/documentation/computers/raspberry-pi.html) · [Câblage et alimentation Adafruit](https://learn.adafruit.com/adafruit-16-channel-servo-driver-with-raspberry-pi/hooking-it-up)

Utiliser des signaux SDA et SCL à 3,3 V sur les deux modules. Sur le MPU6050, mettre `AD0` à GND pour l’adresse `0x68`, ou à 3,3 V pour `0x69` et passer `--gyro-address 0x69` avant la commande. Le programme utilise des lectures I²C périodiques. La broche `INT` peut rester débranchée. [Brochage MPU6050](https://learn.adafruit.com/mpu6050-6-dof-accelerometer-and-gyro/pinouts)

## Lancer sur la Raspberry Pi

Activer I²C dans `sudo raspi-config` via **Interface Options → I2C**, puis vérifier que `/dev/i2c-1` est accessible. Le programme utilise Python 3.11 ou supérieur. Depuis le dossier parent de `servomotor_monitoring`, avec `smbus2` déjà installé dans l’environnement Python, lancer les commandes suivantes. [Configuration I²C officielle](https://www.raspberrypi.com/documentation/computers/configuration.html)

```bash
ls -l /dev/i2c-1
i2cdetect -y 1
python3 -m servomotor_monitoring check
python3 -m servomotor_monitoring status
python3 -m servomotor_monitoring status --watch
```

Avec les adresses par défaut, le scan doit afficher `40` pour le PCA9685 et `68` pour le MPU6050. Installer `i2c-tools` si `i2cdetect` manque. Si le bus reste absent après l’activation, redémarrer la Pi et vérifier de nouveau.

Si `smbus2` manque, installer la dépendance dans un environnement virtuel.

```bash
python3 -m venv servomotor_monitoring/.venv
servomotor_monitoring/.venv/bin/python -m pip install -r servomotor_monitoring/requirements.txt
servomotor_monitoring/.venv/bin/python -m servomotor_monitoring check
```

L’adresse I²C par défaut est `0x40` avec les cavaliers d’adresse ouverts. Pour un autre bus ou une autre adresse, passer `--bus` et `--address` avant la commande, par exemple `python3 -m servomotor_monitoring --bus 1 --address 0x41 check`. Les commandes `check` et `status` laissent les sorties intactes. `status` affiche les impulsions programmées et calcule leur durée avec l’oscillateur nominal de 25 MHz. [Fiche technique NXP PCA9685](https://www.nxp.com/docs/en/data-sheet/PCA9685.pdf)

## Commander un servo

Régler `CALIBRATIONS` dans `servo.py` avant le premier mouvement. Les valeurs initiales sont 1000, 1500 et 2000 µs. Pour ZOOM et TILT, elles correspondent à 0°, 90° et 180°. Pour PAN, elles correspondent à la commande maximale dans un sens, au neutre et à la commande maximale dans l’autre sens. `inverted=True` inverse la correspondance entre les sens et les impulsions de l’axe.

- `position` fixe un angle absolu. Pour ZOOM et TILT, la plage est de 0° à 180° et la CLI maintient le PWM pendant une seconde par défaut, puis le coupe. Pour PAN, la plage est de −360° à +360° autour du repère, avec une marge d’arrêt prioritaire sur la cible.
- `move` commande la vitesse de PAN en pourcentage. Sur ZOOM ou TILT, ce pourcentage représente la demi-course depuis 90° dans le sens demandé. Par exemple, 50 % en sens horaire donne une cible de 135°. Le mouvement réel dépend de l’angle de départ. À 0 %, `move` coupe le PWM sur les trois axes.

```bash
python3 -m servomotor_monitoring position ZOOM 75 --duration 2
python3 -m servomotor_monitoring position TILT 110
python3 -m servomotor_monitoring position PAN 90
python3 -m servomotor_monitoring move PAN 20 HORAIRE --duration 0.3
python3 -m servomotor_monitoring stop PAN
```

Pour ZOOM et TILT, les commandes CLI `move` et `position` coupent le PWM après la durée demandée. Depuis Python, le PWM reste actif jusqu’à `stop`, une commande `move` à 0 % ou la sortie du bloc `with`. Pour PAN, la commande coupe le PWM à la fin de chaque déplacement surveillé. `Ctrl+C` ou `SIGTERM` interrompt les commandes CLI. Une coupure brutale du processus ou du bus peut laisser le dernier PWM actif sur la carte.

## Mouvements simultanés

Les écritures I²C se succèdent et le PCA9685 génère ensuite les signaux simultanément. Utiliser **un seul** contrôleur dans un même bloc `with`. Régler d’abord ZOOM ou TILT, puis lancer PAN. La commande PAN bloque le programme appelant pendant la surveillance et le PCA9685 continue à produire le PWM du premier canal. Deux processus de pilotage séparés se disputent le verrou du bus.

```python
from servomotor_monitoring.servo import Direction, PanResult, Servo, ServoController

with ServoController(bus=1, address=0x40) as controller:
    controller.set_angle(Servo.ZOOM, 75)
    result = controller.move(Servo.PAN, 20, Direction.HORAIRE, duration=0.5)
    if result is PanResult.LIMITE_HORAIRE:
        print("Tourner uniquement dans le sens antihoraire.")
```

## Limite PAN

Fixer le MPU6050 sur la partie qui tourne avec PAN. L’axe `Z` du capteur doit être parallèle à l’axe mécanique. Ajuster `MPU6050.AXIS` et `MPU6050.CLOCKWISE_SIGN` dans `pan.py` selon le montage. Vérifier le signe à partir d’un mouvement court depuis le repère, loin des limites. Le capteur doit rester immobile avant chaque commande pendant l’estimation de son biais.

Placer physiquement PAN au repère où le câblage est détendu, puis enregistrer le zéro avec `pan-reference`. `pan-position` affiche la dernière position validée. Le programme ajoute la rotation horaire et soustrait la rotation antihoraire. Il borne la position estimée à ±360° par rapport au repère, avec une marge d’arrêt qui augmente avec la vitesse mesurée.

```bash
python3 -m servomotor_monitoring pan-reference
python3 -m servomotor_monitoring pan-position
```

`move(Servo.PAN, ...)` renvoie `PanResult.TERMINE`, `PanResult.LIMITE_HORAIRE` ou `PanResult.LIMITE_ANTIHORAIRE`. À la limite, le PWM est coupé et le sens indiqué reste bloqué jusqu’à un recul mesuré. Le résultat est aussi affiché par la CLI. La position est enregistrée dans `~/.local/state/servomotor_monitoring/pan-1-40.json` avec le bus et l’adresse par défaut. Une interruption pendant le déplacement invalide la position et impose de retrouver le repère physique.

`set_angle(servo, angle)` est commun aux trois axes. `Servo.angle` contient le dernier angle commandé de ZOOM/TILT ou l’angle estimé et enregistré de PAN. `None` indique une position inconnue. Pour PAN, `set_angle` renvoie aussi `CIBLE_NON_ATTEINTE` si la tolérance de ±3° n’est pas atteinte après au plus trois tentatives. Si PAN s’arrête avant sa cible sans erreur, l’angle enregistré reste l’estimation mesurée.

Le gyroscope estime le déplacement par intégration et accumule de la dérive. Un déplacement manuel ou hors tension exige un nouveau référencement. Valider la marge et l’arrêt sur le montage réel. Pour une limite matérielle stricte, prévoir une mesure absolue multi-tour ou des fins de course capables de couper le moteur indépendamment du programme.

`reset_positions()` ramène PAN au zéro enregistré, puis commande TILT à 90° et ZOOM à 0°. Le retour de PAN doit être confirmé avant de déplacer TILT et ZOOM. Le zéro de référence est conservé. Pour utiliser la fonction avec la surveillance batterie, lancer `python3 -m station_controller --initial-positions`.

## Tester uniquement ZOOM

Ce test direct fait passer ZOOM par 90°, 75°, 105° et 90°, puis coupe le PWM. Vérifier que cette course est libre. Pour tester les axes avec la surveillance batterie, utiliser `python3 -m station_controller.motor_test --speed 30`.

```bash
cd ~
python3 -m servomotor_monitoring.zoom_test
```

