# Argus — diario

## 06/11/2026 — l'idea

L'idea: una telecamera che vede quando ci si siede alla scrivania o sul divano a cazzeggiare, e un
programma sul PC che blocca tutto tranne lo studio. Prima risposta: la telecamera da sola vede *dove*
sei, non *cosa* fai. Il chiarimento ha cambiato tutto: telecamere e programma del PC **si parlano**
(sdraiato con le cuffie + Lectio aperto = studio), la telecamera ruota e segue, e soprattutto nota i
**dispositivi non controllati** (tablet, un altro telefono, console), che è la cosa che nessun altro
pezzo può fare.

Decisioni prese insieme, in ordine:
- **Quota, non pena a tempo.** La proposta iniziale era "2 ore di blocco ogni 10 minuti persi". Scelta
  la quota giornaliera: il PC resta in modalità studio finché non è fatta, ogni minuto perso conta
  doppio con un tetto. Motivo: una pena che si può sempre ripagare studiando tiene dentro, una che
  seppellisce fa spegnere tutto.
- **Pausa "segreta" dal terminale**: `ps m: <motivo> & t: <durata>`. Tempo di lavoro: `lv30`.
  Sonno: `dm45`, sforare non punisce.
- **Il pensiero lo giudica il modello**, guardando prima, durante e dopo (non dichiarazioni a mano).
- **Leggere altro o dormire**: né avanti né punizione.
- **L'ora parte da quello che vedono le telecamere** (anche in cucina), non dal Wi-Fi: il telefono ha
  problemi e non è affidabile.
- **Classe Viva e WhatsApp** (30 minuti in più per ogni verifica nei due giorni prima): in stand-by.
- **Modelli gratis e aperti**: SemIf (la versione libera di Jev) per le decisioni, lo stesso decisore
  che usa Sol sul NAS; Qwen3.5-9B sul PC per guardare le foto dubbie.
- **Telecamere**: Tapo economiche, 2 stanze, inseguimento scritto da Argus. Nome: **Argus**, il
  guardiano dai cento occhi.

## 07/11/2026 — costruito

- Regole e contratto scritti prima del codice (`docs/regole.md`, `docs/contratto.md`).
- **Frigate tolto** rispetto al piano: l'inseguimento automatico non va con le Tapo e costava circa
  1 GB dei 3 liberi del NAS. Argus legge le telecamere da solo; go2rtc per flussi e altoparlante.
- NAS (Python) e PC (C# .NET 8) costruiti in parallelo da due costruttori, poi un revisore
  indipendente li ha fatti parlare dal vivo: protocollo allineato, ma 2 errori che rompevano il
  funzionamento (dm che si chiudeva da solo, verdetti persi dopo un mese) e diverse regole ingiuste o
  aggirabili (telecamere giù = punizione, programmi riconosciuti solo dal nome, agente chiudibile,
  sblocco fino al 2099). Tutto corretto, con prove.
- Ctrl+Alt+Spazio era già occupato su questo PC: il terminale si apre con **Ctrl+Alt+T**.
- Su C: c'erano 6,6 GB liberi: il modello del PC va in `D:\Argus\modelli`.
- Il segreto per lo sblocco d'emergenza lo genera l'installatore (con la password dell'amministratore)
  e lo registra sul NAS una volta sola: non passa mai dalle mani dello studente.
- Cervello messo sul NAS, **inattivo** finché non ci sono le telecamere (48 MB di memoria da fermo).
- Prova vera dal container con i servizi veri: la voce `supertonic` prepara una frase in 5 s. SemIf
  risponde in 15-45 s, ma alla domanda "quel tempo fermo era studio?" su un caso chiaro (storia prima e
  dopo) diceva "non studio" al 59%. Riscritta come domanda su un fatto ("prima e dopo stava lavorando
  sulla stessa materia?") con opzioni corte: 99% "studio"; col telefono dopo, 47% "non studio" (sotto
  soglia = neutro). Lezione: a SemIf si chiedono fatti, non intenzioni.

Da fare: comprare le Tapo, configurarle, tarare le soglie con le immagini di casa, installare il
programma del PC (serve l'amministratore).
