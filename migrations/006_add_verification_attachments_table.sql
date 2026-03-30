-- Migrazione 006: Tabella per gli allegati alle verifiche funzionali
-- Permette di allegare documenti scannerizzati alle verifiche.
-- I file vengono salvati su disco nella cartella attachments/ e nel DB si salva solo il percorso.

CREATE TABLE IF NOT EXISTS verification_attachments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    uuid TEXT NOT NULL UNIQUE,
    verification_id INTEGER NOT NULL,
    verification_type TEXT NOT NULL DEFAULT 'functional',
    filename TEXT NOT NULL,
    file_path TEXT NOT NULL,
    mime_type TEXT NOT NULL DEFAULT 'image/jpeg',
    file_size INTEGER NOT NULL DEFAULT 0,
    description TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    last_modified TEXT NOT NULL DEFAULT (datetime('now')),
    is_synced INTEGER NOT NULL DEFAULT 0,
    is_deleted INTEGER NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_attachments_verification 
    ON verification_attachments(verification_id, verification_type);
