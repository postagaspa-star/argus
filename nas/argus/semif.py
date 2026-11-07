"""Client di SemIf (sol-decisore) e le domande di Argus (regole sezione 9, contratto sezione 4).

- Una richiesta alla volta (il decisore è condiviso con Sol).
- 503 `decisore_non_disponibile` -> si riprova dopo 30 secondi.
- La scelta vale solo se probabilita[scelta] >= 0.6 e massa_opzioni >= 0.5; se no `non_si_capisce`.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass

import httpx

log = logging.getLogger("argus.semif")

SOGLIA_PROBABILITA = 0.6
SOGLIA_MASSA = 0.5
MAX_DOMANDE = 8
MAX_OPZIONI = 16
NON_SI_CAPISCE = "non_si_capisce"


class DecisoreNonDisponibile(Exception):
    pass


@dataclass
class Domanda:
    id: str
    domanda: str
    opzioni: list[tuple[str, str]]  # (id, descrizione)

    def a_dict(self) -> dict:
        return {"id": self.id, "domanda": self.domanda,
                "opzioni": [{"id": i, "descrizione": d} for i, d in self.opzioni]}


def accetta(risposta: dict | None, opzioni_valide: set[str]) -> str:
    """Applica le soglie del contratto a una risposta di SemIf per una domanda."""
    if not risposta:
        return NON_SI_CAPISCE
    scelta = risposta.get("scelta")
    if scelta not in opzioni_valide:
        return NON_SI_CAPISCE
    probabilita = (risposta.get("probabilita") or {}).get(scelta)
    massa = risposta.get("massa_opzioni")
    try:
        if probabilita is None or float(probabilita) < SOGLIA_PROBABILITA:
            return NON_SI_CAPISCE
        if massa is None or float(massa) < SOGLIA_MASSA:
            return NON_SI_CAPISCE
    except (TypeError, ValueError):
        return NON_SI_CAPISCE
    return scelta


class Decisore:
    def __init__(self, url: str, client: httpx.AsyncClient, attesa_503: float = 30.0,
                 tentativi_503: int = 20, timeout: float = 150.0):
        self.url = url.rstrip("/")
        self.client = client
        self.attesa_503 = attesa_503
        self.tentativi_503 = tentativi_503
        self.timeout = timeout
        self._lock = asyncio.Lock()
        self.ultimo_ok: bool | None = None

    async def decidi(self, stato: str, domande: list[Domanda], scadenza_secondi: int = 120) -> dict[str, str]:
        if not domande or len(domande) > MAX_DOMANDE:
            raise ValueError("da 1 a 8 domande per richiesta")
        if any(len(d.opzioni) > MAX_OPZIONI or len(d.opzioni) < 2 for d in domande):
            raise ValueError("da 2 a 16 opzioni per domanda")
        corpo = {"stato": stato, "domande": [d.a_dict() for d in domande], "scadenza_secondi": scadenza_secondi}
        async with self._lock:
            for tentativo in range(self.tentativi_503 + 1):
                try:
                    r = await self.client.post(f"{self.url}/decidi", json=corpo, timeout=self.timeout)
                except httpx.HTTPError as e:
                    self.ultimo_ok = False
                    raise DecisoreNonDisponibile(str(e)) from e
                if r.status_code == 503:
                    self.ultimo_ok = True
                    log.info("Decisore occupato (503), riprovo tra %s s", self.attesa_503)
                    if tentativo < self.tentativi_503:
                        await asyncio.sleep(self.attesa_503)
                        continue
                    raise DecisoreNonDisponibile("decisore occupato troppo a lungo")
                if r.status_code != 200:
                    self.ultimo_ok = False
                    raise DecisoreNonDisponibile(f"risposta {r.status_code}")
                self.ultimo_ok = True
                risposte = (r.json() or {}).get("risposte") or {}
                return {d.id: accetta(risposte.get(d.id), {i for i, _ in d.opzioni}) for d in domande}
        raise DecisoreNonDisponibile("non raggiungibile")  # pragma: no cover

    async def salute(self) -> str:
        try:
            r = await self.client.get(f"{self.url}/salute", timeout=3.0)
            return "ok" if r.status_code < 500 else "assente"
        except httpx.HTTPError:
            return "assente"


# --- Le domande (regole sezione 9), scritte per un lettore che vede solo il diario --------------

def domanda_pensiero(inizio: str, fine: str, minuti: int) -> Domanda:
    return Domanda(
        id="pensiero",
        # Domanda su un FATTO (stessa materia prima e dopo), non su un'intenzione: provata sul decisore
        # vero il 07/11/2026. "Era studio?" dava 59% "non studio" su un caso chiaro (storia prima e
        # dopo); questa forma dà 90% "sì". Opzioni corte: le descrizioni lunghe confondono il modello.
        domanda=(f"Subito prima e subito dopo il tempo in cui era fermo (dalle {inizio} alle {fine}, "
                 f"{minuti} minuti), lo studente stava lavorando sulla stessa materia di scuola?"),
        opzioni=[
            ("studio", "prima e dopo studia la stessa materia"),
            ("non_studio", "dopo fa un'altra cosa, non di scuola"),
            ("non_si_capisce", "il diario non lo dice"),
        ],
    )


def domanda_titolo(dominio: str, titolo: str) -> Domanda:
    return Domanda(
        id="titolo",
        domanda=(f"Sul computer è aperta una pagina del sito {dominio} con questo titolo: «{titolo}». "
                 "Questa pagina è studio, lavoro o svago?"),
        opzioni=[
            ("studio", "Studio: una materia di scuola (lezioni, spiegazioni, esercizi, ripasso, documentari "
                       "o domande su argomenti di scuola)."),
            ("lavoro", "Lavoro: programmazione, siti web, server, strumenti per lavorare al computer."),
            ("svago", "Svago: divertimento (musica, giochi, intrattenimento, scherzi, sport, curiosità "
                      "che non sono di scuola)."),
            ("non_si_capisce", "Dal titolo non si capisce."),
        ],
    )


def domanda_pausa(motivo: str) -> Domanda:
    return Domanda(
        id="pausa",
        domanda=(f"Lo studente ha chiesto una pausa scrivendo questo motivo: «{motivo}». Quello che si vede "
                 "nel diario durante la pausa torna con il motivo?"),
        opzioni=[
            ("torna", "Sì: quello che fa è coerente col motivo (per esempio motivo «bagno» e non si vede, "
                      "motivo «merenda» e mangia), oppure non c'è niente che lo contraddica."),
            ("non_torna", "No: fa chiaramente un'altra cosa che col motivo non c'entra (per esempio motivo "
                          "«bagno» e sta sul divano col telefono in mano)."),
            ("non_si_capisce", "Non si vede abbastanza per dirlo."),
        ],
    )


def domanda_lettura() -> Domanda:
    return Domanda(
        id="lettura",
        domanda=("Lo studente legge un libro o dei fogli che non sono tra quelli registrati. "
                 "Da quello che dice il diario, quello che legge è roba di scuola?"),
        opzioni=[
            ("scuola", "Sì: un libro di testo, appunti, fotocopie o esercizi di scuola."),
            ("non_scuola", "No: un romanzo, un fumetto, una rivista o altro che non è di scuola."),
            ("non_si_capisce", "Dal diario non si capisce."),
        ],
    )
