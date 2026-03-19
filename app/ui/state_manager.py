from PySide6.QtCore import QObject, Signal
from enum import Enum

class AppState(Enum):
    """Stati dell'applicazione"""
    IDLE = "idle"
    TESTING = "testing"
    SYNCING = "syncing"
    LOADING = "loading"
    ERROR = "error"

class StateManager(QObject):
    """Gestore centralizzato dello stato dell'applicazione"""
    state_changed = Signal(AppState)
    message_changed = Signal(str)
    
    def __init__(self):
        super().__init__()
        self._current_state = AppState.IDLE
        self._current_message = ""
    
    @property
    def current_state(self):
        """Stato corrente dell'applicazione"""
        return self._current_state
    
    @property
    def current_message(self):
        """Messaggio di stato corrente"""
        return self._current_message
    
    def set_state(self, new_state: AppState, message: str = ""):
        """Imposta un nuovo stato dell'applicazione"""
        if self._current_state != new_state:
            self._current_state = new_state
            self.state_changed.emit(new_state)
        
        if message and self._current_message != message:
            self._current_message = message
            self.message_changed.emit(message)
    
    def is_idle(self):
        """Verifica se l'applicazione è inattiva"""
        return self._current_state == AppState.IDLE
    
    def is_testing(self):
        """Verifica se è in corso un test"""
        return self._current_state == AppState.TESTING
    
    def is_syncing(self):
        """Verifica se è in corso una sincronizzazione"""
        return self._current_state == AppState.SYNCING
    
    def is_loading(self):
        """Verifica se è in corso un caricamento"""
        return self._current_state == AppState.LOADING
    
    def is_error(self):
        """Verifica se c'è un errore"""
        return self._current_state == AppState.ERROR
    
    def can_start_test(self):
        """Verifica se è possibile avviare un test"""
        return self._current_state in [AppState.IDLE]
    
    def can_sync(self):
        """Verifica se è possibile sincronizzare"""
        return self._current_state in [AppState.IDLE]
