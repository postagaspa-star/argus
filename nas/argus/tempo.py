"""Orologio e piccoli aiuti per le ore.

Il NAS è l'orologio che conta (contratto, sezione 2): fuso Europe/Rome.
L'orologio è iniettabile, così le prove possono simulare un pomeriggio intero in un attimo.
"""

from __future__ import annotations

import math
import threading
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

FUSO = ZoneInfo("Europe/Rome")


class Orologio:
    """Interfaccia: chi vuole l'ora la chiede qui, mai a datetime.now()."""

    def adesso(self) -> datetime:  # pragma: no cover - interfaccia
        raise NotImplementedError


class OrologioReale(Orologio):
    def adesso(self) -> datetime:
        return datetime.now(FUSO)


class OrologioFinto(Orologio):
    """Orologio per le prove: fermo finché non lo si fa avanzare."""

    def __init__(self, inizio: datetime):
        self._ora = a_fuso(inizio)
        self._lock = threading.Lock()

    def adesso(self) -> datetime:
        with self._lock:
            return self._ora

    def avanza(self, **kwargs) -> datetime:
        with self._lock:
            self._ora = self._ora + timedelta(**kwargs)
            return self._ora

    def imposta(self, ora: datetime) -> None:
        with self._lock:
            self._ora = a_fuso(ora)


def a_fuso(ora: datetime) -> datetime:
    """Porta un datetime nel fuso di Roma (se è senza fuso, lo considera già ora di Roma)."""
    if ora.tzinfo is None:
        return ora.replace(tzinfo=FUSO)
    return ora.astimezone(FUSO)


def ora_roma(anno: int, mese: int, giorno: int, ore: int = 0, minuti: int = 0, secondi: int = 0) -> datetime:
    return datetime(anno, mese, giorno, ore, minuti, secondi, tzinfo=FUSO)


def inizio_minuto(ora: datetime) -> datetime:
    return ora.replace(second=0, microsecond=0)


def arrotonda_su_minuto(ora: datetime) -> datetime:
    """Arrotonda in su al minuto intero (15:52:20 -> 15:53:00; 15:52:00 resta così)."""
    base = inizio_minuto(ora)
    if base == ora:
        return base
    return base + timedelta(minutes=1)


def minuti_tra(da: datetime, a: datetime) -> float:
    return (a - da).total_seconds() / 60.0


def minuti_interi_su(da: datetime, a: datetime) -> int:
    """Minuti trascorsi arrotondati in su (mai negativi)."""
    m = minuti_tra(da, a)
    if m <= 0:
        return 0
    return int(math.ceil(m - 1e-9))


def hhmm(ora: datetime | None) -> str | None:
    if ora is None:
        return None
    return a_fuso(ora).strftime("%H:%M")


def iso(ora: datetime | None) -> str | None:
    if ora is None:
        return None
    return a_fuso(ora).isoformat(timespec="seconds")


def da_iso(testo: str | None) -> datetime | None:
    if not testo:
        return None
    return a_fuso(datetime.fromisoformat(testo))


def mezzanotte_dopo(ora: datetime) -> datetime:
    domani = ora.date() + timedelta(days=1)
    return datetime.combine(domani, time(0, 0), tzinfo=FUSO)


def fine_giornata(giorno: date) -> datetime:
    return datetime.combine(giorno, time(23, 59, 59), tzinfo=FUSO)
