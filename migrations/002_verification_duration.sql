-- Aggiunge il tracciamento del tempo impiegato per l'esecuzione delle verifiche
-- (usato dal report di fatturazione). Disponibile solo per le verifiche
-- effettuate a partire dall'installazione di questo aggiornamento.
ALTER TABLE verifications ADD COLUMN duration_seconds INTEGER;
ALTER TABLE functional_verifications ADD COLUMN duration_seconds INTEGER;
