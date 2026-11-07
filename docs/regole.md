# Argus — le regole (v1)

Questo file è la fonte di verità del comportamento. Il codice del NAS (`nas/`) e del PC (`pc/`)
lo seguono alla lettera; se una regola cambia, si cambia prima qui.
Nel testo "lo studente" è la persona che Argus segue. Nel codice niente nomi veri né indirizzi di casa.

## 1. L'idea in una riga

Ogni giorno di scuola c'è una **quota** di lavoro vero (studio o lavoro al computer). Finché non è
fatta, i dispositivi controllati (il PC) fanno girare solo le cose permesse. Quando è fatta, si è liberi.
L'unico modo per uscirne è studiare: distrarsi non blocca per ore, allunga la quota.

## 2. Il giorno

- **Giorno di scuola**: lunedì-venerdì (sabato configurabile, spento di serie), esclusi festivi e
  vacanze del calendario scolastico del Veneto 2026/27 (sezione 13) e il patrono del comune
  (configurabile, vuoto di serie).
- **Arrivo**: la prima volta che una telecamera riconosce lo studente dopo le 11:00 di un giorno di
  scuola, dopo almeno 3 ore senza vederlo. Senza arrivo (malato, a casa tutto il giorno, fuori fino a
  mezzanotte) la quota del giorno non parte.
- **Inizio** = l'arrivo. Da lì valgono le regole e il PC è in modalità studio.
- **Pranzo**: mangiare visto (seduto al tavolo con cibo) è neutro. In più c'è **una sola sparizione
  "pranzo"** al giorno (per chi mangia di sopra o fuori): se lo studente sparisce dalla vista entro
  30 minuti dall'arrivo, i primi 60 minuti di assenza sono sempre neutri. Dal 61° minuto vale il fuori
  vista senza altra grazia (distrazione, con avviso), finché non ricompare o scrive una pausa `ps`:
  si paga solo il tempo oltre, mai quello già concesso. Se è già stato visto mangiare quel giorno, la
  sparizione pranzo non c'è più.
- **Mezzanotte**: quello che manca della quota passa al prossimo giorno di scuola, **al massimo 30
  minuti**. Il resto si perde (e resta nel registro).
- **Quota fatta**: libero fino al prossimo giorno di scuola; Argus smette di analizzare le immagini
  (risparmia il NAS) e lo dice una volta a voce.

## 3. La quota

quota del giorno = base 60 min + verifiche (0: Classe Viva e WhatsApp sono in stand-by)
                   + riporto da ieri (max 30) + aggiunte di oggi

- **Aggiunte**: distrazione (sezione 5) e imbroglio (sezione 6). Tetto: distrazioni +60 al giorno,
  imbrogli +30 l'uno; **tetto totale delle aggiunte +120 al giorno** (il debito non deve gonfiarsi).
- **Il lavoro (lv) conta per tutto tranne i minuti delle verifiche**: quelli si coprono solo studiando.
- **Nessun tetto allo studio**: la quota è il minimo, si può studiare quanto si vuole. I minuti oltre
  la quota non si accumulano per domani.

## 4. Come si classifica ogni minuto

Ogni minuto dall'Inizio a quota fatta prende **una** classe:

| Classe | Effetto | Esempi |
|---|---|---|
| **studio** | avanza la quota | PC su programma/sito di studio in primo piano e lo studente lì davanti; libro o quaderno di scuola (registrato) in uso; scrivere; Lectio dal PC con le cuffie (anche sdraiato: vale **solo** l'audio di Lectio, non quello di altri programmi della lista); pensiero giudicato studio (sezione 7) |
| **lavoro** | avanza la quota (non i minuti verifiche) | durante `lv`: programmi/siti di lavoro in uso |
| **neutro** | niente | dormire (visto o `dm`); leggere altro; mangiare visto; pensiero giudicato non studio; pausa `ps` nel suo tempo; sparizione pranzo; fuori vista fino a 5 minuti; **nel dubbio** |
| **distrazione** | non avanza **e** aggiunge 1 minuto (conta doppio) | il suo telefono in mano acceso; fuori vista oltre i 5 minuti senza pausa; pausa sforata; contenuto di svago dentro un'app permessa (prima che venga coperto) |
| **imbroglio** | +30 alla quota, una volta per episodio | dispositivo non controllato in uso (tablet, altro telefono, console, TV accesa); motivo della pausa falso |

Principio fisso: **nel dubbio, né avanti né punizione**. Una penalità richiede una prova chiara.

## 5. Distrazione

- Un episodio comincia dopo **1 minuto** di distrazione continua (filtra i falsi allarmi). A quel punto
  parte un **avviso a voce** dalla stanza dov'è lo studente (sezione 11).
- Da lì ogni minuto è distrazione (non avanza + aggiunge 1). L'episodio finisce appena torna a studiare.
- **Fuori vista**: i primi 5 minuti sono neutri (bagno, acqua). Dal sesto in poi distrazione, a meno di
  una pausa `ps` attiva, della sparizione pranzo o di un `dm` valido. Durante una pausa il conteggio
  del fuori vista è fermo. Se il PC è in uso (tasti o mouse nell'ultimo minuto) lo studente è lì,
  anche se la telecamera non lo vede: niente fuori vista.
- **Telecamere giù**: se la telecamera della stanza dove lo studente è stato visto per ultimo è spenta,
  irraggiungibile o la visione è ferma (o lo sono tutte), il minuto è **neutro** e il conteggio del
  fuori vista non avanza. Senza occhi non c'è prova, quindi non c'è punizione.
- Un episodio di distrazione si chiude quando torna a studiare **o dopo 5 minuti senza distrazione**;
  un episodio nuovo riparte dal minuto di filtro.

## 6. Imbroglio

- **Dispositivo non controllato**: uno schermo acceso in mano o davanti allo studente che non è il PC
  controllato, mentre il PC dice che lo schermo controllato non è in uso o è su altro. Il suo telefono
  (registrato con `tf`) è distrazione, non imbroglio. Un altro telefono, un tablet, una console, la TV
  accesa con lo studente davanti = imbroglio. Se TV o console hanno una presa smart configurata,
  la presa si spegne.
- **Motivo della pausa falso**: durante un `ps` lo studente viene visto fare una cosa che non torna con
  il motivo (SemIf, sezione 9). Esempio: "m: bagno" e lo si vede sul divano col telefono.
- **Senza il PC per le foto**: se una foto dubbia non viene guardata dal PC entro 15 minuti (portatile
  staccato dalla corrente, spento, motore che non parte), il NAS decide da solo **solo con prove forti**:
  telefono o tablet riconosciuto con sicurezza alta in mano allo studente in almeno 3 immagini di fila,
  e chiaramente diverso dal telefono registrato. Altrimenti neutro.
- Ogni imbroglio: +30 alla quota (dentro il tetto totale), voce, registro.
- Chiudere il programma del PC **non** è imbroglio: il guardiano lo riapre in pochi secondi e lo segna
  nel registro.

## 7. Il pensiero (studio senza niente in mano)

- Lo studente fermo senza oggetti, con gli occhi aperti, alla scrivania o sul divano: i minuti vanno
  **in sospeso**.
- Il giudizio arriva dopo, da SemIf, leggendo il **diario a parole** di prima, durante e dopo.
  Esempio: prima libro di storia aperto, dopo scrive sul quaderno → studio.
- Conta come studio **al massimo 10 minuti per episodio**, e solo se il "dopo" (entro 30 minuti) è
  studio vero che dura **almeno quanto** il sospeso. Altrimenti neutro.
- Se il giudizio non arriva entro mezzanotte: neutro.

## 8. I comandi (il terminale)

Il terminale è una finestra di Argus sul PC (sezione 12). Comandi, maiuscole o minuscole uguali:

- **`ps m: <motivo> & t: <durata>`** — pausa. Durata: `10`, `10 min`, `10m`, `1h`, `1h30`, `90 min`.
  - Budget: **10 minuti all'Inizio + 10 ogni 50 minuti trascorsi dall'Inizio**, meno quelli usati.
    Se chiede di più: "Ti restano X minuti di pausa." e la pausa **non** parte. Una nuova `ps` durante
    una pausa la sostituisce, contando come disponibili anche i minuti non usati di quella in corso;
    se la nuova è rifiutata, **quella in corso resta** e la risposta lo dice.
  - Durante la pausa l'assenza è neutra. Se lo vedono fare una cosa che non torna col motivo: imbroglio.
  - Finisce allo scadere o appena lo studente torna a studiare. I minuti oltre la scadenza (se non
    studia) sono distrazione.
  - Risposta sempre: "Pausa fino alle 15:52." oppure "Non ho capito. Scrivi così: ps m: bagno & t: 10".
- **`lv<minuti>`** (`lv30`, `lv 30`, 5-240) — tempo di lavoro: oltre alle cose di studio sono permesse
  quelle di lavoro, e il tempo conta come lavoro. `lv0` lo chiude prima. Risposta: "Lavoro fino alle 16:25."
- **`dm<minuti>`** (`dm45`) — dormo. Neutro come il sonno visto, in più: niente avvisi a voce, e la
  persona sdraiata in quel posto è considerata lo studente anche se il viso non si vede.
  - Vale solo se entro 5 minuti lo vedono sdraiato (letto o divano); se no "Non ti vedo sdraiato: dm annullato."
  - Finisce da solo quando lo vedono alzarsi (almeno 1 minuto in piedi o attivo) o allo scadere.
    Il PC conta come "alzato" solo se viene toccato **dopo** la conferma del dm, nell'ultimo minuto
    (il comando stesso si scrive al PC e non deve chiudere il dm).
  - **Sforare non punisce**: anche dopo lo scadere, la persona sdraiata nello stesso posto resta lo
    studente finché non lo vedono alzarsi. Fuori vista per più di 5 minuti durante il dm: vale la regola normale.
- **`st`** — stato: quota fatta/totale, in sospeso, aggiunte, pausa disponibile, classe adesso, comando
  attivo, ora prevista di fine.
- **`lb <nome>`** — registra un libro di scuola (foto trascinate nella finestra o 6 scatti dalla webcam;
  consiglio: copertina + 2-3 pagine aperte). `lb` da solo = elenco. `lb via <nome>` = toglie.
- **`qd <nome>`** — come `lb`, per i quaderni.
- **`vs`** — registra il viso dello studente (10 scatti dalla webcam, girando un po' la testa).
- **`tf`** — registra il telefono dello studente (6 scatti: davanti, dietro, di lato).
- **`ag <studio|lavoro> <programma.exe|sito>`** — aggiunge alla lista: vale **dopo 4 giorni**.
- **`tg <studio|lavoro> <programma.exe|sito>`** — toglie dalla lista: vale **subito**.
- **`aiuto`** — l'elenco dei comandi in una riga ciascuno.

## 9. Le decisioni (SemIf)

Le regole semplici le decide il codice (esempi: PC su programma di studio = studio; telefono suo acceso
in mano = distrazione). SemIf, sul NAS (lo stesso decisore di Sol), decide solo i casi che chiedono di
capire, sempre con risposte fisse:

- **pensiero**: "Il sospeso era studio?" → `studio` / `non_studio` / `non_si_capisce`.
- **titolo**: "Questa pagina è studio, lavoro o svago?" (per i siti da giudicare: YouTube, chat AI dal
  browser) → `studio` / `lavoro` / `svago` / `non_si_capisce`. Risultato in memoria per quel titolo
  (30 giorni; `non_si_capisce` solo 15 minuti, poi si rigiudica). Si chiede **solo** mentre la quota è
  in corso: in `libero` o `inattivo` i titoli non vanno a SemIf.
- **pausa**: "Quello che si vede torna col motivo della pausa?" → `torna` / `non_torna` / `non_si_capisce`.
- **lettura**: "Quello che legge è roba di scuola?" quando il confronto delle copertine non basta.

`non_si_capisce` = nel dubbio, neutro.

## 10. Le foto dubbie (modello sul PC)

Quando il codice e SemIf non bastano perché serve guardare un'immagine (cosa ha in mano, se lo schermo
è acceso, se dorme), il NAS mette un **lavoro** in coda con un ritaglio dell'immagine e domande a
risposte fisse. Il PC lo prende solo se: attaccato alla corrente, almeno 8 GB di memoria libera,
processore sotto il 50% nell'ultimo minuto. Modello: Qwen3.5-9B (Q4_K_M + parte visiva, 6,5 GB, nella
cartella `D:\Argus\modelli` perché su C: non c'è spazio), caricato al bisogno e tolto dopo 5 minuti
senza lavori. Se il PC non lo prende, il lavoro aspetta; a mezzanotte
decide SemIf sulle sole parole del diario, e nel dubbio neutro. L'immagine si cancella appena giudicata.

## 11. La voce

Frasi brevi, in italiano semplice, dall'altoparlante della telecamera della stanza dove lo studente è
stato visto per ultimo; se lì non si può, dal PC. Voce: `supertonic` del servizio voci del NAS.
Mai durante un `dm`. Mai più di una frase ogni 2 minuti. Esempi:
- distrazione: "Torna a studiare: mancano 35 minuti."
- fuori vista: "Non ti vedo da 5 minuti. Se ti serve una pausa, scrivila nel terminale."
- imbroglio: "Quello non è un dispositivo di studio: altri 30 minuti."
- quota fatta: "Fatto per oggi. Sei libero."

## 12. Il PC

- **Modalità**: `libero` (niente coperture), `studio` (permesse: sempre + studio), `lavoro` (durante `lv`:
  sempre + studio + lavoro), `inattivo` (Argus spento, niente coperture).
- **Copertura**: se in primo piano c'è una finestra non permessa, una finestra senza bordi copre ogni
  schermo (come la copertura dei lavori di casa di Pactum: non chiude e non tocca le altre app, le
  copre). Testo: "Adesso è tempo di studio. Mancano 35 minuti." e "Torna a una cosa permessa o apri il
  terminale: Ctrl+Alt+T". Sparisce appena in primo piano torna una cosa permessa. Un clic sulla
  copertura apre il terminale (serve se il tasto è preso da un altro programma).
- **Se Pactum sta già coprendo** (Studio o lavori di casa), la copertura di Argus si fa da parte; il
  conteggio continua.
- **Siti da giudicare** (YouTube, claude.ai, chatgpt.com, gemini.google.com, grok.com, copilot): permessi
  in attesa del giudizio per al massimo 20 secondi, poi coperti se il giudizio non è `studio`/`lavoro`.
- **Terminale**: finestra scura, una riga dove si scrive, apre con **Ctrl+Alt+T** da qualsiasi
  punto (configurabile: Ctrl+Alt+Spazio su questo PC è già occupato), si nasconde con Esc, nessuna
  icona nella barra delle applicazioni. Accetta foto trascinate e usa la webcam per `lb`, `qd`, `vs`, `tf`.
  Si apre anche dal menu Start ("Argus - terminale") e con un clic sulla copertura.
- **Senza NAS**: in un giorno di scuola tra le 11:00 (l'ora da cui può esserci l'arrivo) e mezzanotte,
  se il NAS non risponde da più di 2 minuti e l'ultima risposta non era "quota fatta oggi", il PC va in
  modalità studio finché il NAS torna (la modalità più severa, non la più comoda).
- **Programmi riconosciuti davvero, non solo dal nome**: un programma in una cartella dove lo studente
  può scrivere (profilo, Download, Desktop, Temp) vale solo se ha una firma digitale valida e il suo
  nome originale (dentro il file) è quello in lista, oppure se il suo percorso completo è tra i
  "percorsi fidati" della configurazione (le app fatte in casa). Rinominare un gioco in `soffice.exe`
  non basta. I programmi di Argus valgono solo dalla loro cartella in Program Files.
- **Il programma non si chiude né si congela dall'account dello studente**: il guardiano lo avvia con
  permessi che non gli permettono di terminarlo, sospenderlo o leggerne la memoria, e si accorge se
  smette di rispondere (lo riapre e lo segna).
- **Guardiano**: un servizio di Windows (account di sistema) riapre il programma entro pochi secondi
  se viene chiuso, e lo segna nel registro.
- **Sblocco d'emergenza**: un programma a parte che chiede la password dell'amministratore (il padre)
  e sblocca il PC per 1-48 ore. Usa un secondo segreto che legge solo l'amministratore: il programma
  dello studente non lo conosce, quindi non può sbloccarsi da solo. Il NAS accetta al massimo 48 ore,
  calcolate col suo orologio. Finisce nel registro.

## 13. Calendario scolastico Veneto 2026/27 (giorni senza scuola)

Lezioni dal 10/09/2026 all'08/06/2027 (DGR 712 del 07/07/2026). Senza scuola anche:
30/10-02/11/2026; 07-08/12/2026; 24/12/2026-06/01/2027; 08-13/02/2027; 25-30/03/2027;
25/04/2027; 29/04-01/05/2027; 31/05-02/06/2027. Dopo l'08/06/2027 niente scuola fino a settembre.

## 14. Le liste di partenza

Programmi per nome dell'eseguibile (minuscolo), siti per dominio (vale anche per i sottodomini).

- **Sempre**: il terminale e il programma di Argus, explorer.exe, calculatorapp.exe /
  calculator.exe, notepad.exe, snippingtool.exe / screenclippinghost.exe, pactum.exe, i dialoghi di
  sistema (consent.exe, lockapp.exe, searchhost.exe, startmenuexperiencehost.exe,
  shellexperiencehost.exe, applicationframehost.exe solo se il titolo è Calcolatrice/Strumento di cattura).
- **Studio — programmi**: soffice.exe, swriter.exe, scalc.exe, simpress.exe, smath.exe, sdraw.exe,
  pdfelement.exe, lectio (eseguibile del PC di Lectio), googledrivefs.exe, photos.exe
  (microsoft.photos.exe), soundrec.exe / voicerecorder.exe, i browser (chrome.exe, msedge.exe,
  firefox.exe, brave.exe) **solo sui siti della lista**.
- **Studio — siti**: spaggiari.eu, classeviva.it, drive.google.com, docs.google.com,
  classroom.google.com, zanichelli.it, pearson.it, hubscuola.it, mondadorieducation.it,
  deascuola.it, bsmart.it, loescher.it, wikipedia.org, treccani.it, wordreference.com,
  translate.google.com, deepl.com, brocardi.it, normattiva.it, geogebra.org, desmos.com,
  wolframalpha.com, khanacademy.org. Da giudicare: youtube.com, claude.ai, chatgpt.com,
  gemini.google.com, grok.com, copilot.microsoft.com.
- **Lavoro — programmi**: claude.exe, windowsterminal.exe, powershell.exe, cmd.exe, git-bash.exe,
  bash.exe, mintty.exe, git-gui.exe / wish.exe, studio64.exe (Android Studio), python.exe,
  pythonw.exe, node.exe, devhome.exe, wisper ufficio (eseguibile) / wisperufficio.exe, ugreen nas
  (eseguibile), lm studio.exe / bionic.exe (LM Studio), ollama app.exe, outlook.exe / olk.exe,
  epsonscan2.exe.
- **Lavoro — siti**: github.com, githubusercontent.com, netlify.com, netlify.app, firebase.google.com,
  console.cloud.google.com, cloudflare.com, tailscale.com, huggingface.co, devpost.com,
  stackoverflow.com, developer.mozilla.org, docs.python.org, developer.android.com, learn.microsoft.com,
  mail.google.com, localhost, 127.0.0.1, gli indirizzi di casa 192.168.x.x; i siti dei clienti stanno
  solo nella configurazione locale del NAS (`liste_extra`), non nel repo. Da giudicare: come studio.
- **Mai** (anche se qualcuno li aggiunge): steam.exe e tutto ciò che parte da Steam, minecraft
  (launcher e gioco), albion, crusader kings, hearts of iron, war thunder, paradox launcher,
  schedule i, xbox, solitaire; social e streaming (instagram.com, tiktok.com, x.com, twitter.com,
  reddit.com, facebook.com, twitch.tv, netflix.com, primevideo.com, disneyplus.com); whatsapp.exe e
  web.whatsapp.com, teams.exe (finché non si decide diversamente), msn.com.
- Tutto quello che non è in nessuna lista: **coperto**.

## 15. Le telecamere

- Due stanze: la camera (scrivania e divani) e salotto/cucina. Tapo economiche da almeno 2K.
- Argus le legge dal flusso secondario (bassa risoluzione) a 2-5 immagini al secondo, e dal flusso
  principale solo per i ritagli da riconoscere (libri, telefono, viso).
- **Inseguimento**: Argus muove la telecamera della stanza dove sta lo studente per tenerlo al centro
  (zona morta 20%, al massimo un movimento ogni 2 secondi); dopo 60 secondi senza di lui torna alla
  posizione di partenza. Se il comando di movimento non funziona, si usa l'inseguimento integrato
  della telecamera.
- **Dove sta**: dedotto dagli oggetti, non da zone disegnate (la telecamera si muove): sul divano
  (`couch`), sul letto (`bed`), al tavolo/scrivania (sedia + tavolo o portatile davanti), in piedi,
  fuori vista. Più la stanza.
