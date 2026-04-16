#!/usr/bin/env bash
set -e
export DEBIAN_FRONTEND=noninteractive

DIR="$(cd "$(dirname "$0")" && pwd)"

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

# ── Docker ────────────────────────────────────────────────
if ! command -v docker &>/dev/null; then
  echo "→ Installation de Docker..."
  curl -fsSL https://get.docker.com | sh
  sudo usermod -aG docker "$(whoami)"
fi
sudo systemctl enable docker

# ── Dépendances affichage (Chromium kiosk) ────────────────
echo "→ Installation des dépendances d'affichage..."
sudo apt-get install -y -q \
  chromium xserver-xorg x11-xserver-utils xinit openbox \
  unclutter-xfixes fonts-noto-color-emoji

# ── Démarrage de l'application ────────────────────────────
echo "→ Démarrage de l'application..."
cd "$DIR"
sudo docker compose up -d --build

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
ExecStart=-/sbin/agetty --autologin $(whoami) --noclear %I \$TERM
EOF
sudo systemctl daemon-reload

# ── Nettoyage ancien service systemd (si existant) ────────
sudo systemctl disable affichage-display.service 2>/dev/null || true
sudo rm -f /etc/systemd/system/affichage-display.service
sudo systemctl daemon-reload

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
