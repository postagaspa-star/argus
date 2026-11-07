"""Regole della visione senza modelli (pure, provate a parte):
"dove sta" dagli oggetti, cosa ha in mano, schermi accesi, fermo o no.

Principio: nel dubbio non si dice niente. Un oggetto conta "in mano" solo se è vicino a una mano;
uno schermo conta "acceso" solo se è chiaramente più luminoso di quello che ha intorno o se cambia
da un'immagine all'altra (una TV accesa cambia sempre).
"""

from __future__ import annotations

import math
from collections import deque
from dataclasses import dataclass, field

import cv2
import numpy as np

from .geometria import Box
from .rilevatore import CIBO, Rilevamento

ARREDI = {"couch", "bed", "chair", "dining table"}
POSTAZIONE = {"laptop", "keyboard", "mouse", "tv"}
OGGETTI_PICCOLI = {"cell phone", "book", "remote", "cup", "bottle", "laptop"} | CIBO


def dove_sta(persona: Box, posa: str | None, rilevamenti: list[Rilevamento]) -> str | None:
    """Regole sezione 15: divano (couch), letto (bed), scrivania (sedia + tavolo o portatile davanti),
    in piedi. None se non si capisce."""
    if posa == "in_piedi":
        return "in_piedi"
    # Parte bassa della persona (bacino e gambe): è quella che appoggia sul mobile.
    bassa = Box(persona.x1, persona.y1 + persona.h * 0.4, persona.x2, persona.y2)
    migliore: tuple[str | None, float] = (None, 0.0)
    for r in rilevamenti:
        if r.classe in ("bed", "couch"):
            f = bassa.frazione_dentro(r.box)
            if f > migliore[1]:
                migliore = ("letto" if r.classe == "bed" else "divano", f)
    if migliore[0] and migliore[1] >= 0.3:
        return migliore[0]
    attorno = persona.allarga(1.6)
    sedia = any(r.classe == "chair" and r.box.intersezione(persona) > 0.1 * persona.area for r in rilevamenti)
    tavolo = any(r.classe == "dining table" and r.box.intersezione(attorno) > 0 for r in rilevamenti)
    postazione = any(r.classe in POSTAZIONE and r.box.intersezione(attorno) > 0
                     and r.box.area < 1.5 * persona.area for r in rilevamenti)
    if postazione or (sedia and tavolo):
        return "scrivania"
    if posa == "sdraiato":
        return None
    return None


def vicino_alle_mani(oggetto: Box, mani: list[tuple[float, float]], persona: Box) -> bool:
    """Una mano (polso o dita) dentro l'oggetto allargato, o molto vicino."""
    if not mani:
        return False
    margine = max(8.0, 0.06 * persona.h)
    allargato = Box(oggetto.x1 - margine, oggetto.y1 - margine, oggetto.x2 + margine, oggetto.y2 + margine)
    return any(allargato.contiene_punto(x, y) for x, y in mani)


@dataclass
class OggettoPersona:
    rilevamento: Rilevamento
    in_mano: bool
    vicino: bool
    davanti_al_busto: bool


def oggetti_della_persona(persona: Box, mani: list[tuple[float, float]], spalle_y: float | None,
                          anche_y: float | None, rilevamenti: list[Rilevamento]) -> list[OggettoPersona]:
    attorno = persona.allarga(1.5)
    uscita = []
    for r in rilevamenti:
        if r.classe not in OGGETTI_PICCOLI:
            continue
        if r.box.area > 0.6 * persona.area and r.classe != "laptop":
            continue
        if r.box.intersezione(attorno) <= 0:
            continue
        in_mano = vicino_alle_mani(r.box, mani, persona)
        cy = r.box.centro[1]
        # Davanti al busto o al viso (come si tiene un telefono che si sta usando), non giù lungo
        # il fianco. Se le anche non si vedono (inquadratura tagliata) si stima il busto.
        if spalle_y is not None:
            busto = abs(anche_y - spalle_y) if anche_y is not None else 0.3 * persona.h
            busto = max(busto, 1.0)
            alto = min(spalle_y, anche_y) if anche_y is not None else spalle_y
            basso = max(spalle_y, anche_y) if anche_y is not None else spalle_y + busto
            davanti = (alto - busto) <= cy <= (basso + 0.35 * busto) and persona.contiene_punto(*r.box.centro)
        else:
            davanti = persona.contiene_punto(*r.box.centro) and cy <= persona.y1 + 0.7 * persona.h
        uscita.append(OggettoPersona(r, in_mano, True, davanti))
    return uscita


def stato_schermo(ritaglio: np.ndarray, contorno: np.ndarray | None,
                  precedente: np.ndarray | None = None) -> str | None:
    """"acceso" | "spento" | None. Ritaglio = lo schermo; contorno = un po' di immagine attorno."""
    if ritaglio is None or ritaglio.size == 0 or min(ritaglio.shape[:2]) < 6:
        return None
    h, w = ritaglio.shape[:2]
    centro = ritaglio[int(h * 0.15):int(h * 0.85), int(w * 0.15):int(w * 0.85)]
    if centro.size == 0:
        centro = ritaglio
    v = cv2.cvtColor(centro, cv2.COLOR_BGR2HSV)[:, :, 2].astype(np.float32)
    media = float(v.mean())
    variazione = float(v.std())
    rel = None
    if contorno is not None and contorno.size:
        vc = cv2.cvtColor(contorno, cv2.COLOR_BGR2HSV)[:, :, 2].astype(np.float32)
        rel = (media + 1.0) / (float(vc.mean()) + 1.0)
    cambio = None
    if precedente is not None and precedente.size:
        a = cv2.resize(cv2.cvtColor(centro, cv2.COLOR_BGR2GRAY), (48, 32)).astype(np.float32)
        b = cv2.resize(cv2.cvtColor(precedente, cv2.COLOR_BGR2GRAY), (48, 32)).astype(np.float32)
        cambio = float(np.abs(a - b).mean())
    if cambio is not None and cambio > 10 and media > 40:
        return "acceso"
    if rel is not None and rel > 1.35 and media > 90:
        return "acceso"
    if rel is not None and rel < 0.8 and variazione < 22 and (cambio is None or cambio < 3):
        return "spento"
    return None


def anello(immagine: np.ndarray, box: Box, fattore: float = 1.6) -> np.ndarray | None:
    """L'immagine attorno al riquadro (per confrontare la luminosità)."""
    h, w = immagine.shape[:2]
    grande = box.allarga(fattore, w, h)
    x1, y1, x2, y2 = grande.interi()
    pezzo = immagine[y1:y2, x1:x2].copy()
    if pezzo.size == 0:
        return None
    bx1, by1, bx2, by2 = box.interi()
    maschera = np.ones(pezzo.shape[:2], dtype=bool)
    maschera[max(0, by1 - y1):max(0, by2 - y1), max(0, bx1 - x1):max(0, bx2 - x1)] = False
    if not maschera.any():
        return None
    return pezzo[maschera].reshape(-1, 1, 3)


@dataclass
class StoriaMovimento:
    """Punti del corpo degli ultimi secondi, per dire se la persona è ferma."""

    secondi: float = 20.0
    campioni: deque = field(default_factory=deque)

    def aggiungi(self, quando: float, punti: np.ndarray | None, box: Box, telecamera_ferma: bool) -> None:
        if not telecamera_ferma:
            self.campioni.clear()  # se la telecamera si muove, il confronto non vale
            return
        if punti is not None:
            indici = [0, 11, 12, 15, 16, 23, 24]
            scelti = punti[indici]
            vis = scelti[:, 2] >= 0.5
            spalle = punti[[11, 12]]
            busto = None
            if (punti[[11, 12, 23, 24], 2] >= 0.5).all():
                busto = math.dist(spalle[:, :2].mean(axis=0), punti[[23, 24], :2].mean(axis=0))
            scala = busto or max(box.h * 0.35, 1.0)
            self.campioni.append((quando, scelti[:, :2].copy(), vis, scala))
        else:
            self.campioni.append((quando, np.array([[box.centro[0], box.centro[1]]]), np.array([True]),
                                  max(box.h * 0.35, 1.0)))
        while self.campioni and quando - self.campioni[0][0] > self.secondi:
            self.campioni.popleft()

    def fermo(self, minimo_secondi: float = 10.0, soglia: float = 0.06) -> bool | None:
        """True se negli ultimi secondi i punti non si sono mossi più del 6% del busto."""
        if len(self.campioni) < 3:
            return None
        if self.campioni[-1][0] - self.campioni[0][0] < minimo_secondi:
            return None
        riferimento = self.campioni[0]
        massimo = 0.0
        for quando, punti, vis, scala in list(self.campioni)[1:]:
            if punti.shape != riferimento[1].shape:
                return None
            comuni = vis & riferimento[2]
            if not comuni.any():
                continue
            spostamento = np.linalg.norm(punti[comuni] - riferimento[1][comuni], axis=1).max() / scala
            massimo = max(massimo, float(spostamento))
        return massimo < soglia
