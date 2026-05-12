# app/http_client.py
"""
Modulo centralizzato per le chiamate HTTP al server SyncAPI.
Gestisce automaticamente il certificato SSL e le credenziali
Cloudflare Access Service Token per connessioni Zero Trust.

Uso:
    from app.http_client import http_session
    
    # Funziona esattamente come requests, ma con SSL e CF preconfigurati
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
        # Con Cloudflare Tunnel il certificato è valido, quindi funziona senza configurazione aggiuntiva
        pass

def _configure_cloudflare_service_token():
    """
    Aggiunge gli header Cloudflare Access Service Token alla sessione.
    Necessario per autenticazione machine-to-machine con Cloudflare Zero Trust.
    """
    if config.CF_CLIENT_ID and config.CF_CLIENT_SECRET:
        http_session.headers.update({
            "CF-Access-Client-Id": config.CF_CLIENT_ID,
            "CF-Access-Client-Secret": config.CF_CLIENT_SECRET,
        })
        logging.info(f"☁️  CF Service Token impostato nella sessione HTTP: {config.CF_CLIENT_ID[:12]}...")
        logging.debug(f"[CF] Headers sessione: { {k: v[:8]+'...' for k,v in http_session.headers.items() if 'CF-Access' in k} }")
    else:
        logging.warning("⚠️  CF Service Token NON configurato nella sessione HTTP - sincronizzazione bloccata da Cloudflare!")

_configure_ssl()
_configure_cloudflare_service_token()
