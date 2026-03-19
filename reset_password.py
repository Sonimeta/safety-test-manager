# reset_password.py
import psycopg2
from argon2 import PasswordHasher
import getpass
import logging

# Configura il logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# Copia gli stessi parametri del database che usi in real_server.py
DB_PARAMS = {
    "dbname": "verifiche_db",
    "user": "admin",
    "password": "admin",
    "host": "195.149.221.71",
    "port": "5432"
}

def reset_user_password():
    """
    Resetta la password per un utente specifico nel database PostgreSQL.
    """
    ph = PasswordHasher()
    
    # Chiede all'amministratore i dati necessari
    username_to_reset = input("Inserisci lo username dell'utente di cui resettare la password: ")
    if not username_to_reset:
        print("Username non valido.")
        return

    new_password = getpass.getpass("Inserisci la nuova password: ")
    if not new_password:
        print("La password non può essere vuota.")
        return
        
    # Crea il nuovo hash della password
    try:
        new_hashed_password = ph.hash(new_password)
        logging.info("Nuovo hash della password generato con successo.")
    except Exception as e:
        logging.error(f"Errore durante la creazione dell'hash: {e}")
        return

    conn = None
    try:
        # Esegui l'aggiornamento sul database
        logging.info(f"Tentativo di connessione al database per aggiornare l'utente '{username_to_reset}'...")
        conn = psycopg2.connect(**DB_PARAMS)
        cursor = conn.cursor()
        
        cursor.execute(
            "UPDATE users SET hashed_password = %s WHERE username = %s",
            (new_hashed_password, username_to_reset)
        )
        
        # Controlla se l'aggiornamento è andato a buon fine
        if cursor.rowcount == 0:
            logging.error(f"OPERAZIONE FALLITA: Nessun utente trovato con lo username '{username_to_reset}'. Nessuna modifica effettuata.")
            print("\nERRORE: Utente non trovato. Controlla che lo username sia corretto.")
        else:
            conn.commit()
            logging.info(f"Password per l'utente '{username_to_reset}' aggiornata con successo.")
            print("\nSUCCESSO: La password è stata resettata.")

    except Exception as e:
        if conn:
            conn.rollback()
        logging.error("ERRORE: Impossibile aggiornare la password nel database.", exc_info=True)
        print(f"\nERRORE: Non è stato possibile completare l'operazione. Dettagli nel log.")
    finally:
        if conn:
            conn.close()

if __name__ == "__main__":
    reset_user_password()