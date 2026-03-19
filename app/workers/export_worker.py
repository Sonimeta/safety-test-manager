import json
from PySide6.QtCore import QObject, Signal
# MODIFICA: Importa 'services', non 'database'
from app import services
import logging

class DailyExportWorker(QObject):
    """Esegue l'esportazione delle verifiche di una data specifica in formato JSON (.stm)."""
    finished = Signal(str, str)
    error = Signal(str)

    def __init__(self, target_date, output_path):
        super().__init__()
        self.target_date = target_date
        self.output_path = output_path

    def run(self):
        try:
            logging.info(f"Avvio esportazione in formato STM per la data: {self.target_date}")
            
            # MODIFICA: Chiama la funzione di servizio, che a sua volta chiama il database
            export_data = services.get_data_for_daily_export(self.target_date)
            
            if not export_data["verifications"]:
                logging.warning(f"Nessuna verifica trovata per la data {self.target_date}.")
                self.finished.emit("Warning", "Nessuna verifica trovata per la data selezionata.")
                return

            with open(self.output_path, 'w', encoding='utf-8') as f:
                json.dump(export_data, f, indent=4)
            
            num_verifiche = len(export_data['verifications'])
            logging.info(f"Esportazione completata con successo. Salvate {num_verifiche} verifiche.")
            self.finished.emit("Success", f"Esportazione completata.\n\nSalvate {num_verifiche} verifiche nel file:\n{self.output_path}")

        except Exception as e:
            logging.error("Errore durante l'esportazione delle verifiche.", exc_info=True)
            self.error.emit(f"Si è verificato un errore imprevisto durante l'esportazione:\n{e}")