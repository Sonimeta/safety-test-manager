PRAGMA foreign_keys=ON;

CREATE TABLE IF NOT EXISTS schema_version (
    version INTEGER NOT NULL
);
DELETE FROM schema_version;
INSERT INTO schema_version(version) VALUES (1);

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

CREATE TABLE IF NOT EXISTS profiles (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    uuid TEXT NOT NULL UNIQUE,
    profile_key TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    last_modified TEXT NOT NULL,
    is_synced INTEGER NOT NULL DEFAULT 0,
    is_deleted INTEGER NOT NULL DEFAULT 0
);

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

CREATE TABLE IF NOT EXISTS signatures (
    username TEXT PRIMARY KEY NOT NULL,
    signature_data BLOB,
    last_modified TEXT NOT NULL,
    is_synced INTEGER NOT NULL DEFAULT 0
);

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

CREATE UNIQUE INDEX IF NOT EXISTS idx_devices_serial_unique
ON devices(serial_number)
WHERE serial_number IS NOT NULL AND serial_number <> '' AND is_deleted = 0;

CREATE UNIQUE INDEX IF NOT EXISTS idx_verifications_verification_code_unique
ON verifications(verification_code)
WHERE verification_code IS NOT NULL AND verification_code <> '';

CREATE INDEX IF NOT EXISTS idx_audit_timestamp ON audit_log(timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_audit_username ON audit_log(username);
CREATE INDEX IF NOT EXISTS idx_audit_action ON audit_log(action_type);
CREATE INDEX IF NOT EXISTS idx_audit_entity ON audit_log(entity_type, entity_id);