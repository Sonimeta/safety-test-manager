# Guida Integrazione: TechBusiness_PRO → Safety Test Manager (STM)

**Data:** Maggio 2026  
**Versione STM:** 1.0.0+STABLE  
**Autore richiesta:** Elson  

---

## 📋 Obiettivo

Quando in TechBusiness_PRO si **assegna un intervento a un tecnico** (campo `tecnicoPianificato`),
il sistema deve notificare automaticamente il gestionale STM (Safety Test Manager) per creare
un "assignment" (incarico di verifica) per quel tecnico.

Il tecnico potrà quindi vedere l'incarico nella propria app mobile STM e avviarlo.

---

## 🏗️ Architettura

```
TechBusiness_PRO (Node.js / Express)
        │
        │  HTTP POST (JSON) — chiamata locale sulla stessa macchina
        │  Header: X-STM-API-Key: <chiave_segreta_condivisa>
        ▼
Safety Test Manager — STM (Python / FastAPI)
http://127.0.0.1:8000/api/v1/external/create-assignment
```

Entrambe le applicazioni girano sullo stesso server Windows.  
La chiamata è **interna** (127.0.0.1), non esposta su internet.

---

## 🔑 Variabili d'ambiente da aggiungere in TechBusiness_PRO

Nel file `.env.server` (o `.env`, a seconda della configurazione usata per le variabili di backend),
aggiungere le seguenti righe:

```env
# URL base del server STM (sulla stessa macchina)
STM_URL=http://127.0.0.1:8000

# Chiave segreta condivisa — deve corrispondere a STM_EXTERNAL_API_KEY nel .env di STM
# Scegliere una stringa lunga e casuale (es. generata con: node -e "console.log(require('crypto').randomBytes(32).toString('hex'))")
STM_WEBHOOK_KEY=INSERIRE_QUI_LA_CHIAVE_SEGRETA
```

> ⚠️ La stessa chiave deve essere inserita nel file `.env` di STM alla voce `STM_EXTERNAL_API_KEY`.
> Concordare la chiave con il gestore di STM.

---

## 🔧 Modifica da apportare in `server.js`

### Dove intervenire

Nel gestore **`PUT /api/interventi_extra/:id`** (o equivalente), **dopo** aver salvato il record
aggiornato nel database e **prima** di inviare la risposta al client.

### Logica da implementare

```
SE tabella == 'interventi_extra'
   E il campo tecnicoPianificato è cambiato (era vuoto o diverso)
   E STM_URL e STM_WEBHOOK_KEY sono configurati
ALLORA
   Inviare una chiamata HTTP POST asincrona (fire-and-forget) a STM
   con i dati dell'intervento
```

### Codice da integrare (JavaScript / Node.js)

Inserire il seguente blocco **dopo** `res.json(rows[0]);` (o equivalente invio risposta),
all'interno del try-catch del PUT handler per `interventi_extra`:

```javascript
// --- HOOK INTEGRAZIONE STM -------------------------------------------
// Si attiva solo per interventi_extra quando viene assegnato/cambiato il tecnico
if (tabella === 'interventi_extra') {
  const nuovoRecord    = rows[0];                         // record appena salvato
  const tecnicoNuovo   = (req.body.tecnicoPianificato || '').trim();
  const tecnicoVecchio = String(vecchioRecord.tecnicoPianificato || '').trim();
  const stmUrl         = process.env.STM_URL || '';
  const stmKey         = process.env.STM_WEBHOOK_KEY || '';

  // Procede solo se il tecnico è stato appena assegnato o cambiato
  if (tecnicoNuovo && tecnicoNuovo !== tecchicoVecchio && stmUrl && stmKey) {

    // Estrae il nome cliente dal campo JSON richiestaCliente (se presente)
    let clienteNome = null;
    try {
      const c = JSON.parse(nuovoRecord.richiestaCliente || 'null');
      clienteNome = c && c.nome ? c.nome : null;
    } catch(e) {}

    const stmPayload = {
      assigned_to:        tecnicoNuovo,                        // username tecnico in STM (DEVE corrispondere)
      serial_number:      nuovoRecord.matricola       || null, // matricola apparecchiatura
      device_description: nuovoRecord.apparecchiatura || null, // nome/descrizione dispositivo (fallback)
      destination_name:   nuovoRecord.indirizzo       || null, // nome sede/luogo (fallback finale)
      titolo:             nuovoRecord.titolo          || null,
      apparecchiatura:    nuovoRecord.apparecchiatura || null,
      cliente:            clienteNome,
      indirizzo:          nuovoRecord.indirizzo       || null,
      rdi:                nuovoRecord.rdi             || null,
      notes:              nuovoRecord.descrizione     || null,
      // Mappa priorità TBP → STM (low / normal / high / urgent)
      priority:           nuovoRecord.priorita === 'alta'  ? 'high' :
                          nuovoRecord.priorita === 'bassa' ? 'low'  : 'normal',
      // Data pianificata in formato YYYY-MM-DD
      due_date:           nuovoRecord.dataPianificata
                            ? String(nuovoRecord.dataPianificata).split('T')[0]
                            : null,
      gestionale_id:      nuovoRecord.id ? parseInt(nuovoRecord.id) : null,
    };

    // Chiamata asincrona fire-and-forget: non blocca la risposta al client
    fetch(`${stmUrl}/api/v1/external/create-assignment`, {
      method:  'POST',
      headers: {
        'Content-Type': 'application/json',
        'X-STM-API-Key': stmKey,          // header di autenticazione
      },
      body: JSON.stringify(stmPayload),
    })
    .then(resp => resp.json().then(d => {
      if (resp.ok) {
        // Successo — logAction è la funzione di log già usata nel progetto
        logAction('STM_SYNC_OK', req.user.username,
          `Assignment STM creato: ${d.assignment_uuid} -> tecnico: ${tecnicoNuovo}`,
          req.ip, req.user.ruolo);
      } else {
        logAction('STM_SYNC_WARN', req.user.username,
          `STM ha risposto con errore: ${JSON.stringify(d)}`,
          req.ip, req.user.ruolo);
      }
    }))
    .catch(err => {
      logAction('STM_SYNC_ERROR', req.user.username,
        `Impossibile contattare STM: ${err.message}`,
        req.ip, req.user.ruolo);
    });
  }
}
// --- FINE HOOK STM ---------------------------------------------------
```

> **Nota:** `fetch` è disponibile nativamente in Node.js 18+.  
> Se la versione di Node è inferiore, usare `node-fetch` (`import fetch from 'node-fetch'`).

---

## 📦 Payload JSON inviato a STM

| Campo | Tipo | Descrizione |
|---|---|---|
| `assigned_to` | `string` **required** | Username del tecnico in STM (deve corrispondere esattamente) |
| `serial_number` | `string` | Matricola/numero di serie del dispositivo |
| `device_description` | `string` | Descrizione dispositivo (usato se serial_number non trova nulla) |
| `destination_name` | `string` | Nome sede/destinazione (usato se il device non viene trovato) |
| `titolo` | `string` | Titolo dell'intervento |
| `apparecchiatura` | `string` | Nome apparecchiatura |
| `cliente` | `string` | Nome cliente |
| `indirizzo` | `string` | Indirizzo/luogo intervento |
| `rdi` | `string` | Numero RDI / riferimento documento |
| `notes` | `string` | Note aggiuntive |
| `priority` | `string` | `low` / `normal` / `high` / `urgent` |
| `due_date` | `string` | Data scadenza in formato `YYYY-MM-DD` |
| `gestionale_id` | `integer` | ID record in TechBusiness_PRO (per tracciabilità) |

### Esempio payload:
```json
{
  "assigned_to": "mario.rossi",
  "serial_number": "SN-12345",
  "device_description": "Monitor Multiparametrico",
  "destination_name": null,
  "titolo": "Verifica periodica annuale",
  "apparecchiatura": "Monitor Multiparametrico",
  "cliente": "Ospedale San Giovanni",
  "indirizzo": "Via Roma 1, Milano",
  "rdi": "RDI-2026-0042",
  "notes": "Portare adattatore BNC",
  "priority": "high",
  "due_date": "2026-06-15",
  "gestionale_id": 1234
}
```

---

## ✅ Risposta dell'endpoint STM

### Successo (HTTP 200):
```json
{
  "status": "ok",
  "assignment_uuid": "3fa85f64-5717-4562-b3fc-2c963f66afa6"
}
```

### Errori possibili:

| Codice HTTP | Significato |
|---|---|
| `401` | API Key mancante o errata |
| `404` | Tecnico non trovato in STM **oppure** nessun dispositivo/sede trovata |
| `503` | STM non configurato (variabile `STM_EXTERNAL_API_KEY` mancante) |
| `500` | Errore interno STM |

> La chiamata è **fire-and-forget**: TechBusiness_PRO non aspetta la risposta prima di
> inviare il risultato al browser. Gli errori vengono solo registrati nel log interno.

---

## 🔍 Come STM fa il match con i propri dati

STM cerca il dispositivo in questo ordine di priorità:

1. **`serial_number`** → cerca nella tabella `devices` per `serial_number` (ILIKE, case-insensitive)
2. **`device_description`** → cerca nella tabella `devices` per `description` (ILIKE, ricerca parziale)
3. **`destination_name`** → cerca nella tabella `destinations` per `name` (ILIKE, ricerca parziale)

Se nessun match viene trovato, l'endpoint risponde `404` e non crea l'assignment.

---

## ⚠️ Requisito importante: corrispondenza username tecnico

Il valore di `tecnicoPianificato` in TechBusiness_PRO **deve corrispondere esattamente**
allo `username` del tecnico in STM (case-sensitive).

Esempi:
- ✅ `"mario.rossi"` in TBP → `"mario.rossi"` in STM → **funziona**
- ❌ `"Mario Rossi"` in TBP → `"mario.rossi"` in STM → **errore 404**

Se i nomi non corrispondono, sarà necessario concordare una mappatura o normalizzare
il campo prima di inviarlo.

---

## 🧪 Come testare l'integrazione

### Test manuale con curl (dalla macchina server):
```bash
curl -X POST http://127.0.0.1:8000/api/v1/external/create-assignment \
  -H "Content-Type: application/json" \
  -H "X-STM-API-Key: INSERIRE_QUI_LA_CHIAVE_SEGRETA" \
  -d '{
    "assigned_to": "nome.tecnico",
    "serial_number": "SN-TEST-001",
    "titolo": "Test integrazione",
    "priority": "normal"
  }'
```

### Risposta attesa se tutto funziona:
```json
{"status": "ok", "assignment_uuid": "...uuid generato..."}
```

### Risposta se la chiave è sbagliata:
```json
{"detail": "API Key non valida"}
```

---

## 📋 Checklist per il programmatore

- [ ] Aggiungere `STM_URL=http://127.0.0.1:8000` nel file `.env.server`
- [ ] Aggiungere `STM_WEBHOOK_KEY=<chiave_concordata>` nel file `.env.server`
- [ ] Inserire il blocco di codice nel PUT handler di `interventi_extra`
- [ ] Verificare che `fetch` sia disponibile (Node.js 18+) o aggiungere `node-fetch`
- [ ] Concordare con il gestore STM il valore della `STM_EXTERNAL_API_KEY`
- [ ] Verificare che i nomi utente tecnici corrispondano tra i due sistemi
- [ ] Testare con curl prima di mettere in produzione
- [ ] Riavviare il server Node.js dopo aver modificato le variabili `.env`

---

## 📞 Contatto per chiarimenti

Per domande sulla struttura dell'endpoint STM o sulla configurazione della chiave API,
contattare il gestore dell'applicazione STM.
