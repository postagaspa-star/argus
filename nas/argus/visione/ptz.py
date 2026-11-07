"""Inseguimento PTZ (regole sezione 15).

- La telecamera della stanza dove sta lo studente si muove per tenerlo al centro.
- Zona morta 20%: se il centro della persona sta nel riquadro centrale largo il 20% dell'immagine
  (cioè entro il 10% dal centro, in orizzontale e in verticale), non si muove niente.
- Al massimo un movimento ogni 2 secondi: ContinuousMove a impulsi (breve) e poi Stop.
- Dopo 60 secondi senza di lui torna alla posizione di partenza.
- Se il comando di movimento non funziona (3 errori di fila), Argus smette di muoverla e si usa
  l'inseguimento integrato della telecamera (va acceso nell'app Tapo).
"""

from __future__ import annotations

import logging
import threading
from pathlib import Path
from typing import Callable

log = logging.getLogger("argus.ptz")


class Ptz:
    """Interfaccia: velocità da -1 a 1 (x positivo = a destra, y positivo = in alto)."""

    def muovi(self, vx: float, vy: float) -> None:  # pragma: no cover - interfaccia
        raise NotImplementedError

    def ferma(self) -> None:  # pragma: no cover - interfaccia
        raise NotImplementedError

    def segna_partenza(self) -> None:
        pass

    def torna_partenza(self) -> None:  # pragma: no cover - interfaccia
        raise NotImplementedError


class PtzFinto(Ptz):
    """Telecamera finta: ricorda i comandi e simula la posizione."""

    def __init__(self, rotta: bool = False):
        self.comandi: list[tuple] = []
        self.posizione = [0.0, 0.0]
        self.rotta = rotta

    def muovi(self, vx: float, vy: float) -> None:
        if self.rotta:
            raise ConnectionError("telecamera finta rotta")
        self.comandi.append(("muovi", round(vx, 3), round(vy, 3)))
        self.posizione[0] += vx
        self.posizione[1] += vy

    def ferma(self) -> None:
        if self.rotta:
            raise ConnectionError("telecamera finta rotta")
        self.comandi.append(("ferma",))

    def segna_partenza(self) -> None:
        self.comandi.append(("segna_partenza",))

    def torna_partenza(self) -> None:
        if self.rotta:
            raise ConnectionError("telecamera finta rotta")
        self.comandi.append(("torna_partenza",))
        self.posizione = [0.0, 0.0]


class PtzOnvif(Ptz):
    """PTZ via ONVIF (onvif-zeep). Le Tapo rispondono di solito sulla porta 2020."""

    PRESET = "argus-partenza"

    def __init__(self, host: str, porta: int, utente: str, password: str):
        from onvif import ONVIFCamera
        import onvif

        wsdl = Path(onvif.__file__).parent / "wsdl"
        if not wsdl.exists():
            wsdl = Path(onvif.__file__).parent.parent / "wsdl"
        self._cam = ONVIFCamera(host, porta, utente, password, str(wsdl))
        self._media = self._cam.create_media_service()
        self._ptz = self._cam.create_ptz_service()
        self._profilo = self._media.GetProfiles()[0].token
        self._preset: str | None = None
        self._posizione = None

    def muovi(self, vx: float, vy: float) -> None:
        richiesta = self._ptz.create_type("ContinuousMove")
        richiesta.ProfileToken = self._profilo
        richiesta.Velocity = {"PanTilt": {"x": float(vx), "y": float(vy)}}
        self._ptz.ContinuousMove(richiesta)

    def ferma(self) -> None:
        self._ptz.Stop({"ProfileToken": self._profilo, "PanTilt": True, "Zoom": False})

    def segna_partenza(self) -> None:
        try:
            self._preset = self._ptz.SetPreset({"ProfileToken": self._profilo, "PresetName": self.PRESET})
        except Exception as e:  # noqa: BLE001 - non tutte le Tapo accettano SetPreset
            log.info("SetPreset non disponibile (%s): provo con la posizione", e)
            self._preset = None
        try:
            stato = self._ptz.GetStatus({"ProfileToken": self._profilo})
            self._posizione = stato.Position
        except Exception:  # noqa: BLE001
            self._posizione = None

    def torna_partenza(self) -> None:
        if self._preset:
            self._ptz.GotoPreset({"ProfileToken": self._profilo, "PresetToken": self._preset})
            return
        if self._posizione is not None:
            try:
                self._ptz.AbsoluteMove({"ProfileToken": self._profilo, "Position": self._posizione})
                return
            except Exception:  # noqa: BLE001
                pass
        self._ptz.GotoHomePosition({"ProfileToken": self._profilo})


class Inseguitore:
    def __init__(self, ptz: Ptz, zona_morta: float = 0.20, intervallo: float = 2.0, impulso: float = 0.35,
                 velocita: float = 0.5, ritorno_dopo: float = 60.0, inverti_pan: bool = False,
                 inverti_tilt: bool = False, sincrono: bool = False,
                 quando_spento: Callable[[str], None] | None = None):
        self.ptz = ptz
        self.zona_morta = zona_morta
        self.intervallo = intervallo
        self.impulso = impulso
        self.velocita = velocita
        self.ritorno_dopo = ritorno_dopo
        self.segno_pan = -1.0 if inverti_pan else 1.0
        self.segno_tilt = -1.0 if inverti_tilt else 1.0
        self.sincrono = sincrono
        self.quando_spento = quando_spento
        self.attivo = True
        self.errori = 0
        self.ultimo_movimento: float | None = None
        self.ultimo_visto: float | None = None
        self.spostato = False
        self._partenza_segnata = False

    def _esegui(self, azione: Callable[[], None]) -> bool:
        try:
            azione()
            self.errori = 0
            return True
        except Exception as e:  # noqa: BLE001 - la telecamera può non rispondere in mille modi
            self.errori += 1
            log.warning("Comando PTZ non riuscito (%d): %s", self.errori, e)
            if self.errori >= 3:
                self.attivo = False
                log.warning("PTZ spento: si usa l'inseguimento integrato della telecamera")
                if self.quando_spento:
                    self.quando_spento(str(e))
            return False

    def aggiorna(self, centro: tuple[float, float] | None, adesso: float) -> str | None:
        """centro: centro dello studente in coordinate 0..1 dell'immagine (o None se non c'è)."""
        if not self.attivo:
            return None
        if not self._partenza_segnata:
            self._partenza_segnata = True
            self._esegui(self.ptz.segna_partenza)
        if centro is None:
            if (self.spostato and self.ultimo_visto is not None
                    and adesso - self.ultimo_visto >= self.ritorno_dopo):
                if self._esegui(self.ptz.torna_partenza):
                    self.spostato = False
                    self.ultimo_movimento = adesso
                    return "partenza"
            return None
        self.ultimo_visto = adesso
        dx, dy = centro[0] - 0.5, centro[1] - 0.5
        soglia = self.zona_morta / 2
        if abs(dx) <= soglia and abs(dy) <= soglia:
            return None
        if self.ultimo_movimento is not None and adesso - self.ultimo_movimento < self.intervallo:
            return None
        vx = (self.velocita if dx > 0 else -self.velocita) * self.segno_pan if abs(dx) > soglia else 0.0
        vy = (-self.velocita if dy > 0 else self.velocita) * self.segno_tilt if abs(dy) > soglia else 0.0
        if not self._esegui(lambda: self.ptz.muovi(vx, vy)):
            return None
        self.ultimo_movimento = adesso
        self.spostato = True
        if self.sincrono:
            self._esegui(self.ptz.ferma)
        else:
            threading.Timer(self.impulso, lambda: self._esegui(self.ptz.ferma)).start()
        return "muovi"

    def si_sta_muovendo(self, adesso: float, margine: float = 1.5) -> bool:
        return self.ultimo_movimento is not None and adesso - self.ultimo_movimento < self.impulso + margine
