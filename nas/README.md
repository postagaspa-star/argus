# Argus sul NAS

Argus è il sistema anti-distrazione che lo studente si è scelto da solo. Questa cartella è il pezzo
che gira sul NAS: guarda le telecamere, decide minuto per minuto se si sta studiando, tiene il conto
della quota del giorno e dice al programma del PC cosa può girare. Le regole complete sono in
`docs/regole.md`, il modo in cui i pezzi si parlano in `docs/contratto.md`.

## Cosa fa, in breve

- **Il giorno**: nei giorni di scuola (calendario del Veneto 2026/27) la quota parte quando la
  telecamera riconosce lo studente dopo le 11:00, dopo almeno 3 ore che non lo vedeva.
- **La quota**: 60 minuti di base, più quello che manca da ieri (al massimo 30), più le aggiunte
  per le distrazioni e gli imbrogli (al massimo 120 in tutto al giorno).
- **Ogni minuto** diventa studio, lavoro, neutro, distrazione o imbroglio. Nel dubbio è neutro:
  per punire serve una prova chiara.
- **I comandi** si scrivono nel programma del PC: `ps` (pausa), `lv` (lavoro), `dm` (dormo),
  `st` (come sto andando), `lb`/`qd`/`vs`/`tf` (registra libri, quaderni, viso, telefono),
  `ag`/`tg` (liste), `aiuto`.
- **La voce**: le frasi escono dall'altoparlante della telecamera della stanza; se non va, le dice
  il PC. Mai durante `dm`, al massimo una ogni 2 minuti.
- **Le decisioni difficili** (un pensiero è studio? quel titolo è svago? quel motivo di pausa è
  vero?) le chiede al decisore di Sol, che è già sul NAS.
- **Le foto dubbie** (cosa ha in mano? quello schermo è acceso?) le manda al PC, che le guarda con
  il suo modello e risponde.
- **Le immagini non si salvano.** Restano solo i ritagli delle foto dubbie, cancellati appena
  giudicati o a mezzanotte, e le foto che lo studente registra con `lb`, `qd`, `vs`, `tf`.
- **Senza occhi niente punizione**: se la telecamera della stanza dove lo studente era (o tutte) è
  giù, o la visione si è fermata, quei minuti sono neutri.

Senza telecamere nella configurazione Argus resta **inattivo**: risponde al PC, ma non conta
niente, non punisce e non carica i modelli. Si può quindi installare prima che arrivino le telecamere.

## I file

| Cosa | Dove |
|---|---|
| Programma | `argus/` (regole in `motore.py`, collegamento col PC in `api.py` e `servizio.py`, visione in `visione/`) |
| Prove automatiche | `tests/` |
| Container | `Dockerfile`, `docker-compose.yml`, `go2rtc/go2rtc.yaml` |
| Esempi da copiare | `.env.example` (password), `config.esempio.json` (telecamere) |

Sul NAS, nella cartella `data/` (creata da sola):

- `config.json`: la configurazione. Al primo avvio se ne crea una senza telecamere.
- `token-pc.txt`: la chiave che il PC deve usare. Si crea al primo avvio: va copiata nel programma del PC.
- `token-sblocco.txt`: il secondo segreto, solo per lo sblocco d'emergenza. **Non lo crea il NAS**:
  lo genera l'installatore del PC e lo manda al NAS una volta sola, così non passa mai per le mani
  dello studente. Finché non c'è, nessuno sblocco d'emergenza è possibile.
- `argus.db`: il database (giorni, minuti, episodi, diario, registro, liste, vettori dei registrati).
- `registrati/`: le foto di libri, quaderni, viso e telefono.
- `voce/`: le frasi già pronunciate, così non si rifanno ogni volta.

## Installare sul NAS

1. Copiare la cartella `nas/` sul NAS, per esempio in `/volume1/docker/Argus-NAS`.
2. Copiare `.env.example` in `.env` e scrivere i valori (vedi sotto per le Tapo).
3. Controllare che esistano le reti degli altri due servizi che Argus usa:
   `docker network ls` deve mostrare `sol-rete` (il decisore di Sol) e `lectio_default` (le voci di
   Lectio). Se una manca, quel servizio non è acceso: Argus parte lo stesso, ma senza decisioni
   (resta tutto neutro) o senza voce dalla telecamera.
4. `docker compose up -d --build`. La prima volta scarica i modelli (circa 185 MB) e li controlla.
5. Prova: `http://<indirizzo del NAS>:8700/api/salute` deve rispondere con `"ok": true`.
6. Aprire `data/token-pc.txt` e dare la chiave all'installatore del PC. L'installatore registra da
   solo il segreto dello sblocco sul NAS (`data/token-sblocco.txt` compare dopo l'installazione).
7. Quando ci sono le telecamere: copiare in `data/config.json` le telecamere da
   `config.esempio.json` e riavviare: `docker compose restart argus`.

### Azzerare il segreto dello sblocco

Il NAS accetta il segreto una volta sola: se si reinstalla il programma del PC, la registrazione
nuova viene rifiutata ("Sul NAS c'è già un segreto di sblocco: va azzerato a mano da chi gestisce il
NAS."). Per azzerarlo, sul NAS:

1. cancellare il file `data/token-sblocco.txt` (nella cartella di Argus, per esempio
   `/volume1/docker/Argus-NAS/data/token-sblocco.txt`);
2. `docker compose restart argus`;
3. rifare l'installazione sul PC, che registra il segreto nuovo.

## Configurare una Tapo

Le Tapo hanno un **account della telecamera** separato dall'account TP-Link: è quello che serve
per vedere le immagini (RTSP) e per muoverla (ONVIF).

1. App Tapo → la telecamera → ingranaggio (Impostazioni) → **Impostazioni avanzate** →
   **Account della telecamera**. Scegliere un nome utente e una password.
2. Nel file `.env`: `TAPO_UTENTE` e `TAPO_CAMERA_PASSWORD` con quei valori, `TAPO_CAMERA_IP` con
   l'indirizzo della telecamera (si legge nell'app, in Informazioni sul dispositivo). Conviene
   fissarlo nel router, così non cambia.
3. Le Tapo hanno due flussi sulla porta 554: `stream1` (alta risoluzione, usato solo per i ritagli)
   e `stream2` (bassa risoluzione, usato per guardare). ONVIF risponde sulla porta **2020**.
   `config.esempio.json` è già scritto così.
4. **Altoparlante**: per far parlare la telecamera serve la password dell'account TP-Link (quello
   dell'app), in `TAPO_CLOUD_PASSWORD`. Nelle versioni nuove dell'app va anche acceso, una volta
   sola, **Io → Servizi di terze parti → Compatibilità con terze parti** (in inglese: Me →
   Third-Party Services → Third-Party Compatibility): senza, go2rtc può non riuscire ad entrare.
   Se non si vuole mettere la password, si toglie la riga `altoparlante` e le frasi le dice il PC.
   Modello consigliato: Tapo C210 (3 MP, gira di 360° e si inclina di 114°). Le Mercusys sembrano
   uguali, ma l'altoparlante con go2rtc non è confermato e si inclinano solo di 70°.
5. **Movimento**: Argus muove la telecamera per tenere lo studente al centro e dopo 60 secondi senza
   di lui torna dove era partita. Se gira dalla parte sbagliata, mettere `"inverti_pan": true` (o
   `"inverti_tilt": true`) in quella telecamera. Se il movimento non funziona per 3 volte di fila,
   Argus smette di provarci e lo annota nel database (evento `ptz_spento`): in quel caso conviene accendere nell'app l'**inseguimento
   del movimento** della telecamera, come riserva.
6. **TV**: nella stanza dove c'è solo il monitor del PC mettere `"tv": false`. Così uno schermo
   acceso lì non viene mai scambiato per una televisione.

Due telecamere in `config.esempio.json`: `camera` (scrivania e letto, `tv: false`) e `salotto`
(`tv: true`). Per la seconda servono anche `TAPO_SALOTTO_IP` e `TAPO_SALOTTO_PASSWORD`.

## Primi passi dello studente

Appena le telecamere funzionano, dal programma del PC:

1. `vs`: registra il viso (10 scatti, girando un po' la testa). **Senza questo Argus non lo
   riconosce e non parte niente.**
2. `tf`: registra il suo telefono (6 scatti: davanti, dietro, di lato).
3. `lb matematica`, `qd storia`, ...: registra libri e quaderni di scuola (copertina e 2-3 pagine
   aperte). `lb` da solo fa vedere l'elenco, `lb via matematica` lo toglie.

Per `lb`, `qd` e `tf` l'oggetto deve vedersi in almeno metà delle foto, se no Argus risponde per
esempio "Non vedo un telefono nelle foto: riprova inquadrandolo bene." e non salva niente.

## Siti e programmi solo di casa (`liste_extra`)

Le liste di serie sono nel codice, che è pubblico. I siti dei clienti e i programmi fatti in casa si
scrivono solo nel `config.json` del NAS, e valgono subito (dopo il riavvio di `argus`):

```json
"liste_extra": {"lavoro": {"programmi": ["gestionale.exe"], "siti": ["cliente-esempio.it"]},
                "studio": {"programmi": [], "siti": []}}
```

Quando cambiano, il numero di versione delle liste sale e il PC le rilegge da solo.

## Prese smart (facoltativo)

Se c'è Home Assistant, Argus può spegnere la presa della TV (o della console) quando la trova accesa mentre la quota non è
fatta: è un imbroglio, e oltre al +30 la spegne.
In `config.json`:

```json
"home_assistant": "http://<indirizzo di Home Assistant>:8123",
"prese": [{"dispositivo": "tv", "stanza": "salotto e cucina", "entity_id": "switch.tv"}]
```

e in `.env` un token di accesso a lunga durata in `HA_TOKEN` (Home Assistant → profilo → Sicurezza).

## GPU del N100 (facoltativo)

Di base tutto gira sul processore. Per far girare il rilevatore di oggetti sulla scheda grafica del
N100: in `docker-compose.yml` togliere i `#` davanti a `devices: /dev/dri` e costruire con
`docker compose build --build-arg GPU_INTEL=1`. Se la GPU non risponde, Argus torna da solo al
processore.

## Le prove

Sul PC (Python 3.12, fuori da OneDrive):

```
python -m pip install -r requirements.txt
python -m pip install --no-deps -r requirements-mediapipe.txt
python -m pip install -r requirements-prove.txt
python -m pytest
```

Così girano le prove veloci (regole, comandi, collegamento col PC, visione con telecamere finte).
Pomeriggi interi sono simulati minuto per minuto.

Le prove lente usano i modelli veri e qualche foto vera (dal dataset COCO, scaricate fuori dal repo
in `~/argus-build/`):

```
python -m pytest -m lente -s
```

Dentro il container, dopo il deploy:

```
docker exec argus sh -c "pip install -q -r requirements-prove.txt && python -m pytest"
docker exec -e ARGUS_MODELLI_PROVA=/modelli argus sh -c "python -m pytest -m lente -s"
```

## Quando qualcosa non va

- `docker logs argus --tail 100`: il registro del programma. Con `ARGUS_LOG=DEBUG` in `.env` dice
  di più.
- `/api/salute` dice in che stato è ogni telecamera e se il decisore e le voci rispondono.
- Se il NAS è stato spento, alla riaccensione Argus riprende dal punto in cui era (i giorni passati
  vengono chiusi come a mezzanotte).
