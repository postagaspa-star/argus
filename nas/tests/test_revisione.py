"""Correzioni chieste dalla revisione indipendente (07/11): una prova per ogni punto.

A1 dm che si chiude da solo, A2 verdetti oltre 300, B1 ps che cancellava la pausa, B2 telecamere giù,
B3 dm sforato, B4 audio solo Lectio, B5 programmi di Argus per nome esatto, B7 sblocco col secondo
segreto, più le regole nuove (PC in uso, pausa, fine dell'episodio, titoli, non_si_capisce, foto,
liste_extra, decisione senza il PC).
"""

from __future__ import annotations

from datetime import timedelta
from types import SimpleNamespace

import numpy as np

from argus.config import Config, ConfigVisione, Telecamera, da_dict
from argus.db import Database
from argus.liste import LISTE_PARTENZA, Liste, programma_in
from argus.motore import Classe, PcMinuto
from argus.pc_attivita import chiave_verdetto, riassumi
from argus.visione.aggregatore import Aggregatore, Osservazione, riassumi_minuto
from argus.visione.analizzatore import Analizzatore, Traccia
from argus.visione.geometria import Box
from argus.visione.ragionamento import OggettoPersona
from argus.visione.rilevatore import Rilevamento
from finti import VisioneFinta, config_con_telecamera, risposta_semif
from simulatore import FERMO, FUORI, MANGIA, SDRAIATO, STUDIA_LIBRO, TELEFONO, Sim, hm
from test_api_servizio import ARRIVO, Banco, esegui, jpeg


def _pronto(s: Sim) -> None:
    s.arriva("13:30")
    s.tratto("13:31", "14:00", **MANGIA)


def _pc(quando: str | None, categoria: str = "sempre") -> PcMinuto:
    return PcMinuto(categoria, True, ultimo_input=hm(quando) if quando else None)


# --- A1: il dm scritto al PC non si chiude da solo ---------------------------------------------------

def test_a1_dm_scritto_al_pc_non_si_chiude_da_solo():
    s = Sim()
    _pronto(s)
    s.tratto("14:00", "14:30", **STUDIA_LIBRO)
    assert s.cmd("dm45", "14:30:20").ok
    # Il comando si scrive al PC: l'ultimo tasto è alle 14:30:20 e il PC resta "in uso" per 5 minuti.
    s.minuto("14:30", **SDRAIATO, pc=_pc("14:30:20"))
    s.minuto("14:31", **SDRAIATO, pc=_pc("14:30:20"))
    assert s.m.giorno.dm is not None and s.m.giorno.dm.stato == "valido"
    # Poi dorme girato verso il muro: la visione vede solo una persona sdraiata che non riconosce.
    s.tratto("14:32", "14:42", visto=False, forse_visto=True)
    assert s.m.giorno.dm is not None
    assert s.m.aggiunte() == 0
    assert s.conta(Classe.DISTRAZIONE) == 0
    # Un tasto dopo la conferma, nell'ultimo minuto: si è alzato.
    s.minuto("14:42", visto=False, pc=_pc("14:42:30"))
    assert s.m.giorno.dm is None
    assert s.classe("14:42") == Classe.NEUTRO


def test_a1_ultimo_input_dai_campioni_del_pc():
    liste = Liste().attive(hm("14:00"))
    t0 = hm("14:00:00")
    campioni = [{"processo": "explorer.exe", "inattivo_secondi": 3}, {"processo": "explorer.exe", "inattivo_secondi": 4}]
    ore = [t0 + timedelta(seconds=10), t0 + timedelta(seconds=11)]
    pc = riassumi(campioni, liste, {}, ore=ore)
    assert pc.ultimo_input == t0 + timedelta(seconds=7)
    bloccato = [{"processo": "lockapp.exe", "inattivo_secondi": 0, "schermo_bloccato": True}]
    assert riassumi(bloccato, liste, {}, ore=[t0]).ultimo_input is None


# --- A2: i verdetti dei titoli visti adesso arrivano sempre al PC ------------------------------------

def test_a2_verdetti_visti_negli_ultimi_10_minuti_anche_oltre_300(tmp_path):
    db = Database(tmp_path / "argus.db")
    for i in range(310):
        db.salva_verdetto(chiave_verdetto("youtube.com", f"Video {i}"), "youtube.com", f"Video {i}", "studio",
                          hm("10:00") + timedelta(seconds=i))
    db.chiudi()

    async def prova():
        async with Banco(tmp_path, config_con_telecamera()) as b:
            await b.minuti("13:30", "13:31", **ARRIVO)
            vecchio = {"processo": "msedge.exe", "titolo": "Video 0", "dominio": "youtube.com", "inattivo_secondi": 1}
            b.orologio.imposta(hm("14:00"))
            await b.post("/api/pc/attivita", json={"campioni": [vecchio]})
            verdetti = (await b.get("/api/pc/stato")).json()["verdetti"]
            assert verdetti[chiave_verdetto("youtube.com", "Video 0")] == "studio"
            assert chiave_verdetto("youtube.com", "Video 309") in verdetti  # i più recenti restano
            # dopo 10 minuti senza vederlo, il verdetto vecchio torna fuori dai 300
            b.orologio.imposta(hm("14:11"))
            verdetti = (await b.get("/api/pc/stato")).json()["verdetti"]
            assert chiave_verdetto("youtube.com", "Video 0") not in verdetti
            assert len(verdetti) == 300
    esegui(prova())


# --- B1: una ps rifiutata non cancella la pausa in corso -----------------------------------------------

def test_b1_ps_rifiutata_lascia_la_pausa_in_corso():
    s = Sim()
    _pronto(s)
    assert s.cmd("ps m: bagno & t: 10", "14:00:10").risposta == "Pausa fino alle 14:11."
    s.tratto("14:00", "14:02", **FUORI)
    r = s.cmd("ps m: bagno & t: 15", "14:02:30")
    assert r.risposta == "Ti restano 7 minuti di pausa: resta quella fino alle 14:11."
    assert s.m.comando_attivo(hm("14:02:40")) == {"tipo": "ps", "fino": "14:11"}
    s.tratto("14:02", "14:11", **FUORI)
    assert s.conta(Classe.NEUTRO, "14:00", "14:11") == 11
    assert s.m.giorno.agg_distrazione == 0


def test_b1_ps_nuova_conta_i_minuti_non_usati_della_pausa_in_corso():
    s = Sim()
    _pronto(s)
    s.cmd("ps m: bagno & t: 10", "14:00:10")
    s.tratto("14:00", "14:02", **FUORI)
    r = s.cmd("ps m: acqua & t: 7", "14:02:30")
    assert r.risposta == "Pausa fino alle 14:10."
    assert s.m.giorno.pausa_usata == 10  # 3 usati della prima + 7 della nuova
    assert s.m.giorno.pausa.motivo == "acqua"


# --- B2: telecamere giù = niente punizione -------------------------------------------------------------

def test_b2_telecamere_giu_neutro_e_conteggio_fermo():
    s = Sim()
    _pronto(s)
    s.tratto("14:00", "14:10", **STUDIA_LIBRO)
    s.tratto("14:10", "14:12", **FUORI)  # 2 minuti fuori vista
    s.tratto("14:12", "14:22", visto=False, telecamere_ok=False)
    assert s.conta(Classe.NEUTRO, "14:12", "14:22") == 10
    assert s.m.giorno.fuori_vista == 2
    # tutte accese tranne quella della stanza dove era visto per ultimo
    s.tratto("14:22", "14:32", visto=False, stanze_cieche=frozenset({"camera"}))
    assert s.m.giorno.fuori_vista == 2 and s.m.aggiunte() == 0
    # tornano: il conteggio riparte da dove era (3, 4, 5 neutri, poi distrazione)
    s.tratto("14:32", "14:37", **FUORI)
    assert s.m.giorno.agg_distrazione == 2


def test_b2_aggregatore_stanza_cieca_e_visione_ferma():
    inizio = hm("15:00")
    stanze = {"camera": "camera", "salotto": "salotto e cucina"}

    def oss(tel, secondi, ok=True):
        return [Osservazione(ora=inizio + timedelta(seconds=x), telecamera=tel, stanza=stanze[tel], ok=ok)
                for x in secondi]

    # la camera manda immagini solo nei primi 20 secondi: visione ferma da più di 30 secondi
    r = riassumi_minuto(oss("camera", range(0, 20, 2)) + oss("salotto", range(0, 60, 2)), inizio, stanze)
    assert r["stanze_cieche"] == frozenset({"camera"}) and r["telecamere_ok"] is True
    # immagini che arrivano ma rotte (ok=False): cieca
    r = riassumi_minuto(oss("camera", range(0, 60, 2), ok=False) + oss("salotto", range(0, 60, 2)), inizio, stanze)
    assert r["stanze_cieche"] == frozenset({"camera"})
    # niente immagini da nessuna: tutto giù
    r = riassumi_minuto([], inizio, stanze)
    assert r["telecamere_ok"] is False and r["stanze_cieche"] == frozenset(stanze.values())
    # tutto bene
    r = riassumi_minuto(oss("camera", range(0, 60, 2)) + oss("salotto", range(0, 60, 2)), inizio, stanze)
    assert r["stanze_cieche"] == frozenset() and r["telecamere_ok"] is True
    a = Aggregatore(stanze=stanze)
    for o in oss("salotto", range(0, 60, 2)):
        a.aggiungi(o)
    assert a.minuto(inizio)["stanze_cieche"] == frozenset({"camera"})


# --- B3: il dm sforato non punisce -------------------------------------------------------------------

def test_b3_dopo_lo_scadere_del_dm_resta_lui_finche_non_si_alza():
    s = Sim()
    _pronto(s)
    assert s.cmd("dm20", "14:00:05").risposta.startswith("Dormi pure fino alle 14:21.")
    s.tratto("14:00", "14:21", **SDRAIATO)
    # scaduto, ma dorme girato verso il muro
    s.tratto("14:21", "14:31", visto=False, forse_visto=True)
    assert s.m.aggiunte() == 0 and s.conta(Classe.DISTRAZIONE) == 0
    contesto = s.m.contesto_visione(hm("14:31:10"))
    assert contesto["dm"] == "valido" and contesto["dm_dove"] == "letto"
    assert s.m.comando_attivo(hm("14:31:10")) is None
    s.tratto("14:31", "14:40", **SDRAIATO)
    assert s.m.giorno.dm is not None
    s.minuto("14:40", **FERMO)  # si alza
    assert s.m.giorno.dm is None
    s.tratto("14:41", "14:48", **FUORI)  # da qui la regola normale
    assert s.m.giorno.agg_distrazione == 2


def test_b3_la_visione_tiene_la_persona_sdraiata_solo_nello_stesso_posto():
    a = Analizzatore.__new__(Analizzatore)
    tel = Telecamera(id="camera", stanza="camera")
    letto = Rilevamento("bed", 0.9, Box(0, 100, 300, 300))
    divano = Rilevamento("couch", 0.9, Box(400, 100, 640, 300))
    sul_letto = Traccia(1, Box(20, 150, 280, 260), 0.0, posa="sdraiato")
    sul_divano = Traccia(2, Box(420, 150, 620, 260), 0.0, posa="sdraiato")
    contesto = {"dm": "valido", "dm_stanza": "camera", "dm_dove": "letto"}
    assert a._scegli_studente([sul_divano], contesto, tel, [letto, divano]) is None
    assert a._scegli_studente([sul_letto, sul_divano], contesto, tel, [letto, divano]) is sul_letto


# --- B4: l'audio conta come studio solo per Lectio --------------------------------------------------------

def test_b4_audio_di_studio_solo_lectio():
    liste = Liste().attive(hm("14:00"))
    film = [{"processo": "explorer.exe", "inattivo_secondi": 400, "audio": ["microsoft.photos.exe"]}] * 10
    assert riassumi(film, liste, {}).audio_studio is False
    lezione = [{"processo": "explorer.exe", "inattivo_secondi": 400, "audio": ["Lectio.exe"]}] * 10
    assert riassumi(lezione, liste, {}).audio_studio is True


# --- B5: i programmi di Argus per nome esatto; niente siti di clienti nelle liste di serie ----------------

def test_b5_programmi_di_argus_per_nome_esatto_e_niente_clienti():
    sempre = LISTE_PARTENZA["sempre"]["programmi"]
    for nome in ("argus.agente.exe", "Argus.Sblocco.exe", "argus.guardiano.exe"):
        assert programma_in(nome, sempre)
    assert not programma_in("argusgioco.exe", sempre)
    assert not programma_in("argus.exe", sempre)
    assert "stgm" + ".eu" not in LISTE_PARTENZA["lavoro"]["siti"]


# --- B7: lo sblocco vale solo col secondo segreto -----------------------------------------------------------

def test_b7_sblocco_solo_col_secondo_segreto_e_ore_controllate(tmp_path):
    async def prova():
        async with Banco(tmp_path, config_con_telecamera()) as b:
            segreto = "0123456789abcdef" * 4  # lo genera l'installatore del PC, non il NAS
            assert (await b.post("/api/pc/registra-sblocco", json={"segreto": segreto})).status_code == 200
            await b.minuti("13:30", "13:31", **ARRIVO)
            b.orologio.imposta(hm("14:00"))
            corpo = {"tipo": "sblocco_emergenza", "dettagli": {"ore": 2, "fino": "2030-01-01T00:00:00+01:00"}}
            r = await b.post("/api/pc/evento", json=corpo)
            assert r.status_code == 403 and r.json()["codice"] == "sblocco"
            r = await b.http.post("/api/pc/evento", json=corpo, headers=b.h | {"X-Argus-Sblocco": "sbagliato"})
            assert r.status_code == 403 and r.json()["codice"] == "sblocco"
            assert (await b.get("/api/pc/stato")).json()["modalita"] == "studio"
            con = b.h | {"X-Argus-Sblocco": segreto}
            for ore in ("due", 49, -1, 2.5, True, None):
                r = await b.http.post("/api/pc/evento", headers=con,
                                      json={"tipo": "sblocco_emergenza", "dettagli": {"ore": ore}})
                assert r.status_code == 422, ore
            r = await b.http.post("/api/pc/evento", headers=con, json={"tipo": "sblocco_emergenza", "dettagli": {}})
            assert r.status_code == 422
            r = await b.http.post("/api/pc/evento", json=corpo, headers=con)
            assert r.status_code == 200
            d = (await b.get("/api/pc/stato")).json()
            assert d["modalita"] == "libero"
            assert d["sblocco_fino"] == "2026-11-09T16:00:00+01:00"  # orologio del NAS, il fino del PC no
            r = await b.http.post("/api/pc/evento", headers=con,
                                  json={"tipo": "sblocco_emergenza", "dettagli": {"ore": 0}})
            assert r.status_code == 200
            d = (await b.get("/api/pc/stato")).json()
            assert d["modalita"] == "studio" and d["sblocco_fino"] is None
            # gli altri eventi non vogliono il segreto
            r = await b.post("/api/pc/evento", json={"tipo": "agente_riaperto", "dettagli": {}})
            assert r.status_code == 200
    esegui(prova())


# --- Regole nuove del motore ------------------------------------------------------------------------------

def test_pc_in_uso_niente_fuori_vista_anche_su_un_programma_sempre():
    s = Sim()
    _pronto(s)
    for i in range(8):
        t = hm("14:30") + timedelta(minutes=i)
        s.minuto(t, visto=False, pc=PcMinuto("sempre", True, ultimo_input=t + timedelta(seconds=30)))
    assert s.conta(Classe.NEUTRO, "14:30", "14:38") == 8
    assert s.m.aggiunte() == 0
    # "in uso" da qualche minuto ma senza tasti nell'ultimo minuto: il fuori vista conta
    s.tratto("14:38", "14:45", visto=False, pc=_pc("14:37:30"))
    assert s.m.giorno.agg_distrazione == 2


def test_conteggio_fuori_vista_fermo_durante_la_pausa():
    s = Sim()
    _pronto(s)
    assert s.cmd("ps m: spesa & t: 10", "14:00:10").ok
    s.tratto("14:00", "14:10", **FUORI)
    assert s.m.giorno.fuori_vista == 0
    assert s.conta(Classe.NEUTRO, "14:00", "14:10") == 10


def test_episodio_di_distrazione_finisce_dopo_5_minuti_senza():
    s = Sim()
    _pronto(s)
    s.tratto("14:00", "14:03", **TELEFONO)  # filtro, poi 2 minuti
    assert s.m.giorno.agg_distrazione == 2
    s.tratto("14:03", "14:07", **FERMO)  # 4 minuti: l'episodio è ancora aperto
    s.minuto("14:07", **TELEFONO)
    assert s.classe("14:07") == Classe.DISTRAZIONE and s.m.giorno.agg_distrazione == 3
    s.tratto("14:08", "14:13", **FERMO)  # 5 minuti senza distrazione: episodio chiuso
    assert s.m.giorno.distrazione is None
    s.minuto("14:13", **TELEFONO)  # si riparte dal minuto di filtro
    assert s.classe("14:13") == Classe.NEUTRO and s.m.giorno.agg_distrazione == 3
    s.minuto("14:14", **TELEFONO)
    assert s.classe("14:14") == Classe.DISTRAZIONE and s.m.giorno.agg_distrazione == 4


# --- Regole nuove del servizio ------------------------------------------------------------------------------

YOUTUBE = {"processo": "msedge.exe", "titolo": "Lezione di storia", "dominio": "youtube.com", "inattivo_secondi": 2}


def test_titoli_a_semif_solo_durante_la_quota(tmp_path):
    async def prova():
        async with Banco(tmp_path, config_con_telecamera()) as b:
            b.orologio.imposta(hm("12:30"))  # niente arrivo: libero
            await b.post("/api/pc/attivita", json={"campioni": [YOUTUBE]})
            assert await b.s.svuota_decisioni() == 0
            await b.minuti("13:30", "13:31", **ARRIVO)
            b.orologio.imposta(hm("13:40"))
            await b.post("/api/pc/attivita", json={"campioni": [YOUTUBE]})
            b.rete.risposte_semif = [risposta_semif("titolo", "studio")]
            assert await b.s.svuota_decisioni() == 1
    esegui(prova())


def test_titoli_niente_semif_quando_argus_e_inattivo(tmp_path):
    async def prova():
        async with Banco(tmp_path, Config()) as b:
            await b.post("/api/pc/attivita", json={"campioni": [YOUTUBE]})
            assert await b.s.svuota_decisioni() == 0
    esegui(prova())


def test_non_si_capisce_vale_15_minuti_poi_si_rigiudica(tmp_path):
    async def prova():
        async with Banco(tmp_path, config_con_telecamera()) as b:
            await b.minuti("13:30", "13:31", **ARRIVO)
            chiave = chiave_verdetto("youtube.com", "Lezione di storia")
            b.orologio.imposta(hm("14:00"))
            await b.post("/api/pc/attivita", json={"campioni": [YOUTUBE]})
            b.rete.risposte_semif = [risposta_semif("titolo", "non_si_capisce")]
            assert await b.s.svuota_decisioni() == 1
            assert (await b.get("/api/pc/stato")).json()["verdetti"][chiave] == "non_si_capisce"
            b.orologio.imposta(hm("14:14"))
            await b.post("/api/pc/attivita", json={"campioni": [YOUTUBE]})
            assert await b.s.svuota_decisioni() == 0  # ancora valido
            b.orologio.imposta(hm("14:16"))
            assert chiave not in (await b.get("/api/pc/stato")).json()["verdetti"]
            await b.post("/api/pc/attivita", json={"campioni": [YOUTUBE]})
            b.rete.risposte_semif = [risposta_semif("titolo", "studio")]
            assert await b.s.svuota_decisioni() == 1
            assert (await b.get("/api/pc/stato")).json()["verdetti"][chiave] == "studio"
    esegui(prova())


class VisioneMetaVuota(VisioneFinta):
    """Trova l'oggetto solo nelle prime `trovati` foto."""

    def __init__(self, trovati: int):
        super().__init__()
        self.trovati = trovati

    def registra(self, tipo, immagini):
        return "finto", [np.ones(4, dtype=np.float32) if i < self.trovati else None for i in range(len(immagini))]


def test_foto_rifiutate_se_l_oggetto_non_c_e_in_meta_delle_foto(tmp_path):
    async def prova():
        visione = VisioneMetaVuota(trovati=1)
        async with Banco(tmp_path, config_con_telecamera(), visione=visione) as b:
            foto = [("immagini", (f"{i}.jpg", jpeg(100 + i), "image/jpeg")) for i in range(4)]
            for tipo, nome, frase in (("tf", None, "Non vedo un telefono nelle foto: riprova inquadrandolo bene."),
                                      ("lb", "storia", "Non vedo un libro nelle foto: riprova inquadrandolo bene."),
                                      ("qd", "storia", "Non vedo un quaderno nelle foto: riprova inquadrandolo bene.")):
                dati = {"tipo": tipo} | ({"nome": nome} if nome else {})
                r = await b.post("/api/pc/foto", data=dati, files=foto)
                assert r.status_code == 422 and r.json()["errore"] == frase
            assert b.s.db.vettori() == []
            visione.trovati = 2  # metà: va bene
            r = await b.post("/api/pc/foto", data={"tipo": "lb", "nome": "storia"}, files=foto)
            assert r.json()["ok"] is True
    esegui(prova())


def test_registrazione_senza_oggetto_nella_foto_non_da_vettore():
    modelli = SimpleNamespace(rilevatore=SimpleNamespace(rileva=lambda img, soglia=None, classi=None: []),
                              vettori=SimpleNamespace(vettore=lambda r: np.ones(4, dtype=np.float32)))
    a = Analizzatore(modelli, SimpleNamespace(), ConfigVisione())
    img = np.full((120, 160, 3), 90, dtype=np.uint8)
    assert a.vettore_registrazione("tf", img) is None
    assert a.vettore_registrazione("lb", img) is None


def test_liste_extra_da_config_valgono_subito_e_cambiano_la_versione(tmp_path):
    config = da_dict({"telecamere": [], "liste_extra": {"lavoro": {"siti": ["cliente-esempio.it"],
                                                                   "programmi": ["gestionale.exe"]}}})
    assert config.liste_extra["lavoro"]["siti"] == ["cliente-esempio.it"]
    ora = hm("14:00")
    senza = Liste()
    con = Liste(extra=config.liste_extra, versione_extra=1)
    assert "cliente-esempio.it" in con.attive(ora)["lavoro"]["siti"]
    assert "gestionale.exe" in con.per_pc(ora)["lavoro"]["programmi"]
    assert con.versione(ora) == senza.versione(ora) + 1

    async def prova():
        async with Banco(tmp_path / "a", Config()) as b:
            v1 = (await b.get("/api/pc/liste")).json()["versione"]
        async with Banco(tmp_path / "a", config) as b:
            liste = (await b.get("/api/pc/liste")).json()
            assert "cliente-esempio.it" in liste["lavoro"]["siti"]
            assert liste["versione"] == v1 + 1
        async with Banco(tmp_path / "a", config) as b:  # stessa configurazione: stessa versione
            assert (await b.get("/api/pc/liste")).json()["versione"] == v1 + 1
    esegui(prova())


# --- Senza il PC per le foto: il NAS decide da solo solo con prove forti ------------------------------------

def _analizzatore_telefono(somiglianza: float | None, cv: ConfigVisione | None = None):
    lavori: list = []
    registrati = SimpleNamespace(telefono=[1] if somiglianza is not None else [],
                                 somiglianza_telefono=lambda v: somiglianza, oggetti=[])
    modelli = SimpleNamespace(vettori=SimpleNamespace(vettore=lambda r: np.ones(4, dtype=np.float32)))
    a = Analizzatore(modelli, registrati, cv or ConfigVisione(),
                     crea_lavoro=lambda tipo, jpeg_, contesto, origine: lavori.append((tipo, origine)))
    img = np.full((240, 320, 3), 25, dtype=np.uint8)
    img[100:160, 140:180] = 230  # schermo acceso
    studente = Traccia(1, Box(80, 20, 260, 240), 0.0, identita="studente")
    return a, img, studente, lavori


def _telefono_in_mano(punteggio: float = 0.9) -> OggettoPersona:
    return OggettoPersona(Rilevamento("cell phone", punteggio, Box(140, 100, 180, 160)), in_mano=True, vicino=True,
                          davanti_al_busto=False)


def _immagine(a, o, studente, img, adesso: float):
    """Come fa analizza(): il telefono, poi la fine dell'immagine (conta le immagini di fila)."""
    risultato = a._telefono(o, studente, img, 1.0, "Camera.", adesso=adesso)[0]
    a._dopo_immagine(forte_vista=a._forte_in_questa)
    return risultato


def test_senza_pc_dopo_15_minuti_decide_solo_con_prove_forti():
    a, img, studente, lavori = _analizzatore_telefono(somiglianza=0.02)
    o = _telefono_in_mano()
    assert _immagine(a, o, studente, img, 0.0) is None
    assert lavori and lavori[0][0] == "oggetto_in_mano"
    assert _immagine(a, o, studente, img, 10.0) is None  # c'è tempo per il PC
    a._dopo_immagine(forte_vista=False)  # un'immagine senza: si riparte da zero
    assert _immagine(a, o, studente, img, 901.0) is None
    assert _immagine(a, o, studente, img, 902.0) is None
    assert _immagine(a, o, studente, img, 903.0) == "telefono_altro"


def test_senza_pc_niente_decisione_se_la_prova_non_e_forte():
    # troppo simile al suo telefono
    a, img, studente, _ = _analizzatore_telefono(somiglianza=0.4)
    for t in (0.0, 901.0, 902.0, 903.0, 904.0):
        assert _immagine(a, _telefono_in_mano(), studente, img, t) is None
    # rilevatore poco sicuro
    a, img, studente, _ = _analizzatore_telefono(somiglianza=0.02)
    for t in (0.0, 901.0, 902.0, 903.0, 904.0):
        assert _immagine(a, _telefono_in_mano(0.5), studente, img, t) is None
    # nessun telefono registrato: non si può dire che è diverso
    a, img, studente, _ = _analizzatore_telefono(somiglianza=None)
    for t in (0.0, 901.0, 902.0, 903.0, 904.0):
        assert _immagine(a, _telefono_in_mano(), studente, img, t) is None
    # la risposta del PC arriva: si torna ad aspettare il PC
    a, img, studente, _ = _analizzatore_telefono(somiglianza=0.02)
    _immagine(a, _telefono_in_mano(), studente, img, 0.0)
    a.usa_giudizio({"origine": {"chiave": "telefono"}, "risposte": {"in_mano": "niente"}})
    a.giudizi.clear()
    for t in (901.0, 902.0, 903.0):
        assert _immagine(a, _telefono_in_mano(), studente, img, t) is None


def test_soglie_della_decisione_senza_pc_in_config():
    c = da_dict({"telecamere": [], "visione": {"soglia_senza_pc_rilevatore": 0.8, "soglia_senza_pc_diverso": 0.05,
                                               "immagini_senza_pc": 4, "minuti_senza_pc": 20}})
    assert (c.visione.soglia_senza_pc_rilevatore, c.visione.soglia_senza_pc_diverso,
            c.visione.immagini_senza_pc, c.visione.minuti_senza_pc) == (0.8, 0.05, 4, 20)


# --- dati sensibili --------------------------------------------------------------------------------------

def test_niente_nomi_o_percorsi_personali_nel_codice():
    """Il repo diventa pubblico: niente account, siti di clienti o percorsi di casa (scritti a pezzi
    qui, così questa prova non trova sé stessa)."""
    from pathlib import Path
    radice = Path(__file__).resolve().parent.parent
    vietati = ["posta" + "gaspa", "stgm" + ".eu", "c:" + "\\users\\" + "andre", "/c/users/" + "andre"]
    for file in list(radice.rglob("*.py")) + list(radice.rglob("*.md")) + list(radice.rglob("*.json")):
        if "__pycache__" in file.parts:
            continue
        testo = file.read_text(encoding="utf-8", errors="ignore").lower()
        for parola in vietati:
            assert parola not in testo, f"{file.name} contiene un dato personale"


def test_pc_toccato_arriva_dal_servizio_fino_al_motore(tmp_path):
    """Dal campione del PC (inattivo_secondi) al minuto del motore: tasti nell'ultimo minuto = è lì."""
    async def prova():
        async with Banco(tmp_path, config_con_telecamera()) as b:
            await b.minuti("13:30", "13:31", **ARRIVO)
            terminale = {"processo": "argus.agente.exe", "inattivo_secondi": 2}
            for i in range(8):
                t = hm("14:00") + timedelta(minutes=i)
                b.orologio.imposta(t + timedelta(seconds=30))
                await b.post("/api/pc/attivita", json={"campioni": [terminale] * 5})
                await b.minuti(t.strftime("%H:%M"), (t + timedelta(minutes=1)).strftime("%H:%M"), visto=False)
            assert b.s.motore.giorno.agg_distrazione == 0
            assert b.s.motore.giorno.fuori_vista == 0
    esegui(prova())


# --- Secondo segreto: lo genera l'installatore del PC e lo registra una volta sola ----------------------

def test_registra_sblocco_una_volta_sola(tmp_path):
    async def prova():
        async with Banco(tmp_path, config_con_telecamera()) as b:
            file = tmp_path / "token-sblocco.txt"
            assert not file.exists()  # il NAS non lo crea più al primo avvio
            await b.minuti("13:30", "13:31", **ARRIVO)
            b.orologio.imposta(hm("14:00"))
            sblocco = {"tipo": "sblocco_emergenza", "dettagli": {"ore": 2}}
            # senza segreto registrato nessuno sblocco, qualunque intestazione
            for intestazione in ({}, {"X-Argus-Sblocco": ""}, {"X-Argus-Sblocco": "ab" * 32}):
                r = await b.http.post("/api/pc/evento", json=sblocco, headers=b.h | intestazione)
                assert r.status_code == 403 and r.json()["codice"] == "sblocco"
            # serve il token del PC
            r = await b.http.post("/api/pc/registra-sblocco", json={"segreto": "ab" * 32})
            assert r.status_code == 401
            # 64 caratteri esadecimali, se no 422
            for sbagliato in ("ab" * 31, "zz" * 32, "ab" * 33, ""):
                r = await b.post("/api/pc/registra-sblocco", json={"segreto": sbagliato})
                assert r.status_code == 422, sbagliato
            assert not file.exists()
            segreto = "Cd" * 32
            r = await b.post("/api/pc/registra-sblocco", json={"segreto": segreto})
            assert r.status_code == 200 and r.json()["ok"] is True
            assert file.read_text(encoding="utf-8").strip() == segreto
            registro = b.s.db.registro("sblocco_registrato")
            assert registro and segreto not in str(registro)
            # già registrato: 409 e il segreto non cambia
            r = await b.post("/api/pc/registra-sblocco", json={"segreto": "ef" * 32})
            assert r.status_code == 409
            assert r.json()["codice"] == "sblocco_gia_registrato"
            assert r.json()["errore"] == ("Sul NAS c'è già un segreto di sblocco: va azzerato a mano da chi "
                                          "gestisce il NAS.")
            assert file.read_text(encoding="utf-8").strip() == segreto
            r = await b.http.post("/api/pc/evento", json=sblocco, headers=b.h | {"X-Argus-Sblocco": segreto})
            assert r.status_code == 200
            assert (await b.get("/api/pc/stato")).json()["modalita"] == "libero"
            # azzerato a mano (file cancellato): si può registrare di nuovo; un file vuoto vale come assente
            file.write_text("", encoding="utf-8")
            r = await b.post("/api/pc/registra-sblocco", json={"segreto": "ef" * 32})
            assert r.status_code == 200
            file.unlink()
            r = await b.post("/api/pc/registra-sblocco", json={"segreto": "12" * 32})
            assert r.status_code == 200
    esegui(prova())
