"""Vettori di immagine con SigLIP 2 base (solo la parte visiva, int8, Apache-2.0) e confronto con le
cose registrate (lb, qd, tf). Il viso (vs) usa SFace, non SigLIP.
"""

from __future__ import annotations

import threading
from pathlib import Path

import cv2
import numpy as np

from .esecutore import Esecutore

LATO = 224
# Vettore medio di SigLIP 2 su ~430 ritagli COCO vari: togliendolo, due oggetti qualsiasi hanno
# somiglianza vicina a 0 invece di ~0,8 (misure in NOTE-COSTRUTTORE.md).
MEDIA = Path(__file__).parent / "dati" / "media_siglip2.npy"


class Vettori:
    def __init__(self, percorso: Path | str, thread: int = 2):
        # SigLIP int8 va su ONNX Runtime CPU (vedi esecutore.py).
        self.esecutore = Esecutore(percorso, "CPU", thread)
        self.media = np.load(MEDIA).astype(np.float32) if MEDIA.exists() else None

    @staticmethod
    def prepara(bgr: np.ndarray) -> np.ndarray:
        rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
        x = cv2.resize(rgb, (LATO, LATO), interpolation=cv2.INTER_LINEAR).astype(np.float32) / 255.0
        x = (x - 0.5) / 0.5
        return x.transpose(2, 0, 1)[None]

    def vettore(self, bgr: np.ndarray) -> np.ndarray:
        uscite = self.esecutore.esegui(self.prepara(bgr))
        v = np.asarray(uscite[1] if len(uscite) > 1 else uscite[0]).reshape(-1).astype(np.float32)
        v = v / (np.linalg.norm(v) + 1e-9)
        if self.media is not None:
            v = v - self.media
        return v / (np.linalg.norm(v) + 1e-9)


class Registrati:
    """I vettori di libri, quaderni, telefono e viso registrati (letti dal database)."""

    def __init__(self):
        self._lock = threading.Lock()
        self.oggetti: list[tuple[str, str, np.ndarray]] = []  # (tipo lb|qd, nome, vettore)
        self.telefono: list[np.ndarray] = []
        self.viso: list[np.ndarray] = []

    def carica(self, righe: list[dict], modello_oggetti: str, modello_viso: str) -> None:
        oggetti, telefono, viso = [], [], []
        for r in righe:
            v = r.get("vettore")
            if v is None or not len(v):
                continue
            if r["tipo"] in ("lb", "qd") and r.get("modello") == modello_oggetti:
                oggetti.append((r["tipo"], r["nome"], v))
            elif r["tipo"] == "tf" and r.get("modello") == modello_oggetti:
                telefono.append(v)
            elif r["tipo"] == "vs" and r.get("modello") == modello_viso:
                viso.append(v)
        with self._lock:
            self.oggetti, self.telefono, self.viso = oggetti, telefono, viso

    def miglior_oggetto(self, v: np.ndarray) -> tuple[str | None, str | None, float]:
        with self._lock:
            migliore = (None, None, -1.0)
            for tipo, nome, r in self.oggetti:
                s = float(np.dot(v, r))
                if s > migliore[2]:
                    migliore = (tipo, nome, s)
            return migliore

    def somiglianza_telefono(self, v: np.ndarray) -> float | None:
        with self._lock:
            if not self.telefono:
                return None
            return max(float(np.dot(v, r)) for r in self.telefono)

    def somiglianza_viso(self, v: np.ndarray) -> float | None:
        with self._lock:
            if not self.viso:
                return None
            return max(float(np.dot(v, r)) for r in self.viso)

    @property
    def ha_viso(self) -> bool:
        return bool(self.viso)
