#!/usr/bin/env bash
set -e

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
sudo apt-get update -qq && sudo apt-get full-upgrade -y -qq

# ── Docker ────────────────────────────────────────────────
if ! command -v docker &>/dev/null; then
  echo "→ Installation de Docker..."
  curl -fsSL https://get.docker.com | sh
  sudo usermod -aG docker "$(whoami)"
fi
sudo systemctl enable docker

# ── Chromium + Openbox ────────────────────────────────────
echo "→ Installation de Chromium / Openbox..."
sudo apt-get install -y -qq chromium-browser xorg xinit openbox unclutter

# ── Démarrage de l'application ────────────────────────────
echo "→ Démarrage de l'application..."
cd "$DIR"
sudo docker compose up -d --build

# ── Mode kiosk ────────────────────────────────────────────
echo "→ Configuration du mode kiosk..."
mkdir -p "$HOME/.config/openbox"
cat > "$HOME/.config/openbox/autostart" << 'EOF'
xset s off; xset s noblank; xset -dpms
unclutter -idle 0.5 -root &
chromium-browser --noerrdialogs --disable-infobars --kiosk \
  --disable-session-crashed-bubble http://localhost:8000 &
EOF

echo "exec openbox-session" > "$HOME/.xinitrc"

grep -q "startx" "$HOME/.bash_profile" 2>/dev/null || cat >> "$HOME/.bash_profile" << 'EOF'

[ -z "$DISPLAY" ] && [ "$(tty)" = "/dev/tty1" ] && startx
EOF

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
echo "│   Admin : http://$IP:8000/admin"
echo "│                                             │"
echo "│   → sudo reboot                             │"
echo "└─────────────────────────────────────────────┘"
echo ""
