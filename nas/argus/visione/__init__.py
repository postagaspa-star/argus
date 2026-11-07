"""Visione: telecamere, modelli, "dove sta", inseguimento, diario della scena.

Qui c'è solo l'interfaccia verso il servizio. I moduli pesanti (OpenCV, ONNX Runtime, OpenVINO,
MediaPipe) si caricano solo quando ci sono telecamere configurate: senza telecamere Argus è
inattivo e non carica nessun modello.
"""

from __future__ import annotations

from datetime import datetime


class SorgenteVisione:
    """Quello che il servizio chiede alla visione."""

    def avvia(self) -> None:  # pragma: no cover - interfaccia
        pass

    def ferma(self) -> None:  # pragma: no cover - interfaccia
        pass

    def imposta_contesto(self, contesto: dict) -> None:
        """Dal motore: analizzare o no, dm in corso (la persona sdraiata vale come lo studente)."""

    def minuto(self, inizio: datetime) -> dict:  # pragma: no cover - interfaccia
        """I campi del `Minuto` (senza `ora` e `pc`) per il minuto che comincia a `inizio`."""
        raise NotImplementedError

    def scena(self, ora: datetime) -> dict | None:
        """L'ultima scena vista (per il diario)."""
        return None

    def telecamere(self) -> dict[str, str]:
        """Salute: id telecamera -> "ok" | "errore" | "assente"."""
        return {}

    def registra(self, tipo: str, immagini: list[bytes]) -> tuple[str | None, list]:
        """Vettori per lb/qd/tf (immagine) e vs (viso). Ritorna (nome del modello, vettori o None)."""
        return None, [None for _ in immagini]

    def ricarica_registrati(self) -> None:
        """Rilegge i vettori registrati dal database."""
