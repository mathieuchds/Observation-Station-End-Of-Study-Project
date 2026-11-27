# Consignes pour `servomotor_monitoring`

- Garder le pilotage en Python sur Raspberry Pi 5, via I²C et une carte PCA9685. Préserver l’API `ServoController.move(servo, power, direction)` et les axes `Servo.ZOOM`, `Servo.PAN` et `Servo.TILT`.
- Traiter ZOOM et TILT comme des servos positionnels de 0° à 180° et PAN comme un servo à rotation continue. Sur PAN, la puissance est une consigne de vitesse. Sur ZOOM et TILT, elle exprime une fraction de la demi-course depuis 90°. Respecter la calibration de chaque axe et la coupure du PWM à 0 % avec `move`.
- Garder `check` et `status` en lecture seule. Pour valider un déploiement, commencer par `check`. Exécuter un mouvement physique uniquement si le test de mouvement est demandé.
- Garder les adresses de groupe lisibles via `check --addresses`. L’adresse individuelle du PCA9685 et celle du gyroscope doivent être distinctes.
- Garder le diagnostic `mpu6050_test.py` indépendant des moteurs. Le mode `--probe-only` lit uniquement l’identité. Le pilote accepte le MPU-6050 (`WHO_AM_I=0x68`) et le MPU-6500 (`0x70`). `center_tilt` envoie la consigne centrale sans modifier la calibration enregistrée.
- Faire passer toute rotation de PAN par le suivi du MPU6050 et conserver les retours `PanResult`. Une position incertaine doit bloquer la commande jusqu’au référencement manuel.
- Exposer une commande d’angle absolu pour les trois axes via `set_angle`. `Servo.angle` contient la dernière consigne pour ZOOM/TILT et l’estimation validée pour PAN. Conserver la limite signée de PAN et distinguer une cible non atteinte d’une cible atteinte.
- ZOOM, PAN et TILT utilisent les canaux PCA9685 marqués 0, 1 et 12. `reset_positions` ramène d’abord PAN au zéro enregistré, puis commande TILT à 90° et ZOOM à 0°.
- Garder la mesure de batterie et le blocage des déplacements dans `station_controller`. Un arrêt supervisé de PAN doit préserver sa position lorsqu’elle a pu être mesurée jusqu’à l’arrêt.
- Pour analyser la structure du module avec Graphify, depuis ce dossier lancer `graphify extract . --code-only`, puis `graphify query "ServoController move set_angle status"`. Régénérer le graphe après modification du code. Le dossier `graphify-out/` est généré localement.
- Vérifier les changements de logique avec un bus I²C simulé si la carte est indisponible. En cas de déploiement sur la Pi, rapporter séparément le résultat du lancement et celui de la communication I²C.
