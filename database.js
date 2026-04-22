const Database = require('better-sqlite3');
const crypto = require('crypto');
const fs = require('fs');
const path = require('path');

const DB_PATH = process.env.DB_PATH || path.join(__dirname, 'data', 'affichage.db');

// Ensure data directory exists
const dbDir = path.dirname(DB_PATH);
if (!fs.existsSync(dbDir)) fs.mkdirSync(dbDir, { recursive: true });

const db = new Database(DB_PATH);
db.pragma('journal_mode = WAL');
db.pragma('synchronous = NORMAL');
db.pragma('cache_size = -8000');

// ── Hash cache ──────────────────────────────────────────────
let hashCache = { hash: null, ts: 0 };

function getContentHash() {
  const now = Date.now();
  if (hashCache.hash && now - hashCache.ts < 5000) return hashCache.hash;
  const slides = db.prepare(
    'SELECT id,title,content,type,layout,images,duration,position,active,extra FROM slides WHERE active=1 ORDER BY position,id'
  ).all();
  const ticker = db.prepare(
    'SELECT id,text,active,position FROM ticker WHERE active=1 ORDER BY position,id'
  ).all();
  const raw = JSON.stringify({ s: slides, t: ticker });
  const h = crypto.createHash('md5').update(raw).digest('hex');
  hashCache = { hash: h, ts: now };
  return h;
}

function invalidateCache() {
  hashCache = { hash: null, ts: 0 };
}

// ── Init ────────────────────────────────────────────────────
function initDb() {
  db.exec(`CREATE TABLE IF NOT EXISTS slides (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    title      TEXT    NOT NULL DEFAULT '',
    content    TEXT    NOT NULL DEFAULT '',
    images     TEXT    NOT NULL DEFAULT '[]',
    duration   INTEGER,
    position   INTEGER NOT NULL DEFAULT 0,
    active     INTEGER NOT NULL DEFAULT 1,
    created_at TEXT    NOT NULL DEFAULT (datetime('now', 'localtime'))
  )`);

  const cols = db.prepare('PRAGMA table_info(slides)').all().map(r => r.name);
  if (cols.includes('image') && !cols.includes('images')) {
    db.exec("ALTER TABLE slides ADD COLUMN images TEXT NOT NULL DEFAULT '[]'");
    for (const row of db.prepare('SELECT id, image FROM slides WHERE image IS NOT NULL').all()) {
      db.prepare('UPDATE slides SET images=? WHERE id=?').run(JSON.stringify([row.image]), row.id);
    }
  }
  if (!cols.includes('type'))   db.exec("ALTER TABLE slides ADD COLUMN type TEXT NOT NULL DEFAULT 'intervention'");
  if (!cols.includes('layout')) db.exec("ALTER TABLE slides ADD COLUMN layout TEXT NOT NULL DEFAULT 'annonce'");
  if (!cols.includes('extra'))  db.exec("ALTER TABLE slides ADD COLUMN extra TEXT NOT NULL DEFAULT '{}'");

  db.exec(`CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY, value TEXT NOT NULL DEFAULT ''
  )`);
  db.prepare("INSERT OR IGNORE INTO settings (key,value) VALUES ('ci_name','CIS Fontainebleau')").run();

  db.exec(`CREATE TABLE IF NOT EXISTS icons (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    filename TEXT NOT NULL, label TEXT NOT NULL DEFAULT '', position INTEGER NOT NULL DEFAULT 0
  )`);

  db.exec(`CREATE TABLE IF NOT EXISTS ticker (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    text     TEXT    NOT NULL DEFAULT '',
    active   INTEGER NOT NULL DEFAULT 1,
    position INTEGER NOT NULL DEFAULT 0
  )`);

  db.exec('CREATE INDEX IF NOT EXISTS idx_slides_active_pos ON slides(active, position)');
  db.exec('CREATE INDEX IF NOT EXISTS idx_ticker_active_pos ON ticker(active, position)');
  db.exec('CREATE INDEX IF NOT EXISTS idx_icons_pos ON icons(position)');
}

// ── Slides ──────────────────────────────────────────────────
function parseSlide(row) {
  return { ...row, images: JSON.parse(row.images || '[]'), extra: JSON.parse(row.extra || '{}') };
}

function getSlides(activeOnly = true) {
  const q = activeOnly
    ? 'SELECT * FROM slides WHERE active=1 ORDER BY position,id'
    : 'SELECT * FROM slides ORDER BY position,id';
  return db.prepare(q).all().map(parseSlide);
}

function getSlide(id) {
  const row = db.prepare('SELECT * FROM slides WHERE id=?').get(id);
  return row ? parseSlide(row) : null;
}

function createSlide({ title, content, type = 'intervention', layout = 'annonce', images = [], extra = {}, duration = null }) {
  const maxPos = db.prepare('SELECT COALESCE(MAX(position),0) as m FROM slides').get().m;
  db.prepare(
    'INSERT INTO slides (title,content,type,layout,images,extra,duration,position) VALUES (?,?,?,?,?,?,?,?)'
  ).run(title, content, type, layout, JSON.stringify(images), JSON.stringify(extra), duration, maxPos + 1);
  invalidateCache();
}

function updateSlide(id, { title, content, type, layout, images, extra, duration }) {
  db.prepare(
    'UPDATE slides SET title=?,content=?,type=?,layout=?,images=?,extra=?,duration=? WHERE id=?'
  ).run(title, content, type, layout, JSON.stringify(images), JSON.stringify(extra || {}), duration, id);
  invalidateCache();
}

function deleteSlide(id) {
  db.prepare('DELETE FROM slides WHERE id=?').run(id);
  invalidateCache();
}

function toggleSlide(id) {
  db.prepare('UPDATE slides SET active=1-active WHERE id=?').run(id);
  invalidateCache();
}

function reorderSlides(ids) {
  const stmt = db.prepare('UPDATE slides SET position=? WHERE id=?');
  const tx = db.transaction((ids) => { ids.forEach((id, pos) => stmt.run(pos, id)); });
  tx(ids);
  invalidateCache();
}

function moveSlide(id, direction) {
  const slide = db.prepare('SELECT * FROM slides WHERE id=?').get(id);
  if (!slide) return;
  const other = db.prepare(
    direction === 'up'
      ? 'SELECT * FROM slides WHERE position<? ORDER BY position DESC LIMIT 1'
      : 'SELECT * FROM slides WHERE position>? ORDER BY position ASC LIMIT 1'
  ).get(slide.position);
  if (other) {
    db.prepare('UPDATE slides SET position=? WHERE id=?').run(other.position, id);
    db.prepare('UPDATE slides SET position=? WHERE id=?').run(slide.position, other.id);
    invalidateCache();
  }
}

// ── Settings ────────────────────────────────────────────────
function getSetting(key, defaultVal = '') {
  const row = db.prepare('SELECT value FROM settings WHERE key=?').get(key);
  return row ? row.value : defaultVal;
}

function setSetting(key, value) {
  db.prepare('INSERT OR REPLACE INTO settings (key,value) VALUES (?,?)').run(key, value);
}

// ── Icons ───────────────────────────────────────────────────
function getIcons() {
  return db.prepare('SELECT * FROM icons ORDER BY position,id').all();
}

function addIcon(filename, label) {
  const maxPos = db.prepare('SELECT COALESCE(MAX(position),0) as m FROM icons').get().m;
  db.prepare('INSERT INTO icons (filename,label,position) VALUES (?,?,?)').run(filename, label, maxPos + 1);
}

function deleteIcon(id) {
  db.prepare('DELETE FROM icons WHERE id=?').run(id);
}

function moveIcon(id, direction) {
  const icon = db.prepare('SELECT * FROM icons WHERE id=?').get(id);
  if (!icon) return;
  const other = db.prepare(
    direction === 'up'
      ? 'SELECT * FROM icons WHERE position<? ORDER BY position DESC LIMIT 1'
      : 'SELECT * FROM icons WHERE position>? ORDER BY position ASC LIMIT 1'
  ).get(icon.position);
  if (other) {
    db.prepare('UPDATE icons SET position=? WHERE id=?').run(other.position, id);
    db.prepare('UPDATE icons SET position=? WHERE id=?').run(icon.position, other.id);
  }
}

// ── Ticker ──────────────────────────────────────────────────
function getTicker(activeOnly = true) {
  const q = activeOnly
    ? 'SELECT * FROM ticker WHERE active=1 ORDER BY position,id'
    : 'SELECT * FROM ticker ORDER BY position,id';
  return db.prepare(q).all();
}

function createTicker(text) {
  const maxPos = db.prepare('SELECT COALESCE(MAX(position),0) as m FROM ticker').get().m;
  db.prepare('INSERT INTO ticker (text,position) VALUES (?,?)').run(text, maxPos + 1);
  invalidateCache();
}

function updateTicker(id, text) {
  db.prepare('UPDATE ticker SET text=? WHERE id=?').run(text, id);
  invalidateCache();
}

function deleteTicker(id) {
  db.prepare('DELETE FROM ticker WHERE id=?').run(id);
  invalidateCache();
}

function toggleTicker(id) {
  db.prepare('UPDATE ticker SET active=1-active WHERE id=?').run(id);
  invalidateCache();
}

function moveTicker(id, direction) {
  const item = db.prepare('SELECT * FROM ticker WHERE id=?').get(id);
  if (!item) return;
  const other = db.prepare(
    direction === 'up'
      ? 'SELECT * FROM ticker WHERE position<? ORDER BY position DESC LIMIT 1'
      : 'SELECT * FROM ticker WHERE position>? ORDER BY position ASC LIMIT 1'
  ).get(item.position);
  if (other) {
    db.prepare('UPDATE ticker SET position=? WHERE id=?').run(other.position, id);
    db.prepare('UPDATE ticker SET position=? WHERE id=?').run(item.position, other.id);
    invalidateCache();
  }
}

module.exports = {
  initDb, getContentHash,
  getSlides, getSlide, createSlide, updateSlide, deleteSlide, toggleSlide, reorderSlides, moveSlide,
  getSetting, setSetting,
  getIcons, addIcon, deleteIcon, moveIcon,
  getTicker, createTicker, updateTicker, deleteTicker, toggleTicker, moveTicker,
};
