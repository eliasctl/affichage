const express = require('express');
const session = require('express-session');
const multer = require('multer');
const path = require('path');
const fs = require('fs');
const crypto = require('crypto');
const config = require('./config');
const db = require('./database');

const app = express();
const PORT = 8000;

// ── View engine ─────────────────────────────────────────────
app.set('view engine', 'ejs');
app.set('views', path.join(__dirname, 'views'));

// ── Middleware ───────────────────────────────────────────────
app.use(express.urlencoded({ extended: true }));
app.use(express.json());
app.use(session({
  secret: config.SECRET_KEY,
  resave: false,
  saveUninitialized: false,
  cookie: { maxAge: 24 * 60 * 60 * 1000 },
}));

// Static files with 1-day cache
app.use('/static', express.static(path.join(__dirname, 'static'), { maxAge: '1d' }));

// ── Upload config ───────────────────────────────────────────
const UPLOAD_DIR = path.join(__dirname, 'static', 'uploads');
const ICONS_DIR  = path.join(__dirname, 'static', 'icons');
const VIDEOS_DIR = path.join(__dirname, 'static', 'videos');

const ALLOWED_IMG = new Set(['png', 'jpg', 'jpeg', 'gif', 'webp', 'svg']);
const ALLOWED_VID = new Set(['mp4', 'webm']);

const storage = multer.diskStorage({
  destination: (req, file, cb) => {
    if (file.fieldname === 'video_file') cb(null, VIDEOS_DIR);
    else if (file.fieldname === 'icon_file') cb(null, ICONS_DIR);
    else cb(null, UPLOAD_DIR);
  },
  filename: (req, file, cb) => {
    if (file.fieldname === 'logo_file') {
      const ext = path.extname(file.originalname).slice(1).toLowerCase();
      cb(null, `logo.${ext}`);
    } else {
      cb(null, file.originalname.replace(/[^a-zA-Z0-9._-]/g, '_'));
    }
  },
});

const fileFilter = (req, file, cb) => {
  const ext = path.extname(file.originalname).slice(1).toLowerCase();
  if (file.fieldname === 'video_file') cb(null, ALLOWED_VID.has(ext));
  else cb(null, ALLOWED_IMG.has(ext));
};

const upload = multer({ storage, fileFilter });
const slideUpload = upload.fields([{ name: 'images', maxCount: 10 }, { name: 'video_file', maxCount: 1 }]);
const settingsUpload = upload.fields([{ name: 'logo_file', maxCount: 1 }, { name: 'icon_file', maxCount: 1 }]);

// ── Types & Layouts ─────────────────────────────────────────
const SLIDE_TYPES = {
  intervention: { color: '#C0392B', label: 'Intervention' },
  caserne:      { color: '#1A5276', label: 'Vie de caserne' },
  information:  { color: '#566573', label: 'Information' },
};

const SLIDE_LAYOUTS = {
  annonce:   'Annonce',
  photo:     'Photo plein écran',
  countdown: 'Compte à rebours',
  stats:     'Statistiques',
  video:     'Vidéo',
  meteo:     'Météo',
};

// ── Météo ───────────────────────────────────────────────────
const weatherCache = {};
const WEATHER_TTL = 600_000; // 10 min

const WMO_DAY = {
  0: ['Ensoleillé', '☀️'], 1: ['Peu nuageux', '🌤️'],
  2: ['Partiellement nuageux', '⛅'], 3: ['Couvert', '☁️'],
  45: ['Brouillard', '🌫️'], 48: ['Brouillard givrant', '🌫️'],
  51: ['Bruine légère', '🌦️'], 53: ['Bruine', '🌦️'], 55: ['Bruine dense', '🌦️'],
  61: ['Pluie légère', '🌧️'], 63: ['Pluie', '🌧️'], 65: ['Pluie forte', '🌧️'],
  71: ['Neige légère', '❄️'], 73: ['Neige', '❄️'], 75: ['Neige forte', '❄️'],
  77: ['Grésil', '🌨️'], 80: ['Averses', '🌦️'], 81: ['Averses', '🌦️'],
  82: ['Averses violentes', '⛈️'], 85: ['Averses de neige', '🌨️'],
  86: ['Averses de neige fortes', '🌨️'], 95: ['Orage', '⛈️'],
  96: ['Orage avec grêle', '⛈️'], 99: ['Orage violent', '⛈️'],
};
const WMO_NIGHT = { ...WMO_DAY, 0: ['Nuit claire', '🌙'], 1: ['Nuit peu nuageuse', '🌙'] };
const WIND_DIRS = ['N', 'NE', 'E', 'SE', 'S', 'SO', 'O', 'NO'];

function wmo(code, isDay) {
  return (isDay ? WMO_DAY : WMO_NIGHT)[code] || ['—', '🌡️'];
}

async function fetchWeather(lat, lon) {
  const key = `${lat},${lon}`;
  const cached = weatherCache[key];
  if (cached && Date.now() - cached.ts < WEATHER_TTL) return cached.data;

  const url = `https://api.open-meteo.com/v1/forecast?latitude=${lat}&longitude=${lon}`
    + '&current=temperature_2m,apparent_temperature,weather_code,wind_speed_10m,wind_direction_10m,relative_humidity_2m,is_day'
    + '&hourly=temperature_2m,weather_code,precipitation_probability,is_day'
    + '&daily=weather_code,temperature_2m_max,temperature_2m_min,precipitation_probability_max'
    + '&wind_speed_unit=kmh&forecast_days=6&timezone=Europe%2FParis';

  try {
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 5000);
    const resp = await fetch(url, { headers: { 'User-Agent': 'affichage-sdis/2.0' }, signal: controller.signal });
    clearTimeout(timeout);
    const data = await resp.json();

    const c = data.current;
    const [desc, emoji] = wmo(c.weather_code ?? 0, c.is_day ?? 1);
    const windDeg = c.wind_direction_10m ?? 0;

    // Hourly forecast (12h)
    const h = data.hourly || {};
    const times = h.time || [];
    const now = new Date();
    const nowStr = now.getFullYear() + '-' + String(now.getMonth() + 1).padStart(2, '0')
      + '-' + String(now.getDate()).padStart(2, '0') + 'T' + String(now.getHours()).padStart(2, '0') + ':00';
    let startI = times.indexOf(nowStr);
    if (startI === -1) startI = 0;

    const forecast = [];
    for (let i = startI; i < Math.min(startI + 13, times.length); i++) {
      const [, fcEmoji] = wmo(h.weather_code[i], h.is_day[i]);
      forecast.push({
        hour: times[i].slice(11, 13) + 'h',
        temp: Math.round(h.temperature_2m[i]),
        emoji: fcEmoji,
        precip: h.precipitation_probability[i],
      });
    }

    // Daily forecast (5 days, skip today)
    const d = data.daily || {};
    const dayNames = ['Dim', 'Lun', 'Mar', 'Mer', 'Jeu', 'Ven', 'Sam'];
    const daily = [];
    for (let i = 1; i < Math.min(6, (d.time || []).length); i++) {
      const [, dEmoji] = wmo(d.weather_code[i], true);
      const dt = new Date(d.time[i] + 'T12:00:00');
      daily.push({
        day: dayNames[dt.getDay()],
        emoji: dEmoji,
        tmax: Math.round(d.temperature_2m_max[i]),
        tmin: Math.round(d.temperature_2m_min[i]),
        precip: d.precipitation_probability_max[i],
      });
    }

    const result = {
      temp: Math.round(c.temperature_2m ?? 0),
      feels: Math.round(c.apparent_temperature ?? 0),
      desc, emoji,
      wind: Math.round(c.wind_speed_10m ?? 0),
      wind_dir: WIND_DIRS[Math.round(windDeg / 45) % 8],
      humidity: Math.round(c.relative_humidity_2m ?? 0),
      forecast, daily,
    };
    weatherCache[key] = { data: result, ts: Date.now() };
    return result;
  } catch {
    return null;
  }
}

// ── Helpers ─────────────────────────────────────────────────
function stripHtml(html) { return (html || '').replace(/<[^>]+>/g, ''); }

function calcDuration(content, layout = 'annonce') {
  if (layout === 'video') return 60;
  if (layout === 'meteo') return 20;
  if (layout === 'photo') {
    const t = stripHtml(content);
    return Math.max(12, Math.min(30, 10 + Math.ceil(t.length / 40)));
  }
  if (layout === 'stats' || layout === 'countdown') {
    return Math.max(20, Math.min(45, 18 + Math.ceil(stripHtml(content).length / 40)));
  }
  const t = stripHtml(content);
  if (!t.trim()) return 15;
  return Math.max(25, Math.min(130, 25 + Math.ceil(t.length / 25)));
}

function loginRequired(req, res, next) {
  if (!req.session.auth) return res.redirect('/login');
  next();
}

// ── Auth écran (token longue durée — "lifetime") ────────────
const DISPLAY_COOKIE = 'display_auth';
const DISPLAY_COOKIE_MAX_AGE = 10 * 365 * 24 * 60 * 60 * 1000; // ≈ 10 ans

function getDisplayToken() {
  if (config.DISPLAY_TOKEN) return config.DISPLAY_TOKEN;
  let t = db.getSetting('display_token', '');
  if (!t) {
    t = crypto.randomBytes(24).toString('hex');
    db.setSetting('display_token', t);
  }
  return t;
}

function regenDisplayToken() {
  const t = crypto.randomBytes(24).toString('hex');
  db.setSetting('display_token', t);
  return t;
}

function parseCookies(req) {
  const out = {};
  (req.headers.cookie || '').split(';').forEach(p => {
    const i = p.indexOf('=');
    if (i > 0) out[p.slice(0, i).trim()] = decodeURIComponent(p.slice(i + 1).trim());
  });
  return out;
}

function displayAuth(req, res, next) {
  // Un admin connecté a toujours accès à l'écran
  if (req.session?.auth) return next();
  const expected = getDisplayToken();
  const provided = req.query.token || parseCookies(req)[DISPLAY_COOKIE];
  if (provided && provided === expected) {
    if (req.query.token === expected) {
      // L'écran a fourni le bon token via l'URL → pose un cookie longue durée.
      res.cookie(DISPLAY_COOKIE, expected, {
        maxAge: DISPLAY_COOKIE_MAX_AGE,
        httpOnly: true,
        sameSite: 'lax',
      });
    }
    return next();
  }
  if (req.path.startsWith('/api/')) return res.status(401).json({ error: 'unauthorized' });
  return res.redirect('/login');
}

async function enrichSlide(s) {
  const meta = SLIDE_TYPES[s.type] || SLIDE_TYPES.intervention;
  s.color = meta.color;
  s.type_label = meta.label;
  if (!s.duration) s.duration = calcDuration(s.content || '', s.layout || 'annonce');
  if (s.layout === 'meteo') {
    const ex = s.extra || {};
    s.weather = await fetchWeather(ex.lat ?? 48.4, ex.lon ?? 2.7);
  }
  return s;
}

function parseSlideExtra(body) {
  const layout = body.layout || 'annonce';
  const extra = {};
  if (layout === 'countdown') {
    let t = (body.cd_target || '').trim();
    if (t && t.length === 16) t += ':00';
    extra.target = t;
  } else if (layout === 'stats') {
    try { extra.items = JSON.parse(body.stats_json || '[]'); }
    catch { extra.items = []; }
  } else if (layout === 'meteo') {
    extra.lat = body.meteo_lat || '48.4';
    extra.lon = body.meteo_lon || '2.7';
    extra.city = body.meteo_city || '';
  }
  return { layout, extra };
}

// ── Init DB ─────────────────────────────────────────────────
db.initDb();

// Génère et persiste le token d'accès écran dès le démarrage,
// pour qu'il soit immédiatement visible dans Admin → Paramètres.
getDisplayToken();

// ── Display ─────────────────────────────────────────────────

app.get('/', displayAuth, async (req, res) => {
  const slides  = await Promise.all(db.getSlides(true).map(enrichSlide));
  const icons   = db.getIcons();
  const ci_name = db.getSetting('ci_name', 'CIS Fontainebleau');
  const ticker  = db.getTicker(true);
  const logo    = db.getSetting('logo', 'logo-sdis.png');
  res.render('display', { slides, icons, ci_name, ticker, logo });
});

app.get('/api/display', displayAuth, async (req, res) => {
  const slides  = await Promise.all(db.getSlides(true).map(enrichSlide));
  const icons   = db.getIcons();
  const ci_name = db.getSetting('ci_name', 'CIS Fontainebleau');
  const ticker  = db.getTicker(true);
  const logo    = db.getSetting('logo', 'logo-sdis.png');
  res.json({ slides, icons, ci_name, ticker, logo });
});

app.get('/api/hash', displayAuth, (req, res) => {
  res.json({ hash: db.getContentHash() });
});

// ── Auth ────────────────────────────────────────────────────

app.get('/login', (req, res) => res.render('login', { error: null }));

app.post('/login', (req, res) => {
  if (req.body.password === config.ADMIN_PASSWORD) {
    req.session.auth = true;
    return res.redirect('/admin');
  }
  res.render('login', { error: 'Mot de passe incorrect.' });
});

app.get('/logout', (req, res) => { req.session.destroy(); res.redirect('/login'); });

// ── Admin – Slides ──────────────────────────────────────────

app.get('/admin', loginRequired, (req, res) => {
  res.render('admin/index', { slides: db.getSlides(false), currentPath: '/admin', SLIDE_TYPES, SLIDE_LAYOUTS });
});

app.get('/admin/new', loginRequired, (req, res) => {
  res.render('admin/slide_form', { slide: null, currentPath: '/admin', SLIDE_TYPES, SLIDE_LAYOUTS });
});

app.post('/admin/new', loginRequired, slideUpload, (req, res) => {
  const title   = (req.body.title || '').trim();
  const content = (req.body.content || '').trim();
  let type = req.body.type || 'intervention';
  if (!SLIDE_TYPES[type]) type = 'intervention';
  const { layout, extra } = parseSlideExtra(req.body);
  const images = (req.files?.images || []).map(f => f.filename);
  if (layout === 'video' && req.files?.video_file?.[0]) extra.filename = req.files.video_file[0].filename;
  db.createSlide({ title, content, type, layout, images, extra, duration: null });
  res.redirect('/admin');
});

app.get('/admin/edit/:id', loginRequired, (req, res) => {
  const slide = db.getSlide(parseInt(req.params.id));
  if (!slide) return res.status(404).send('Not found');
  res.render('admin/slide_form', { slide, currentPath: '/admin', SLIDE_TYPES, SLIDE_LAYOUTS });
});

app.post('/admin/edit/:id', loginRequired, slideUpload, (req, res) => {
  const sid = parseInt(req.params.id);
  const slide = db.getSlide(sid);
  if (!slide) return res.status(404).send('Not found');
  const title   = (req.body.title || '').trim();
  const content = (req.body.content || '').trim();
  let type = req.body.type || 'intervention';
  if (!SLIDE_TYPES[type]) type = 'intervention';
  const { layout, extra } = parseSlideExtra(req.body);

  const toDelete = new Set(Array.isArray(req.body.delete_img) ? req.body.delete_img : req.body.delete_img ? [req.body.delete_img] : []);
  const kept    = slide.images.filter(img => !toDelete.has(img));
  const newImgs = (req.files?.images || []).map(f => f.filename);
  const images  = [...kept, ...newImgs];

  if (layout === 'video') {
    if (req.files?.video_file?.[0]) extra.filename = req.files.video_file[0].filename;
    else if (slide.layout === 'video' && slide.extra?.filename) extra.filename = slide.extra.filename;
  }
  db.updateSlide(sid, { title, content, type, layout, images, extra, duration: null });
  res.redirect('/admin');
});

app.post('/admin/delete/:id', loginRequired, (req, res) => {
  db.deleteSlide(parseInt(req.params.id)); res.redirect('/admin');
});

app.post('/admin/toggle/:id', loginRequired, (req, res) => {
  db.toggleSlide(parseInt(req.params.id)); res.redirect('/admin');
});

app.post('/admin/move/:id/:direction', loginRequired, (req, res) => {
  if (['up', 'down'].includes(req.params.direction)) db.moveSlide(parseInt(req.params.id), req.params.direction);
  res.redirect('/admin');
});

app.post('/admin/reorder', loginRequired, (req, res) => {
  const ids = req.body?.ids;
  if (Array.isArray(ids) && ids.length) db.reorderSlides(ids.map(Number));
  res.json({ ok: true });
});

// ── Admin – Settings ────────────────────────────────────────

app.get('/admin/settings', loginRequired, (req, res) => {
  res.render('admin/settings', {
    ci_name: db.getSetting('ci_name', 'CIS Fontainebleau'),
    logo: db.getSetting('logo', 'logo-sdis.png'),
    icons: db.getIcons(),
    display_token: getDisplayToken(),
    display_token_locked: !!config.DISPLAY_TOKEN,
    currentPath: '/admin/settings',
  });
});

app.post('/admin/regen-display-token', loginRequired, (req, res) => {
  if (!config.DISPLAY_TOKEN) regenDisplayToken();
  res.redirect('/admin/settings');
});

app.post('/admin/settings', loginRequired, settingsUpload, (req, res) => {
  const action = req.body.action;
  if (action === 'save_ci') {
    db.setSetting('ci_name', (req.body.ci_name || '').trim());
  } else if (action === 'save_logo' && req.files?.logo_file?.[0]) {
    db.setSetting('logo', `uploads/${req.files.logo_file[0].filename}`);
  } else if (action === 'add_icon' && req.files?.icon_file?.[0]) {
    db.addIcon(req.files.icon_file[0].filename, (req.body.icon_label || '').trim());
  } else if (action === 'delete_icon') {
    db.deleteIcon(parseInt(req.body.icon_id));
  } else if (action === 'move_icon_up' || action === 'move_icon_down') {
    db.moveIcon(parseInt(req.body.icon_id), action === 'move_icon_up' ? 'up' : 'down');
  }
  res.redirect('/admin/settings');
});

// ── Admin – Ticker ──────────────────────────────────────────

app.get('/admin/ticker', loginRequired, (req, res) => {
  res.render('admin/ticker', { items: db.getTicker(false), currentPath: '/admin/ticker' });
});

app.post('/admin/ticker', loginRequired, (req, res) => {
  const action = req.body.action;
  if (action === 'add') {
    const text = (req.body.text || '').trim();
    if (text) db.createTicker(text);
  } else if (action === 'edit') {
    db.updateTicker(parseInt(req.body.tid), (req.body.text || '').trim());
  } else if (action === 'delete') {
    db.deleteTicker(parseInt(req.body.tid));
  } else if (action === 'toggle') {
    db.toggleTicker(parseInt(req.body.tid));
  } else if (action === 'up' || action === 'down') {
    db.moveTicker(parseInt(req.body.tid), action);
  }
  res.redirect('/admin/ticker');
});

// ── Start ───────────────────────────────────────────────────

app.listen(PORT, '0.0.0.0', () => {
  console.log(`Serveur démarré sur http://0.0.0.0:${PORT}`);
});
