# pip install PySide6 requests
from PySide6.QtCore import Qt, QTimer, QPoint, QSettings
from PySide6.QtGui import QAction, QColor
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QLineEdit, QLabel, QDialogButtonBox, QMessageBox,
    QFormLayout, QFrame, QGraphicsDropShadowEffect, QSizePolicy, QSpacerItem
)
import requests
from app.http_client import http_session

# Config di fallback se non esiste il modulo app.config
try:
    from app import config
    from app.config import load_stylesheet, get_current_stylesheet
    # Ottiene lo stylesheet corrente in base al tema
    STYLESHEET = get_current_stylesheet()
    # Carica lo stile specifico per il login
    EXTRA_STYLESHEET = load_stylesheet("login.qss")
except ModuleNotFoundError:
    class DummyConfig:
        SERVER_URL = "http://localhost:8000"
    config = DummyConfig()
    STYLESHEET = ""
    EXTRA_STYLESHEET = ""


class LoginDialog(QDialog):
    """
    Versione "solo riquadro": la finestra mostra unicamente la card bianca con ombra,
    senza spazio/grigio intorno. È anche frameless e con sfondo trasparente
    per un look pulito.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("LoginDialog")
        self.setWindowTitle("Login - Safety Test Manager")
        self.setModal(True)
        self.token_data = None

        # --- Mostra SOLO il riquadro ---
        self.setWindowFlags(self.windowFlags() | Qt.FramelessWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground)

        # ------- Root layout -------
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(0)

        # ------- Card con ombra -------
        self.card = QFrame()
        self.card.setObjectName("card")
        card_layout = QVBoxLayout(self.card)
        card_layout.setContentsMargins(28, 28, 28, 20)
        card_layout.setSpacing(18)

        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(40)
        shadow.setOffset(0, 16)
        shadow.setColor(QColor(0, 0, 0, 160))
        self.card.setGraphicsEffect(shadow)

        title = QLabel("Accedi")
        title.setObjectName("title")
        subtitle = QLabel("Inserisci le tue credenziali per continuare.")
        subtitle.setObjectName("subtitle")
        subtitle.setWordWrap(True)

        # ------- Form -------
        form_layout = QFormLayout()
        form_layout.setLabelAlignment(Qt.AlignLeft)
        form_layout.setFormAlignment(Qt.AlignTop)

        self.username_edit = QLineEdit()
        self.settings = QSettings("ELSON META", "SafetyTester")
        self.username_edit.setText(self.settings.value("last_username",""))
        self.username_edit.setObjectName("input")
        self.username_edit.setProperty("_stm_skip_uppercase", True)  # Escludi dal maiuscolo globale
        self.username_edit.setPlaceholderText("Nome utente")
        self.username_edit.setClearButtonEnabled(True)

        self.password_edit = QLineEdit()
        self.password_edit.setObjectName("input")
        self.password_edit.setPlaceholderText("Password")
        self.password_edit.setEchoMode(QLineEdit.Password)
        self.password_edit.setProperty("_stm_password", True)
        self.password_edit.setClearButtonEnabled(True)

        # Toggle mostra/nascondi password
        self.toggle_action = QAction("Mostra", self.password_edit)
        self.toggle_action.triggered.connect(self._toggle_password)
        self.password_edit.addAction(self.toggle_action, QLineEdit.TrailingPosition)

        form_layout.addRow(QLabel("Nome utente:"), self.username_edit)
        form_layout.addRow(QLabel("Password:"), self.password_edit)

        # ------- Pulsanti -------
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Ok).setText("Accedi")
        buttons.button(QDialogButtonBox.Cancel).setText("Annulla")

        buttons.button(QDialogButtonBox.Ok).setDefault(True)
        buttons.button(QDialogButtonBox.Ok).setAutoDefault(True)

        buttons.accepted.connect(self.attempt_login)
        buttons.rejected.connect(self.reject)

        # Invio = login, Esc = annulla
        self.password_edit.returnPressed.connect(self.attempt_login)
        self.username_edit.returnPressed.connect(self.password_edit.setFocus)
        self.addAction(self._make_esc_action())

        # Compose
        card_layout.addWidget(title)
        card_layout.addWidget(subtitle)
        card_layout.addLayout(form_layout)
        card_layout.addSpacing(8)
        card_layout.addWidget(buttons)

        root.addWidget(self.card, 0, Qt.AlignCenter)

        # Stile e dimensioni compatte
        self._apply_style()
        self.adjustSize()
        self.setFixedSize(self.sizeHint())

        # Drag finestra
        self._drag_pos: QPoint | None = None
        self.card.mousePressEvent = self._start_drag
        self.card.mouseMoveEvent = self._do_drag
        self.card.mouseReleaseEvent = self._end_drag

    # ------------------ UI helpers ------------------

    def _make_esc_action(self):
        act = QAction(self)
        act.setShortcut("Esc")
        act.triggered.connect(self.reject)
        return act

    def _apply_style(self):
        combined = ""
        try:
            combined = STYLESHEET
        except Exception:
            combined = ""
        self.setStyleSheet(combined + "\n" + EXTRA_STYLESHEET)

    def _toggle_password(self):
        if self.password_edit.echoMode() == QLineEdit.Password:
            self.password_edit.setEchoMode(QLineEdit.Normal)
            self.toggle_action.setText("Nascondi")
        else:
            self.password_edit.setEchoMode(QLineEdit.Password)
            self.toggle_action.setText("Mostra")

    # ------------------ Login logic ------------------

    def attempt_login(self):
        username = self.username_edit.text().strip()
        self.settings.setValue("last_username", username)
        password = self.password_edit.text()

        if not username or not password:
            QMessageBox.warning(self, "Dati mancanti", "Inserire nome utente e password.")
            self._highlight_empty()
            return

        token_url = f"{config.SERVER_URL}/token"

        try:
            self.setEnabled(False)
            response = http_session.post(
                token_url,
                data={"username": username, "password": password},
                timeout=10,
            )

            if response.status_code == 200:
                try:
                    self.token_data = response.json()
                except ValueError:
                    QMessageBox.critical(self, "Errore server", "Risposta non valida dal server (JSON non parsabile).")
                    self.setEnabled(True)
                    return
                self.accept()
            elif response.status_code == 429:
                try:
                    retry = response.json().get("detail", "Troppi tentativi. Riprova tra qualche minuto.")
                except ValueError:
                    retry = "Troppi tentativi di login. Riprova tra qualche minuto."
                QMessageBox.warning(self, "Troppi tentativi", retry)
                self.setEnabled(True)
            elif response.status_code in (401, 422):
                QMessageBox.warning(self, "Login fallito", "Nome utente o password non corretti.")
                self.setEnabled(True)
            else:
                QMessageBox.critical(self, "Errore server", f"Errore inatteso: {response.status_code}")
                self.setEnabled(True)

        except requests.RequestException as e:
            detail = ""
            try:
                if e.response is not None and 'application/json' in e.response.headers.get('content-type',''):
                    detail = e.response.json().get("detail","")
            except Exception:
                pass
            QMessageBox.critical(self, "Errore di connessione", f"Connessione fallita.\n{detail or str(e)}")

            self.setEnabled(True)

    def _highlight_empty(self):
        base = self.styleSheet()
        for w in (self.username_edit, self.password_edit):
            if not w.text().strip():
                w.setStyleSheet(base + " QLineEdit#input { border: 1px solid #f87171; }")
        QTimer.singleShot(700, self._apply_style)

    # --------- drag della finestra frameless ---------
    def _start_drag(self, e):
        if e.buttons() & Qt.LeftButton:
            self._drag_pos = e.globalPosition().toPoint() - self.frameGeometry().topLeft()
            e.accept()

    def _do_drag(self, e):
        if self._drag_pos is not None and e.buttons() & Qt.LeftButton:
            self.move(e.globalPosition().toPoint() - self._drag_pos)
            e.accept()

    def _end_drag(self, e):
        self._drag_pos = None
