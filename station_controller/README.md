# Automate de contrôle de la station

La v1 prend le contrôle du PCA9685, coupe les PWM au démarrage et mesure la batterie avant d’autoriser les déplacements. Le contrôle se répète toutes les 5 secondes par défaut, même en l’absence de saisie.

Tapez `0 45` puis Entrée pour commander ZOOM à 45°. La commande accepte un angle absolu de 0° à 180°. Pour placer et maintenir uniquement ZOOM à son origine de 0°, lancez `python3 -m station_controller --init-zoom`.

`battery.py` mesure la tension totale du pack LiPo 2S sur A3 de l’ADS1115. Si la tension descend à **7,0 V ou moins** en cours d’utilisation, l’automate interrompt le mouvement, tente une fois de ramener TILT à 90°, ZOOM à 0° et PAN à son repère, puis désactive les PWM et sort avec le code 2. Si PAN ne peut pas revenir au repère, l’automate le signale. Si la batterie est déjà basse au démarrage, aucun mouvement n’est lancé. Une mesure indisponible ou incohérente entraîne un arrêt avec le code 1, sans retour automatique. Le seuil correspond à une moyenne de 3,5 V par cellule. La mesure du pack ne détecte pas un déséquilibre entre cellules. [Guide LiPo Gens Ace](https://gensace.de/pages/lipo-battery-guide)

## Câblage de l’ADS1115

| ADS1115 | Connexion |
| --- | --- |
| VDD | 3,3 V Pi, broche physique 1 |
| SDA | GPIO2, broche physique 3 |
| SCL | GPIO3, broche physique 5 |
| GND | Masse Pi, broche physique 6, reliée au négatif batterie |
| ADDR | GND pour fixer l’adresse I²C à `0x48` |
| A3 | Jonction des résistances de 10 kΩ et 4,7 kΩ |

```text
Batterie + ── 10 kΩ ──┬── 4,7 kΩ ── Batterie − / GND
                     A3
```

À 8,4 V côté batterie, A3 reçoit environ 2,69 V. Gardez l’ADS1115 alimenté tant que l’entrée est reliée à la batterie, ou débranchez le pont lorsque la Pi est éteinte. Le pont consomme environ 0,5 mA à 7,4 V. Le verrouillage agit sur les commandes PWM. L’alimentation matérielle reste sous le contrôle du montage. [Fiche technique TI ADS1115](https://www.ti.com/lit/ds/symlink/ads1115.pdf)

## Essais simulés

Depuis la racine du dépôt, exécuter les tests avec la commande suivante.

```bash
python3 -m unittest station_controller.test_battery station_controller.test_station servomotor_monitoring.test_pan
```

## Lancer sur la Raspberry Pi

L’automate réutilise `servomotor_monitoring`. Les deux dossiers doivent être présents côte à côte. Le script de transfert à la racine prend en charge les deux dossiers.

```bash
./deploy_to_pi.sh servomotor_monitoring station_controller
```

Sur la Pi, depuis le répertoire parent des deux dossiers, tester d’abord la mesure. Comparer la tension affichée à celle d’un multimètre branché aux bornes du pack.

```bash
python3 -m station_controller.battery
```

Lancer ensuite l’automate.

```bash
python3 -m station_controller
```

Utiliser `--interval 5` pour fixer l’intervalle en secondes. `Ctrl+C` arrête l’automate et désactive les PWM.

## Test interactif des trois moteurs

Pour tester PAN, fixer d’abord le MPU6050 sur l’axe tournant. Placer PAN au repère et enregistrer le zéro avec `python3 -m servomotor_monitoring pan-reference`. Si la broche AD0 du MPU6050 sélectionne l’adresse `0x69`, passer `--gyro-address 0x69` devant `pan-reference` et après `station_controller.motor_test`.

```bash
cd ~
python3 -m station_controller.motor_test --speed 30
```

`--speed` règle la progression des consignes de PAN et TILT en °/s et peut être omis pour tester ZOOM seul. ZOOM reçoit directement l’angle demandé par défaut. Ajouter `--zoom-speed` pour lui appliquer une rampe en °/s. Les rampes conservent les contrôles batterie.

| Saisie suivie d’Entrée | Mouvement |
| --- | --- |
| `0 45` | ZOOM à 45°, ou à l’angle absolu saisi |
| `1` | PAN entre 0° et 90°, avec estimation par le gyroscope |
| `2` | TILT entre 0° et 20° mécaniques (consignes servo 90° et 110°) |

Les déplacements sont autorisés après un contrôle batterie normal. La mesure continue toutes les 5 secondes par défaut, y compris pendant un déplacement de PAN. `Ctrl+C` ou `Ctrl+D` arrête le test et désactive les PWM.
