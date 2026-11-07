"""Lettura dei comandi del terminale (regole sezione 8). Puro: solo testo dentro, oggetti fuori.

Maiuscole e minuscole valgono uguale. La sintassi della pausa è esatta:
    ps m: <motivo> & t: <durata>
con durata `10`, `10 min`, `10m`, `1h`, `1h30`, `90 min` (e poche varianti con gli spazi).
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from . import testi

LV_MIN, LV_MAX = 5, 240
DM_MIN, DM_MAX = 5, 600
NOME_MAX = 40


@dataclass(frozen=True)
class CmdPausa:
    motivo: str
    minuti: int


@dataclass(frozen=True)
class CmdLavoro:
    minuti: int  # 0 = chiude


@dataclass(frozen=True)
class CmdDormo:
    minuti: int


@dataclass(frozen=True)
class CmdStato:
    pass


@dataclass(frozen=True)
class CmdRegistra:
    tipo: str  # lb | qd | vs | tf
    azione: str  # registra | elenco | togli
    nome: str | None = None


@dataclass(frozen=True)
class CmdLista:
    azione: str  # ag | tg
    lista: str  # studio | lavoro
    voce: str


@dataclass(frozen=True)
class CmdAiuto:
    pass


@dataclass(frozen=True)
class CmdErrore:
    risposta: str


Comando = CmdPausa | CmdLavoro | CmdDormo | CmdStato | CmdRegistra | CmdLista | CmdAiuto | CmdErrore

_RE_MINUTI = re.compile(r"^(\d{1,3})\s*(m|min|minuti|minuto)?$")
_RE_ORE = re.compile(r"^(\d{1,2})\s*(h|ora|ore)\s*(?:(\d{1,2})\s*(m|min|minuti)?)?$")
_RE_PAUSA = re.compile(r"^ps\s+m\s*:\s*(?P<motivo>[^&]*?)\s*&\s*t\s*:\s*(?P<durata>.+?)\s*$")
_RE_NOME = re.compile(r"^[\w][\w '\-.]*$", re.UNICODE)


def durata_minuti(testo: str) -> int | None:
    """Legge una durata e la porta in minuti. None se non la capisce o se è zero."""
    t = " ".join(testo.strip().lower().split())
    m = _RE_MINUTI.match(t)
    if m:
        n = int(m.group(1))
        return n if n > 0 else None
    m = _RE_ORE.match(t)
    if m:
        ore = int(m.group(1))
        minuti = int(m.group(3)) if m.group(3) else 0
        if minuti >= 60:
            return None
        n = ore * 60 + minuti
        return n if n > 0 else None
    return None


def _pulisci(testo: str) -> str:
    return " ".join((testo or "").strip().split())


def _nome_valido(nome: str) -> bool:
    return 0 < len(nome) <= NOME_MAX and bool(_RE_NOME.match(nome))


def analizza(testo: str) -> Comando:
    t = _pulisci(testo)
    basso = t.lower()
    if not basso:
        return CmdErrore(testi.NON_CAPITO)
    parole = basso.split(" ")
    capo = parole[0]

    # ps (anche "ps" attaccato: "psm: ..." non vale, serve lo spazio come nell'esempio)
    if capo == "ps" or basso.startswith("ps "):
        m = _RE_PAUSA.match(basso)
        if not m:
            return CmdErrore(testi.ESEMPIO_PS)
        # Il motivo si prende dal testo originale (con le maiuscole), stesso tratto.
        motivo = _pulisci(t[m.start("motivo"):m.end("motivo")])
        minuti = durata_minuti(m.group("durata"))
        if not motivo or minuti is None:
            return CmdErrore(testi.ESEMPIO_PS)
        return CmdPausa(motivo=motivo, minuti=minuti)

    m = re.fullmatch(r"lv\s*(\d{1,4})", basso)
    if m:
        n = int(m.group(1))
        if n == 0 or LV_MIN <= n <= LV_MAX:
            return CmdLavoro(minuti=n)
        return CmdErrore(testi.ESEMPIO_LV)
    if capo == "lv" or re.fullmatch(r"lv\S+", capo):
        return CmdErrore(testi.ESEMPIO_LV)

    m = re.fullmatch(r"dm\s*(\d{1,4})", basso)
    if m:
        n = int(m.group(1))
        if DM_MIN <= n <= DM_MAX:
            return CmdDormo(minuti=n)
        return CmdErrore(testi.ESEMPIO_DM)
    if capo == "dm" or re.fullmatch(r"dm\S+", capo):
        return CmdErrore(testi.ESEMPIO_DM)

    if capo == "st":
        return CmdStato() if len(parole) == 1 else CmdErrore(testi.ESEMPIO_ST)

    if capo == "aiuto" or basso in ("help", "?"):
        return CmdAiuto()

    if capo in ("lb", "qd"):
        esempio = testi.ESEMPIO_LB if capo == "lb" else testi.ESEMPIO_QD
        resto = _pulisci(t[len(capo):])
        if not resto:
            return CmdRegistra(tipo=capo, azione="elenco")
        if resto.lower().startswith("via ") or resto.lower() == "via":
            nome = _pulisci(resto[3:])
            if not _nome_valido(nome):
                return CmdErrore(esempio)
            return CmdRegistra(tipo=capo, azione="togli", nome=nome)
        if not _nome_valido(resto):
            return CmdErrore(esempio)
        return CmdRegistra(tipo=capo, azione="registra", nome=resto)

    if capo in ("vs", "tf"):
        if len(parole) != 1:
            return CmdErrore(testi.ESEMPIO_VS if capo == "vs" else testi.ESEMPIO_TF)
        return CmdRegistra(tipo=capo, azione="registra")

    if capo in ("ag", "tg"):
        esempio = testi.ESEMPIO_AG if capo == "ag" else testi.ESEMPIO_TG
        if len(parole) < 3 or parole[1] not in ("studio", "lavoro"):
            return CmdErrore(esempio)
        voce = " ".join(parole[2:])
        return CmdLista(azione=capo, lista=parole[1], voce=voce)

    return CmdErrore(testi.NON_CAPITO)
