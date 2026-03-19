# app/workers/stm_import_worker.py
import json
import logging
import uuid
from datetime import datetime, timezone
from PySide6.QtCore import QObject, Signal
import database

class StmImportWorker(QObject):
    """Esegue l'importazione di un file archivio .stm in background."""
    finished = Signal(int, int, int, int) # verif_imp, verif_skip, dev_new, cust_new
    error = Signal(str)

    def __init__(self, filepath):
        super().__init__()
        self.filepath = filepath

    def run(self):
        logging.info(f"Avvio importazione dall'archivio: {self.filepath}")
        try:
            with open(self.filepath, 'r', encoding='utf-8') as f:
                data = json.load(f)
        except Exception as e:
            self.error.emit(f"Impossibile leggere o parsare il file .stm: {e}")
            return

        verif_imported = 0
        verif_skipped = 0
        devices_created = 0
        customers_created = 0
        
        # Itera su ogni pacchetto di verifica presente nel file
        for verification_package in data.get("verifications", []):
            try:
                # --- 1. Gestione Cliente ---
                customer_data = verification_package['customer']
                customer_id = database.add_or_get_customer(customer_data['name'], customer_data['address'])
                
                # --- 1.1. Gestione Destinazione ---
                # Crea o ottiene una destinazione per il cliente (usa il nome del cliente come nome destinazione)
                destinations = database.get_destinations_for_customer(customer_id)
                if destinations:
                    destination_id = destinations[0]['id']  # Usa la prima destinazione disponibile
                else:
                    # Crea una nuova destinazione con il nome del cliente
                    dest_uuid = str(uuid.uuid4())
                    dest_timestamp = datetime.now(timezone.utc).isoformat()
                    database.add_destination(dest_uuid, customer_id, customer_data['name'], customer_data.get('address', ''), dest_timestamp)
                    # Recupera la destinazione appena creata
                    destinations = database.get_destinations_for_customer(customer_id)
                    destination_id = destinations[0]['id'] if destinations else None
                    if not destination_id:
                        raise Exception(f"Impossibile creare o recuperare una destinazione per il cliente {customer_data['name']}")
                
                # --- 2. Gestione Dispositivo ---
                device_data = verification_package['device']
                device_serial = device_data['serial_number']
                
                existing_device = database.get_device_by_serial(device_serial)
                if existing_device:
                    device_id = existing_device['id']
                else:
                    # Crea il nuovo dispositivo se non esiste
                    device_uuid = str(uuid.uuid4())
                    device_timestamp = datetime.now(timezone.utc).isoformat()
                    applied_parts = json.loads(device_data.get('applied_parts_json', '[]'))
                    department = device_data.get('department', None)
                    verification_interval = device_data.get('verification_interval', None)
                    default_profile_key = device_data.get('default_profile_key', None)
                    default_functional_profile_key = device_data.get('default_functional_profile_key', None)
                    
                    database.add_device(
                        device_uuid,
                        destination_id,
                        device_serial,
                        device_data.get('description', ''),
                        device_data.get('manufacturer', ''),
                        device_data.get('model', ''),
                        department,
                        applied_parts,
                        device_data.get('customer_inventory', ''),
                        device_data.get('ams_inventory', ''),
                        verification_interval,
                        default_profile_key,
                        default_functional_profile_key,
                        device_timestamp
                    )
                    new_device = database.get_device_by_serial(device_serial)
                    device_id = new_device['id']
                    devices_created += 1
                    logging.info(f"Nuovo dispositivo creato: {device_serial}")
                
                # --- 3. Gestione Verifica ---
                verif_details = verification_package['verification_details']
                verif_date = verif_details['verification_date']
                verif_profile = verif_details['profile_name']

                if database.verification_exists(device_id, verif_date, verif_profile):
                    verif_skipped += 1
                    logging.warning(f"Verifica del {verif_date} per S/N {device_serial} già esistente. Saltata.")
                else:
                    # Salva la nuova verifica
                    verif_uuid = str(uuid.uuid4())
                    verif_timestamp = datetime.now(timezone.utc).isoformat()
                    technician_name = verif_details.get('technician_name', 'Importazione STM')
                    technician_username = verif_details.get('technician_username', 'stm_import')
                    verification_code = verif_details.get('verification_code', None)
                    
                    database.save_verification(
                        verif_uuid,
                        device_id,
                        verif_profile,
                        json.loads(verif_details.get('results_json', '{}')),
                        verif_details.get('overall_status', 'PASSATO'),
                        json.loads(verif_details.get('visual_inspection_json', '{}')),
                        verif_details.get('mti_info', {}),
                        technician_name,
                        technician_username,
                        verif_timestamp,
                        verification_date=verif_date,
                        verification_code=verification_code
                    )
                    verif_imported += 1
            
            except Exception as e:
                logging.error(f"Errore durante l'importazione di un record di verifica.", exc_info=True)
                verif_skipped += 1 # Salta il record problematico

        self.finished.emit(verif_imported, verif_skipped, devices_created, customers_created)