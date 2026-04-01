from __future__ import annotations

# app/services.py (Versione completa per la sincronizzazione)
import logging
import json
from datetime import datetime, timezone, date, timedelta
import uuid

import serial

import database
from .data_models import AppliedPart
from .functional_models import FunctionalProfile
from .exceptions import DeletedDeviceFoundException  # Import custom exception
import report_generator
import tempfile
import os
from PySide6.QtCore import QTimer, QSettings, Qt, QLocale
from PySide6.QtPrintSupport import QPrintDialog, QPrinter, QPrintPreviewDialog
from PySide6.QtGui import QPainter, QAction
from app import auth_manager
from app import config



# ==============================================================================
# SERVIZI PER CLIENTI
# ==============================================================================

def add_destination(customer_id, name, address):
    if not name: raise ValueError("Il nome della destinazione non può essere vuoto.")
    timestamp = datetime.now(timezone.utc).isoformat()
    new_uuid = str(uuid.uuid4())
    database.add_destination(new_uuid, customer_id, name, address, timestamp)
    
    # Log audit
    log_action('CREATE', 'destination', entity_description=name,
               details={'address': address, 'customer_id': customer_id})

def delete_destination(dest_id):
    """
    Wrapper di servizio per eliminare una destinazione, solo se non contiene dispositivi.
    """
    # Controlla se ci sono dispositivi associati a questa destinazione
    device_count = database.get_device_count_for_destination(dest_id)
    if device_count > 0:
        # Solleva un errore specifico che l'interfaccia può mostrare all'utente
        raise ValueError(f"Impossibile eliminare: la destinazione contiene {device_count} dispositivi. Spostarli o eliminarli prima.")
    
    # Ottieni info prima di eliminare
    destination = database.get_destination_by_id(dest_id)
    dest_name = dict(destination).get('name', 'Sconosciuta') if destination else 'Sconosciuta'
    
    # Se non ci sono dispositivi, procedi con l'eliminazione
    timestamp = datetime.now(timezone.utc).isoformat()
    database.delete_destination(dest_id, timestamp)
    
    # Log audit
    log_action('DELETE', 'destination', entity_id=dest_id, entity_description=dest_name)

def update_destination(dest_id, name, address):
    """
    Wrapper di servizio per aggiornare i dati di una destinazione.
    """
    if not name:
        raise ValueError("Il nome della destinazione non può essere vuoto.")
    
    timestamp = datetime.now(timezone.utc).isoformat()
    database.update_destination(dest_id, name, address, timestamp)
    
    # Log audit
    log_action('UPDATE', 'destination', entity_id=dest_id, entity_description=name,
               details={'address': address})

def add_customer(name: str, address: str, phone: str, email: str):
    """Crea i dati di sync e aggiunge un cliente."""
    if not name:
        raise ValueError("Il nome del cliente non può essere vuoto.")
    new_uuid = str(uuid.uuid4())
    timestamp = datetime.now(timezone.utc)
    database.add_customer(new_uuid, name, address, phone, email, timestamp)
    
    # Log audit
    log_action('CREATE', 'customer', entity_description=name, 
               details={'address': address, 'phone': phone, 'email': email})

def update_customer(cust_id: int, name: str, address: str, phone: str, email: str):
    """Crea il timestamp e aggiorna un cliente."""
    if not name:
        raise ValueError("Il nome del cliente non può essere vuoto.")
    timestamp = datetime.now(timezone.utc)
    database.update_customer(cust_id, name, address, phone, email, timestamp)
    
    # Log audit
    log_action('UPDATE', 'customer', entity_id=cust_id, entity_description=name,
               details={'address': address, 'phone': phone, 'email': email})

def delete_customer(cust_id: int) -> tuple[bool, str]:
    """Crea il timestamp ed esegue un soft delete."""
    # Ottieni info prima di eliminare
    customer = database.get_customer_by_id(cust_id)
    customer_name = dict(customer).get('name', 'Sconosciuto') if customer else 'Sconosciuto'
    
    timestamp = datetime.now(timezone.utc)
    result = database.soft_delete_customer(cust_id, timestamp)
    
    # Log audit
    log_action('DELETE', 'customer', entity_id=cust_id, entity_description=customer_name)
    
    return result

# --- Wrapper di lettura per coerenza architetturale ---
def get_all_customers(search_query=None):
    with database.DatabaseConnection() as conn:
        if search_query:
            query = """
                SELECT id, name, address, phone, email
                FROM customers 
                WHERE (name LIKE ? OR address LIKE ?)
                AND is_deleted = 0
                ORDER BY name
            """
            search_pattern = f"%{search_query}%"
            return conn.execute(query, (search_pattern, search_pattern)).fetchall()
        else:
            query = """
                SELECT id, name, address, phone, email
                FROM customers
                WHERE is_deleted = 0
                ORDER BY name
            """
            return conn.execute(query).fetchall()

def get_customer_by_id(customer_id):
    return database.get_customer_by_id(customer_id)

def get_device_count_for_customer(customer_id):
    return database.get_device_count_for_customer(customer_id)

def get_all_destinations_with_device_count():
    """Get all destinations with their device counts."""
    with database.DatabaseConnection() as conn:
        query = """
            SELECT 
                d.id,
                d.name,
                d.address,
                d.customer_id,
                c.name as customer_name,
                COUNT(dev.id) as device_count
            FROM destinations d
            LEFT JOIN customers c ON d.customer_id = c.id
            LEFT JOIN devices dev ON dev.destination_id = d.id AND dev.is_deleted = 0
            WHERE d.is_deleted = 0
            GROUP BY d.id, d.name, d.address, d.customer_id, c.name
            ORDER BY c.name, d.name
        """
        return conn.execute(query).fetchall()

def get_destinations_with_device_count_for_customer(customer_id: int, search_query=None):
    """Get destinations and device counts for a specific customer."""
    with database.DatabaseConnection() as conn:
        if search_query:
            query = """
                SELECT 
                    d.id,
                    d.name,
                    d.address,
                    d.customer_id,
                    c.name as customer_name,
                    COUNT(dev.id) as device_count
                FROM destinations d
                LEFT JOIN customers c ON d.customer_id = c.id
                LEFT JOIN devices dev ON dev.destination_id = d.id AND dev.is_deleted = 0
                WHERE d.is_deleted = 0
                AND c.is_deleted = 0
                AND d.customer_id = ?
                AND (d.name LIKE ? OR d.address LIKE ?)
                GROUP BY d.id, d.name, d.address, d.customer_id, c.name
                ORDER BY d.name
            """
            search_pattern = f"%{search_query}%"
            return conn.execute(query, (customer_id, search_pattern, search_pattern)).fetchall()
        else:
            query = """
                SELECT 
                    d.id,
                    d.name,
                    d.address,
                    d.customer_id,
                    c.name as customer_name,
                    COUNT(dev.id) as device_count
                FROM destinations d
                LEFT JOIN customers c ON d.customer_id = c.id
                LEFT JOIN devices dev ON dev.destination_id = d.id AND dev.is_deleted = 0
                WHERE d.is_deleted = 0
                AND c.is_deleted = 0
                AND d.customer_id = ?
                GROUP BY d.id, d.name, d.address, d.customer_id, c.name
                ORDER BY d.name
            """
            return conn.execute(query, (customer_id,)).fetchall()

def get_all_destinations_with_customer(search_query=None):
    """Get all destinations with customer name."""
    with database.DatabaseConnection() as conn:
        if search_query:
            query = """
                SELECT 
                    d.id,
                    d.name,
                    d.address,
                    d.customer_id,
                    c.name as customer_name
                FROM destinations d
                JOIN customers c ON d.customer_id = c.id
                WHERE (d.name LIKE ? OR d.address LIKE ? OR c.name LIKE ?)
                AND d.is_deleted = 0 
                AND c.is_deleted = 0
                ORDER BY c.name, d.name
            """
            search_pattern = f"%{search_query}%"
            return conn.execute(query, (search_pattern, search_pattern, search_pattern)).fetchall()
        else:
            query = """
                SELECT 
                    d.id,
                    d.name,
                    d.address,
                    d.customer_id,
                    c.name as customer_name
                FROM destinations d
                JOIN customers c ON d.customer_id = c.id
                WHERE d.is_deleted = 0 
                AND c.is_deleted = 0
                ORDER BY c.name, d.name
            """
            return conn.execute(query).fetchall()

# ==============================================================================
# SERVIZI PER DISPOSITIVI
# ==============================================================================

def normalize_serial(serial):
    if not serial:
        return None
    s = str(serial).strip().upper()
    return None if s in config.PLACEHOLDER_SERIALS or s == "" else s


def _normalize_audit_value(value):
    """Normalizza un valore per confronto audit (evita falsi positivi)."""
    if isinstance(value, str):
        trimmed = value.strip()
        return trimmed if trimmed != "" else None
    return value


def _build_device_label_from_fields(desc=None, serial=None, manufacturer=None, model=None,
                                    customer_inventory=None, ams_inventory=None):
    """Crea una label compatta e leggibile del dispositivo per il log audit."""
    primary = (desc or "").strip() or "Dispositivo"
    tags = []

    serial = _normalize_audit_value(serial)
    manufacturer = _normalize_audit_value(manufacturer)
    model = _normalize_audit_value(model)
    customer_inventory = _normalize_audit_value(customer_inventory)
    ams_inventory = _normalize_audit_value(ams_inventory)

    if serial:
        tags.append(f"S/N: {serial}")
    if manufacturer or model:
        tags.append(" ".join([p for p in [manufacturer, model] if p]))
    if customer_inventory:
        tags.append(f"Inv. Cliente: {customer_inventory}")
    if ams_inventory:
        tags.append(f"Inv. AMS: {ams_inventory}")

    return f"{primary} ({' | '.join(tags)})" if tags else primary


def _build_device_label(device_info: dict | None):
    if not device_info:
        return "Dispositivo"
    return _build_device_label_from_fields(
        desc=device_info.get('description'),
        serial=device_info.get('serial_number') or device_info.get('serial'),
        manufacturer=device_info.get('manufacturer'),
        model=device_info.get('model'),
        customer_inventory=device_info.get('customer_inventory'),
        ams_inventory=device_info.get('ams_inventory'),
    )


def _build_audit_changes(before_values: dict, after_values: dict, labels: dict[str, str]):
    """Costruisce l'elenco campi modificati con vecchio/nuovo valore."""
    changes = []
    for field, label in labels.items():
        old_value = _normalize_audit_value(before_values.get(field))
        new_value = _normalize_audit_value(after_values.get(field))
        if old_value != new_value:
            changes.append({
                'field': field,
                'label': label,
                'old': old_value,
                'new': new_value,
            })
    return changes

def check_deleted_device_by_serial(serial):
    """
    Verifica se esiste un dispositivo eliminato con questo numero di serie.
    Restituisce le informazioni complete del dispositivo se trovato, altrimenti None.
    """
    serial = normalize_serial(serial)
    if not serial:
        return None
    return database.find_deleted_device_by_serial_with_details(serial)

def add_device(destination_id, serial, desc, mfg, model, department, applied_parts, customer_inv, ams_inv, verification_interval, default_profile_key, default_functional_profile_key, force_create=False):
    """
    Aggiunge un nuovo dispositivo.
    
    Args:
        force_create: Se True, crea un nuovo dispositivo anche se ne esiste uno eliminato
                     con lo stesso serial (sconsigliato, usato solo dopo conferma utente)
    
    Raises:
        ValueError: Se il serial è già in uso da un dispositivo attivo
        
    Note:
        Se viene trovato un dispositivo eliminato con lo stesso serial e force_create=False,
        questa funzione solleva un'eccezione speciale che il chiamante deve gestire
        mostrando il dialog di conferma.
    """
    serial = normalize_serial(serial)
    if serial:
        if database.device_exists(serial):
            raise ValueError(f"Il numero di serie '{serial}' è già utilizzato da un altro dispositivo attivo.")

        if not force_create:
            deleted_device = database.find_deleted_device_by_serial_with_details(serial)
            if deleted_device:
                raise DeletedDeviceFoundException(deleted_device)

    timestamp = datetime.now(timezone.utc).isoformat()
    new_uuid = str(uuid.uuid4())
    new_id = database.add_device(
        new_uuid,
        destination_id,
        serial,
        desc,
        mfg,
        model,
        department,
        applied_parts,
        customer_inv,
        ams_inv,
        verification_interval,
        default_profile_key,
        default_functional_profile_key,
        timestamp,
    )

    destination = database.get_destination_by_id(destination_id)
    destination_name = dict(destination).get('name') if destination else None
    device_label = _build_device_label_from_fields(
        desc=desc,
        serial=serial,
        manufacturer=mfg,
        model=model,
        customer_inventory=customer_inv,
        ams_inventory=ams_inv,
    )

    log_action(
        'CREATE',
        'device',
        entity_id=new_id,
        entity_description=device_label,
        details={
            'device_label': device_label,
            'serial': serial,
            'manufacturer': mfg,
            'model': model,
            'destination_id': destination_id,
            'destination_name': destination_name,
            'customer_inventory': customer_inv,
            'ams_inventory': ams_inv,
            'verification_interval_months': verification_interval,
        },
    )
    return new_id


def update_device(
    dev_id,
    destination_id,
    serial,
    desc,
    mfg,
    model,
    department,
    applied_parts,
    customer_inv,
    ams_inv,
    verification_interval,
    default_profile_key,
    default_functional_profile_key,
    reactivate=False,
    new_destination_id=None,
):
    serial = normalize_serial(serial)
    current_device_row = database.get_device_by_id(dev_id)
    current_device = dict(current_device_row) if current_device_row else {}

    if serial:
        existing = database.find_device_by_serial(serial, include_deleted=False)
        if existing and int(existing.get('id', -1)) != int(dev_id):
            raise ValueError(f"Il numero di serie '{serial}' è già utilizzato da un altro dispositivo attivo.")

    timestamp = datetime.now(timezone.utc).isoformat()
    database.update_device(
        dev_id,
        destination_id,
        serial,
        desc,
        mfg,
        model,
        department,
        applied_parts,
        customer_inv,
        ams_inv,
        verification_interval,
        default_profile_key,
        default_functional_profile_key,
        timestamp,
        reactivate=reactivate,
        new_destination_id=new_destination_id,
    )

    final_destination_id = new_destination_id if new_destination_id is not None else destination_id
    final_destination = database.get_destination_by_id(final_destination_id)
    final_destination_name = dict(final_destination).get('name') if final_destination else None

    before_values = {
        'destination_id': current_device.get('destination_id'),
        'serial': current_device.get('serial_number'),
        'description': current_device.get('description'),
        'manufacturer': current_device.get('manufacturer'),
        'model': current_device.get('model'),
        'department': current_device.get('department'),
        'customer_inventory': current_device.get('customer_inventory'),
        'ams_inventory': current_device.get('ams_inventory'),
        'verification_interval': current_device.get('verification_interval'),
        'default_profile_key': current_device.get('default_profile_key'),
        'default_functional_profile_key': current_device.get('default_functional_profile_key'),
    }
    after_values = {
        'destination_id': final_destination_id,
        'serial': serial,
        'description': desc,
        'manufacturer': mfg,
        'model': model,
        'department': department,
        'customer_inventory': customer_inv,
        'ams_inventory': ams_inv,
        'verification_interval': verification_interval,
        'default_profile_key': default_profile_key,
        'default_functional_profile_key': default_functional_profile_key,
    }
    labels = {
        'destination_id': 'Destinazione (ID)',
        'serial': 'Seriale',
        'description': 'Descrizione',
        'manufacturer': 'Costruttore',
        'model': 'Modello',
        'department': 'Reparto',
        'customer_inventory': 'Inventario cliente',
        'ams_inventory': 'Inventario AMS',
        'verification_interval': 'Intervallo verifica (mesi)',
        'default_profile_key': 'Profilo elettrico di default',
        'default_functional_profile_key': 'Profilo funzionale di default',
    }
    changes = _build_audit_changes(before_values, after_values, labels)

    current_destination_name = None
    if current_device.get('destination_id'):
        current_destination = database.get_destination_by_id(current_device.get('destination_id'))
        current_destination_name = dict(current_destination).get('name') if current_destination else None

    device_label = _build_device_label_from_fields(
        desc=desc,
        serial=serial,
        manufacturer=mfg,
        model=model,
        customer_inventory=customer_inv,
        ams_inventory=ams_inv,
    )

    log_action(
        'REACTIVATE' if reactivate else 'UPDATE',
        'device',
        entity_id=dev_id,
        entity_description=device_label,
        details={
            'device_label': device_label,
            'serial': serial,
            'manufacturer': mfg,
            'model': model,
            'destination_id': final_destination_id,
            'destination_name': final_destination_name,
            'previous_destination_id': current_device.get('destination_id'),
            'previous_destination_name': current_destination_name,
            'reactivated': bool(reactivate),
            'changed_fields_count': len(changes),
            'changes': changes,
        },
    )


def delete_device(dev_id: int):
    device_row = database.get_device_by_id(dev_id)
    device_info = dict(device_row) if device_row else {}

    timestamp = datetime.now(timezone.utc).isoformat()
    database.soft_delete_device(dev_id, timestamp)

    device_label = _build_device_label(device_info)

    log_action(
        'DELETE',
        'device',
        entity_id=dev_id,
        entity_description=device_label,
        details={
            'device_label': device_label,
            'serial': device_info.get('serial_number'),
            'manufacturer': device_info.get('manufacturer'),
            'model': device_info.get('model'),
            'customer_inventory': device_info.get('customer_inventory'),
            'ams_inventory': device_info.get('ams_inventory'),
            'destination_id': device_info.get('destination_id'),
        },
    )


def decommission_device(dev_id: int):
    """Marca un dispositivo come dismesso (decommissioned)."""
    device_row = database.get_device_by_id(dev_id)
    device_info = dict(device_row) if device_row else {}

    timestamp = datetime.now(timezone.utc).isoformat()
    database.set_device_status(dev_id, 'decommissioned', timestamp)

    device_label = _build_device_label(device_info)
    log_action(
        'DECOMMISSION',
        'device',
        entity_id=dev_id,
        entity_description=device_label,
        details={
            'device_label': device_label,
            'serial': device_info.get('serial_number'),
            'manufacturer': device_info.get('manufacturer'),
            'model': device_info.get('model'),
        },
    )


def reactivate_device(dev_id: int):
    """Riattiva un dispositivo precedentemente dismesso."""
    device_row = database.get_device_by_id(dev_id)
    device_info = dict(device_row) if device_row else {}

    timestamp = datetime.now(timezone.utc).isoformat()
    database.set_device_status(dev_id, 'active', timestamp)

    device_label = _build_device_label(device_info)
    log_action(
        'REACTIVATE',
        'device',
        entity_id=dev_id,
        entity_description=device_label,
        details={
            'device_label': device_label,
            'serial': device_info.get('serial_number'),
            'manufacturer': device_info.get('manufacturer'),
            'model': device_info.get('model'),
        },
    )


def move_device_to_destination(device_id: int, new_destination_id: int):
    """Sposta un dispositivo verso una nuova destinazione e registra audit."""
    device_row = database.get_device_by_id(device_id)
    if not device_row:
        raise ValueError("Dispositivo non trovato.")

    device_info = dict(device_row)
    old_destination_id = device_info.get('destination_id')

    try:
        new_destination_id = int(new_destination_id)
    except (TypeError, ValueError):
        raise ValueError("Destinazione non valida.")

    if old_destination_id is not None and int(old_destination_id) == new_destination_id:
        return

    destination_row = database.get_destination_by_id(new_destination_id)
    if not destination_row:
        raise ValueError("Destinazione di arrivo non trovata.")

    timestamp = datetime.now(timezone.utc).isoformat()
    database.move_device_to_destination(device_id, new_destination_id, timestamp)

    old_destination_name = None
    if old_destination_id:
        old_destination = database.get_destination_by_id(old_destination_id)
        old_destination_name = dict(old_destination).get('name') if old_destination else None

    new_destination_name = dict(destination_row).get('name')
    device_label = _build_device_label(device_info)

    log_action(
        'MOVE',
        'device',
        entity_id=device_id,
        entity_description=device_label,
        details={
            'device_label': device_label,
            'serial': device_info.get('serial_number'),
            'previous_destination_id': old_destination_id,
            'previous_destination_name': old_destination_name,
            'destination_id': new_destination_id,
            'destination_name': new_destination_name,
        },
    )


def get_device_by_id(device_id: int):
    return database.get_device_by_id(device_id)


def get_devices_needing_verification(days_in_future=30):
    """Recupera i dispositivi ATTIVI con verifica scaduta o in scadenza."""
    return database.get_devices_needing_verification(days_in_future)


def get_devices_for_destination(destination_id: int, search_query=None):
    return database.get_devices_for_destination(destination_id, search_query)


def get_device_count_for_destination(destination_id: int):
    return database.get_device_count_for_destination(destination_id)


def get_destination_devices_for_export(destination_id: int) -> list[dict]:
    """Restituisce i dispositivi della destinazione per export tabellare (ultima verifica)."""
    rows = database.get_devices_with_last_verification_for_destination(destination_id)
    return [dict(row) for row in rows]


def get_destination_devices_for_export_by_date_range(
    destination_id: int,
    start_date: str,
    end_date: str,
) -> list[dict]:
    """Restituisce i dispositivi della destinazione per export tabellare filtrato per date."""
    rows = database.get_devices_with_verifications_for_destination_by_date_range(
        destination_id,
        start_date,
        end_date,
    )
    return [dict(row) for row in rows]


def finalizza_e_salva_verifica(device_id, profile_name, results,
                               visual_inspection_data, mti_info,
                               technician_name, technician_username,
                               device_info=None) -> tuple[str, int]:
    if isinstance(results, list):
        passed_flags = [bool(r.get('passed')) for r in results if isinstance(r, dict) and 'passed' in r]
        overall_status = 'PASSATO' if all(passed_flags) else 'FALLITO'
    elif isinstance(results, dict) and results.get('overall_status'):
        overall_status = results.get('overall_status')
    else:
        overall_status = 'PASSATO'

    # Regola business: se la verifica elettrica ha note e non è fallita,
    # l'esito deve essere "CONFORME CON ANNOTAZIONE".
    notes_text = ""
    visual_has_ko = False
    if isinstance(visual_inspection_data, dict):
        notes_text = str(visual_inspection_data.get('notes') or '').strip()
        checklist = visual_inspection_data.get('checklist') or []
        if isinstance(checklist, list):
            for item in checklist:
                if not isinstance(item, dict):
                    continue
                result_text = str(item.get('result') or '').strip().upper()
                if result_text in {'KO', 'FALLITO', 'FAIL', 'NON CONFORME'}:
                    visual_has_ko = True
                    break

    # Priorità assoluta: KO in ispezione visiva => NON CONFORME
    if visual_has_ko:
        overall_status = 'FALLITO'

    # "CONFORME CON ANNOTAZIONE" solo per note presenti e nessun KO
    if notes_text and overall_status in {'PASSATO', 'CONFORME'}:
        overall_status = 'CONFORME CON ANNOTAZIONE'

    new_uuid = str(uuid.uuid4())
    timestamp = datetime.now(timezone.utc).isoformat()
    verification_code, new_id = database.save_verification(
        new_uuid,
        device_id,
        profile_name,
        results,
        overall_status,
        visual_inspection_data,
        mti_info,
        technician_name,
        technician_username,
        timestamp,
    )

    device_info = device_info or {}
    device_label = _build_device_label(device_info)
    log_action(
        'VERIFY',
        'verification',
        entity_id=new_id,
        entity_description=f"Verifica elettrica su {device_label}",
        details={
            'device_id': device_id,
            'device_label': device_label,
            'serial': device_info.get('serial_number'),
            'profile': profile_name,
            'status': overall_status,
            'code': verification_code,
            'technician_name': technician_name,
            'technician_username': technician_username,
        },
    )

    return verification_code, new_id


def delete_verification(verification_id: int):
    verification_info = database.get_verification_with_device_info(verification_id)
    verification_data = dict(verification_info) if verification_info else {}

    timestamp = datetime.now(timezone.utc).isoformat()
    deleted = database.soft_delete_verification(verification_id, timestamp)

    if deleted:
        device_label = _build_device_label(verification_data)
        verification_code = verification_data.get('verification_code')
        entity_description = f"Eliminata verifica {verification_code}" if verification_code else "Eliminata verifica"
        if device_label:
            entity_description = f"{entity_description} - {device_label}"

        log_action(
            'DELETE',
            'verification',
            entity_id=verification_id,
            entity_description=entity_description,
            details={
                'verification_code': verification_code,
                'verification_date': verification_data.get('verification_date'),
                'status': verification_data.get('overall_status'),
                'profile': verification_data.get('profile_name'),
                'device_id': verification_data.get('device_id'),
                'device_label': device_label,
                'serial': verification_data.get('serial_number'),
                'technician_name': verification_data.get('technician_name'),
                'technician_username': verification_data.get('technician_username'),
            },
        )

    return deleted


def update_verification(verification_id: int, verification_date: str, overall_status: str,
                        technician_name: str, *,
                        results: list | None = None,
                        visual_inspection_data: dict | None = None,
                        mti_instrument: str | None = None,
                        mti_serial: str | None = None,
                        mti_version: str | None = None,
                        mti_cal_date: str | None = None):
    """Aggiorna tutti i campi di una verifica elettrica con audit log."""
    verification_info = database.get_verification_with_device_info(verification_id)
    verification_data = dict(verification_info) if verification_info else {}

    timestamp = datetime.now(timezone.utc).isoformat()
    updated = database.update_verification(
        verification_id, verification_date, overall_status, technician_name, timestamp,
        results=results,
        visual_inspection_data=visual_inspection_data,
        mti_instrument=mti_instrument,
        mti_serial=mti_serial,
        mti_version=mti_version,
        mti_cal_date=mti_cal_date,
    )

    if updated:
        device_label = _build_device_label(verification_data)
        verification_code = verification_data.get('verification_code')
        entity_description = f"Modificata verifica {verification_code}" if verification_code else "Modificata verifica"
        if device_label:
            entity_description = f"{entity_description} - {device_label}"

        log_action(
            'UPDATE',
            'verification',
            entity_id=verification_id,
            entity_description=entity_description,
            details={
                'verification_code': verification_code,
                'old_date': verification_data.get('verification_date'),
                'new_date': verification_date,
                'old_status': verification_data.get('overall_status'),
                'new_status': overall_status,
                'old_technician': verification_data.get('technician_name'),
                'new_technician': technician_name,
                'device_id': verification_data.get('device_id'),
                'device_label': device_label,
            },
        )

    return updated


def generate_pdf_report(filename, verification_id, device_id, report_settings):
    logging.info(f"Servizio di generazione report per verifica ID {verification_id}")

    device_info_row = database.get_device_by_id(device_id)
    if not device_info_row:
        raise ValueError(f"Dispositivo con ID {device_id} non trovato.")
    device_info = dict(device_info_row)

    destination_id = device_info.get('destination_id')
    if not destination_id:
        raise ValueError(f"Il dispositivo ID {device_id} non è associato a nessuna destinazione.")

    destination_info_row = database.get_destination_by_id(destination_id)
    if not destination_info_row:
        raise ValueError(f"Destinazione ID {destination_id} non trovata.")
    destination_info = dict(destination_info_row)

    customer_id = destination_info.get('customer_id')
    customer_info_row = database.get_customer_by_id(customer_id)
    if not customer_info_row:
        raise ValueError(f"Cliente ID {customer_id} non trovato.")
    customer_info = dict(customer_info_row)

    verifications = database.get_verifications_for_device(device_id)
    verification = next((v for v in verifications if v.get('id') == verification_id), None)
    if not verification:
        raise ValueError(f"Dati di verifica mancanti per la verifica ID {verification_id}")

    technician_name = verification.get('technician_name') or "N/D"
    technician_username = verification.get('technician_username')

    logging.debug("Generazione Report: username tecnico: %s", technician_username)
    signature_data = database.get_signature_by_username(technician_username)

    mti_info = {
        "instrument": verification.get('mti_instrument', ''),
        "serial": verification.get('mti_serial', ''),
        "version": verification.get('mti_version', ''),
        "cal_date": verification.get('mti_cal_date', ''),
    }

    verification_data_for_report = {
        'date': verification.get('verification_date', ''),
        'profile_name': verification.get('profile_name', ''),
        'overall_status': verification.get('overall_status', ''),
        'results': verification.get('results') or [],
        'visual_inspection_data': verification.get('visual_inspection') or {},
        'verification_code': verification.get('verification_code', 'N/A'),
        'functional_results': verification.get('structured_results') or {},
    }

    # Recupera allegati per la verifica (tipo electrical)
    try:
        attachments = database.get_verification_attachments(verification_id, 'electrical')
        if attachments:
            verification_data_for_report['attachments'] = attachments
            logging.info(f"Trovati {len(attachments)} allegati per report VE ID {verification_id}")
    except Exception as e:
        logging.warning(f"Impossibile recuperare allegati per report VE: {e}")

    report_generator.create_report(
        filename,
        device_info,
        customer_info,
        destination_info,
        mti_info,
        report_settings,
        verification_data_for_report,
        technician_name,
        signature_data,
    )


def generate_functional_pdf_report(filename, verification_id, device_id, report_settings):
    logging.info(f"Servizio di generazione report funzionale per verifica ID {verification_id}")

    device_info_row = database.get_device_by_id(device_id)
    if not device_info_row:
        raise ValueError(f"Dispositivo con ID {device_id} non trovato.")
    device_info = dict(device_info_row)

    destination_id = device_info.get('destination_id')
    if not destination_id:
        raise ValueError(f"Il dispositivo ID {device_id} non è associato a nessuna destinazione.")

    destination_info_row = database.get_destination_by_id(destination_id)
    if not destination_info_row:
        raise ValueError(f"Destinazione ID {destination_id} non trovata.")
    destination_info = dict(destination_info_row)

    customer_id = destination_info.get('customer_id')
    customer_info_row = database.get_customer_by_id(customer_id)
    if not customer_info_row:
        raise ValueError(f"Cliente ID {customer_id} non trovato.")
    customer_info = dict(customer_info_row)

    verifications = database.get_functional_verifications_for_device(device_id)
    verification = next((v for v in verifications if v.get('id') == verification_id), None)
    if not verification:
        raise ValueError(f"Dati di verifica funzionale mancanti per la verifica ID {verification_id}")

    technician_name = verification.get('technician_name') or "N/D"
    technician_username = verification.get('technician_username')
    signature_data = database.get_signature_by_username(technician_username)

    used_instruments_json = verification.get('used_instruments_json')
    used_instruments = []
    if used_instruments_json:
        try:
            used_instruments = json.loads(used_instruments_json)
        except (json.JSONDecodeError, TypeError):
            pass

    if not used_instruments:
        mti_info = {
            "instrument": verification.get('mti_instrument', ''),
            "serial": verification.get('mti_serial', ''),
            "version": verification.get('mti_version', ''),
            "cal_date": verification.get('mti_cal_date', ''),
        }
        used_instruments = [mti_info] if mti_info.get('instrument') else []
    else:
        mti_info = used_instruments[0]

    profile_key = verification.get('profile_key', '')
    profile_obj = config.FUNCTIONAL_PROFILES.get(profile_key)
    profile_display_name = profile_obj.name if profile_obj else profile_key

    verification_data_for_report = {
        'date': verification.get('verification_date', ''),
        'profile_name': profile_display_name,
        'overall_status': verification.get('overall_status', ''),
        'results': [],
        'visual_inspection_data': {'notes': verification.get('notes', '')} if verification.get('notes') else {},
        'verification_code': verification.get('verification_code', 'N/A'),
        'functional_results': verification.get('structured_results') or verification.get('results') or {},
        'used_instruments': used_instruments,
    }

    # Recupera allegati per la verifica (tipo functional)
    try:
        attachments = database.get_verification_attachments(verification_id, 'functional')
        if attachments:
            verification_data_for_report['attachments'] = attachments
            logging.info(f"Trovati {len(attachments)} allegati per report VFUN ID {verification_id}")
    except Exception as e:
        logging.warning(f"Impossibile recuperare allegati per report VFUN: {e}")

    report_generator.create_report(
        filename,
        device_info,
        customer_info,
        destination_info,
        mti_info,
        report_settings,
        verification_data_for_report,
        technician_name,
        signature_data,
    )


def _print_pdf_with_qt_preview(pdf_filename, parent_widget=None):
    """
    Mostra una vera anteprima di stampa del PDF e permette la stampa cartacea.
    L'utente può verificare il layout del rapportino prima dell'invio alla stampante.
    """
    if not os.path.exists(pdf_filename):
        raise FileNotFoundError(f"File PDF non trovato: {pdf_filename}")

    try:
        from PySide6.QtPdf import QPdfDocument, QPdfDocumentRenderOptions
        from PySide6.QtWidgets import QMessageBox, QPushButton
    except ImportError as e:
        raise Exception("Il modulo QtPdf non è disponibile. Aggiorna PySide6 per usare l'anteprima di stampa.") from e

    def _render_pdf_on_printer(target_printer: QPrinter):
        pdf_doc = QPdfDocument()
        load_status = pdf_doc.load(pdf_filename)

        # Compatibilità PySide6/Qt: load() può restituire Error (Qt6 moderno)
        # oppure Status (versioni diverse). Gestiamo entrambi i casi.
        load_ok = True
        if hasattr(QPdfDocument, "Error"):
            none_error = getattr(QPdfDocument.Error, "None_", None)
            no_error = getattr(QPdfDocument.Error, "NoError", None)
            valid_results = {r for r in (none_error, no_error) if r is not None}
            if valid_results and load_status not in valid_results:
                load_ok = False
        elif hasattr(QPdfDocument, "Status"):
            ready_status = getattr(QPdfDocument.Status, "Ready", None)
            if ready_status is not None and load_status != ready_status:
                load_ok = False

        if not load_ok:
            raise Exception(f"Impossibile caricare il PDF per l'anteprima (status={load_status}).")

        page_count = pdf_doc.pageCount()
        if page_count <= 0:
            raise Exception("Il PDF non contiene pagine stampabili.")

        render_options = QPdfDocumentRenderOptions()
        painter = QPainter()
        if not painter.begin(target_printer):
            raise Exception("Impossibile inizializzare il motore di stampa.")

        try:
            for page_index in range(page_count):
                if page_index > 0:
                    target_printer.newPage()

                page_rect = target_printer.pageLayout().paintRectPixels(target_printer.resolution())
                image = pdf_doc.render(page_index, page_rect.size(), render_options)
                if image.isNull():
                    raise Exception(f"Rendering non riuscito per la pagina {page_index + 1}.")

                x = page_rect.x() + max(0, (page_rect.width() - image.width()) // 2)
                y = page_rect.y() + max(0, (page_rect.height() - image.height()) // 2)
                painter.drawImage(x, y, image)
        finally:
            painter.end()

    def _translate_preview_ui(dialog: QPrintPreviewDialog):
        """Traduce le etichette principali dell'anteprima in italiano."""
        text_map = {
            "Print": "Stampa",
            "Page setup": "Imposta pagina",
            "Page Setup": "Imposta pagina",
            "Next page": "Pagina successiva",
            "Previous page": "Pagina precedente",
            "First page": "Prima pagina",
            "Last page": "Ultima pagina",
            "Fit width": "Adatta larghezza",
            "Fit page": "Adatta pagina",
            "Zoom in": "Zoom +",
            "Zoom out": "Zoom -",
            "Portrait": "Verticale",
            "Landscape": "Orizzontale",
            "Single page": "Pagina singola",
            "Facing pages": "Pagine affiancate",
            "Overview": "Panoramica",
            "Close": "Chiudi",
        }

        def _translate_text(text: str) -> str:
            if not text:
                return text
            clean = text.replace("&", "").strip()
            for eng, ita in text_map.items():
                if clean.lower() == eng.lower() or clean.lower().startswith(eng.lower()):
                    return ita
            return text

        for action in dialog.findChildren(QAction):
            action.setText(_translate_text(action.text()))
            action.setToolTip(_translate_text(action.toolTip()))
            action.setStatusTip(_translate_text(action.statusTip()))

        for button in dialog.findChildren(QPushButton):
            current_text = button.text()
            new_text = _translate_text(current_text)
            if new_text != current_text:
                button.setText(new_text)

    printer = QPrinter(QPrinter.HighResolution)
    printer.setOutputFormat(QPrinter.NativeFormat)

    preview_dialog = QPrintPreviewDialog(printer, parent_widget)
    preview_dialog.setObjectName("printPreviewDialog")
    preview_dialog.setWindowTitle("Anteprima di Stampa Rapportino")
    try:
        preview_dialog.setLocale(QLocale(QLocale.Italian, QLocale.Italy))
    except AttributeError:
        # Compatibilità Qt6 recente: enum scoped
        preview_dialog.setLocale(QLocale(QLocale.Language.Italian, QLocale.Country.Italy))
    preview_dialog.resize(1200, 800)

    try:
        _translate_preview_ui(preview_dialog)
    except Exception as e:
        logging.warning(f"Traduzione UI anteprima non completa: {e}")

    preview_error = {'error': None}

    def _on_paint_requested(target_printer: QPrinter):
        try:
            _render_pdf_on_printer(target_printer)
        except Exception as e:
            preview_error['error'] = e
            logging.error(f"Errore durante rendering anteprima/stampa PDF: {e}", exc_info=True)

    preview_dialog.paintRequested.connect(_on_paint_requested)
    logging.info("Apertura anteprima di stampa report PDF...")
    def _safe_late_translate():
        try:
            _translate_preview_ui(preview_dialog)
        except Exception as e:
            logging.warning(f"Traduzione UI anteprima (post-init) non completa: {e}")

    QTimer.singleShot(50, _safe_late_translate)
    QTimer.singleShot(0, preview_dialog.showFullScreen)
    result = preview_dialog.exec()

    if preview_error['error'] is not None:
        QMessageBox.critical(
            parent_widget,
            "Errore di Stampa",
            f"Impossibile preparare anteprima/stampa del PDF:\n{preview_error['error']}"
        )
        raise preview_error['error']

    if result != QPrintDialog.Accepted:
        logging.info("Anteprima chiusa o stampa annullata dall'utente.")


def print_pdf_report(verification_id, device_id, report_settings, parent_widget=None):
    """
    Stampa un report PDF usando il sistema di stampa integrato di Qt.
    
    Args:
        verification_id: ID della verifica
        device_id: ID del dispositivo
        report_settings: Impostazioni del report
        parent_widget: Widget padre per il dialog (opzionale)
    """
    temp_fd, temp_filename = tempfile.mkstemp(suffix=".pdf")
    os.close(temp_fd)

    try:
        generate_pdf_report(temp_filename, verification_id, device_id, report_settings)
        _print_pdf_with_qt_preview(temp_filename, parent_widget)
        logging.info(f"Report per verifica ID {verification_id} pronto per la stampa.")
    except Exception as e:
        # Pulisci il file temporaneo in caso di errore
        try:
            if os.path.exists(temp_filename):
                os.unlink(temp_filename)
        except:
            pass
        raise e
    finally:
        # Pulisci il file temporaneo dopo un breve delay per permettere la stampa
        def cleanup():
            try:
                if os.path.exists(temp_filename):
                    os.unlink(temp_filename)
            except:
                pass
        
        timer = QTimer()
        timer.setSingleShot(True)
        timer.timeout.connect(cleanup)
        timer.start(10000)  # Pulisci dopo 10 secondi


def print_functional_pdf_report(verification_id, device_id, report_settings, parent_widget=None):
    """
    Stampa un report PDF funzionale usando il sistema di stampa integrato di Qt.
    
    Args:
        verification_id: ID della verifica funzionale
        device_id: ID del dispositivo
        report_settings: Impostazioni del report
        parent_widget: Widget padre per il dialog (opzionale)
    """
    temp_fd, temp_filename = tempfile.mkstemp(suffix=".pdf")
    os.close(temp_fd)

    try:
        generate_functional_pdf_report(temp_filename, verification_id, device_id, report_settings)
        _print_pdf_with_qt_preview(temp_filename, parent_widget)
        logging.info(f"Report funzionale per verifica ID {verification_id} pronto per la stampa.")
    except Exception as e:
        # Pulisci il file temporaneo in caso di errore
        try:
            if os.path.exists(temp_filename):
                os.unlink(temp_filename)
        except:
            pass
        raise e
    finally:
        # Pulisci il file temporaneo dopo un breve delay per permettere la stampa
        def cleanup():
            try:
                if os.path.exists(temp_filename):
                    os.unlink(temp_filename)
            except:
                pass
        
        timer = QTimer()
        timer.setSingleShot(True)
        timer.timeout.connect(cleanup)
        timer.start(10000)  # Pulisci dopo 10 secondi

def get_data_for_daily_export(target_date: str) -> dict:
    return database.get_full_verification_data_for_date(target_date)

def get_verifications_for_customer_by_month(customer_id: int, year: int, month: int) -> list:
    return database.get_verifications_for_customer_by_month(customer_id, year, month)

def get_verifications_for_device(device_id: int, search_query: str = None):
    return database.get_verifications_for_device(device_id, search_query)

def get_verification_table_structure():
    """Debug: verifica la struttura della tabella verifications."""
    with database.DatabaseConnection() as conn:
        # Get table structure
        result = conn.execute("""
            SELECT sql FROM sqlite_master 
            WHERE type='table' AND name='verifications'
        """).fetchone()
        
        if result:
            logging.info(f"Verifications table structure: {result['sql']}")
        else:
            logging.error("Verifications table does not exist")
        
        # Get column names
        columns = conn.execute("PRAGMA table_info(verifications)").fetchall()
        logging.info(f"Verifications columns: {[col['name'] for col in columns]}")
        
        return columns

def debug_verification_stats():
    """Debug function to check verifications data."""
    try:
        with database.DatabaseConnection() as conn:
            # First check the table structure
            columns = conn.execute("PRAGMA table_info(verifications)").fetchall()
            column_names = [col['name'] for col in columns]
            logging.debug(f"Verifications table columns: {column_names}")
            
            # Check if we have verification_results table instead
            vr_check = conn.execute("""
                SELECT name FROM sqlite_master 
                WHERE type='table' AND name='verification_results'
            """).fetchone()
            
            if vr_check:
                logging.debug("Found verification_results table")
                # Check verification_results structure
                vr_columns = conn.execute("PRAGMA table_info(verification_results)").fetchall()
                vr_column_names = [col['name'] for col in vr_columns]
                logging.debug(f"verification_results columns: {vr_column_names}")
                
            return True
            
    except Exception as e:
        logging.error(f"Debug verification stats error: {e}")
        return None

def get_verification_stats():
    """Get verification statistics."""
    try:
        with database.DatabaseConnection() as conn:
            # Query corretta usando overall_status
            query = """
                SELECT 
                    COUNT(*) as totale,
                    SUM(CASE WHEN overall_status = 'PASSATO' THEN 1 ELSE 0 END) as conformi,
                    SUM(CASE WHEN overall_status = 'FALLITO' THEN 1 ELSE 0 END) as non_conformi
                FROM verifications
                WHERE is_deleted = 0
            """
            
            result = conn.execute(query).fetchone()
            
            if not result:
                return {'totale': 0, 'conformi': 0, 'non_conformi': 0}
            
            stats = {
                'totale': int(result['totale'] or 0),
                'conformi': int(result['conformi'] or 0),
                'non_conformi': int(result['non_conformi'] or 0)
            }
            
            logging.info(f"Verification stats: {stats}")
            
            # Debug: mostra distribuzione status
            status_dist = conn.execute("""
                SELECT overall_status, COUNT(*) as count
                FROM verifications
                WHERE is_deleted = 0
                GROUP BY overall_status
            """).fetchall()
            logging.debug(f"Status distribution: {[dict(s) for s in status_dist]}")
            
            return stats
            
    except Exception as e:
        logging.error(f"Error getting verification stats: {e}", exc_info=True)
        return {'totale': 0, 'conformi': 0, 'non_conformi': 0}

# ==============================================================================
# SERVIZI PER IMPORT / EXPORT
# ==============================================================================

def process_device_import_row(row_data: dict, mapping: dict, destination_id: int):
    serial_number = row_data.get(mapping.get('matricola'))
    
    description = row_data.get(mapping.get('descrizione'))
    if not description:
        raise ValueError("Descrizione mancante.")
    profile_key = (row_data.get(mapping.get('profilo')) or "IEC 62353 Metodo Diretto - Classe 1") if mapping.get('profilo') else None
    # Durante l'import da Excel il profilo funzionale di default non è presente: lo lasciamo vuoto
    default_functional_profile_key = None

    add_device(
        destination_id=destination_id,
        serial=serial_number,
        desc=description,
        mfg=row_data.get(mapping.get('costruttore'), ''),
        model=row_data.get(mapping.get('modello'), ''),
        department=row_data.get(mapping.get('reparto'), ''),
        customer_inv=row_data.get(mapping.get('inv_cliente'), ''),
        ams_inv=row_data.get(mapping.get('inv_ams'), ''),
        verification_interval=row_data.get(mapping.get('verification_interval'), None),
        applied_parts=[],
        default_profile_key=profile_key,
        default_functional_profile_key=default_functional_profile_key,
    )

# --- NUOVA FUNZIONE PER LA RICERCA GLOBALE ---
def search_globally(search_term: str) -> list:
    """
    Esegue una ricerca globale su clienti, destinazioni e dispositivi.
    Restituisce una lista combinata di risultati.
    """
    if not search_term or len(search_term) < 3:
        return []
    
    customers = database.get_all_customers(search_term)
    destinations = database.search_destinations_globally(search_term)
    devices = database.search_device_globally(search_term)
    
    # Converti i risultati in dizionari e combinali
    results = [dict(c) for c in customers] + [dict(d) for d in destinations] + [dict(dev) for dev in devices]
    return results


def search_device_globally(search_term: str) -> list:
    """Ricerca dispositivi per descrizione/modello/SN con minimo 3 caratteri."""
    if not search_term or len(search_term.strip()) < 3:
        return []
    rows = database.search_device_globally(search_term.strip())
    return [dict(r) for r in rows]


def get_duplicate_devices_by_serial() -> list:
    """Restituisce dispositivi duplicati per seriale/inventari."""
    rows = database.get_duplicate_devices_by_serial()
    return [dict(r) for r in rows]


def get_duplicate_devices_by_characteristics() -> list:
    """Restituisce dispositivi potenzialmente duplicati per caratteristiche."""
    rows = database.get_duplicate_devices_by_characteristics()
    return [dict(r) for r in rows]


def get_device_data_quality_issues() -> list:
    """Restituisce eventuali anomalie qualità dati dei dispositivi."""
    rows = database.get_device_data_quality_issues()
    return [dict(r) for r in rows]
# --- FINE NUOVA FUNZIONE ---


# ==============================================================================
# SERVIZI PER STRUMENTI E IMPOSTAZIONI
# ==============================================================================

def get_all_instruments(instrument_type: str = None):
    """
    Recupera tutti gli strumenti, opzionalmente filtrati per tipo.
    
    Args:
        instrument_type: 'electrical' per strumenti elettrici, 'functional' per strumenti funzionali, None per tutti
    """
    return database.get_all_instruments(instrument_type)

def add_instrument(instrument_name: str, serial_number: str, 
                   fw_version: str, calibration_date: str, instrument_type: str = 'electrical'):
    """Add a new instrument to the database."""
    new_uuid = str(uuid.uuid4())
    timestamp = datetime.now(timezone.utc).isoformat()
    database.add_instrument(
        new_uuid, 
        instrument_name, 
        serial_number, 
        fw_version, 
        calibration_date, 
        timestamp=timestamp,
        instrument_type=instrument_type
    )
    
    # Log audit
    log_action('CREATE', 'instrument', entity_description=f"{instrument_name} (S/N: {serial_number})",
               details={'fw_version': fw_version, 'calibration_date': calibration_date, 'instrument_type': instrument_type})

def update_instrument(inst_id: int, instrument_name: str, serial_number: str, 
                     fw_version: str, calibration_date: str, instrument_type: str = None):
    """Update an instrument in the database."""
    timestamp = datetime.now(timezone.utc).isoformat()
    database.update_instrument(
        inst_id, 
        instrument_name, 
        serial_number, 
        fw_version, 
        calibration_date, 
        timestamp,
        instrument_type=instrument_type
    )
    
    # Log audit
    log_action('UPDATE', 'instrument', entity_id=inst_id, 
               entity_description=f"{instrument_name} (S/N: {serial_number})",
               details={'fw_version': fw_version, 'calibration_date': calibration_date, 'instrument_type': instrument_type})

def delete_instrument(inst_id: int):
    # Ottieni info prima di eliminare
    instruments = database.get_all_instruments()
    instrument = next((i for i in instruments if i['id'] == inst_id), None)
    inst_desc = f"{instrument['instrument_name']} (S/N: {instrument['serial_number']})" if instrument else 'Sconosciuto'
    
    timestamp = datetime.now(timezone.utc)
    database.soft_delete_instrument(inst_id, timestamp)
    
    # Log audit
    log_action('DELETE', 'instrument', entity_id=inst_id, entity_description=inst_desc)

def set_default_instrument(inst_id: int):
    timestamp = datetime.now(timezone.utc)
    database.set_default_instrument(inst_id, timestamp)

def get_stats():
    return database.get_stats()

def resolve_conflict_keep_local(conflict: dict):
    """
    Risolve un conflitto mantenendo la versione locale.

    Per la maggior parte delle tabelle questo significa solo
    aggiornare il timestamp locale per forzare un nuovo PUSH.

    Per i conflitti sul numero di serie dei dispositivi ('serial_conflict')
    implementiamo invece una logica speciale:
    - facciamo in modo che il dispositivo locale erediti l'UUID del server
      (così non ci sono più due dispositivi diversi con lo stesso seriale)
    - manteniamo tutti i dati locali
    - marchiamo il record come non sincronizzato, così al prossimo sync
      il server riceve un UPDATE sull'UUID esistente e quindi tutti gli
      altri client vedranno il dispositivo con i dati locali.
    """
    table_name = conflict.get("table")
    reason = conflict.get("reason")
    timestamp = datetime.now(timezone.utc)

    # Gestione speciale per conflitto di seriale sui dispositivi
    if table_name == "devices" and reason == "serial_conflict":
        logging.warning("Risoluzione conflitto devices.serial_conflict: mantenere versione LOCALE e farla vincere sul server.")
        database.resolve_device_serial_conflict_keep_local(conflict, timestamp)
        return

    # Fallback generico: forza solo l'aggiornamento del timestamp locale
    uuid = conflict.get("uuid") or conflict.get("client_version", {}).get("uuid")
    logging.warning(f"Risoluzione conflitto generico per {table_name} UUID {uuid}: forzatura versione locale.")
    if uuid:
        database.force_update_timestamp(table_name, uuid, timestamp)

def resolve_conflict_use_server(table_name: str, server_version: dict):
    uuid = server_version.get('uuid')
    logging.warning(f"Risoluzione conflitto per {table_name} UUID {uuid}: accettazione versione server.")
    # Passa is_conflict_resolution=True per saltare il controllo dei duplicati di serial_number
    database.overwrite_local_record(table_name, server_version, is_conflict_resolution=True)

def force_full_push():
    import database
    with database.DatabaseConnection() as conn:
        return database.mark_everything_for_full_push(conn)
    
# ==============================================================================
# SERVIZI PER PROFILI DI VERIFICA
# ==============================================================================

def add_profile_with_tests(profile_key, profile_name, tests_list, norma=""):
    """Wrapper di servizio per aggiungere un nuovo profilo."""
    timestamp = datetime.now(timezone.utc).isoformat()
    return database.add_profile_with_tests(profile_key, profile_name, tests_list, timestamp, norma=norma)

def update_profile_with_tests(profile_id, profile_name, tests_list, norma=""):
    """Wrapper di servizio per aggiornare un profilo."""
    timestamp = datetime.now(timezone.utc).isoformat()
    database.update_profile_with_tests(profile_id, profile_name, tests_list, timestamp, norma=norma)

def delete_profile(profile_id):
    """Wrapper di servizio per eliminare un profilo."""
    timestamp = datetime.now(timezone.utc).isoformat()
    database.delete_profile(profile_id, timestamp)
    

# ======================================================================
# PROFILI FUNZIONALI
# ======================================================================

def add_functional_profile(profile_key: str, profile: FunctionalProfile):
    timestamp = datetime.now(timezone.utc).isoformat()
    new_id = database.add_functional_profile(profile_key, profile, timestamp)
    log_action(
        'CREATE',
        'functional_profile',
        entity_id=new_id,
        entity_description=profile.name,
        details={'device_type': profile.device_type},
    )
    return new_id


def update_functional_profile(profile_id: int, profile: FunctionalProfile):
    timestamp = datetime.now(timezone.utc).isoformat()
    # Assicurati che il profile_key sia sempre aggiornato nel database
    # anche se tecnicamente non dovrebbe cambiare per profili esistenti
    database.update_functional_profile(profile_id, profile, timestamp)
    # Ricarica i profili per assicurarsi che siano aggiornati
    config.load_functional_profiles()
    log_action(
        'UPDATE',
        'functional_profile',
        entity_id=profile_id,
        entity_description=profile.name,
        details={'device_type': profile.device_type},
    )


def delete_functional_profile(profile_id: int):
    timestamp = datetime.now(timezone.utc).isoformat()
    database.delete_functional_profile(profile_id, timestamp)
    log_action('DELETE', 'functional_profile', entity_id=profile_id)


# ======================================================================
# VERIFICHE FUNZIONALI
# ======================================================================

def finalizza_e_salva_verifica_funzionale(
    device_id: int,
    profile_key: str,
    results: dict,
    structured_results: dict,
    overall_status: str,
    notes: str,
    mti_info: dict,
    technician_name: str,
    technician_username: str,
    device_info: dict,
    used_instruments: list | None = None,
) -> tuple[str, int]:
    new_uuid = str(uuid.uuid4())
    timestamp = datetime.now(timezone.utc).isoformat()
    verification_code, new_id = database.save_functional_verification(
        uuid=new_uuid,
        device_id=device_id,
        profile_key=profile_key,
        results=results,
        structured_results=structured_results,
        overall_status=overall_status,
        notes=notes,
        mti_info=mti_info or {},
        technician_name=technician_name,
        technician_username=technician_username,
        timestamp=timestamp,
        used_instruments=used_instruments,
    )

    device_info = device_info or {}
    device_label = _build_device_label(device_info)
    log_action(
        'VERIFY',
        'functional_verification',
        entity_id=new_id,
        entity_description=f"Verifica funzionale su {device_label}",
        details={
            'device_id': device_id,
            'device_label': device_label,
            'serial': device_info.get('serial_number'),
            'profile': profile_key,
            'status': overall_status,
            'code': verification_code,
            'technician_name': technician_name,
            'technician_username': technician_username,
        },
    )
    return verification_code, new_id


def get_functional_verifications_for_device(device_id: int) -> list[dict]:
    return database.get_functional_verifications_for_device(device_id)


def delete_functional_verification(verification_id: int):
    verification_info = database.get_functional_verification_with_device_info(verification_id)
    verification_data = dict(verification_info) if verification_info else {}

    timestamp = datetime.now(timezone.utc).isoformat()
    database.delete_functional_verification(verification_id, timestamp)

    device_label = _build_device_label(verification_data)
    verification_code = verification_data.get('verification_code')
    entity_description = (
        f"Eliminata verifica funzionale {verification_code}"
        if verification_code else
        "Eliminata verifica funzionale"
    )
    if device_label:
        entity_description = f"{entity_description} - {device_label}"

    log_action(
        'DELETE',
        'functional_verification',
        entity_id=verification_id,
        entity_description=entity_description,
        details={
            'verification_code': verification_code,
            'verification_date': verification_data.get('verification_date'),
            'status': verification_data.get('overall_status'),
            'profile': verification_data.get('profile_key'),
            'device_id': verification_data.get('device_id'),
            'device_label': device_label,
            'serial': verification_data.get('serial_number'),
            'technician_name': verification_data.get('technician_name'),
            'technician_username': verification_data.get('technician_username'),
        },
    )


def update_functional_verification(verification_id: int, verification_date: str, overall_status: str,
                                    technician_name: str, notes: str, *,
                                    results: dict | None = None,
                                    structured_results: dict | None = None,
                                    mti_instrument: str | None = None,
                                    mti_serial: str | None = None,
                                    mti_version: str | None = None,
                                    mti_cal_date: str | None = None):
    """Aggiorna tutti i campi di una verifica funzionale con audit log."""
    verification_info = database.get_functional_verification_with_device_info(verification_id)
    verification_data = dict(verification_info) if verification_info else {}

    timestamp = datetime.now(timezone.utc).isoformat()
    updated = database.update_functional_verification(
        verification_id, verification_date, overall_status, technician_name, notes, timestamp,
        results=results,
        structured_results=structured_results,
        mti_instrument=mti_instrument,
        mti_serial=mti_serial,
        mti_version=mti_version,
        mti_cal_date=mti_cal_date,
    )

    if updated:
        device_label = _build_device_label(verification_data)
        verification_code = verification_data.get('verification_code')
        entity_description = (
            f"Modificata verifica funzionale {verification_code}"
            if verification_code else
            "Modificata verifica funzionale"
        )
        if device_label:
            entity_description = f"{entity_description} - {device_label}"

        log_action(
            'UPDATE',
            'functional_verification',
            entity_id=verification_id,
            entity_description=entity_description,
            details={
                'verification_code': verification_code,
                'old_date': verification_data.get('verification_date'),
                'new_date': verification_date,
                'old_status': verification_data.get('overall_status'),
                'new_status': overall_status,
                'old_technician': verification_data.get('technician_name'),
                'new_technician': technician_name,
                'device_id': verification_data.get('device_id'),
                'device_label': device_label,
            },
        )

    return updated


def get_unique_manufacturers():
    """Recupera tutti i costruttori unici dal database."""
    with database.DatabaseConnection() as conn:
        query = """
            SELECT DISTINCT manufacturer 
            FROM devices 
            WHERE manufacturer IS NOT NULL AND TRIM(manufacturer) != ''
            AND is_deleted = 0
            ORDER BY manufacturer
        """
        rows = conn.execute(query).fetchall()
        return [dict(row) for row in rows]

def get_unique_models():
    """Recupera tutti i modelli unici dal database."""
    with database.DatabaseConnection() as conn:
        query = """
            SELECT DISTINCT model 
            FROM devices 
            WHERE model IS NOT NULL AND TRIM(model) != ''
            AND is_deleted = 0
            ORDER BY model
        """
        rows = conn.execute(query).fetchall()
        return [dict(row) for row in rows]


def get_all_unique_device_descriptions() -> list[str]:
    """Recupera tutte le descrizioni uniche dei dispositivi attivi."""
    return database.get_all_unique_device_descriptions()


def get_devices_by_description(description: str):
    """Recupera i dispositivi attivi che corrispondono alla descrizione indicata."""
    return database.get_devices_by_description(description)


def correct_device_description(old_description: str, new_description: str) -> int:
    """Corregge in blocco la descrizione dispositivi e restituisce il numero di righe aggiornate."""
    timestamp = datetime.now(timezone.utc).isoformat()
    return database.bulk_update_device_description(old_description, new_description, timestamp)


def advanced_search(criteria: dict):
    """Wrapper di servizio per la ricerca avanzata."""
    rows = database.advanced_search(criteria)
    return [dict(row) for row in rows]

def get_suggested_profiles_for_device(manufacturer: str | None, model: str | None, description: str | None):
    """
    Wrapper di servizio per suggerire profili di verifica in base ai
    dispositivi esistenti (stesso costruttore/modello o stessa descrizione).
    """
    return database.get_suggested_profiles_for_device(manufacturer, model, description)

def get_verification_stats_by_month(year: int):
    """Recupera le statistiche delle verifiche per mese."""
    return database.get_verification_stats_by_month(year)

def get_top_customers_by_verifications(limit=10):
    """Recupera i top clienti per numero di verifiche."""
    return database.get_top_customers_by_verifications(limit)

def get_top_technicians_by_verifications(limit=10):
    """Recupera i top tecnici per numero di verifiche."""
    return database.get_top_technicians_by_verifications(limit)

def get_functional_verification_stats():
    """Recupera statistiche sulle verifiche funzionali."""
    return database.get_functional_verification_stats()

def get_functional_verification_stats_by_month(year: int):
    """Recupera statistiche verifiche funzionali per mese."""
    return database.get_functional_verification_stats_by_month(year)

def get_device_type_distribution():
    """Distribuzione dispositivi per tipologia."""
    return database.get_device_type_distribution()

def get_recent_verifications(limit=20):
    """Recupera le verifiche più recenti."""
    return database.get_recent_verifications(limit)

def get_verifications_per_day_last_n_days(days=30):
    """Verifiche per giorno negli ultimi N giorni."""
    return database.get_verifications_per_day_last_n_days(days)

def get_dashboard_summary_stats():
    """Statistiche riassuntive complete per la dashboard."""
    return database.get_dashboard_summary_stats()

def get_top_device_types_by_verifications(limit=10):
    """Tipologie di dispositivi con più verifiche."""
    return database.get_top_device_types_by_verifications(limit)

def get_monthly_productivity(year: int):
    """Produttività mensile."""
    return database.get_monthly_productivity(year)

def get_instruments_needing_calibration(days_in_future=30):
    """Recupera strumenti con calibrazione in scadenza."""
    return database.get_instruments_needing_calibration(days_in_future)

# ==============================================================================
# AUDIT LOG SERVICES
# ==============================================================================

def log_action(action_type, entity_type, entity_id=None, entity_description=None, details=None):
    """
    Registra un'azione nel log di audit.
    
    Wrapper che aggiunge automaticamente le info dell'utente corrente.
    """
    try:
        user_info = auth_manager.get_current_user_info()
        username = user_info.get('username', 'system')
        user_full_name = user_info.get('full_name', 'Sistema')
        
        database.log_audit(
            username=username,
            user_full_name=user_full_name,
            action_type=action_type,
            entity_type=entity_type,
            entity_id=entity_id,
            entity_description=entity_description,
            details=details
        )
    except Exception as e:
        logging.error(f"Errore log azione: {e}")

def get_audit_log(filters=None, limit=100, offset=0):
    """Recupera il log delle attività."""
    return database.get_audit_log(filters, limit, offset)

def get_audit_log_stats():
    """Recupera statistiche sul log di audit."""
    return database.get_audit_log_stats()

def prepare_profiles_for_sync():
    """Prepara i profili per la sincronizzazione."""
    with database.DatabaseConnection() as conn:
        query = """
            SELECT 
                id,
                name,
                description,
                settings,
                uuid,
                is_deleted,
                last_modified,
                is_synced
            FROM profiles
            WHERE is_synced = 0 OR is_deleted = 1
        """
        profiles = conn.execute(query).fetchall()
        return [dict(p) for p in profiles]

def update_profile_sync_status(profile_uuid: str):
    """Aggiorna lo stato di sincronizzazione di un profilo."""
    with database.DatabaseConnection() as conn:
        query = """
            UPDATE profiles 
            SET is_synced = 1, last_modified = CURRENT_TIMESTAMP
            WHERE uuid = ?
        """
        conn.execute(query, (profile_uuid,))
        conn.commit()