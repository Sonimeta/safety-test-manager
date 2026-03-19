from click import command
import serial
import serial.tools.list_ports
import time
import logging
import re

class FlukeESA612Error(Exception):
    """Eccezione personalizzata per errori di comunicazione con il Fluke ESA612."""
    pass
# Dizionario per tradurre i codici di errore dello strumento
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
    def __init__(self, port):
        if not port or port == "Nessuna":
            raise ValueError("È richiesta una porta COM valida per comunicare con lo strumento.")
        self.port = port
        self.ser = None
        # Stato interno per gestire le sequenze sulle parti applicate
        self._pa_sequence_active = False
        self._pa_sequence_is_reverse = None
        self.connection_params = {
            'baudrate': 115200, 'bytesize': serial.EIGHTBITS, 'parity': serial.PARITY_NONE,
            'stopbits': serial.STOPBITS_ONE, 'timeout': 4, 'rtscts': True
        }

    def __enter__(self):
        self.connect()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.disconnect()

    def connect(self):
        try:
            logging.info(f"Connessione con strumento sulla porta {self.port}...")
            self.ser = serial.Serial(self.port, **self.connection_params)
            self.ser.reset_input_buffer()
            self.ser.reset_output_buffer()
            time.sleep(0.2) # Breve pausa per stabilizzare la connessione
            self.ser.write(b'\x1b') # Invia ESC per resettare lo stato dello strumento
            time.sleep(0.2)  # Dai allo strumento il tempo di rispondere a ESC
            
            # Svuota attivamente il buffer di input da qualsiasi risposta residua a ESC
            if self.ser.in_waiting > 0:
                bytes_da_leggere = self.ser.in_waiting
                self.ser.read(bytes_da_leggere)
                logging.debug(f"Puliti {bytes_da_leggere} byte residui dopo ESC.")
            
            self.ser.reset_input_buffer() # Assicura che sia completamente vuoto
            
            self._send_and_check("REMOTE")
            time.sleep(0.2)
            logging.info("Connessione riuscita e strumento in modalità remota.")
            
        except serial.SerialException as e:
            raise ConnectionError(f"Impossibile aprire la porta {self.port}. Controllare che sia libera e che lo strumento sia acceso.")
        except Exception:
            self.disconnect()
            raise

    def disconnect(self):
        """
        Riporta lo strumento in modalità locale e chiude la connessione in modo definitivo.
        """
        if self.ser and self.ser.is_open:
            try:
                logging.info("Ripristino dello strumento in modalità locale...")
                # Pulisce eventuali dati residui nel buffer prima di inviare l'ultimo comando
                if self.ser.in_waiting > 0:
                    self.ser.read(self.ser.in_waiting)
                    logging.debug("Puliti byte residui prima della disconnessione.")

                self.ser.write(b'LOCAL\r\n')
                logging.debug("-> CMD: LOCAL")
                time.sleep(0.5) # Pausa critica per permettere allo strumento di tornare in locale
            except Exception as e:
                logging.warning(f"Errore non critico durante l'invio del comando LOCAL: {e}")
            finally:
                self.ser.close()
                logging.info(f"Disconnesso da {self.port}.")
        self.ser = None

    def send_command(self, command: str) -> str:
        if not self.ser or not self.ser.is_open:
            raise ConnectionError("Porta seriale non aperta.")
        full_command = f"{command}\r\n".encode('ascii')
        self.ser.write(full_command)
        logging.debug(f"-> CMD: {command}")
        deadline = time.time() + (self.connection_params.get('timeout') or 2)
        while time.time() < deadline:
            line = self.ser.readline()
            if line:
                resp = line.decode('ascii', errors='ignore').strip()
                logging.debug(f"<- RESP: {resp}")
                return resp
        raise TimeoutError(f"Timeout attendendo risposta a '{command}'")

    def _send_and_check(self, command: str, expected: str = "*", retries: int = 3):
        last_err = None
        for _ in range(max(1, retries)):
            try:
                response = self.send_command(command)
                if expected in response:
                    return
                error_message = FLUKE_ERROR_CODES.get(response, f"Risposta inattesa: '{response}'")
                raise IOError(f"Comando '{command}' fallito. {error_message}")
            except Exception as e:
                last_err = e
                time.sleep(0.2)
        raise last_err

    def get_first_reading(self) -> str:
        self._send_and_check("MREAD")
        reading = None
        
        try:
            for _ in range(15):
                line = self.ser.readline().decode('ascii').strip()
                if not line:
                    continue

                # Se la risposta è un errore conosciuto, la restituiamo come risultato
                if line in FLUKE_ERROR_CODES:
                    logging.warning(f"Strumento ha riportato un codice di errore: {line}")
                    reading = line # Restituisce il codice di errore (es. '!21')
                    break

                # Altrimenti, cerca un valore numerico come prima
                if re.search(r'\d', line):
                    logging.debug(f"<- MREAD: {line}")
                    reading = line
                    break
                
                time.sleep(0.2)
        finally:
            # Questa parte viene eseguita sempre per garantire che lo strumento esca dalla modalità di lettura
            self.ser.write(b'\x1b')
            time.sleep(0.2)
            if self.ser.in_waiting > 0:
                self.ser.read(self.ser.in_waiting)

        return reading

    def extract_numeric_value(self, raw_response: str) -> str:
        if raw_response is None:
            raise ValueError("Nessuna lettura valida ricevuta dallo strumento (timeout).")
        # Regex migliorata per gestire numeri in notazione scientifica
        match = re.search(r'[-+]?\d*\.?\d+(?:[eE][-+]?\d+)?', raw_response)
        if not match:
            raise ValueError(f"Impossibile estrarre un valore numerico dalla risposta: '{raw_response}'")
        return match.group(0)

    # --- FUNZIONI DI TEST DI ALTO LIVELLO ---
    def esegui_test_tensione_rete(self, parametro_test: str, **kwargs):
        param_map = {"Da Fase a Neutro": "L1-L2", "Da Neutro a Terra": "L2-GND", "Da Fase a Terra": "L1-GND"}
        fluke_param = param_map.get(parametro_test)
        if not fluke_param:
            raise ValueError(f"Parametro test tensione non valido: {parametro_test}")
        self._send_and_check("STD=353")
        self._send_and_check(f"MAINS={fluke_param}")
        time.sleep(0.3)
        raw_reading = self.get_first_reading()
        # Se la lettura è un codice di errore, restituiscilo direttamente
        if raw_reading and raw_reading.startswith('!'):
            return raw_reading
        return self.extract_numeric_value(raw_reading)

    def esegui_test_resistenza_terra(self, **kwargs):
        self._send_and_check("STD=353")
        self._send_and_check("ERES")
        time.sleep(0.3)
        raw_reading = self.get_first_reading()
        # Se la lettura è un codice di errore, restituiscilo direttamente
        if raw_reading and raw_reading.startswith('!'):
            return raw_reading
        return self.extract_numeric_value(raw_reading)

    def esegui_test_dispersione_diretta(self, parametro_test: str, **kwargs):
        is_reverse = "inversa" in parametro_test.lower()
        self._send_and_check("STD=353")
        time.sleep(0.3)
        self._send_and_check("DIRL")
        time.sleep(0.2)
        self._send_and_check("MODE=ACDC")
        time.sleep(0.1)
        self._send_and_check("EARTH=O")
        time.sleep(0.2)
        self._send_and_check("POL=OFF")
        time.sleep(3)
        polarity_command = "POL=R" if is_reverse else "POL=N"
        self._send_and_check(polarity_command)
        time.sleep(0.3)
        self._send_and_check("AP=ALL//")
        time.sleep(1)
        raw_reading = self.get_first_reading()
        # Se la lettura è un codice di errore, restituiscilo direttamente
        if raw_reading and raw_reading.startswith('!'):
            return raw_reading
        return self.extract_numeric_value(raw_reading)

    def _start_pa_sequence(self, is_reverse: bool):
        """
        Configura lo strumento per una sequenza di prove sulle parti applicate
        con una data polarità (diretta o inversa). Viene chiamata solo quando
        inizia una nuova sequenza o quando cambia la polarità.
        """
        self._send_and_check("STD=353")
        time.sleep(0.3)
        self._send_and_check("NOMINAL=ON")
        time.sleep(0.2)
        self._send_and_check("DMAP")
        time.sleep(0.1)
        self._send_and_check("MAP=3.5MA")
        time.sleep(0.1)
        self._send_and_check("MODE=ACDC")
        time.sleep(0.2)
        self._send_and_check("POL=OFF")
        time.sleep(3)
        polarity_command = "POL=R" if is_reverse else "POL=N"
        self._send_and_check(polarity_command)
        time.sleep(0.3)
        # Segna la sequenza come attiva per questa polarità
        self._pa_sequence_active = True
        self._pa_sequence_is_reverse = is_reverse

    def _measure_single_pa(self, pa_code: str) -> str:
        """
        Esegue la misura su UNA singola parte applicata, assumendo che lo
        strumento sia già stato configurato per la sequenza corrente.
        """
        self._send_and_check(f"AP={pa_code}//OPEN")
        time.sleep(0.3)
        raw_reading = self.get_first_reading()
        # Se la lettura è un codice di errore, restituiscilo direttamente
        if raw_reading and raw_reading.startswith('!'):
            return raw_reading
        return self.extract_numeric_value(raw_reading)

    def esegui_test_dispersione_parti_applicate(self, parametro_test: str, pa_code: str = "ALL", **kwargs):
        """
        Misura la corrente di dispersione sulle parti applicate.

        Importante: per non togliere tensione tra una parte applicata e l'altra,
        la configurazione della sequenza (NOMINAL, DMAP, POL, ecc.) viene eseguita
        solo quando inizia una nuova sequenza o cambia la polarità (diretta/inversa).
        """
        is_reverse = "inversa" in parametro_test.lower()

        # Se non c'è una sequenza attiva o la polarità è cambiata, riconfigura tutto
        if (not self._pa_sequence_active) or (self._pa_sequence_is_reverse != is_reverse):
            self._start_pa_sequence(is_reverse)

        # Esegui la misura sulla parte applicata richiesta senza spegnere la tensione
        return self._measure_single_pa(pa_code)

    @staticmethod
    def list_available_ports():
        """Elenca tutte le porte COM disponibili sul sistema."""
        ports = serial.tools.list_ports.comports()
        port_names = [port.device for port in ports]
        # Log di debug con descrizione utile soprattutto su Windows
        for p in ports:
            logging.debug(
                f"Porta trovata: device={p.device}, desc={getattr(p, 'description', '')}, "
                f"hwid={getattr(p, 'hwid', '')}, manufacturer={getattr(p, 'manufacturer', '')}"
            )
        return port_names

    @staticmethod
    def _get_fluke_candidate_ports():
        """
        Restituisce una lista di porte che sembrano riferirsi a strumenti Fluke,
        utilizzando le informazioni fornite da Windows (descrizione, produttore, ecc.).
        """
        candidates = []
        ports = serial.tools.list_ports.comports()
        for p in ports:
            desc = (getattr(p, "description", "") or "").lower()
            manuf = (getattr(p, "manufacturer", "") or "").lower()
            hwid = (getattr(p, "hwid", "") or "").lower()

            # Escludi esplicitamente le porte Bluetooth virtuali che tendono a
            # bloccare l'apertura e non sono quasi mai lo strumento di misura.
            if "bluetooth" in desc or "bluetooth" in hwid or "bthenum" in hwid:
                continue

            text = f"{desc} {manuf} {hwid}"

            # Criteri euristici:
            # - qualsiasi riferimento a "fluke"
            # - oppure interfacce USB-Seriali tipiche degli strumenti (es. Prolific PL2303)
            if (
                "fluke" in text
                or "prolific" in text
                or "pl2303" in text
                or "usb serial" in text
            ):
                logging.info(
                    f"Candidato strumento trovato: {p.device} "
                    f"(desc='{p.description}', manufacturer='{p.manufacturer}', hwid='{p.hwid}')"
                )
                candidates.append(p.device)

        return candidates
    
    @staticmethod
    def detect_fluke_port(timeout_per_port=0.5, max_ports_to_test=5):
        """
        Rileva automaticamente la porta COM su cui è collegato il Fluke ESA612.
        Testa ogni porta COM disponibile inviando un comando di identificazione.
        
        NOTA: Questo metodo può richiedere diversi secondi. Dovrebbe essere chiamato
        in un thread separato per non bloccare l'interfaccia utente.
        
        Args:
            timeout_per_port: Timeout in secondi per ogni test di porta (default: 0.5)
            max_ports_to_test: Numero massimo di porte da testare (default: 5)
            
        Returns:
            str: Nome della porta COM se trovata (es. "COM3"), None se non trovata
        """
        all_ports = FlukeESA612.list_available_ports()
        if not all_ports:
            logging.warning("Nessuna porta COM disponibile trovata.")
            return None

        # Filtra le porte Bluetooth - lo strumento Fluke non usa Bluetooth
        ports_info = serial.tools.list_ports.comports()
        filtered_ports = []
        for port_info in ports_info:
            port_name = port_info.device
            description = getattr(port_info, 'description', '').lower()
            hwid = getattr(port_info, 'hwid', '').lower()
            
            # Escludi porte Bluetooth
            if 'bluetooth' in description or 'bluetooth' in hwid or 'bthenum' in hwid:
                logging.debug(f"Porta Bluetooth esclusa: {port_name}")
                continue
            
            filtered_ports.append(port_name)
        
        if not filtered_ports:
            logging.warning("Nessuna porta COM disponibile (escluse porte Bluetooth).")
            return None
        
        logging.info(f"Porte disponibili dopo filtro Bluetooth: {filtered_ports}")

        # Prima prova le porte che sembrano essere Fluke (in base a descrizione / produttore)
        fluke_ports = FlukeESA612._get_fluke_candidate_ports()
        # Filtra anche i candidati Fluke per escludere Bluetooth
        fluke_ports = [p for p in fluke_ports if p in filtered_ports]

        # Se non troviamo candidati specifici Fluke, testiamo tutte le porte filtrate (ma limitate)
        if fluke_ports:
            ports_to_test = fluke_ports + [p for p in filtered_ports if p not in fluke_ports]
            logging.info(
                f"Rilevamento automatico porta COM: priorità alle porte candidate Fluke "
                f"({fluke_ports}), totale da testare: {min(len(ports_to_test), max_ports_to_test)}"
            )
        else:
            ports_to_test = filtered_ports[:max_ports_to_test]  # Limita il numero di porte
            logging.info(f"Rilevamento automatico porta COM: nessun candidato Fluke, "
                         f"testando le prime {len(ports_to_test)} porte disponibili (Bluetooth escluse)...")
        
        # Limita il numero totale di porte da testare
        ports_to_test = ports_to_test[:max_ports_to_test]

        for port_name in ports_to_test:
            test_ser = None
            try:
                logging.debug(f"Testando porta {port_name}...")
                # Prova a connettersi e inviare un comando di identificazione
                # Usa un timeout molto breve per evitare blocchi lunghi
                test_ser = serial.Serial(
                    port_name,
                    baudrate=115200,
                    bytesize=serial.EIGHTBITS,
                    parity=serial.PARITY_NONE,
                    stopbits=serial.STOPBITS_ONE,
                    timeout=min(timeout_per_port, 0.5),  # Massimo 0.5 secondi per evitare blocchi
                    write_timeout=0.3,  # Timeout breve per la scrittura
                    rtscts=True
                )
                
                # Pulisce il buffer
                test_ser.reset_input_buffer()
                test_ser.reset_output_buffer()
                time.sleep(0.2)
                
                # Invia ESC per resettare lo stato
                test_ser.write(b'\x1b')
                time.sleep(0.2)
                if test_ser.in_waiting > 0:
                    test_ser.read(test_ser.in_waiting)
                
                # Prova a inviare un comando semplice che il Fluke dovrebbe riconoscere
                # Usa un comando che non modifica lo stato dello strumento
                test_ser.write(b'REMOTE\r\n')
                time.sleep(0.3)
                
                # Legge la risposta
                if test_ser.in_waiting > 0:
                    response = test_ser.read(test_ser.in_waiting).decode('ascii', errors='ignore').strip()
                    # Il Fluke ESA612 dovrebbe rispondere con "*" o un messaggio di conferma
                    if response and ('*' in response or 'REMOTE' in response.upper() or len(response) > 0):
                        logging.info(f"Porta COM rilevata automaticamente: {port_name}")
                        # Invia LOCAL per ripristinare lo stato
                        try:
                            test_ser.write(b'LOCAL\r\n')
                            time.sleep(0.2)
                        except:
                            pass
                        if test_ser:
                            test_ser.close()
                        return port_name
                
                # Prova anche con un comando di identificazione alternativo
                test_ser.reset_input_buffer()
                test_ser.write(b'IDN?\r\n')
                time.sleep(0.3)
                if test_ser.in_waiting > 0:
                    response = test_ser.read(test_ser.in_waiting).decode('ascii', errors='ignore').strip()
                    if response:
                        logging.info(f"Porta COM rilevata automaticamente (IDN): {port_name}")
                        try:
                            test_ser.write(b'LOCAL\r\n')
                            time.sleep(0.2)
                        except:
                            pass
                        if test_ser:
                            test_ser.close()
                        return port_name

            except serial.SerialException as e:
                error_msg = str(e)
                # Se è un timeout del semaforo (Windows), passa rapidamente alla porta successiva
                if "timeout" in error_msg.lower() or "semaforo" in error_msg.lower():
                    logging.debug(f"Porta {port_name} non disponibile (timeout): saltata")
                else:
                    logging.debug(f"Porta {port_name} non disponibile o errore: {e}")
                if test_ser:
                    try:
                        test_ser.close()
                    except:
                        pass
                continue
            except Exception as e:
                error_msg = str(e)
                # Gestisci rapidamente i timeout
                if "timeout" in error_msg.lower() or "semaforo" in error_msg.lower():
                    logging.debug(f"Timeout su porta {port_name}: saltata")
                else:
                    logging.debug(f"Errore durante il test della porta {port_name}: {e}")
                if test_ser:
                    try:
                        test_ser.close()
                    except:
                        pass
                continue
        
        logging.warning("Nessuna porta COM compatibile con Fluke ESA612 trovata.")
        return None
