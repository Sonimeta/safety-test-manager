-- Migrazione 006: Tabella per i preset delle parti applicate

CREATE TABLE IF NOT EXISTS applied_parts_presets (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    uuid TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL UNIQUE,
    description TEXT,
    parts_json TEXT NOT NULL,
    last_modified TEXT NOT NULL DEFAULT (datetime('now')),
    is_deleted INTEGER NOT NULL DEFAULT 0,
    is_synced INTEGER NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_pa_presets_name ON applied_parts_presets(name);
CREATE INDEX IF NOT EXISTS idx_pa_presets_deleted ON applied_parts_presets(is_deleted);
