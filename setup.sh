#!/usr/bin/env bash
set -e
export DEBIAN_FRONTEND=noninteractive

DIR="$(cd "$(dirname "$0")" && pwd)"
USER="$(whoami)"

echo ""
echo "┌─────────────────────────────────────────────┐"
echo "│   Installation affichage SDIS               │"
echo "└─────────────────────────────────────────────┘"
echo ""

# ── Mot de passe admin ────────────────────────────────────
read -rp "Mot de passe admin (interface web) : " ADMIN_PASSWORD
echo ""

# ── Écriture de config.py ─────────────────────────────────
SECRET_KEY=$(tr -dc 'a-zA-Z0-9' < /dev/urandom | head -c 48)
cat > "$DIR/config.py" << EOF
SECRET_KEY     = "$SECRET_KEY"
ADMIN_PASSWORD = "$ADMIN_PASSWORD"
EOF

# ── Mise à jour système ───────────────────────────────────
echo "→ Mise à jour du système..."
sudo apt-get update -q && sudo apt-get full-upgrade -y -q

# ── Dépendances Python + affichage ────────────────────────
echo "→ Installation des dépendances..."
sudo apt-get install -y -q \
  python3 python3-pip \
  chromium xserver-xorg x11-xserver-utils xinit openbox \
  unclutter-xfixes fonts-noto-color-emoji

pip3 install --break-system-packages flask 2>/dev/null || pip3 install flask

# ── Créer les dossiers ───────────────────────────────────
mkdir -p "$DIR/data" "$DIR/static/uploads" "$DIR/static/icons" "$DIR/static/videos"

# ── Service systemd Flask ─────────────────────────────────
echo "→ Configuration du service Flask..."
sudo tee /etc/systemd/system/affichage-flask.service > /dev/null << EOF
[Unit]
Description=Affichage SDIS (Flask)
After=network.target

[Service]
Type=simple
User=$USER
WorkingDirectory=$DIR
ExecStart=/usr/bin/python3 $DIR/app.py
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable affichage-flask.service
sudo systemctl restart affichage-flask.service

# ── Script kiosk (lancé par openbox) ─────────────────────
cat > "$DIR/kiosk.sh" << 'KIOSK'
#!/usr/bin/env bash
# Attendre que Flask soit prêt
while ! curl -s -o /dev/null http://localhost:8000; do sleep 2; done

# Désactiver veille écran
xset s off
xset -dpms
xset s noblank

# Cacher le curseur
unclutter-xfixes --hide-on-touch &

# Lancer Chromium en mode kiosk
chromium \
  --kiosk \
  --noerrdialogs \
  --disable-infobars \
  --disable-session-crashed-bubble \
  --disable-restore-session-state \
  --disable-features=TranslateUI,Translate \
  --disable-translate \
  --lang=fr \
  --check-for-update-interval=31536000 \
  --disable-component-update \
  --autoplay-policy=no-user-gesture-required \
  --start-fullscreen \
  --incognito \
  http://localhost:8000
KIOSK
chmod +x "$DIR/kiosk.sh"

# ── Openbox lance le kiosk au démarrage de X ──────────────
mkdir -p "$HOME/.config/openbox"
cat > "$HOME/.config/openbox/autostart" << EOF
$DIR/kiosk.sh &
EOF

# ── Désactiver le blanking écran (console) ────────────────
sudo bash -c 'grep -q "consoleblank=0" /boot/firmware/cmdline.txt || sed -i "s/$/ consoleblank=0/" /boot/firmware/cmdline.txt'

# ── Auto-startx à la connexion sur tty1 ──────────────────
grep -q "startx" "$HOME/.profile" 2>/dev/null || cat >> "$HOME/.profile" << 'PROF'

# Démarrage automatique de X11 sur tty1
if [ -z "$DISPLAY" ] && [ "$(tty)" = "/dev/tty1" ]; then
  exec startx -- -nocursor 2>/dev/null
fi
PROF

# ── Autologin ─────────────────────────────────────────────
sudo mkdir -p /etc/systemd/system/getty@tty1.service.d
sudo tee /etc/systemd/system/getty@tty1.service.d/autologin.conf > /dev/null << EOF
[Service]
ExecStart=
ExecStart=-/sbin/agetty --autologin $USER --noclear %I \$TERM
EOF
sudo systemctl daemon-reload

# ── Nettoyage Docker (si présent) ─────────────────────────
if command -v docker &>/dev/null; then
  echo "→ Arrêt des conteneurs Docker (si existants)..."
  cd "$DIR" && sudo docker compose down 2>/dev/null || true
  sudo systemctl disable docker 2>/dev/null || true
  sudo systemctl stop docker 2>/dev/null || true
  echo "  Docker désactivé (économie ~200 Mo RAM)."
  echo "  Pour le supprimer complètement : sudo apt remove docker-ce docker-ce-cli"
fi

# ── Résumé ────────────────────────────────────────────────
IP=$(hostname -I | awk '{print $1}')
echo ""
echo "┌─────────────────────────────────────────────┐"
echo "│   Terminé !                                 │"
echo "│                                             │"
echo "│   Admin : http://$IP:8000/admin             │"
echo "│                                             │"
echo "│   L'affichage démarre automatiquement       │"
echo "│   au boot (autologin → X11 → Chromium).     │"
echo "│                                             │"
echo "│   → sudo reboot                             │"
echo "└─────────────────────────────────────────────┘"
echo ""
