-- Extracted from app/pilot.py; current phase-1 schema.

PRAGMA foreign_keys=ON;
CREATE TABLE IF NOT EXISTS packs (
 pack_id TEXT PRIMARY KEY, name TEXT NOT NULL, series TEXT, set_code TEXT,
 release_date DATE, card_count INTEGER, source_url TEXT
);
CREATE TABLE IF NOT EXISTS cards (
 card_id TEXT PRIMARY KEY, pack_id TEXT NOT NULL REFERENCES packs(pack_id),
 name TEXT NOT NULL, card_number TEXT, rarity TEXT, rarity_raw TEXT,
 image_path TEXT, source_url TEXT, first_listed_at DATE,
 is_active INTEGER NOT NULL DEFAULT 1 CHECK(is_active IN (0,1))
);
CREATE TABLE IF NOT EXISTS prices (
 id INTEGER PRIMARY KEY AUTOINCREMENT, card_id TEXT NOT NULL REFERENCES cards(card_id),
 market TEXT NOT NULL CHECK(market IN ('JP','US')), price_type TEXT NOT NULL,
 price INTEGER, price_original REAL, currency TEXT, fx_rate REAL, source TEXT,
 fetched_at DATETIME NOT NULL, available INTEGER NOT NULL DEFAULT 1,
 stock_count INTEGER, run_id TEXT, source_url TEXT
);
CREATE INDEX IF NOT EXISTS prices_latest ON prices(card_id, market, price_type, fetched_at);
CREATE TABLE IF NOT EXISTS collection (
 card_id TEXT PRIMARY KEY REFERENCES cards(card_id), owned_count INTEGER DEFAULT 0 CHECK(owned_count>=0),
 condition TEXT, note TEXT, updated_at DATETIME
);
CREATE TABLE IF NOT EXISTS runs (
 run_id TEXT PRIMARY KEY, pack_id TEXT, started_at TEXT NOT NULL, finished_at TEXT,
 status TEXT NOT NULL, origin TEXT NOT NULL, report_json TEXT
);
