# Deploy del Server SyncAPI sul Server PostgreSQL

Guida per spostare il server **SyncAPI** (che prima girava localmente su ogni PC)
sul **server centralizzato** dove è già installato PostgreSQL.

> **Il server NON ha Python installato** - si usa il file **EXE compilato** con PyInstaller.
> **Il server ha un IP PUBBLICO** - il traffico è cifrato con HTTPS (certificato SSL).

---

## Architettura Finale

```
                                            +----------------------------+
+-------------+       HTTPS :8000          |   Server (IP Pubblico)     |
|  PC Client  | ========================> |                            |
|  (app GUI)  | <======================== |  +----------------------+  |
+-------------+    traffico cifrato        |  | SyncAPI_Server.exe   |  |
                                           |  +----------+-----------+  |
+-------------+       HTTPS :8000          |             | localhost    |
|  PC Client  | ========================> |  +----------v-----------+  |
|  (app GUI)  | <======================== |  |    PostgreSQL DB     |  |
+-------------+    traffico cifrato        |  +----------------------+  |
                                           +----------------------------+
```

- I **client** non avviano piu' `SyncAPI_Server.exe` in locale.
- Tutti i client puntano allo stesso server centralizzato via rete.
- Il server SyncAPI si connette a PostgreSQL in **localhost** (stessa macchina).
- Il traffico tra client e server e' **cifrato con HTTPS/TLS**.

---

## Passo 1 - Compila l'exe (dal PC di sviluppo)

Sul PC dove hai Python e il codice sorgente:

```powershell
cd "D:\Desktop\PROGRAMMI\VERIFICHE ELETTRICHE + VFUN V1.0"
.\.venv\Scripts\Activate.ps1
pyinstaller real_server.spec
```

Nella cartella `dist\SyncAPI_Server\` troverai l'exe e tutte le sue dipendenze.

---

## Passo 2 - Copia i file sul server

Copia sul server (es. `C:\SyncAPI\`) questa struttura:

```
C:\SyncAPI\
+-- SyncAPI_Server\              <-- cartella dalla build PyInstaller (dist\SyncAPI_Server\)
|   +-- SyncAPI_Server.exe
|   +-- _internal\               <-- dipendenze dell'exe
|   +-- ...
+-- .env                         <-- configurazione (creato dal template)
+-- start_server.bat             <-- script di avvio
```

In pratica:
1. Copia la cartella `dist\SyncAPI_Server\` dalla build
2. Copia `start_server.bat` dalla cartella `server_deploy\`
3. Copia `.env.example`, rinominalo in `.env` e configuralo

---

## Passo 3 - Configura il file .env

Apri `.env` con Blocco Note e modifica i valori:

```env
# Database - PostgreSQL e' sulla STESSA macchina
DB_NAME=safety_test_db
DB_USER=safety_user
DB_PASSWORD=la_tua_password_reale
DB_HOST=localhost
DB_PORT=5432

# Chiave JWT - USA LA STESSA CHE AVEVI PRIMA!
SECRET_KEY=la-tua-chiave-segreta-esistente
ALGORITHM=HS256
ACCESS_TOKEN_EXPIRE_MINUTES=43200
```

**IMPORTANTE:**
- `SECRET_KEY` deve essere **identica** a quella usata prima, altrimenti tutti i client dovranno ri-loggarsi.
- `DB_HOST=localhost` perche' ora il SyncAPI gira sulla stessa macchina di PostgreSQL.

---

## Passo 4 - Genera il certificato SSL (OBBLIGATORIO per IP pubblico)

Il server ha un **IP pubblico**, quindi TUTTO il traffico deve essere cifrato con HTTPS.

### 4a. Prerequisito: OpenSSL

Il modo piu' semplice e' installare **Git for Windows** sul server
(include OpenSSL): https://git-scm.com/download/win

### 4b. Genera il certificato

Dal PC di sviluppo o dal server (se ha PowerShell), copia lo script 
`genera_certificato.ps1` nella cartella `C:\SyncAPI\` e esegui come Amministratore:

```powershell
cd C:\SyncAPI
powershell -ExecutionPolicy Bypass -File genera_certificato.ps1 -IP "IL_TUO_IP_PUBBLICO"
```

Lo script creera':
```
C:\SyncAPI\
+-- ssl\
    +-- server.key    (chiave privata - resta sul server)
    +-- server.crt    (certificato - da copiare anche sui client)
```

### 4c. Verifica che il .env punti ai file SSL

Il `.env` deve contenere:
```env
SSL_CERTFILE=ssl\server.crt
SSL_KEYFILE=ssl\server.key
```

---

## Passo 5 - Apri la porta nel Firewall di Windows

Sul server, apri PowerShell **come Amministratore**:

```powershell
New-NetFirewallRule -DisplayName "SyncAPI Server" -Direction Inbound -LocalPort 8000 -Protocol TCP -Action Allow
```

Oppure da interfaccia grafica:
1. **Windows Defender Firewall** -> Impostazioni avanzate
2. **Regole connessioni in entrata** -> Nuova regola
3. Tipo: **Porta** -> TCP -> **8000**
4. Azione: **Consenti la connessione**
5. Nome: `SyncAPI Server`

---

## Passo 6 - Avvia il server (test manuale)

Riavvia il servizio NSSM (o fai doppio clic su `start_server.bat`):

```powershell
nssm restart SyncAPI
```

Dovresti vedere nel log:
```
[CONFIG] File .env caricato da: C:\SyncAPI\.env
INFO:     HTTPS abilitato con certificato: ssl\server.crt
INFO:     Avvio server su https://0.0.0.0:8000
INFO:     Started server process
INFO:     Uvicorn running on https://0.0.0.0:8000
```

> Nota: ora dice **https** e non piu' http!

### Verifica che funzioni

Da un **PC client**, apri nel browser:
```
https://IP_DEL_SERVER:8000/health
```

> Il browser mostrera' un avviso di certificato non attendibile: e' normale
> con un certificato self-signed. Clicca "Continua" per verificare.

Risposta attesa:
```json
{"status": "healthy", "database": "connected"}
```

---

## Passo 7 - Configura i PC Client

### Opzione A: Utilita' di Pianificazione (Task Scheduler) - CONSIGLIATA

1. Apri **Utilita' di pianificazione** (`taskschd.msc`)
2. **Crea attivita'** (non "attivita' di base")
3. Scheda **Generale**:
   - Nome: `SyncAPI Server`
   - Spunta: **Esegui indipendentemente dalla connessione dell'utente**
   - Spunta: **Esegui con i privilegi piu' elevati**
4. Scheda **Trigger**:
   - Nuovo -> **All'avvio del sistema**
5. Scheda **Azione**:
   - Nuova -> **Avvio programma**
   - Programma: `C:\SyncAPI\SyncAPI_Server\SyncAPI_Server.exe`
   - Directory di avvio: `C:\SyncAPI`
6. Scheda **Impostazioni**:
   - Deseleziona "Arresta l'attivita' se in esecuzione per piu' di..."

> **FONDAMENTALE**: La **directory di avvio** deve essere `C:\SyncAPI`
> (dove c'e' il `.env`), NON la cartella dell'exe!

### Opzione B: NSSM (servizio Windows)

Scarica [NSSM](https://nssm.cc/download), poi da PowerShell come admin:

```powershell
nssm install SyncAPI "C:\SyncAPI\SyncAPI_Server\SyncAPI_Server.exe"
nssm set SyncAPI AppDirectory "C:\SyncAPI"
nssm set SyncAPI Description "Safety Test Sync API Server"
nssm set SyncAPI Start SERVICE_AUTO_START
nssm start SyncAPI
```

Comandi utili:
```powershell
nssm status SyncAPI     # verifica stato
nssm stop SyncAPI       # ferma il server
nssm restart SyncAPI    # riavvia
nssm remove SyncAPI     # rimuovi il servizio
```

---

## Passo 8 - Configura i PC Client

Su **ogni PC client**:

### 8a. Copia il certificato

Copia il file `ssl\server.crt` dal server nella **cartella del programma** del client
(la stessa cartella dove c'e' `config.ini`).

### 8b. Modifica config.ini

```ini
[server]
url = https://IP_DEL_SERVER:8000
ssl_ca_cert = server.crt
```

Esempio con IP reale:
```ini
[server]
url = https://203.0.113.50:8000
ssl_ca_cert = server.crt
```

> `ssl_ca_cert` dice all'app di fidarsi del certificato self-signed del server.
> Senza questa riga, le connessioni HTTPS falliranno.

**Non serve piu' avviare SyncAPI_Server.exe sui PC client!**

---

## Riepilogo

| Cosa | Prima (locale) | Dopo (centralizzato) |
|------|----------------|----------------------|
| **Server SyncAPI** | `.exe` su ogni PC | `.exe` **solo sul server** |
| **config.ini client** | `url = http://localhost:8000` | `url = https://IP_SERVER:8000` |
| **Protocollo** | HTTP (in chiaro) | **HTTPS (cifrato)** |
| **Connessione al DB** | Remota da ogni PC | **Locale** (localhost) = piu' veloce |
| **SyncAPI_Server.exe sui client** | Necessario | **Non piu' necessario** |
| **Avvio** | Manuale su ogni PC | Automatico come servizio NSSM |
| **Python sul server** | Non necessario | Non necessario (exe compilato) |

---

## Troubleshooting

### Il client non si connette al server
1. Il server e' acceso e l'exe e' in esecuzione?
2. Prova ad aprire `https://IP_SERVER:8000/health` dal browser del client
3. La porta 8000 e' aperta nel firewall del server?
4. Il `config.ini` del client ha l'IP giusto e usa `https://`?
5. Il file `server.crt` e' presente nella cartella del programma del client?
6. Il `config.ini` ha la riga `ssl_ca_cert = server.crt`?

### Errore SSL / certificato non valido
- Verifica che `server.crt` sul client sia lo **stesso file** generato sul server
- Se hai rigenerato il certificato sul server, copia il nuovo `server.crt` su tutti i client
- Se l'IP del server e' cambiato, rigenera il certificato con il nuovo IP

### Errore "token_expired" dopo la migrazione
- Il `SECRET_KEY` nel `.env` del server deve essere **identico** a quello usato prima
- Se l'hai cambiata, fai ri-logare tutti gli utenti dall'app

### L'exe non trova il .env
- Il file `.env` deve stare nella **directory di lavoro** (working directory), NON dentro la cartella SyncAPI_Server\
- Se usi Task Scheduler, controlla che "Directory di avvio" sia `C:\SyncAPI` (non `C:\SyncAPI\SyncAPI_Server`)
- Se avvii da prompt, fai prima `cd C:\SyncAPI`

### Errore connessione al database
- Verifica che PostgreSQL sia avviato (Servizi Windows -> `postgresql-x64-XX`)
- Verifica le credenziali nel file `.env`
- Verifica che `pg_hba.conf` permetta connessioni da `localhost`

### L'exe non parte / errore DLL
- Assicurati di aver copiato **tutta** la cartella `dist\SyncAPI_Server\` (inclusa `_internal\`)
- Non spostare solo l'exe fuori dalla sua cartella
