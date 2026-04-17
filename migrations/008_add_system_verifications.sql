-- Migrazione 008: Aggiunge il supporto per le verifiche di sistema (CEI 62353)
-- Una verifica di sistema raggruppa più dispositivi verificati insieme.

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

CREATE UNIQUE INDEX IF NOT EXISTS idx_system_verifications_code_unique
ON system_verifications(verification_code)
WHERE verification_code IS NOT NULL AND verification_code <> '';

CREATE INDEX IF NOT EXISTS idx_system_verification_devices_sv
ON system_verification_devices(system_verification_id);

CREATE INDEX IF NOT EXISTS idx_system_verification_devices_device
ON system_verification_devices(device_id);
