"""API del contratto e servizio, con orologio finto, visione a copione e servizi finti."""

from __future__ import annotations

import asyncio
import base64
import hashlib
from datetime import date, timedelta

import cv2
import httpx
import numpy as np
import pytest

from argus.api import crea_app
from argus.config import Config
from argus.servizio import Servizio
from argus.tempo import OrologioFinto
from finti import Rete, VisioneFinta, config_con_telecamera, risposta_semif
from simulatore import hm

STUDIO = dict(visto=True, stanza="camera", dove="scrivania", posa="seduto", in_mano=["libro_scuola"])
ARRIVO = dict(visto=True, stanza="camera", dove="in_piedi", posa="in_piedi")
TELEFONO = dict(visto=True, stanza="camera", dove="divano", posa="seduto", in_mano=["telefono_suo"])


def jpeg(colore: int = 128) -> bytes:
    img = np.full((64, 64, 3), colore, dtype=np.uint8)
    ok, dati = cv2.imencode(".jpg", img)
    return dati.tobytes()


class Banco:
    def __init__(self, cartella, config: Config | None = None, ora=None, visione=None):
        self.rete = Rete()
        self.orologio = OrologioFinto(ora or hm("12:00"))
        config = config if config is not None else Config()
        self.visione = visione if visione is not None else (VisioneFinta() if config.telecamere else None)
        self.s = Servizio(cartella, self.orologio, config=config, client=self.rete.client(), visione=self.visione,
                          attesa_decisore=0)
        self.app = crea_app(self.s)
        self.http = httpx.AsyncClient(transport=httpx.ASGITransport(app=self.app), base_url="http://nas")
        self.h = {"Authorization": f"Bearer {self.s.token}"}

    async def __aenter__(self):
        await self.s.avvia(cicli=False)
        return self

    async def __aexit__(self, *exc):
        await self.s.attendi_compiti()
        await self.http.aclose()
        await self.s.ferma()

    async def minuti(self, da: str, a: str, giorno: date | None = None, **campi) -> None:
        t = hm(da, giorno) if giorno else hm(da)
        fine = hm(a, giorno) if giorno else hm(a)
        while t < fine:
            self.visione.copione[t] = dict(campi)
            self.orologio.imposta(t + timedelta(minutes=1, seconds=2))
            await self.s.passo_minuto(t)
            t += timedelta(minutes=1)
        await self.s.attendi_compiti()

    async def get(self, url: str, **kw):
        return await self.http.get(url, headers=self.h, **kw)

    async def post(self, url: str, **kw):
        return await self.http.post(url, headers=self.h, **kw)


def esegui(coro):
    return asyncio.run(coro)


# --- autenticazione e forma delle risposte -------------------------------------------------------

def test_salute_senza_token_e_token_obbligatorio(tmp_path):
    async def prova():
        async with Banco(tmp_path) as b:
            r = await b.http.get("/api/salute")
            assert r.status_code == 200
            d = r.json()
            assert d["ok"] is True and d["versione"] == "1.0.0" and d["telecamere"] == {}
            assert d["decisore"] in ("ok", "assente") and d["voci"] in ("ok", "assente")
            assert "ora_server" in d
            r = await b.http.get("/api/pc/stato")
            assert r.status_code == 401
            assert r.json()["codice"] == "token" and r.json()["errore"]
            r = await b.http.get("/api/pc/stato", headers={"Authorization": "Bearer sbagliato"})
            assert r.status_code == 401 and r.json()["codice"] == "token"
            r = await b.get("/api/nessuno")
            assert r.status_code == 404 and r.json()["codice"] == "non_trovato"
    esegui(prova())


def test_token_generato_al_primo_avvio_e_stabile(tmp_path):
    async def prova():
        async with Banco(tmp_path) as b:
            token = b.s.token
        assert len(token) == 64 and int(token, 16) >= 0
        assert (tmp_path / "token-pc.txt").read_text().strip() == token
        async with Banco(tmp_path) as b2:
            assert b2.s.token == token
    esegui(prova())


def test_senza_telecamere_inattivo(tmp_path):
    async def prova():
        async with Banco(tmp_path) as b:
            r = await b.get("/api/pc/stato")
            d = r.json()
            assert d["modalita"] == "inattivo"
            assert d["classe_adesso"] == "nessuna"
            assert d["messaggio_copertura"] is None
            assert d["liste_versione"] == 1
            assert d["ora_server"].endswith("+01:00")
            r = await b.post("/api/pc/comando", json={"testo": "ps m: bagno & t: 10"})
            assert r.json()["risposta"] == "Argus adesso è spento: non serve."
            assert b.s.visione is None
    esegui(prova())


def test_dati_non_validi_422(tmp_path):
    async def prova():
        async with Banco(tmp_path) as b:
            r = await b.post("/api/pc/attivita", json={"campioni": [{}] * 31})
            assert r.status_code == 422 and r.json()["codice"] == "dati_non_validi"
            r = await b.post("/api/pc/evento", json={"tipo": "boh"})
            assert r.status_code == 422 and r.json()["codice"] == "evento_sconosciuto"
    esegui(prova())


# --- un pomeriggio attraverso il servizio ----------------------------------------------------------

def test_pomeriggio_completo_via_api(tmp_path):
    async def prova():
        async with Banco(tmp_path, config_con_telecamera()) as b:
            await b.minuti("07:00", "07:01", **ARRIVO)
            await b.minuti("13:30", "13:31", **ARRIVO)
            r = (await b.get("/api/pc/stato")).json()
            assert r["modalita"] == "studio"
            assert r["messaggio_copertura"] == "Adesso è tempo di studio. Mancano 60 minuti."
            # campioni del PC: wikipedia in primo piano
            campione = {"ts": "x", "processo": "chrome.exe", "titolo": "Rivoluzione francese - Wikipedia",
                        "dominio": "it.wikipedia.org", "permesso": True, "coperto": False, "inattivo_secondi": 3,
                        "audio": [], "schermo_bloccato": False, "pactum_copre": False}
            b.orologio.imposta(hm("14:00:30"))
            assert (await b.post("/api/pc/attivita", json={"campioni": [campione] * 5})).json()["ok"] is True
            await b.minuti("14:00", "14:01", visto=True, stanza="camera", dove="scrivania", posa="seduto")
            assert b.s.motore.giorno.studio == 1
            await b.minuti("14:01", "14:20", **STUDIO)
            r = (await b.post("/api/pc/comando", json={"testo": "ps m: bagno & t: 10"})).json()
            assert r == {"ora_server": r["ora_server"], "ok": True, "risposta": "Pausa fino alle 14:31.",
                         "chiede_foto": None}
            r = (await b.get("/api/pc/stato")).json()
            assert r["comando_attivo"] == {"tipo": "ps", "fino": "14:31"}
            assert r["quota"]["fatti"] == 20 and r["quota"]["pausa_disponibile"] == 10
            await b.minuti("14:20", "14:31", visto=False)
            await b.minuti("14:31", "15:12", **STUDIO)
            r = (await b.get("/api/pc/stato")).json()
            assert r["modalita"] == "libero" and r["quota_fatta_oggi"] is True
            # la voce "Fatto per oggi" è andata all'altoparlante della telecamera via go2rtc
            assert ("Fatto per oggi. Sei libero.", "camera", "telecamera") in b.s.voci_dette
            richiesta = b.rete.a("argus-go2rtc")[-1]
            assert richiesta.url.path == "/api/streams"
            assert richiesta.url.params["dst"] == "camera_voce"
            src = richiesta.url.params["src"]
            assert src.startswith("ffmpeg:http://argus:8700/interno/voce/") and src.endswith("#audio=pcma#input=file")
            nome_wav = src.split("/interno/voce/")[1].split("#")[0]
            r = await b.http.get(f"/interno/voce/{nome_wav}")
            assert r.status_code == 200 and r.content[:4] == b"RIFF"
            # database
            assert b.s.db.giorno("2026-11-09")["fatta_alle"] is not None
            assert b.s.db.registro("quota_fatta")
    esegui(prova())


def test_voce_ripiega_sul_pc_se_go2rtc_non_va(tmp_path):
    async def prova():
        async with Banco(tmp_path, config_con_telecamera()) as b:
            b.rete.go2rtc_ok = False
            await b.minuti("13:30", "13:31", **ARRIVO)
            await b.minuti("14:00", "14:02", **TELEFONO)
            r = (await b.get("/api/pc/stato")).json()
            assert "di_voce" in r
            url = r["di_voce"]["url"]
            assert url == f"/api/pc/voce/{r['di_voce']['id']}.wav"
            wav = await b.get(url)
            assert wav.status_code == 200 and wav.content[:4] == b"RIFF"
            assert (await b.http.get(url)).status_code == 401
            b.orologio.avanza(minutes=3)
            assert "di_voce" not in (await b.get("/api/pc/stato")).json()
    esegui(prova())


def test_presa_spenta_per_la_tv(tmp_path):
    async def prova():
        async with Banco(tmp_path, config_con_telecamera(prese=True)) as b:
            await b.minuti("13:30", "13:31", **ARRIVO)
            await b.minuti("14:00", "14:02", visto=True, stanza="camera", dove="divano", posa="seduto",
                           schermi=["tv"])
            ha = b.rete.a("ha")
            assert len(ha) == 1
            assert ha[0].url.path == "/api/services/switch/turn_off"
            assert ha[0].headers["authorization"] == "Bearer token-ha"
            assert b"switch.tv" in ha[0].content
    esegui(prova())


def test_titolo_youtube_giudicato_da_semif(tmp_path):
    async def prova():
        async with Banco(tmp_path, config_con_telecamera()) as b:
            await b.minuti("13:30", "13:31", **ARRIVO)
            campione = {"processo": "msedge.exe", "titolo": "Gattini buffi compilation - YouTube",
                        "dominio": "youtube.com", "inattivo_secondi": 2, "audio": ["msedge.exe"]}
            b.orologio.imposta(hm("14:00:10"))
            await b.post("/api/pc/attivita", json={"campioni": [campione]})
            b.rete.risposte_semif = [risposta_semif("titolo", "svago")]
            assert await b.s.svuota_decisioni() == 1
            corpo = b.rete.corpi_semif()[0]
            assert corpo["domande"][0]["id"] == "titolo"
            assert [o["id"] for o in corpo["domande"][0]["opzioni"]] == ["studio", "lavoro", "svago", "non_si_capisce"]
            assert "Gattini buffi" in corpo["stato"]
            chiave = hashlib.sha1("youtube.com|Gattini buffi compilation - YouTube".encode()).hexdigest()
            r = (await b.get("/api/pc/stato")).json()
            assert r["verdetti"][chiave] == "svago"
            # lo stesso titolo non si richiede
            await b.post("/api/pc/attivita", json={"campioni": [campione]})
            assert await b.s.svuota_decisioni() == 0
            # il minuto con lo svago sul PC conta come distrazione (dopo il primo)
            for minuto in ("14:00", "14:01", "14:02"):
                b.orologio.imposta(hm(minuto) + timedelta(seconds=30))
                await b.post("/api/pc/attivita", json={"campioni": [campione] * 5})
                await b.minuti(minuto, (hm(minuto) + timedelta(minutes=1)).strftime("%H:%M"),
                               visto=True, stanza="camera", dove="scrivania", posa="seduto")
            assert b.s.motore.giorno.agg_distrazione == 2
    esegui(prova())


def test_chiave_del_verdetto_come_la_calcola_il_pc():
    """sha1(dominio + "|" + titolo) sui valori esatti del campione: niente minuscole, niente "www."."""
    from argus.liste import LISTE_PARTENZA
    from argus.pc_attivita import categoria, chiave_verdetto, da_giudicare

    attese = hashlib.sha1("YouTube.com|Ripasso Storia".encode("utf-8")).hexdigest()
    assert chiave_verdetto("YouTube.com", "Ripasso Storia") == attese
    assert chiave_verdetto("youtube.com", "Ripasso Storia") != attese
    liste = dict(LISTE_PARTENZA)
    campione = {"processo": "msedge.exe", "titolo": "Ripasso Storia", "dominio": "YouTube.com", "inattivo_secondi": 1}
    assert da_giudicare([campione], liste, {}) == [("YouTube.com", "Ripasso Storia")]
    assert categoria(campione, liste, {attese: "studio"}) == "studio"
    assert da_giudicare([campione], liste, {attese: "studio"}) == []


def test_semif_sotto_soglia_vale_non_si_capisce_e_503_riprova(tmp_path):
    async def prova():
        async with Banco(tmp_path, config_con_telecamera()) as b:
            await b.minuti("13:30", "13:31", **ARRIVO)  # i titoli si giudicano solo durante la quota
            campione = {"processo": "chrome.exe", "titolo": "Lezione di fisica", "dominio": "youtube.com",
                        "inattivo_secondi": 1}
            await b.post("/api/pc/attivita", json={"campioni": [campione]})
            b.rete.risposte_semif = [503, 503, risposta_semif("titolo", "studio", probabilita=0.55)]
            await b.s.svuota_decisioni()
            assert len(b.rete.a("sol-decisore")) == 3
            assert list(b.s.verdetti.values()) == ["non_si_capisce"]
    esegui(prova())


def test_pensiero_giudicato_da_semif_col_diario(tmp_path):
    async def prova():
        async with Banco(tmp_path, config_con_telecamera()) as b:
            await b.minuti("13:30", "13:31", **ARRIVO)
            b.visione.di_base = STUDIO
            await b.minuti("14:00", "14:10", **STUDIO)
            for minuto in range(10, 16):
                b.orologio.imposta(hm(f"14:{minuto:02d}:20"))
                b.s.scrivi_diario()
            await b.minuti("14:10", "14:16", visto=True, stanza="camera", dove="scrivania", posa="seduto",
                           pensiero=True)
            await b.minuti("14:16", "14:22", **STUDIO)
            b.rete.risposte_semif = [risposta_semif("pensiero", "studio")]
            await b.s.svuota_decisioni()
            corpo = b.rete.corpi_semif()[0]
            assert corpo["domande"][0]["id"] == "pensiero"
            assert "Diario di prima" in corpo["stato"] and "Diario di dopo" in corpo["stato"]
            assert corpo["scadenza_secondi"] == 120
            assert b.s.motore.giorno.studio == 16 + 6
    esegui(prova())


def test_pausa_falsa_via_semif(tmp_path):
    async def prova():
        async with Banco(tmp_path, config_con_telecamera()) as b:
            await b.minuti("13:30", "13:31", **ARRIVO)
            b.orologio.imposta(hm("14:00"))
            await b.post("/api/pc/comando", json={"testo": "ps m: bagno & t: 10"})
            await b.minuti("14:00", "14:03", **TELEFONO)
            b.rete.risposte_semif = [risposta_semif("pausa", "non_torna")]
            await b.s.svuota_decisioni()
            await b.s.attendi_compiti()
            assert b.s.motore.giorno.agg_imbroglio == 30
            assert "«bagno»" in b.rete.corpi_semif()[0]["domande"][0]["domanda"]
    esegui(prova())


# --- comandi, foto, liste --------------------------------------------------------------------------

def test_comandi_lb_ag_aiuto(tmp_path):
    async def prova():
        async with Banco(tmp_path, config_con_telecamera()) as b:
            r = (await b.post("/api/pc/comando", json={"testo": "lb storia"})).json()
            assert r["ok"] and r["chiede_foto"] == {"tipo": "lb", "nome": "storia", "scatti": 6,
                                                    "consiglio": "Copertina e 2-3 pagine aperte."}
            r = (await b.post("/api/pc/comando", json={"testo": "vs"})).json()
            assert r["chiede_foto"]["scatti"] == 10 and r["chiede_foto"]["nome"] is None
            r = (await b.post("/api/pc/comando", json={"testo": "aiuto"})).json()
            assert len(r["risposta"].splitlines()) == 11
            r = (await b.post("/api/pc/comando", json={"testo": "ag studio onenote.exe"})).json()
            assert r["ok"] and "sarà nella lista studio dal 13/11" in r["risposta"]
            r = (await b.post("/api/pc/comando", json={"testo": "tg lavoro github.com"})).json()
            assert r["risposta"] == "github.com tolto dalla lista lavoro."
            liste = (await b.get("/api/pc/liste")).json()
            assert "github.com" not in liste["lavoro"]["siti"]
            assert liste["versione"] == 2
            assert (await b.get("/api/pc/stato")).json()["liste_versione"] == 2
            r = (await b.post("/api/pc/comando", json={"testo": "boh"})).json()
            assert r["ok"] is False and r["risposta"] == "Non ho capito. Scrivi aiuto per vedere i comandi."
            r = (await b.post("/api/pc/comando", json={"testo": "ps bagno"})).json()
            assert r["ok"] is False and r["risposta"] == "Non ho capito. Scrivi così: ps m: bagno & t: 10"
        # le modifiche alle liste restano dopo un riavvio
        async with Banco(tmp_path, config_con_telecamera()) as b2:
            assert "github.com" not in (await b2.get("/api/pc/liste")).json()["lavoro"]["siti"]
    esegui(prova())


def test_foto_registrazione_elenco_e_togli(tmp_path):
    async def prova():
        async with Banco(tmp_path, config_con_telecamera()) as b:
            file = [("immagini", (f"f{i}.jpg", jpeg(i * 20), "image/jpeg")) for i in range(3)]
            r = await b.post("/api/pc/foto", data={"tipo": "lb", "nome": "Storia"}, files=file)
            assert r.status_code == 200, r.text
            assert r.json() == {"ora_server": r.json()["ora_server"], "ok": True, "risposta": "«Storia» salvato (3 foto)."}
            assert len(list((tmp_path / "registrati" / "lb" / "storia").iterdir())) == 3
            assert len(b.s.db.vettori("lb")) == 3
            r = (await b.post("/api/pc/comando", json={"testo": "lb"})).json()
            assert r["risposta"] == "Libri registrati: Storia."
            r = (await b.post("/api/pc/comando", json={"testo": "lb via storia"})).json()
            assert r["risposta"] == "«storia» tolto."
            assert not (tmp_path / "registrati" / "lb" / "storia").exists()
            r = (await b.post("/api/pc/comando", json={"testo": "lb"})).json()
            assert r["risposta"] == "Nessun libro registrato."
            r = (await b.post("/api/pc/comando", json={"testo": "lb via storia"})).json()
            assert r["risposta"] == "«storia» non c'è."
            # file che non è un'immagine
            r = await b.post("/api/pc/foto", data={"tipo": "tf"},
                             files=[("immagini", ("x.txt", b"ciao", "text/plain"))])
            assert r.status_code == 422 and r.json()["codice"] == "foto_non_valide"
            r = await b.post("/api/pc/foto", data={"tipo": "vs"},
                             files=[("immagini", (f"v{i}.jpg", jpeg(), "image/jpeg")) for i in range(4)])
            assert r.json()["risposta"] == "Viso salvato (4 foto)."
    esegui(prova())


# --- foto dubbie -----------------------------------------------------------------------------------

def test_lavori_coda_presa_risposta_e_cancellazione(tmp_path):
    async def prova():
        async with Banco(tmp_path, config_con_telecamera(), ora=hm("15:40")) as b:
            assert (await b.get("/api/pc/lavori")).status_code == 204
            ricevuti = []
            b.s.lavori.quando_giudicato(ricevuti.append)
            id_lavoro = b.s.lavori.aggiungi("oggetto_in_mano", jpeg(), "Camera, sul divano, 15:41.",
                                            {"traccia": 3}, hm("15:41"))
            r = await b.get("/api/pc/lavori")
            d = r.json()
            assert d["id"] == id_lavoro
            assert base64.b64decode(d["immagine_jpeg_base64"])[:3] == b"\xff\xd8\xff"
            assert d["contesto"] == "Camera, sul divano, 15:41."
            assert [q["id"] for q in d["domande"]] == ["in_mano", "schermo_acceso"]
            assert d["domande"][0]["opzioni"] == ["telefono", "tablet", "libro", "quaderno", "controller", "niente",
                                                  "non_si_capisce"]
            assert d["scade"] == "2026-11-09T23:59:59+01:00"
            # preso: non lo si dà a nessun altro per 3 minuti
            assert (await b.get("/api/pc/lavori")).status_code == 204
            b.orologio.avanza(minutes=3)
            assert (await b.get("/api/pc/lavori")).json()["id"] == id_lavoro
            r = await b.post(f"/api/pc/lavori/{id_lavoro}",
                             json={"risposte": {"in_mano": "astronave", "schermo_acceso": "si"}})
            assert r.status_code == 422 and r.json()["codice"] == "opzione_non_valida"
            r = await b.post(f"/api/pc/lavori/{id_lavoro}",
                             json={"risposte": {"in_mano": "telefono", "schermo_acceso": "si"},
                                   "millisecondi": 41200, "modello": "Qwen3.5-9B-Q4_K_M"})
            assert r.status_code == 200 and r.json()["ok"] is True
            assert ricevuti and ricevuti[0]["risposte"] == {"in_mano": "telefono", "schermo_acceso": "si"}
            assert ricevuti[0]["origine"] == {"traccia": 3}
            assert not list((tmp_path / "lavori").glob("*.jpg"))
            assert (await b.get("/api/pc/lavori")).status_code == 204
            r = await b.post(f"/api/pc/lavori/{id_lavoro}", json={"risposte": {}})
            assert r.status_code == 409
            r = await b.post("/api/pc/lavori/l-nessuno", json={"risposte": {}})
            assert r.status_code == 404
    esegui(prova())


def test_lavori_cancellati_a_mezzanotte(tmp_path):
    async def prova():
        async with Banco(tmp_path, config_con_telecamera(), ora=hm("23:50")) as b:
            b.s.lavori.aggiungi("lettura", jpeg(), "Camera, 23:50.", {}, hm("23:50"))
            assert len(list((tmp_path / "lavori").glob("*.jpg"))) == 1
            b.orologio.imposta(hm("00:00:30", date(2026, 11, 10)))
            await b.s.passo_minuto(hm("00:00", date(2026, 11, 10)))
            assert not list((tmp_path / "lavori").glob("*.jpg"))
            assert (await b.get("/api/pc/lavori")).status_code == 204
    esegui(prova())


# --- eventi del PC -----------------------------------------------------------------------------------

def test_sblocco_di_emergenza(tmp_path):
    async def prova():
        async with Banco(tmp_path, config_con_telecamera()) as b:
            await b.minuti("13:30", "13:31", **ARRIVO)
            b.orologio.imposta(hm("14:00"))
            segreto = "ab" * 32
            assert (await b.post("/api/pc/registra-sblocco", json={"segreto": segreto})).status_code == 200
            r = await b.http.post("/api/pc/evento", headers=b.h | {"X-Argus-Sblocco": segreto},
                                  json={"tipo": "sblocco_emergenza", "dettagli": {"ore": 2},
                                        "ts": "2026-11-09T14:00:03+01:00"})
            assert r.json()["ok"] is True
            d = (await b.get("/api/pc/stato")).json()
            assert d["modalita"] == "libero"
            assert d["sblocco_fino"] == "2026-11-09T16:00:00+01:00"
            assert b.s.db.registro("pc_sblocco_emergenza")
            b.orologio.imposta(hm("16:00:01"))
            d = (await b.get("/api/pc/stato")).json()
            assert d["modalita"] == "studio" and d["sblocco_fino"] is None
            r = await b.post("/api/pc/evento", json={"tipo": "agente_riaperto", "dettagli": {}})
            assert r.json()["ok"] is True
    esegui(prova())


def test_stato_salvato_e_ripreso_dopo_un_riavvio(tmp_path):
    async def prova():
        async with Banco(tmp_path, config_con_telecamera()) as b:
            await b.minuti("13:30", "13:31", **ARRIVO)
            await b.minuti("14:00", "14:25", **STUDIO)
        async with Banco(tmp_path, config_con_telecamera(), ora=hm("14:26")) as b2:
            d = (await b2.get("/api/pc/stato")).json()
            assert d["quota"]["fatti"] == 25 and d["modalita"] == "studio"
            assert len(b2.s.db.minuti("2026-11-09")) == 26  # anche il minuto dell'arrivo
    esegui(prova())


@pytest.mark.parametrize("scelta,prob,massa,atteso", [
    ("studio", 0.6, 0.5, "studio"), ("studio", 0.59, 0.9, "non_si_capisce"),
    ("studio", 0.9, 0.49, "non_si_capisce"), ("inventata", 0.9, 0.9, "non_si_capisce"),
])
def test_soglie_semif(scelta, prob, massa, atteso):
    from argus.semif import accetta
    assert accetta({"scelta": scelta, "probabilita": {scelta: prob}, "massa_opzioni": massa},
                   {"studio", "non_studio", "non_si_capisce"}) == atteso
    assert accetta(None, {"studio"}) == "non_si_capisce"


def test_semif_limiti_domande():
    from argus.semif import Decisore, Domanda

    async def prova():
        d = Decisore("http://sol-decisore:8300", httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(200))))
        with pytest.raises(ValueError):
            await d.decidi("x", [Domanda(str(i), "?", [("a", "a"), ("b", "b")]) for i in range(9)])
        with pytest.raises(ValueError):
            await d.decidi("x", [Domanda("q", "?", [(str(i), "x") for i in range(17)])])
    esegui(prova())
