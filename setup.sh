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

# ── Dépendances affichage (WebView / WebKitGTK + X11) ────
echo "→ Installation des dépendances d'affichage..."
sudo apt-get install -y -q \
  python3-gi python3-gi-cairo gir1.2-gtk-3.0 gir1.2-webkit2-4.1 \
  python3-pip mpv unclutter-xfixes \
  xserver-xorg x11-xserver-utils xinit openbox
pip3 install --break-system-packages pywebview 2>/dev/null || pip3 install pywebview

# ── Démarrage de l'application ────────────────────────────
echo "→ Démarrage de l'application..."
cd "$DIR"
sudo docker compose up -d --build

# ── Service systemd pour l'affichage ──────────────────────
echo "→ Configuration du service d'affichage..."
sudo tee /etc/systemd/system/affichage-display.service > /dev/null << EOF
[Unit]
Description=Affichage SDIS (WebView kiosk)
After=docker.service
Wants=docker.service

[Service]
Type=simple
User=$(whoami)
Environment=DISPLAY=:0
Environment=FLASK_URL=http://localhost:8000
Environment=GDK_BACKEND=x11
ExecStart=/usr/bin/python3 $DIR/display_webview.py
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable affichage-display.service

# ── Désactiver le blanking écran ──────────────────────────
# Console blanking off
sudo bash -c 'grep -q "consoleblank=0" /boot/firmware/cmdline.txt || sed -i "s/$/ consoleblank=0/" /boot/firmware/cmdline.txt'

# ── Démarrage automatique X11 + affichage ─────────────────
mkdir -p "$HOME/.config/openbox"
cat > "$HOME/.config/openbox/autostart" << 'OBOX'
# Désactiver écran de veille / blanking
xset s off
xset -dpms
xset s noblank

# Cacher le curseur
unclutter-xfixes --hide-on-touch &
OBOX

# Auto-startx à la connexion sur tty1
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

# ── Résumé ────────────────────────────────────────────────
IP=$(hostname -I | awk '{print $1}')
echo ""
echo "┌─────────────────────────────────────────────┐"
echo "│   Terminé !                                 │"
echo "│                                             │"
echo "│   Admin : http://$IP:8000/admin             │"
echo "│                                             │"
echo "│   L'affichage démarre automatiquement       │"
echo "│   via le service systemd.                   │"
echo "│                                             │"
echo "│   → sudo reboot                             │"
echo "└─────────────────────────────────────────────┘"
echo ""
