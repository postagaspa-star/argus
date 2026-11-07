"""Lettura delle telecamere.

- Flusso secondario (bassa risoluzione) letto di continuo con OpenCV/FFmpeg da go2rtc
  (rtsp://argus-go2rtc:8554/<id>_secondario): si tiene solo l'ultima immagine, a 2-5 al secondo.
- Flusso principale solo per i ritagli: un'istantanea JPEG da go2rtc (/api/frame.jpeg).
- TelecameraFinta: immagini da una cartella (o da una lista), per le prove senza telecamere.

Le immagini non si salvano mai su disco (contratto, sezione 5).
"""

from __future__ import annotations

import logging
import os
import threading
import time
from pathlib import Path

import cv2
import numpy as np

log = logging.getLogger("argus.flusso")

os.environ.setdefault("OPENCV_FFMPEG_CAPTURE_OPTIONS", "rtsp_transport;tcp|stimeout;5000000")


class Sorgente:
    id: str = ""

    def avvia(self) -> None:
        pass

    def ferma(self) -> None:
        pass

    def imposta_fps(self, fps: float) -> None:
        pass

    def ultimo(self) -> tuple[np.ndarray | None, float]:
        """L'ultima immagine del flusso secondario e quando è arrivata (time.monotonic)."""
        raise NotImplementedError

    def istantanea_principale(self) -> np.ndarray | None:
        return None

    def stato(self) -> str:
        return "assente"


class LettoreRtsp(Sorgente):
    def __init__(self, id_telecamera: str, url: str, url_istantanea: str | None = None, fps: float = 2.0):
        self.id = id_telecamera
        self.url = url
        self.url_istantanea = url_istantanea
        self._fps = fps
        self._lock = threading.Lock()
        self._immagine: np.ndarray | None = None
        self._quando = 0.0
        self._ok = False
        self._mai_connesso = True
        self._ferma = threading.Event()
        self._thread = threading.Thread(target=self._ciclo, name=f"flusso-{id_telecamera}", daemon=True)
        self._client = None

    def avvia(self) -> None:
        self._thread.start()

    def ferma(self) -> None:
        self._ferma.set()

    def copia(self) -> "LettoreRtsp":
        return LettoreRtsp(self.id, self.url, self.url_istantanea, self._fps)

    def imposta_fps(self, fps: float) -> None:
        self._fps = max(0.1, fps)

    def ultimo(self) -> tuple[np.ndarray | None, float]:
        with self._lock:
            return self._immagine, self._quando

    def stato(self) -> str:
        if self._ok and time.monotonic() - self._quando < 15:
            return "ok"
        return "assente" if self._mai_connesso else "errore"

    def _ciclo(self) -> None:
        attesa = 2.0
        while not self._ferma.is_set():
            cattura = cv2.VideoCapture(self.url, cv2.CAP_FFMPEG)
            if not cattura.isOpened():
                self._ok = False
                log.warning("Telecamera %s non raggiungibile, riprovo tra %.0f s", self.id, attesa)
                self._ferma.wait(attesa)
                attesa = min(60.0, attesa * 2)
                continue
            self._mai_connesso = False
            attesa = 2.0
            ultimo_preso = 0.0
            errori = 0
            while not self._ferma.is_set():
                # grab() di continuo per non restare indietro; retrieve() solo alla velocità voluta.
                if not cattura.grab():
                    errori += 1
                    if errori > 25:
                        break
                    continue
                errori = 0
                adesso = time.monotonic()
                if adesso - ultimo_preso >= 1.0 / self._fps:
                    ok, immagine = cattura.retrieve()
                    if ok and immagine is not None:
                        with self._lock:
                            self._immagine, self._quando = immagine, adesso
                        self._ok = True
                        ultimo_preso = adesso
            cattura.release()
            self._ok = False
            log.warning("Telecamera %s: flusso interrotto, riconnetto", self.id)

    def istantanea_principale(self) -> np.ndarray | None:
        if not self.url_istantanea:
            return None
        try:
            import httpx

            if self._client is None:
                self._client = httpx.Client(timeout=6.0)
            r = self._client.get(self.url_istantanea)
            if r.status_code != 200:
                return None
            return cv2.imdecode(np.frombuffer(r.content, dtype=np.uint8), cv2.IMREAD_COLOR)
        except Exception as e:  # noqa: BLE001 - il ritaglio ad alta risoluzione è un di più
            log.debug("Istantanea di %s non riuscita: %s", self.id, e)
            return None


class TelecameraFinta(Sorgente):
    """Legge immagini da una cartella (in ordine di nome) o da una lista. Ogni `ultimo()` dà la
    prossima; `ripeti` le fa ricominciare dall'inizio."""

    ESTENSIONI = {".jpg", ".jpeg", ".png", ".bmp"}

    def __init__(self, id_telecamera: str, cartella: str | Path | None = None,
                 immagini: list[np.ndarray] | None = None, ripeti: bool = True, principale_scala: float = 1.0):
        self.id = id_telecamera
        self._immagini: list[np.ndarray] = list(immagini or [])
        if cartella:
            for f in sorted(Path(cartella).iterdir()):
                if f.suffix.lower() in self.ESTENSIONI:
                    img = cv2.imread(str(f))
                    if img is not None:
                        self._immagini.append(img)
        self._indice = 0
        self._ripeti = ripeti
        self._attuale: np.ndarray | None = None
        self._principale_scala = principale_scala
        self.spenta = False

    def ultimo(self) -> tuple[np.ndarray | None, float]:
        if self.spenta or not self._immagini:
            return None, 0.0
        if self._indice >= len(self._immagini):
            if not self._ripeti:
                return None, 0.0
            self._indice = 0
        self._attuale = self._immagini[self._indice]
        self._indice += 1
        return self._attuale, time.monotonic()

    def istantanea_principale(self) -> np.ndarray | None:
        if self._attuale is None:
            return None
        if self._principale_scala == 1.0:
            return self._attuale
        return cv2.resize(self._attuale, None, fx=self._principale_scala, fy=self._principale_scala)

    def stato(self) -> str:
        return "errore" if self.spenta else "ok"
