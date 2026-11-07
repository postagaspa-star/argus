"""Aiuto per le prove: un pomeriggio simulato minuto per minuto sul motore delle regole."""

from __future__ import annotations

from datetime import date, datetime, timedelta

from argus import comandi
from argus.motore import (ChiediPausa, ChiediPensiero, Classe, Episodio, Evento, Minuto, MinutoClassificato,
                          Motore, PcMinuto, Regole, SpegniPresa, Voce)
from argus.tempo import ora_roma

LUNEDI = date(2026, 11, 9)  # giorno di scuola

# Situazioni tipiche (argomenti per Minuto)
STUDIA_LIBRO = dict(visto=True, stanza="camera", dove="scrivania", posa="seduto", in_mano=frozenset({"libro_scuola"}))
STUDIA_PC = dict(visto=True, stanza="camera", dove="scrivania", posa="seduto", pc=PcMinuto("studio", True))
LAVORA_PC = dict(visto=True, stanza="camera", dove="scrivania", posa="seduto", pc=PcMinuto("lavoro", True))
TELEFONO = dict(visto=True, stanza="camera", dove="divano", posa="seduto", in_mano=frozenset({"telefono_suo"}))
FUORI = dict(visto=False)
MANGIA = dict(visto=True, stanza="salotto e cucina", dove="scrivania", posa="seduto", mangia=True)
PENSA = dict(visto=True, stanza="camera", dove="scrivania", posa="seduto", pensiero=True)
ARRIVA = dict(visto=True, stanza="salotto e cucina", dove="in_piedi", posa="in_piedi")
FERMO = dict(visto=True, stanza="camera", dove="in_piedi", posa="in_piedi")
SDRAIATO = dict(visto=True, stanza="camera", dove="letto", posa="sdraiato")
DORME = dict(visto=True, stanza="camera", dove="letto", posa="sdraiato", dorme=True)
TABLET = dict(visto=True, stanza="camera", dove="divano", posa="seduto", in_mano=frozenset({"tablet"}))
TV_CONSOLE = dict(visto=True, stanza="salotto e cucina", dove="divano", posa="seduto",
                  in_mano=frozenset({"controller"}), schermi=frozenset({"tv"}))


def hm(testo: str, giorno: date = LUNEDI) -> datetime:
    h, m = testo.split(":")[:2]
    s = int(testo.split(":")[2]) if testo.count(":") == 2 else 0
    return ora_roma(giorno.year, giorno.month, giorno.day, int(h), int(m), s)


class Sim:
    def __init__(self, giorno: date = LUNEDI, regole: Regole | None = None, motore: Motore | None = None):
        self.giorno = giorno
        self.m = motore or Motore(regole or Regole(), oggi=giorno)
        self.effetti: list = []
        self.classi: dict[datetime, MinutoClassificato] = {}

    # --- tempo ---
    def ora(self, testo: str, giorno: date | None = None) -> datetime:
        return hm(testo, giorno or self.giorno)

    def minuto(self, quando: str | datetime, **kw) -> list:
        ora = quando if isinstance(quando, datetime) else self.ora(quando)
        kw = dict(kw)
        for chiave in ("in_mano", "schermi", "stanze_cieche"):
            if chiave in kw and not isinstance(kw[chiave], frozenset):
                kw[chiave] = frozenset(kw[chiave])
        eff = self.m.tick(Minuto(ora=ora, **kw))
        self._registra(eff)
        return eff

    def tratto(self, da: str, a: str, giorno: date | None = None, **kw) -> list:
        """Un minuto alla volta da `da` (compreso) ad `a` (escluso)."""
        inizio = self.ora(da, giorno)
        fine = self.ora(a, giorno)
        if fine <= inizio:
            fine += timedelta(days=1)
        eff = []
        t = inizio
        while t < fine:
            eff += self.minuto(t, **kw)
            t += timedelta(minutes=1)
        return eff

    def cmd(self, testo: str, quando: str):
        c = comandi.analizza(testo)
        r = self.m.comando(c, self.ora(quando))
        self._registra(r.effetti)
        return r

    def _registra(self, eff: list) -> None:
        self.effetti += eff
        for e in eff:
            if isinstance(e, MinutoClassificato):
                self.classi[e.ora] = e

    # --- letture ---
    def classe(self, quando: str) -> Classe:
        return self.classi[self.ora(quando)].classe

    def conta(self, classe: Classe, da: str | None = None, a: str | None = None) -> int:
        n = 0
        for ora, mc in self.classi.items():
            if da and ora < self.ora(da):
                continue
            if a and ora >= self.ora(a):
                continue
            if mc.classe == classe:
                n += 1
        return n

    @property
    def voci(self) -> list[Voce]:
        return [e for e in self.effetti if isinstance(e, Voce)]

    def eventi(self, tipo: str) -> list[Evento]:
        return [e for e in self.effetti if isinstance(e, Evento) and e.tipo == tipo]

    def episodi(self, tipo: str) -> list[Episodio]:
        return [e for e in self.effetti if isinstance(e, Episodio) and e.tipo == tipo]

    @property
    def domande_pensiero(self) -> list[ChiediPensiero]:
        return [e for e in self.effetti if isinstance(e, ChiediPensiero)]

    @property
    def domande_pausa(self) -> list[ChiediPausa]:
        return [e for e in self.effetti if isinstance(e, ChiediPausa)]

    @property
    def prese(self) -> list[SpegniPresa]:
        return [e for e in self.effetti if isinstance(e, SpegniPresa)]

    def arriva(self, quando: str = "13:30", visto_prima: str | None = "07:20", **come) -> None:
        """Lo studente esce la mattina e arriva a casa (di solito in piedi in cucina)."""
        if visto_prima:
            self.minuto(visto_prima, visto=True, stanza="camera", dove="in_piedi", posa="in_piedi")
        self.minuto(quando, **(come or ARRIVA))
        assert self.m.giorno.arrivo == self.ora(quando)
