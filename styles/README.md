# File di Stile QSS

Questa cartella contiene i file di stile Qt Style Sheet (QSS) utilizzati dall'applicazione.

## File disponibili

- **main.qss**: Stile principale dell'applicazione. Contiene gli stili per tutti i componenti principali (bottoni, tabelle, input, ecc.)
- **login.qss**: Stile specifico per il dialog di login
- **components.qss**: Stili per componenti specifici (overlay, tabelle funzionali, ecc.)

## Come modificare gli stili

1. Apri il file QSS che vuoi modificare con un editor di testo
2. Modifica le proprietà CSS secondo le tue esigenze
3. Salva il file
4. Riavvia l'applicazione per vedere le modifiche

## Sintassi QSS

La sintassi QSS è simile a CSS, ma con alcune differenze. Ecco alcuni esempi:

```qss
/* Selettore per tutti i QPushButton */
QPushButton {
    background-color: #2563eb;
    color: white;
    border-radius: 8px;
}

/* Selettore per un QPushButton con ID specifico */
QPushButton#addButton {
    background-color: #16a34a;
}

/* Selettore per stato hover */
QPushButton:hover {
    background-color: #1d4ed8;
}

/* Selettore per stato focus */
QLineEdit:focus {
    border: 2px solid #2563eb;
}
```

## Note importanti

- I file QSS vengono caricati automaticamente all'avvio dell'applicazione
- Se un file QSS non viene trovato, l'applicazione userà gli stili predefiniti di Qt
- Le modifiche ai file QSS richiedono il riavvio dell'applicazione per essere applicate
- I file QSS devono essere salvati con codifica UTF-8

## Struttura dei file

- **main.qss**: Contiene gli stili base per tutta l'applicazione
- **login.qss**: Contiene solo gli stili specifici per il dialog di login
- **components.qss**: Contiene stili per componenti specifici che possono essere sovrascritti

## Colori principali utilizzati

- Blu primario: `#2563eb`
- Verde (successo): `#16a34a`
- Rosso (errore): `#dc2626`
- Arancione (warning): `#ea580c`
- Grigio secondario: `#64748b`
- Sfondo chiaro: `#f8fafc`
- Sfondo bianco: `#ffffff`

