"""La visione vera: un lettore per telecamera, un solo thread di analisi (così CPU e memoria restano
sotto controllo sul NAS), l'aggregatore del minuto e l'inseguimento PTZ.

Si avvia solo se ci sono telecamere in config. I modelli si caricano alla prima immagine da
analizzare (e restano caricati); finché la quota è fatta o non è giorno di scuola, le telecamere
non si leggono nemmeno.
"""

from __future__ import annotations

import logging
import os
import threading
import time
from datetime import datetime
from pathlib import Path
from urllib.parse import quote

import cv2
import numpy as np

from ..config import Config, Telecamera
from ..db import Database
from ..lavori import CodaLavori
from ..tempo import Orologio
from . import SorgenteVisione
from . import modelli as mod
from .aggregatore import Aggregatore, Osservazione
from .analizzatore import MODELLO_OGGETTI, MODELLO_VISO, Analizzatore, Modelli
from .flusso import LettoreRtsp, Sorgente, TelecameraFinta
from .ptz import Inseguitore, Ptz, PtzOnvif
from .vettori import Registrati

log = logging.getLogger("argus.visione")

ORA_PIENA = 11  # prima delle 11 basta sapere se lo studente c'è: si guarda più piano


class Pipeline(SorgenteVisione):
    def __init__(self, config: Config, cartella_dati: Path, db: Database, lavori: CodaLavori, orologio: Orologio,
                 sorgenti: dict[str, Sorgente] | None = None, ptz: dict[str, Ptz] | None = None,
                 modelli: Modelli | None = None, cartella_modelli: Path | str | None = None,
                 scarica_modelli: bool = True):
        self.config = config
        self.cv = config.visione
        self.dati = Path(cartella_dati)
        self.db = db
        self.lavori = lavori
        self.orologio = orologio
        self._tel = {t.id: t for t in config.telecamere}
        self._sorgenti_date = sorgenti
        self.sorgenti: dict[str, Sorgente] = {}
        self._ptz_dati = ptz
        self.inseguitori: dict[str, Inseguitore] = {}
        self.modelli = modelli
        self.cartella_modelli = Path(cartella_modelli if cartella_modelli is not None
                                     else os.environ.get("ARGUS_MODELLI", "/modelli"))
        self.scarica_modelli = scarica_modelli
        self.registrati = Registrati()
        self.aggregatore = Aggregatore(stanze={t.id: t.stanza for t in config.telecamere})
        self.analizzatore: Analizzatore | None = None
        self.contesto: dict = {"analizza": False}
        self._ferma = threading.Event()
        self._thread: threading.Thread | None = None
        self._lock_modelli = threading.Lock()
        self._ultima_analisi: dict[str, float] = {}
        self._visto_qui: dict[str, float] = {}
        self._in_pausa = True
        self._ultimo_stato: dict[str, str] = {}
        self.errore_modelli: str | None = None

    # ---- interfaccia verso il servizio ---------------------------------------------------------

    def avvia(self, ciclo: bool = True) -> None:
        """ciclo=False: niente thread di analisi (le prove chiamano `passo()` a mano)."""
        self._prepara_sorgenti()
        self.ricarica_registrati()
        self.lavori.quando_giudicato(self._giudicato)
        if ciclo:
            self._thread = threading.Thread(target=self._ciclo, name="visione", daemon=True)
            self._thread.start()

    def ferma(self) -> None:
        self._ferma.set()
        for s in self.sorgenti.values():
            s.ferma()
        if self._thread is not None:
            self._thread.join(timeout=5)

    def imposta_contesto(self, contesto: dict) -> None:
        self.contesto = dict(contesto)

    def minuto(self, inizio: datetime) -> dict:
        return self.aggregatore.minuto(inizio)

    def scena(self, ora: datetime) -> dict | None:
        return self.aggregatore.scena(ora)

    def telecamere(self) -> dict[str, str]:
        """ok | errore | assente. In pausa (quota fatta, niente scuola) le telecamere non si leggono:
        si dice l'ultimo stato visto."""
        stato = {}
        for id_t in self._tel:
            s = self.sorgenti.get(id_t)
            if s is None:
                stato[id_t] = "assente"
            elif self._in_pausa:
                stato[id_t] = self._ultimo_stato.get(id_t, "assente")
            else:
                stato[id_t] = self._ultimo_stato[id_t] = s.stato()
        return stato

    def registra(self, tipo: str, immagini: list[bytes]) -> tuple[str | None, list]:
        analizzatore = self._carica_modelli()
        if analizzatore is None:
            return None, [None for _ in immagini]
        vettori = []
        for dati in immagini:
            img = cv2.imdecode(np.frombuffer(dati, dtype=np.uint8), cv2.IMREAD_COLOR)
            with self._lock_modelli:
                vettori.append(analizzatore.vettore_registrazione(tipo, img))
        return (MODELLO_VISO if tipo == "vs" else MODELLO_OGGETTI), vettori

    def ricarica_registrati(self) -> None:
        self.registrati.carica(self.db.vettori(), MODELLO_OGGETTI, MODELLO_VISO)

    # ---- preparazione -------------------------------------------------------------------------

    def _registra_flussi_go2rtc(self) -> bool:
        """Dice a go2rtc quali flussi aprire (le password restano nella memoria di go2rtc, non su disco)."""
        try:
            import httpx

            with httpx.Client(timeout=5.0) as c:
                for t in self.config.telecamere:
                    for nome, src in ((f"{t.id}_principale", t.rtsp_principale),
                                      (f"{t.id}_secondario", t.rtsp_secondario),
                                      (f"{t.id}_voce", t.altoparlante)):
                        if src:
                            c.put(f"{self.config.go2rtc_url}/api/streams?name={quote(nome)}&src={quote(src, safe='')}")
            return True
        except Exception as e:  # noqa: BLE001 - senza go2rtc si leggono le telecamere direttamente
            log.warning("go2rtc non raggiungibile (%s): leggo le telecamere direttamente", e)
            return False

    def _prepara_sorgenti(self) -> None:
        if self._sorgenti_date is not None:
            self.sorgenti = dict(self._sorgenti_date)
        else:
            con_go2rtc = self._registra_flussi_go2rtc()
            for t in self.config.telecamere:
                if t.cartella_finta:
                    self.sorgenti[t.id] = TelecameraFinta(t.id, t.cartella_finta)
                    continue
                if con_go2rtc:
                    url = f"{self.config.go2rtc_rtsp}/{t.id}_secondario"
                    istantanea = f"{self.config.go2rtc_url}/api/frame.jpeg?src={quote(t.id)}_principale"
                else:
                    url = t.rtsp_secondario or t.rtsp_principale or ""
                    istantanea = None
                if not url:
                    continue
                self.sorgenti[t.id] = LettoreRtsp(t.id, url, istantanea, fps=self.cv.fps_attesa)
        for t in self.config.telecamere:
            ptz = (self._ptz_dati or {}).get(t.id)
            if ptz is None and self._ptz_dati is None and t.onvif is not None and t.insegui:
                try:
                    ptz = PtzOnvif(t.onvif.host, t.onvif.porta, t.onvif.utente, t.onvif.password)
                except Exception as e:  # noqa: BLE001
                    log.warning("ONVIF di %s non disponibile (%s): uso l'inseguimento integrato", t.id, e)
                    self._registra_evento("ptz_spento", {"telecamera": t.id, "errore": str(e)})
            if ptz is not None:
                self.inseguitori[t.id] = Inseguitore(
                    ptz, inverti_pan=t.inverti_pan, inverti_tilt=t.inverti_tilt,
                    quando_spento=lambda errore, tid=t.id: self._registra_evento(
                        "ptz_spento", {"telecamera": tid, "errore": errore}))

    def _registra_evento(self, tipo: str, dettagli: dict) -> None:
        try:
            self.db.registra(self.orologio.adesso(), tipo, dettagli)
        except Exception:  # noqa: BLE001
            log.exception("Registro non scritto")

    def _carica_modelli(self) -> Analizzatore | None:
        with self._lock_modelli:
            if self.analizzatore is not None:
                return self.analizzatore
            try:
                if self.modelli is None:
                    if self.scarica_modelli:
                        mod.assicura(self.cartella_modelli)
                    self.modelli = Modelli(self.cartella_modelli, self.cv)
                self.analizzatore = Analizzatore(self.modelli, self.registrati, self.cv, self._nuovo_lavoro,
                                                 self.config.stanze_studente)
                self.errore_modelli = None
                self._ricalcola_mancanti()
            except Exception as e:  # noqa: BLE001
                self.errore_modelli = str(e)
                log.exception("Modelli non caricati")
                return None
            return self.analizzatore

    def _ricalcola_mancanti(self) -> None:
        """Vettori mancanti (foto registrate prima che i modelli ci fossero, o modello cambiato)."""
        cambiati = 0
        for r in self.db.vettori():
            atteso = MODELLO_VISO if r["tipo"] == "vs" else MODELLO_OGGETTI
            if r["vettore"] is not None and r["modello"] == atteso:
                continue
            img = cv2.imread(r["file"]) if r.get("file") else None
            v = self.analizzatore.vettore_registrazione(r["tipo"], img) if img is not None else None
            self.db.aggiorna_vettore(r["id"], atteso, v)
            cambiati += 1
        if cambiati:
            self.ricarica_registrati()

    def _nuovo_lavoro(self, tipo: str, jpeg: bytes, contesto: str, origine: dict) -> None:
        self.lavori.aggiungi(tipo, jpeg, contesto, origine, self.orologio.adesso())

    def _giudicato(self, lavoro: dict) -> None:
        if self.analizzatore is not None:
            self.analizzatore.usa_giudizio(lavoro)

    # ---- ciclo di analisi -----------------------------------------------------------------------

    def _metti_in_pausa(self, pausa: bool) -> None:
        if pausa == self._in_pausa:
            return
        self._in_pausa = pausa
        for id_t, s in list(self.sorgenti.items()):
            if pausa:
                self._ultimo_stato[id_t] = s.stato()
                s.ferma()
            else:
                if isinstance(s, LettoreRtsp):
                    s = s.copia()  # un thread fermato non riparte: lettore nuovo
                    self.sorgenti[id_t] = s
                s.avvia()
        log.info("Visione %s", "in pausa" if pausa else "attiva")

    def passo(self, adesso: float | None = None) -> list[Osservazione]:
        """Un giro su tutte le telecamere che è ora di guardare (usato dal ciclo e dalle prove)."""
        adesso = time.monotonic() if adesso is None else adesso
        analizzatore = self._carica_modelli()
        if analizzatore is None:
            return []
        ora = self.orologio.adesso()
        prima_delle_11 = ora.hour < ORA_PIENA
        fatte = []
        for id_t, tel in self._tel.items():
            sorgente = self.sorgenti.get(id_t)
            if sorgente is None:
                continue
            recente = adesso - self._visto_qui.get(id_t, -1e9) < 30
            fps = self.cv.fps if (recente and not prima_delle_11) else self.cv.fps_attesa
            sorgente.imposta_fps(fps)
            if adesso - self._ultima_analisi.get(id_t, -1e9) < 1.0 / fps - 1e-3:
                continue
            self._ultima_analisi[id_t] = adesso
            immagine, quando = sorgente.ultimo()
            if immagine is not None and quando and adesso - quando > 10 and not isinstance(sorgente, TelecameraFinta):
                immagine = None  # immagine vecchia: la telecamera non manda più niente
            inseguitore = self.inseguitori.get(id_t)
            ferma = inseguitore is None or not inseguitore.si_sta_muovendo(adesso)
            with self._lock_modelli:
                o = analizzatore.analizza(immagine, tel, self.contesto, ora, adesso, telecamera_ferma=ferma,
                                          istantanea=sorgente.istantanea_principale, tv_nella_stanza=tel.tv)
            self.aggregatore.aggiungi(o)
            if o.studente:
                self._visto_qui[id_t] = adesso
            if inseguitore is not None:
                inseguitore.aggiorna(o.centro if o.studente else None, adesso)
            fatte.append(o)
        return fatte

    def _ciclo(self) -> None:
        while not self._ferma.is_set():
            analizza = bool(self.contesto.get("analizza"))
            self._metti_in_pausa(not analizza)
            if not analizza:
                self._ferma.wait(5.0)
                continue
            inizio = time.monotonic()
            try:
                self.passo(inizio)
            except Exception:  # noqa: BLE001 - un'immagine storta non deve fermare la visione
                log.exception("Errore nell'analisi")
                self._ferma.wait(2.0)
            durata = time.monotonic() - inizio
            self._ferma.wait(max(0.05, 0.25 - durata))


def telecamera_finta_per_prove(id_t: str, stanza: str, immagini: list[np.ndarray]) -> tuple[Telecamera, TelecameraFinta]:
    return Telecamera(id=id_t, stanza=stanza), TelecameraFinta(id_t, immagini=immagini)
