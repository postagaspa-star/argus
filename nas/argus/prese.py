"""Prese smart via Home Assistant (facoltativo, contratto sezione 4).

config.json:
    "home_assistant": "http://<nas>:8123",
    "prese": [{"dispositivo": "tv", "stanza": "salotto e cucina", "entity_id": "switch.tv"}]
token in .env: HA_TOKEN. Se manca qualcosa, niente prese.
"""

from __future__ import annotations

import logging

import httpx

log = logging.getLogger("argus.prese")


class Prese:
    def __init__(self, url: str | None, token: str | None, prese: list[dict], client: httpx.AsyncClient):
        self.url = url.rstrip("/") if url else None
        self.token = token
        self.prese = prese or []
        self.client = client

    @property
    def configurate(self) -> bool:
        return bool(self.url and self.token and self.prese)

    def da_spegnere(self, dispositivo: str, stanza: str | None) -> list[str]:
        trovate = []
        for p in self.prese:
            if p.get("dispositivo") not in (dispositivo, "tv" if dispositivo == "console" else None):
                continue
            if stanza and p.get("stanza") and p["stanza"] != stanza:
                continue
            if p.get("entity_id"):
                trovate.append(p["entity_id"])
        return trovate

    async def spegni(self, dispositivo: str, stanza: str | None) -> list[str]:
        if not self.configurate:
            return []
        spente = []
        for entita in self.da_spegnere(dispositivo, stanza):
            try:
                r = await self.client.post(f"{self.url}/api/services/switch/turn_off",
                                           json={"entity_id": entita},
                                           headers={"Authorization": f"Bearer {self.token}"}, timeout=10.0)
                if r.status_code < 300:
                    spente.append(entita)
                else:
                    log.warning("Home Assistant: %s -> %s", entita, r.status_code)
            except httpx.HTTPError as e:
                log.warning("Home Assistant non raggiungibile: %s", e)
        return spente
