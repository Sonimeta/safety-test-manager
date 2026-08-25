-- Migrazione 004: Aggiunta colonna sede alla tabella mti_instruments
PRAGMA foreign_keys=OFF;

-- Aggiunge la colonna sede alla tabella mti_instruments
ALTER TABLE mti_instruments ADD COLUMN sede TEXT;

PRAGMA foreign_keys=ON;
