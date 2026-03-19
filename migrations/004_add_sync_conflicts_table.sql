-- Migrazione 004: Aggiunge la tabella sync_conflicts per gestire i conflitti di sincronizzazione
-- I conflitti vengono salvati localmente invece di generare errori, permettendo all'utente di risolverli

CREATE TABLE IF NOT EXISTS sync_conflicts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    conflict_id TEXT UNIQUE NOT NULL,
    table_name TEXT NOT NULL,
    record_uuid TEXT,
    conflict_type TEXT NOT NULL,
    severity TEXT NOT NULL DEFAULT 'medium',
    local_data JSON,
    server_data JSON,
    error_message TEXT,
    status TEXT NOT NULL DEFAULT 'pending',
    resolution TEXT,
    resolved_at TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_sync_conflicts_status ON sync_conflicts(status);
CREATE INDEX IF NOT EXISTS idx_sync_conflicts_table ON sync_conflicts(table_name);
