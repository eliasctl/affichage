import json
import math
import re
import time
import urllib.request
from datetime import datetime
from pathlib import Path
from functools import wraps

from flask import Flask, render_template, request, redirect, url_for, session, abort, jsonify
from werkzeug.utils import secure_filename

import config
from database import (
    init_db, get_content_hash,
    get_slides, get_slide, create_slide, update_slide, delete_slide, toggle_slide, move_slide, reorder_slides,
    get_setting, set_setting,
    get_icons, add_icon, delete_icon, move_icon,
    get_ticker, create_ticker, update_ticker, delete_ticker, toggle_ticker, move_ticker,
)

app = Flask(__name__)
app.secret_key = config.SECRET_KEY
init_db()


# ── Compression gzip ─────────────────────────────────────────
@app.after_request
def add_headers(response):
    # Cache statique 1 jour
    if request.path.startswith("/static/"):
        response.headers["Cache-Control"] = "public, max-age=86400"
    return response

UPLOAD_DIR = Path(__file__).parent / "static" / "uploads"
ICONS_DIR  = Path(__file__).parent / "static" / "icons"
VIDEOS_DIR = Path(__file__).parent / "static" / "videos"
STATIC_DIR = Path(__file__).parent / "static"
ALLOWED_IMG = {"png", "jpg", "jpeg", "gif", "webp", "svg"}
ALLOWED_VID = {"mp4", "webm"}

# ── Types & Layouts ────────────────────────────────────────

SLIDE_TYPES = {
    "intervention": {"color": "#C0392B", "label": "Intervention"},
    "caserne":      {"color": "#1A5276", "label": "Vie de caserne"},
    "information":  {"color": "#566573", "label": "Information"},
}

SLIDE_LAYOUTS = {
    "annonce":   "Annonce",
    "photo":     "Photo plein écran",
    "countdown": "Compte à rebours",
    "stats":     "Statistiques",
    "video":     "Vidéo",
    "meteo":     "Météo",
}

# ── Météo ─────────────────────────────────────────────────

_weather_cache = {}
WEATHER_TTL = 600  # 10 min

WMO_DAY = {
    0: ("Ensoleillé", "☀️"), 1: ("Peu nuageux", "🌤️"),
    2: ("Partiellement nuageux", "⛅"), 3: ("Couvert", "☁️"),
    45: ("Brouillard", "🌫️"), 48: ("Brouillard givrant", "🌫️"),
    51: ("Bruine légère", "🌦️"), 53: ("Bruine", "🌦️"), 55: ("Bruine dense", "🌦️"),
    61: ("Pluie légère", "🌧️"), 63: ("Pluie", "🌧️"), 65: ("Pluie forte", "🌧️"),
    71: ("Neige légère", "❄️"), 73: ("Neige", "❄️"), 75: ("Neige forte", "❄️"),
    77: ("Grésil", "🌨️"), 80: ("Averses", "🌦️"), 81: ("Averses", "🌦️"),
    82: ("Averses violentes", "⛈️"), 85: ("Averses de neige", "🌨️"),
    86: ("Averses de neige fortes", "🌨️"), 95: ("Orage", "⛈️"),
    96: ("Orage avec grêle", "⛈️"), 99: ("Orage violent", "⛈️"),
}
WMO_NIGHT = {**WMO_DAY, 0: ("Nuit claire", "🌙"), 1: ("Nuit peu nuageuse", "🌙")}
WIND_DIRS = ["N", "NE", "E", "SE", "S", "SO", "O", "NO"]


def _wmo(code, is_day):
    return (WMO_DAY if is_day else WMO_NIGHT).get(code, ("—", "🌡️"))


def fetch_weather(lat, lon):
    key = f"{lat},{lon}"
    cached = _weather_cache.get(key)
    if cached and time.time() - cached["ts"] < WEATHER_TTL:
        return cached["data"]
    url = (
        f"https://api.open-meteo.com/v1/forecast?latitude={lat}&longitude={lon}"
        f"&current=temperature_2m,apparent_temperature,weather_code,"
        f"wind_speed_10m,wind_direction_10m,relative_humidity_2m,is_day"
        f"&hourly=temperature_2m,weather_code,precipitation_probability,is_day"
        f"&daily=weather_code,temperature_2m_max,temperature_2m_min,precipitation_probability_max"
        f"&wind_speed_unit=kmh&forecast_days=6&timezone=Europe%2FParis"
    )
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "affichage-sdis/1.0"})
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read().decode())
        c = data["current"]
        code     = c.get("weather_code", 0)
        is_day   = c.get("is_day", 1)
        desc, emoji = _wmo(code, is_day)
        wind_deg = c.get("wind_direction_10m", 0)

        # Prévisions horaires – 12 prochaines heures
        h = data.get("hourly", {})
        times = h.get("time", [])
        now_str = datetime.now().strftime("%Y-%m-%dT%H:00")
        try:
            start_i = times.index(now_str)
        except ValueError:
            start_i = 0
        forecast = []
        for i in range(start_i, min(start_i + 13, len(times))):
            fc_code = h["weather_code"][i]
            fc_day  = h["is_day"][i]
            _, fc_emoji = _wmo(fc_code, fc_day)
            hour_label = times[i][11:13] + "h"
            forecast.append({
                "hour":   hour_label,
                "temp":   round(h["temperature_2m"][i]),
                "emoji":  fc_emoji,
                "precip": h["precipitation_probability"][i],
            })

        # Prévisions journalières – 5 prochains jours (skip aujourd'hui)
        d = data.get("daily", {})
        day_names = ["Lun", "Mar", "Mer", "Jeu", "Ven", "Sam", "Dim"]
        daily = []
        for i in range(1, min(6, len(d.get("time", [])))):
            d_code = d["weather_code"][i]
            _, d_emoji = _wmo(d_code, True)
            dt = datetime.strptime(d["time"][i], "%Y-%m-%d")
            daily.append({
                "day":    day_names[dt.weekday()],
                "emoji":  d_emoji,
                "tmax":   round(d["temperature_2m_max"][i]),
                "tmin":   round(d["temperature_2m_min"][i]),
                "precip": d["precipitation_probability_max"][i],
            })

        result = {
            "temp":     round(c.get("temperature_2m", 0)),
            "feels":    round(c.get("apparent_temperature", 0)),
            "desc":     desc, "emoji": emoji,
            "wind":     round(c.get("wind_speed_10m", 0)),
            "wind_dir": WIND_DIRS[round(wind_deg / 45) % 8],
            "humidity": round(c.get("relative_humidity_2m", 0)),
            "forecast": forecast,
            "daily":    daily,
        }
        _weather_cache[key] = {"data": result, "ts": time.time()}
        return result
    except Exception:
        return None


# ── Helpers ────────────────────────────────────────────────

def strip_html(html):
    return re.sub(r"<[^>]+>", "", html or "")


def calc_duration(content, layout="annonce"):
    if layout == "video":
        return 60
    if layout == "meteo":
        return 20
    if layout == "photo":
        text = strip_html(content)
        return max(12, min(30, 10 + math.ceil(len(text) / 40)))
    if layout in ("stats", "countdown"):
        return max(20, min(45, 18 + math.ceil(len(strip_html(content)) / 40)))
    text = strip_html(content)
    if not text.strip():
        return 15
    return max(25, min(130, 25 + math.ceil(len(text) / 25)))


def allowed_img(fn):
    return "." in fn and fn.rsplit(".", 1)[1].lower() in ALLOWED_IMG


def allowed_vid(fn):
    return "." in fn and fn.rsplit(".", 1)[1].lower() in ALLOWED_VID


def login_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if not session.get("auth"):
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return wrapper


def save_file(field, dest, allowed_fn):
    f = request.files.get(field)
    if f and f.filename and allowed_fn(f.filename):
        name = secure_filename(f.filename)
        f.save(dest / name)
        return name
    return None


def save_files(field, dest, allowed_fn):
    names = []
    for f in request.files.getlist(field):
        if f and f.filename and allowed_fn(f.filename):
            name = secure_filename(f.filename)
            f.save(dest / name)
            names.append(name)
    return names


def enrich_slide(s):
    """Ajoute color, type_label, weather selon layout."""
    meta = SLIDE_TYPES.get(s.get("type", "intervention"), SLIDE_TYPES["intervention"])
    s["color"]      = meta["color"]
    s["type_label"] = meta["label"]
    if not s.get("duration"):
        s["duration"] = calc_duration(s.get("content", ""), s.get("layout", "annonce"))
    if s.get("layout") == "meteo":
        ex = s.get("extra", {})
        s["weather"] = fetch_weather(ex.get("lat", 48.4), ex.get("lon", 2.7))
    return s


# ── Display ────────────────────────────────────────────────

@app.route("/")
def display():
    slides  = [enrich_slide(s) for s in get_slides(active_only=True)]
    icons   = get_icons()
    ci_name = get_setting("ci_name", "CIS Fontainebleau")
    ticker  = get_ticker(active_only=True)
    logo    = get_setting("logo", "logo-sdis.png")
    return render_template("display.html", slides=slides, icons=icons,
                           ci_name=ci_name, ticker=ticker, logo=logo)


@app.route("/api/display")
def api_display():
    slides  = [enrich_slide(s) for s in get_slides(active_only=True)]
    icons   = get_icons()
    ci_name = get_setting("ci_name", "CIS Fontainebleau")
    ticker  = get_ticker(active_only=True)
    logo    = get_setting("logo", "logo-sdis.png")
    return jsonify(slides=slides, icons=icons, ci_name=ci_name,
                   ticker=ticker, logo=logo)


@app.route("/api/hash")
def api_hash():
    """Hash léger mis en cache pour détecter les changements (polling)."""
    return jsonify(hash=get_content_hash())


# ── Auth ───────────────────────────────────────────────────

@app.route("/login", methods=["GET", "POST"])
def login():
    error = None
    if request.method == "POST":
        if request.form.get("password") == config.ADMIN_PASSWORD:
            session["auth"] = True
            return redirect(url_for("admin_index"))
        error = "Mot de passe incorrect."
    return render_template("login.html", error=error)


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


# ── Admin – Slides ─────────────────────────────────────────

@app.route("/admin")
@login_required
def admin_index():
    slides = get_slides(active_only=False)
    return render_template("admin/index.html", slides=slides,
                           calc_duration=calc_duration,
                           type_colors={k: v["color"] for k, v in SLIDE_TYPES.items()},
                           type_labels={k: v["label"] for k, v in SLIDE_TYPES.items()},
                           layout_labels=SLIDE_LAYOUTS)


def _slide_extra_from_form():
    layout = request.form.get("layout", "annonce")
    extra  = {}
    if layout == "countdown":
        t = request.form.get("cd_target", "").strip()
        # datetime-local donne "YYYY-MM-DDTHH:MM" — normalise avec secondes
        if t and len(t) == 16:
            t += ":00"
        extra["target"] = t
    elif layout == "stats":
        try:
            extra["items"] = json.loads(request.form.get("stats_json", "[]"))
        except Exception:
            extra["items"] = []
    elif layout == "meteo":
        extra["lat"]  = request.form.get("meteo_lat", "48.4")
        extra["lon"]  = request.form.get("meteo_lon", "2.7")
        extra["city"] = request.form.get("meteo_city", "")
    return layout, extra


@app.route("/admin/new", methods=["GET", "POST"])
@login_required
def admin_new():
    if request.method == "POST":
        title      = request.form.get("title", "").strip()
        content    = request.form.get("content", "").strip()
        slide_type = request.form.get("type", "intervention")
        if slide_type not in SLIDE_TYPES:
            slide_type = "intervention"
        layout, extra = _slide_extra_from_form()
        images = save_files("images", UPLOAD_DIR, allowed_img)
        if layout == "video":
            vf = save_file("video_file", VIDEOS_DIR, allowed_vid)
            if vf:
                extra["filename"] = vf
        create_slide(title=title, content=content, slide_type=slide_type,
                     layout=layout, images=images, extra=extra, duration=None)
        return redirect(url_for("admin_index"))
    return render_template("admin/slide_form.html", slide=None,
                           slide_types=SLIDE_TYPES, slide_layouts=SLIDE_LAYOUTS)


@app.route("/admin/edit/<int:sid>", methods=["GET", "POST"])
@login_required
def admin_edit(sid):
    slide = get_slide(sid)
    if not slide:
        abort(404)
    if request.method == "POST":
        title      = request.form.get("title", "").strip()
        content    = request.form.get("content", "").strip()
        slide_type = request.form.get("type", "intervention")
        if slide_type not in SLIDE_TYPES:
            slide_type = "intervention"
        layout, extra = _slide_extra_from_form()

        to_delete = set(request.form.getlist("delete_img"))
        kept      = [img for img in slide["images"] if img not in to_delete]
        new_imgs  = save_files("images", UPLOAD_DIR, allowed_img)
        images    = kept + new_imgs

        if layout == "video":
            vf = save_file("video_file", VIDEOS_DIR, allowed_vid)
            if vf:
                extra["filename"] = vf
            elif slide.get("layout") == "video" and slide["extra"].get("filename"):
                extra["filename"] = slide["extra"]["filename"]  # keep existing

        update_slide(sid, title=title, content=content, slide_type=slide_type,
                     layout=layout, images=images, extra=extra, duration=None)
        return redirect(url_for("admin_index"))
    return render_template("admin/slide_form.html", slide=slide,
                           slide_types=SLIDE_TYPES, slide_layouts=SLIDE_LAYOUTS)


@app.route("/admin/delete/<int:sid>", methods=["POST"])
@login_required
def admin_delete(sid):
    delete_slide(sid); return redirect(url_for("admin_index"))


@app.route("/admin/toggle/<int:sid>", methods=["POST"])
@login_required
def admin_toggle(sid):
    toggle_slide(sid); return redirect(url_for("admin_index"))


@app.route("/admin/move/<int:sid>/<direction>", methods=["POST"])
@login_required
def admin_move(sid, direction):
    if direction in ("up", "down"):
        move_slide(sid, direction)
    return redirect(url_for("admin_index"))


@app.route("/admin/reorder", methods=["POST"])
@login_required
def admin_reorder():
    ids = request.get_json(silent=True, force=True) or {}
    ids = ids.get("ids", [])
    if ids:
        reorder_slides([int(i) for i in ids])
    return jsonify(ok=True)


# ── Admin – Paramètres ─────────────────────────────────────

@app.route("/admin/settings", methods=["GET", "POST"])
@login_required
def admin_settings():
    if request.method == "POST":
        action = request.form.get("action")
        if action == "save_ci":
            set_setting("ci_name", request.form.get("ci_name", "").strip())
        elif action == "save_logo":
            f = request.files.get("logo_file")
            if f and f.filename and allowed_img(f.filename):
                ext = f.filename.rsplit(".", 1)[1].lower()
                filename = f"logo.{ext}"
                f.save(UPLOAD_DIR / filename)
                set_setting("logo", f"uploads/{filename}")
        elif action == "add_icon":
            fn = save_file("icon_file", ICONS_DIR, allowed_img)
            if fn:
                add_icon(fn, request.form.get("icon_label", "").strip())
        elif action == "delete_icon":
            delete_icon(int(request.form.get("icon_id")))
        elif action in ("move_icon_up", "move_icon_down"):
            move_icon(int(request.form.get("icon_id")),
                      "up" if action == "move_icon_up" else "down")
        return redirect(url_for("admin_settings"))
    return render_template("admin/settings.html",
                           ci_name=get_setting("ci_name", "CIS Fontainebleau"),
                           logo=get_setting("logo", "logo-sdis.png"),
                           icons=get_icons())


# ── Admin – Bandeau ticker ─────────────────────────────────

@app.route("/admin/ticker", methods=["GET", "POST"])
@login_required
def admin_ticker():
    if request.method == "POST":
        action = request.form.get("action")
        if action == "add":
            text = request.form.get("text", "").strip()
            if text:
                create_ticker(text)
        elif action == "edit":
            update_ticker(int(request.form.get("tid")),
                          request.form.get("text", "").strip())
        elif action == "delete":
            delete_ticker(int(request.form.get("tid")))
        elif action == "toggle":
            toggle_ticker(int(request.form.get("tid")))
        elif action in ("up", "down"):
            move_ticker(int(request.form.get("tid")), action)
        return redirect(url_for("admin_ticker"))
    return render_template("admin/ticker.html", items=get_ticker(active_only=False))


# ── Lancement ──────────────────────────────────────────────

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000, debug=False)
