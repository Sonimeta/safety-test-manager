-- Migrazione 005: Indici di performance per accelerare dashboard, statistiche e ricerche

CREATE INDEX IF NOT EXISTS idx_verifications_device_id 
    ON verifications(device_id);

CREATE INDEX IF NOT EXISTS idx_verifications_date 
    ON verifications(verification_date);

CREATE INDEX IF NOT EXISTS idx_verifications_status 
    ON verifications(overall_status);

CREATE INDEX IF NOT EXISTS idx_verifications_tech 
    ON verifications(technician_name);

CREATE INDEX IF NOT EXISTS idx_verifications_del_date
    ON verifications(is_deleted, verification_date);

CREATE INDEX IF NOT EXISTS idx_func_verif_device_id 
    ON functional_verifications(device_id);

CREATE INDEX IF NOT EXISTS idx_func_verif_date 
    ON functional_verifications(verification_date);

CREATE INDEX IF NOT EXISTS idx_func_verif_del_date
    ON functional_verifications(is_deleted, verification_date);

CREATE INDEX IF NOT EXISTS idx_devices_dest_status 
    ON devices(destination_id, status, is_deleted);

CREATE INDEX IF NOT EXISTS idx_devices_next_verif 
    ON devices(next_verification_date);

CREATE INDEX IF NOT EXISTS idx_devices_del_status
    ON devices(is_deleted, status);

CREATE INDEX IF NOT EXISTS idx_destinations_cust 
    ON destinations(customer_id, is_deleted);
