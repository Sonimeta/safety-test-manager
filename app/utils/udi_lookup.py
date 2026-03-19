"""
Utility per la ricerca di informazioni dispositivo tramite codice UDI/GTIN.
Utilizza:
1. Database GUDID (FDA) via API
2. Prefissi GS1 noti per identificare il produttore
3. Cache locale per ricerche precedenti
"""

import logging
import json
import os
from typing import Optional, Dict
from pathlib import Path

# Percorso per la cache locale
CACHE_DIR = Path(__file__).parent.parent.parent / "data"
CACHE_FILE = CACHE_DIR / "udi_cache.json"

# Prefissi GS1 noti per produttori di dispositivi medici
# I primi 6-9 caratteri del GTIN identificano l'azienda
GS1_PREFIXES = {
    # Philips
    "087123": "PHILIPS",
    "871011": "PHILIPS HEALTHCARE",
    "884227": "PHILIPS",
    
    # Smeg
    "080177": "SMEG",
    "801770": "SMEG",
    "08017709172831": {"manufacturer": "SMEG", "model": "WD 4060", "description": "LAVASTOVIGLIE PROFESSIONALE"},
    
    # GE Healthcare
    "060009": "GE HEALTHCARE",
    "079009": "GE HEALTHCARE",
    "818937": "GE HEALTHCARE",
    "008017": "GE MEDICAL SYSTEMS",
    
    # Siemens Healthineers
    "040009": "SIEMENS HEALTHINEERS",
    "401251": "SIEMENS",
    
    # Medtronic
    "076393": "MEDTRONIC",
    "863000": "MEDTRONIC",
    
    # Dräger
    "405010": "DRAEGER",
    "040501": "DRAEGER",
    
    # B. Braun
    "401612": "B. BRAUN",
    "404007": "B. BRAUN",
    
    # Fresenius
    "401007": "FRESENIUS",
    "400639": "FRESENIUS KABI",
    
    # Baxter
    "030010": "BAXTER",
    "060574": "BAXTER",
    
    # Mindray
    "693799": "MINDRAY",
    "069379": "MINDRAY",
    
    # Nihon Kohden
    "495aborr": "NIHON KOHDEN",
    "453560": "NIHON KOHDEN",
    
    # Welch Allyn (now Hillrom)
    "035082": "WELCH ALLYN",
    "079082": "WELCH ALLYN",
    
    # Masimo
    "094922": "MASIMO",
    
    # Spacelabs
    "087861": "SPACELABS",
    
    # Zoll
    "084482": "ZOLL",
    
    # Stryker
    "081227": "STRYKER",
    
    # Olympus
    "049353": "OLYMPUS",
    "453035": "OLYMPUS",
    
    # Karl Storz
    "402627": "KARL STORZ",
    
    # Getinge/Maquet
    "738021": "GETINGE",
    "073802": "MAQUET",
    
    # Hill-Rom
    "035004": "HILL-ROM",
    
    # Fujifilm/Fujinon
    "493406": "FUJIFILM",
    
    # Pentax Medical
    "453030": "PENTAX MEDICAL",
    
    # EDAN
    "692164": "EDAN",
    
    # Schiller
    "076817": "SCHILLER",
    
    # Mortara (now Hillrom)
    "635983": "MORTARA",
    
    # Criticare
    "084482": "CRITICARE",
    
    # Nonin
    "094593": "NONIN",
    
    # CareFusion (BD)
    "084369": "CAREFUSION",
    "038861": "BD",
    
    # Smiths Medical
    "084369": "SMITHS MEDICAL",
    
    # Teleflex
    "074551": "TELEFLEX",
    
    # Edwards Lifesciences
    "020103": "EDWARDS LIFESCIENCES",
    
    # Abbott
    "030067": "ABBOTT",
    
    # Boston Scientific
    "082781": "BOSTON SCIENTIFIC",
    
    # Johnson & Johnson / Ethicon
    "038137": "JOHNSON & JOHNSON",
    "381370": "ETHICON",
    
    # Cook Medical
    "035533": "COOK MEDICAL",
    
    # Italian/European prefixes
    "800": "ITALIA",  # Generic Italian prefix
    "803": "ITALIA",
    "840": "SPAGNA",
    "400": "GERMANIA",
    "750": "MESSICO",
    
    # European prefixes
    "061399": "DISPOSITIVO EUROPEO",
}


def load_cache() -> Dict:
    """Carica la cache locale."""
    try:
        if CACHE_FILE.exists():
            with open(CACHE_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
    except Exception as e:
        logging.warning(f"Errore caricamento cache UDI: {e}")
    return {}


def save_cache(cache: Dict):
    """Salva la cache locale."""
    try:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        with open(CACHE_FILE, 'w', encoding='utf-8') as f:
            json.dump(cache, f, indent=2, ensure_ascii=False)
    except Exception as e:
        logging.warning(f"Errore salvataggio cache UDI: {e}")


def lookup_gudid(gtin: str) -> Optional[Dict]:
    """
    Cerca informazioni nel database GUDID (FDA).
    https://accessgudid.nlm.nih.gov/
    
    Ritorna dict con: manufacturer, model, description, etc.
    """
    try:
        import requests
        
        # API GUDID - ricerca per GTIN/DI
        url = f"https://accessgudid.nlm.nih.gov/api/v3/devices/lookup.json?di={gtin}"
        
        logging.info(f"[UDI Lookup] Ricerca GUDID per GTIN: {gtin}")
        
        response = requests.get(url, timeout=10)
        
        if response.status_code == 200:
            data = response.json()
            
            if 'gudid' in data:
                device = data['gudid'].get('device', {})
                
                result = {
                    'gtin': gtin,
                    'manufacturer': device.get('companyName', ''),
                    'brand': device.get('brandName', ''),
                    'model': device.get('versionModelNumber', ''),
                    'description': device.get('deviceDescription', ''),
                    'catalog_number': device.get('catalogNumber', ''),
                    'device_class': device.get('deviceClass', ''),
                    'source': 'GUDID'
                }
                
                logging.info(f"[UDI Lookup] GUDID trovato: {result['manufacturer']} - {result['model']}")
                return result
        
        logging.info(f"[UDI Lookup] GUDID: nessun risultato per {gtin}")
        return None
        
    except ImportError:
        logging.warning("[UDI Lookup] Modulo 'requests' non disponibile per GUDID lookup")
        return None
    except Exception as e:
        logging.warning(f"[UDI Lookup] Errore GUDID: {e}")
        return None


def lookup_by_gs1_prefix(gtin: str) -> Optional[Dict]:
    """
    Cerca il produttore tramite il prefisso GS1 del GTIN.
    """
    if not gtin or len(gtin) < 6:
        return None
    
    # Prova prefissi di lunghezza decrescente (9, 8, 7, 6, 3)
    for prefix_len in [9, 8, 7, 6, 3]:
        if len(gtin) >= prefix_len:
            prefix = gtin[:prefix_len]
            if prefix in GS1_PREFIXES:
                manufacturer = GS1_PREFIXES[prefix]
                logging.info(f"[UDI Lookup] Prefisso GS1 {prefix} -> {manufacturer}")
                return {
                    'gtin': gtin,
                    'manufacturer': manufacturer,
                    'brand': '',
                    'model': '',
                    'description': '',
                    'source': 'GS1_PREFIX'
                }
    
    return None


def lookup_ministero_salute(gtin: str) -> Optional[Dict]:
    """
    Interroga il motore di ricerca del Ministero della Salute.
    """
    try:
        import requests
        from bs4 import BeautifulSoup
        
        # Il portale del Ministero non permette la ricerca diretta per GTIN via web form,
        # ma possiamo provare a cercare per codice catalogo (che spesso coincide o è parte dell'UDI)
        # o usare una ricerca Google mirata sul dominio del ministero.
        
        logging.info(f"[UDI Lookup] Ricerca Ministero Salute per: {gtin}")
        
        # Strategia: Ricerca Google mirata sul sito del ministero per trovare la scheda dispositivo
        search_url = f"https://www.google.com/search?q=site:salute.gov.it+{gtin}"
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
        
        response = requests.get(search_url, headers=headers, timeout=10)
        if response.status_code == 200:
            # Se troviamo un link alla RicercaDispositiviServlet, abbiamo fatto centro
            if 'RicercaDispositiviServlet' in response.text:
                logging.info("[UDI Lookup] Trovato riferimento nel database Ministero")
                # Qui potremmo approfondire il parsing, ma per ora usiamo il titolo dei risultati
                # per estrarre Marca e Modello se possibile
        
        return None # Fallback agli altri metodi se non troviamo dati certi
    except Exception as e:
        logging.warning(f"[UDI Lookup] Errore ricerca Ministero: {e}")
        return None

def lookup_udi(gtin: str, use_network: bool = True) -> Optional[Dict]:
    """
    Cerca informazioni sul dispositivo tramite GTIN.
    
    Args:
        gtin: Il codice GTIN (14 cifre)
        use_network: Se True, prova anche la ricerca online (GUDID)
    
    Returns:
        Dict con manufacturer, model, description, etc. o None
    """
    if not gtin:
        return None
    
    # Pulisci GTIN (rimuovi spazi, assicurati sia 14 cifre)
    gtin = gtin.strip().replace(' ', '')
    
    # Padding a 14 cifre se necessario
    if len(gtin) < 14:
        gtin = gtin.zfill(14)
    
    logging.info(f"[UDI Lookup] Ricerca per GTIN: {gtin}")
    
    # 1. Controlla prefissi completi (hardcoded) - PRIORITÀ MASSIMA
    if gtin in GS1_PREFIXES and isinstance(GS1_PREFIXES[gtin], dict):
        logging.info(f"[UDI Lookup] Trovato GTIN esatto in database interno: {gtin}")
        return GS1_PREFIXES[gtin]

    # 2. Prova GUDID (FDA) - Database internazionale ufficiale
    if use_network:
        result = lookup_gudid(gtin)
        if result:
            # Salva in cache locale per velocizzare ricerche future
            cache = load_cache()
            cache[gtin] = result
            save_cache(cache)
            return result

    # 3. Controlla cache locale (scansioni precedenti dell'utente)
    cache = load_cache()
    if gtin in cache:
        logging.info(f"[UDI Lookup] Trovato in cache: {cache[gtin].get('manufacturer', 'N/D')}")
        return cache[gtin]
    
    # 4. Fallback finale: prefisso GS1 (identifica almeno la marca)
    result = lookup_by_gs1_prefix(gtin)
    if result:
        return result
        
    return None


def get_manufacturer_from_udi(udi_code: str) -> str:
    """
    Estrae il produttore da un codice UDI completo.
    Delega a get_device_info_from_udi per il parsing.
    """
    info = get_device_info_from_udi(udi_code)
    return info.get('manufacturer', '') if info else ''


def get_device_info_from_udi(udi_code: str) -> Dict:
    """
    Estrae tutte le informazioni disponibili da un codice UDI.
    Supporta:
    - GS1 Human Readable:  (01)GTIN(21)SERIAL(10)LOT …
    - GS1 DataMatrix/Code128: 01GTIN21SERIAL  (FNC1 / GS separators)
    - GTIN puro (13-14 cifre)
    - Codici HIBC (prefisso +)
    
    Returns:
        Dict con: manufacturer, model, description, serial_number, lot_number, etc.
    """
    import re
    
    result: Dict = {
        'manufacturer': '',
        'model': '',
        'description': '',
        'serial_number': '',
        'lot_number': '',
        'production_date': '',
        'expiry_date': '',
        'gtin': ''
    }
    
    if not udi_code or not udi_code.strip():
        return result
    
    udi_code = udi_code.strip()
    
    # Rimuovi prefissi Symbology Identifier (DataMatrix, Code128, QR, ecc.)
    clean_code = re.sub(r'^\](?:d2|C1|e0|Q3|J1)', '', udi_code)
    # Normalizza i separatori GS (ASCII 29) e FNC1 in pipe
    clean_code = clean_code.replace(chr(29), '|').replace('\x1d', '|')
    
    gtin = None
    
    # --- 1. Formato con parentesi: (01)GTIN ---
    gtin_match = re.search(r'\(01\)(\d{14})', udi_code)
    if gtin_match:
        gtin = gtin_match.group(1)
    
    # --- 2. Formato DataMatrix senza parentesi: 01 + 14 cifre ---
    if not gtin:
        # Solo se il codice inizia con 01 seguito da 14 cifre (tipico DataMatrix GS1)
        dm_match = re.match(r'^01(\d{14})', clean_code)
        if dm_match:
            gtin = dm_match.group(1)
    
    # --- 3. GTIN puro (13 o 14 cifre senza AI) ---
    if not gtin:
        pure_digits = re.sub(r'\D', '', udi_code)
        if len(pure_digits) == 14:
            gtin = pure_digits
        elif len(pure_digits) == 13:
            gtin = '0' + pure_digits  # EAN-13 → GTIN-14
        elif len(pure_digits) == 12:
            gtin = '00' + pure_digits  # UPC-A → GTIN-14
    
    # Se abbiamo un GTIN, cerca nel database
    if gtin:
        result['gtin'] = gtin
        lookup_result = lookup_udi(gtin, use_network=True)
        if lookup_result:
            result['manufacturer'] = lookup_result.get('manufacturer', '')
            result['model'] = lookup_result.get('model', '')
            result['description'] = lookup_result.get('description', '')
    
    # --- Estrai seriale (AI 21) ---
    # Caratteri ammessi nel seriale: alfanumerici + - . / _ (GS1 spec)
    _SER_CHARS = r'[A-Za-z0-9\.\-\/\_\+]'
    serial_match = (
        re.search(rf'\(21\)({_SER_CHARS}+?)(?:\(|$)', udi_code) or
        re.search(rf'(?:^01\d{{14}}|[|])21({_SER_CHARS}+?)(?:[|]|$|(?=\d{{2}}[A-Z0-9]))', clean_code) or
        re.search(rf'21({_SER_CHARS}+?)$', clean_code)
    )
    if serial_match:
        result['serial_number'] = serial_match.group(1).strip()
    
    # --- Estrai lotto (AI 10) ---
    lot_match = (
        re.search(rf'\(10\)({_SER_CHARS}+?)(?:\(|$)', udi_code) or
        re.search(rf'(?:^01\d{{14}}|[|])10({_SER_CHARS}+?)(?:[|]|$|(?=11|17|21|240|30|91))', clean_code)
    )
    if lot_match:
        result['lot_number'] = lot_match.group(1).strip()
    
    # --- Estrai date ---
    prod_match = re.search(r'(?:\(11\)|\b11)(\d{6})', udi_code)
    if prod_match:
        result['production_date'] = prod_match.group(1)
    
    exp_match = re.search(r'(?:\(17\)|\b17)(\d{6})', udi_code)
    if exp_match:
        result['expiry_date'] = exp_match.group(1)
    
    logging.info(f"[UDI] Parsing risultato: GTIN={result['gtin']}, "
                 f"mfg={result['manufacturer']}, model={result['model']}, "
                 f"serial={result['serial_number']}, lot={result['lot_number']}")
    
    return result


# Test
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    
    # Test con alcuni GTIN noti
    test_gtins = [
        "00884227000610",  # Philips
        "00076393010123",  # Medtronic
        "00060009123456",  # GE Healthcare
    ]
    
    for gtin in test_gtins:
        print(f"\nGTIN: {gtin}")
        result = lookup_udi(gtin, use_network=False)
        if result:
            print(f"  Manufacturer: {result.get('manufacturer', 'N/D')}")
            print(f"  Source: {result.get('source', 'N/D')}")
