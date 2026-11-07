"""Posa del corpo: MediaPipe Pose Landmarker (lite, Apache-2.0) sul ritaglio della persona.

La classificazione (seduto / sdraiato / in piedi / chino) è pura geometria sui punti, così si
prova anche senza modello.
"""

from __future__ import annotations

import math
from pathlib import Path

import numpy as np

from .geometria import Box

# Indici dei punti di MediaPipe Pose.
NASO = 0
SPALLE = (11, 12)
POLSI = (15, 16)
MANI = (17, 18, 19, 20, 21, 22)
ANCHE = (23, 24)
GINOCCHIA = (25, 26)
CAVIGLIE = (27, 28)
VISIBILE = 0.5


def _media(punti: np.ndarray, indici: tuple[int, ...]) -> np.ndarray | None:
    scelti = [punti[i, :2] for i in indici if punti[i, 2] >= VISIBILE]
    if not scelti:
        return None
    return np.mean(scelti, axis=0)


def classifica_posa(punti: np.ndarray | None, box: Box) -> str | None:
    """punti: array 33x3 (x, y in pixel, visibilità). Ritorna seduto | sdraiato | in_piedi | chino | None."""
    if punti is None:
        return posa_da_forma(box)
    spalle = _media(punti, SPALLE)
    anche = _media(punti, ANCHE)
    if spalle is None or anche is None:
        return posa_da_forma(box)
    dx, dy = spalle - anche
    lunghezza_busto = math.hypot(dx, dy)
    if lunghezza_busto < 1e-3:
        return posa_da_forma(box)
    angolo_busto = math.degrees(math.atan2(abs(dx), abs(dy)))  # 0 = dritto in verticale
    if angolo_busto > 60 or dy > 0:  # busto orizzontale, o spalle sotto le anche
        return "sdraiato"
    ginocchia = _media(punti, GINOCCHIA)
    caviglie = _media(punti, CAVIGLIE)
    seduto = None
    if ginocchia is not None:
        tx, ty = ginocchia - anche
        angolo_coscia = math.degrees(math.atan2(abs(ty), abs(tx) + 1e-6))  # 90 = coscia verticale
        coscia_corta = math.hypot(tx, ty) < 0.45 * lunghezza_busto  # coscia vista di fronte, accorciata
        seduto = angolo_coscia < 45 or coscia_corta
        if not seduto and caviglie is not None and caviglie[1] > ginocchia[1] and angolo_busto < 30:
            return "in_piedi"
    if seduto is None:
        forma = posa_da_forma(box)
        seduto = forma != "in_piedi"
        if not seduto:
            return "in_piedi"
    if seduto:
        naso = punti[NASO]
        testa_bassa = naso[2] >= VISIBILE and naso[1] > spalle[1] - 0.15 * lunghezza_busto
        if angolo_busto > 25 or testa_bassa:
            return "chino"
        return "seduto"
    return "in_piedi"


def posa_da_forma(box: Box) -> str | None:
    """Quando i punti non bastano: la forma del riquadro."""
    if box.h <= 0 or box.l <= 0:
        return None
    if box.l > 1.3 * box.h:
        return "sdraiato"
    if box.h > 2.4 * box.l:
        return "in_piedi"
    return None


def punti_mani(punti: np.ndarray | None) -> list[tuple[float, float]]:
    if punti is None:
        return []
    return [(float(punti[i, 0]), float(punti[i, 1])) for i in POLSI + MANI if punti[i, 2] >= VISIBILE]


class Posa:
    def __init__(self, percorso: Path | str):
        import mediapipe as mp
        from mediapipe.tasks.python import BaseOptions, vision

        self._mp = mp
        opzioni = vision.PoseLandmarkerOptions(
            base_options=BaseOptions(model_asset_path=str(percorso)),
            running_mode=vision.RunningMode.IMAGE, num_poses=1,
            min_pose_detection_confidence=0.4, min_pose_presence_confidence=0.4)
        self._rilevatore = vision.PoseLandmarker.create_from_options(opzioni)

    def punti(self, ritaglio_bgr: np.ndarray) -> np.ndarray | None:
        """33x3 in pixel del ritaglio (x, y, visibilità), o None se non trova una persona."""
        import cv2

        if ritaglio_bgr.size == 0:
            return None
        rgb = cv2.cvtColor(ritaglio_bgr, cv2.COLOR_BGR2RGB)
        immagine = self._mp.Image(image_format=self._mp.ImageFormat.SRGB, data=np.ascontiguousarray(rgb))
        risultato = self._rilevatore.detect(immagine)
        if not risultato.pose_landmarks:
            return None
        h, w = ritaglio_bgr.shape[:2]
        return np.array([[p.x * w, p.y * h, p.visibility if p.visibility is not None else 1.0]
                         for p in risultato.pose_landmarks[0]], dtype=np.float32)

    def chiudi(self) -> None:
        self._rilevatore.close()
