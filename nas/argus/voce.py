"""La voce (regole sezione 11, contratto sezione 4).

1. Il testo diventa un wav col servizio voci del NAS (lectio-voci, motore supertonic). Ogni frase
   si tiene in cache su disco in /data/voce/ (le frasi fisse si preparano all'avvio).
2. Il wav va all'altoparlante della Tapo della stanza tramite go2rtc:
       POST {go2rtc}/api/streams?dst=<telecamera>_voce&src=ffmpeg:<url del wav>#audio=pcma#input=file
   (documentazione di go2rtc: "Stream to camera"; le Tapo accettano solo PCMA/8000, `#input=file`
   serve perché è un file e va mandato in tempo reale).
3. Se lì non si può, la frase va al PC: GET /api/pc/stato ha "di_voce" e il PC la suona una volta.

Le regole "mai durante dm" e "una frase ogni 2 minuti" le applica già il motore.
"""

from __future__ import annotations

import hashlib
import logging
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import quote

import httpx

from . import testi

log = logging.getLogger("argus.voce")

DURATA_DI_VOCE_PC = timedelta(seconds=90)


@dataclass
class VocePerPc:
    id: str
    file: Path
    scade: datetime

    def a_dict(self) -> dict:
        return {"id": self.id, "url": f"/api/pc/voce/{self.id}.wav"}


class Voce:
    def __init__(self, voci_url: str, motore_voce: str, cartella: Path, client: httpx.AsyncClient,
                 go2rtc_url: str | None, url_interno: str, altoparlanti: dict[str, str]):
        """altoparlanti: stanza -> nome della telecamera con ritorno audio in go2rtc."""
        self.voci_url = voci_url.rstrip("/")
        self.motore_voce = motore_voce
        self.cartella = Path(cartella)
        self.cartella.mkdir(parents=True, exist_ok=True)
        self.client = client
        self.go2rtc_url = go2rtc_url.rstrip("/") if go2rtc_url else None
        self.url_interno = url_interno.rstrip("/")
        self.altoparlanti = altoparlanti
        self.per_pc: VocePerPc | None = None
        self._per_pc_file: dict[str, Path] = {}
        self.ultimo_ok: bool | None = None

    def nome_file(self, testo: str) -> str:
        return hashlib.sha1(f"{self.motore_voce}|{testo}".encode("utf-8")).hexdigest() + ".wav"

    async def prepara(self, testo: str) -> Path | None:
        percorso = self.cartella / self.nome_file(testo)
        if percorso.exists() and percorso.stat().st_size > 44:
            return percorso
        try:
            r = await self.client.post(f"{self.voci_url}/voce", json={"motore": self.motore_voce, "testo": testo},
                                       timeout=60.0)
        except httpx.HTTPError as e:
            log.warning("Servizio voci non raggiungibile: %s", e)
            self.ultimo_ok = False
            return None
        if r.status_code != 200 or len(r.content) <= 44:
            log.warning("Servizio voci: risposta %s", r.status_code)
            self.ultimo_ok = False
            return None
        self.ultimo_ok = True
        temporaneo = percorso.with_suffix(".tmp")
        temporaneo.write_bytes(r.content)
        temporaneo.replace(percorso)
        return percorso

    async def prepara_fisse(self) -> int:
        n = 0
        for frase in testi.FRASI_FISSE_VOCE:
            if await self.prepara(frase):
                n += 1
        return n

    async def dici(self, testo: str, stanza: str | None, ora: datetime) -> str:
        """Ritorna dove è andata la frase: "telecamera", "pc" o "niente"."""
        percorso = await self.prepara(testo)
        if percorso is None:
            return "niente"
        telecamera = self.altoparlanti.get(stanza or "") if stanza else None
        if telecamera is None and len(self.altoparlanti) == 1 and stanza is None:
            telecamera = next(iter(self.altoparlanti.values()))
        if telecamera and self.go2rtc_url:
            sorgente = f"ffmpeg:{self.url_interno}/interno/voce/{percorso.name}#audio=pcma#input=file"
            url = f"{self.go2rtc_url}/api/streams?dst={quote(telecamera, safe='')}&src={quote(sorgente, safe='')}"
            try:
                r = await self.client.post(url, timeout=10.0)
                if r.status_code < 300:
                    return "telecamera"
                log.warning("go2rtc non ha preso l'audio per %s: %s", telecamera, r.status_code)
            except httpx.HTTPError as e:
                log.warning("go2rtc non raggiungibile: %s", e)
        # Ripiego: la frase la dice il PC.
        voce_pc = VocePerPc(id=uuid.uuid4().hex[:16], file=percorso, scade=ora + DURATA_DI_VOCE_PC)
        self.per_pc = voce_pc
        self._per_pc_file = {voce_pc.id: percorso}
        return "pc"

    def di_voce(self, ora: datetime) -> dict | None:
        if self.per_pc is None or ora >= self.per_pc.scade:
            return None
        return self.per_pc.a_dict()

    def file_per_pc(self, id_voce: str) -> Path | None:
        return self._per_pc_file.get(id_voce)

    def file_interno(self, nome: str) -> Path | None:
        if not nome.endswith(".wav") or "/" in nome or "\\" in nome or ".." in nome:
            return None
        percorso = self.cartella / nome
        return percorso if percorso.exists() else None
