"""Visi: trovati con OpenCV YuNet (MIT), riconosciuti con OpenCV SFace (Apache-2.0).
Occhi aperti o chiusi: MediaPipe Face Landmarker (Apache-2.0), punteggi "eyeBlink".
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np

from .geometria import Box


@dataclass
class Viso:
    box: Box
    punteggio: float
    riga: np.ndarray  # la riga di YuNet (serve ad allineare per SFace)


class Visi:
    def __init__(self, yunet: Path | str, sface: Path | str, occhi: Path | str | None = None,
                 soglia_viso: float = 0.7):
        self._yunet = cv2.FaceDetectorYN.create(str(yunet), "", (320, 320), soglia_viso, 0.3, 50)
        self._sface = cv2.FaceRecognizerSF.create(str(sface), "")
        self._occhi = None
        self._percorso_occhi = str(occhi) if occhi else None

    def trova(self, bgr: np.ndarray) -> list[Viso]:
        if bgr is None or bgr.size == 0:
            return []
        h, w = bgr.shape[:2]
        self._yunet.setInputSize((w, h))
        _, righe = self._yunet.detect(bgr)
        if righe is None:
            return []
        visi = []
        for r in righe:
            x, y, lw, lh = r[:4]
            visi.append(Viso(Box(float(x), float(y), float(x + lw), float(y + lh)), float(r[14]), r))
        return sorted(visi, key=lambda v: -v.box.area)

    def vettore(self, bgr: np.ndarray, viso: Viso) -> np.ndarray:
        allineato = self._sface.alignCrop(bgr, viso.riga)
        v = self._sface.feature(allineato).reshape(-1).astype(np.float32)
        return v / (np.linalg.norm(v) + 1e-9)

    def _carica_occhi(self):
        if self._occhi is None and self._percorso_occhi:
            from mediapipe.tasks.python import BaseOptions, vision

            opzioni = vision.FaceLandmarkerOptions(
                base_options=BaseOptions(model_asset_path=self._percorso_occhi),
                running_mode=vision.RunningMode.IMAGE, num_faces=1, output_face_blendshapes=True)
            self._occhi = vision.FaceLandmarker.create_from_options(opzioni)
        return self._occhi

    def chiudi(self) -> None:
        if self._occhi is not None:
            self._occhi.close()
            self._occhi = None

    def occhi(self, bgr: np.ndarray, viso: Viso) -> str | None:
        """"aperti" | "chiusi" | None (non si capisce)."""
        modello = self._carica_occhi()
        if modello is None:
            return None
        import mediapipe as mp

        h, w = bgr.shape[:2]
        b = viso.box.allarga(1.8, w, h)
        x1, y1, x2, y2 = b.interi()
        ritaglio = bgr[y1:y2, x1:x2]
        if ritaglio.size == 0 or min(ritaglio.shape[:2]) < 40:
            return None
        if min(ritaglio.shape[:2]) < 160:
            fattore = 160 / min(ritaglio.shape[:2])
            ritaglio = cv2.resize(ritaglio, None, fx=fattore, fy=fattore, interpolation=cv2.INTER_CUBIC)
        rgb = np.ascontiguousarray(cv2.cvtColor(ritaglio, cv2.COLOR_BGR2RGB))
        risultato = modello.detect(mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb))
        if not risultato.face_blendshapes:
            return None
        punteggi = {c.category_name: c.score for c in risultato.face_blendshapes[0]}
        chiusura = (punteggi.get("eyeBlinkLeft", 0.0) + punteggi.get("eyeBlinkRight", 0.0)) / 2
        if chiusura < 0.35:
            return "aperti"
        if chiusura > 0.6:
            return "chiusi"
        return None


def coseno(a: np.ndarray, b: np.ndarray) -> float:
    return float(np.dot(a, b) / ((np.linalg.norm(a) * np.linalg.norm(b)) + 1e-9))
