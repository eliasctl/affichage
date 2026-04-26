#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────
#  Setup écran client — Raspberry Pi Zero 2 W
#  OS recommandé : DietPi (ARMv8 / Aarch64)
#  Installe surf (navigateur WebKit léger) en kiosk.
#  Pointe vers le serveur central.
# ─────────────────────────────────────────────────────────
set -e
export DEBIAN_FRONTEND=noninteractive

# Détecter le vrai utilisateur
if [ -n "$SUDO_USER" ]; then
  REAL_USER="$SUDO_USER"
elif [ "$(whoami)" = "root" ]; then
  REAL_USER=$(ls /home/ | head -1 2>/dev/null || echo "dietpi")
else
  REAL_USER="$(whoami)"
fi
REAL_HOME=$(eval echo "~$REAL_USER")
echo "→ Utilisateur détecté : $REAL_USER ($REAL_HOME)"

echo ""
echo "┌─────────────────────────────────────────────┐"
echo "│   Installation CLIENT affichage SDIS        │"
echo "│   (Pi Zero 2 W — DietPi + surf)            │"
echo "└─────────────────────────────────────────────┘"
echo ""

# ── URL du serveur ────────────────────────────────────────
echo "Entrez l'adresse du serveur :"
echo "  - IP locale       : 192.168.1.50  (→ http://192.168.1.50:8000)"
echo "  - Nom de domaine  : affichage.exemple.fr  (→ https://affichage.exemple.fr)"
echo ""
read -rp "IP ou domaine : " SERVER_HOST

# Nettoyer un éventuel http:// ou https:// saisi par l'utilisateur
SERVER_HOST=$(echo "$SERVER_HOST" | sed -E 's|^https?://||' | sed 's|/$||')

# Détection automatique : domaine → HTTPS sans port / IP → HTTP:8000
if echo "$SERVER_HOST" | grep -qP '^[0-9.]+$'; then
  SERVER_URL="http://${SERVER_HOST}:8000"
else
  SERVER_URL="https://${SERVER_HOST}"
fi
echo "→ URL serveur : $SERVER_URL"
echo ""

# ── Token d'accès écran ──────────────────────────────────
echo "Token d'accès écran (visible dans l'admin > Paramètres) :"
read -rp "Token : " DISPLAY_TOKEN
if [ -z "$DISPLAY_TOKEN" ]; then
  echo "✗ Token requis pour autoriser l'écran." >&2
  exit 1
fi

DISPLAY_URL="${SERVER_URL}/?token=${DISPLAY_TOKEN}"
echo "→ URL écran : $DISPLAY_URL"
echo ""

# ── Mise à jour système ───────────────────────────────────
echo "→ Mise à jour du système..."
apt-get update -q && apt-get full-upgrade -y -q

# ── Dépendances : surf + X11 minimal ────────────────────
echo "→ Installation de surf et X11..."
apt-get install -y -q \
  surf xserver-xorg x11-xserver-utils xinit openbox \
  unclutter-xfixes xdotool fonts-noto-color-emoji

# ── Désactiver les services inutiles ─────────────────────
echo "→ Optimisation pour Pi Zero 2 W..."
systemctl disable bluetooth 2>/dev/null || true
systemctl disable avahi-daemon 2>/dev/null || true
systemctl disable triggerhappy 2>/dev/null || true
systemctl disable hciuart 2>/dev/null || true
# Réduire la consommation RAM au maximum
systemctl disable rsyslog 2>/dev/null || true
systemctl disable cron 2>/dev/null || true

# ── Swap optimisé (Pi Zero = 512 Mo RAM) ─────────────────
if [ -f /etc/dphys-swapfile ]; then
  sed -i 's/^CONF_SWAPSIZE=.*/CONF_SWAPSIZE=256/' /etc/dphys-swapfile
  systemctl restart dphys-swapfile 2>/dev/null || true
fi

# ── Script kiosk ─────────────────────────────────────────
KIOSK_DIR="$REAL_HOME/kiosk"
mkdir -p "$KIOSK_DIR"

cat > "$KIOSK_DIR/kiosk.sh" << EOF
#!/usr/bin/env bash
# Attendre que le serveur soit joignable (ping non authentifié)
while ! curl -s -o /dev/null -m 3 ${SERVER_URL}/login; do sleep 3; done

# Désactiver veille écran
xset s off
xset -dpms
xset s noblank

# Cacher le curseur
unclutter-xfixes --hide-on-touch &

# Lancer surf en plein écran — token d'accès écran
# Le serveur valide le token et pose un cookie longue durée (10 ans).
surf -F "${DISPLAY_URL}" &
SURF_PID=\$!

# Forcer le plein écran
sleep 2
WID=\$(xdotool search --pid \$SURF_PID 2>/dev/null | head -1)
if [ -n "\$WID" ]; then
  xdotool windowfocus \$WID
  xdotool windowsize \$WID 100% 100%
  xdotool windowmove \$WID 0 0
fi

wait \$SURF_PID
EOF
chmod +x "$KIOSK_DIR/kiosk.sh"
chown -R "$REAL_USER:$REAL_USER" "$KIOSK_DIR"

# ── Sauvegarder l'URL serveur (pour maintenance) ─────────
echo "$SERVER_URL" > "$KIOSK_DIR/server_url"
echo "$DISPLAY_URL" > "$KIOSK_DIR/display_url"

# ── Openbox lance le kiosk au démarrage de X ──────────────
sudo -u "$REAL_USER" mkdir -p "$REAL_HOME/.config/openbox"
echo "$KIOSK_DIR/kiosk.sh &" | sudo -u "$REAL_USER" tee "$REAL_HOME/.config/openbox/autostart" > /dev/null

# ── Désactiver le blanking écran (console) ────────────────
if [ -f /boot/firmware/cmdline.txt ]; then
  grep -q "consoleblank=0" /boot/firmware/cmdline.txt || sed -i "s/$/ consoleblank=0/" /boot/firmware/cmdline.txt
elif [ -f /boot/cmdline.txt ]; then
  grep -q "consoleblank=0" /boot/cmdline.txt || sed -i "s/$/ consoleblank=0/" /boot/cmdline.txt
fi

# ── Auto-startx à la connexion sur tty1 ──────────────────
grep -q "startx" "$REAL_HOME/.bashrc" 2>/dev/null || cat >> "$REAL_HOME/.bashrc" << 'PROF'

# Démarrage automatique de X11 sur tty1
if [ -z "$DISPLAY" ] && [ "$(tty)" = "/dev/tty1" ]; then
  exec startx -- -nocursor 2>/dev/null
fi
PROF

# ── Autologin ─────────────────────────────────────────────
mkdir -p /etc/systemd/system/getty@tty1.service.d
tee /etc/systemd/system/getty@tty1.service.d/autologin.conf > /dev/null << EOF
[Service]
ExecStart=
ExecStart=-/sbin/agetty --autologin $REAL_USER --noclear %I \$TERM
EOF
systemctl daemon-reload

# ── GPU memory split (128 Mo pour le rendu) ───────────────
CFG=""
[ -f /boot/firmware/config.txt ] && CFG="/boot/firmware/config.txt"
[ -f /boot/config.txt ] && CFG="/boot/config.txt"
[ -f /boot/dietpi.txt ] && CFG="/boot/config.txt"
if [ -n "$CFG" ]; then
  grep -q "^gpu_mem=" "$CFG" || echo "gpu_mem=128" >> "$CFG"
fi

# ── Résumé ────────────────────────────────────────────────
echo ""
echo "┌─────────────────────────────────────────────┐"
echo "│   Client installé !                         │"
echo "│                                             │"
echo "│   Navigateur : surf (WebKit léger)          │"
echo "│   Mode       : kiosk plein écran             │"
echo "│   Serveur    : $SERVER_URL                  │"
echo "│   Token écran configuré ✓                   │"
echo "│                                             │"
echo "│   → sudo reboot                             │"
echo "└─────────────────────────────────────────────┘"
echo ""
