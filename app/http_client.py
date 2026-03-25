# app/http_client.py
"""
Modulo centralizzato per le chiamate HTTP al server SyncAPI.
Gestisce automaticamente il certificato SSL per connessioni HTTPS
con certificato self-signed.

Uso:
    from app.http_client import http_session
    
    # Funziona esattamente come requests, ma con SSL preconfigurato
    response = http_session.get(url, headers=headers, timeout=10)
    response = http_session.post(url, json=data, headers=headers, timeout=10)
"""

import logging
import requests
from app import config

# Crea una sessione requests globale con il certificato CA configurato
http_session = requests.Session()

def _configure_ssl():
    """Configura la sessione HTTP con il certificato SSL se disponibile."""
    if config.SSL_CA_CERT:
        http_session.verify = config.SSL_CA_CERT
        logging.info(f"🔒 Sessione HTTP configurata con certificato CA: {config.SSL_CA_CERT}")
    elif config.SERVER_URL.startswith("https://"):
        # HTTPS senza certificato CA custom: usa i certificati di sistema
        # Se self-signed, fallirà. L'utente deve configurare ssl_ca_cert in config.ini
        logging.warning(
            "⚠ Server configurato in HTTPS ma nessun certificato CA personalizzato trovato. "
            "Se il server usa un certificato self-signed, configura 'ssl_ca_cert' in config.ini"
        )

_configure_ssl()
