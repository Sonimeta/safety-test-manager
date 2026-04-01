# main.py
import logging
import sys
import os
from PySide6.QtCore import Qt, QTimer, QLocale, QTranslator, QLibraryInfo, QEvent
from PySide6.QtWidgets import (QApplication, QMessageBox, QDialog, QSplashScreen,
                               QStyle, QLineEdit, QComboBox,
                               QListWidget, QListWidgetItem,
                               QTableWidget, QTableWidgetItem)
from PySide6.QtGui import QPixmap, QKeyEvent
from PySide6.QtGui import QGuiApplication, QFontDatabase
from PySide6.QtGui import QFont
from jose import jwt, JWTError
from app import auth_manager
from dotenv import load_dotenv
from app.config import MODERN_STYLESHEET, load_verification_profiles
from app.ui.main_window import MainWindow
from app.logging_config import setup_logging, log_session_start
from app.backup_manager import create_backup
from app.ui.dialogs.login_dialog import LoginDialog
from app import config
from app import services
from app.functional_templates import FUNCTIONAL_PROFILE_TEMPLATES

# ═══════════════════════════════════════════════════════════════════════════════
# PATCH MAIUSCOLO SELETTIVO: Forza testo MAIUSCOLO solo in finestre marcate
# con la proprietà Qt "_stm_uppercase_window" = True.
# Attivo solo in: Schermata Principale (MainWindow) e Gestione Anagrafiche.
# Copre: QLineEdit (input) e QComboBox
# ═══════════════════════════════════════════════════════════════════════════════

def _is_uppercase_context(widget):
    """Restituisce True se il widget si trova in una finestra marcata per il maiuscolo.
    
    Risale la catena dei parent e si ferma alla prima finestra (QDialog/QMainWindow).
    Solo se quella finestra ha la proprietà _stm_uppercase_window = True il maiuscolo è attivo.
    Questo evita che dialog figli di MainWindow ereditino il maiuscolo automaticamente.
    """
    parent = widget
    while parent:
        # Se troviamo una finestra (dialog o main window), controlliamo solo lei
        if parent.isWindow():
            return bool(parent.property("_stm_uppercase_window"))
        parent = parent.parent()
    return False


# ---------- QLineEdit ----------
_orig_keyPressEvent = QLineEdit.keyPressEvent
_orig_setText = QLineEdit.setText
_orig_focusOutEvent = QLineEdit.focusOutEvent


def _is_password_field(le):
    """Restituisce True se il QLineEdit è un campo password o deve essere escluso dal maiuscolo."""
    return (le.echoMode() != QLineEdit.EchoMode.Normal
            or le.property("_stm_password")
            or le.property("_stm_skip_uppercase"))


def _uppercase_keyPressEvent(self, event):
    """Intercetta la digitazione e converte ogni carattere in maiuscolo (solo in finestre marcate)."""
    if _is_password_field(self) or not _is_uppercase_context(self):
        return _orig_keyPressEvent(self, event)

    if event.type() == QEvent.Type.KeyPress:
        text = event.text()
        mods = event.modifiers()

        # Ctrl+V (incolla) → lascia incollare, poi converti il risultato
        if (mods & Qt.ControlModifier) and event.key() == Qt.Key_V:
            _orig_keyPressEvent(self, event)
            cur = self.text()
            if cur != cur.upper():
                pos = self.cursorPosition()
                _orig_setText(self, cur.upper())
                self.setCursorPosition(pos)
            return

        # Caratteri stampabili (senza Ctrl/Alt/Meta) → crea evento maiuscolo
        if (text and text.isprintable()
                and not (mods & (Qt.ControlModifier | Qt.AltModifier | Qt.MetaModifier))):
            if text != text.upper():
                upper_event = QKeyEvent(
                    QEvent.Type.KeyPress, event.key(), mods,
                    text.upper(), event.isAutoRepeat(), event.count()
                )
                return _orig_keyPressEvent(self, upper_event)

    _orig_keyPressEvent(self, event)


def _uppercase_setText(self, text):
    """Converte il testo in maiuscolo quando impostato programmaticamente (solo in finestre marcate)."""
    if _is_password_field(self) or not text or not isinstance(text, str) or not _is_uppercase_context(self):
        _orig_setText(self, text)
    else:
        _orig_setText(self, text.upper())


def _uppercase_focusOutEvent(self, event):
    """Rete di sicurezza: converte in maiuscolo quando il campo perde il focus (solo in finestre marcate)."""
    if not _is_password_field(self) and _is_uppercase_context(self):
        text = self.text()
        if text and text != text.upper():
            pos = self.cursorPosition()
            _orig_setText(self, text.upper())
            self.setCursorPosition(pos)
    _orig_focusOutEvent(self, event)


QLineEdit.keyPressEvent = _uppercase_keyPressEvent
QLineEdit.setText = _uppercase_setText
QLineEdit.focusOutEvent = _uppercase_focusOutEvent


# ---------- QComboBox ----------
_orig_QCB_addItem = QComboBox.addItem
_orig_QCB_addItems = QComboBox.addItems
_orig_QCB_setCurrentText = QComboBox.setCurrentText
_orig_QCB_insertItem = QComboBox.insertItem


def _to_upper(text):
    """Converte in maiuscolo solo stringhe non vuote."""
    return text.upper() if isinstance(text, str) and text else text


def _uppercase_QCB_addItem(self, *args, **kwargs):
    """Converte il testo dell'opzione in maiuscolo (solo in finestre marcate)."""
    if _is_uppercase_context(self):
        args = list(args)
        if args:
            if isinstance(args[0], str):
                args[0] = args[0].upper()
            elif len(args) > 1 and isinstance(args[1], str):
                args[1] = args[1].upper()
    _orig_QCB_addItem(self, *args, **kwargs)


def _uppercase_QCB_addItems(self, texts):
    if _is_uppercase_context(self):
        _orig_QCB_addItems(self, [_to_upper(t) for t in texts])
    else:
        _orig_QCB_addItems(self, texts)


def _uppercase_QCB_setCurrentText(self, text):
    if _is_uppercase_context(self):
        _orig_QCB_setCurrentText(self, _to_upper(text))
    else:
        _orig_QCB_setCurrentText(self, text)


def _uppercase_QCB_insertItem(self, index, *args, **kwargs):
    """insertItem(index, text) o insertItem(index, icon, text) — solo in finestre marcate."""
    if _is_uppercase_context(self):
        args = list(args)
        if args:
            if isinstance(args[0], str):
                args[0] = args[0].upper()
            elif len(args) > 1 and isinstance(args[1], str):
                args[1] = args[1].upper()
    _orig_QCB_insertItem(self, index, *args, **kwargs)


QComboBox.addItem = _uppercase_QCB_addItem
QComboBox.addItems = _uppercase_QCB_addItems
QComboBox.setCurrentText = _uppercase_QCB_setCurrentText
QComboBox.insertItem = _uppercase_QCB_insertItem


# ---------- QListWidget (uppercase item text al momento dell'inserimento) ----------
_orig_QLW_addItem = QListWidget.addItem
_orig_QLW_addItems = QListWidget.addItems


def _uppercase_QLW_addItem(self, item_or_text):
    """Converte il testo dell'item in maiuscolo al momento dell'inserimento nella lista (solo in finestre marcate)."""
    if _is_uppercase_context(self):
        if isinstance(item_or_text, str):
            item_or_text = item_or_text.upper()
        elif isinstance(item_or_text, QListWidgetItem):
            text = item_or_text.text()
            if text and isinstance(text, str):
                item_or_text.setText(text.upper())
    _orig_QLW_addItem(self, item_or_text)


def _uppercase_QLW_addItems(self, texts):
    if _is_uppercase_context(self):
        _orig_QLW_addItems(self, [_to_upper(t) for t in texts])
    else:
        _orig_QLW_addItems(self, texts)


QListWidget.addItem = _uppercase_QLW_addItem
QListWidget.addItems = _uppercase_QLW_addItems


# ---------- QTableWidget (uppercase cell text al momento dell'inserimento) ----------
_orig_QTW_setItem = QTableWidget.setItem


def _uppercase_QTW_setItem(self, row, col, item):
    """Converte il testo della cella in maiuscolo al momento dell'inserimento (solo in finestre marcate)."""
    if item and _is_uppercase_context(self):
        text = item.text()
        if text and isinstance(text, str):
            item.setText(text.upper())
    _orig_QTW_setItem(self, row, col, item)


QTableWidget.setItem = _uppercase_QTW_setItem
# ═══════════════════════════════════════════════════════════════════════════════

load_dotenv()
# La SECRET_KEY qui deve essere IDENTICA a quella in real_server.py
SECRET_KEY = os.getenv("SECRET_KEY")
ALGORITHM = os.getenv("ALGORITHM")

if __name__ == '__main__':
 # Configure High DPI settings BEFORE creating QApplication
    QGuiApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.RoundPreferFloor
    )
    os.environ["QT_ENABLE_HIGHDPI_SCALING"] = "1"
    
    app = QApplication(sys.argv)
    app.setApplicationName("Safety Test Manager")
    app.setOrganizationName("ELSON META")

    # Localizzazione UI Qt (pulsanti standard: Sì/No, OK/Annulla, ecc.)
    QLocale.setDefault(QLocale(QLocale.Italian, QLocale.Italy))
    qt_translator = QTranslator(app)
    qtbase_translator = QTranslator(app)
    translations_path = QLibraryInfo.path(QLibraryInfo.TranslationsPath)
    qt_translator.load("qt_it", translations_path)
    qtbase_translator.load("qtbase_it", translations_path)
    app.installTranslator(qt_translator)
    app.installTranslator(qtbase_translator)
    # Mantiene riferimenti vivi ai translator
    app._qt_translator = qt_translator
    app._qtbase_translator = qtbase_translator
    
    # Imposta un font base leggermente più grande per tutta l'app
    base_font = QFont("Segoe UI", 11)
    app.setFont(base_font)

    try:
        # Carica il pixmap originale
        logo_pixmap = QPixmap("logo.png")
        # Ridimensiona il pixmap a una dimensione più piccola (es. 500x500) mantenendo le proporzioni
        logo_pixmap = logo_pixmap.scaled(500, 500, Qt.KeepAspectRatio, Qt.SmoothTransformation)

        # --- MODIFICA CHIAVE: Crea un nuovo pixmap più alto per includere un'area per il testo ---
        text_area_height = 10  # Altezza in pixel per l'area del testo
        # Crea un pixmap composito con sfondo nero
        composite_pixmap = QPixmap(logo_pixmap.width(), logo_pixmap.height() + text_area_height)
        composite_pixmap.fill(Qt.black)
        from PySide6.QtGui import QPainter
        painter = QPainter(composite_pixmap)
        # Centra il logo orizzontalmente
        logo_x = (composite_pixmap.width() - logo_pixmap.width()) // 2
        painter.drawPixmap(logo_x, 0, logo_pixmap)
        painter.end()

        # Usa il pixmap composito per lo splash screen
        pixmap = composite_pixmap
        
        splash = QSplashScreen(pixmap)
        # Aumenta la dimensione del font per il messaggio dello splash screen
        font = splash.font()
        font.setPointSize(16) # Puoi regolare questo valore
        font.setBold(True)
        splash.setFont(font)
        splash.showMessage(f"Avvio Safety Test Manager v{config.VERSIONE}...", Qt.AlignBottom | Qt.AlignHCenter, Qt.white)
        splash.show()
        app.processEvents() 
    except Exception as e:
        logging.warning(f"Impossibile creare o mostrare lo splash screen: {e}")
        splash = None # Se il logo non viene trovato, l'app parte comunque
    # --- FINE MODIFICA ---
    # Load Segoe UI font
    font_id = QFontDatabase.addApplicationFont("C:/Windows/Fonts/segoeui.ttf")
    if font_id < 0:
        logging.warning("Font Segoe UI non trovato, uso font di sistema")
     
    # Setup logging and create backup in the main thread
    setup_logging()
    log_session_start()
    logging.info(f"BASE_DIR: {config.BASE_DIR}")
    logging.info(f"APP_DATA_DIR: {config.APP_DATA_DIR}")
    if splash:
        splash.showMessage("Configurazione logging...", Qt.AlignBottom | Qt.AlignHCenter, Qt.white)
    logging.info(f"DB_PATH: {config.DB_PATH}")
    logging.info(f"BACKUP_DIR: {config.BACKUP_DIR}")
    
    try:
        create_backup()
    except Exception as e:
        logging.error(f"Errore durante il backup: {e}")
        if splash:
            splash.showMessage("Creazione backup...", Qt.AlignBottom | Qt.AlignHCenter, Qt.white)
        QMessageBox.warning(None, "Avviso", "Impossibile creare il backup automatico.")

    while True:
        logged_in_successfully = False
        
        if auth_manager.load_session_from_disk():
            if splash:
                splash.showMessage("Sessione utente caricata...", Qt.AlignBottom | Qt.AlignHCenter, Qt.white)
            logged_in_successfully = True
        else:
            if splash:
                splash.hide() # Nascondi lo splash prima di mostrare il login
            # Create login dialog in the main thread
            login_dialog = LoginDialog()
            if login_dialog.exec() == QDialog.Accepted:
                try:
                    token = login_dialog.token_data['access_token']
                    payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
                    username = payload.get("sub")
                    role = payload.get("role")
                    full_name = payload.get("full_name", "N/D")
                    
                    auth_manager.set_current_user(username, role, token, full_name)
                    auth_manager.save_session_to_disk()
                    logged_in_successfully = True
                except (JWTError, KeyError) as e:
                    logging.error(f"Errore token: {e}")
                    QMessageBox.critical(None, "ERRORE CRITICO", 
                                      "IL TOKEN DI AUTENTICAZIONE NON È VALIDO.")
        
        if logged_in_successfully:
            try:
                # Load profiles in the main thread
                if splash:
                    splash.showMessage("Caricamento profili di verifica...", Qt.AlignBottom | Qt.AlignHCenter, Qt.white)
                config.load_verification_profiles()
                config.load_functional_profiles()
                # Evita la creazione automatica dei profili funzionali di default
                # perché può generare conflitti di sincronizzazione con il server.
                # Se serve, si può riabilitare impostando STM_SEED_FUNCTIONAL_TEMPLATES=1.
                should_seed_templates = os.getenv("STM_SEED_FUNCTIONAL_TEMPLATES", "0") == "1"
                if should_seed_templates and not config.FUNCTIONAL_PROFILES:
                    try:
                        for key, profile in FUNCTIONAL_PROFILE_TEMPLATES.items():
                            if key not in config.FUNCTIONAL_PROFILES:
                                services.add_functional_profile(key, profile)
                        config.load_functional_profiles()
                    except Exception as seed_err:
                        logging.warning(
                            "Impossibile creare i profili funzionali predefiniti: %s",
                            seed_err,
                        )
            except Exception as e:
                logging.error(f"Errore caricamento profili: {e}")
                QMessageBox.critical(None, "ERRORE CARICAMENTO PROFILI", 
                                   f"IMPOSSIBILE CARICARE I PROFILI:\n{str(e).upper()}")
                sys.exit(1)

            if splash:
                splash.showMessage("Preparazione interfaccia utente...", Qt.AlignBottom | Qt.AlignHCenter, Qt.white)
            app.setStyleSheet(config.MODERN_STYLESHEET)
            window = MainWindow()
            window.show()
            
            if splash:
                splash.finish(window) 

            app.exec()
            
            if window.relogin_requested or window.restart_after_sync:
                logging.info("Riavvio richiesto (logout o post-sync)...")
                continue
            else:
                break
        else:
            break

    logging.info("Applicazione chiusa.")
    sys.exit(0)