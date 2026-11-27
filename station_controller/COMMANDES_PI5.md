# Commandes de test sur la Raspberry Pi 5

Les commandes Python se lancent sur `gumapi5` depuis le dossier personnel.

```bash
cd ~
```

## Vérifier le bus et la batterie

| Commande | Résultat attendu |
| --- | --- |
| `python3 -m servomotor_monitoring check` | Le PCA9685 répond à `0x40`. |
| `python3 -m servomotor_monitoring check --addresses` | Affiche l’adresse principale du PCA9685 et les adresses de groupe réellement activées. |
| `python3 -m servomotor_monitoring status --watch` | Affiche le PWM programmé sur les trois sorties. `Ctrl+C` arrête l’affichage. |
| `python3 -m station_controller.battery --samples 10` | Affiche le code brut, la tension mesurée entre A3 et GND, la tension du pack calculée et les seuils. |

Avec le pont 10 kΩ / 4,7 kΩ, le pack vaut environ `A3 × 3,1277`. Le seuil de 7,00 V correspond à 2,2381 V sur A3. En cas de coupure batterie, l’automate affiche la mesure qui a déclenché l’arrêt. Ajouter `--battery-debug` pour afficher aussi les mesures normales.

## Diagnostiquer le MPU6050

```bash
python3 -m servomotor_monitoring.mpu6050_test --probe-only
python3 -m servomotor_monitoring.mpu6050_test --samples 30
```

La première commande lit l’identité aux adresses `0x68` et `0x69`. `WHO_AM_I=0x68` identifie un MPU-6050 et `0x70` un MPU-6500. Le gyroscope conserve une adresse I²C de `0x68` ou `0x69` même si son identifiant est `0x70`. La seconde réveille le capteur et affiche X, Y et Z en degrés par seconde. Au repos, les valeurs doivent rester proches de zéro. En tournant doucement le capteur à la main, regarde quel axe change et dans quel sens. [Registres du MPU-6500](https://res.ameya360.com/91/2A/58/3933E841E38F0B6BA0B9DB69D7_A.pdf)

En cas d’absence de réponse, vérifier VCC, GND, SDA sur GPIO2, SCL sur GPIO3 et le niveau de la broche AD0. AD0 bas sélectionne `0x68` et AD0 haut sélectionne `0x69`. On peut cibler une seule adresse avec `--address 0x69`. Arrêter l’automate avant de demander des mesures X/Y/Z, car le diagnostic et PAN partagent le gyroscope.

### Vérifier la cohabitation sur le bus I²C

Par défaut, le PCA9685 utilise `0x40` et l’adresse de groupe All Call `0x70` au démarrage. Ses trois sous-adresses par défaut sont `0x71`, `0x72` et `0x74`, désactivées à la mise sous tension. Le MPU utilise `0x68` ou `0x69` et l’ADS1115 utilise `0x48`. [Adresses du PCA9685](https://www.nxp.com/docs/en/data-sheet/PCA9685.pdf)

Si le MPU répond seul, couper l’alimentation avant de reconnecter uniquement le côté logique du PCA (`VCC`, `GND`, `SDA`, `SCL`). Laisser `V+` des servos débranché et relancer les deux diagnostics. Si le MPU ne répond plus, vérifier que SDA/SCL restent au niveau haut près de 3,3 V au repos et que les résistances de rappel des modules vont au 3,3 V. Si le problème ne revient qu’avec `V+` rétabli, vérifier la tension et la masse avec l’alimentation des servos connectée.

Pour tester le MPU à `0x69`, placer `AD0` au niveau haut de la logique du module hors tension. Pour changer l’adresse principale du PCA9685, configurer ses broches A0–A5. Sur un module à cavaliers de type Adafruit, fermer le cavalier A0 donne `0x41`. Après ces changements matériels, les commandes correspondantes sont les suivantes. [Sélection d’adresse du MPU-6500](https://product.tdk.com/system/files/dam/doc/product/sensor/mortion-inertial/imu/data_sheet/mpu-6500-datasheet2.pdf) · [Cavaliers du PCA9685 Adafruit](https://learn.adafruit.com/16-channel-pwm-servo-driver/chaining-drivers)

```bash
python3 -m servomotor_monitoring --address 0x41 check --addresses
python3 -m servomotor_monitoring.mpu6050_test --probe-only --address 0x69
python3 -m station_controller.motor_test --pca-address 0x41 --gyro-address 0x69 --speed 30
```

En cas de changement d’adresse du PCA9685, refaire le référencement de PAN avec `python3 -m servomotor_monitoring --address 0x41 --gyro-address 0x69 pan-reference`, en adaptant les adresses à ton montage. Le fichier de position est associé à l’adresse du PCA.

## Centrer TILT avant le montage

Laisser le palonnier et la tringlerie démontés avant de lancer la commande.

```bash
python3 -m station_controller --center-tilt
```

La commande amorce l’ADS1115 puis vérifie la batterie avec une nouvelle conversion. Elle maintient uniquement TILT à 90° et affiche la largeur d’impulsion relue sur le canal marqué `12` (environ 1 500 µs). Monter le palonnier dans l’orientation neutre à cette position. `Ctrl+C` ou `Ctrl+D` désactive les PWM.

Si les registres indiquent environ 1 500 µs et que TILT reste immobile, vérifier la tension au multimètre entre `V+` et `GND` sur le connecteur marqué `12`. Utiliser la tension nominale du servo, avec une masse commune. Vérifier également que `OE` est au niveau bas et que le fil de signal est sur `PWM/S`. La réponse I²C confirme l’alimentation logique du PCA9685. L’alimentation moteur arrive par `V+`. [Brochage PCA9685](https://learn.adafruit.com/16-channel-pwm-servo-driver/pinouts)

Si le PWM est absent à l’oscilloscope, mesurer entre `PWM/S` et `GND` du connecteur marqué `12` pendant le centrage, en laissant la commande ouverte. Le programme remet le bit `FULL_OFF` du registre `0x3D` à l’arrêt. À 90°, le programme doit relire environ 1 498 µs et l’oscilloscope doit montrer une période d’environ 20 ms. [Registres et sorties PCA9685](https://www.nxp.com/docs/en/data-sheet/PCA9685.pdf)

## Initialiser ZOOM seul

```bash
python3 -m station_controller --init-zoom
```

La commande vérifie la batterie et maintient ZOOM à 0°. `Ctrl+C` ou `Ctrl+D` coupe le PWM.

## Référencer PAN puis tester les trois moteurs

Placer PAN au repère physique et l’immobiliser avant de lancer le référencement. Cette commande ne fait pas tourner PAN.

```bash
python3 -m servomotor_monitoring pan-reference
python3 -m station_controller.motor_test --speed 30
```

`--speed` règle les consignes de PAN et TILT en degrés par seconde. PAN avance par segments de 10° maximum contrôlés au gyroscope, avec des phases de mesure et d’arrêt entre les segments. TILT avance par pas de 2° maximum. Pour tester ZOOM seul, lancer `python3 -m station_controller.motor_test`. Par défaut, ZOOM reçoit directement la consigne et se déplace à sa vitesse native. Ajouter `--zoom-speed 30` pour limiter la progression de ses consignes en °/s.

Si le MPU6050 répond à `0x69`, utiliser `python3 -m servomotor_monitoring --gyro-address 0x69 pan-reference` puis `python3 -m station_controller.motor_test --speed 30 --gyro-address 0x69`.

Le référencement enregistre l’angle 0° dans `~/.local/state/servomotor_monitoring/pan-1-40.json`. Le programme actualise ensuite l’angle estimé à chaque mouvement surveillé. Si PAN a bougé manuellement ou si son suivi a été interrompu pendant un mouvement, replacer PAN physiquement au repère et relancer le référencement.

| Saisie suivie d’Entrée | Action |
| --- | --- |
| `0 45` | ZOOM à 45°. Remplacer 45 par l’angle absolu voulu entre 0° et 180°. |
| `1` | PAN entre 0° et 90° |
| `2` | TILT entre 0° et 20° mécaniques (consignes servo 90° et 110°) |

`Ctrl+C` ou `Ctrl+D` arrête le test et désactive les PWM. L’automate v1 accepte aussi `0 <angle>` pour ZOOM via `python3 -m station_controller`.

## Revenir aux positions initiales

```bash
python3 -m station_controller --initial-positions
```

La commande vérifie la batterie et ramène PAN à son zéro enregistré. Une fois PAN revenu au repère selon le gyroscope, elle commande TILT à 90° sur le canal PCA9685 marqué `12` et ZOOM à 0°. La batterie reste surveillée jusqu’à `Ctrl+C` ou `Ctrl+D`.

Si la batterie atteint le seuil de 7,0 V en service, l’automate tente un seul retour aux positions d’origine et sort avec le code 2. Une batterie déjà basse au démarrage bloque immédiatement les mouvements.
