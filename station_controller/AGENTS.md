# Consignes pour `station_controller`

- Garder ce dossier dédié à l’automate global de la Raspberry Pi 5. Réutiliser `servomotor_monitoring` pour les servos.
- Garder la mesure de batterie dans `battery.py`, hors de `servomotor_monitoring`. Elle utilise A3 de l’ADS1115 sur I²C à `0x48` avec ADDR à GND et un pont de 10 kΩ côté batterie, 4,7 kΩ côté masse.
- Vérifier la batterie avant les déplacements, puis périodiquement même sans saisie. Si elle est déjà basse au démarrage, bloquer tout mouvement. Si elle atteint 7,0 V en service, arrêter la commande en cours, tenter une seule fois ZOOM à 0°, TILT à 90° et PAN à 0°, puis terminer. Une mesure invalide ou une erreur I²C arrête l’automate sans commander de retour.
- Garder le test interactif dans `motor_test.py`. Il utilise l’automate et vérifie aussi la batterie durant les déplacements de PAN. Ne le lancer sur la Pi que sur demande explicite.
- Le test interactif reçoit une vitesse de progression en degrés par seconde et espace les consignes intermédiaires. Dans ce test, le zéro mécanique de TILT correspond à la consigne servo 90°.
- La commande terminal `0 <angle>` donne une consigne absolue de ZOOM. Par défaut, elle est envoyée directement. `--zoom-speed` active la rampe. L’origine de ZOOM est 0°.
- Le mode `--center-tilt` maintient uniquement TILT à 90° pour le montage, avec les mêmes contrôles batterie. L’arrêt du programme désactive les PWM.
- Le mode `--initial-positions` conserve le repère PAN existant. Surveiller la batterie pendant le retour de PAN.
- Tester la logique avec un bus, un servo et une horloge simulés. Le diagnostic `python3 -m station_controller.battery` vérifie uniquement l’ADS1115.
- Le diagnostic batterie affiche le code ADC brut, la tension A3 et le calcul côté pack. Conserver le seuil de coupure de 7,0 V côté pack, équivalent à environ 2,238 V sur A3 avec le pont nominal.
- Au démarrage, amorcer l’ADS1115 puis prendre la décision sur une nouvelle conversion. Pendant le fonctionnement, conserver le contrôle sur chaque conversion périodique.
- Après une modification du code, régénérer le graphe local avec `graphify extract . --code-only` depuis ce dossier. Interroger le graphe avec `graphify query "run_station check_battery"`.
