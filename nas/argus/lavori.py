"""Coda delle foto dubbie per il modello del PC (regole sezione 10, contratto GET/POST /api/pc/lavori).

- Un lavoro = un ritaglio JPEG + domande a risposte fisse.
- Il PC prende un lavoro; resta "preso" per 3 minuti, poi se non ha risposto torna in coda.
- Il ritaglio si cancella appena giudicato, oppure a mezzanotte (i lavori non presi scadono: le
  risposte valgono solo per i minuti dopo, quindi un giudizio arrivato tardi non cambierebbe
  niente e nel dubbio resta neutro).
"""

from __future__ import annotations

import base64
import logging
import threading
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from typing import Callable

from .db import Database
from .tempo import fine_giornata, iso

log = logging.getLogger("argus.lavori")

PRESO_PER = timedelta(minutes=3)
MAX_IN_CODA = 30

DOMANDE: dict[str, dict] = {
    "in_mano": {"id": "in_mano", "domanda": "Cosa tiene in mano la persona?",
                "opzioni": ["telefono", "tablet", "libro", "quaderno", "controller", "niente", "non_si_capisce"]},
    "schermo_acceso": {"id": "schermo_acceso", "domanda": "C'è uno schermo acceso davanti alla persona?",
                       "opzioni": ["si", "no", "non_si_capisce"]},
    "lettura": {"id": "lettura", "domanda": "Cosa sta leggendo la persona?",
                "opzioni": ["libro_di_scuola", "quaderno_o_appunti", "romanzo_o_fumetto", "rivista_o_altro",
                            "niente", "non_si_capisce"]},
    "dorme": {"id": "dorme", "domanda": "La persona sta dormendo (occhi chiusi, ferma)?",
              "opzioni": ["si", "no", "non_si_capisce"]},
    "tv_accesa": {"id": "tv_accesa", "domanda": "La televisione nella foto è accesa?",
                  "opzioni": ["si", "no", "non_si_capisce"]},
}

# Lavori tipici: che domande fare per ogni dubbio della visione.
TIPI = {
    "oggetto_in_mano": ["in_mano", "schermo_acceso"],
    "lettura": ["lettura"],
    "dorme": ["dorme"],
    "tv": ["tv_accesa"],
}


class ErroreLavoro(Exception):
    def __init__(self, codice: str, messaggio: str, stato_http: int):
        super().__init__(messaggio)
        self.codice = codice
        self.messaggio = messaggio
        self.stato_http = stato_http


class CodaLavori:
    def __init__(self, db: Database, cartella: Path):
        self.db = db
        self.cartella = Path(cartella)
        self.cartella.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._ascoltatori: list[Callable[[dict], None]] = []

    def quando_giudicato(self, funzione: Callable[[dict], None]) -> None:
        """La visione si iscrive qui per usare le risposte (per esempio: quel telefono è acceso)."""
        self._ascoltatori.append(funzione)

    def aggiungi(self, tipo: str, jpeg: bytes, contesto: str, origine: dict, ora: datetime) -> str | None:
        if tipo not in TIPI:
            raise ValueError(f"tipo di lavoro sconosciuto: {tipo}")
        with self._lock:
            in_coda = self.db.lavori("in_coda") + self.db.lavori("preso")
            if len(in_coda) >= MAX_IN_CODA:
                log.info("Coda dei lavori piena: scarto il dubbio (resta neutro)")
                return None
            id_lavoro = "l-" + uuid.uuid4().hex[:12]
            file = self.cartella / f"{id_lavoro}.jpg"
            file.write_bytes(jpeg)
            self.db.salva_lavoro({
                "id": id_lavoro, "stato": "in_coda", "tipo": tipo, "creato": ora.isoformat(), "preso_alle": None,
                "scade": iso(fine_giornata(ora.date())), "contesto": contesto,
                "domande": [DOMANDE[d] for d in TIPI[tipo]], "file": str(file), "origine": origine,
            })
            return id_lavoro

    def prossimo(self, ora: datetime) -> dict | None:
        with self._lock:
            candidati = []
            for lav in self.db.lavori("preso"):
                preso = datetime.fromisoformat(lav["preso_alle"]) if lav["preso_alle"] else None
                if preso is None or ora - preso >= PRESO_PER:
                    lav["stato"] = "in_coda"
                    self.db.salva_lavoro(lav)
            candidati = [lav for lav in self.db.lavori("in_coda")
                         if datetime.fromisoformat(lav["scade"]) > ora]
            if not candidati:
                return None
            lav = candidati[0]
            try:
                jpeg = Path(lav["file"]).read_bytes()
            except OSError:
                lav["stato"] = "scaduto"
                self.db.salva_lavoro(lav)
                return None
            lav["stato"] = "preso"
            lav["preso_alle"] = ora.isoformat()
            self.db.salva_lavoro(lav)
            return {
                "id": lav["id"],
                "immagine_jpeg_base64": base64.b64encode(jpeg).decode("ascii"),
                "contesto": lav["contesto"],
                "domande": lav["domande"],
                "scade": lav["scade"],
            }

    def rispondi(self, id_lavoro: str, risposte: dict, millisecondi: int | None, modello: str | None,
                 ora: datetime) -> dict:
        with self._lock:
            lav = self.db.lavoro(id_lavoro)
            if lav is None:
                raise ErroreLavoro("lavoro_sconosciuto", "Questo lavoro non c'è.", 404)
            if lav["stato"] not in ("preso", "in_coda"):
                raise ErroreLavoro("lavoro_chiuso", "Questo lavoro è già stato giudicato o è scaduto.", 409)
            for d in lav["domande"]:
                valore = risposte.get(d["id"])
                if valore not in d["opzioni"]:
                    raise ErroreLavoro("opzione_non_valida",
                                       f"Risposta non valida per «{d['id']}»: deve essere una di {', '.join(d['opzioni'])}.",
                                       422)
            lav.update(stato="giudicato", risposte={d["id"]: risposte[d["id"]] for d in lav["domande"]},
                       giudicato_alle=ora.isoformat(), millisecondi=millisecondi, modello=modello)
            self._cancella_file(lav)
            self.db.salva_lavoro(lav)
        for funzione in self._ascoltatori:
            try:
                funzione(lav)
            except Exception:  # noqa: BLE001 - un ascoltatore rotto non deve fermare la risposta al PC
                log.exception("Errore nell'usare la risposta del lavoro %s", id_lavoro)
        return lav

    def mezzanotte(self) -> int:
        """Cancella tutti i ritagli rimasti e chiude i lavori non giudicati."""
        n = 0
        with self._lock:
            for stato in ("in_coda", "preso"):
                for lav in self.db.lavori(stato):
                    lav["stato"] = "scaduto"
                    self._cancella_file(lav)
                    self.db.salva_lavoro(lav)
                    n += 1
            # file orfani (per esempio dopo un riavvio a metà)
            for f in self.cartella.glob("*.jpg"):
                try:
                    f.unlink()
                except OSError:
                    pass
        return n

    def in_coda(self) -> int:
        return len(self.db.lavori("in_coda")) + len(self.db.lavori("preso"))

    @staticmethod
    def _cancella_file(lav: dict) -> None:
        if lav.get("file"):
            try:
                Path(lav["file"]).unlink(missing_ok=True)
            except OSError:
                pass
            lav["file"] = None
