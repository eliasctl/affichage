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
# Créer config.py manuellement :
cat > config.py << 'EOF'
SECRET_KEY     = "CHANGEZ_MOI_48_CHARS_ALEATOIRES"
ADMIN_PASSWORD = "votre_mot_de_passe"
EOF

docker compose up -d
```

### Vérification

Depuis n'importe quel navigateur sur le réseau :

```
http://<IP_SERVEUR>:8000/admin
```

---

## Client — Raspberry Pi Zero 2 W

### Matériel

- Raspberry Pi Zero 2 W
- Carte SD 8 Go minimum
- Adaptateur mini-HDMI → HDMI
- Alimentation 5V 2A

### Étape 1 — Flasher la carte SD

Avec **[Raspberry Pi Imager](https://www.raspberrypi.com/software/)** :

```
Raspberry Pi OS (other) → Raspberry Pi OS Lite (64-bit)
```

Configuration :

| Paramètre | Valeur |
|---|---|
| Hostname | `ecran-1` (ou `ecran-2`, etc.) |
| SSH | Activé |
| Utilisateur | `sdis` + mot de passe |
| Wi-Fi | SSID + mot de passe |
| Locale | `Europe/Paris`, clavier `fr` |

### Étape 2 — Installer le client

```bash
ssh sdis@ecran-1.local
```

Copier le script depuis le serveur ou le dépôt :

```bash
curl -O http://<IP_SERVEUR>:8000/static/setup-client.sh
# OU
git clone <URL_DU_DEPOT> ~/affichage && cd ~/affichage
```

Lancer l'installation :

```bash
bash setup-client.sh
```

Le script demande l'IP du serveur, installe Chromium et configure le démarrage automatique en kiosk.

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
