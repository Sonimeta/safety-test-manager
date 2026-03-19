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

