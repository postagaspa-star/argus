"""Quello che manda il PC (POST /api/pc/attivita) trasformato in un riassunto per minuto.

Il NAS usa le stesse regole di confronto del PC (contratto, sezione 3) per capire se in primo
piano c'era una cosa di studio, di lavoro, di svago (sito giudicato) o altro.
"""

from __future__ import annotations

import hashlib
import threading
from collections import deque
from dataclasses import dataclass
from datetime import datetime, timedelta

from .liste import e_browser, in_mai, programma_in, sito_in
from .motore import PcMinuto

SECONDI_IN_USO = 300  # leggere un PDF senza toccare il mouse per qualche minuto è ancora "in uso"
# L'audio conta come studio SOLO se è la voce di Lectio (regole, sezione 4): un film aperto con Foto
# o un altro programma della lista studio non basta.
AUDIO_DI_STUDIO = ["lectio"]
# Prefisso che il PC mette ai programmi che hanno il nome di uno in lista ma non passano il
# riconoscimento (firma + nome originale, o percorso fidato).
NON_RICONOSCIUTO = "non_riconosciuto:"


def chiave_verdetto(dominio: str, titolo: str) -> str:
    """sha1(dominio + "|" + titolo) in esadecimale minuscolo, UTF-8 (contratto, sezione 3).

    Dominio e titolo vanno presi ESATTAMENTE come arrivano nel campione del PC (il PC li ha già
    ripuliti: niente "www.", niente " - Google Chrome"): il PC calcola la stessa chiave per cercare
    il verdetto, quindi qui non si normalizza niente, nemmeno le maiuscole."""
    return hashlib.sha1(f"{dominio or ''}|{titolo or ''}".encode("utf-8")).hexdigest()


def categoria(c: dict, liste: dict, verdetti: dict[str, str]) -> str:
    """Categoria di un campione: studio | lavoro | sempre | svago | attesa | dubbio | coperto | pactum
    | bloccato | mai | altro."""
    if c.get("schermo_bloccato"):
        return "bloccato"
    if c.get("pactum_copre"):
        return "pactum"
    if c.get("coperto"):
        return "coperto"
    processo = (c.get("processo") or "").lower()
    dominio = (c.get("dominio") or "").lower()
    if processo.startswith(NON_RICONOSCIUTO):
        # Nome giusto ma firma o percorso no (contratto, sezione 3): mai studio, lavoro o browser.
        return "altro"
    if in_mai(processo, dominio, liste):
        return "mai"
    if e_browser(processo, liste):
        if not dominio:
            return "attesa"  # pagina nuova o impostazioni del browser
        if sito_in(dominio, liste["da_giudicare"]):
            esito = verdetti.get(chiave_verdetto(c.get("dominio") or "", c.get("titolo") or ""))
            return {"studio": "studio", "lavoro": "lavoro", "svago": "svago",
                    "non_si_capisce": "dubbio"}.get(esito or "", "attesa")
        if sito_in(dominio, liste["studio"]["siti"]):
            return "studio"
        if sito_in(dominio, liste["lavoro"]["siti"]):
            return "lavoro"
        if sito_in(dominio, liste["sempre"]["siti"]):
            return "sempre"
        return "altro"
    if programma_in(processo, liste["studio"]["programmi"]):
        return "studio"
    if programma_in(processo, liste["lavoro"]["programmi"]):
        return "lavoro"
    if programma_in(processo, liste["sempre"]["programmi"]):
        return "sempre"
    titoli = (liste.get("condizionati") or {}).get(processo)
    if titoli and (c.get("titolo") or "") in titoli:
        return "sempre"
    return "altro"


def audio_di_studio(c: dict, liste: dict) -> bool:
    for p in c.get("audio") or []:
        if not p or str(p).lower().startswith(NON_RICONOSCIUTO):
            continue
        if e_browser(p, liste):
            continue
        # Lectio, e solo finché è nella lista studio (se lo si toglie con tg, non conta più).
        if programma_in(p, AUDIO_DI_STUDIO) and programma_in(p, liste["studio"]["programmi"]):
            return True
    return False


def riassumi(campioni: list[dict], liste: dict, verdetti: dict[str, str],
             ore: list[datetime] | None = None) -> PcMinuto | None:
    """Il minuto del PC. `ore` = quando il NAS ha ricevuto ogni campione (serve per sapere quando il
    PC è stato toccato l'ultima volta: ora del campione meno i secondi di inattività)."""
    if not campioni:
        return None
    conteggi: dict[str, int] = {}
    in_uso = False
    audio = False
    ultimo_input: datetime | None = None
    for i, c in enumerate(campioni):
        cat = categoria(c, liste, verdetti)
        conteggi[cat] = conteggi.get(cat, 0) + 1
        inattivo = c.get("inattivo_secondi")
        if not c.get("schermo_bloccato") and inattivo is not None:
            if inattivo < SECONDI_IN_USO:
                in_uso = True
            if ore is not None and i < len(ore):
                toccato = ore[i] - timedelta(seconds=max(0.0, float(inattivo)))
                if ultimo_input is None or toccato > ultimo_input:
                    ultimo_input = toccato
        if audio_di_studio(c, liste):
            audio = True
    # Vince la categoria più presente; a pari merito la più "prudente" (prima in questa lista).
    ordine = ["attesa", "dubbio", "coperto", "pactum", "bloccato", "sempre", "altro", "studio", "lavoro",
              "mai", "svago"]
    migliore = max(conteggi.items(), key=lambda kv: (kv[1], -ordine.index(kv[0]) if kv[0] in ordine else -99))[0]
    return PcMinuto(categoria=migliore, in_uso=in_uso, audio_studio=audio, ultimo_input=ultimo_input)


@dataclass
class Campione:
    ricevuto: datetime
    dati: dict


class MemoriaPc:
    """Tiene gli ultimi campioni del PC (qualche minuto) e i titoli da far giudicare."""

    def __init__(self, minuti: int = 15):
        self._campioni: deque[Campione] = deque()
        self._lock = threading.Lock()
        self._minuti = minuti
        self.ultimo: Campione | None = None

    def aggiungi(self, campioni: list[dict], ricevuto: datetime) -> None:
        n = len(campioni)
        with self._lock:
            for i, c in enumerate(campioni):
                # Uno al secondo: l'ultimo è "adesso", quelli prima qualche secondo indietro.
                quando = ricevuto - timedelta(seconds=(n - 1 - i))
                self._campioni.append(Campione(quando, c))
            if campioni:
                self.ultimo = self._campioni[-1]
            limite = ricevuto - timedelta(minutes=self._minuti)
            while self._campioni and self._campioni[0].ricevuto < limite:
                self._campioni.popleft()

    def del_minuto(self, inizio: datetime) -> list[dict]:
        return [d for _, d in self.del_minuto_con_ora(inizio)]

    def del_minuto_con_ora(self, inizio: datetime) -> list[tuple[datetime, dict]]:
        fine = inizio + timedelta(minutes=1)
        with self._lock:
            return [(c.ricevuto, c.dati) for c in self._campioni if inizio <= c.ricevuto < fine]

    def chiavi_recenti(self, ora: datetime, minuti: int = 10) -> set[str]:
        """Le chiavi dei verdetti (dominio + titolo) viste negli ultimi minuti: il PC le deve avere."""
        limite = ora - timedelta(minutes=minuti)
        with self._lock:
            return {chiave_verdetto(c.dati.get("dominio") or "", c.dati.get("titolo") or "")
                    for c in self._campioni
                    if c.ricevuto >= limite and c.dati.get("dominio") and c.dati.get("titolo")}

    def ultimo_campione(self, ora: datetime, entro_secondi: int = 30) -> dict | None:
        with self._lock:
            if self.ultimo is None or (ora - self.ultimo.ricevuto).total_seconds() > entro_secondi:
                return None
            return self.ultimo.dati


def da_giudicare(campioni: list[dict], liste: dict, verdetti: dict[str, str]) -> list[tuple[str, str]]:
    """Le coppie (dominio, titolo) dei siti da giudicare che non hanno ancora un verdetto."""
    trovati: list[tuple[str, str]] = []
    for c in campioni:
        dominio = c.get("dominio") or ""  # così come arriva: serve per la chiave del verdetto
        titolo = c.get("titolo") or ""
        if not dominio or not titolo or not e_browser(c.get("processo"), liste):
            continue
        if not sito_in(dominio.lower(), liste["da_giudicare"]):
            continue
        if chiave_verdetto(dominio, titolo) in verdetti:
            continue
        if (dominio, titolo) not in trovati:
            trovati.append((dominio, titolo))
    return trovati
