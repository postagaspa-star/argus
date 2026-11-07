"""Riquadri (x1, y1, x2, y2) in pixel e piccoli conti su di essi."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Box:
    x1: float
    y1: float
    x2: float
    y2: float

    @property
    def l(self) -> float:
        return max(0.0, self.x2 - self.x1)

    @property
    def h(self) -> float:
        return max(0.0, self.y2 - self.y1)

    @property
    def area(self) -> float:
        return self.l * self.h

    @property
    def centro(self) -> tuple[float, float]:
        return (self.x1 + self.x2) / 2, (self.y1 + self.y2) / 2

    def intersezione(self, altro: "Box") -> float:
        x1, y1 = max(self.x1, altro.x1), max(self.y1, altro.y1)
        x2, y2 = min(self.x2, altro.x2), min(self.y2, altro.y2)
        return max(0.0, x2 - x1) * max(0.0, y2 - y1)

    def iou(self, altro: "Box") -> float:
        inter = self.intersezione(altro)
        unione = self.area + altro.area - inter
        return inter / unione if unione > 0 else 0.0

    def frazione_dentro(self, altro: "Box") -> float:
        """Quanta parte di questo riquadro sta dentro `altro` (0..1)."""
        return self.intersezione(altro) / self.area if self.area > 0 else 0.0

    def allarga(self, fattore: float, larghezza: float | None = None, altezza: float | None = None) -> "Box":
        cx, cy = self.centro
        mezza_l, mezza_h = self.l * fattore / 2, self.h * fattore / 2
        b = Box(cx - mezza_l, cy - mezza_h, cx + mezza_l, cy + mezza_h)
        return b.limita(larghezza, altezza) if larghezza and altezza else b

    def limita(self, larghezza: float, altezza: float) -> "Box":
        return Box(max(0.0, self.x1), max(0.0, self.y1), min(larghezza, self.x2), min(altezza, self.y2))

    def scala(self, sx: float, sy: float) -> "Box":
        return Box(self.x1 * sx, self.y1 * sy, self.x2 * sx, self.y2 * sy)

    def sposta(self, dx: float, dy: float) -> "Box":
        return Box(self.x1 + dx, self.y1 + dy, self.x2 + dx, self.y2 + dy)

    def interi(self) -> tuple[int, int, int, int]:
        return int(self.x1), int(self.y1), int(round(self.x2)), int(round(self.y2))

    def contiene_punto(self, x: float, y: float) -> bool:
        return self.x1 <= x <= self.x2 and self.y1 <= y <= self.y2
