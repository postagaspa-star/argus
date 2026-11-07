"""Dalle osservazioni (una per immagine analizzata) al riassunto del minuto per il motore.

Puro, senza modelli. Le soglie sono prudenti: perché una cosa entri nel minuto deve esserci per
buona parte del tempo in cui lo studente si vede (una prova chiara, non un'immagine sola).
"""

from __future__ import annotations

import threading
from collections import Counter, deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta

MIN_IMMAGINI_VISTO = 2
FRAZIONE_OGGETTI = 0.5
FRAZIONE_SCHERMI = 0.5
FRAZIONE_MANGIA = 0.3
FRAZIONE_DORME = 0.6
FRAZIONE_SCRIVE = 0.5
FRAZIONE_PENSIERO = 0.7
# Una stanza è "cieca" se nel minuto la sua telecamera ha un buco di immagini analizzate più lungo di
# così (telecamera giù, irraggiungibile o visione ferma). Regole, sezione 5: senza occhi niente prova.
BUCO_MASSIMO = timedelta(seconds=30)


@dataclass
class Osservazione:
    ora: datetime
    telecamera: str
    stanza: str
    ok: bool = True
    studente: bool = False
    forse: bool = False
    dove: str | None = None
    posa: str | None = None
    gettoni: frozenset[str] = frozenset()  # per il motore: telefono_suo, libro_scuola, tablet...
    schermi: frozenset[str] = frozenset()  # schermi non controllati accesi davanti: tv, tablet...
    mangia: bool = False
    scrive: bool = False
    occhi: str | None = None
    fermo: bool | None = None
    altre_persone: int = 0
    descrizione: dict = field(default_factory=dict)  # per il diario: in_mano, vicino, schermi a parole
    centro: tuple[float, float] | None = None


class Aggregatore:
    def __init__(self, minuti_memoria: int = 4, stanze: dict[str, str] | None = None):
        """stanze = {id telecamera: stanza} delle telecamere configurate."""
        self.stanze = dict(stanze or {})
        self._oss: deque[Osservazione] = deque()
        self._lock = threading.Lock()
        self._memoria = timedelta(minutes=minuti_memoria)
        self.ultima_stanza: str | None = None

    def aggiungi(self, o: Osservazione) -> None:
        with self._lock:
            self._oss.append(o)
            if o.studente:
                self.ultima_stanza = o.stanza
            limite = o.ora - self._memoria
            while self._oss and self._oss[0].ora < limite:
                self._oss.popleft()

    def osservazioni(self, da: datetime, a: datetime) -> list[Osservazione]:
        with self._lock:
            return [o for o in self._oss if da <= o.ora < a]

    def minuto(self, inizio: datetime) -> dict:
        tutte = self.osservazioni(inizio, inizio + timedelta(minutes=1))
        return riassumi_minuto(tutte, inizio, self.stanze or None)

    def scena(self, ora: datetime, entro_secondi: int = 15) -> dict:
        recenti = self.osservazioni(ora - timedelta(seconds=entro_secondi), ora + timedelta(seconds=1))
        con_lui = [o for o in recenti if o.studente]
        if not con_lui:
            return {"visto": False, "ultima_stanza": self.ultima_stanza}
        o = con_lui[-1]
        return {"visto": True, "stanza": o.stanza, "dove": o.dove, "posa": o.posa, "occhi": o.occhi,
                "fermo": bool(o.fermo), "mangia": o.mangia, "altre_persone": o.altre_persone,
                "in_mano": o.descrizione.get("in_mano", []), "vicino": o.descrizione.get("vicino", []),
                "schermi": o.descrizione.get("schermi", [])}


def _moda(valori: list) -> object | None:
    valori = [v for v in valori if v is not None]
    if not valori:
        return None
    return Counter(valori).most_common(1)[0][0]


def stanze_cieche(tutte: list[Osservazione], inizio: datetime, stanze: dict[str, str]) -> frozenset[str]:
    """Le stanze rimaste senza occhi nel minuto: ogni loro telecamera ha avuto un buco di immagini
    buone più lungo di 30 s (giù, irraggiungibile, visione ferma)."""
    fine = inizio + timedelta(minutes=1)
    per_stanza: dict[str, list[str]] = {}
    for id_t, stanza in stanze.items():
        per_stanza.setdefault(stanza, []).append(id_t)
    return frozenset(stanza for stanza, ids in per_stanza.items()
                     if all(_buco(tutte, id_t, inizio, fine) for id_t in ids))


def _buco(tutte: list[Osservazione], id_t: str, inizio: datetime, fine: datetime) -> bool:
    punti = [inizio] + sorted(o.ora for o in tutte if o.telecamera == id_t and o.ok) + [fine]
    return any(b - a > BUCO_MASSIMO for a, b in zip(punti, punti[1:]))


def riassumi_minuto(tutte: list[Osservazione], inizio: datetime | None = None,
                    stanze: dict[str, str] | None = None) -> dict:
    """`inizio` e `stanze` servono per dire quali stanze sono rimaste senza occhi (stanze_cieche)."""
    if inizio is not None and stanze:
        cieche = stanze_cieche(tutte, inizio, stanze)
        telecamere_ok = cieche != frozenset(stanze.values())
    else:
        cieche = frozenset()
        telecamere_ok = any(o.ok for o in tutte)
    con_lui = [o for o in tutte if o.studente]
    forse = sum(1 for o in tutte if o.forse)
    if len(con_lui) < MIN_IMMAGINI_VISTO:
        return {"telecamere_ok": telecamere_ok, "stanze_cieche": cieche, "visto": False,
                "forse_visto": forse >= MIN_IMMAGINI_VISTO}
    n = len(con_lui)
    conteggio_gettoni: Counter = Counter()
    conteggio_schermi: Counter = Counter()
    for o in con_lui:
        conteggio_gettoni.update(o.gettoni)
        conteggio_schermi.update(o.schermi)
    in_mano = frozenset(g for g, c in conteggio_gettoni.items() if c / n >= FRAZIONE_OGGETTI)
    schermi = frozenset(s for s, c in conteggio_schermi.items() if c / n >= FRAZIONE_SCHERMI)
    dorme = sum(1 for o in con_lui if o.posa == "sdraiato" and o.occhi == "chiusi") / n >= FRAZIONE_DORME
    pensiero = sum(1 for o in con_lui if o.fermo and not o.gettoni and o.occhi == "aperti"
                   and o.dove in ("scrivania", "divano")) / n >= FRAZIONE_PENSIERO
    return {
        "telecamere_ok": telecamere_ok,
        "stanze_cieche": cieche,
        "visto": True,
        "forse_visto": False,
        "stanza": _moda([o.stanza for o in con_lui]),
        "dove": _moda([o.dove for o in con_lui]),
        "posa": _moda([o.posa for o in con_lui]),
        "in_mano": in_mano,
        "schermi": schermi,
        "mangia": sum(1 for o in con_lui if o.mangia) / n >= FRAZIONE_MANGIA,
        "scrive": sum(1 for o in con_lui if o.scrive) / n >= FRAZIONE_SCRIVE,
        "dorme": dorme,
        "pensiero": pensiero and not in_mano,
    }
