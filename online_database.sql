-- ==========================================
-- Online DB bootstrap (PostgreSQL)
-- Safety Test Manager - Full Schema
-- ==========================================

CREATE EXTENSION IF NOT EXISTS "pgcrypto";

-- --- 1) Users ---
CREATE TABLE IF NOT EXISTS users (
    id SERIAL PRIMARY KEY,
    uuid TEXT UNIQUE,
    username TEXT NOT NULL UNIQUE,
    hashed_password TEXT NOT NULL,
    first_name TEXT,
    last_name TEXT,
    sede TEXT,
    token TEXT,
    role TEXT NOT NULL CHECK (role IN ('admin', 'moderator', 'technician', 'seg')),
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    is_deleted BOOLEAN NOT NULL DEFAULT FALSE,
    last_modified TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Admin di default (idempotente)
INSERT INTO users (username, hashed_password, first_name, last_name, role)
SELECT 'admin', '$argon2d$v=19$m=16,t=2,p=1$anUycEd2c3NqREQwZ05YdA$D1hwGTwOTQGISAV+qukA8g', 'ELSON', 'META', 'admin'
WHERE NOT EXISTS (SELECT 1 FROM users WHERE username='admin');

-- --- 2) Customers ---
CREATE TABLE IF NOT EXISTS customers (
    id SERIAL PRIMARY KEY,
    uuid TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    address TEXT,
    phone TEXT,
    email TEXT,
    last_modified TIMESTAMPTZ NOT NULL,
    is_deleted BOOLEAN NOT NULL DEFAULT FALSE,
    is_synced BOOLEAN NOT NULL DEFAULT TRUE
);

-- --- 3) Destinations (dipende da customers) ---
CREATE TABLE IF NOT EXISTS destinations (
    id SERIAL PRIMARY KEY,
    uuid VARCHAR(255) NOT NULL UNIQUE,
    customer_id INTEGER NOT NULL REFERENCES customers(id) ON DELETE CASCADE,
    name VARCHAR(255) NOT NULL,
    address TEXT,
    phone TEXT,
    email TEXT,
    last_modified TIMESTAMPTZ NOT NULL,
    is_synced BOOLEAN NOT NULL DEFAULT FALSE,
    is_deleted BOOLEAN NOT NULL DEFAULT FALSE
);

-- --- 4) Devices (dipende da destinations) ---
CREATE TABLE IF NOT EXISTS devices (
    id SERIAL PRIMARY KEY,
    uuid VARCHAR(255) NOT NULL UNIQUE,
    destination_id INTEGER REFERENCES destinations(id) ON DELETE SET NULL,
    serial_number VARCHAR(255),
    description TEXT,
    manufacturer VARCHAR(255),
    model VARCHAR(255),
    department VARCHAR(255),
    applied_parts_json TEXT,
    customer_inventory VARCHAR(255),
    ams_inventory VARCHAR(255),
    verification_interval INTEGER,
    default_profile_key TEXT,
    default_functional_profile_key TEXT,
    next_verification_date DATE,
    status TEXT NOT NULL DEFAULT 'active',
    last_modified TIMESTAMPTZ NOT NULL,
    is_synced BOOLEAN NOT NULL DEFAULT FALSE,
    is_deleted BOOLEAN NOT NULL DEFAULT FALSE
);

-- --- 5) Verifications (dipende da devices) ---
CREATE TABLE IF NOT EXISTS verifications (
    id SERIAL PRIMARY KEY,
    uuid TEXT NOT NULL UNIQUE,
    device_id INTEGER REFERENCES devices(id) ON DELETE CASCADE,
    verification_date DATE NOT NULL,
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
    notes TEXT,
    last_modified TIMESTAMPTZ NOT NULL,
    is_deleted BOOLEAN NOT NULL DEFAULT FALSE,
    is_synced BOOLEAN NOT NULL DEFAULT TRUE
);

-- --- 6) Functional Verifications (dipende da devices) ---
CREATE TABLE IF NOT EXISTS functional_verifications (
    id SERIAL PRIMARY KEY,
    uuid TEXT NOT NULL UNIQUE,
    device_id INTEGER NOT NULL REFERENCES devices(id) ON DELETE CASCADE,
    profile_key TEXT NOT NULL,
    verification_date DATE NOT NULL,
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
    last_modified TIMESTAMPTZ NOT NULL,
    is_synced BOOLEAN NOT NULL DEFAULT FALSE,
    is_deleted BOOLEAN NOT NULL DEFAULT FALSE
);

-- --- 7) MTI Instruments (indipendente) ---
CREATE TABLE IF NOT EXISTS mti_instruments (
    id SERIAL PRIMARY KEY,
    uuid TEXT NOT NULL UNIQUE,
    instrument_name TEXT NOT NULL,
    serial_number TEXT NOT NULL,
    fw_version TEXT,
    calibration_date TEXT,
    instrument_type TEXT DEFAULT 'electrical',
    sede TEXT,
    is_default BOOLEAN NOT NULL DEFAULT FALSE,
    last_modified TIMESTAMPTZ NOT NULL,
    is_deleted BOOLEAN NOT NULL DEFAULT FALSE,
    is_synced BOOLEAN NOT NULL DEFAULT TRUE
);

-- --- 8) Profiles & Profile Tests ---
CREATE TABLE IF NOT EXISTS profiles (
    id SERIAL PRIMARY KEY,
    uuid VARCHAR(255) NOT NULL UNIQUE,
    profile_key VARCHAR(255) NOT NULL,
    name VARCHAR(255) NOT NULL,
    norma VARCHAR(255) NOT NULL DEFAULT 'CEI EN 62353',
    last_modified TIMESTAMPTZ NOT NULL,
    is_synced BOOLEAN NOT NULL DEFAULT FALSE,
    is_deleted BOOLEAN NOT NULL DEFAULT FALSE
);

CREATE TABLE IF NOT EXISTS profile_tests (
    id SERIAL PRIMARY KEY,
    uuid VARCHAR(255) NOT NULL UNIQUE,
    profile_id INTEGER NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
    name VARCHAR(255) NOT NULL,
    parameter VARCHAR(255),
    limits_json TEXT,
    is_applied_part_test BOOLEAN NOT NULL DEFAULT FALSE,
    last_modified TIMESTAMPTZ NOT NULL,
    is_synced BOOLEAN NOT NULL DEFAULT FALSE,
    is_deleted BOOLEAN NOT NULL DEFAULT FALSE
);

-- --- 9) Functional Profiles ---
CREATE TABLE IF NOT EXISTS functional_profiles (
    id SERIAL PRIMARY KEY,
    uuid TEXT NOT NULL UNIQUE,
    profile_key TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    device_type TEXT,
    instrument_id INTEGER,
    instrument_ids TEXT,
    schema_json TEXT NOT NULL,
    last_modified TIMESTAMPTZ NOT NULL,
    is_synced BOOLEAN NOT NULL DEFAULT FALSE,
    is_deleted BOOLEAN NOT NULL DEFAULT FALSE
);

-- --- 10) Signatures ---
CREATE TABLE IF NOT EXISTS signatures (
    username VARCHAR(255) PRIMARY KEY NOT NULL,
    signature_data BYTEA,
    last_modified TIMESTAMPTZ NOT NULL,
    is_synced BOOLEAN NOT NULL DEFAULT FALSE
);

-- --- 11) Audit Log ---
CREATE TABLE IF NOT EXISTS audit_log (
    id SERIAL PRIMARY KEY,
    uuid TEXT NOT NULL UNIQUE,
    timestamp TIMESTAMPTZ NOT NULL,
    username TEXT NOT NULL,
    user_full_name TEXT,
    action_type TEXT NOT NULL,
    entity_type TEXT NOT NULL,
    entity_id INTEGER,
    entity_description TEXT,
    details TEXT,
    ip_address TEXT,
    last_modified TIMESTAMPTZ NOT NULL,
    is_synced BOOLEAN NOT NULL DEFAULT TRUE,
    is_deleted BOOLEAN NOT NULL DEFAULT FALSE
);

-- --- 12) Verification Attachments (Foto VE/VF e Certificati Strumenti) ---
CREATE TABLE IF NOT EXISTS verification_attachments (
    id SERIAL PRIMARY KEY,
    uuid TEXT NOT NULL UNIQUE,
    verification_id INTEGER NOT NULL,
    verification_type TEXT NOT NULL DEFAULT 'functional',
    filename TEXT NOT NULL,
    file_data BYTEA,
    mime_type TEXT NOT NULL DEFAULT 'image/jpeg',
    file_size INTEGER NOT NULL DEFAULT 0,
    description TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_modified TIMESTAMPTZ NOT NULL,
    is_synced BOOLEAN NOT NULL DEFAULT TRUE,
    is_deleted BOOLEAN NOT NULL DEFAULT FALSE
);

-- --- 13) System Verifications ---
CREATE TABLE IF NOT EXISTS system_verifications (
    id SERIAL PRIMARY KEY,
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
    notes TEXT,
    last_modified TIMESTAMPTZ NOT NULL,
    is_synced BOOLEAN NOT NULL DEFAULT TRUE,
    is_deleted BOOLEAN NOT NULL DEFAULT FALSE
);

CREATE TABLE IF NOT EXISTS system_verification_devices (
    id SERIAL PRIMARY KEY,
    uuid TEXT NOT NULL UNIQUE,
    system_verification_id INTEGER NOT NULL REFERENCES system_verifications(id) ON DELETE CASCADE,
    device_id INTEGER NOT NULL REFERENCES devices(id) ON DELETE CASCADE,
    device_order INTEGER NOT NULL DEFAULT 0,
    last_modified TIMESTAMPTZ NOT NULL,
    is_synced BOOLEAN NOT NULL DEFAULT TRUE,
    is_deleted BOOLEAN NOT NULL DEFAULT FALSE
);

-- --- 14) Ecografo Quality Checks & Probes & Controls ---
CREATE TABLE IF NOT EXISTS ecografo_quality_checks (
    id SERIAL PRIMARY KEY,
    uuid TEXT NOT NULL UNIQUE,
    device_id INTEGER NOT NULL REFERENCES devices(id) ON DELETE CASCADE,
    verification_date TEXT NOT NULL,
    technician_name TEXT,
    technician_username TEXT,
    verification_code TEXT,
    overall_status TEXT NOT NULL DEFAULT 'NON VALUTATO',
    notes TEXT,
    last_modified TIMESTAMPTZ NOT NULL,
    is_deleted BOOLEAN NOT NULL DEFAULT FALSE,
    is_synced BOOLEAN NOT NULL DEFAULT TRUE
);

CREATE TABLE IF NOT EXISTS ecografo_quality_probes (
    id SERIAL PRIMARY KEY,
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
    last_modified TIMESTAMPTZ NOT NULL,
    is_deleted BOOLEAN NOT NULL DEFAULT FALSE,
    is_synced BOOLEAN NOT NULL DEFAULT TRUE
);

CREATE TABLE IF NOT EXISTS ecografo_quality_controls (
    id SERIAL PRIMARY KEY,
    uuid TEXT NOT NULL UNIQUE,
    probe_id INTEGER NOT NULL REFERENCES ecografo_quality_probes(id) ON DELETE CASCADE,
    control_key TEXT NOT NULL,
    control_label TEXT,
    value TEXT,
    unit TEXT,
    passed INTEGER,
    notes TEXT,
    last_modified TIMESTAMPTZ NOT NULL,
    is_deleted BOOLEAN NOT NULL DEFAULT FALSE,
    is_synced BOOLEAN NOT NULL DEFAULT TRUE
);

-- --- 15) Verification Assignments (Lavori Assegnati ai Tecnici) ---
CREATE TABLE IF NOT EXISTS verification_assignments (
    id              SERIAL PRIMARY KEY,
    uuid            TEXT        NOT NULL UNIQUE,
    device_id       INTEGER     REFERENCES devices(id) ON DELETE CASCADE,
    destination_id  INTEGER     REFERENCES destinations(id) ON DELETE CASCADE,
    assigned_to     TEXT        NOT NULL,
    assigned_by     TEXT        NOT NULL,
    notes           TEXT,
    priority        TEXT        NOT NULL DEFAULT 'normal',
    due_date        DATE,
    status          TEXT        NOT NULL DEFAULT 'pending',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    completed_at    TIMESTAMPTZ,
    is_deleted      BOOLEAN     NOT NULL DEFAULT FALSE,
    last_modified   TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- --- 16) Device Unavailability Reports (Non a Disposizione) ---
CREATE TABLE IF NOT EXISTS device_unavailability_reports (
    id                  SERIAL PRIMARY KEY,
    uuid                TEXT        NOT NULL UNIQUE,
    device_id           INTEGER     NOT NULL REFERENCES devices(id) ON DELETE CASCADE,
    destination_id      INTEGER     NOT NULL REFERENCES destinations(id) ON DELETE CASCADE,
    period_start        TEXT        NOT NULL,
    period_end          TEXT        NOT NULL,
    report_date         TEXT        NOT NULL,
    reason              TEXT        NOT NULL,
    technician_name     TEXT,
    technician_username TEXT,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_modified       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    is_deleted          BOOLEAN     NOT NULL DEFAULT FALSE,
    is_synced           BOOLEAN     NOT NULL DEFAULT TRUE
);

-- --- 17) Hard Deletes Tombstone (per propagazione eliminazioni definitive) ---
CREATE TABLE IF NOT EXISTS hard_deletes (
    id SERIAL PRIMARY KEY,
    table_name VARCHAR(100) NOT NULL,
    record_uuid VARCHAR(255) NOT NULL,
    deleted_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    deleted_by VARCHAR(100)
);

-- --- 18) Applied Parts Presets (Preset Parti Applicate) ---
CREATE TABLE IF NOT EXISTS applied_parts_presets (
    id SERIAL PRIMARY KEY,
    uuid TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    description TEXT,
    parts_json TEXT NOT NULL,
    last_modified TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    is_deleted BOOLEAN NOT NULL DEFAULT FALSE,
    is_synced BOOLEAN NOT NULL DEFAULT TRUE
);

-- ==========================================
-- INDICI E VINCOLI DI UNICITÀ PARZIALI
-- ==========================================

-- UUID Indexes
CREATE INDEX IF NOT EXISTS idx_customers_uuid ON customers(uuid);
CREATE INDEX IF NOT EXISTS idx_destinations_uuid ON destinations(uuid);
CREATE INDEX IF NOT EXISTS idx_devices_uuid ON devices(uuid);
CREATE INDEX IF NOT EXISTS idx_verifications_uuid ON verifications(uuid);
CREATE INDEX IF NOT EXISTS idx_functional_verifications_uuid ON functional_verifications(uuid);
CREATE INDEX IF NOT EXISTS idx_mti_instruments_uuid ON mti_instruments(uuid);
CREATE INDEX IF NOT EXISTS idx_profiles_uuid ON profiles(uuid);
CREATE INDEX IF NOT EXISTS idx_profile_tests_uuid ON profile_tests(uuid);
CREATE INDEX IF NOT EXISTS idx_functional_profiles_uuid ON functional_profiles(uuid);
CREATE INDEX IF NOT EXISTS idx_applied_parts_presets_uuid ON applied_parts_presets(uuid);
CREATE INDEX IF NOT EXISTS idx_audit_log_uuid ON audit_log(uuid);
CREATE INDEX IF NOT EXISTS idx_verification_attachments_uuid ON verification_attachments(uuid);
CREATE INDEX IF NOT EXISTS idx_ecografo_quality_checks_uuid ON ecografo_quality_checks(uuid);
CREATE INDEX IF NOT EXISTS idx_ecografo_quality_probes_uuid ON ecografo_quality_probes(uuid);
CREATE INDEX IF NOT EXISTS idx_ecografo_quality_controls_uuid ON ecografo_quality_controls(uuid);
CREATE INDEX IF NOT EXISTS idx_assign_uuid ON verification_assignments(uuid);
CREATE INDEX IF NOT EXISTS idx_unavail_uuid ON device_unavailability_reports(uuid);

-- Foreign Key Indexes
CREATE INDEX IF NOT EXISTS idx_destinations_customer_id ON destinations(customer_id);
CREATE INDEX IF NOT EXISTS idx_devices_destination_id ON devices(destination_id);
CREATE INDEX IF NOT EXISTS idx_verifications_device_id ON verifications(device_id);
CREATE INDEX IF NOT EXISTS idx_functional_verifications_device_id ON functional_verifications(device_id);
CREATE INDEX IF NOT EXISTS idx_profile_tests_profile_id ON profile_tests(profile_id);
CREATE INDEX IF NOT EXISTS idx_attachments_verification ON verification_attachments(verification_id, verification_type);
CREATE INDEX IF NOT EXISTS idx_system_verification_devices_sv ON system_verification_devices(system_verification_id);
CREATE INDEX IF NOT EXISTS idx_system_verification_devices_device ON system_verification_devices(device_id);
CREATE INDEX IF NOT EXISTS idx_ecografo_quality_checks_device ON ecografo_quality_checks(device_id, verification_date DESC);
CREATE INDEX IF NOT EXISTS idx_ecografo_quality_probes_check ON ecografo_quality_probes(check_id, probe_order);
CREATE INDEX IF NOT EXISTS idx_ecografo_quality_controls_probe ON ecografo_quality_controls(probe_id, control_key);
CREATE INDEX IF NOT EXISTS idx_applied_parts_presets_name ON applied_parts_presets(name);
CREATE INDEX IF NOT EXISTS idx_applied_parts_presets_deleted ON applied_parts_presets(is_deleted);
CREATE INDEX IF NOT EXISTS idx_assign_to ON verification_assignments(assigned_to);
CREATE INDEX IF NOT EXISTS idx_assign_status ON verification_assignments(status);
CREATE INDEX IF NOT EXISTS idx_assign_device ON verification_assignments(device_id);
CREATE INDEX IF NOT EXISTS idx_assign_dest ON verification_assignments(destination_id);
CREATE INDEX IF NOT EXISTS idx_unavail_device ON device_unavailability_reports(device_id);
CREATE INDEX IF NOT EXISTS idx_unavail_dest ON device_unavailability_reports(destination_id);
CREATE INDEX IF NOT EXISTS idx_unavail_period ON device_unavailability_reports(period_start, period_end);
CREATE INDEX IF NOT EXISTS idx_hard_deletes_deleted_at ON hard_deletes(deleted_at);
CREATE INDEX IF NOT EXISTS idx_hard_deletes_table_uuid ON hard_deletes(table_name, record_uuid);

-- Audit Log Indexes
CREATE INDEX IF NOT EXISTS idx_audit_timestamp ON audit_log(timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_audit_username ON audit_log(username);
CREATE INDEX IF NOT EXISTS idx_audit_action ON audit_log(action_type);
CREATE INDEX IF NOT EXISTS idx_audit_entity ON audit_log(entity_type, entity_id);

-- Indice per ricerca su matricola/seriale (non univoco: i duplicati sono consentiti)
CREATE INDEX IF NOT EXISTS idx_devices_serial_number
    ON devices(serial_number);

CREATE UNIQUE INDEX IF NOT EXISTS idx_profiles_profile_key_unique
    ON profiles(profile_key)
    WHERE is_deleted = FALSE;

CREATE UNIQUE INDEX IF NOT EXISTS idx_system_verifications_code_unique
    ON system_verifications(verification_code)
    WHERE verification_code IS NOT NULL AND verification_code <> '' AND is_deleted = FALSE;

CREATE UNIQUE INDEX IF NOT EXISTS idx_ecografo_quality_checks_code_unique
    ON ecografo_quality_checks(verification_code)
    WHERE verification_code IS NOT NULL AND verification_code <> '' AND is_deleted = FALSE;

-- ==============================================================================
-- MIGRAZIONI IDEMPOTENTI PER DATABASE ESISTENTI (NON TOCCANO I DATI PRESENTI)
-- ==============================================================================

-- 1. Rimozione vincolo di unicità sui seriali (duplicati permessi)
DROP INDEX IF EXISTS idx_devices_serial_unique;

-- 2. Colonne Users
ALTER TABLE users ADD COLUMN IF NOT EXISTS uuid TEXT UNIQUE;
ALTER TABLE users ADD COLUMN IF NOT EXISTS sede TEXT;
ALTER TABLE users ADD COLUMN IF NOT EXISTS token TEXT;
ALTER TABLE users ADD COLUMN IF NOT EXISTS is_active BOOLEAN NOT NULL DEFAULT TRUE;
ALTER TABLE users ADD COLUMN IF NOT EXISTS is_deleted BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE users ADD COLUMN IF NOT EXISTS last_modified TIMESTAMPTZ NOT NULL DEFAULT NOW();

-- 3. Colonne MTI Instruments
ALTER TABLE mti_instruments ADD COLUMN IF NOT EXISTS sede TEXT;
ALTER TABLE mti_instruments ADD COLUMN IF NOT EXISTS instrument_type TEXT DEFAULT 'electrical';
ALTER TABLE mti_instruments ADD COLUMN IF NOT EXISTS is_default BOOLEAN NOT NULL DEFAULT FALSE;

-- 4. Colonne Profiles & Functional Profiles
ALTER TABLE profiles ADD COLUMN IF NOT EXISTS norma VARCHAR(255) NOT NULL DEFAULT 'CEI EN 62353';
ALTER TABLE functional_profiles ADD COLUMN IF NOT EXISTS device_type TEXT;
ALTER TABLE functional_profiles ADD COLUMN IF NOT EXISTS instrument_id INTEGER;
ALTER TABLE functional_profiles ADD COLUMN IF NOT EXISTS instrument_ids TEXT;

-- 5. Colonne Verifications
ALTER TABLE verifications ADD COLUMN IF NOT EXISTS verification_code TEXT;
ALTER TABLE verifications ADD COLUMN IF NOT EXISTS notes TEXT;

-- 6. Colonne Verification Assignments
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'verification_assignments') THEN
        ALTER TABLE verification_assignments ADD COLUMN IF NOT EXISTS destination_id INTEGER REFERENCES destinations(id) ON DELETE CASCADE;
        ALTER TABLE verification_assignments ADD COLUMN IF NOT EXISTS last_modified TIMESTAMPTZ NOT NULL DEFAULT NOW();
        ALTER TABLE verification_assignments ALTER COLUMN device_id DROP NOT NULL;
    END IF;
END $$;

-- 7. Migrazione colonne device_unavailability_reports a BOOLEAN
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.columns 
        WHERE table_name = 'device_unavailability_reports' 
          AND column_name = 'is_deleted' 
          AND data_type IN ('smallint', 'integer', 'bigint')
    ) THEN
        ALTER TABLE device_unavailability_reports ALTER COLUMN is_deleted DROP DEFAULT;
        ALTER TABLE device_unavailability_reports ALTER COLUMN is_deleted TYPE BOOLEAN USING (is_deleted <> 0);
        ALTER TABLE device_unavailability_reports ALTER COLUMN is_deleted SET DEFAULT FALSE;

        ALTER TABLE device_unavailability_reports ALTER COLUMN is_synced DROP DEFAULT;
        ALTER TABLE device_unavailability_reports ALTER COLUMN is_synced TYPE BOOLEAN USING (is_synced <> 0);
        ALTER TABLE device_unavailability_reports ALTER COLUMN is_synced SET DEFAULT FALSE;
    END IF;
END $$;

-- 8. Tabella applied_parts_presets
CREATE TABLE IF NOT EXISTS applied_parts_presets (
    id SERIAL PRIMARY KEY,
    uuid TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    description TEXT,
    parts_json TEXT NOT NULL,
    last_modified TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    is_deleted BOOLEAN NOT NULL DEFAULT FALSE,
    is_synced BOOLEAN NOT NULL DEFAULT TRUE
);

