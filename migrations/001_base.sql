-- Migrazione 001 (consolidata): Schema completo del database locale SQLite.
-- Incorpora tutte le versioni precedenti (002-010).
-- I duplicati di numero di serie sono permessi e gestiti a livello applicativo.

PRAGMA foreign_keys=ON;

CREATE TABLE IF NOT EXISTS schema_version (
    version INTEGER NOT NULL
);
DELETE FROM schema_version;
INSERT INTO schema_version(version) VALUES (1);

-- CLIENTI
CREATE TABLE IF NOT EXISTS customers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    uuid TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    address TEXT,
    phone TEXT,
    email TEXT,
    last_modified TEXT NOT NULL,
    is_deleted INTEGER NOT NULL DEFAULT 0,
    is_synced INTEGER NOT NULL DEFAULT 0
);

-- DESTINAZIONI
CREATE TABLE IF NOT EXISTS destinations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    uuid TEXT NOT NULL UNIQUE,
    customer_id INTEGER NOT NULL REFERENCES customers(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    address TEXT,
    last_modified TEXT NOT NULL,
    is_synced INTEGER NOT NULL DEFAULT 0,
    is_deleted INTEGER NOT NULL DEFAULT 0
);

-- DISPOSITIVI (serial_number NON univoco: duplicati permessi, gestiti dall UI)
CREATE TABLE IF NOT EXISTS devices (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    uuid TEXT NOT NULL UNIQUE,
    destination_id INTEGER NOT NULL REFERENCES destinations(id) ON DELETE CASCADE,
    serial_number TEXT,
    description TEXT,
    manufacturer TEXT,
    model TEXT,
    department TEXT,
    applied_parts_json TEXT,
    customer_inventory TEXT,
    ams_inventory TEXT,
    verification_interval INTEGER,
    next_verification_date TEXT,
    default_profile_key TEXT,
    default_functional_profile_key TEXT,
    last_modified TEXT NOT NULL,
    is_synced INTEGER NOT NULL DEFAULT 0,
    is_deleted INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'active'
);

-- VERIFICHE ELETTRICHE
CREATE TABLE IF NOT EXISTS verifications (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    uuid TEXT NOT NULL UNIQUE,
    device_id INTEGER NOT NULL REFERENCES devices(id) ON DELETE CASCADE,
    verification_date TEXT NOT NULL,
    profile_name TEXT NOT NULL,
    results_json TEXT NOT NULL,
    overall_status TEXT NOT NULL,
    visual_inspection_json TEXT,
    mti_instrument TEXT,
    mti_serial TEXT,
    mti_version TEXT,
    mti_cal_date TEXT,
    technician_name TEXT,
    technician_username TEXT,
    verification_code TEXT,
    last_modified TEXT NOT NULL,
    is_deleted INTEGER NOT NULL DEFAULT 0,
    is_synced INTEGER NOT NULL DEFAULT 0
);

-- PROFILI FUNZIONALI
CREATE TABLE IF NOT EXISTS functional_profiles (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    uuid TEXT NOT NULL UNIQUE,
    profile_key TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    device_type TEXT,
    instrument_id INTEGER,
    instrument_ids TEXT,
    schema_json TEXT NOT NULL,
    last_modified TEXT NOT NULL,
    is_synced INTEGER NOT NULL DEFAULT 0,
    is_deleted INTEGER NOT NULL DEFAULT 0
);

-- VERIFICHE FUNZIONALI
CREATE TABLE IF NOT EXISTS functional_verifications (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    uuid TEXT NOT NULL UNIQUE,
    device_id INTEGER NOT NULL REFERENCES devices(id) ON DELETE CASCADE,
    profile_key TEXT NOT NULL,
    verification_date TEXT NOT NULL,
    technician_name TEXT,
    technician_username TEXT,
    mti_instrument TEXT,
    mti_serial TEXT,
    mti_version TEXT,
    mti_cal_date TEXT,
    results_json TEXT NOT NULL,
    structured_results_json TEXT,
    overall_status TEXT NOT NULL,
    notes TEXT,
    verification_code TEXT,
    used_instruments_json TEXT,
    last_modified TEXT NOT NULL,
    is_synced INTEGER NOT NULL DEFAULT 0,
    is_deleted INTEGER NOT NULL DEFAULT 0
);

-- PROFILI ELETTRICI
CREATE TABLE IF NOT EXISTS profiles (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    uuid TEXT NOT NULL UNIQUE,
    profile_key TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    norma TEXT NOT NULL DEFAULT '',
    last_modified TEXT NOT NULL,
    is_synced INTEGER NOT NULL DEFAULT 0,
    is_deleted INTEGER NOT NULL DEFAULT 0
);

-- TEST DEI PROFILI
CREATE TABLE IF NOT EXISTS profile_tests (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    uuid TEXT NOT NULL UNIQUE,
    profile_id INTEGER NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    parameter TEXT,
    limits_json TEXT,
    is_applied_part_test INTEGER NOT NULL DEFAULT 0,
    last_modified TEXT NOT NULL,
    is_synced INTEGER NOT NULL DEFAULT 0,
    is_deleted INTEGER NOT NULL DEFAULT 0
);

-- STRUMENTI DI MISURA
CREATE TABLE IF NOT EXISTS mti_instruments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    uuid TEXT NOT NULL UNIQUE,
    instrument_name TEXT NOT NULL,
    serial_number TEXT NOT NULL,
    fw_version TEXT,
    calibration_date TEXT,
    instrument_type TEXT DEFAULT 'electrical',
    is_default INTEGER NOT NULL DEFAULT 0,
    last_modified TEXT NOT NULL,
    is_deleted INTEGER NOT NULL DEFAULT 0,
    is_synced INTEGER NOT NULL DEFAULT 0
);

-- FIRME
CREATE TABLE IF NOT EXISTS signatures (
    username TEXT PRIMARY KEY NOT NULL,
    signature_data BLOB,
    last_modified TEXT NOT NULL,
    is_synced INTEGER NOT NULL DEFAULT 0
);

-- AUDIT LOG
CREATE TABLE IF NOT EXISTS audit_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL,
    username TEXT NOT NULL,
    user_full_name TEXT,
    action_type TEXT NOT NULL,
    entity_type TEXT NOT NULL,
    entity_id INTEGER,
    entity_description TEXT,
    details TEXT,
    ip_address TEXT,
    uuid TEXT NOT NULL UNIQUE,
    last_modified TEXT NOT NULL,
    is_deleted INTEGER NOT NULL DEFAULT 0,
    is_synced INTEGER NOT NULL DEFAULT 0
);

-- ALLEGATI ALLE VERIFICHE
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

-- CONFLITTI DI SINCRONIZZAZIONE
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

-- RISOLUZIONI CONFLITTO PENDENTI
CREATE TABLE IF NOT EXISTS pending_sync_resolutions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    table_name TEXT NOT NULL,
    uuid_to_keep TEXT NOT NULL,
    uuid_to_delete TEXT NOT NULL,
    resolution_type TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

-- VERIFICHE DI SISTEMA (CEI 62353)
CREATE TABLE IF NOT EXISTS system_verifications (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    uuid TEXT NOT NULL UNIQUE,
    system_name TEXT,
    destination_id INTEGER NOT NULL REFERENCES destinations(id) ON DELETE CASCADE,
    verification_date TEXT NOT NULL,
    profile_name TEXT NOT NULL,
    results_json TEXT NOT NULL,
    overall_status TEXT NOT NULL,
    visual_inspection_json TEXT,
    mti_instrument TEXT,
    mti_serial TEXT,
    mti_version TEXT,
    mti_cal_date TEXT,
    technician_name TEXT,
    technician_username TEXT,
    verification_code TEXT,
    last_modified TEXT NOT NULL,
    is_deleted INTEGER NOT NULL DEFAULT 0,
    is_synced INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS system_verification_devices (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    uuid TEXT NOT NULL UNIQUE,
    system_verification_id INTEGER NOT NULL REFERENCES system_verifications(id) ON DELETE CASCADE,
    device_id INTEGER NOT NULL REFERENCES devices(id) ON DELETE CASCADE,
    device_order INTEGER NOT NULL DEFAULT 0,
    last_modified TEXT NOT NULL,
    is_deleted INTEGER NOT NULL DEFAULT 0,
    is_synced INTEGER NOT NULL DEFAULT 0
);

-- ASSEGNAZIONI VERIFICHE
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

-- SEGNALAZIONI "NON MESSO A DISPOSIZIONE"
CREATE TABLE IF NOT EXISTS device_unavailability_reports (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    uuid                TEXT    NOT NULL UNIQUE,
    device_id           INTEGER NOT NULL REFERENCES devices(id) ON DELETE CASCADE,
    destination_id      INTEGER NOT NULL REFERENCES destinations(id) ON DELETE CASCADE,
    period_start        TEXT    NOT NULL,
    period_end          TEXT    NOT NULL,
    report_date         TEXT    NOT NULL,
    reason              TEXT    NOT NULL,
    technician_name     TEXT,
    technician_username TEXT,
    created_at          TEXT    NOT NULL DEFAULT (datetime('now')),
    last_modified       TEXT    NOT NULL DEFAULT (datetime('now')),
    is_deleted          INTEGER NOT NULL DEFAULT 0,
    is_synced           INTEGER NOT NULL DEFAULT 0
);

-- INDICI
-- Nota: idx_devices_serial_unique assente: duplicati serial_number permessi.

CREATE UNIQUE INDEX IF NOT EXISTS idx_verifications_verification_code_unique
ON verifications(verification_code)
WHERE verification_code IS NOT NULL AND verification_code <> '';

CREATE UNIQUE INDEX IF NOT EXISTS idx_system_verifications_code_unique
ON system_verifications(verification_code)
WHERE verification_code IS NOT NULL AND verification_code <> '';

CREATE INDEX IF NOT EXISTS idx_audit_timestamp ON audit_log(timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_audit_username ON audit_log(username);
CREATE INDEX IF NOT EXISTS idx_audit_action ON audit_log(action_type);
CREATE INDEX IF NOT EXISTS idx_audit_entity ON audit_log(entity_type, entity_id);

CREATE INDEX IF NOT EXISTS idx_sync_conflicts_status ON sync_conflicts(status);
CREATE INDEX IF NOT EXISTS idx_sync_conflicts_table ON sync_conflicts(table_name);

CREATE INDEX IF NOT EXISTS idx_attachments_verification
    ON verification_attachments(verification_id, verification_type);

CREATE INDEX IF NOT EXISTS idx_system_verification_devices_sv
    ON system_verification_devices(system_verification_id);
CREATE INDEX IF NOT EXISTS idx_system_verification_devices_device
    ON system_verification_devices(device_id);

CREATE INDEX IF NOT EXISTS idx_assignments_assigned_to ON verification_assignments(assigned_to);
CREATE INDEX IF NOT EXISTS idx_assignments_status      ON verification_assignments(status);
CREATE INDEX IF NOT EXISTS idx_assignments_device_id   ON verification_assignments(device_id);
