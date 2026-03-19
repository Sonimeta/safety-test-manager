PRAGMA foreign_keys=ON;

ALTER TABLE devices
ADD COLUMN default_functional_profile_key TEXT;
