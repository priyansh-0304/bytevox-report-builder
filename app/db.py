"""SQLite connection + schema. Every query in the app uses '?' placeholders, never string-built SQL."""
import os
import sqlite3

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
  id INTEGER PRIMARY KEY,
  email TEXT NOT NULL UNIQUE,
  password_hash TEXT NOT NULL,
  created_at INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS sessions (
  token_hash TEXT PRIMARY KEY,              -- sha256 of the cookie value; the raw token is never stored
  user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  expires_at INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS datasets (
  id INTEGER PRIMARY KEY,
  user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  name TEXT NOT NULL,
  original_filename TEXT NOT NULL,          -- display only; the raw file itself is NOT kept
  profile_json TEXT NOT NULL,               -- columns, types, missing counts, rejected rows, warnings
  row_count INTEGER NOT NULL,
  created_at INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_datasets_user ON datasets(user_id);

CREATE TABLE IF NOT EXISTS data_rows (
  dataset_id INTEGER NOT NULL REFERENCES datasets(id) ON DELETE CASCADE,
  row_num INTEGER NOT NULL,                 -- line number in the original file, so every number is traceable
  values_json TEXT NOT NULL,                -- typed values, same order as profile columns
  PRIMARY KEY (dataset_id, row_num)
) WITHOUT ROWID;

CREATE TABLE IF NOT EXISTS reports (
  id INTEGER PRIMARY KEY,
  user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  dataset_id INTEGER NOT NULL REFERENCES datasets(id) ON DELETE CASCADE,
  title TEXT NOT NULL,
  blocks_json TEXT NOT NULL,
  filters_json TEXT NOT NULL,
  created_at INTEGER NOT NULL,
  updated_at INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_reports_user ON reports(user_id);

CREATE TABLE IF NOT EXISTS share_links (
  id INTEGER PRIMARY KEY,
  report_id INTEGER NOT NULL REFERENCES reports(id) ON DELETE CASCADE,
  token_hash TEXT NOT NULL UNIQUE,          -- only the hash is stored; the link is shown once at creation
  token_hint TEXT NOT NULL,                 -- last 4 chars, so the owner can tell links apart
  created_at INTEGER NOT NULL,
  expires_at INTEGER NOT NULL,
  revoked_at INTEGER
);
CREATE INDEX IF NOT EXISTS ix_share_report ON share_links(report_id);
"""


def connect(path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db(path: str) -> None:
    folder = os.path.dirname(path)
    if folder:
        os.makedirs(folder, exist_ok=True)
    conn = connect(path)
    conn.execute("PRAGMA journal_mode = WAL")
    conn.executescript(SCHEMA)
    conn.commit()
    conn.close()
