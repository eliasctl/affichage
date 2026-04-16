#!/usr/bin/env python3
"""
Affichage SDIS — Rendu direct framebuffer via Pygame (sans navigateur).

Lit les données depuis l'API Flask locale et rend les slides
directement sur l'écran via SDL/KMS-DRM.
"""

import io
import json
import math
import os
import re
import subprocess
import sys
import time
import urllib.request
from datetime import datetime
from pathlib import Path

os.environ.setdefault("SDL_VIDEODRIVER", "kmsdrm")
os.environ["SDL_NOMOUSE"] = "1"

import pygame
import pygame.freetype

# ── Configuration ─────────────────────────────────────────────

API_URL = os.environ.get("API_URL", "http://localhost:8000/api/display")
STATIC_URL = os.environ.get("STATIC_URL", "http://localhost:8000/static")
FETCH_INTERVAL = 30  # seconds between API polls
FPS = 30

# Couleurs SDIS
COLORS = {
    "intervention": (192, 57, 43),
    "caserne":      (26, 82, 118),
    "information":  (86, 101, 115),
}
WHITE = (255, 255, 255)
BLACK = (0, 0, 0)
DARK_BG = (20, 20, 30)
HEADER_BG = (15, 15, 25)
TICKER_BG = (10, 10, 20)
ACCENT = (52, 152, 219)


def strip_html(html):
    return re.sub(r"<[^>]+>", "", html or "")


# ── Display Engine ────────────────────────────────────────────

class SDISDisplay:
    def __init__(self):
        pygame.init()
        pygame.mouse.set_visible(False)

        # Detect screen size
        info = pygame.display.Info()
        self.W = info.current_w or 1920
        self.H = info.current_h or 1080

        try:
            self.screen = pygame.display.set_mode(
                (self.W, self.H), pygame.FULLSCREEN | pygame.NOFRAME
            )
        except pygame.error:
            # Fallback: try fbdev driver
            os.environ["SDL_VIDEODRIVER"] = "fbdev"
            pygame.display.quit()
            pygame.display.init()
            info = pygame.display.Info()
            self.W = info.current_w or 1920
            self.H = info.current_h or 1080
            self.screen = pygame.display.set_mode(
                (self.W, self.H), pygame.FULLSCREEN | pygame.NOFRAME
            )

        pygame.display.set_caption("Affichage SDIS")
        self.clock = pygame.time.Clock()

        # Layout metrics
        self.header_h = int(self.H * 0.07)
        self.ticker_h = int(self.H * 0.06)
        self.sidebar_w = int(self.W * 0.06)
        self.main_x = self.sidebar_w
        self.main_y = self.header_h
        self.main_w = self.W - self.sidebar_w
        self.main_h = self.H - self.header_h - self.ticker_h

        # Fonts — try common paths on RPi
        font_paths = [
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
            "/usr/share/fonts/truetype/freefont/FreeSans.ttf",
            "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
            None,  # pygame default
        ]
        self.font_path = None
        for fp in font_paths:
            if fp and Path(fp).exists():
                self.font_path = fp
                break

        self.font_title = self._make_font(int(self.H * 0.055))
        self.font_subtitle = self._make_font(int(self.H * 0.035))
        self.font_text = self._make_font(int(self.H * 0.030))
        self.font_small = self._make_font(int(self.H * 0.022))
        self.font_clock = self._make_font(int(self.H * 0.025))
        self.font_ticker = self._make_font(int(self.H * 0.028))
        self.font_huge = self._make_font(int(self.H * 0.12))
        self.font_big = self._make_font(int(self.H * 0.07))
        self.font_emoji = self._make_font(int(self.H * 0.06))

        # State
        self.slides = []
        self.icons_data = []
        self.ticker_items = []
        self.ci_name = "CIS Fontainebleau"
        self.logo_name = "logo-sdis.png"
        self.current_idx = 0
        self.slide_start = time.time()
        self.last_fetch = 0
        self.image_cache = {}
        self.logo_surface = None
        self.icon_surfaces = []

        # Ticker scroll
        self.ticker_offset = 0

        # Transition
        self.transitioning = False
        self.transition_alpha = 0
        self.prev_surface = None
        self.next_surface = None

    def _make_font(self, size):
        if self.font_path:
            return pygame.font.Font(self.font_path, size)
        return pygame.font.SysFont("sans", size)

    # ── Network ───────────────────────────────────────────────

    def fetch_data(self):
        try:
            req = urllib.request.Request(
                API_URL, headers={"User-Agent": "affichage-sdis-fb/1.0"}
            )
            with urllib.request.urlopen(req, timeout=5) as resp:
                data = json.loads(resp.read().decode())
            self.slides = data.get("slides", [])
            self.icons_data = data.get("icons", [])
            self.ticker_items = data.get("ticker", [])
            self.ci_name = data.get("ci_name", "CIS Fontainebleau")
            self.logo_name = data.get("logo", "logo-sdis.png")
            self.last_fetch = time.time()

            # Preload logo
            self.logo_surface = self._load_image(
                f"/{self.logo_name}",
                (int(self.header_h * 0.7), int(self.header_h * 0.7)),
            )

            # Preload icons
            self.icon_surfaces = []
            icon_size = int(self.sidebar_w * 0.6)
            for ic in self.icons_data:
                surf = self._load_image(
                    f"/icons/{ic['filename']}", (icon_size, icon_size)
                )
                self.icon_surfaces.append((surf, ic.get("label", "")))

            # Preload slide images
            for slide in self.slides:
                for img_name in slide.get("images", []):
                    self._load_image(f"/uploads/{img_name}")
                if slide.get("layout") == "video":
                    fn = slide.get("extra", {}).get("filename")
                    if fn:
                        self._load_image(f"/videos/{fn}")

            # Reset index if out of bounds
            if self.current_idx >= len(self.slides):
                self.current_idx = 0

        except Exception as e:
            print(f"[fetch] Erreur: {e}", file=sys.stderr)

    def _load_image(self, path, size=None):
        cache_key = (path, size)
        if cache_key in self.image_cache:
            return self.image_cache[cache_key]
        url = STATIC_URL + path
        try:
            req = urllib.request.Request(
                url, headers={"User-Agent": "affichage-sdis-fb/1.0"}
            )
            with urllib.request.urlopen(req, timeout=10) as resp:
                raw = resp.read()
            surf = pygame.image.load(io.BytesIO(raw))
            if size:
                surf = pygame.transform.smoothscale(surf, size)
            self.image_cache[cache_key] = surf
            return surf
        except Exception as e:
            print(f"[img] {path}: {e}", file=sys.stderr)
            return None

    def _fit_image(self, path, max_w, max_h):
        """Load and scale image to fit within max_w x max_h, keeping aspect."""
        surf = self._load_image(path)
        if not surf:
            return None
        iw, ih = surf.get_size()
        scale = min(max_w / iw, max_h / ih, 1.0)
        new_w = int(iw * scale)
        new_h = int(ih * scale)
        key = (path, (new_w, new_h))
        if key in self.image_cache:
            return self.image_cache[key]
        scaled = pygame.transform.smoothscale(surf, (new_w, new_h))
        self.image_cache[key] = scaled
        return scaled

    # ── Text helpers ──────────────────────────────────────────

    def _wrap_text(self, text, font, max_width):
        """Word-wrap text and return list of lines."""
        words = text.split()
        lines = []
        current = ""
        for word in words:
            test = f"{current} {word}".strip() if current else word
            tw, _ = font.size(test)
            if tw > max_width and current:
                lines.append(current)
                current = word
            else:
                current = test
        if current:
            lines.append(current)
        return lines or [""]

    def _render_text_block(self, surface, text, font, color, x, y, max_w, max_h, line_spacing=1.3):
        """Render wrapped text block. Returns final y position."""
        text = strip_html(text)
        paragraphs = text.split("\n")
        cy = y
        line_h = int(font.get_height() * line_spacing)
        for para in paragraphs:
            if not para.strip():
                cy += line_h
                continue
            lines = self._wrap_text(para.strip(), font, max_w)
            for line in lines:
                if cy + line_h > y + max_h:
                    return cy
                rendered = font.render(line, True, color)
                surface.blit(rendered, (x, cy))
                cy += line_h
        return cy

    # ── Slide Renderers ───────────────────────────────────────

    def _get_bg_color(self, slide):
        return COLORS.get(slide.get("type", "intervention"), COLORS["intervention"])

    def _render_slide(self, slide):
        """Render a single slide to a surface."""
        surf = pygame.Surface((self.main_w, self.main_h))
        bg = self._get_bg_color(slide)
        surf.fill(bg)

        layout = slide.get("layout", "annonce")
        renderer = {
            "annonce": self._render_annonce,
            "photo": self._render_photo,
            "countdown": self._render_countdown,
            "stats": self._render_stats,
            "video": self._render_video_placeholder,
            "meteo": self._render_meteo,
        }.get(layout, self._render_annonce)

        renderer(surf, slide, bg)
        return surf

    def _render_annonce(self, surf, slide, bg):
        w, h = surf.get_size()
        pad = int(w * 0.04)
        images = slide.get("images", [])

        # Decide layout: text left, images right (or full width if no images)
        if images:
            text_w = int(w * 0.55)
            img_area_x = text_w + pad
            img_area_w = w - img_area_x - pad
        else:
            text_w = w - pad * 2
            img_area_x = 0
            img_area_w = 0

        # Title
        title = slide.get("title", "")
        y = pad
        if title:
            rendered = self.font_title.render(title, True, WHITE)
            surf.blit(rendered, (pad, y))
            y += self.font_title.get_height() + int(pad * 0.5)

        # Separator line
        pygame.draw.line(surf, (*WHITE[:3], 80), (pad, y), (text_w, y), 2)
        y += int(pad * 0.5)

        # Content
        content = slide.get("content", "")
        if content:
            self._render_text_block(
                surf, content, self.font_text, WHITE,
                pad, y, text_w - pad, h - y - pad
            )

        # Images on right side
        if images:
            img_y = pad
            remaining_h = h - pad * 2
            per_img_h = remaining_h // len(images) if images else remaining_h
            for img_name in images:
                img_surf = self._fit_image(
                    f"/uploads/{img_name}", img_area_w, per_img_h - int(pad * 0.5)
                )
                if img_surf:
                    iw, ih = img_surf.get_size()
                    ix = img_area_x + (img_area_w - iw) // 2
                    iy = img_y + (per_img_h - ih) // 2
                    surf.blit(img_surf, (ix, iy))
                img_y += per_img_h

    def _render_photo(self, surf, slide, bg):
        w, h = surf.get_size()
        images = slide.get("images", [])
        if images:
            img_surf = self._fit_image(f"/uploads/{images[0]}", w, h)
            if img_surf:
                iw, ih = img_surf.get_size()
                surf.blit(img_surf, ((w - iw) // 2, (h - ih) // 2))

        # Caption overlay at bottom
        content = strip_html(slide.get("content", ""))
        if content:
            overlay = pygame.Surface((w, int(h * 0.15)), pygame.SRCALPHA)
            overlay.fill((0, 0, 0, 160))
            surf.blit(overlay, (0, h - int(h * 0.15)))
            self._render_text_block(
                surf, content, self.font_subtitle, WHITE,
                int(w * 0.04), h - int(h * 0.13),
                w - int(w * 0.08), int(h * 0.12)
            )

    def _render_countdown(self, surf, slide, bg):
        w, h = surf.get_size()
        pad = int(w * 0.04)

        # Title
        title = slide.get("title", "")
        y = int(h * 0.1)
        if title:
            rendered = self.font_title.render(title, True, WHITE)
            tx = (w - rendered.get_width()) // 2
            surf.blit(rendered, (tx, y))
            y += self.font_title.get_height() + pad

        # Calculate remaining time
        target_str = slide.get("extra", {}).get("target", "")
        if target_str:
            try:
                target = datetime.strptime(target_str, "%Y-%m-%dT%H:%M:%S")
                delta = target - datetime.now()
                total_secs = max(0, int(delta.total_seconds()))
                days = total_secs // 86400
                hours = (total_secs % 86400) // 3600
                mins = (total_secs % 3600) // 60
                secs = total_secs % 60
            except Exception:
                days = hours = mins = secs = 0
        else:
            days = hours = mins = secs = 0

        # Render countdown blocks
        blocks = [
            (str(days), "JOURS"),
            (str(hours).zfill(2), "HEURES"),
            (str(mins).zfill(2), "MINUTES"),
            (str(secs).zfill(2), "SECONDES"),
        ]
        block_w = int(w * 0.18)
        total_w = block_w * len(blocks) + pad * (len(blocks) - 1)
        start_x = (w - total_w) // 2
        cy = int(h * 0.35)

        for i, (val, label) in enumerate(blocks):
            bx = start_x + i * (block_w + pad)
            # Background box
            box_rect = pygame.Rect(bx, cy, block_w, int(h * 0.35))
            pygame.draw.rect(surf, (0, 0, 0, 80), box_rect, border_radius=12)
            pygame.draw.rect(surf, WHITE, box_rect, 2, border_radius=12)

            # Number
            num_surf = self.font_huge.render(val, True, WHITE)
            nx = bx + (block_w - num_surf.get_width()) // 2
            ny = cy + int(h * 0.05)
            surf.blit(num_surf, (nx, ny))

            # Label
            lbl_surf = self.font_small.render(label, True, (200, 200, 200))
            lx = bx + (block_w - lbl_surf.get_width()) // 2
            ly = cy + int(h * 0.27)
            surf.blit(lbl_surf, (lx, ly))

    def _render_stats(self, surf, slide, bg):
        w, h = surf.get_size()
        pad = int(w * 0.04)

        # Title
        title = slide.get("title", "")
        y = pad
        if title:
            rendered = self.font_title.render(title, True, WHITE)
            tx = (w - rendered.get_width()) // 2
            surf.blit(rendered, (tx, y))
            y += self.font_title.get_height() + pad

        items = slide.get("extra", {}).get("items", [])
        if not items:
            return

        # Grid layout
        cols = min(4, len(items))
        rows = math.ceil(len(items) / cols)
        card_w = int((w - pad * (cols + 1)) / cols)
        card_h = int((h - y - pad * (rows + 1)) / rows)

        for idx, item in enumerate(items):
            col = idx % cols
            row = idx // cols
            cx = pad + col * (card_w + pad)
            cy = y + pad + row * (card_h + pad)

            # Card background
            card_rect = pygame.Rect(cx, cy, card_w, card_h)
            darker = tuple(max(0, c - 30) for c in bg)
            pygame.draw.rect(surf, darker, card_rect, border_radius=10)
            pygame.draw.rect(surf, (255, 255, 255, 40), card_rect, 1, border_radius=10)

            # Emoji
            emoji = item.get("emoji", "")
            if emoji:
                e_surf = self.font_emoji.render(emoji, True, WHITE)
                ex = cx + (card_w - e_surf.get_width()) // 2
                surf.blit(e_surf, (ex, cy + int(card_h * 0.05)))

            # Value
            val = str(item.get("value", ""))
            v_surf = self.font_big.render(val, True, WHITE)
            vx = cx + (card_w - v_surf.get_width()) // 2
            surf.blit(v_surf, (vx, cy + int(card_h * 0.35)))

            # Label
            label = item.get("label", "")
            l_surf = self.font_small.render(label, True, (200, 200, 200))
            lx = cx + (card_w - l_surf.get_width()) // 2
            surf.blit(l_surf, (lx, cy + int(card_h * 0.75)))

    def _render_video_placeholder(self, surf, slide, bg):
        """Render placeholder — actual video playback uses mpv subprocess."""
        w, h = surf.get_size()
        title = slide.get("title", "Video")
        rendered = self.font_title.render(title, True, WHITE)
        surf.blit(rendered, ((w - rendered.get_width()) // 2, h // 2 - 30))

    def _render_meteo(self, surf, slide, bg):
        w, h = surf.get_size()
        pad = int(w * 0.04)
        weather = slide.get("weather")
        city = slide.get("extra", {}).get("city", "")

        if not weather:
            msg = self.font_title.render("Meteo indisponible", True, WHITE)
            surf.blit(msg, ((w - msg.get_width()) // 2, h // 2 - 30))
            return

        # City name
        y = pad
        city_text = city or self.ci_name
        rendered = self.font_title.render(f"Meteo — {city_text}", True, WHITE)
        surf.blit(rendered, (pad, y))
        y += self.font_title.get_height() + pad

        # Current weather
        emoji_surf = self.font_huge.render(weather.get("emoji", ""), True, WHITE)
        surf.blit(emoji_surf, (pad, y))

        temp_text = f"{weather.get('temp', '—')}°C"
        temp_surf = self.font_huge.render(temp_text, True, WHITE)
        surf.blit(temp_surf, (pad + int(w * 0.15), y))

        desc_surf = self.font_subtitle.render(weather.get("desc", ""), True, (220, 220, 220))
        surf.blit(desc_surf, (pad + int(w * 0.15), y + self.font_huge.get_height()))

        # Details
        details_y = y + self.font_huge.get_height() + self.font_subtitle.get_height() + pad
        details = [
            f"Ressenti: {weather.get('feels', '—')}°C",
            f"Vent: {weather.get('wind', '—')} km/h {weather.get('wind_dir', '')}",
            f"Humidite: {weather.get('humidity', '—')}%",
        ]
        for d in details:
            d_surf = self.font_text.render(d, True, (200, 200, 200))
            surf.blit(d_surf, (pad, details_y))
            details_y += self.font_text.get_height() + 5

        # Forecast bar at bottom
        forecast = weather.get("forecast", [])
        if forecast:
            fc_y = int(h * 0.65)
            fc_w = (w - pad * 2) // min(len(forecast), 13)
            for i, fc in enumerate(forecast[:13]):
                fx = pad + i * fc_w
                # Hour
                h_surf = self.font_small.render(fc.get("hour", ""), True, (180, 180, 180))
                surf.blit(h_surf, (fx + (fc_w - h_surf.get_width()) // 2, fc_y))
                # Emoji
                e_surf = self.font_subtitle.render(fc.get("emoji", ""), True, WHITE)
                surf.blit(e_surf, (fx + (fc_w - e_surf.get_width()) // 2, fc_y + 25))
                # Temp
                t_surf = self.font_small.render(f"{fc.get('temp', '')}°", True, WHITE)
                surf.blit(t_surf, (fx + (fc_w - t_surf.get_width()) // 2, fc_y + 65))
                # Precip
                precip = fc.get("precip", 0)
                if precip:
                    p_surf = self.font_small.render(f"{precip}%", True, ACCENT)
                    surf.blit(p_surf, (fx + (fc_w - p_surf.get_width()) // 2, fc_y + 90))

    # ── Chrome (header, sidebar, ticker) ──────────────────────

    def _draw_header(self):
        header = pygame.Surface((self.W, self.header_h))
        header.fill(HEADER_BG)

        pad = int(self.header_h * 0.15)

        # Logo
        x = self.sidebar_w + pad
        if self.logo_surface:
            ly = (self.header_h - self.logo_surface.get_height()) // 2
            header.blit(self.logo_surface, (x, ly))
            x += self.logo_surface.get_width() + pad

        # CI Name
        name_surf = self.font_subtitle.render(self.ci_name, True, WHITE)
        ny = (self.header_h - name_surf.get_height()) // 2
        header.blit(name_surf, (x, ny))

        # Clock on right
        now = datetime.now().strftime("%H:%M:%S")
        date_str = datetime.now().strftime("%d/%m/%Y")
        clock_surf = self.font_clock.render(f"{date_str}   {now}", True, (200, 200, 200))
        cx = self.W - clock_surf.get_width() - pad * 2
        cy = (self.header_h - clock_surf.get_height()) // 2
        header.blit(clock_surf, (cx, cy))

        self.screen.blit(header, (0, 0))

    def _draw_sidebar(self):
        sidebar = pygame.Surface((self.sidebar_w, self.main_h))
        sidebar.fill(DARK_BG)

        pad = int(self.sidebar_w * 0.15)
        y = pad
        for surf, label in self.icon_surfaces:
            if surf:
                ix = (self.sidebar_w - surf.get_width()) // 2
                sidebar.blit(surf, (ix, y))
                y += surf.get_height() + 4
            if label:
                lbl = self.font_small.render(label, True, (180, 180, 180))
                lx = (self.sidebar_w - lbl.get_width()) // 2
                sidebar.blit(lbl, (max(0, lx), y))
                y += lbl.get_height() + pad

        self.screen.blit(sidebar, (0, self.header_h))

    def _draw_ticker(self):
        ticker = pygame.Surface((self.W, self.ticker_h))
        ticker.fill(TICKER_BG)

        if not self.ticker_items:
            self.screen.blit(ticker, (0, self.H - self.ticker_h))
            return

        pad = int(self.ticker_h * 0.2)

        # Build ticker text
        separator = "     ●     "
        full_text = separator.join(item.get("text", "") for item in self.ticker_items)
        full_text = f"{full_text}{separator}"

        text_surf = self.font_ticker.render(full_text, True, WHITE)
        tw = text_surf.get_width()

        # Scroll
        self.ticker_offset = (self.ticker_offset + 1.5) % (tw + self.W)
        tx = self.W - int(self.ticker_offset)
        ty = (self.ticker_h - text_surf.get_height()) // 2
        ticker.blit(text_surf, (tx, ty))

        # Separator line at top
        pygame.draw.line(ticker, ACCENT, (0, 0), (self.W, 0), 2)

        self.screen.blit(ticker, (0, self.H - self.ticker_h))

    # ── Video playback (subprocess) ───────────────────────────

    def _play_video(self, slide):
        """Play video using mpv in framebuffer mode."""
        fn = slide.get("extra", {}).get("filename")
        if not fn:
            return
        # Download video to temp file
        url = f"{STATIC_URL}/videos/{fn}"
        tmp = f"/tmp/sdis_video_{fn}"
        if not Path(tmp).exists():
            try:
                urllib.request.urlretrieve(url, tmp)
            except Exception as e:
                print(f"[video] download error: {e}", file=sys.stderr)
                return
        try:
            # Try mpv with drm output first, then fbdev
            for vo in ["drm", "fbdev", "sdl"]:
                try:
                    subprocess.run(
                        ["mpv", f"--vo={vo}", "--fs", "--no-terminal",
                         "--no-input-default-bindings", tmp],
                        timeout=120, check=False,
                    )
                    break
                except FileNotFoundError:
                    # mpv not installed, try vlc
                    subprocess.run(
                        ["cvlc", "--play-and-exit", "--no-video-title-show", tmp],
                        timeout=120, check=False,
                    )
                    break
                except Exception:
                    continue
        except Exception as e:
            print(f"[video] playback error: {e}", file=sys.stderr)

    # ── Progress bar ──────────────────────────────────────────

    def _draw_progress(self, elapsed, duration):
        if duration <= 0:
            return
        progress = min(1.0, elapsed / duration)
        bar_h = 4
        bar_y = self.header_h - bar_h
        bar_w = int(self.main_w * progress)
        pygame.draw.rect(self.screen, ACCENT, (self.sidebar_w, bar_y, bar_w, bar_h))

    # ── Main Loop ─────────────────────────────────────────────

    def run(self):
        print(f"[display] Demarrage ({self.W}x{self.H})")
        self.fetch_data()

        running = True
        while running:
            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    running = False
                elif event.type == pygame.KEYDOWN:
                    if event.key in (pygame.K_ESCAPE, pygame.K_q):
                        running = False

            # Periodic data refresh
            if time.time() - self.last_fetch > FETCH_INTERVAL:
                self.fetch_data()

            # Clear screen
            self.screen.fill(DARK_BG)

            # Draw chrome
            self._draw_header()
            self._draw_sidebar()
            self._draw_ticker()

            # Draw current slide
            if self.slides:
                slide = self.slides[self.current_idx]
                duration = slide.get("duration") or 15
                elapsed = time.time() - self.slide_start

                # Handle video slides specially
                if slide.get("layout") == "video" and elapsed < 1:
                    self._play_video(slide)
                    self.slide_start = time.time() - duration  # force advance

                # Render slide
                slide_surf = self._render_slide(slide)
                self.screen.blit(slide_surf, (self.main_x, self.main_y))

                # Progress bar
                self._draw_progress(elapsed, duration)

                # Advance slide
                if elapsed >= duration:
                    self.current_idx = (self.current_idx + 1) % len(self.slides)
                    self.slide_start = time.time()
                    self.image_cache.clear()  # free memory periodically
            else:
                # No slides — show waiting message
                msg = self.font_title.render("En attente de contenu...", True, WHITE)
                mx = self.main_x + (self.main_w - msg.get_width()) // 2
                my = self.main_y + (self.main_h - msg.get_height()) // 2
                self.screen.blit(msg, (mx, my))

            pygame.display.flip()
            self.clock.tick(FPS)

        pygame.quit()


if __name__ == "__main__":
    display = SDISDisplay()
    display.run()
