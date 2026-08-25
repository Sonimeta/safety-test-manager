-- Migrazione 003: Controllo Qualità Sonde Ecografo
-- Aggiunge tabelle per tracciare i controlli qualità delle sonde ecografiche
-- collegati ai dispositivi in anagrafica.

CREATE TABLE IF NOT EXISTS ecografo_quality_checks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    uuid TEXT NOT NULL UNIQUE,
    device_id INTEGER NOT NULL REFERENCES devices(id) ON DELETE CASCADE,
    verification_date TEXT NOT NULL,
    technician_name TEXT,
    technician_username TEXT,
    verification_code TEXT,
    overall_status TEXT NOT NULL DEFAULT 'NON VALUTATO',
    notes TEXT,
    last_modified TEXT NOT NULL,
    is_deleted INTEGER NOT NULL DEFAULT 0,
    is_synced INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS ecografo_quality_probes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    uuid TEXT NOT NULL UNIQUE,
    check_id INTEGER NOT NULL REFERENCES ecografo_quality_checks(id) ON DELETE CASCADE,
    probe_order INTEGER NOT NULL DEFAULT 0,
    inventory TEXT,
    manufacturer TEXT,
    probe_type TEXT,
    serial_number TEXT,
    model TEXT,
    test_model TEXT,
    preset TEXT,
    gain TEXT,
    power TEXT,
    baseline TEXT,
    control_stage TEXT DEFAULT 'Baseline',
    overall_judgment TEXT,
    creation_year TEXT,
    notes TEXT,
    last_modified TEXT NOT NULL,
    is_deleted INTEGER NOT NULL DEFAULT 0,
    is_synced INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS ecografo_quality_controls (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    uuid TEXT NOT NULL UNIQUE,
    probe_id INTEGER NOT NULL REFERENCES ecografo_quality_probes(id) ON DELETE CASCADE,
    control_key TEXT NOT NULL,
    control_label TEXT,
    value TEXT,
    unit TEXT,
    passed INTEGER,
    notes TEXT,
    last_modified TEXT NOT NULL,
    is_deleted INTEGER NOT NULL DEFAULT 0,
    is_synced INTEGER NOT NULL DEFAULT 0
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_ecografo_quality_checks_code_unique
ON ecografo_quality_checks(verification_code)
WHERE verification_code IS NOT NULL AND verification_code <> '';

CREATE INDEX IF NOT EXISTS idx_ecografo_quality_checks_device
    ON ecografo_quality_checks(device_id, verification_date DESC);

CREATE INDEX IF NOT EXISTS idx_ecografo_quality_probes_check
    ON ecografo_quality_probes(check_id, probe_order);

CREATE INDEX IF NOT EXISTS idx_ecografo_quality_controls_probe
    ON ecografo_quality_controls(probe_id, control_key);
