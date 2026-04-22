# Installation — Architecture client/serveur

## Principe

```
┌──────────────┐       ┌──────────────┐       ┌──────────────┐
│  Pi Zero 2 W │       │  Pi Zero 2 W │       │  Pi Zero 2 W │
│  (écran 1)   │──┐    │  (écran 2)   │──┐    │  (écran 3)   │──┐
│  Chromium     │  │    │  Chromium     │  │    │  Chromium     │  │
└──────────────┘  │    └──────────────┘  │    └──────────────┘  │
                  │                      │                      │
                  ▼                      ▼                      ▼
            ┌──────────────────────────────────────────────┐
            │           SERVEUR (PC / Pi 4 / NAS)         │
            │   Flask + SQLite + admin + fichiers médias  │
            └──────────────────────────────────────────────┘
```

- **Serveur** : héberge l'application Flask, la base de données, l'interface admin et les fichiers médias.
- **Clients** (Pi Zero 2 W) : affichent uniquement la page web en plein écran via Chromium. Aucun logiciel applicatif.

---

## Serveur

### Option A — Bare metal (Raspberry Pi 4 / PC / VM)

```bash
git clone <URL_DU_DEPOT> ~/affichage
cd ~/affichage
bash setup-server.sh
```

Le script installe Python, Flask, crée le service systemd et démarre l'API sur le port 8000.

### Option B — Docker

```bash
git clone <URL_DU_DEPOT> ~/affichage
cd ~/affichage

# Configurer les variables d'environnement :
cat > .env << 'EOF'
SECRET_KEY=CHANGEZ_MOI_48_CHARS_ALEATOIRES
ADMIN_PASSWORD=votre_mot_de_passe
EOF

docker compose up -d
```

### Option C — Dokploy (avec nom de domaine + HTTPS)

1. Dans Dokploy, créer un nouveau projet puis un service **Compose**.

2. Source : connecter le dépot Git (GitHub, GitLab, etc.) ou coller le contenu du `docker-compose.yml`.

3. Dans l'onglet **Environment**, ajouter :
   ```
   SECRET_KEY=une_cle_secrete_longue_et_aleatoire
   ADMIN_PASSWORD=votre_mot_de_passe_admin
   ```

4. Dans l'onglet **Domains**, ajouter le domaine souhaité :
   - Hostname : `affichage.exemple.fr`
   - Port : `8000`
   - HTTPS : activé (Let's Encrypt automatique)

5. Déployer. Dokploy gère le reverse proxy (Traefik) et le certificat SSL.

6. Accéder à l'admin : `https://affichage.exemple.fr/admin`

### Vérification

Depuis n'importe quel navigateur sur le réseau :

```
http://<IP_SERVEUR>:8000/admin
# ou avec Dokploy :
https://affichage.exemple.fr/admin
```

---

## Client — Raspberry Pi Zero 2 W

### Matériel

- Raspberry Pi Zero 2 W
- Carte SD 8 Go minimum
- Adaptateur mini-HDMI → HDMI
- Alimentation 5V 2A

### Étape 1 — Flasher DietPi

Télécharger l'image **[DietPi pour Raspberry Pi Zero 2 W](https://dietpi.com/#downloadinfo)** (ARMv8 / Aarch64).

Flasher avec [balenaEtcher](https://etcher.balena.io/) ou Raspberry Pi Imager.

Avant de démarrer, éditer sur la carte SD :

**`dietpi.txt`** :
```ini
AUTO_SETUP_LOCALE=fr_FR.UTF-8
AUTO_SETUP_KEYBOARD_LAYOUT=fr
AUTO_SETUP_TIMEZONE=Europe/Paris
AUTO_SETUP_NET_WIFI_ENABLED=1
AUTO_SETUP_NET_WIFI_COUNTRY_CODE=FR
AUTO_SETUP_AUTOMATED=1
AUTO_SETUP_GLOBAL_PASSWORD=sdis
```

**`dietpi-wifi.txt`** :
```ini
aWIFI_SSID[0]='VotreSSID'
aWIFI_KEY[0]='VotreMotDePasse'
```

### Étape 2 — Installer le client

```bash
ssh root@<IP_DU_PI>
# mot de passe par défaut DietPi : dietpi (ou celui configuré)
```

Copier le script :

```bash
curl -O http://<IP_SERVEUR>:8000/static/setup-client.sh
# OU
apt install -y git && git clone <URL_DU_DEPOT> ~/affichage && cd ~/affichage
```

Lancer l'installation :

```bash
bash setup-client.sh
```

Le script installe surf (navigateur WebKit léger), active le mode **lite** (sans animations) et configure le kiosk automatique.

### Étape 3 — Redémarrer

```bash
sudo reboot
```

L'écran affiche automatiquement le contenu géré depuis l'admin du serveur.

---

## Ajouter un nouvel écran

Chaque nouvel écran = un Pi Zero 2 W avec `setup-client.sh`. Tous pointent vers le même serveur. Pas besoin de toucher au serveur.

---

## Commandes utiles

### Serveur

```bash
# Logs Flask
sudo journalctl -u affichage-flask -f

# Redémarrer Flask
sudo systemctl restart affichage-flask

# Mettre à jour
cd ~/affichage && git pull && sudo systemctl restart affichage-flask
```

### Serveur Docker

```bash
cd ~/affichage
docker compose logs -f
docker compose restart
docker compose up -d --build   # après mise à jour
```

### Serveur Dokploy

Les logs, redémarrages et redéploiements se font depuis l'interface Dokploy. Pour redéployer après un `git push`, activer le **auto-deploy** dans les paramètres du service.

### Client

```bash
# Voir l'URL serveur configurée
cat ~/kiosk/server_url

# Changer le serveur
nano ~/kiosk/kiosk.sh    # modifier l'URL
sudo reboot
```

---

## Résolution d'écran (client, si besoin)

```bash
sudo nano /boot/firmware/config.txt
```

```ini
hdmi_group=1
hdmi_mode=16        # 1080p 60 Hz
hdmi_force_hotplug=1
```
