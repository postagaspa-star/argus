# Argus - la parte del PC

Il programma di Argus per il PC Windows dello studente. Guarda che cosa c'è in primo piano, copre lo
schermo quando c'è una cosa non permessa, apre il terminale per parlare con Argus e, quando il PC è
libero e alla corrente, guarda le foto dubbie al posto del NAS. Le regole le decide il NAS: il PC
esegue.

Tre programmi:

| Programma | Cosa fa |
|---|---|
| **Argus.Guardiano** | servizio di Windows: apre il programma dello studente quando lo studente entra e lo riapre se viene chiuso |
| **Argus.Agente** | il programma dello studente: copertura, terminale, foto, modello per le foto dubbie |
| **Argus.Sblocco** | lo sblocco d'emergenza (chiede la password dell'amministratore) |

## Cosa serve

- Windows 10 o 11 a 64 bit.
- Un account **amministratore** (per installare) e l'account **standard** dello studente.
- Il NAS con Argus acceso e il suo **token del PC** (sul NAS, nel file `/data/token-pc.txt`).
- Circa **7,5 GB liberi** per il modello delle foto dubbie: va su **D:** (`D:\Argus\modelli`) se c'è un
  disco D: fisso con almeno 8 GB liberi, altrimenti su C: (`C:\ProgramData\Argus\modelli`). Se lo spazio
  non c'è, Argus funziona lo stesso e le foto dubbie le guarda il NAS.

## 1. Preparare il pacchetto

Sul PC dove c'è il codice, in Windows PowerShell (non serve amministratore), nella cartella `pc`:

```
.\crea-pacchetto.ps1
```

Fa le prove, compila e crea la cartella `C:\Users\<tu>\argus-build\pc\pacchetto\Argus-pc`.

## 2. Installare

1. Copia la cartella `Argus-pc` sul PC da controllare (per esempio in `Download`).
2. Apri il menu Start, scrivi `PowerShell`, tasto destro su **Windows PowerShell** e scegli
   **Esegui come amministratore**.
3. Scrivi queste righe, una alla volta, premendo Invio (cambia il percorso, l'indirizzo del NAS e il
   nome dell'account dello studente):

```
cd "C:\Users\<nome>\Downloads\Argus-pc"
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
Get-ChildItem -Recurse | Unblock-File
.\installa.ps1 -IndirizzoNas 192.168.1.10 -UtenteControllato <account dello studente>
```

4. Quando chiede il token, incollalo e premi Invio (mentre lo scrivi non si vede: è normale).
   Alla prima installazione il NAS deve essere acceso: lo script ci registra il segreto dello sblocco
   d'emergenza (lo crea da solo e non lo mostra mai). Se il NAS non risponde si ferma senza aver cambiato
   niente.
5. Aspetta la fine: il modello sono circa 6,5 GB da scaricare (lo script dice in che cartella lo
   mette). Alla fine compare **"Argus è installato."** in verde.

Opzioni di `installa.ps1`:

| Opzione | Cosa fa |
|---|---|
| `-SabatoScuola` | il sabato c'è scuola |
| `-Patrono 15/06` | il giorno del patrono (senza scuola) |
| `-SenzaModello` | non scarica il modello adesso (rilancia lo script più tardi senza questa opzione) |
| `-SenzaMotore` | il PC non usa mai il modello: le foto dubbie le guarda solo il NAS |
| `-CartellaModelli E:\Argus\modelli` | mette il modello in un'altra cartella (nuova o vuota, su un disco interno) |
| `-TastoTerminale "Ctrl+Alt+A"` | un'altra combinazione per il terminale (di serie Ctrl+Alt+T) |
| `-Token ...` | il token scritto direttamente (meglio lasciarlo chiedere: così non resta nella cronologia) |
| `-PercorsiFidati "C:\Users\<studente>\AppData\Local\Programs\App\App.exe","..."` | programmi fatti in casa, senza firma, in cartelle dello studente, che devono valere per le liste (percorso completo, scritto per intero) |
| `-NuovoSegretoSblocco` | solo per rifare il segreto dello sblocco: prima va cancellato `/data/token-sblocco.txt` sul NAS |

Se il download del modello si interrompe, rilancia la stessa riga: riprende da dove era e non rifà il
resto.

## 3. Per lo studente

- Se in primo piano c'è una cosa non permessa, lo schermo si copre con un messaggio. Basta tornare a una
  cosa permessa e la copertura sparisce.
- **Ctrl+Alt+T** apre il terminale, **Esc** lo nasconde. Si scrive un comando e si preme Invio
  (`aiuto` per l'elenco).
- Se Ctrl+Alt+T non funziona (lo usa già un altro programma): **clic sulla copertura**, oppure menu
  Start → **Argus - terminale**. La combinazione si cambia in `config.json` (`"tasto_terminale"`) o con
  `-TastoTerminale` rilanciando l'installazione.
- Un programma vale per dove è installato, non per il nome: un programma copiato o rinominato in una
  cartella tua non conta come quello vero.

## 4. Sblocco d'emergenza

Menu Start → **Argus - sblocco d'emergenza** → password dell'amministratore → scegli le ore (da 1 a 48)
→ **Sblocca**. Finisce nel registro di Argus. **Togli lo sblocco** lo chiude prima.

## 5. Dove stanno le cose

| Dove | Cosa |
|---|---|
| `C:\Program Files\Argus` | i programmi |
| `C:\ProgramData\Argus\config.json` | indirizzo del NAS, token, segreto dello sblocco, utente controllato, tasto del terminale, percorsi del modello, percorsi fidati (lo leggono solo SYSTEM e gli amministratori) |
| `C:\ProgramData\Argus\sblocco.json` | lo sblocco d'emergenza |
| `D:\Argus\modelli` oppure `C:\ProgramData\Argus\modelli` | il modello per le foto dubbie (il percorso giusto è in `config.json`, `motore.modello`) |
| `C:\ProgramData\Argus\log` | registri del guardiano e dello sblocco |
| `C:\Users\<studente>\AppData\Local\Argus\log` | registri dell'agente e del motore |

## 6. Aggiornare e togliere

- **Aggiornare**: rifai il pacchetto e rilancia `installa.ps1` con le stesse opzioni. Ferma la versione
  vecchia da solo e non riscarica il modello se c'è già.
- **Togliere**: come amministratore, nella cartella del pacchetto, `.\disinstalla.ps1`. Il modello resta
  dov'è (per toglierlo anche lui: `.\disinstalla.ps1 -TogliModelli`; trova da solo la cartella).
- **Reinstallare dopo averlo tolto**: sul NAS resta il segreto dello sblocco della vecchia installazione.
  Prima chi gestisce il NAS cancella `/data/token-sblocco.txt`, poi si rilancia `installa.ps1`.

## 7. Se qualcosa non va

| Cosa vedi | Cosa vuol dire |
|---|---|
| "Il NAS non risponde: riprova tra poco." | il PC non raggiunge il NAS. Nei giorni di scuola, dalle 11:00 e dopo 2 minuti senza NAS, il PC passa in modalità studio finché il NAS torna |
| l'installazione dice "Sul NAS c'è già un segreto di sblocco" | il NAS ha il segreto di un'installazione di prima: chi gestisce il NAS cancella `/data/token-sblocco.txt`, poi rilancia |
| l'installazione dice "il NAS non risponde e devo registrarci il segreto dello sblocco" | accendi il NAS o controlla l'indirizzo, poi rilancia: non è stato cambiato niente |
| un programma di lavoro o di studio fatto in casa viene coperto | non ha la firma digitale e sta in una cartella dello studente: rilancia l'installazione con `-PercorsiFidati` (o installalo in `C:\Program Files`) |
| nel registro dell'agente: "Ctrl+Alt+T è già preso" | un altro programma usa la stessa combinazione: vale il clic sulla copertura o il menu Start, oppure scegli un'altra combinazione con `-TastoTerminale` |
| l'installazione dice "spazio libero insufficiente" | libera spazio sul disco del modello (o scegline un altro con `-CartellaModelli`) e rilancia `installa.ps1` |
| il terminale dice che manca WebView2 | installa "Microsoft Edge WebView2 Runtime" dal sito di Microsoft |

## Per chi lavora sul codice

- SDK: `%LOCALAPPDATA%\Microsoft\dotnet-sdk-8\dotnet.exe`. Compilazione e file intermedi finiscono in
  `C:\Users\<tu>\argus-build\pc` (fuori da OneDrive, vedi `Directory.Build.props`).
- Prove: `dotnet test Argus.Prove`. La prova col motore vero parte solo con la variabile
  `ARGUS_PROVA_MOTORE=1` e un modello piccolo in `C:\Users\<tu>\argus-build\modelli-prova`.
- Prove a mano senza amministratore: `Argus.Agente.exe --prova-programmi <elenco.txt> <esito.txt>` (come
  vengono riconosciuti i programmi), `Argus.Guardiano.exe --prova-avvio <config.json> <secondi> [--congela 20]`
  (agente protetto, permessi, battito).
- Scelte e limiti: `NOTE-COSTRUTTORE.md`.
