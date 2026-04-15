# Installation sur Raspberry Pi

## Matériel recommandé

Raspberry Pi 4 (2 Go+), carte SD 16 Go, alimentation 3 A, écran HDMI 1080p.
Un Pi 3B fonctionne aussi mais sera plus lent au démarrage.

---

## Étape 1 — Flasher la carte SD

Télécharger **[Raspberry Pi Imager](https://www.raspberrypi.com/software/)** et choisir :

```
Raspberry Pi OS (other) → Raspberry Pi OS Lite (64-bit)
```

Avant de flasher, cliquer sur ⚙️ et configurer :

| Paramètre | Valeur |
|---|---|
| Hostname | `affichage-sdis` |
| SSH | Activé |
| Utilisateur | `sdis` + votre mot de passe |
| Wi-Fi | SSID + mot de passe (si pas de câble) |
| Locale | `Europe/Paris`, clavier `fr` |

Insérer la carte dans le Pi et le démarrer.

---

## Étape 2 — Lancer l'installation

Se connecter en SSH :

```bash
ssh sdis@affichage-sdis.local
```

Cloner le dépôt et lancer le script d'installation :

```bash
git clone <URL_DU_DEPOT> ~/affichage
cd ~/affichage
bash setup.sh
```

Le script installe Docker, configure le mode kiosk et démarre l'application. (~5 min)

---

## Étape 3 — Redémarrer

```bash
sudo reboot
```

Le Pi démarre directement sur l'écran d'affichage en plein écran.

---

## Administration

Depuis n'importe quel navigateur sur le réseau local :

```
http://affichage-sdis.local:8000/admin
```

Mot de passe défini dans `config.py` (`ADMIN_PASSWORD`).

---

## Résolution d'écran (si besoin)

Si l'image n't est pas en 1080p, éditer `/boot/config.txt` :

```bash
sudo nano /boot/config.txt
```

```ini
hdmi_group=1
hdmi_mode=16        # 1080p 60 Hz
hdmi_force_hotplug=1
```

---

## Commandes utiles

```bash
# Logs de l'application
docker compose -f ~/affichage/docker-compose.yml logs -f

# Mettre à jour après modification du code
cd ~/affichage && git pull && docker compose up -d --build

# Redémarrer l'app sans reboot
docker compose restart
```
