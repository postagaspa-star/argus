"""Visione senza modelli: geometria, posa, "dove sta", oggetti in mano, schermi, fermo,
aggregatore del minuto, inseguimento PTZ con telecamera finta, telecamera finta da cartella."""

from __future__ import annotations

import hashlib
from datetime import timedelta

import cv2
import numpy as np
import pytest

from argus.visione import modelli as mod
from argus.visione.aggregatore import Aggregatore, Osservazione, riassumi_minuto
from argus.visione.flusso import TelecameraFinta
from argus.visione.geometria import Box
from argus.visione.posa import classifica_posa, posa_da_forma
from argus.visione.ptz import Inseguitore, PtzFinto
from argus.visione.ragionamento import (StoriaMovimento, anello, dove_sta, oggetti_della_persona, stato_schermo,
                                        vicino_alle_mani)
from argus.visione.rilevatore import CLASSI, Rilevamento, decodifica
from simulatore import hm


def R(classe: str, x1, y1, x2, y2, p=0.9) -> Rilevamento:
    return Rilevamento(classe, p, Box(x1, y1, x2, y2))


# --- geometria ----------------------------------------------------------------------------------

def test_box():
    a, b = Box(0, 0, 10, 10), Box(5, 5, 15, 15)
    assert a.area == 100 and a.intersezione(b) == 25
    assert a.iou(b) == pytest.approx(25 / 175)
    assert Box(2, 2, 4, 4).frazione_dentro(a) == 1.0
    assert a.allarga(2.0, 12, 12) == Box(0, 0, 12, 12)
    assert a.centro == (5, 5)


# --- posa ---------------------------------------------------------------------------------------

def _scheletro(punti: dict[int, tuple[float, float]]) -> np.ndarray:
    p = np.zeros((33, 3), dtype=np.float32)
    for i, (x, y) in punti.items():
        p[i] = (x, y, 0.9)
    return p


IN_PIEDI = {0: (50, 10), 11: (40, 30), 12: (60, 30), 23: (42, 80), 24: (58, 80), 25: (42, 120), 26: (58, 120),
            27: (42, 160), 28: (58, 160), 15: (35, 80), 16: (65, 80)}
SEDUTO = {0: (50, 10), 11: (40, 30), 12: (60, 30), 23: (42, 80), 24: (58, 80), 25: (80, 85), 26: (90, 85),
          27: (80, 125), 28: (90, 125)}
SDRAIATO = {0: (10, 50), 11: (30, 40), 12: (30, 60), 23: (80, 42), 24: (80, 58), 25: (120, 42), 26: (120, 58)}
CHINO = {0: (75, 40), 11: (55, 30), 12: (75, 32), 23: (42, 80), 24: (58, 80), 25: (80, 85), 26: (90, 85)}


@pytest.mark.parametrize("punti,attesa", [(IN_PIEDI, "in_piedi"), (SEDUTO, "seduto"), (SDRAIATO, "sdraiato"),
                                          (CHINO, "chino")])
def test_classifica_posa(punti, attesa):
    assert classifica_posa(_scheletro(punti), Box(0, 0, 100, 170)) == attesa


def test_posa_dalla_forma_quando_mancano_i_punti():
    assert posa_da_forma(Box(0, 0, 200, 80)) == "sdraiato"
    assert posa_da_forma(Box(0, 0, 50, 200)) == "in_piedi"
    assert posa_da_forma(Box(0, 0, 100, 120)) is None
    assert classifica_posa(None, Box(0, 0, 200, 80)) == "sdraiato"


# --- dove sta -----------------------------------------------------------------------------------

def test_dove_sta():
    persona = Box(100, 100, 200, 300)
    assert dove_sta(persona, "in_piedi", []) == "in_piedi"
    assert dove_sta(persona, "seduto", [R("couch", 50, 180, 300, 320)]) == "divano"
    assert dove_sta(persona, "sdraiato", [R("bed", 0, 150, 400, 400)]) == "letto"
    assert dove_sta(persona, "seduto", [R("chair", 110, 200, 190, 320), R("dining table", 180, 200, 400, 300)]) == "scrivania"
    assert dove_sta(persona, "chino", [R("laptop", 190, 180, 260, 230)]) == "scrivania"
    assert dove_sta(persona, "seduto", [R("chair", 110, 200, 190, 320)]) is None
    assert dove_sta(persona, "seduto", []) is None


def test_oggetti_in_mano_e_davanti():
    persona = Box(100, 100, 200, 300)
    mani = [(150, 180)]
    trovati = oggetti_della_persona(persona, mani, 140, 220, [
        R("cell phone", 140, 170, 160, 195), R("book", 400, 400, 450, 450), R("cup", 180, 250, 195, 270),
        R("couch", 0, 0, 500, 500)])
    assert [(o.rilevamento.classe, o.in_mano) for o in trovati] == [("cell phone", True), ("cup", False)]
    assert trovati[0].davanti_al_busto is True
    assert not vicino_alle_mani(Box(0, 0, 5, 5), mani, persona)


# --- schermi ------------------------------------------------------------------------------------

def test_stato_schermo():
    sfondo = np.full((120, 160, 3), 60, dtype=np.uint8)
    acceso = sfondo.copy()
    acceso[40:80, 50:110] = (240, 230, 220)
    box = Box(50, 40, 110, 80)
    x1, y1, x2, y2 = box.interi()
    assert stato_schermo(acceso[y1:y2, x1:x2], anello(acceso, box)) == "acceso"
    spento = sfondo.copy()
    spento[40:80, 50:110] = 15
    assert stato_schermo(spento[y1:y2, x1:x2], anello(spento, box)) == "spento"
    # una TV che cambia da un'immagine all'altra è accesa anche se non più chiara del muro
    rng = np.random.default_rng(1)
    a = rng.integers(40, 120, (40, 60, 3), dtype=np.uint8)
    b = rng.integers(40, 120, (40, 60, 3), dtype=np.uint8)
    assert stato_schermo(a, None, b) == "acceso"
    assert stato_schermo(np.zeros((2, 2, 3), np.uint8), None) is None


# --- fermo ----------------------------------------------------------------------------------------

def test_storia_movimento_fermo_e_mosso():
    s = StoriaMovimento()
    punti = _scheletro(SEDUTO)
    for t in range(0, 15):
        s.aggiungi(float(t), punti + np.array([0.3, 0.2, 0], dtype=np.float32) * (t % 2), Box(0, 0, 100, 170), True)
    assert s.fermo() is True
    m = StoriaMovimento()
    for t in range(0, 15):
        m.aggiungi(float(t), punti + np.array([t * 3.0, 0, 0], dtype=np.float32), Box(0, 0, 100, 170), True)
    assert m.fermo() is False
    corta = StoriaMovimento()
    corta.aggiungi(0.0, punti, Box(0, 0, 100, 170), True)
    assert corta.fermo() is None
    # se la telecamera si muove, si ricomincia
    s.aggiungi(16.0, punti, Box(0, 0, 100, 170), False)
    assert s.fermo() is None


# --- aggregatore ------------------------------------------------------------------------------------

def _oss(secondo: int, **kw) -> Osservazione:
    return Osservazione(ora=hm("14:00") + timedelta(seconds=secondo), telecamera="camera", stanza="camera", **kw)


def test_minuto_con_studente_e_telefono_per_buona_parte():
    agg = Aggregatore()
    for s in range(0, 60, 2):
        agg.aggiungi(_oss(s, studente=True, dove="divano", posa="seduto",
                          gettoni=frozenset({"telefono_suo"}) if s < 40 else frozenset()))
    m = agg.minuto(hm("14:00"))
    assert m["visto"] and m["stanza"] == "camera" and m["dove"] == "divano" and m["posa"] == "seduto"
    assert m["in_mano"] == frozenset({"telefono_suo"})


def test_minuto_oggetto_visto_poco_non_conta():
    oss = [_oss(s, studente=True, dove="divano", posa="seduto",
                gettoni=frozenset({"tablet"}) if s < 10 else frozenset()) for s in range(0, 60, 2)]
    assert riassumi_minuto(oss)["in_mano"] == frozenset()


def test_minuto_senza_studente_e_telecamere_rotte():
    assert riassumi_minuto([_oss(s, ok=True) for s in range(0, 60, 5)]) == {
        "telecamere_ok": True, "stanze_cieche": frozenset(), "visto": False, "forse_visto": False}
    assert riassumi_minuto([_oss(s, ok=False) for s in range(0, 60, 5)])["telecamere_ok"] is False
    assert riassumi_minuto([])["telecamere_ok"] is False
    # una sola immagine non basta per dire "visto"
    assert riassumi_minuto([_oss(0, studente=True)])["visto"] is False
    assert riassumi_minuto([_oss(s, forse=True) for s in range(3)])["forse_visto"] is True


def test_minuto_pensiero_dorme_mangia():
    pensa = [_oss(s, studente=True, dove="scrivania", posa="seduto", fermo=True, occhi="aperti") for s in range(0, 60, 3)]
    assert riassumi_minuto(pensa)["pensiero"] is True
    chiusi = [_oss(s, studente=True, dove="letto", posa="sdraiato", fermo=True, occhi="chiusi") for s in range(0, 60, 3)]
    m = riassumi_minuto(chiusi)
    assert m["dorme"] is True and m["pensiero"] is False
    occhi_ignoti = [_oss(s, studente=True, dove="scrivania", posa="seduto", fermo=True) for s in range(0, 60, 3)]
    assert riassumi_minuto(occhi_ignoti)["pensiero"] is False  # nel dubbio niente sospeso
    mangia = [_oss(s, studente=True, dove="scrivania", posa="seduto", mangia=s < 30) for s in range(0, 60, 3)]
    assert riassumi_minuto(mangia)["mangia"] is True


def test_scena_per_il_diario():
    agg = Aggregatore()
    agg.aggiungi(_oss(0, studente=True, dove="scrivania", posa="chino",
                      descrizione={"in_mano": ["libro «storia»"], "vicino": [], "schermi": []}))
    sc = agg.scena(hm("14:00:05"))
    assert sc["visto"] and sc["in_mano"] == ["libro «storia»"]
    assert agg.scena(hm("14:05"))["visto"] is False
    assert agg.scena(hm("14:05"))["ultima_stanza"] == "camera"


# --- PTZ ------------------------------------------------------------------------------------------

def test_inseguitore_zona_morta_intervallo_direzione_e_ritorno():
    ptz = PtzFinto()
    ins = Inseguitore(ptz, sincrono=True)
    assert ins.aggiorna((0.55, 0.45), 0.0) is None  # dentro la zona morta (±10%)
    assert ptz.comandi == [("segna_partenza",)]
    assert ins.aggiorna((0.8, 0.5), 1.0) == "muovi"
    assert ptz.comandi[-2:] == [("muovi", 0.5, 0.0), ("ferma",)]
    assert ins.aggiorna((0.8, 0.5), 2.0) is None  # meno di 2 secondi dall'ultimo movimento
    assert ins.aggiorna((0.2, 0.9), 3.1) == "muovi"
    assert ptz.comandi[-2] == ("muovi", -0.5, -0.5)  # a sinistra e in basso
    assert ins.aggiorna(None, 30.0) is None
    assert ins.aggiorna(None, 62.0) is None  # 58,9 secondi senza di lui: ancora no
    assert ins.aggiorna(None, 63.2) == "partenza"
    assert ptz.comandi[-1] == ("torna_partenza",)
    assert ins.aggiorna(None, 200.0) is None  # già tornata


def test_inseguitore_inverte_e_si_spegne_se_la_telecamera_non_risponde():
    spento = []
    ptz = PtzFinto(rotta=True)
    ins = Inseguitore(ptz, sincrono=True, quando_spento=spento.append)
    for t in range(4):
        ins.aggiorna((0.9, 0.5), t * 3.0)
    assert ins.attivo is False and spento
    assert ins.aggiorna((0.9, 0.5), 20.0) is None
    ptz2 = PtzFinto()
    ins2 = Inseguitore(ptz2, sincrono=True, inverti_pan=True, inverti_tilt=True)
    ins2.aggiorna((0.9, 0.9), 0.0)
    assert ("muovi", -0.5, 0.5) in ptz2.comandi


# --- telecamera finta ------------------------------------------------------------------------------

def test_telecamera_finta_da_cartella(tmp_path):
    for i in range(3):
        cv2.imwrite(str(tmp_path / f"{i:02d}.png"), np.full((20, 30, 3), i * 50, np.uint8))
    (tmp_path / "leggimi.txt").write_text("non è un'immagine")
    t = TelecameraFinta("camera", tmp_path, ripeti=False)
    valori = []
    while True:
        img, quando = t.ultimo()
        if img is None:
            break
        valori.append(int(img[0, 0, 0]))
    assert valori == [0, 50, 100]
    assert t.istantanea_principale() is not None
    t.spenta = True
    assert t.stato() == "errore" and t.ultimo()[0] is None


# --- modelli e rilevatore --------------------------------------------------------------------------

def test_manifesto_dei_modelli():
    assert {"dfine_s", "siglip2_visione", "yunet", "sface", "posa", "occhi"} <= set(mod.MODELLI)
    for m in mod.MODELLI.values():
        assert len(m.sha256) == 64 and m.url.startswith("https://") and m.licenza in ("Apache-2.0", "MIT")
        assert "/resolve/main/" not in m.url and "latest" not in m.url  # versione fissata


def test_controllo_sha256(tmp_path, monkeypatch):
    dati = b"modello finto"
    finto = mod.Modello("finto", "finto.onnx", "https://esempio/finto.onnx", hashlib.sha256(dati).hexdigest(),
                        len(dati), "MIT", "prova")
    monkeypatch.setitem(mod.MODELLI, "finto", finto)
    (tmp_path / "finto.onnx").write_bytes(dati)
    assert mod.controlla(tmp_path, "finto")
    (tmp_path / "finto.onnx").write_bytes(b"modello cambiat")
    assert not mod.controlla(tmp_path, "finto")


def test_decodifica_del_rilevatore():
    logits = np.full((300, 80), -10.0, dtype=np.float32)
    riquadri = np.zeros((300, 4), dtype=np.float32)
    logits[0, CLASSI.index("person")] = 3.0
    riquadri[0] = (0.5, 0.5, 0.2, 0.4)
    logits[1, CLASSI.index("cell phone")] = 1.0
    riquadri[1] = (0.25, 0.25, 0.1, 0.1)
    logits[2, CLASSI.index("zebra")] = 5.0  # classe che non serve
    logits[3, CLASSI.index("person")] = 2.9  # doppione
    riquadri[3] = (0.5, 0.5, 0.2, 0.41)
    trovati = decodifica(logits, riquadri, 640, 360, 0.45, {"person", "cell phone"})
    assert sorted(r.classe for r in trovati) == ["cell phone", "person"]
    persona = next(r for r in trovati if r.classe == "person")
    assert (persona.box.x1, persona.box.y1, persona.box.x2, persona.box.y2) == pytest.approx((256, 108, 384, 252), abs=0.01)
    assert CLASSI[57] == "couch" and CLASSI[62] == "tv" and CLASSI[67] == "cell phone"
