# app/exceptions.py
"""
Eccezioni custom per l'applicazione Safety Test Manager.
"""

class DeletedDeviceFoundException(Exception):
    """
    Eccezione sollevata quando si tenta di creare un dispositivo con un numero
    di serie che è già stato utilizzato da un dispositivo eliminato.
    
    Questa eccezione deve essere gestita dall'UI mostrando un dialog di conferma
    all'utente per scegliere se riattivare il dispositivo esistente o crearne uno nuovo.
    
    Attributes:
        deleted_device (dict): Dizionario contenente tutti i dettagli del dispositivo eliminato
    """
    def __init__(self, deleted_device):
        self.deleted_device = deleted_device
        serial = deleted_device.get('serial_number', 'N/A')
        super().__init__(f"Dispositivo eliminato trovato con S/N: {serial}")


class DuplicateActiveSerialException(Exception):
    """
    Eccezione sollevata quando si tenta di creare/modificare un dispositivo con un numero
    di serie già utilizzato da un altro dispositivo ATTIVO nel database.

    A differenza di DeletedDeviceFoundException, qui il dispositivo duplicato è ancora
    attivo: l'utente può scegliere se inserire comunque il nuovo dispositivo (permettendo
    duplicati) oppure annullare l'operazione.

    Attributes:
        existing_device (dict): Dizionario con i dati del dispositivo attivo già esistente
        serial_number (str): Il numero di serie duplicato
    """
    def __init__(self, existing_device: dict, serial_number: str):
        self.existing_device = existing_device
        self.serial_number = serial_number
        super().__init__(f"Numero di serie '{serial_number}' già utilizzato da un dispositivo attivo.")

