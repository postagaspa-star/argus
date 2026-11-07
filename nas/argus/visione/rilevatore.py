"""Rilevatore di oggetti COCO: D-FINE S (Apache-2.0) in ONNX.

Ingresso: immagine RGB 640x640 in [0, 1] (niente normalizzazione, come il suo preprocessor).
Uscita: 300 proposte con punteggi (sigmoide) sulle 80 classi COCO e riquadri (cx, cy, l, h)
normalizzati.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np

from .esecutore import Esecutore
from .geometria import Box

# Ordine delle classi del modello (config.json di dfine_*_coco), con i nomi COCO di oggi.
CLASSI = ['person', 'bicycle', 'car', 'motorcycle', 'airplane', 'bus', 'train', 'truck', 'boat', 'traffic light',
          'fire hydrant', 'stop sign', 'parking meter', 'bench', 'bird', 'cat', 'dog', 'horse', 'sheep', 'cow',
          'elephant', 'bear', 'zebra', 'giraffe', 'backpack', 'umbrella', 'handbag', 'tie', 'suitcase', 'frisbee',
          'skis', 'snowboard', 'sports ball', 'kite', 'baseball bat', 'baseball glove', 'skateboard', 'surfboard',
          'tennis racket', 'bottle', 'wine glass', 'cup', 'fork', 'knife', 'spoon', 'bowl', 'banana', 'apple',
          'sandwich', 'orange', 'broccoli', 'carrot', 'hot dog', 'pizza', 'donut', 'cake', 'chair', 'couch',
          'potted plant', 'bed', 'dining table', 'toilet', 'tv', 'laptop', 'mouse', 'remote', 'keyboard',
          'cell phone', 'microwave', 'oven', 'toaster', 'sink', 'refrigerator', 'book', 'clock', 'vase',
          'scissors', 'teddy bear', 'hair drier', 'toothbrush']

# Le classi che servono ad Argus (le altre si ignorano).
UTILI = {"person", "cell phone", "laptop", "tv", "remote", "book", "couch", "bed", "chair", "dining table",
         "cup", "bottle", "keyboard", "mouse", "bowl", "fork", "knife", "spoon", "banana", "apple", "sandwich",
         "orange", "pizza", "donut", "cake", "hot dog", "carrot", "broccoli"}
CIBO = {"bowl", "fork", "knife", "spoon", "banana", "apple", "sandwich", "orange", "pizza", "donut", "cake",
        "hot dog", "carrot", "broccoli"}
LATO = 640


@dataclass(frozen=True)
class Rilevamento:
    classe: str
    punteggio: float
    box: Box


class Rilevatore:
    def __init__(self, percorso: Path | str, dispositivo: str = "auto", thread: int = 2, soglia: float = 0.45):
        prova = np.zeros((1, 3, LATO, LATO), dtype=np.float32)
        self.esecutore = Esecutore(percorso, dispositivo, thread, prova=prova)
        self.soglia = soglia

    @staticmethod
    def prepara(immagine_bgr: np.ndarray) -> np.ndarray:
        rgb = cv2.cvtColor(immagine_bgr, cv2.COLOR_BGR2RGB)
        x = cv2.resize(rgb, (LATO, LATO), interpolation=cv2.INTER_LINEAR).astype(np.float32) / 255.0
        return x.transpose(2, 0, 1)[None]

    def rileva(self, immagine_bgr: np.ndarray, soglia: float | None = None,
               classi: set[str] | None = None) -> list[Rilevamento]:
        altezza, larghezza = immagine_bgr.shape[:2]
        logits, riquadri = self.esecutore.esegui(self.prepara(immagine_bgr))[:2]
        return decodifica(logits[0], riquadri[0], larghezza, altezza, soglia or self.soglia, classi or UTILI)


def decodifica(logits: np.ndarray, riquadri: np.ndarray, larghezza: int, altezza: int, soglia: float,
               classi: set[str]) -> list[Rilevamento]:
    punteggi = 1.0 / (1.0 + np.exp(-logits))
    uscita: list[Rilevamento] = []
    for q, c in np.argwhere(punteggi >= soglia):
        nome = CLASSI[int(c)]
        if nome not in classi:
            continue
        cx, cy, w, h = (float(v) for v in riquadri[q])
        box = Box((cx - w / 2) * larghezza, (cy - h / 2) * altezza, (cx + w / 2) * larghezza,
                  (cy + h / 2) * altezza).limita(larghezza, altezza)
        uscita.append(Rilevamento(nome, float(punteggi[q, c]), box))
    return nms(uscita)


def nms(rilevamenti: list[Rilevamento], soglia_iou: float = 0.7) -> list[Rilevamento]:
    """Toglie i doppioni della stessa classe (D-FINE di solito non ne fa, ma non si sa mai)."""
    tenuti: list[Rilevamento] = []
    for r in sorted(rilevamenti, key=lambda x: -x.punteggio):
        if all(t.classe != r.classe or t.box.iou(r.box) < soglia_iou for t in tenuti):
            tenuti.append(r)
    return tenuti
