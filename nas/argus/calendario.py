"""Giorni di scuola: regole sezioni 2 e 13 (calendario scolastico del Veneto 2026/27).

Fuori dall'anno 2026/27 non c'è scuola finché qualcuno non aggiunge il calendario nuovo:
è la scelta prudente (niente quota invece di una quota sbagliata).
"""

from __future__ import annotations

import re
from datetime import date

INIZIO_LEZIONI = date(2026, 9, 10)
FINE_LEZIONI = date(2027, 6, 8)

# Giorni senza scuola dentro il periodo delle lezioni (estremi compresi).
VACANZE: tuple[tuple[date, date], ...] = (
    (date(2026, 10, 30), date(2026, 11, 2)),
    (date(2026, 12, 7), date(2026, 12, 8)),
    (date(2026, 12, 24), date(2027, 1, 6)),
    (date(2027, 2, 8), date(2027, 2, 13)),
    (date(2027, 3, 25), date(2027, 3, 30)),
    (date(2027, 4, 25), date(2027, 4, 25)),
    (date(2027, 4, 29), date(2027, 5, 1)),
    (date(2027, 5, 31), date(2027, 6, 2)),
)


def leggi_patrono(valore: str | None) -> tuple[int, int] | None:
    """Il patrono in config: "GG/MM" oppure "MM-GG" oppure una data "AAAA-MM-GG". Ritorna (mese, giorno)."""
    if not valore:
        return None
    testo = str(valore).strip()
    m = re.fullmatch(r"(\d{1,2})/(\d{1,2})", testo)
    if m:
        return int(m.group(2)), int(m.group(1))
    m = re.fullmatch(r"(\d{4})-(\d{1,2})-(\d{1,2})", testo)
    if m:
        return int(m.group(2)), int(m.group(3))
    m = re.fullmatch(r"(\d{1,2})-(\d{1,2})", testo)
    if m:
        return int(m.group(1)), int(m.group(2))
    raise ValueError(f"Patrono non valido: {valore!r} (scrivi per esempio \"25/04\")")


def giorno_di_scuola(giorno: date, sabato_scuola: bool = False, patrono: str | None = None) -> bool:
    if giorno < INIZIO_LEZIONI or giorno > FINE_LEZIONI:
        return False
    dow = giorno.weekday()  # 0 = lunedì
    if dow == 6:
        return False
    if dow == 5 and not sabato_scuola:
        return False
    for inizio, fine in VACANZE:
        if inizio <= giorno <= fine:
            return False
    p = leggi_patrono(patrono)
    if p is not None and (giorno.month, giorno.day) == p:
        return False
    return True
