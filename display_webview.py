#!/usr/bin/env python3
"""
Affichage SDIS — Rendu via WebView natif (WebKit/GTK).

Ouvre la page web Flask dans une fenêtre plein écran légère,
sans navigateur complet (Chrome/Chromium).
Rendu identique à la vue web, consommation mémoire réduite.
"""

import os
import sys
import time
import subprocess
import threading
import urllib.request

FLASK_URL = os.environ.get("FLASK_URL", "http://localhost:8000")
WAIT_TIMEOUT = int(os.environ.get("WAIT_TIMEOUT", "30"))


def wait_for_flask(url, timeout=WAIT_TIMEOUT):
    """Attend que le serveur Flask soit disponible."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            urllib.request.urlopen(url, timeout=2)
            return True
        except Exception:
            time.sleep(1)
    return False


def hide_cursor():
    """Cache le curseur souris (utile en mode kiosk sur RPi)."""
    try:
        subprocess.Popen(
            ["unclutter", "-idle", "0.1", "-root"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except FileNotFoundError:
        pass  # unclutter non installé, pas grave


def main():
    print(f"[display_webview] Attente du serveur Flask sur {FLASK_URL}...")
    if not wait_for_flask(FLASK_URL):
        print(f"[display_webview] ERREUR : Flask non disponible après {WAIT_TIMEOUT}s", file=sys.stderr)
        sys.exit(1)
    print("[display_webview] Serveur Flask disponible.")

    hide_cursor()

    try:
        import webview
    except ImportError:
        print(
            "[display_webview] ERREUR : pywebview non installé.\n"
            "  Installez-le avec : pip install pywebview\n"
            "  Sur RPi/Debian    : sudo apt install python3-gi python3-gi-cairo "
            "gir1.2-gtk-3.0 gir1.2-webkit2-4.1 && pip install pywebview",
            file=sys.stderr,
        )
        sys.exit(1)

    window = webview.create_window(
        title="Affichage SDIS",
        url=FLASK_URL,
        fullscreen=True,
        frameless=True,
        easy_drag=False,
        text_select=False,
    )

    # Relancer la page si déconnexion réseau / erreur de chargement
    def watchdog():
        """Vérifie la connectivité et recharge si nécessaire."""
        while True:
            time.sleep(60)
            try:
                urllib.request.urlopen(FLASK_URL, timeout=5)
            except Exception:
                continue
            try:
                window.evaluate_js(
                    "if(document.title===''){location.reload();}"
                )
            except Exception:
                pass

    threading.Thread(target=watchdog, daemon=True).start()

    print("[display_webview] Lancement de l'affichage plein écran...")
    webview.start(
        debug=("--debug" in sys.argv),
        gui="gtk",  # WebKitGTK sur Linux — léger et rapide
    )


if __name__ == "__main__":
    main()
