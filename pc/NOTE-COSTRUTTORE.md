# Argus PC - note del costruttore

Scelte fatte dove `docs/regole.md` e `docs/contratto.md` non dicevano abbastanza, cosa è stato provato
davvero, cosa si può provare solo con l'installazione vera, limiti noti. Data: 07/11/2026.

## 1. Com'è fatto

| Progetto | Tipo | Cosa contiene |
|---|---|---|
| `Argus.Nucleo` | libreria, nessuna finestra | tutta la logica provabile: liste (`Liste.cs`), calendario Veneto (`Calendario.cs`), modalità e regola "senza NAS" (`Modalita.cs`), giudizio della finestra e chiave dei verdetti (`Giudice.cs`), sblocco (`Sblocco.cs`), condizioni e domande del modello (`Condizioni.cs`, `Modello.cs`), motore e lavori (`Motore.cs`), client del NAS (`ClientNas.cs`), testi e comandi locali (`Terminale.cs`), riavvii del guardiano (`Guardia.cs`), firma digitale (`Firma.cs`), programmi riconosciuti dal percorso (`Riconoscimento.cs`), avvio protetto e battito dell'agente (`AvvioProtetto.cs`) |
| `Argus.Prove` | xUnit | 312 prove (310 passano, 2 col motore vero partono solo con `ARGUS_PROVA_MOTORE=1`) |
| `Argus.Agente` | WinForms (+ WPF solo per UI Automation) | sensore, giri verso il NAS, copertura, terminale WebView2 (`ui/terminale.html`), voce, motore |
| `Argus.Guardiano` | servizio Windows (LocalSystem) | avvia/riapre l'agente nella sessione dello studente, eventi, sblocco |
| `Argus.Sblocco` | WinForms, `requireAdministrator` | sblocco d'emergenza 1-48 ore |

Compilazione fuori da OneDrive (`Directory.Build.props` → `%USERPROFILE%\argus-build\pc`). Pacchetto
a cartella (self-contained win-x64, NON single-file): `crea-pacchetto.ps1` → 275 file, 147 MB.

## 2. Letture delle regole (dove c'era un buco, la più prudente)

### Configurazione e token
- Il contratto vuole `config.json` leggibile solo da SYSTEM e Administrators, ma l'agente gira come
  studente. **Il guardiano gli passa la configurazione sull'ingresso standard** (una conduttura privata,
  non la riga di comando, che altri processi possono leggere). Senza configurazione l'agente gira lo
  stesso: regola "senza NAS" e liste di partenza.
- **Il segreto dello sblocco non arriva mai all'agente** (revisione B7): il guardiano manda
  `ConfigArgus.PerAgente(istanza)`, una copia senza `segreto_sblocco` e con `istanza` (16 byte casuali
  nuovi a ogni avvio, vedi B6). C'è una prova che lo controlla.
- Il token sta nella memoria dell'agente. Dalla revisione B6 lo studente non può leggerla (niente
  PROCESS_VM_READ, niente debugger: provato); resta possibile solo con trucchi che fanno girare codice
  dentro l'agente (vedi i limiti). Il NAS deve comunque trattare quello che arriva dal PC come
  "dichiarato dal PC", non come prova.

### Regola "senza NAS" (regole 12)
- NAS "muto" = nessuna risposta da più di 2 minuti, **oppure mai risposto da quando l'agente è partito**
  (altrimenti chiudere e riaprire l'agente regalerebbe 2 minuti ogni volta), oppure orologio del PC
  tornato indietro di più di 5 minuti rispetto all'ultima risposta.
- "Quota fatta oggi" conta solo se l'ultima risposta del NAS era dello stesso giorno (ora italiana,
  presa da `ora_server`).
- Fuori dalla finestra (giorno non di scuola, o **prima delle 11:00**: revisione B8, prima erano le 13:00)
  col NAS muto il PC è **libero**: la regola parla solo di quella finestra.
- Giorni di scuola: tabella 2026/27 dalle regole 13 (10/09/2026-08/06/2027, vacanze comprese); per gli
  anni senza tabella una regola generica (10/09-08/06, feste nazionali, 24/12-06/01, da giovedì santo a
  martedì dopo Pasqua). Sabato e patrono dalla configurazione (`sabato_scuola`, `patrono`).
- Liste: finché il NAS non ha mai risposto valgono le liste di partenza delle regole 14 (versione 0).
  Le liste ricevute stanno solo in memoria: se l'agente riparte col NAS spento, si torna a quelle di
  partenza.

### Giudizio della finestra (regole 12 e 14)
- "mai" vince su tutto; i giochi lanciati da Steam contano come "mai" (riconosciuti dalla cartella
  `steam`/`steamapps`).
- I programmi di Argus sono sempre permessi, **ma solo i tre col nome esatto dentro
  `C:\Program Files\Argus`** (revisione B5): un `argusgioco.exe` o un `Argus.Agente.exe` copiato altrove no.
- Superfici di Windows (menu Start, ricerca, barra, Alt+Tab, Win+Tab, schermata di blocco, UAC...):
  non sono "la cosa in primo piano". Vale l'ultima finestra vera: aprire Start non scopre il video sotto
  e non fa lampeggiare la copertura.
- `applicationframehost.exe` (le app moderne) permesso solo se il titolo è Calcolatrice o Strumento di
  cattura; il resto si copre (non si sa che app sia).
- Browser senza dominio leggibile (scheda nuova, impostazioni, cursore nella barra): 20 secondi **per
  finestra**, che non ripartono cambiando finestra o scheda.
- Siti da giudicare: 20 secondi **per pagina** (per chiave). Chiave = `sha1(dominio + "|" + titolo)` in
  esadecimale minuscolo, testo in UTF-8, con il titolo **ripulito** dal pezzo del browser
  (" - Google Chrome", " - Personale - Microsoft Edge", " e altre 2 schede", "(3) " davanti...). Il NAS
  deve calcolare la chiave dagli stessi `dominio` e `titolo` che riceve nel campione.
- Verdetto `lavoro` vale solo durante `lv`; in studio quella pagina si copre. Un verdetto diverso da
  studio/lavoro copre subito.
- **"www." davanti al sito non conta**: Chrome lo nasconde nella barra (provato: su www.youtube.com
  si legge "youtube.com"), Edge e Firefox no. Il PC manda il sito senza "www." e una voce di lista
  "www.youtube.com" vale come "youtube.com". Così chiave e liste sono uguali in ogni browser.
- Voci di lista: `youtube.com` vale anche per i sottodomini (`m.youtube.com`), `web.whatsapp.com` no per
  `whatsapp.com`; `192.168.` (con il punto finale) è un prefisso solo per gli indirizzi IP; `localhost` e
  gli IP solo uguali.
- Titolo nel campione: solo per i siti da giudicare e per i programmi e i siti delle liste studio/lavoro
  (contratto). Il titolo si legge solo quando serve.

### Programmi riconosciuti dal percorso (revisione B5)
- Prima un programma valeva per il nome del file: bastava rinominare un gioco in `claude.exe`. Adesso
  (`RiconoscitoreProgrammi`, in quest'ordine):
  1. programmi di Argus: nome esatto in `C:\Program Files\Argus`;
  2. percorso completo in `percorsi_fidati` di `config.json` (maiuscole e barre indifferenti);
  3. dentro `Program Files`, `Program Files (x86)` o `Windows` **e lo studente non può scrivere né il file
     né nella sua cartella**: basta il nome;
  4. altrove (o in una cartella di sistema dove lo studente può scrivere, come quella di Steam): vale solo
     con una **firma Authenticode valida** e allora conta il **nome originale** scritto dentro il file
     (`OriginalFilename`, senza ".exe" e maiuscole), non il nome del file;
  5. tutto il resto è **non riconosciuto**: non è un browser, non è una superficie di Windows, non vale per
     nessuna lista, quindi in studio si copre. Il NAS lo riceve come `processo: "non_riconosciuto:nome.exe"`
     (vedi Campioni). Un nome in "mai" vale comunque, anche senza firma (prudente).
- "Lo studente può scrivere": `AccessCheck` con il token dell'agente (che è lo studente) sul file e sulla
  cartella; nel dubbio "sì".
- Firma "valida": WinVerifyTrust **senza rete** e in più la radice della catena deve stare nei certificati
  del computer (LocalMachine Root/AuthRoot): un certificato aggiunto dallo studente nei suoi non basta.
  I file di Windows firmati solo nei cataloghi (notepad, cmd, powershell) qui risultano "senza firma":
  valgono perché stanno in `Windows`; una loro copia in Download no.
- Firma, nome originale e permessi si ricordano per percorso + data di modifica + dimensione (al massimo
  500 voci): si ricalcolano solo se il file cambia.
- Il motore (`llama-server.exe`) vale solo con la firma "Element Labs" controllata nello stesso modo.

**Programmi veri di questo PC** (prova `Argus.Agente.exe --prova-programmi <elenco> <esito>`, 07/11):

| Programma | Percorso | Come passa |
|---|---|---|
| Claude (app) | `C:\Program Files\WindowsApps\Claude_...\app\claude.exe` | cartella protetta |
| Edge, Chrome, Firefox, Brave | `C:\Program Files (x86)\Microsoft\Edge\...`, `C:\Program Files\Google\Chrome\...`, `C:\Program Files\Mozilla Firefox\...`, `C:\Program Files\BraveSoftware\...` | cartella protetta |
| Android Studio | `C:\Program Files\Android\Android Studio\bin\studio64.exe` | cartella protetta |
| Git (git-bash, bash, mintty, git-gui, wish) | `C:\Program Files\Git\...` | cartella protetta |
| Node | `C:\Program Files\nodejs\node.exe` | cartella protetta |
| UGREEN NAS | `C:\Program Files\UGREEN NAS\UGREEN NAS.exe` | cartella protetta |
| LibreOffice, PDFelement, Google Drive | `C:\Program Files\...` | cartella protetta |
| Python | `%LOCALAPPDATA%\Programs\Python\Python314\python.exe` e `pythonw.exe` | **firma** (nome originale python.exe) |
| Steam | `C:\Program Files (x86)\Steam\steam.exe` (cartella scrivibile dagli utenti) | firma → `steam.exe` → **mai** |
| LM Studio | `%LOCALAPPDATA%\Programs\Bionic\Bionic.exe` | firmato ma **senza nome originale** → `percorsi_fidati`; e in lista c'è `lm studio.exe`: va aggiunto **`bionic.exe`** alla lista lavoro (sul NAS) |
| Ollama | `%LOCALAPPDATA%\Programs\Ollama\ollama app.exe` | firmato senza nome originale → `percorsi_fidati` |
| Lectio | `%USERPROFILE%\Lectio\Lectio.exe` | senza firma → `percorsi_fidati` |
| Wisper Ufficio | `%LOCALAPPDATA%\Programs\WisperUfficio\WisperUfficio.exe` | senza firma → `percorsi_fidati`; e la voce di lista `wisper ufficio` (con lo spazio) non vale per `wisperufficio.exe`: va corretta in `wisperufficio.exe` |
| Claude Code (riga di comando) | `%USERPROFILE%\.local\bin\claude.exe` | firmato senza nome originale → `percorsi_fidati` solo se serve: gira dentro un terminale, e in primo piano c'è il terminale (protetto) |
| Pactum | quello installato (la voce di avvio punta a `%USERPROFILE%\Pactum\Pactum.exe`, che adesso non c'è; la copia di sviluppo è senza firma) | senza firma → `percorsi_fidati`, altrimenti Argus non riconosce le coperture di Pactum |
| Chromium portatile (Playwright) | `%LOCALAPPDATA%\ms-playwright\chromium-1223\chrome-win64\chrome.exe` | senza firma → **non riconosciuto**: non vale come browser (giusto) |
| Grok Bot | `%LOCALAPPDATA%\Programs\Grok Bot\Grok Bot.exe` | firmato senza nome originale → non riconosciuto |

Quindi su questo PC: `-PercorsiFidati` con LM Studio, Ollama, Lectio, Wisper Ufficio e Pactum (e Claude
Code se serve), **scritti per intero con il profilo dello studente** (`C:\Users\<studente>\...`: lo
script gira da amministratore, `%LOCALAPPDATA%` lì sarebbe quello dell'amministratore). Meglio ancora:
installare i programmi fatti in casa in `C:\Program Files`, così bastano i nomi.

### Copertura
- Compare dopo **1 secondo** continuo di "da coprire" (niente lampi nei passaggi tra finestre) e sparisce
  subito quando torna una cosa permessa.
- Quando compare prende il primo piano (così la tastiera non scrive nella cosa coperta), e lo riprende
  quando cambia la finestra coperta o ogni 2 secondi; resta sopra a tutto ogni mezzo secondo; si rifà se
  qualcuno la nasconde, la rende trasparente o cambiano gli schermi. Non chiude, non minimizza e non
  tocca le altre app, niente hook di tastiera.
- **Tasto del terminale: Ctrl+Alt+T** (decisione del coordinatore, 07/11). Le regole dicono
  Ctrl+Alt+Spazio, ma su questo PC quella combinazione è già presa da un altro programma (probabilmente
  Claude Desktop), mentre Ctrl+Alt+T è libera. Si cambia in `config.json` con `"tasto_terminale"`
  (esempi: "Ctrl+Alt+A", "Ctrl+Maiusc+Spazio", "Alt+F9"; serve almeno Ctrl, Alt o Win più una lettera,
  una cifra, F1-F24 o Spazio) o con `installa.ps1 -TastoTerminale`. Se il valore non va bene l'agente usa
  Ctrl+Alt+T e lo scrive nel registro. La copertura scrive il tasto vero ("...apri il terminale:
  Ctrl+Alt+T"). `docs\regole.md` dice ancora Ctrl+Alt+Spazio: lo aggiorna il coordinatore.
- **Se anche quel tasto è già preso da un altro programma**: senza hook di tastiera non si può prenderlo
  lo stesso. Allora la copertura dice "Torna a una cosa permessa o apri il terminale: **fai clic qui.**"
  invece di promettere un tasto che non va; un clic sulla copertura apre sempre il terminale; nel menu
  Start c'è "Argus - terminale" (`Argus.Agente.exe --terminale`, che avvisa la copia accesa con un evento
  con nome). L'agente riprova a prendere la combinazione ogni 30 secondi.
- Task Manager, Impostazioni, Pannello di controllo: non sono in nessuna lista, quindi in studio si
  coprono. Dalla revisione B6 lo studente **non può chiudere né sospendere l'agente** (vedi Guardiano).

### Pactum
- "Pactum copre" = una finestra di `pactum.exe` **riconosciuto dal percorso** (B5), visibile, non
  minimizzata né nascosta, **non trasparente** (niente WS_EX_LAYERED/TRANSPARENT né regioni), sempre in
  primo piano, grande almeno il 90% di uno schermo. Allora la copertura di Argus si fa da parte; il campione ha
  `pactum_copre: true` e c'è l'evento `pactum_copre {attivo}` quando cambia.

### Eventi
- `agente_avviato`: prima apertura dopo l'accesso dello studente; `agente_riaperto`: ogni riapertura;
  `agente_chiuso {codice_uscita, minuti_acceso}`: chiusura non dovuta a uscita/spegnimento.
- `nas_irraggiungibile {dal, al, secondi}`: mandato quando il NAS torna, se era muto da più di 2 minuti.
- `sblocco_emergenza {ore}` (revisione B7: intero 0-48, niente più `fino`, lo calcola il NAS; `ore: 0` =
  togli lo sblocco), con l'intestazione **`X-Argus-Sblocco: <segreto_sblocco>`**: lo manda Argus.Sblocco
  subito; se il NAS non risponde lo manda il guardiano appena può (il file ricorda se è partito). Senza
  segreto in `config.json` nessuno dei due lo manda e lo dicono. `403` dal NAS = "segreto dello sblocco
  sbagliato o mancante".
- **`agente_bloccato {pid, secondi}`** (revisione B6): l'agente non batteva più e il guardiano l'ha
  chiuso e riaperto. **Il NAS e il contratto non lo conoscono ancora**: oggi il NAS risponde `422` e il
  guardiano lo butta (lo scrive nel registro). Va aggiunto a `EVENTI_PC` e al contratto (sezione 3).
- `ts` = orologio del PC, formato `2026-11-09T15:41:00.000+01:00`.

### Campioni e rete
- `processo` nel campione: il nome riconosciuto dal percorso (B5; per la firma, il nome originale). Un
  programma **non riconosciuto** va come **`"non_riconosciuto:nome.exe"`**: il NAS oggi giudica il
  campione dal nome (`pc_attivita.categoria`), e col nome nudo un gioco rinominato `claude.exe`
  passerebbe per lavoro anche lì. Il contratto non lo prevede: da decidere col NAS (aggiungere il
  prefisso al contratto, o un campo `riconosciuto: false`). Le voci `audio` seguono la stessa regola.
- Un campione al secondo, mandati ogni 5 secondi (al massimo 30). Se il NAS non risponde si tengono gli
  ultimi 30: un'assenza lunga non si ricostruisce dal PC.
- Stato ogni 2 secondi, liste quando cambia `liste_versione`, voce `di_voce` scaricata solo dallo stesso
  indirizzo del NAS e riprodotta una volta. Tempi massimi: 4 s (stato, attività, eventi), 10 s (comando,
  voce), 90 s (foto).
- Foto (`POST /api/pc/foto`): multipart con i nomi tra virgolette (`name="tipo"`, `name="immagini";
  filename="foto-1.jpg"`), 1-20 immagini, al massimo 8 MB l'una; le foto trascinate si ricomprimono in
  JPEG (lato lungo al massimo 2000 px).
- Comandi del terminale: li capisce il NAS. Solo se il NAS non risponde il PC risponde da sé ("Il NAS
  non risponde: riprova tra poco.", `aiuto` sì).

### Modello per le foto dubbie (regole 10)
- Condizioni, controllate ogni 5 secondi: PC alla corrente (un portatile a batteria no), almeno **8 GB
  di memoria libera** contando anche quella del motore acceso, processore degli **altri** programmi sotto
  il **50%** nell'ultimo minuto (serve un minuto di misure prima di partire). Tutto in configurazione
  (`motore.memoria_minima_gb`, `motore.cpu_massima_percento`).
- Motore: `llama-server.exe` dalla cartella più recente
  `%USERPROFILE%\.lmstudio\extensions\backends\llama.cpp-win-x86_64-avx2-*` dell'utente (versione
  letta dal nome), **solo se firmato "Element Labs"** (WinVerifyTrust, senza rete). LM Studio, i motori e le
  sue impostazioni non si toccano: si usa l'eseguibile così com'è. Argomenti: `-ngl 0` (solo CPU),
  `-np 1`, `-c 4096`, `-t` metà dei processori logici, `--reasoning off --no-webui --offline`, porta
  `127.0.0.1:8781`. Priorità bassa, legato all'agente con un Job Object (se l'agente muore, muore anche
  lui). Mai due copie: se la porta è occupata non parte.
- Risposta vincolata con `response_format` json_schema (un `enum` per domanda) e poi ricontrollata: una
  scelta fuori elenco diventa `non_si_capisce` se la domanda ce l'ha, altrimenti il lavoro non si
  risponde (torna in coda al NAS dopo 3 minuti) e questo PC non lo riprende.
- Tempi massimi: 300 s per caricare il modello, 170 s per una domanda (meno dei 3 minuti in cui il NAS
  tiene il lavoro "preso"). Spento dopo 5 minuti senza lavori o appena le condizioni non valgono più
  (anche a metà domanda). Dopo un errore del motore, 10 minuti di pausa.
- Modello e proiettore nella cartella scelta dall'installazione (`D:\Argus\modelli` o
  `C:\ProgramData\Argus\modelli`, vedi sotto); i percorsi completi sono in `config.json`
  (`motore.modello`, `motore.mmproj`; configurabili anche `motore.llama_server`, `motore.cartella_backends`).

### Guardiano e sblocco
- L'agente parte solo nella sessione della console attiva e solo se l'utente è `utente_controllato`
  (senza dominio e senza `@...`, maiuscole indifferenti). Se un'altra copia dell'agente è già nella
  sessione (non avviata dal guardiano, quindi senza token) la chiude prima di avviare la sua.
- **Agente protetto (revisione B6)**, `AvvioProtetto` nel Nucleo:
  - processo e thread principale nascono con un descrittore di sicurezza
    `D:P(A;;GA;;;SY)(A;;GA;;;BA)(A;;<pochi>;;;<SID dello studente>)(A;;RC;;;OW)`: allo studente solo
    attendere la fine, leggere le informazioni di base e i permessi; niente TERMINATE, SUSPEND_RESUME,
    VM_READ/WRITE/OPERATION, CREATE_THREAD, DUP_HANDLE, SET_INFORMATION, SET_QUOTA, WRITE_DAC,
    WRITE_OWNER, DELETE (sui thread: niente TERMINATE, SUSPEND, GET/SET_CONTEXT, SET_INFORMATION,
    IMPERSONATE, WRITE_DAC/OWNER). La voce OWNER RIGHTS (`OW`, solo READ_CONTROL) serve perché il
    proprietario (lo studente: il processo gira col suo token) altrimenti potrebbe sempre riscriversi i
    permessi;
  - i thread che l'agente crea dopo nascono coi permessi di serie dell'utente: l'agente stesso li rimette
    stretti ogni 5 secondi (prova vera: dopo 8 secondi **0 thread su 23** sospendibili dallo studente);
  - **eredita solo i due capi di conduttura** (ingresso con la configurazione, uscita per il battito) con
    `STARTUPINFOEX` + `PROC_THREAD_ATTRIBUTE_HANDLE_LIST`. Nota: Windows **vuole `bInheritHandles = TRUE`**
    quando si passa quell'elenco (con FALSE l'elenco non vale); è l'elenco che limita l'eredità a quei due
    handle. C'è una prova che un altro handle ereditabile del padre non arriva al figlio;
  - le condutture sono anonime (nome casuale, permessi di SYSTEM): nessun altro processo può aprirle per
    battere al posto dell'agente. Il contratto parlava di "named pipe con ACL": una conduttura anonima è
    una named pipe che nessuno può trovare, e risparmia il nome da proteggere;
  - **battito**: l'agente scrive un byte ogni 5 secondi sull'uscita standard, solo se negli ultimi 10
    secondi hanno girato sia il thread delle finestre sia il sensore. Il guardiano: nessun battito per
    **20 secondi** (il primo entro 60, per gli accessi lenti) → `TerminateProcess` con l'handle della
    creazione, evento `agente_bloccato`, riapertura;
  - **mutex**: avviato dal guardiano, il nome è `Local\Argus.Agente.<istanza>` (l'istanza arriva
    sull'ingresso standard, lo studente non la conosce): occupare `Local\Argus.Agente` non lo fa più
    uscire. Una copia sola la garantisce il guardiano;
  - un WM_QUIT mandato da un altro programma chiude l'agente con il **codice 5**; il ponte delle finestre e
    la finestra del tasto ignorano WM_CLOSE da fuori; l'evento del collegamento "Argus - terminale" se è
    già preso non blocca più l'avvio;
  - **pausa di 30 secondi** dopo 5 uscite in un minuto **solo se l'agente muore da solo entro 10 secondi
    dall'avvio** (o non parte); chiuso dal guardiano o con codice 5 o vissuto di più: sempre 1 secondo.
- La configurazione si rilegge quando cambia il file; senza `utente_controllato` il guardiano non avvia
  niente (lo scrive nel registro).
- Sblocco: file `sblocco.json` scritto da Argus.Sblocco (solo amministratori possono scriverlo),
  controllato dall'agente ogni 5 secondi e dal guardiano ogni 15. Uno sblocco che dura più di 48 ore o con
  date incoerenti non vale.

### Installazione
- Indirizzo del NAS: si accetta anche senza `http://` e senza porta (di serie 8700, dal contratto).
- Il token si chiede senza mostrarlo; se il NAS risponde, lo script controlla il token (`401` = si
  ferma).
- **Segreto dello sblocco (revisione B7, contratto sezione 1)**: alla prima installazione `installa.ps1`
  (che gira da amministratore) genera 32 byte con `RandomNumberGenerator` (64 caratteri esadecimali), li
  registra con `POST /api/pc/registra-sblocco {"segreto": ...}` e il token del PC, e li scrive in
  `config.json` come `segreto_sblocco`. Mai sullo schermo, mai nei registri, mai nell'indirizzo (solo nel
  corpo della richiesta). Tutto **prima di cambiare qualcosa**: se il NAS non risponde, se il token è
  sbagliato o se il NAS ne ha già uno (`409`: "Sul NAS c'è già un segreto di sblocco: va azzerato da chi
  gestisce il NAS, poi rilancia l'installazione.") lo script si ferma senza aver toccato niente.
  Registrato il segreto, lo scrive **subito** in `config.json` (cartella protetta prima): se
  l'installazione si fermasse più avanti, rilanciandola il segreto c'è già e non si registra di nuovo.
  In un aggiornamento con il segreto già in `config.json` non si rigenera e non si registra (e il NAS
  spento non ferma l'aggiornamento). `-NuovoSegretoSblocco`: solo per una reinstallazione voluta (prima
  si cancella `/data/token-sblocco.txt` sul NAS). `disinstalla.ps1` lo ricorda alla fine.
- **`config.json` non passa mai da "Users: lettura"**: si crea già con i suoi permessi (`FileStream` con
  `FileSecurity`, `CreateNew`) dopo aver cancellato quello vecchio (chi lo avesse aperto resta con il
  vecchio; se qualcuno lo rimette nel frattempo lo script si ferma). `Proteggi` non lo rimette più
  ereditato. Prima c'era un attimo, fra lo `/reset` e i permessi stretti, in cui lo studente poteva
  leggerlo.
- **`-PercorsiFidati`** (B5): percorsi completi di `.exe` (si ferma se no; avvisa se il file non c'è);
  senza l'opzione restano quelli dell'installazione di prima; `@()` li toglie.
- `C:\ProgramData\Argus`: proprietario Administrators, niente permessi ereditati, SYSTEM e
  Administrators tutto, Users solo lettura (l'agente deve leggere modello e sblocco). `config.json`: solo
  SYSTEM e Administrators. SID fissi, così va anche con Windows in italiano.
- **Cartella del modello** (decisione del coordinatore: su C: ci sono 6,6 GB liberi, su D: 377 GB):
  `-CartellaModelli`; di serie `D:\Argus\modelli` se D: è un disco fisso con almeno 8 GB liberi,
  altrimenti `C:\ProgramData\Argus\modelli`. Il resto di ProgramData resta su C:. In più, prudente: in un
  aggiornamento senza `-CartellaModelli`, se la cartella della configurazione di prima ha già i due file
  della dimensione giusta, il modello resta lì (niente secondo download da 6,5 GB). Una cartella scelta a
  mano deve essere un percorso completo su un disco fisso, non la radice, e nuova, vuota o con solo file
  del modello (i permessi si cambiano: non si rischia di toccare una cartella di altri).
- Permessi della cartella del modello come `C:\ProgramData\Argus` (proprietario Administrators, niente
  ereditati, SYSTEM e Administrators tutto, Users solo lettura). Se sta in `D:\Argus` e `D:\Argus` contiene
  solo lei, si protegge `D:\Argus` intera (nella radice di D: gli utenti di serie possono modificare).
- `config.json` ha sempre `motore.modello` e `motore.mmproj` con i percorsi completi, e
  `tasto_terminale`.
- Modello: si scarica solo se sul disco scelto c'è spazio (file mancanti + 1 GB di margine), con ripresa
  (`curl -C -`) e controllo sha256; se manca spazio Argus si installa lo stesso e lo dice.
- Disinstallazione: la cartella del modello si legge da `config.json`. Senza `-TogliModelli` resta; con
  `-TogliModelli` si tolgono solo i `*.gguf` (e i pezzi `.part`), poi la cartella se è rimasta vuota e
  `D:\Argus` se è vuota.
- Servizio `ArgusGuardiano`: automatico, si riavvia dopo 5 s, 5 s, 30 s se cade. Lo studente (account
  standard) non può fermarlo: i permessi di serie dei servizi non lo consentono agli utenti normali.
- In più rispetto alla richiesta: collegamenti nel menu Start "Argus - terminale" e "Argus - sblocco
  d'emergenza" (il primo serve quando il tasto del terminale è preso).

## 3. Cosa è stato provato davvero (su questo PC, 07/11/2026)

- **Compilazione** (da zero, `--no-incremental`): 5 progetti, 0 avvisi, 0 errori. **Prove: 310 passate, 2
  saltate** (quelle del motore vero, che partono a parte: ripassate anche dopo le revisioni B5-B8, 2 su 2,
  con la firma del motore controllata nel modo nuovo).
- **Motore vero** (`ARGUS_PROVA_MOTORE=1`) con il modello piccolo della stessa famiglia
  (Qwen3.5-0.8B Q4_K_M + mmproj, in `argus-build\modelli-prova`), llama-server di LM Studio 2.43.0 firmato
  Element Labs, i5-1235U, 6 thread: pronto in **2,5 s**, prima domanda con immagine **6,0 s** (434 token
  di prompt a 78 token/s), seconda **1,1 s**, memoria 1,2 GB, risposte dentro le opzioni. Seconda copia
  sulla stessa porta rifiutata; porta libera e nessun llama-server rimasto dopo lo spegnimento.
- **Agente intero contro un NAS finto** (Python, porta 18700, modalità libero, 2 minuti): liste chieste
  e caricate (versione 7), campioni ogni 5 secondi (4-5 per volta) con processo, titolo solo per il
  programma di lista, inattività, audio, schermo bloccato, Pactum; dopo il minuto di misure il motore
  si accende, prende il lavoro, risponde in **6,2 s** col formato del contratto
  (`{"risposte": {...}, "millisecondi": 6228, "modello": "Qwen3.5-0.8B-Q4_K_M"}`); poi la memoria libera
  scende a 7,6 GB e **il motore si spegne da solo** ("memoria libera 7,6 GB, ne servono 8").
  Questa prova ha trovato un errore vero (con la configurazione giusta l'agente diceva "manca la
  configurazione" e non parlava col NAS): corretto, e c'è una prova che lo controlla.
- **Lettura del sito** con UI Automation su un Edge e un Chrome **di prova** (profili temporanei poi
  cancellati, finestre fuori dallo schermo, chiusi per PID; il browser di chi usa il PC non è stato
  toccato): Edge `it.wikipedia.org` in 196 ms, Chrome `youtube.com` in 151 ms
  (opzione di prova `Argus.Agente.exe --prova-dominio <pid> <file.txt>`).
- **Terminale vero** (WebView2, pagina `ui/terminale.html`, finestra fuori dallo schermo e senza primo
  piano): `aiuto` e `ps m: bagno & t: 10` scritti nella pagina, risposte arrivate, immagine salvata
  (`argus-build\prove-immagini\terminale-pacchetto.png`), anche dal **pacchetto finale**.
- **Copertura** disegnata in un'immagine (`argus-build\prove-immagini\copertura.png`), mai aperta sullo
  schermo.
- **Guardiano** `--sessioni`: legge sessione della console (3), utente e stato. Dal **pacchetto finale**
  `--prova-avvio` (16 s): permessi giusti, 0 thread su 23 sospendibili, 4 battiti.
- **Pacchetto**: `crea-pacchetto.ps1` fatto girare: prove, compilazione dei tre programmi, controlli.
  Gli eseguibili del pacchetto partono (guardiano, copertura, terminale). **Bitdefender e Smart App
  Control non hanno bloccato niente** in `argus-build` (eseguibili non firmati); in `Program Files`
  non è stato provato.
- **Script**: i tre `.ps1` passano il controllo di sintassi di Windows PowerShell 5.1, salvati in UTF-8
  con BOM; `installa.ps1` senza amministratore si ferma col messaggio giusto.
- **Tasto del terminale**: Ctrl+Alt+Spazio rifiutato da `RegisterHotKey` in tutte le prove (già preso);
  **Ctrl+Alt+T registrato** dall'agente vero (registro: "tasto del terminale: Ctrl+Alt+T"). Il tasto non è
  stato premuto davvero (avrebbe aperto il terminale sullo schermo).
- **Scelta della cartella del modello e del tasto in `installa.ps1`**: il pezzo di script provato da solo,
  senza amministratore, con 14 casi: di serie → `D:\Argus\modelli` (D: fisso, 377 GB liberi); percorso
  relativo, di rete, radice del disco, disco che non c'è, cartella con altri file → si ferma col messaggio;
  cartella nuova con la barra finale → accettata; modello di prima completo → resta lì; incompleto o
  config senza `motore` → `D:\Argus\modelli`; tasti `T` e `Shift+T` rifiutati. Niente è stato scritto in
  `D:\Argus`.

- **Riconoscimento dei programmi veri** (B5): tabella sopra, 37 programmi del PC con
  `--prova-programmi`.
- **Agente protetto** (B6), senza amministratore (`Argus.Guardiano.exe --prova-avvio`: stesso avvio del
  servizio, ma con l'utente di adesso): l'agente vero parte, da questo stesso utente **tutti i diritti
  vietati sono negati** (processo e thread principale), 0 thread su 23 sospendibili dopo 8 secondi, 4
  battiti in 20 secondi; **congelato** a 20 secondi (`NtSuspendProcess` con l'handle della creazione) →
  chiuso dal guardiano a 35 secondi, 20 secondi dopo l'ultimo battito. **WM_QUIT** mandato al thread
  principale → uscita con codice 5. **Terminale WebView2** dentro l'agente protetto (`--prova-terminale`):
  funziona. Le prove xUnit fanno lo stesso con `ping.exe` (anche `Process.Kill()` negato, e l'handle
  ereditabile del padre che non arriva).
- **`installa.ps1`, segreto e percorsi fidati**: i pezzi nuovi provati da soli contro un NAS finto
  (21 casi): prima installazione (64 esadecimali, registrato, `config.json` illeggibile per l'utente, mai
  nei messaggi), aggiornamento (né rigenerato né registrato, anche col NAS spento), `409` con la frase
  giusta e config intatta, NAS spento o muto o token sbagliato → si ferma **senza creare niente**,
  `-NuovoSegretoSblocco` (409, poi dopo l'azzeramento segreto nuovo), percorsi fidati (validi, relativo,
  non `.exe`, tenuti dall'installazione di prima, tolti con `@()`), JSON della lista sempre una lista in
  PowerShell 5.1. I 14 casi di cartella del modello e tasto ripassati.

## 4. Da provare solo con l'installazione vera

- `installa.ps1` e `disinstalla.ps1` come amministratore (permessi, servizio, collegamenti, download del
  modello da 6,5 GB e controllo sha256).
- Il servizio vero: `WTSQueryUserToken` + `CreateProcessAsUser` (con descrittore di sicurezza ed elenco
  degli handle) nella sessione dello studente, accesso, uscita, cambio utente, blocco dello schermo,
  configurazione passata sull'ingresso standard, battito e `agente_bloccato` col NAS vero, Task Manager
  dello studente che **non** riesce a chiudere l'agente.
- La registrazione del segreto dello sblocco sul NAS vero e lo sblocco con `X-Argus-Sblocco`.
- La copertura sugli schermi veri (anche con due schermi), il clic sulla copertura, Ctrl+Alt+T premuto
  davvero, il collegamento "Argus - terminale".
- I permessi su `D:\Argus` e il download del modello su D:.
- Webcam (`getUserMedia` nella WebView2) per `lb`, `qd`, `vs`, `tf`, le foto trascinate, l'invio al NAS
  vero.
- Pactum che copre davvero (Studio e lavori di casa), con Argus che si fa da parte.
- Firefox (la barra si cerca come `urlbar-input`, non provato), video a schermo intero.
- La voce di ripiego dal NAS vero.
- Argus.Sblocco (chiede l'UAC: non avviato nelle prove).
- **Il modello vero da 9B**: tempi (stima: da 10 a 20 volte il piccolo, quindi circa 1-2 minuti per
  lavoro sul processore di questo PC, dentro i 170 secondi ma da misurare) e qualità. Il modello piccolo
  ha sbagliato (ha visto una persona in un paesaggio): la qualità va giudicata solo col 9B.
- Bitdefender / Smart App Control sugli eseguibili non firmati in `C:\Program Files\Argus`.

## 5. Limiti noti

- **Spazio**: su C: ci sono circa 6,6 GB liberi, troppo poco per il modello (6,5 GB + 1 GB di margine):
  per questo di serie va su D:. Se D: non ci fosse e C: restasse così, l'installazione salterebbe il
  modello (Argus va lo stesso, le foto dubbie restano al NAS).
- Se D: è un disco esterno che Windows vede come "fisso" e viene staccato, il motore non trova il modello:
  il PC smette di fare lavori (lo scrive in `agente.log`) e li fa il NAS.
- Memoria: con Chrome, Claude e il resto aperti la memoria libera su questo PC sta intorno agli 8 GB:
  con la soglia di 8 GB il motore partirà solo quando il PC è poco usato (che è l'idea delle regole 10).
- Lo studente può cambiare l'ora del PC: l'ora che conta è quella del NAS; l'orologio del PC serve solo
  per la regola "senza NAS" e un salto indietro di più di 5 minuti fa considerare il NAS muto.
- **Agente protetto, cosa resta (B6)**: lo studente gira sullo stesso desktop e allo stesso livello
  dell'agente, quindi può ancora (1) mandargli messaggi di finestra: WM_QUIT lo chiude (codice 5, riaperto
  in 1 secondo, segnato come `agente_chiuso`), altri messaggi possono disturbare le finestre; (2) iniettare
  una DLL con un hook di finestra (`SetWindowsHookEx`), che i permessi del processo non fermano: da lì
  potrebbe leggere il token o bloccare l'agente (il blocco lo vede il battito); (3) aprire un thread nato
  da meno di 5 secondi prima che l'agente lo protegga (il battito copre i blocchi); (4) cambiare il
  "DACL di serie" del token dell'agente (non protetto: toccarlo può rompere WebView2), effetto solo sui
  thread nuovi, che l'agente riprotegge; (5) chiudere i processi figli (WebView2 del terminale, motore
  llama-server), che non sono protetti: si chiude il terminale o si ferma il modello, non la copertura.
  Mentre l'agente è congelato, fino a 20 secondi senza copertura (poi chiuso e riaperto).
- **Percorsi fidati in cartelle dello studente**: lo studente può sostituire quel file con un gioco con lo
  stesso nome. È il prezzo dei programmi fatti in casa senza firma: meglio installarli in Program Files.
- Firme senza nome originale (LM Studio, Ollama, Claude Code, Grok): non passano per firma. Un'aggiunta
  possibile, non fatta: "firmatari fidati" (nome dell'editore) in configurazione.
- Prima installazione su un PC dove `C:\ProgramData\Argus` esisteva già (creata dallo studente): la
  cartella viene ripresa (proprietario Administrators, permessi stretti) e `config.json` ricreato, ma
  file che lo studente avesse messo dentro restano (con i permessi della cartella).
- Una finestra sempre in primo piano non copre tutto: il menu Start, la Game Bar, i pannelli di Windows
  e lo schermo di Ctrl+Alt+Canc possono restare sopra. Per questo il giudizio guarda l'ultima finestra
  vera, e la copertura torna appena quelle superfici si chiudono.
- Se l'agente esce (WM_QUIT, errore), per circa un secondo non c'è copertura (poi il guardiano lo
  riapre); se viene congelato, fino a 20 secondi.
- Le liste ricevute non si salvano su disco (vedi sopra).
- Il motore usa l'installazione di LM Studio dell'utente: se LM Studio viene tolto o aggiornato con un
  motore non firmato, il PC smette di fare lavori (lo scrive in `agente.log`) e li fa il NAS.
