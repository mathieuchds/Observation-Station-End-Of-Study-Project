# Observation-Station-End-Of-Study-Project

## Déployer sur la Raspberry Pi

Lancer `./deploy_to_pi.sh` depuis le dépôt pour mettre à jour `~/servomotor_monitoring` sur `gumapi5`. Le script utilise SSH et `rsync` sur les deux machines. L’option `--dry-run` affiche les changements prévus.

```bash
./deploy_to_pi.sh --dry-run
./deploy_to_pi.sh
```

Pour ajouter un projet, créer un fichier `.deploy-files` dans son dossier à la racine du dépôt, avec un chemin relatif par ligne pour chaque fichier à copier. Passer ensuite les noms des dossiers au script. Chaque projet est copié dans un dossier du même nom dans le répertoire personnel distant. Le transfert préserve les autres fichiers présents sur la Pi.

Le [guide des servos](servomotor_monitoring/README.md) décrit les commandes et les vérifications I²C.
Le [guide de l’automate](station_controller/README.md) décrit le contrôle batterie et les essais simulés de la station.
Le [mémo des commandes Pi 5](station_controller/COMMANDES_PI5.md) couvre les diagnostics et les essais sur le matériel.
