"""
Utility per la ricerca di informazioni dispositivo tramite codice UDI/GTIN.
Utilizza:
1. Database GUDID (FDA) via API
2. Prefissi GS1 noti per identificare il produttore
3. Cache locale per ricerche precedenti
"""

import logging
import json
from typing import Any, Optional, Dict, Tuple
from pathlib import Path

# Percorso per la cache locale
CACHE_DIR = Path(__file__).parent.parent.parent / "data"
CACHE_FILE = CACHE_DIR / "udi_cache.json"

# API AccessGUDID v3 (FDA/NLM)
GUDID_LOOKUP_URL = "https://accessgudid.nlm.nih.gov/api/v3/devices/lookup.json"
GUDID_PARSE_UDI_URL = "https://accessgudid.nlm.nih.gov/api/v3/parse_udi.json"
GUDID_TIMEOUT = (5, 30)  # connect timeout, read timeout

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
    
    # Prefix shared by legacy/ambiguous local mappings
    "084482": "ZOLL / CRITICARE",
    
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
    
    # Nonin
    "094593": "NONIN",
    
    # CareFusion/Smiths Medical (ambiguous local mapping)
    "084369": "CAREFUSION / SMITHS MEDICAL",
    "038861": "BD",
    
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


def _request_gudid_json(
    url: str,
    params: Dict[str, str],
    context: str,
) -> Tuple[Optional[Dict[str, Any]], Dict[str, str]]:
    """Esegue una richiesta JSON verso AccessGUDID usando params percent-encoded."""
    try:
        import requests
    except ImportError:
        logging.warning("[UDI Lookup] Modulo 'requests' non disponibile per GUDID lookup")
        return None, {}

    try:
        response = requests.get(
            url,
            params=params,
            timeout=GUDID_TIMEOUT,
            headers={"Accept": "application/json"},
        )

        if response.status_code == 404:
            logging.info(f"[UDI Lookup] GUDID: nessun risultato ({context})")
            return None, dict(response.headers)

        if response.status_code == 400:
            logging.info(
                f"[UDI Lookup] GUDID ha rifiutato il formato della richiesta ({context})"
            )
            return None, dict(response.headers)

        response.raise_for_status()
        return response.json(), dict(response.headers)

    except requests.exceptions.Timeout as e:
        logging.warning(
            f"[UDI Lookup] Timeout GUDID ({context}) dopo {GUDID_TIMEOUT[1]}s: {e}"
        )
    except requests.exceptions.RequestException as e:
        logging.warning(f"[UDI Lookup] Errore rete GUDID ({context}): {e}")
    except ValueError as e:
        logging.warning(f"[UDI Lookup] Risposta JSON GUDID non valida ({context}): {e}")

    return None, {}


def _first_header(headers: Dict[str, str], *names: str) -> str:
    """Recupera un header ignorando differenze di maiuscole/minuscole."""
    lowered = {key.lower(): value for key, value in headers.items()}
    for name in names:
        value = lowered.get(name.lower())
        if value:
            return value
    return ""


def _extract_device_result(
    data: Dict[str, Any],
    di: str,
    source: str,
    parsed: Optional[Dict[str, str]] = None,
) -> Optional[Dict]:
    """Converte la risposta AccessGUDID nel formato usato dall'app."""
    device = data.get('gudid', {}).get('device', {}) if data else {}
    if not device:
        return None

    parsed = parsed or {}
    result = {
        'gtin': parsed.get('gtin') or parsed.get('di') or di,
        'manufacturer': device.get('companyName', ''),
        'brand': device.get('brandName', ''),
        'model': device.get('versionModelNumber', ''),
        'description': device.get('deviceDescription', ''),
        'catalog_number': device.get('catalogNumber', ''),
        'device_class': device.get('deviceClass', ''),
        'source': source
    }

    for key in (
        'issuing_agency',
        'serial_number',
        'lot_number',
        'production_date',
        'expiry_date',
    ):
        if parsed.get(key):
            result[key] = parsed[key]

    return result


def _parsed_udi_from_gudid_payload(
    data: Optional[Dict[str, Any]],
    headers: Optional[Dict[str, str]] = None,
) -> Dict[str, str]:
    """Normalizza i campi restituiti da Parse UDI API o dagli header del lookup."""
    data = data if isinstance(data, dict) else {}
    headers = headers or {}

    parsed = {
        'gtin': data.get('di') or _first_header(headers, 'di'),
        'di': data.get('di') or _first_header(headers, 'di'),
        'issuing_agency': data.get('issuingAgency') or _first_header(headers, 'issuingAgency'),
        'serial_number': data.get('serialNumber') or _first_header(headers, 'serialNumber'),
        'lot_number': data.get('lotNumber') or _first_header(headers, 'lotNumber'),
        'production_date': (
            data.get('manufacturingDate') or
            _first_header(headers, 'manufacturingDate')
        ),
        'expiry_date': (
            data.get('expirationDate') or
            _first_header(headers, 'expirationDate')
        ),
    }

    return {key: value for key, value in parsed.items() if value}


def parse_gudid_udi(udi_code: str) -> Optional[Dict[str, str]]:
    """
    Usa la Parse UDI API ufficiale per scomporre UDI GS1/HIBCC/ICCBBA.
    """
    if not udi_code:
        return None

    data, headers = _request_gudid_json(
        GUDID_PARSE_UDI_URL,
        {'udi': udi_code},
        f"parse_udi udi={udi_code[:40]}",
    )
    parsed = _parsed_udi_from_gudid_payload(data, headers)
    if parsed:
        parsed['source'] = 'GUDID_PARSE'
        logging.info(
            f"[UDI Lookup] Parse UDI OK: DI={parsed.get('di', '')}, "
            f"serial={parsed.get('serial_number', '')}"
        )
        return parsed

    return None


def lookup_gudid(gtin: str) -> Optional[Dict]:
    """
    Cerca informazioni nel database GUDID (FDA).
    https://accessgudid.nlm.nih.gov/
    
    Ritorna dict con: manufacturer, model, description, etc.
    """
    # API GUDID - ricerca per GTIN/DI. Requests percent-encoda i parametri.
    logging.info(f"[UDI Lookup] Ricerca GUDID per GTIN/DI: {gtin}")

    data, _headers = _request_gudid_json(
        GUDID_LOOKUP_URL,
        {'di': gtin},
        f"lookup di={gtin}",
    )

    result = _extract_device_result(data or {}, gtin, 'GUDID')
    if result:
        logging.info(f"[UDI Lookup] GUDID trovato: {result['manufacturer']} - {result['model']}")
        return result

    logging.info(f"[UDI Lookup] GUDID: nessun risultato per {gtin}")
    return None


def lookup_gudid_by_udi(udi_code: str) -> Optional[Dict]:
    """
    Cerca un dispositivo passando l'UDI completo alla Device Lookup API.
    AccessGUDID usa internamente Parse UDI e restituisce i campi parsed negli header.
    """
    if not udi_code:
        return None

    logging.info(f"[UDI Lookup] Ricerca GUDID per UDI completo: {udi_code[:40]}")

    data, headers = _request_gudid_json(
        GUDID_LOOKUP_URL,
        {'udi': udi_code},
        f"lookup udi={udi_code[:40]}",
    )
    parsed = _parsed_udi_from_gudid_payload(data.get('udi') if data else None, headers)
    result = _extract_device_result(data or {}, parsed.get('di', ''), 'GUDID_UDI', parsed)

    if result:
        logging.info(f"[UDI Lookup] GUDID UDI trovato: {result['manufacturer']} - {result['model']}")
        return result

    logging.info(f"[UDI Lookup] GUDID: nessun risultato per UDI {udi_code[:40]}")
    return None


def _save_lookup_to_cache(gtin: str, result: Dict):
    """Salva in cache solo risultati con dati dispositivo reali."""
    if not gtin or not result:
        return

    cache = load_cache()
    cache[gtin] = result
    save_cache(cache)


def _merge_device_info(target: Dict, source: Optional[Dict]):
    """Integra nel risultato solo i campi valorizzati, senza cancellare dati locali."""
    if not source:
        return

    field_map = {
        'gtin': 'gtin',
        'manufacturer': 'manufacturer',
        'model': 'model',
        'description': 'description',
        'serial_number': 'serial_number',
        'lot_number': 'lot_number',
        'production_date': 'production_date',
        'expiry_date': 'expiry_date',
    }

    for target_key, source_key in field_map.items():
        value = (source.get(source_key) or '').strip()
        if value and not target.get(target_key):
            target[target_key] = value


def _parse_gs1_compact_fields(clean_code: str, gtin: str) -> Dict[str, str]:
    """Parse minimale dei codici GS1 compatti letti da scanner senza parentesi."""
    if not clean_code or not gtin:
        return {}

    if clean_code.startswith(f"01{gtin}"):
        pos = 16
    else:
        return {}

    parsed: Dict[str, str] = {}
    fixed_date_fields = {
        '11': 'production_date',
        '17': 'expiry_date',
    }

    while pos < len(clean_code):
        if clean_code[pos] == '|':
            pos += 1
            continue

        ai = clean_code[pos:pos + 2]

        if ai in fixed_date_fields and len(clean_code) >= pos + 8:
            parsed[fixed_date_fields[ai]] = clean_code[pos + 2:pos + 8]
            pos += 8
            continue

        if ai == '21':
            end = clean_code.find('|', pos + 2)
            parsed['serial_number'] = clean_code[pos + 2:] if end == -1 else clean_code[pos + 2:end]
            pos = len(clean_code) if end == -1 else end + 1
            continue

        if ai == '10':
            end = clean_code.find('|', pos + 2)
            parsed['lot_number'] = clean_code[pos + 2:] if end == -1 else clean_code[pos + 2:end]
            pos = len(clean_code) if end == -1 else end + 1
            continue

        break

    return {key: value for key, value in parsed.items() if value}


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

    # 2. Controlla cache locale prima della rete: evita timeout inutili.
    cache = load_cache()
    if gtin in cache:
        logging.info(f"[UDI Lookup] Trovato in cache: {cache[gtin].get('manufacturer', 'N/D')}")
        return cache[gtin]

    # 3. Prova GUDID (FDA) - Database internazionale ufficiale
    if use_network:
        result = lookup_gudid(gtin)
        if result:
            _save_lookup_to_cache(gtin, result)
            return result

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


def get_device_info_from_udi(udi_code: str, use_network: bool = True) -> Dict:
    """
    Estrae tutte le informazioni disponibili da un codice UDI.
    Supporta:
    - GS1 Human Readable:  (01)GTIN(21)SERIAL(10)LOT …
    - GS1 DataMatrix/Code128: 01GTIN21SERIAL  (FNC1 / GS separators)
    - GTIN puro (13-14 cifre)
    - Codici HIBC (prefisso +)
    
    Args:
        udi_code: Codice UDI completo o GTIN puro.
        use_network: Se True, usa AccessGUDID quando i dati locali non bastano.

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
    api_udi_code = re.sub(r'^\](?:d2|C1|e0|Q3|J1)', '', udi_code)
    
    # Rimuovi prefissi Symbology Identifier (DataMatrix, Code128, QR, ecc.)
    clean_code = api_udi_code
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
    
    if gtin:
        result['gtin'] = gtin
        _merge_device_info(result, _parse_gs1_compact_fields(clean_code, gtin))
    
    # --- Estrai seriale (AI 21) ---
    # Caratteri ammessi nel seriale: alfanumerici + - . / _ (GS1 spec)
    _SER_CHARS = r'[A-Za-z0-9\.\-\/\_\+]'
    serial_match = (
        re.search(rf'\(21\)({_SER_CHARS}+?)(?:\(|$)', udi_code) or
        re.search(rf'(?:^01\d{{14}}|[|])21({_SER_CHARS}+?)(?:[|]|$|(?=\d{{2}}[A-Z0-9]))', clean_code) or
        re.search(rf'21({_SER_CHARS}+?)$', clean_code)
    )
    if serial_match and not result['serial_number']:
        result['serial_number'] = serial_match.group(1).strip()
    
    # --- Estrai lotto (AI 10) ---
    lot_match = (
        re.search(rf'\(10\)({_SER_CHARS}+?)(?:\(|$)', udi_code) or
        re.search(rf'(?:^01\d{{14}}|[|])10({_SER_CHARS}+?)(?:[|]|$|(?=11|17|21|240|30|91))', clean_code)
    )
    if lot_match and not result['lot_number']:
        result['lot_number'] = lot_match.group(1).strip()
    
    # --- Estrai date ---
    prod_match = re.search(r'(?:\(11\)|\b11)(\d{6})', udi_code)
    if prod_match and not result['production_date']:
        result['production_date'] = prod_match.group(1)
    
    exp_match = re.search(r'(?:\(17\)|\b17)(\d{6})', udi_code)
    if exp_match and not result['expiry_date']:
        result['expiry_date'] = exp_match.group(1)

    is_plain_gtin = bool(re.fullmatch(r'\d{12,14}', api_udi_code))
    is_full_udi = not is_plain_gtin and (
        '(01)' in api_udi_code or
        api_udi_code.startswith('01') or
        api_udi_code.startswith('+') or
        chr(29) in api_udi_code or
        bool(re.search(r'\(\d{2,4}\)', api_udi_code))
    )

    local_lookup = lookup_udi(result['gtin'], use_network=False) if result['gtin'] else None
    _merge_device_info(result, local_lookup)

    if use_network:
        network_lookup = None

        if result['gtin'] and (
            not local_lookup or local_lookup.get('source') == 'GS1_PREFIX'
        ):
            # Se abbiamo gia' il DI/GTIN, e' piu' robusto del raw UDI senza separatori.
            network_lookup = lookup_udi(result['gtin'], use_network=True)
            if network_lookup and network_lookup.get('gtin'):
                _save_lookup_to_cache(network_lookup['gtin'], network_lookup)
        elif is_full_udi and (
            not local_lookup or local_lookup.get('source') == 'GS1_PREFIX'
        ):
            # Fallback per UDI HIBCC/ICCBBA dove il DI non e' stato estratto localmente.
            network_lookup = lookup_gudid_by_udi(api_udi_code)

        if not result['gtin'] and is_full_udi and not network_lookup:
            parsed_udi = parse_gudid_udi(api_udi_code)
            _merge_device_info(result, parsed_udi)

        _merge_device_info(result, network_lookup)
    
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
