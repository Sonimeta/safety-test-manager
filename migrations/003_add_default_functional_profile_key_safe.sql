PRAGMA foreign_keys=ON;

ALTER TABLE devices
ADD COLUMN IF NOT EXISTS default_functional_profile_key TEXT;

