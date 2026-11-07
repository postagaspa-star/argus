"""API HTTP (contratto, sezione 3). Porta 8700.

Ogni richiesta del PC ha `Authorization: Bearer <token>`; gli errori sono sempre
{"errore": "frase in italiano", "codice": "slug"} e ogni risposta JSON ha `ora_server`.
"""

from __future__ import annotations

import hmac
import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import Depends, FastAPI, File, Form, Request, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse, Response
from pydantic import BaseModel, ConfigDict, Field
from starlette.exceptions import HTTPException as StarletteHTTPException

from . import VERSIONE
from .lavori import ErroreLavoro
from .servizio import EVENTI_PC, RE_SEGRETO_SBLOCCO, Servizio
from .tempo import OrologioReale, iso

log = logging.getLogger("argus.api")


class ErroreApi(Exception):
    def __init__(self, stato_http: int, codice: str, errore: str):
        self.stato_http = stato_http
        self.codice = codice
        self.errore = errore


class Campione(BaseModel):
    model_config = ConfigDict(extra="ignore")
    ts: str | None = None
    processo: str | None = Field(default=None, max_length=260)
    titolo: str | None = Field(default=None, max_length=1000)
    dominio: str | None = Field(default=None, max_length=260)
    permesso: bool | None = None
    coperto: bool = False
    inattivo_secondi: float | None = None
    audio: list[str] = Field(default_factory=list, max_length=20)
    schermo_bloccato: bool = False
    pactum_copre: bool = False


class Attivita(BaseModel):
    campioni: list[Campione] = Field(max_length=30)


class TestoComando(BaseModel):
    testo: str = Field(max_length=500)


class RegistraSblocco(BaseModel):
    segreto: str = Field(max_length=200)


class RispostaLavoro(BaseModel):
    risposte: dict[str, str]
    millisecondi: int | None = None
    modello: str | None = Field(default=None, max_length=200)


class EventoPc(BaseModel):
    tipo: str
    dettagli: dict[str, Any] = Field(default_factory=dict)
    ts: str | None = None


def crea_app(servizio: Servizio | None = None) -> FastAPI:
    """Crea l'app. Senza `servizio` lo costruisce da /data (o da ARGUS_DATI) all'avvio."""
    stato: dict[str, Servizio] = {}

    @asynccontextmanager
    async def ciclo_di_vita(app: FastAPI):
        s = servizio
        if s is None:
            dati = Path(os.environ.get("ARGUS_DATI", "/data"))
            s = Servizio(dati, OrologioReale(), crea_visione=_crea_visione_vera)
            await s.avvia()
        stato["s"] = s
        try:
            yield
        finally:
            if servizio is None:
                await s.ferma()

    app = FastAPI(title="Argus NAS", version=VERSIONE, lifespan=ciclo_di_vita, docs_url=None, redoc_url=None)

    def srv() -> Servizio:
        if "s" not in stato and servizio is not None:
            stato["s"] = servizio
        return stato["s"]

    def ora_server() -> str:
        return iso(srv().orologio.adesso())

    def json_ok(dati: dict, codice: int = 200) -> JSONResponse:
        corpo = {"ora_server": ora_server()} | dati if "ora_server" not in dati else dati
        return JSONResponse(corpo, status_code=codice)

    def errore(stato_http: int, codice: str, testo: str) -> JSONResponse:
        corpo = {"errore": testo, "codice": codice}
        try:
            corpo["ora_server"] = ora_server()
        except Exception:  # noqa: BLE001 - durante l'avvio il servizio può non esserci ancora
            pass
        return JSONResponse(corpo, status_code=stato_http)

    @app.exception_handler(ErroreApi)
    async def _errore_api(request: Request, exc: ErroreApi):
        return errore(exc.stato_http, exc.codice, exc.errore)

    @app.exception_handler(ErroreLavoro)
    async def _errore_lavoro(request: Request, exc: ErroreLavoro):
        return errore(exc.stato_http, exc.codice, exc.messaggio)

    @app.exception_handler(RequestValidationError)
    async def _errore_dati(request: Request, exc: RequestValidationError):
        return errore(422, "dati_non_validi", "I dati mandati non sono nella forma giusta.")

    @app.exception_handler(StarletteHTTPException)
    async def _errore_http(request: Request, exc: StarletteHTTPException):
        if exc.status_code == 404:
            return errore(404, "non_trovato", "Questo indirizzo non esiste.")
        if exc.status_code == 405:
            return errore(405, "metodo_sbagliato", "Questo indirizzo non accetta questo tipo di richiesta.")
        return errore(exc.status_code, "errore_http", "Richiesta non valida.")

    @app.exception_handler(Exception)
    async def _errore_interno(request: Request, exc: Exception):
        log.exception("Errore interno")
        return errore(500, "errore_interno", "Errore interno del NAS. Riprova tra poco.")

    def token(request: Request) -> None:
        intestazione = request.headers.get("authorization", "")
        if not intestazione.lower().startswith("bearer "):
            raise ErroreApi(401, "token", "Manca il token: serve Authorization: Bearer <token>.")
        dato = intestazione[7:].strip()
        if not hmac.compare_digest(dato.encode(), srv().token.encode()):
            raise ErroreApi(401, "token", "Token sbagliato.")

    # --- senza token ---

    @app.get("/api/salute")
    async def salute():
        return json_ok(srv().salute())

    @app.get("/interno/voce/{nome}")
    async def voce_interna(nome: str):
        """Per go2rtc (rete interna): il wav da mandare all'altoparlante della telecamera."""
        percorso = srv().voce.file_interno(nome)
        if percorso is None:
            raise ErroreApi(404, "non_trovato", "Questa frase non c'è.")
        return FileResponse(percorso, media_type="audio/wav")

    # --- PC ---

    @app.get("/api/pc/stato", dependencies=[Depends(token)])
    async def stato_pc():
        return json_ok(await srv().stato_pc())

    @app.get("/api/pc/liste", dependencies=[Depends(token)])
    async def liste():
        return json_ok(srv().liste_pc())

    @app.post("/api/pc/attivita", dependencies=[Depends(token)])
    async def attivita(corpo: Attivita):
        srv().ricevi_attivita([c.model_dump() for c in corpo.campioni])
        return json_ok({"ok": True})

    @app.post("/api/pc/comando", dependencies=[Depends(token)])
    async def comando(corpo: TestoComando):
        return json_ok(await srv().comando(corpo.testo))

    @app.post("/api/pc/foto", dependencies=[Depends(token)])
    async def foto(tipo: str = Form(...), nome: str | None = Form(None),
                   immagini: list[UploadFile] = File(...)):
        if len(immagini) > 20:
            raise ErroreApi(422, "troppe_foto", "Al massimo 20 foto per volta.")
        dati = []
        for f in immagini:
            contenuto = await f.read(8 * 1024 * 1024 + 1)
            if len(contenuto) > 8 * 1024 * 1024:
                raise ErroreApi(413, "foto_troppo_grande", "Una foto è più grande di 8 MB.")
            dati.append(contenuto)
        ok, risposta = await srv().foto(tipo.strip().lower(), nome, dati)
        if not ok:
            raise ErroreApi(422, "foto_non_valide", risposta)
        return json_ok({"ok": True, "risposta": risposta})

    @app.get("/api/pc/lavori", dependencies=[Depends(token)])
    async def lavori():
        lavoro = srv().prossimo_lavoro()
        if lavoro is None:
            return Response(status_code=204)
        return json_ok(lavoro)

    @app.post("/api/pc/lavori/{id_lavoro}", dependencies=[Depends(token)])
    async def risposta_lavoro(id_lavoro: str, corpo: RispostaLavoro):
        srv().rispondi_lavoro(id_lavoro, corpo.risposte, corpo.millisecondi, corpo.modello)
        return json_ok({"ok": True})

    @app.post("/api/pc/evento", dependencies=[Depends(token)])
    async def evento(request: Request, corpo: EventoPc):
        if corpo.tipo not in EVENTI_PC:
            raise ErroreApi(422, "evento_sconosciuto", "Tipo di evento sconosciuto.")
        if corpo.tipo == "sblocco_emergenza":
            # Vale solo con il secondo segreto (contratto, sezione 1): l'agente dello studente non lo ha.
            # Senza segreto registrato nessuno sblocco è possibile.
            atteso = srv().segreto_sblocco()
            dato = request.headers.get("x-argus-sblocco", "")
            if atteso is None or not dato or not hmac.compare_digest(dato.encode(), atteso.encode()):
                raise ErroreApi(403, "sblocco", "Lo sblocco d'emergenza vuole il segreto dello sblocco.")
            ore = corpo.dettagli.get("ore")
            if isinstance(ore, bool) or not isinstance(ore, int) or not 0 <= ore <= 48:
                raise ErroreApi(422, "ore_non_valide", "Le ore dello sblocco devono essere un numero intero da 0 a 48.")
        await srv().evento_pc(corpo.tipo, corpo.dettagli, corpo.ts)
        return json_ok({"ok": True})

    @app.post("/api/pc/registra-sblocco", dependencies=[Depends(token)])
    async def registra_sblocco(corpo: RegistraSblocco):
        """L'installatore del PC registra il secondo segreto, una volta sola (contratto, sezione 1)."""
        if not RE_SEGRETO_SBLOCCO.fullmatch(corpo.segreto):
            raise ErroreApi(422, "segreto_non_valido", "Il segreto deve essere di 64 caratteri esadecimali.")
        if not srv().registra_sblocco(corpo.segreto):
            raise ErroreApi(409, "sblocco_gia_registrato", "Sul NAS c'è già un segreto di sblocco: va azzerato "
                                                           "a mano da chi gestisce il NAS.")
        return json_ok({"ok": True})

    @app.get("/api/pc/voce/{nome}", dependencies=[Depends(token)])
    async def voce_pc(nome: str):
        id_voce = nome[:-4] if nome.endswith(".wav") else nome
        percorso = srv().voce.file_per_pc(id_voce)
        if percorso is None or not percorso.exists():
            raise ErroreApi(404, "non_trovato", "Questa frase non c'è più.")
        return FileResponse(percorso, media_type="audio/wav")

    return app


def _crea_visione_vera(servizio: Servizio):
    # Import pigro: OpenCV, ONNX Runtime e MediaPipe si caricano solo se ci sono telecamere.
    from .visione.pipeline import Pipeline

    return Pipeline(servizio.config, servizio.dati, servizio.db, servizio.lavori, servizio.orologio)
