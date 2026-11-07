"""Configurazione: /data/config.json (contratto, sezione 6) + variabili d'ambiente (.env).

Le password non stanno mai nel file: si scrivono come ${NOME} e si prendono dall'ambiente.
Esempio: "rtsp_principale": "rtsp://${TAPO_UTENTE}:${TAPO_CAMERA_PASSWORD}@${TAPO_CAMERA_IP}:554/stream1"
"""

from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import dataclass, field
from pathlib import Path

log = logging.getLogger("argus.config")

_RE_VAR = re.compile(r"\$\{([A-Z0-9_]+)\}")


def espandi(valore: str | None, ambiente: dict | None = None) -> str | None:
    """Sostituisce ${NOME} con la variabile d'ambiente (vuota se manca, con un avviso nel log)."""
    if valore is None:
        return None
    env = os.environ if ambiente is None else ambiente

    def sostituisci(m: re.Match) -> str:
        nome = m.group(1)
        if nome not in env:
            log.warning("Variabile d'ambiente %s mancante (usata in config.json)", nome)
            return ""
        return env[nome]

    return _RE_VAR.sub(sostituisci, valore)


@dataclass
class Onvif:
    host: str
    porta: int = 2020
    utente: str = ""
    password: str = ""


@dataclass
class Telecamera:
    id: str
    stanza: str
    rtsp_principale: str | None = None
    rtsp_secondario: str | None = None
    onvif: Onvif | None = None
    altoparlante: str | None = None  # sorgente go2rtc con ritorno audio, es. tapo://${TAPO_CLOUD_PASSWORD}@ip
    insegui: bool = True
    inverti_pan: bool = False  # se la telecamera gira dalla parte sbagliata
    inverti_tilt: bool = False
    tv: bool = True  # c'è una televisione in questa stanza? (false dove c'è solo il monitor del PC)
    cartella_finta: str | None = None  # per le prove: immagini da una cartella al posto del flusso


@dataclass
class ConfigVisione:
    fps: float = 2.0  # immagini al secondo della telecamera dove c'è lo studente
    fps_attesa: float = 0.5  # immagini al secondo delle altre (o prima delle 11)
    modello: str = "dfine_s"
    dispositivo: str = "auto"  # auto | CPU | GPU (GPU Intel solo se /dev/dri funziona)
    thread: int = 2
    soglia_oggetti: float = 0.45
    soglia_viso: float = 0.363  # coseno SFace (valore consigliato da OpenCV)
    # Coseni SigLIP 2 su vettori centrati (vedi NOTE-COSTRUTTORE.md): stesso oggetto ~0,75-0,96,
    # oggetti diversi ~0 (due libri diversi anche 0,6: per questo il libro vuole 0,75).
    soglia_libro: float = 0.75
    soglia_telefono_suo: float = 0.70
    soglia_telefono_altro: float = 0.25
    # Senza il PC per le foto dubbie (regole, sezione 6): dopo `minuti_senza_pc` senza risposta il NAS
    # decide da solo SOLO con prove forti: telefono in mano con punteggio del rilevatore almeno
    # `soglia_senza_pc_rilevatore` in `immagini_senza_pc` immagini di fila e somiglianza SigLIP con il
    # suo telefono sotto `soglia_senza_pc_diverso`. Da tarare con le telecamere vere.
    minuti_senza_pc: int = 15
    immagini_senza_pc: int = 3
    soglia_senza_pc_rilevatore: float = 0.70
    soglia_senza_pc_diverso: float = 0.10


@dataclass
class Config:
    telecamere: list[Telecamera] = field(default_factory=list)
    sabato_scuola: bool = False
    patrono: str | None = None
    decisore_url: str = "http://sol-decisore:8300"
    voci_url: str = "http://lectio-voci:8000"
    voce: str = "supertonic"
    home_assistant: str | None = None
    home_assistant_token: str | None = None
    prese: list[dict] = field(default_factory=list)
    go2rtc_url: str = "http://argus-go2rtc:1984"
    go2rtc_rtsp: str = "rtsp://argus-go2rtc:8554"
    url_interno: str = "http://argus:8700"
    stanze_studente: list[str] = field(default_factory=lambda: ["camera"])
    verifiche: int = 0
    visione: ConfigVisione = field(default_factory=ConfigVisione)
    # Voci locali delle liste (siti dei clienti...): {"lavoro": {"programmi": [], "siti": []}, ...}
    liste_extra: dict = field(default_factory=dict)

    @property
    def inattivo(self) -> bool:
        return not self.telecamere


ESEMPIO = {
    "telecamere": [],
    "_esempio_telecamera": {
        "id": "camera",
        "stanza": "camera",
        "rtsp_principale": "rtsp://${TAPO_UTENTE}:${TAPO_CAMERA_PASSWORD}@${TAPO_CAMERA_IP}:554/stream1",
        "rtsp_secondario": "rtsp://${TAPO_UTENTE}:${TAPO_CAMERA_PASSWORD}@${TAPO_CAMERA_IP}:554/stream2",
        "onvif": {"host": "${TAPO_CAMERA_IP}", "porta": 2020, "utente": "${TAPO_UTENTE}",
                  "password_env": "TAPO_CAMERA_PASSWORD"},
        "altoparlante": "tapo://${TAPO_CLOUD_PASSWORD}@${TAPO_CAMERA_IP}",
    },
    "sabato_scuola": False,
    "patrono": None,
    "decisore_url": "http://sol-decisore:8300",
    "voci_url": "http://lectio-voci:8000",
    "voce": "supertonic",
    "home_assistant": None,
    "prese": [],
    "liste_extra": {"lavoro": {"programmi": [], "siti": []}, "studio": {"programmi": [], "siti": []}},
}


def da_dict(dati: dict, ambiente: dict | None = None) -> Config:
    env = os.environ if ambiente is None else ambiente
    telecamere = []
    for t in dati.get("telecamere") or []:
        onvif = None
        if t.get("onvif"):
            o = t["onvif"]
            password = env.get(o["password_env"], "") if o.get("password_env") else espandi(o.get("password", ""), env)
            onvif = Onvif(host=espandi(o["host"], env), porta=int(o.get("porta", 2020)),
                          utente=espandi(o.get("utente", ""), env) or "", password=password or "")
        telecamere.append(Telecamera(
            id=str(t["id"]),
            stanza=str(t.get("stanza") or t["id"]),
            rtsp_principale=espandi(t.get("rtsp_principale"), env),
            rtsp_secondario=espandi(t.get("rtsp_secondario"), env),
            onvif=onvif,
            altoparlante=espandi(t.get("altoparlante"), env),
            insegui=bool(t.get("insegui", True)),
            inverti_pan=bool(t.get("inverti_pan", False)),
            inverti_tilt=bool(t.get("inverti_tilt", False)),
            tv=bool(t.get("tv", True)),
            cartella_finta=t.get("cartella_finta"),
        ))
    visione = ConfigVisione(**{k: v for k, v in (dati.get("visione") or {}).items()
                               if k in ConfigVisione.__dataclass_fields__})
    ha = dati.get("home_assistant")
    return Config(
        telecamere=telecamere,
        sabato_scuola=bool(dati.get("sabato_scuola", False)),
        patrono=dati.get("patrono"),
        decisore_url=dati.get("decisore_url") or "http://sol-decisore:8300",
        voci_url=dati.get("voci_url") or "http://lectio-voci:8000",
        voce=dati.get("voce") or "supertonic",
        home_assistant=espandi(ha, env) if ha else None,
        home_assistant_token=env.get("HA_TOKEN") or None,
        prese=list(dati.get("prese") or []),
        go2rtc_url=dati.get("go2rtc_url") or "http://argus-go2rtc:1984",
        go2rtc_rtsp=dati.get("go2rtc_rtsp") or "rtsp://argus-go2rtc:8554",
        url_interno=dati.get("url_interno") or "http://argus:8700",
        stanze_studente=list(dati.get("stanze_studente") or ["camera"]),
        verifiche=int(dati.get("verifiche", 0)),
        visione=visione,
        liste_extra=dict(dati.get("liste_extra") or {}),
    )


def carica(cartella_dati: Path) -> Config:
    percorso = Path(cartella_dati) / "config.json"
    if not percorso.exists():
        percorso.parent.mkdir(parents=True, exist_ok=True)
        percorso.write_text(json.dumps(ESEMPIO, indent=2, ensure_ascii=False), encoding="utf-8")
        log.info("Creato %s di esempio: senza telecamere Argus resta inattivo.", percorso)
    dati = json.loads(percorso.read_text(encoding="utf-8"))
    return da_dict(dati)
