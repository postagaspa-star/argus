# Argus — contratto tra i pezzi (v1)

Prima si cambia questo file, poi il codice. Le regole di comportamento stanno in `regole.md`.

## 0. I pezzi

```
NAS (Docker, progetto "argus", cartella /volume1/docker/Argus-NAS)
  argus          Python 3.12, FastAPI, porta 8700 (LAN). Cervello: telecamere, visione, regole,
                 diario, registro, coda delle foto dubbie, voce, prese.
  argus-go2rtc   go2rtc: flussi delle telecamere (RTSP) + altoparlante delle Tapo (ritorno audio).
  usa:           sol-decisore:8300 (rete esterna sol-rete)  -> POST /decidi
                 lectio-voci:8000  (rete esterna lectio_default) -> POST /voce
                 Home Assistant (facoltativo, http://<nas>:8123) -> prese smart

PC (Windows, C# .NET 8, cartella C:\Program Files\Argus, dati in C:\ProgramData\Argus,
    modello in D:\Argus\modelli se D: ha spazio, altrimenti C:\ProgramData\Argus\modelli)
  Argus.Guardiano   servizio di Windows (LocalSystem): avvia e riapre Argus.Agente nella sessione
                    dell'utente, sblocco d'emergenza.
  Argus.Agente      programma dell'utente: legge la finestra in primo piano e il dominio, copre,
                    terminale (WebView2), webcam, motore del modello per le foto dubbie.
  Argus.Sblocco     piccolo programma con manifest requireAdministrator: sblocco d'emergenza.
```

Lingua: nomi di dominio in italiano (quota, pausa, diario, copertura...), tecnica in inglese va bene.
Tutti i testi per lo studente in italiano semplice, senza gergo, senza emoji.

## 1. Autenticazione

- Ogni richiesta PC → NAS ha `Authorization: Bearer <token>`. Il token è generato sul NAS al primo
  avvio (`/data/token-pc.txt`, 32 byte casuali in esadecimale) e scritto dall'installatore in
  `C:\ProgramData\Argus\config.json` (leggibile solo da SYSTEM e Administrators).
- Token sbagliato o mancante: `401 {"errore": "...", "codice": "token"}`.
- **Secondo segreto, solo per lo sblocco**: lo genera **l'installatore del PC** (che gira come
  amministratore) e lo scrive in `config.json` (campo `segreto_sblocco`); nessuno lo vede, nemmeno chi
  gestisce il NAS. L'installatore lo registra sul NAS con `POST /api/pc/registra-sblocco
  {"segreto": "<64 caratteri esadecimali>"}` (token del PC): il NAS lo salva in `/data/token-sblocco.txt`
  **solo se non ce n'è già uno** (`200`), altrimenti `409 {"codice": "sblocco_gia_registrato"}`.
  Per rifare l'installazione si cancella quel file sul NAS a mano. Senza segreto registrato nessuno
  sblocco è possibile. Lo leggono SOLO Argus.Sblocco (che gira come amministratore) e il guardiano;
  **mai passato all'agente**. L'evento
  `sblocco_emergenza` vale solo con l'intestazione `X-Argus-Sblocco: <segreto>`; senza, `403
  {"codice": "sblocco"}`.
- Errori sempre nella forma `{"errore": "frase in italiano", "codice": "slug"}`.

## 2. Orari

- Il NAS è l'orologio che conta (fuso Europe/Rome). Ogni risposta ha `ora_server` (ISO 8601 con offset).
- Il PC manda `ts` (suo orologio) solo come informazione.

## 3. PC → NAS

### GET /api/salute (senza token)
`{"ok": true, "versione": "1.0.0", "telecamere": {"camera": "ok"|"assente"|"errore", ...},
  "decisore": "ok"|"assente", "voci": "ok"|"assente"}`

### GET /api/pc/stato
Il PC lo chiede ogni 2 secondi.
```json
{
  "ora_server": "2026-11-09T15:20:00+01:00",
  "modalita": "studio",              // libero | studio | lavoro | inattivo
  "liste_versione": 7,               // se cambia, il PC rilegge /api/pc/liste
  "quota": {"fatti": 25, "totale": 60, "sospeso": 4, "aggiunte": 6,
            "pausa_disponibile": 10, "fine_prevista": "16:05"},
  "classe_adesso": "studio",         // studio|lavoro|neutro|distrazione|imbroglio|sospeso|nessuna
  "comando_attivo": {"tipo": "lv", "fino": "16:25"} ,   // oppure null
  "verdetti": {"<chiave>": "studio"}, // giudizi sui titoli: chiave = sha1(dominio+"|"+titolo) in esadecimale,
                                      // sui valori ESATTI del campione. Contiene SEMPRE i verdetti delle
                                      // chiavi viste nei campioni degli ultimi 10 minuti, più i 300 più recenti.
  "messaggio_copertura": "Adesso è tempo di studio. Mancano 35 minuti.",
  "sblocco_fino": null,              // ISO se c'è uno sblocco d'emergenza attivo (lo manda il PC)
  "quota_fatta_oggi": false
}
```

### GET /api/pc/liste
```json
{
  "versione": 7,
  "sempre":  {"programmi": ["explorer.exe", "..."], "siti": []},
  "studio":  {"programmi": ["soffice.exe", "..."], "siti": ["wikipedia.org", "..."]},
  "lavoro":  {"programmi": ["claude.exe", "..."], "siti": ["github.com", "..."]},
  "da_giudicare": ["youtube.com", "claude.ai", "chatgpt.com", "gemini.google.com", "grok.com",
                   "copilot.microsoft.com"],
  "mai":     {"programmi": ["steam.exe", "..."], "siti": ["instagram.com", "..."]},
  "browser": ["chrome.exe", "msedge.exe", "firefox.exe", "brave.exe"]
}
```
Regole di confronto (uguali sul NAS e sul PC):
- programma: nome dell'eseguibile minuscolo, uguaglianza esatta. Un nome in lista senza ".exe"
  (per esempio "wisper ufficio") vale anche come prefisso del nome del file senza estensione.
- sito: dominio della barra minuscolo; vale se è uguale o finisce con "." + voce della lista.
  "localhost", "127.0.0.1" e "192.168." sono casi speciali (prefisso per gli IP).
- "mai" vince su tutto.
- browser: permesso solo se il dominio è permesso nella modalità; senza dominio leggibile (pagina
  nuova, impostazioni del browser) è permesso per 20 secondi, poi coperto.

### POST /api/pc/attivita
Ogni 5 secondi, gli ultimi campioni (uno al secondo, al massimo 30 per richiesta).
```json
{"campioni": [
  {"ts": "...", "processo": "chrome.exe", "titolo": "Rivoluzione francese - Wikipedia",
   "dominio": "it.wikipedia.org", "permesso": true, "coperto": false,
   "inattivo_secondi": 3, "audio": ["lectio.exe"], "schermo_bloccato": false,
   "pactum_copre": false}
]}
```
- `titolo` si manda **solo** per i siti da giudicare e per i programmi delle liste studio/lavoro
  (serve al diario); per tutto il resto `null`.
- `processo` è il nome dell'eseguibile minuscolo **solo se il PC l'ha riconosciuto** (firma +
  nome originale, oppure percorso in `percorsi_fidati`). Un programma che ha il nome giusto ma non
  passa il riconoscimento arriva come `"non_riconosciuto:nome.exe"` (anche dentro `audio`): il NAS
  lo conta sempre come `altro`, mai come studio, lavoro, browser o audio di Lectio.
- Risposta: `{"ok": true}`.

### POST /api/pc/comando
`{"testo": "ps m: bagno & t: 10"}` →
`{"ok": true, "risposta": "Pausa fino alle 15:52.", "chiede_foto": null}`
- Per `lb`/`qd`/`vs`/`tf`: `"chiede_foto": {"tipo": "lb", "nome": "storia", "scatti": 6,
  "consiglio": "Copertina e 2-3 pagine aperte."}` → il terminale apre la webcam o accetta file
  trascinati, poi manda `POST /api/pc/foto`.
- Testo non capito: `ok: false` e `risposta` con l'esempio giusto.

### POST /api/pc/foto (multipart)
Campi: `tipo` (lb|qd|vs|tf), `nome` (per lb/qd), `immagini` (1-20 file JPEG/PNG, max 8 MB l'uno).
Risposta: `{"ok": true, "risposta": "«storia» salvato (6 foto)."}`.

### GET /api/pc/lavori
Il PC lo chiede ogni 15 secondi **solo** quando può lavorare (regole 10). Risposta `204` se non c'è
niente, altrimenti:
```json
{"id": "l-123", "immagine_jpeg_base64": "...", "contesto": "Camera, sul divano, 15:41.",
 "domande": [{"id": "in_mano", "domanda": "Cosa tiene in mano la persona?",
              "opzioni": ["telefono", "tablet", "libro", "quaderno", "controller", "niente",
                          "non_si_capisce"]},
             {"id": "schermo_acceso", "domanda": "C'è uno schermo acceso davanti alla persona?",
              "opzioni": ["si", "no", "non_si_capisce"]}],
 "scade": "2026-11-09T23:59:59+01:00"}
```
Il lavoro resta "preso" per 3 minuti: se il PC non risponde, torna in coda.

### POST /api/pc/lavori/{id}
`{"risposte": {"in_mano": "telefono", "schermo_acceso": "si"}, "millisecondi": 41200,
  "modello": "Qwen3.5-9B-Q4_K_M"}` → `{"ok": true}`. Un'opzione fuori elenco = `422`.

### POST /api/pc/evento
`{"tipo": "agente_avviato"|"agente_riaperto"|"agente_chiuso"|"agente_bloccato"|"sblocco_emergenza"
  |"pactum_copre"|"nas_irraggiungibile", "dettagli": {...}, "ts": "..."}` → `{"ok": true}`.
`agente_bloccato`: `{"pid": 1234, "secondi": 20}`, lo manda il guardiano quando l'agente non dà
segni di vita per 20 secondi e viene chiuso e riaperto. Il NAS lo annota nel registro.
Un tipo fuori elenco = `422 evento_sconosciuto`.
`sblocco_emergenza`: `{"ore": 4}` (intero 0-48; 0 = togli lo sblocco) → il NAS calcola `fino` col SUO
orologio e mette `modalita: libero` fino a quell'ora. `ore` mancante, non intero o fuori 0-48 = `422`.
Un eventuale `fino` mandato dal PC si ignora.

## 4. NAS → servizi

### SemIf (sol-decisore)
`POST http://sol-decisore:8300/decidi`
```json
{"stato": "<diario a parole e contesto, italiano>",
 "domande": [{"id": "pensiero", "domanda": "Il tempo in sospeso era studio?",
              "opzioni": [{"id": "studio", "descrizione": "..."},
                          {"id": "non_studio", "descrizione": "..."},
                          {"id": "non_si_capisce", "descrizione": "..."}]}],
 "scadenza_secondi": 120}
```
→ `{"risposte": {"pensiero": {"scelta": "studio", "probabilita": {...}, "massa_opzioni": 0.93}},
    "millisecondi": 5400}`
- Al massimo 8 domande e 16 opzioni per richiesta. Una richiesta alla volta (il decisore è condiviso
  con Sol: se risponde 503 `decisore_non_disponibile`, si riprova dopo 30 secondi).
- Si accetta la scelta solo se `probabilita[scelta] >= 0.6` e `massa_opzioni >= 0.5`; altrimenti
  vale `non_si_capisce`.

### Voci (lectio-voci)
`POST http://lectio-voci:8000/voce {"motore": "supertonic", "testo": "..."}` → `audio/wav`.
Le frasi fisse si preparano una volta e si tengono in cache su disco (`/data/voce/`).

### Altoparlante della Tapo (go2rtc)
L'audio si manda alla telecamera con l'API di go2rtc (ritorno audio verso il flusso della camera).
Se non funziona, la frase va al PC: `GET /api/pc/stato` ha in più `"di_voce": {"id": "...",
"url": "/api/pc/voce/<id>.wav"}` e il PC la riproduce una volta.

### Prese (Home Assistant, facoltativo)
`POST http://<ha>:8123/api/services/switch/turn_off {"entity_id": "switch.tv"}` con token in `.env`.
Se non è configurato, niente prese.

## 5. Dati sul NAS

- SQLite in `/data/argus.db`: giorni (quota, riporto, aggiunte), minuti classificati, episodi
  (distrazione, imbroglio, pause, dm, lv, sospesi), diario (una riga ogni 10 secondi mentre è attivo),
  registro eventi, liste con le modifiche in attesa (aggiunte che valgono dopo 4 giorni), lavori
  della coda, riconoscimento (libri, quaderni, viso, telefono: vettori, non foto).
- Le foto registrate (`lb`, `qd`, `vs`, `tf`) servono a calcolare i vettori; si tengono in
  `/data/registrati/` per poter ricalcolare se cambia il modello.
- Le immagini delle telecamere **non si salvano**, tranne i ritagli dei lavori in coda, cancellati
  appena giudicati o a mezzanotte.
- Il diario si tiene 30 giorni.

## 6. Configurazione (NAS, `/data/config.json` + `.env`)

```json
{
  "telecamere": [
    {"id": "camera", "stanza": "camera", "rtsp_principale": "rtsp://...", "rtsp_secondario": "rtsp://...",
     "onvif": {"host": "...", "porta": 2020, "utente": "...", "password_env": "TAPO_CAMERA_PASSWORD"}},
    {"id": "salotto", "stanza": "salotto e cucina", "...": "..."}
  ],
  "sabato_scuola": false,
  "patrono": null,
  "decisore_url": "http://sol-decisore:8300",
  "voci_url": "http://lectio-voci:8000",
  "voce": "supertonic",
  "home_assistant": null,
  "prese": [],
  "liste_extra": {"lavoro": {"programmi": [], "siti": []}, "studio": {"programmi": [], "siti": []}}
}
```
`liste_extra` aggiunge voci locali (per esempio i siti dei clienti) che non devono stare nel repo
pubblico; valgono subito, perché le scrive solo chi gestisce il NAS.

Configurazione del PC (`C:\ProgramData\Argus\config.json`, leggibile e scrivibile solo da SYSTEM e
Administrators): indirizzo del NAS, `token`, `segreto_sblocco` (non passato all'agente),
`utente_controllato`, `tasto_terminale`, `motore` (percorsi del modello), `percorsi_fidati` (percorsi
completi di programmi senza firma fatti in casa che valgono anche se stanno in cartelle dello studente).
Senza telecamere configurate Argus è **inattivo** (`modalita: inattivo`): non conta niente, non
punisce, non copre. Così il NAS può girare prima che arrivino le telecamere.
