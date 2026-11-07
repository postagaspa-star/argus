"""Servizi finti per le prove: SemIf, voci, go2rtc, Home Assistant e una visione a copione."""

from __future__ import annotations

import json
import struct
from datetime import datetime

import httpx

from argus.config import Config, Telecamera
from argus.visione import SorgenteVisione


def wav_finto(secondi: float = 0.2) -> bytes:
    campioni = int(16000 * secondi)
    dati = b"\x00\x00" * campioni
    return (b"RIFF" + struct.pack("<I", 36 + len(dati)) + b"WAVEfmt " + struct.pack("<IHHIIHH", 16, 1, 1, 16000, 32000, 2, 16)
            + b"data" + struct.pack("<I", len(dati)) + dati)


class Rete:
    """Risponde al posto dei servizi del NAS e tiene nota delle richieste."""

    def __init__(self):
        self.richieste: list[httpx.Request] = []
        self.risposte_semif: list = []  # dict (risposta) oppure int (codice http)
        self.go2rtc_ok = True
        self.voci_ok = True

    def gestisci(self, request: httpx.Request) -> httpx.Response:
        self.richieste.append(request)
        host = request.url.host
        if host == "sol-decisore":
            if not self.risposte_semif:
                return httpx.Response(503, json={"errore": "occupato", "codice": "decisore_non_disponibile"})
            r = self.risposte_semif.pop(0)
            if isinstance(r, int):
                return httpx.Response(r, json={"codice": "decisore_non_disponibile"})
            return httpx.Response(200, json=r)
        if host == "lectio-voci":
            if request.url.path == "/voce" and self.voci_ok:
                return httpx.Response(200, content=wav_finto(), headers={"content-type": "audio/wav"})
            return httpx.Response(503)
        if host == "argus-go2rtc":
            return httpx.Response(200 if self.go2rtc_ok else 500)
        if host == "ha":
            return httpx.Response(200, json=[])
        return httpx.Response(404)

    def client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(transport=httpx.MockTransport(self.gestisci))

    def a(self, host: str) -> list[httpx.Request]:
        return [r for r in self.richieste if r.url.host == host]

    def corpi_semif(self) -> list[dict]:
        return [json.loads(r.content) for r in self.a("sol-decisore")]


def risposta_semif(id_domanda: str, scelta: str, probabilita: float = 0.9, massa: float = 0.95) -> dict:
    return {"risposte": {id_domanda: {"scelta": scelta, "probabilita": {scelta: probabilita}, "massa_opzioni": massa}},
            "millisecondi": 1200}


class VisioneFinta(SorgenteVisione):
    """La visione a copione: per ogni minuto i campi del Minuto (di base: non visto)."""

    def __init__(self):
        self.copione: dict[datetime, dict] = {}
        self.di_base: dict = {"visto": False}
        self.contesto: dict = {}
        self.registrati: list = []
        self.avviata = False

    def avvia(self) -> None:
        self.avviata = True

    def ferma(self) -> None:
        self.avviata = False

    def imposta_contesto(self, contesto: dict) -> None:
        self.contesto = contesto

    def minuto(self, inizio: datetime) -> dict:
        return dict(self.copione.get(inizio, self.di_base))

    def scena(self, ora: datetime) -> dict | None:
        campi = self.di_base
        return {"visto": campi.get("visto"), "stanza": campi.get("stanza"), "dove": campi.get("dove"),
                "posa": campi.get("posa"), "in_mano": sorted(campi.get("in_mano", []))}

    def telecamere(self) -> dict[str, str]:
        return {"camera": "ok"}

    def registra(self, tipo: str, immagini: list[bytes]):
        self.registrati.append((tipo, len(immagini)))
        import numpy as np
        return "finto", [np.ones(4, dtype=np.float32) for _ in immagini]


def config_con_telecamera(altoparlante: bool = True, prese: bool = False) -> Config:
    c = Config(telecamere=[Telecamera(id="camera", stanza="camera",
                                      altoparlante="tapo://segreto@telecamera" if altoparlante else None)])
    if prese:
        c.home_assistant = "http://ha:8123"
        c.home_assistant_token = "token-ha"
        c.prese = [{"dispositivo": "tv", "stanza": "camera", "entity_id": "switch.tv"}]
    return c
