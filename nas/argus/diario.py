"""Il diario a parole: una riga ogni 10 secondi mentre Argus è attivo (contratto, sezione 5).

Serve a SemIf per capire i casi dubbi (pensiero, motivo della pausa, lettura): lui non vede le
immagini, legge solo queste righe. Per questo sono frasi semplici e sempre uguali nella forma.
"""

from __future__ import annotations

from datetime import datetime

DOVE = {"scrivania": "alla scrivania o al tavolo", "divano": "sul divano", "letto": "sul letto",
        "in_piedi": "in piedi"}
POSA = {"seduto": "seduto", "sdraiato": "sdraiato", "in_piedi": "in piedi", "chino": "chino sul tavolo"}
NOMI_PC = {"studio": "studio", "lavoro": "lavoro", "svago": "svago", "attesa": "in attesa di giudizio",
           "dubbio": "non si capisce", "coperto": "coperto da Argus", "pactum": "coperto da Pactum",
           "bloccato": "schermo bloccato", "mai": "vietato", "altro": "non permesso", "sempre": "sempre permesso"}


def _elenco(voci: list[str] | None) -> str:
    return ", ".join(voci) if voci else "niente"


def riga(ora: datetime, scena: dict | None, pc: dict | None, pc_categoria: str | None,
         comando: dict | None, pausa_motivo: str | None = None) -> str:
    parti = [ora.strftime("%H:%M:%S")]
    if scena is None or not scena.get("visto"):
        stanza = (scena or {}).get("ultima_stanza")
        parti.append("Lo studente non si vede" + (f" (visto l'ultima volta in {stanza})" if stanza else "") + ".")
    else:
        dove = DOVE.get(scena.get("dove") or "", "posto non chiaro")
        posa = POSA.get(scena.get("posa") or "", "posa non chiara")
        stanza = (scena.get("stanza") or "stanza ?").capitalize()
        frase = f"{stanza}, {dove}, {posa}"
        if scena.get("occhi"):
            frase += f", occhi {scena['occhi']}"
        if scena.get("fermo"):
            frase += ", fermo"
        parti.append(frase + ".")
        parti.append(f"In mano: {_elenco(scena.get('in_mano'))}.")
        if scena.get("vicino"):
            parti.append(f"Vicino: {_elenco(scena.get('vicino'))}.")
        if scena.get("schermi"):
            parti.append(f"Schermi accesi davanti: {_elenco(scena.get('schermi'))}.")
        if scena.get("mangia"):
            parti.append("Sta mangiando.")
        if scena.get("altre_persone"):
            parti.append(f"Altre persone nella stanza: {scena['altre_persone']}.")
    if pc:
        processo = pc.get("processo") or "?"
        testo_pc = f"PC: {processo}"
        if pc.get("dominio"):
            testo_pc += f" su {pc['dominio']}"
        if pc.get("titolo"):
            testo_pc += f", «{pc['titolo']}»"
        if pc_categoria:
            testo_pc += f" ({NOMI_PC.get(pc_categoria, pc_categoria)})"
        inattivo = pc.get("inattivo_secondi")
        if inattivo is not None and inattivo >= 60:
            testo_pc += f", nessun tasto da {int(inattivo) // 60} min"
        if pc.get("audio"):
            testo_pc += f", audio da {', '.join(pc['audio'])}"
        parti.append(testo_pc + ".")
    else:
        parti.append("PC: nessuna notizia.")
    if comando:
        nomi = {"ps": "pausa", "dm": "dormo", "lv": "lavoro"}
        testo_cmd = f"Comando: {nomi.get(comando['tipo'], comando['tipo'])}"
        if comando["tipo"] == "ps" and pausa_motivo:
            testo_cmd += f" «{pausa_motivo}»"
        parti.append(testo_cmd + f" fino alle {comando['fino']}.")
    return " ".join(parti)


def compatta(righe: list[str], massimo: int = 80) -> list[str]:
    """Unisce le righe uguali di fila ("15:41:00-15:44:50 ...") e tiene al massimo `massimo` righe."""
    gruppi: list[list[str]] = []  # [inizio, fine, testo]
    for r in righe:
        ora, _, testo = r.partition(" ")
        if gruppi and gruppi[-1][2] == testo:
            gruppi[-1][1] = ora
        else:
            gruppi.append([ora, ora, testo])
    uscita = [f"{a}-{b} {t}" if a != b else f"{a} {t}" for a, b, t in gruppi]
    if len(uscita) > massimo:
        meta = massimo // 2
        tolte = len(uscita) - 2 * meta
        uscita = uscita[:meta] + [f"(... {tolte} righe saltate ...)"] + uscita[-meta:]
    return uscita
