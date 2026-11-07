# Note del costruttore (NAS)

Scritte il 07/11/2026 alla consegna della versione 1.0.0. Qui ci sono le scelte fatte, i punti delle
regole che ho dovuto interpretare, cosa non ho potuto provare senza le telecamere vere e i limiti noti.
Fonte di verità resta `docs/regole.md` + `docs/contratto.md`.

## 1. Come è fatto

| Pezzo | File | Note |
|---|---|---|
| Regole | `argus/motore.py` | Puro: nessuna rete, nessun disco, orologio passato da fuori. Ogni minuto entra un `Minuto` (cosa si vede + cosa dice il PC), escono effetti (voce, eventi, domande a SemIf, prese). Lo stato si esporta/importa in JSON e si salva a ogni minuto. |
| Calendario | `argus/calendario.py` | Veneto 2026/27 + patrono + sabato configurabile. |
| Comandi | `argus/comandi.py` | Lettura del testo del terminale, pura. |
| Liste | `argus/liste.py` | Liste di partenza (sezione 14), `ag` dopo 4 giorni, `tg` subito, versione. |
| Frasi | `argus/testi.py` | Tutte le frasi per lo studente in un posto solo. |
| Servizio | `argus/servizio.py`, `argus/api.py` | FastAPI, token, minuto per minuto, coda delle decisioni SemIf, coda dei lavori, voce, prese. |
| PC | `argus/pc_attivita.py` | Campioni del PC → categoria del minuto, siti da far giudicare. |
| SemIf | `argus/semif.py` | Una domanda alla volta, 503 → riprova dopo 30 s, soglie 0,6 / 0,5. |
| Voce | `argus/voce.py` | lectio-voci con cache su disco, go2rtc verso la Tapo, ripiego sul PC. |
| Visione | `argus/visione/` | Lettura RTSP, rilevatore, posa, viso, vettori, ragionamento, aggregatore, PTZ, pipeline. |
| Database | `argus/db.py` | SQLite (WAL) in `/data/argus.db`. |

## 2. Modelli scelti

Tutti scaricati da URL fissati a un commit preciso e controllati con sha256 (`argus/visione/modelli.py`).
Totale circa 185 MB, nel volume `argus-modelli`.

| Compito | Modello | Licenza | Peso | Motore |
|---|---|---|---|---|
| Oggetti COCO (persona, telefono, libro, tv, portatile, letto, divano, sedia, tavolo, cibo...) | D-FINE S COCO (onnx-community/dfine_s_coco-ONNX) | Apache-2.0 | 41,5 MB | ONNX Runtime CPU (OpenVINO GPU facoltativo) |
| Riconoscere libri, quaderni, telefono registrati | SigLIP 2 base patch16-224, solo parte visiva, int8 (onnx-community) | Apache-2.0 | 94,5 MB | ONNX Runtime CPU |
| Trovare i visi | YuNet 2023mar (OpenCV Zoo) | MIT | 0,23 MB | OpenCV |
| Riconoscere il viso | SFace 2021dec (OpenCV Zoo) | Apache-2.0 | 38,7 MB | OpenCV |
| Posa (seduto, in piedi, sdraiato, mani) | MediaPipe pose_landmarker_lite float16 | Apache-2.0 | 5,8 MB | MediaPipe |
| Occhi aperti/chiusi | MediaPipe face_landmarker float16 (blendshapes degli occhi) | Apache-2.0 | 3,8 MB | MediaPipe |

Perché questi:

- **Niente YOLO di Ultralytics**: licenza AGPL-3.0, il brief chiede una licenza permissiva.
  D-FINE è Apache-2.0 e su COCO è allo stesso livello.
- **D-FINE S e non N**: la versione N esportata in ONNX dava risultati rotti (doppioni e oggetti
  persi sulle stesse foto dove la S va bene).
- **SigLIP 2 su ONNX Runtime e non su OpenVINO**: con OpenVINO il modello int8 usava circa 1 GB di RAM
  ed era più lento.
- **Vettori SigLIP centrati**: il coseno "grezzo" fra due oggetti qualsiasi era già circa 0,8, quindi
  inutile per distinguere. Tolgo il vettore medio di circa 430 ritagli COCO
  (`argus/visione/dati/media_siglip2.npy`) e rinormalizzo. Dopo: stesso telefono 0,84, telefono
  contro libro 0,09. Due libri diversi però arrivano anche a 0,6: per questo la soglia del libro è
  0,75 (configurabile in `visione.soglia_libro`).
- **Viso**: soglia SFace 0,363, il valore consigliato da OpenCV. Misurato: stesso viso 0,84,
  persona diversa 0,11.
- MediaPipe si installa senza dipendenze (`requirements-mediapipe.txt`), così non tira dentro la
  versione di OpenCV con interfaccia grafica.

## 3. Velocità e memoria misurate sul PC

PC: Intel Core i5-1235U, ONNX Runtime CPU con 2 thread (come nel container), Python 3.12.

| Cosa | Tempo |
|---|---|
| D-FINE S, un'immagine 640x360 | 233-319 ms (ultima misura 251 ms) |
| SigLIP 2 int8, un ritaglio | 98-156 ms (ultima 144 ms) |
| MediaPipe posa, un ritaglio | 21-27 ms |
| Un passo intero della visione (rilevatore + posa + viso + vettori, telecamera finta) | 738 ms (mediana) |
| Memoria del processo con tutti i modelli caricati e la visione che gira | 542 MB |

**Stima per il N100** (non misurata): un core del N100 è circa 1,5-2 volte più lento di quello del
i5-1235U, quindi un passo intero dovrebbe stare fra 1,1 e 1,5 secondi. Vuol dire che sulla telecamera
dove sta lo studente si analizzeranno circa 0,7-1 immagini al secondo, non 2: per le regole basta
(un minuto "visto" vuole almeno 2 immagini, ce ne sono 40-60), ma l'inseguimento sarà meno pronto.
Se serve più velocità: la GPU del N100 per il rilevatore (`GPU_INTEL=1` + `/dev/dri`, vedi README),
oppure `visione.thread: 3` se il resto del NAS lo permette.

**Memoria**: circa 550 MB misurati sul PC per il processo, più la cache delle frasi e i buffer RTSP
(due telecamere a bassa risoluzione: pochi MB). Stima sul NAS: 600-800 MB per `argus`, 30-60 MB per
`argus-go2rtc`. Limiti nel compose: 1600 MB e 256 MB. Senza telecamere (inattivo) nessun modello è
caricato (memoria non misurata, ma senza modelli resta il solo server web).

## 4. Punti delle regole che ho dovuto interpretare

Sempre con la lettura più prudente ("nel dubbio, né avanti né punizione").

**Giorno, arrivo, quota**
- Senza arrivo il giorno non conta: non nasce riporto e il riporto che era destinato a quel giorno si
  perde (sezione 2: "la quota del giorno non parte").
- Una persona sdraiata a letto nella camera dello studente che non si riesce a riconoscere
  (`forse_visto`) blocca l'arrivo: nei giorni da malato non deve partire una quota per sbaglio.
- Se il NAS era spento, alla riaccensione i giorni passati si chiudono come a mezzanotte. Un arrivo
  può comunque essere "falso" se il NAS è rimasto spento durante le 3 ore di assenza (non sa che lo
  studente era in casa).
- Se lo studente non è registrato con `vs`, Argus non lo riconosce e non parte niente.
- Fuori dall'anno 2026/27 nessun giorno è di scuola (va aggiunto il calendario nuovo).
- `verifiche` è nella configurazione (0 di serie, come dice la sezione 3).
- Sblocco d'emergenza dal PC: niente punizioni e niente voce, lo studio però conta. Vale solo con
  l'intestazione `X-Argus-Sblocco` uguale al segreto in `/data/token-sblocco.txt` (senza segreto
  registrato, o intestazione mancante o sbagliata: 403 `sblocco`); `ore` intero da 0 a 48 (altro,
  anche testo: 422); la fine la calcola il NAS col suo orologio, un `fino` mandato dal PC si ignora;
  `ore: 0` toglie lo sblocco.
- **Il secondo segreto non lo genera il NAS** (decisione del coordinatore, contratto 1): per arrivare
  sul PC passerebbe dalle mani dello studente. Lo genera l'installatore del PC e lo registra con
  `POST /api/pc/registra-sblocco {"segreto": "<64 esadecimali>"}` (token del PC; altro formato: 422).
  Il NAS lo salva (permessi 600) solo se il file non c'è o è vuoto, e lo segna nel registro senza il
  segreto (`sblocco_registrato`); se c'è già: 409 `sblocco_gia_registrato`. Si azzera a mano
  cancellando il file e riavviando. Accetto maiuscole e minuscole e confronto il segreto così come è
  stato registrato.

**Distrazione, fuori vista, pausa**
- Il primo minuto di distrazione è neutro (è il filtro) e fa partire l'avviso. L'episodio resta aperto
  finché non torna a studiare **o per 5 minuti di fila senza distrazione** (regole 5, rivista il 07/11):
  dentro l'episodio ogni minuto di distrazione conta subito, gli altri minuti tengono la loro classe.
  Un episodio nuovo riparte dal minuto di filtro.
- **Telecamere giù** (regole 5, rivista il 07/11): se la telecamera della stanza dove era visto per
  ultimo è giù, irraggiungibile o la visione è ferma (nessuna immagine buona per più di 30 secondi
  dentro il minuto), o lo sono tutte, il minuto è neutro e il conteggio del fuori vista resta fermo.
  Le prove che arrivano dal PC (svago su un'app permessa) valgono lo stesso. Prima di questa revisione
  le telecamere spente contavano come fuori vista: era sbagliato.
- **PC in uso = è lì** (regole 5): tasti o mouse nell'ultimo minuto, su qualunque programma (anche
  "sempre", per esempio il terminale), azzerano il fuori vista e il minuto è neutro se non lo si vede.
  L'ora dell'ultimo tocco la stima il NAS: ora di arrivo del campione meno `inattivo_secondi`. Resta
  anche la regola di prima: PC usato su una cosa permessa negli ultimi 5 minuti = conteggio fermo.
- Durante una pausa il conteggio del fuori vista è fermo (e riparte da zero quando la pausa comincia).
- Fuori vista: l'avviso al quinto minuto fa già da filtro, dal sesto conta senza un altro minuto di
  attesa.
- Sparizione pranzo andata male (fuori più di 60 minuti), decisione del coordinatore del 07/11: i
  primi 60 minuti restano neutri, sempre, niente all'indietro. Dal 61° minuto vale la regola normale
  del fuori vista senza altri 5 minuti di grazia: distrazione subito, con l'avviso a voce ("Non ti
  vedo da un'ora: da adesso il tempo conta...") e dentro i tetti, finché non ricompare o scrive una
  pausa `ps`. Stesso principio dello sforo della pausa: si paga solo il tempo oltre. Se nel frattempo
  il PC è usato su una cosa permessa quei minuti sono neutri, ma i 5 minuti di grazia non ripartono.
- PC usato su una cosa permessa mentre lo studente non si vede: neutro, e il conteggio del fuori vista
  si ferma (qualcuno è al PC). Una cosa di lavoro è "permessa" solo durante `lv`.
- Pausa sforata: fuori vista o distratto conta subito; visto (o PC toccato) e non distratto chiude lo
  sforo.
- **Una `ps` durante una pausa** (regole 8, rivista): il budget conta come disponibili anche i minuti
  non usati della pausa in corso, che si chiude solo se la nuova è accettata. Se è rifiutata resta
  quella vecchia e la risposta lo dice: "Ti restano 7 minuti di pausa: resta quella fino alle 14:11."
- La fine della pausa si arrotonda al minuto successivo; i minuti non usati si restituiscono se la
  pausa finisce prima.
- Il controllo della pausa con SemIf parte dopo 2 minuti in cui lo si vede, poi ogni 5. Durante la
  pausa anche il telefono è neutro: solo SemIf può dire "non torna" (imbroglio, una volta per pausa,
  e la pausa finisce).

**dm**
- In attesa della conferma (5 minuti) è neutro, a meno di prove. Il minuto in cui si alza è ancora
  neutro.
- Durata di `dm` accettata: da 5 a 600 minuti (le regole non danno un limite).
- **Il PC chiude il dm solo se toccato dopo la conferma** (fine del minuto in cui lo si vede
  sdraiato) e nell'ultimo minuto: il comando `dm` si scrive al PC e prima lo chiudeva da solo.
- **dm sforato**: allo scadere, se il dm era valido, non si chiude: resta "sforato" finché lo vedono
  alzarsi (o studia, o scrive una `ps`). Nel frattempo la visione continua a considerare lo studente
  la persona sdraiata nello stesso posto (stessa stanza e stesso letto/divano) e niente voce.
  `comando_attivo` per il PC torna `null` allo scadere.
- Durante un dm valido (anche sforato) una persona sdraiata non riconosciuta nella sua stanza
  (`forse_visto`) vale come lui: neutro e niente fuori vista.

**Imbroglio**
- L'episodio si chiude dopo 5 minuti senza prove. Il +30 si applica al primo minuto con la prova.
- La TV conta solo se la telecamera ha `tv: true`, lo studente non è alla scrivania, nella stanza non
  c'è nessun altro e lo schermo è chiaramente acceso.
- "Altro telefono" o "tablet" vogliono la risposta del modello del PC (foto dubbia) più una
  somiglianza bassa con il telefono registrato. Un telefono di cui non si sa di chi è vuole la
  risposta del PC; il suo telefono conta se lo schermo è acceso o lo tiene davanti a sé.
- **Senza il PC per le foto** (regole 6, nuova): se la foto dubbia del telefono resta senza risposta
  per 15 minuti, il NAS decide da solo solo con prove forti: punteggio del rilevatore almeno 0,70 in
  almeno 3 immagini di fila della stessa telecamera e somiglianza SigLIP con il suo telefono sotto
  0,10. Esito: "altro telefono" (imbroglio). Il rilevatore COCO non distingue un tablet da un
  telefono, quindi i due casi sono uno solo. Senza telefono registrato (`tf`) non decide mai. Soglie
  in `visione` (`minuti_senza_pc`, `immagini_senza_pc`, `soglia_senza_pc_rilevatore`,
  `soglia_senza_pc_diverso`), da tarare con le telecamere vere. Quando il PC risponde, si torna ad
  aspettare lui.

**Pensiero (sospeso)**
- Il "dopo" deve durare almeno quanto tutto il sospeso (non solo i 10 minuti che possono contare).
- Se il "dopo" è troppo corto non chiedo nemmeno a SemIf: neutro.

**Foto dubbie**
- Le risposte del PC valgono per i minuti successivi (non riscrivono quelli già classificati).
- A mezzanotte i lavori scadono e i ritagli si cancellano. La sezione 10 dice che a mezzanotte decide
  SemIf sulle parole del diario: siccome le risposte valgono solo per i minuti dopo, a mezzanotte una
  decisione non cambierebbe niente, quindi non la chiedo (nel dubbio, neutro).
- **Registrazione** (`lb`, `qd`, `tf`): l'oggetto deve essere trovato dal rilevatore in almeno metà
  delle foto, se no niente viene salvato e la risposta è "Non vedo un telefono (libro, quaderno) nelle
  foto: riprova inquadrandolo bene.". Prima, senza oggetto, si usava il vettore della foto intera.

**Altre scelte**
- `scrive` non si deduce mai dalle immagini: scrivere conta solo con un quaderno registrato in uso o
  con il PC.
- `/api/pc/liste` ha un campo in più, `condizionati` (programmi permessi solo con certi titoli, per
  esempio Calcolatrice e Strumento di cattura dentro `applicationframehost.exe`). Un PC che non lo
  conosce lo ignora.
- Le frasi "dm annullato" e "quota fatta" hanno la precedenza: se la voce è appena stata usata
  aspettano la fine dei 2 minuti invece di perdersi.
- **Audio di studio** solo per la voce di Lectio (programma "lectio", finché è nella lista studio):
  un film aperto con Foto o con un altro programma della lista studio non conta.
- **Programmi di Argus** nella lista "sempre" per nome esatto: `argus.agente.exe`,
  `argus.sblocco.exe`, `argus.guardiano.exe` (presi dal codice del PC). Il prefisso "argus" di prima
  lasciava passare un gioco rinominato "argusgioco.exe".
- **`liste_extra`** in `config.json` (contratto 6): voci locali aggiunte alle liste di serie, valgono
  subito ("mai" vince comunque). La versione delle liste sale di uno quando cambiano (impronta salvata
  nel database), così il PC le rilegge. I siti dei clienti sono stati tolti dalle liste di serie.

**Allineamenti col programma del PC (07/11)**
- Chiave dei verdetti: `sha1(dominio + "|" + titolo)` in esadecimale minuscolo, UTF-8, sui campi
  `dominio` e `titolo` **esattamente come arrivano** nel campione (il PC li ha già ripuliti). Il NAS
  non li normalizza di nuovo, nemmeno le maiuscole.
- Verdetto `lavoro` fuori da `lv`: il PC lo copre, quindi per il NAS non è studio, non ferma il fuori
  vista e non scusa un dispositivo non controllato in mano. Lo stesso vale per i programmi e i siti
  della lista lavoro.
- Il tasto del terminale è Ctrl+Alt+T. Nessuna frase del NAS nomina il tasto (lo mostra il PC sulla
  copertura), quindi non c'era niente da cambiare.
- **Verdetti al PC**: in `/api/pc/stato` ci sono sempre i verdetti delle chiavi viste nei campioni
  degli ultimi 10 minuti, più i 300 più recenti (prima solo gli ultimi 300: un titolo giudicato da
  tempo poteva sparire e il PC lo copriva).
- **Titoli a SemIf solo durante la quota** (modalità studio o lavoro): in libero, prima dell'arrivo,
  durante uno sblocco o con Argus inattivo non si chiede niente.
- **`non_si_capisce` vale 15 minuti**, poi il verdetto si toglie e il titolo si rigiudica. Gli altri
  verdetti valgono 30 giorni.

**Revisione indipendente (07/11)**: tutte le correzioni sopra segnate "rivista" o "nuova" hanno una
prova in `tests/test_revisione.py` che falliva prima della correzione e passa dopo.

## 5. Cosa non ho potuto provare senza le telecamere vere

Provato con telecamere finte (immagini da cartella) e con foto vere del dataset COCO, non con le Tapo.

- Lettura RTSP dalle Tapo (`stream2` continuo, `stream1` per i ritagli attraverso go2rtc) e la
  riconnessione quando la telecamera cade.
- La voce verso l'altoparlante della Tapo attraverso go2rtc (sorgente `tapo://`). L'URL e la chiamata
  sono provati con una rete finta; se non funziona, il ripiego sul PC è provato.
- Il movimento ONVIF delle Tapo (ContinuousMove + Stop, preset di partenza, ritorno dopo 60 s): la
  logica è provata con una telecamera finta, i comandi veri no. Il verso giusto si sistema con
  `inverti_pan` / `inverti_tilt`.
- Le soglie con le immagini vere della casa: viso da lontano, libri e quaderni con copertine vere,
  il telefono suo contro quello di altri, la luce della sera.
- "Schermo acceso" (TV, telefono) con le immagini vere: è una regola sulla luminosità del ritaglio,
  va tarata.
- Occhi aperti/chiusi da 2-3 metri: con un viso piccolo il modello può non rispondere (in quel caso
  niente pensiero, nel dubbio neutro).
- Velocità e memoria sul N100 vero, e la GPU del N100 con OpenVINO.
- Le reti Docker `sol-rete` e `lectio_default` e i servizi veri `sol-decisore` e `lectio-voci`
  (provati con risposte finte che seguono il contratto).
- Il "buco di 30 secondi" che rende cieca una stanza con le telecamere vere (riconnessioni RTSP brevi
  non dovrebbero bastare, una telecamera spenta sì).
- La stima dell'ultimo tocco del PC (ora di arrivo del campione meno `inattivo_secondi`, errore di
  pochi secondi) contro il PC vero.
- Le soglie della decisione senza il PC (0,70 / 0,10 / 3 immagini / 15 minuti) con telefoni veri.

## 6. Limiti noti

- **Velocità sul N100**: vedi la stima al punto 3. Con le due telecamere e lo studente in camera,
  la seconda telecamera va a 0,5 immagini al secondo e rallenta un po' la prima.
- **Identità**: se il viso non si vede mai (di spalle, cappuccio), lo studente non viene riconosciuto
  e quei minuti sono "fuori vista". Dopo 3 confronti sotto 0,2 una persona è segnata come "altro".
- **Scrivere** non si vede dalle immagini (vedi sopra).
- **Il calendario** vale solo per il 2026/27: dal 09/06/2027 nessun giorno è di scuola finché non si
  aggiunge l'anno nuovo in `argus/calendario.py`.
- **L'ora del NAS** deve essere giusta (NTP): le regole lavorano sull'ora di Roma del NAS.
- **Un solo processo**: lo stato vive in memoria e si salva a ogni minuto e a ogni comando. I minuti
  in cui il container è fermo non vengono classificati: non avanzano e non puniscono.
- **Le decisioni SemIf** non arrivate (decisore spento o che non risponde) diventano "nel dubbio,
  neutro" alla loro scadenza.

## 7. Prove

- 225 prove veloci (27 nuove per la revisione del 07/11) (`python -m pytest`): regole, comandi, liste, calendario, pomeriggi interi simulati
  minuto per minuto, API con token e rete finta (SemIf, voci, go2rtc, Home Assistant), visione con
  telecamera e PTZ finti. Tutte verdi.
- 5 prove lente (`python -m pytest -m lente -s`) con i modelli veri e foto COCO. Tutte verdi.
- `python -m pyflakes argus tests`: pulito.
- Ambiente: Python 3.12 creato con uv in `%USERPROFILE%\argus-build\venv-nas` (fuori da OneDrive),
  modelli e foto di prova in `%USERPROFILE%\argus-build\`.
