#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────
#  Setup écran client — Raspberry Pi Zero 2 W
#  Installe uniquement Chromium en mode kiosk.
#  Pointe vers le serveur central.
# ─────────────────────────────────────────────────────────
set -e
export DEBIAN_FRONTEND=noninteractive

# Détecter le vrai utilisateur
if [ -n "$SUDO_USER" ]; then
  REAL_USER="$SUDO_USER"
elif [ "$(whoami)" = "root" ]; then
  REAL_USER=$(ls /home/ | head -1)
else
  REAL_USER="$(whoami)"
fi
REAL_HOME=$(eval echo "~$REAL_USER")
echo "→ Utilisateur détecté : $REAL_USER ($REAL_HOME)"

echo ""
echo "┌─────────────────────────────────────────────┐"
echo "│   Installation CLIENT affichage SDIS        │"
echo "│   (Raspberry Pi Zero 2 W)                   │"
echo "└─────────────────────────────────────────────┘"
echo ""

# ── URL du serveur ────────────────────────────────────────
read -rp "IP ou hostname du serveur (ex: 192.168.1.50) : " SERVER_HOST
SERVER_URL="http://${SERVER_HOST}:8000"
echo "→ URL serveur : $SERVER_URL"
echo ""

# ── Mise à jour système ───────────────────────────────────
echo "→ Mise à jour du système..."
sudo apt-get update -q && sudo apt-get full-upgrade -y -q

# ── Dépendances affichage uniquement ─────────────────────
echo "→ Installation de Chromium et X11..."
sudo apt-get install -y -q \
  chromium xserver-xorg x11-xserver-utils xinit openbox \
  unclutter-xfixes fonts-noto-color-emoji

# ── Script kiosk ─────────────────────────────────────────
KIOSK_DIR="$REAL_HOME/kiosk"
mkdir -p "$KIOSK_DIR"

cat > "$KIOSK_DIR/kiosk.sh" << EOF
#!/usr/bin/env bash
# Attendre que le serveur soit joignable
while ! curl -s -o /dev/null -m 3 ${SERVER_URL}/api/hash; do sleep 3; done

# Désactiver veille écran
xset s off
xset -dpms
xset s noblank

# Cacher le curseur
unclutter-xfixes --hide-on-touch &

# Lancer Chromium en mode kiosk
chromium \\
  --kiosk \\
  --noerrdialogs \\
  --disable-infobars \\
  --disable-session-crashed-bubble \\
  --disable-restore-session-state \\
  --disable-features=TranslateUI,Translate \\
  --disable-translate \\
  --lang=fr \\
  --check-for-update-interval=31536000 \\
  --disable-component-update \\
  --autoplay-policy=no-user-gesture-required \\
  --start-fullscreen \\
  --incognito \\
  --disable-low-end-device-mode \\
  --disable-dev-shm-usage \\
  --memory-pressure-off \\
  ${SERVER_URL}
EOF
chmod +x "$KIOSK_DIR/kiosk.sh"
chown -R "$REAL_USER:$REAL_USER" "$KIOSK_DIR"

# ── Sauvegarder l'URL serveur (pour maintenance) ─────────
echo "$SERVER_URL" > "$KIOSK_DIR/server_url"

# ── Openbox lance le kiosk au démarrage de X ──────────────
sudo -u "$REAL_USER" mkdir -p "$REAL_HOME/.config/openbox"
echo "$KIOSK_DIR/kiosk.sh &" | sudo -u "$REAL_USER" tee "$REAL_HOME/.config/openbox/autostart" > /dev/null

# ── Désactiver le blanking écran (console) ────────────────
sudo bash -c 'grep -q "consoleblank=0" /boot/firmware/cmdline.txt || sed -i "s/$/ consoleblank=0/" /boot/firmware/cmdline.txt'

# ── Auto-startx à la connexion sur tty1 ──────────────────
grep -q "startx" "$REAL_HOME/.profile" 2>/dev/null || cat >> "$REAL_HOME/.profile" << 'PROF'

# Démarrage automatique de X11 sur tty1
if [ -z "$DISPLAY" ] && [ "$(tty)" = "/dev/tty1" ]; then
  exec startx -- -nocursor 2>/dev/null
fi
PROF
chown "$REAL_USER:$REAL_USER" "$REAL_HOME/.profile"

# ── Autologin ─────────────────────────────────────────────
sudo mkdir -p /etc/systemd/system/getty@tty1.service.d
sudo tee /etc/systemd/system/getty@tty1.service.d/autologin.conf > /dev/null << EOF
[Service]
ExecStart=
ExecStart=-/sbin/agetty --autologin $REAL_USER --noclear %I \$TERM
EOF
sudo systemctl daemon-reload

# ── Désactiver les services inutiles (économie RAM) ──────
echo "→ Optimisation pour Pi Zero 2 W..."
# Désactiver Bluetooth si pas utilisé
sudo systemctl disable bluetooth 2>/dev/null || true
# Désactiver Docker si présent
if command -v docker &>/dev/null; then
  sudo systemctl disable docker 2>/dev/null || true
  sudo systemctl stop docker 2>/dev/null || true
fi

# ── Optimisation GPU memory split ─────────────────────────
# Allouer plus de RAM au GPU pour le rendu Chromium
if ! grep -q "^gpu_mem=" /boot/firmware/config.txt 2>/dev/null; then
  echo "gpu_mem=128" | sudo tee -a /boot/firmware/config.txt > /dev/null
fi

# ── Résumé ────────────────────────────────────────────────
echo ""
echo "┌─────────────────────────────────────────────┐"
echo "│   Client installé !                         │"
echo "│                                             │"
echo "│   Serveur : $SERVER_URL                     │"
echo "│                                             │"
echo "│   Au boot, l'écran affiche                  │"
echo "│   automatiquement le contenu du serveur.    │"
echo "│                                             │"
echo "│   → sudo reboot                             │"
echo "└─────────────────────────────────────────────┘"
echo ""
