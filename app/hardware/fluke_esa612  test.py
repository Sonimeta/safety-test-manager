from click import command
import serial
import serial.tools.list_ports
import time
import logging
import re

class FlukeESA612Error(Exception):
    """Eccezione personalizzata per errori specifici dello strumento Fluke ESA612."""
    pass

# Dizionario per tradurre i codici di errore dello strumento in messaggi chiari
FLUKE_ERROR_CODES = {
    "!56": "Tensione di rete assente (Mains not present). Assicurarsi che il dispositivo da testare sia acceso e collegato.",
    "!21": "Cavo di terra o presa apparecchio non collegato allo strumento.",
    "!50": "GFI (Ground Fault Interrupt) scattato.",
    "!51": "Rilevata sovratensione (Over Voltage).",
    "!53": "Tensione di rete fuori dai limiti (Mains out of range).",
    "!54": "Messa a terra aperta (Open Ground).",
    "!55": "Tensione di rete con polarità inversa (Reverse Voltage).",
    "!32": "Corrente non rilevata (No Current).",
    "!37": "Lettura non disponibile (Reading not available)."
}

class FlukeESA612:
    """
    Classe per controllare in remoto un analizzatore di sicurezza elettrica Fluke ESA612/615.

    Gestisce la connessione seriale, l'invio di comandi, la lettura delle risposte
    e una gestione robusta degli errori e dei timeout.
    """
    def __init__(self, port: str):
        """
        Inizializza la classe ma non apre la connessione.

        Args:
            port (str): La porta COM a cui è collegato lo strumento (es. "COM3").
        
        Raises:
            ValueError: Se la porta COM non è specificata.
        """
        if not port or port == "Nessuna":
            raise ValueError("È richiesta una porta COM valida per comunicare con lo strumento.")
        self.port = port
        self.ser = None
        self.connection_params = {
            'baudrate': 115200,
            'bytesize': serial.EIGHTBITS,
            'parity': serial.PARITY_NONE,
            'stopbits': serial.STOPBITS_ONE,
            'timeout': 5,  # Timeout leggermente aumentato per maggiore tolleranza
            'rtscts': True # Abilita il controllo di flusso hardware come da manuale
        }

    def __enter__(self):
        """Permette l'uso della classe con un blocco 'with', gestendo connessione e disconnessione."""
        self.connect()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Assicura che la disconnessione avvenga sempre all'uscita dal blocco 'with'."""
        self.disconnect()

    def connect(self):
        """
        Stabilisce la connessione seriale con lo strumento e lo imposta in modalità remota.
        Pulisce i buffer e gestisce gli errori di connessione.
        """
        if self.ser and self.ser.is_open:
            logging.warning("La connessione è già aperta.")
            return
        try:
            logging.info(f"Tentativo di connessione con lo strumento sulla porta {self.port}...")
            self.ser = serial.Serial(self.port, **self.connection_params)
            
            # Pulisce i buffer per iniziare da uno stato pulito
            self.ser.reset_input_buffer()
            self.ser.reset_output_buffer()
            time.sleep(0.1)

            # Invia ESC (0x1b) come suggerito dal manuale per resettare lo stato
            # dello strumento e uscire da eventuali modalità di lettura continua (es. MREAD).
            self.ser.write(b'\x1b')
            time.sleep(0.2)  # Pausa per permettere allo strumento di processare l'ESC

            # Legge e scarta qualsiasi dato residuo nel buffer di input
            if self.ser.in_waiting > 0:
                residual_bytes = self.ser.read(self.ser.in_waiting)
                logging.debug(f"Puliti {len(residual_bytes)} byte residui dopo l'invio di ESC.")
            
            self.ser.reset_input_buffer()
            
            # Imposta lo strumento in modalità remota e verifica la risposta
            self._send_and_check("REMOTE")
            time.sleep(0.1)
            logging.info("Connessione riuscita. Strumento in modalità remota.")

        except serial.SerialException as e:
            raise ConnectionError(f"Impossibile aprire la porta {self.port}. Verificare che sia corretta, non sia in uso e che lo strumento sia acceso e collegato.")
        except Exception as e:
            self.disconnect() # Assicura la chiusura in caso di altri errori
            raise e

    def disconnect(self):
        """
        Riporta lo strumento in modalità locale e chiude la connessione seriale in modo sicuro.
        """
        if self.ser and self.ser.is_open:
            try:
                logging.info("Ripristino dello strumento in modalità locale...")
                if self.ser.in_waiting > 0:
                    self.ser.read(self.ser.in_waiting)
                # Comando per terminare la modalità remota
                self.ser.write(b'LOCAL\r\n')
                logging.debug("-> CMD: LOCAL")
                # Pausa per dare tempo allo strumento di processare il comando prima di chiudere la porta
                time.sleep(0.5)
            except Exception as e:
                logging.warning(f"Errore non critico durante l'invio del comando LOCAL: {e}")
            finally:
                self.ser.close()
                logging.info(f"Disconnesso da {self.port}.")
        self.ser = None

    def send_command(self, command: str) -> str:
        """
        Invia un comando e attende una singola riga di risposta.

        Args:
            command (str): Il comando da inviare, senza terminatori.

        Returns:
            str: La risposta ricevuta dallo strumento, pulita da spazi e terminatori.

        Raises:
            ConnectionError: Se la porta seriale non è aperta.
            TimeoutError: Se non viene ricevuta una risposta entro il timeout.
        """
        if not self.ser or not self.ser.is_open:
            raise ConnectionError("La porta seriale non è aperta. Eseguire prima connect().")
        
        # I comandi devono terminare con CR+LF, come da manuale
        full_command = f"{command}\r\n".encode('ascii')
        self.ser.write(full_command)
        logging.debug(f"-> CMD: {command}")
        
        # readline() attende fino al timeout definito in connection_params
        line = self.ser.readline()
        if not line:
            raise TimeoutError(f"Timeout in attesa di risposta al comando '{command}'")
        
        resp = line.decode('ascii', errors='ignore').strip()
        logging.debug(f"<- RESP: {resp}")
        return resp

    def _send_and_check(self, command: str, expected: str = "*", retries: int = 2):
        """
        Invia un comando e verifica che la risposta sia quella attesa.
        Implementa una logica di tentativi in caso di fallimento.

        Args:
            command (str): Comando da inviare.
            expected (str): Risposta attesa (di default "*").
            retries (int): Numero di tentativi da effettuare.

        Raises:
            IOError: Se il comando fallisce dopo tutti i tentativi.
        """
        last_err = None
        for attempt in range(retries + 1):
            try:
                response = self.send_command(command)
                if expected in response:
                    return # Successo
                
                # Se la risposta non è quella attesa, la tratta come un errore
                error_message = FLUKE_ERROR_CODES.get(response, f"Risposta inattesa: '{response}'")
                raise FlukeESA612Error(f"Comando '{command}' fallito. {error_message}")

            except Exception as e:
                last_err = e
                if attempt < retries:
                    logging.warning(f"Tentativo {attempt + 1} per '{command}' fallito. Riprovo...")
                    time.sleep(0.2) # Breve pausa prima del nuovo tentativo
        raise last_err

    def get_first_reading(self) -> str:
        """
        Esegue il comando MREAD, che restituisce dati in continuo, e cattura la prima
        lettura valida o un codice di errore. Gestisce l'uscita dalla modalità MREAD.

        Returns:
            str: La prima lettura valida o il codice di errore.

        Raises:
            FlukeESA612Error: Se viene ricevuto un codice di errore noto.
            TimeoutError: Se non viene ricevuta una lettura valida entro 5 secondi.
        """
        self._send_and_check("MREAD")
        reading = None
        deadline = time.time() + 5 # Timeout esplicito di 5 secondi
        
        try:
            while time.time() < deadline:
                line = self.ser.readline().decode('ascii', errors='ignore').strip()
                if not line:
                    continue

                if line in FLUKE_ERROR_CODES:
                    logging.error(f"Strumento ha riportato un errore: {line} -> {FLUKE_ERROR_CODES[line]}")
                    raise FlukeESA612Error(FLUKE_ERROR_CODES[line])

                if re.search(r'\d', line):
                    logging.debug(f"<- MREAD: {line}")
                    reading = line
                    break # Trovata una lettura valida
                
                time.sleep(0.1)
        finally:
            # Assicura sempre l'invio di ESC per fermare la modalità MREAD,
            # anche in caso di errore o timeout.
            self.ser.write(b'\x1b')
            time.sleep(0.2)
            if self.ser.in_waiting > 0:
                self.ser.read(self.ser.in_waiting)

        if reading is None:
            raise TimeoutError("Nessuna lettura valida ricevuta dallo strumento dopo il comando MREAD.")
        
        return reading

    def extract_numeric_value(self, raw_response: str) -> str:
        """
        Estrae il primo valore numerico (inclusi decimali e notazione scientifica)
        da una stringa di risposta grezza.

        Raises:
            ValueError: Se non viene trovato un valore numerico.
        """
        if raw_response is None:
            raise ValueError("La risposta ricevuta è nulla.")
        
        match = re.search(r'[-+]?\d*\.?\d+(?:[eE][-+]?\d+)?', raw_response)
        if not match:
            raise ValueError(f"Impossibile estrarre un valore numerico dalla risposta: '{raw_response}'")
        return match.group(0)

    # --- FUNZIONI DI TEST DI ALTO LIVELLO ---
    
    def _execute_test_and_get_value(self, commands: list):
        """Funzione helper per eseguire una sequenza di comandi e restituire un valore numerico."""
        for cmd in commands:
            self._send_and_check(cmd)
            time.sleep(0.2) # Pausa tra comandi per stabilità
        
        raw_reading = self.get_first_reading()
        return self.extract_numeric_value(raw_reading)

    def esegui_test_tensione_rete(self, parametro_test: str, **kwargs) -> str:
        param_map = {"Da Fase a Neutro": "L1-L2", "Da Neutro a Terra": "L2-GND", "Da Fase a Terra": "L1-GND"}
        fluke_param = param_map.get(parametro_test)
        if not fluke_param:
            raise ValueError(f"Parametro test tensione non valido: {parametro_test}")
        
        return self._execute_test_and_get_value(["STD=353", f"MAINS={fluke_param}"])

    def esegui_test_resistenza_terra(self, **kwargs) -> str:
        return self._execute_test_and_get_value(["STD=353", "ERES"])
        


    def esegui_test_dispersione_diretta(self, parametro_test: str, **kwargs) -> str:
        is_reverse = "inversa" in parametro_test.lower()
        polarity_command = "POL=R" if is_reverse else "POL=N"
        
        commands = ["STD=353", "DIRL", "MODE=ACDC", "EARTH=O", "POL=OFF"]
        self._execute_test_and_get_value(commands)
        time.sleep(2.8) # Pausa più lunga richiesta da POL=OFF
        
        return self._execute_test_and_get_value([polarity_command, "AP=ALL//"])
        
    def esegui_test_dispersione_parti_applicate(self, parametro_test: str, pa_code: str = "ALL", **kwargs) -> str:
        is_reverse = "inversa" in parametro_test.lower()
        polarity_command = "POL=R" if is_reverse else "POL=N"
        
        commands = ["STD=353", "NOMINAL=ON", "DMAP", "MAP=3.5MA", "MODE=ACDC", "POL=OFF"]
        self._execute_test_and_get_value(commands)
        time.sleep(2.8) # Pausa più lunga richiesta da POL=OFF
        
        try:
            value = self._execute_test_and_get_value([polarity_command, f"AP={pa_code}//OPEN"])
        finally:
            # Assicura che NOMINAL=OFF sia sempre eseguito
            self._send_and_check("NOMINAL=OFF")
            if self.ser.in_waiting > 0:
                self.ser.read(self.ser.in_waiting)
        return value

    @staticmethod
    def list_available_ports() -> list[str]:
        """
        Elenca le porte COM disponibili sul sistema.

        Returns:
            list[str]: Una lista di stringhe con i nomi delle porte (es. ["COM1", "COM3"]).
        """
        ports = serial.tools.list_ports.comports()
        return [port.device for port in ports]
