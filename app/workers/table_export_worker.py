import pandas as pd
from PySide6.QtCore import QObject, Signal, QEventLoop
from PySide6.QtWidgets import QFileDialog
from app import services
import database
import logging

class TableExportWorker(QObject):
    finished = Signal(str)
    error = Signal(str)

    def __init__(self, destination_id, output_path, start_date=None, end_date=None):
        """
        Inizializza il worker.

        Args:
            destination_id (int): L'ID della destinazione da esportare.
            output_path (str): Il percorso del file di output in formato .xlsx.
            start_date (str, optional): La data di inizio per il filtro ("YYYY-MM-DD").
            end_date (str, optional): La data di fine per il filtro ("YYYY-MM-DD").
        """
        super().__init__()
        self.destination_id = destination_id
        self.output_path = output_path
        self.start_date = start_date
        self.end_date = end_date

    def run(self):
        """
        Esegue il processo di esportazione in un thread separato.
        Recupera i dati, li formatta e li salva in un file Excel.
        """
        try:
            # Controlla se è stato fornito un intervallo di date per scegliere la funzione di servizio corretta
            if self.start_date and self.end_date:
                logging.info(f"Avvio esportazione per ID destinazione: {self.destination_id} dal {self.start_date} al {self.end_date}")
                export_data = services.get_destination_devices_for_export_by_date_range(self.destination_id, self.start_date, self.end_date)
            else:
                # Fallback: esporta tutti i dati se non viene specificato un intervallo
                logging.info(f"Avvio esportazione per ID destinazione: {self.destination_id}")
                export_data = services.get_destination_devices_for_export(self.destination_id)
            
            # Se non ci sono dati, emette un segnale di completamento con un messaggio e termina
            if not export_data:
                self.finished.emit("Nessun dato trovato per i criteri selezionati.")
                return

            df = pd.DataFrame(export_data)
            
            final_columns_order = [
                "DESTINAZIONE", "INVENTARIO AMS", "INVENTARIO CLIENTE", "DENOMINAZIONE", "MARCA", "MODELLO", "MATRICOLA",
                "REPARTO", "TECNICO", "NOTE", "DATA", "ESITO", "ESITO VERIFICHE FUNZIONALI", "STATO"
            ]
            
            for col in final_columns_order:
                if col not in df.columns:
                    df[col] = None
            df = df[final_columns_order]

            # Inizializza il writer di Excel con il motore xlsxwriter
            writer = pd.ExcelWriter(self.output_path, engine='xlsxwriter')
            # Scrivi i dati partendo dalla seconda riga (startrow=1) per lasciare spazio all'intestazione
            df.to_excel(writer, sheet_name='Verifiche', index=False, header=False, startrow=1)
            
            workbook = writer.book
            worksheet = writer.sheets['Verifiche']

            # Definisci un formato per l'intestazione (grassetto, sfondo, testo a capo)
            header_format = workbook.add_format({
                'bold': True,
                'text_wrap': True,
                'valign': 'vcenter',
                'fg_color': '#D7E4BC',
                'border': 1
            })

            # Definisci i formati per la formattazione condizionale CON text_wrap incluso
            green_format = workbook.add_format({
                'bg_color': "#129E0D", 
                'font_color': "#000000", 
                'text_wrap': True, 
                'valign': 'top'
            })
            red_format = workbook.add_format({
                'bg_color': "#FF0000", 
                'font_color': "#000000", 
                'text_wrap': True, 
                'valign': 'top'
            })

            blue_format = workbook.add_format({
                'bg_color': "#62A0D6",
                'font_color': "#000000",
                'text_wrap': True,
                'valign': 'top'
            })

            # Definisci un formato base per le celle di dati con testo a capo
            cell_format = workbook.add_format({
                'text_wrap': True, 
                'valign': 'top'
            })

            num_rows, num_cols = df.shape

            # Applica il formato di base a tutte le colonne PRIMA della formattazione condizionale
            for col in range(num_cols):
                worksheet.set_column(col, col, None, cell_format)

            # Applica la formattazione condizionale (questo sovrascriverà il formato base dove applicabile)
            # Formattazione per la colonna ESITO (L)
            worksheet.conditional_format(f'A2:N{num_rows + 1}', {
                'type': 'formula',
                'criteria': '=SEARCH("CONFORME",$L2)',
                'format': green_format
            })

            worksheet.conditional_format(f'A2:N{num_rows + 1}', {
                'type': 'formula',
                'criteria': '=SEARCH("NON CONFORME",$L2)',
                'format': red_format
            })
            worksheet.conditional_format(f'A2:N{num_rows + 1}', {
                'type': 'formula',
                'criteria': '=SEARCH("VERIFICA NON ESEGUITA",$L2)',
                'format': blue_format
            })
            
            # Formattazione per la colonna ESITO VERIFICHE FUNZIONALI (M)
            worksheet.conditional_format(f'A2:N{num_rows + 1}', {
                'type': 'formula',
                'criteria': '=OR(SEARCH("CONFORME",$M2),SEARCH("PASSATO",$M2))',
                'format': green_format
            })

            worksheet.conditional_format(f'A2:N{num_rows + 1}', {
                'type': 'formula',
                'criteria': '=OR(SEARCH("NON CONFORME",$M2),SEARCH("FALLITO",$M2))',
                'format': red_format
            })
            worksheet.conditional_format(f'A2:N{num_rows + 1}', {
                'type': 'formula',
                'criteria': '=SEARCH("CONFORME CON ANNOTAZIONE",$M2)',
                'format': red_format
            })

            # Crea la tabella
            columns_for_table = [{'header': col} for col in df.columns]
            worksheet.add_table(0, 0, num_rows, num_cols - 1, {
                'columns': columns_for_table,
                'header_row': True,
                'style': 'Table Style Light 15'
            })
            
            # Scrivi l'intestazione manualmente per applicare il formato corretto
            for col_num, value in enumerate(df.columns.values):
                worksheet.write(0, col_num, value, header_format)

            # Imposta la larghezza delle colonne
            worksheet.set_column('A:B', 18)
            worksheet.set_column('C:C', 45)
            worksheet.set_column('D:F', 22)
            worksheet.set_column('G:G', 25)
            worksheet.set_column('H:H', 12)
            worksheet.set_column('I:I', 30)
            worksheet.set_column('J:J', 20)
            worksheet.set_column('K:K', 25)
            worksheet.set_column('L:L', 15)
            worksheet.set_column('M:M', 25)  # Esito Verifiche Funzionali

            # IMPORTANTE: Imposta l'altezza delle righe per permettere il testo a capo
            for row in range(1, num_rows + 2):  # +2 perché includiamo l'header
                worksheet.set_row(row, None, None, {'level': 0})

            writer.close()
            
            logging.info(f"Esportazione formattata completata con successo: {self.output_path}")
            self.finished.emit(f"Tabella esportata con successo in:\n{self.output_path}")

        except Exception as e:
            logging.error("Errore durante l'esportazione della tabella.", exc_info=True)
            self.error.emit(f"Si è verificato un errore imprevisto durante l'esportazione:\n{e}")

class InventoryExportWorker(QObject):
    finished = Signal(str)
    error = Signal(str)
    get_save_path = Signal(str)  # New signal for requesting save path
    save_path_received = Signal(str)  # New signal for receiving save path
    
    def __init__(self, customer_id: int, customer_name: str, parent=None):
        super().__init__(parent)
        self.customer_id = int(customer_id)
        self.customer_name = customer_name
        self.save_path = None
        
    def run(self):
        try:
            logging.info(f"Avvio esportazione inventario per ID cliente: {self.customer_id}")
            
            # Get data
            devices = database.get_devices_for_customer_inventory_export(self.customer_id)
            
            if not devices:
                self.error.emit("Nessun dispositivo trovato per questo cliente")
                return
            
            # Request save path from main thread
            suggested_name = f"Inventario_{self.customer_name}.xlsx"
            self.get_save_path.emit(suggested_name)
            
            # Wait for save path
            loop = QEventLoop()
            self.save_path_received.connect(loop.quit)
            loop.exec()
            
            if not self.save_path:
                self.error.emit("Esportazione annullata")
                return
                
            df = pd.DataFrame(devices, columns=[
                'ams_inventory',
                'customer_inventory',
                'description',
                'manufacturer',
                'model',
                'serial_number',
                'destination',
                'status'
            ])
            
            columns = {
                "ams_inventory": "Inventario AMS",
                "customer_inventory": "Inventario Cliente",
                "description": "Denominazione",
                "manufacturer": "Marca", 
                "model": "Modello",
                "serial_number": "Numero Serie",
                "destination": "Destinazione",
                "status": "Stato"
            }
            
            df = df.rename(columns=columns)
            
            # Inizializza il writer di Excel con il motore xlsxwriter
            filename = f"Inventario_{self.customer_name}.xlsx"
            output_path = f"D:/Desktop/{filename}"
            writer = pd.ExcelWriter(self.save_path, engine='xlsxwriter')
            
            # Scrivi i dati partendo dalla seconda riga (startrow=1) per lasciare spazio all'intestazione
            df.to_excel(writer, sheet_name='Inventario', index=False, header=False, startrow=1)
            
            workbook = writer.book
            worksheet = writer.sheets['Inventario']

            # Definisci un formato per l'intestazione (grassetto, sfondo, testo a capo)
            header_format = workbook.add_format({
                'bold': True,
                'text_wrap': True,
                'valign': 'vcenter',
                'fg_color': '#D7E4BC',
                'border': 1
            })

            # Definisci un formato base per le celle di dati con testo a capo
            cell_format = workbook.add_format({
                'text_wrap': True, 
                'valign': 'top'
            })

            num_rows, num_cols = df.shape

            # Applica il formato di base a tutte le colonne PRIMA della formattazione condizionale
            for col in range(num_cols):
                worksheet.set_column(col, col, None, cell_format)

            # Crea la tabella
            columns_for_table = [{'header': col} for col in df.columns]
            worksheet.add_table(0, 0, num_rows, num_cols - 1, {
                'columns': columns_for_table,
                'header_row': True,
                'style': 'Table Style Light 15'
            })
            
            # Scrivi l'intestazione manualmente per applicare il formato corretto
            for col_num, value in enumerate(df.columns.values):
                worksheet.write(0, col_num, value, header_format)

            # Imposta la larghezza delle colonne
            worksheet.set_column('A:B', 18)  # Inventario AMS, Cliente
            worksheet.set_column('C:C', 45)  # Denominazione
            worksheet.set_column('D:D', 22)  # Marca
            worksheet.set_column('E:E', 22)  # Modello
            worksheet.set_column('F:F', 22)  # Numero Serie
            worksheet.set_column('G:G', 35)  # Destinazione
            worksheet.set_column('H:H', 15)  # Stato

            # IMPORTANTE: Imposta l'altezza delle righe per permettere il testo a capo
            for row in range(1, num_rows + 2):  # +2 perché includiamo l'header
                worksheet.set_row(row, None, None, {'level': 0})

            writer.close()
            
            logging.info(f"Esportazione inventario completata: {output_path}")
            self.finished.emit(output_path)
            
        except Exception as e:
            logging.error(f"Errore durante l'esportazione: {str(e)}")
            self.error.emit(str(e))