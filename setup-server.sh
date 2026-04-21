#!/usr/bin/env bash
set -e
export DEBIAN_FRONTEND=noninteractive

DIR="$(cd "$(dirname "$0")" && pwd)"

# Détecter le vrai utilisateur (même si lancé avec sudo/root)
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
echo "│   Installation SERVEUR affichage SDIS       │"
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

# ── Dépendances Python ───────────────────────────────────
echo "→ Installation des dépendances..."
sudo apt-get install -y -q python3 python3-venv

# ── Environnement virtuel Python ──────────────────────────
echo "→ Configuration de l'environnement Python..."
python3 -m venv "$DIR/venv"
"$DIR/venv/bin/pip" install --upgrade pip
"$DIR/venv/bin/pip" install flask

# ── Créer les dossiers et fixer les permissions ───────────
mkdir -p "$DIR/data" "$DIR/static/uploads" "$DIR/static/icons" "$DIR/static/videos"
chown -R "$REAL_USER:$REAL_USER" "$DIR"

# ── Service systemd Flask ─────────────────────────────────
echo "→ Configuration du service Flask..."
sudo tee /etc/systemd/system/affichage-flask.service > /dev/null << EOF
[Unit]
Description=Affichage SDIS (Flask)
After=network.target

[Service]
Type=simple
User=$REAL_USER
WorkingDirectory=$DIR
ExecStart=$DIR/venv/bin/python $DIR/app.py
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable affichage-flask.service
sudo systemctl restart affichage-flask.service

# ── Résumé ────────────────────────────────────────────────
IP=$(hostname -I | awk '{print $1}')
echo ""
echo "┌─────────────────────────────────────────────┐"
echo "│   Serveur installé !                        │"
echo "│                                             │"
echo "│   API :   http://$IP:8000                   │"
echo "│   Admin : http://$IP:8000/admin             │"
echo "│                                             │"
echo "│   Utilisez cette IP pour configurer les     │"
echo "│   écrans clients (setup-client.sh).         │"
echo "└─────────────────────────────────────────────┘"
echo ""
