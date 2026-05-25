-- Migration 009: Aggiunge la tabella verification_assignments per la gestione
-- delle assegnazioni di verifiche da parte dei responsabili ai tecnici.
-- NOTA: sintassi SQLite (il database locale del client desktop).
-- Il database PostgreSQL del server usa online_database.sql (sezione 12).

CREATE TABLE IF NOT EXISTS verification_assignments (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    uuid            TEXT    NOT NULL UNIQUE,
    device_id       INTEGER NOT NULL REFERENCES devices(id) ON DELETE CASCADE,
    assigned_to     TEXT    NOT NULL,
    assigned_by     TEXT    NOT NULL,
    notes           TEXT,
    priority        TEXT    NOT NULL DEFAULT 'normal',
    due_date        TEXT,
    status          TEXT    NOT NULL DEFAULT 'pending',
    created_at      TEXT    NOT NULL,
    updated_at      TEXT    NOT NULL,
    completed_at    TEXT,
    is_deleted      INTEGER NOT NULL DEFAULT 0,
    is_synced       INTEGER NOT NULL DEFAULT 0,
    last_modified   TEXT    NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_assignments_assigned_to ON verification_assignments(assigned_to);
CREATE INDEX IF NOT EXISTS idx_assignments_status      ON verification_assignments(status);
CREATE INDEX IF NOT EXISTS idx_assignments_device_id   ON verification_assignments(device_id);
