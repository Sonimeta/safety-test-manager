-- Migrazione 005: Tabella per risoluzioni conflitto serial pendenti da inviare al server
-- Quando un utente risolve un serial_conflict, il server deve soft-deletare il device "perdente".
-- Questa tabella memorizza le risoluzioni pendenti da includere nel prossimo sync push.

CREATE TABLE IF NOT EXISTS pending_sync_resolutions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    table_name TEXT NOT NULL,
    uuid_to_keep TEXT NOT NULL,
    uuid_to_delete TEXT NOT NULL,
    resolution_type TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
