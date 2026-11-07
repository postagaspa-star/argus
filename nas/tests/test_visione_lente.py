"""Prove lente con i modelli veri e immagini vere (COCO val2017, scaricate fuori dal repo).

Si eseguono con:  python -m pytest -m lente -s
Cartelle (fuori da OneDrive): ARGUS_MODELLI_PROVA (di base ~/argus-build/modelli) e
ARGUS_IMMAGINI_PROVA (di base ~/argus-build/immagini-prova). Se mancano, si scaricano.
"""

from __future__ import annotations

import os
import time
import urllib.request
from datetime import timedelta
from pathlib import Path

import cv2
import numpy as np
import pytest

from argus.config import Config, ConfigVisione, Telecamera
from argus.db import Database
from argus.lavori import CodaLavori
from argus.tempo import OrologioFinto
from simulatore import hm

pytestmark = pytest.mark.lente

MODELLI = Path(os.environ.get("ARGUS_MODELLI_PROVA", Path.home() / "argus-build" / "modelli"))
IMMAGINI = Path(os.environ.get("ARGUS_IMMAGINI_PROVA", Path.home() / "argus-build" / "immagini-prova"))
COCO = {
    "telefono": "000000016598",  # selfie allo specchio, telefono acceso in mano
    "viso": "000000004395",  # ragazzo, viso di tre quarti
    "letto": "000000000632",  # camera da letto con libri
    "divano": "000000039769",  # gatti sul divano con due telecomandi
    "scrivania": "000000009483",  # persone alla scrivania con portatili
    "in_piedi": "000000000785",  # sciatrice in piedi
    "salotto": "000000000139",  # salotto con TV, tavolo, persona
}


def immagine(nome: str) -> np.ndarray:
    IMMAGINI.mkdir(parents=True, exist_ok=True)
    file = IMMAGINI / f"{COCO[nome]}.jpg"
    if not file.exists():
        urllib.request.urlretrieve(f"http://images.cocodataset.org/val2017/{COCO[nome]}.jpg", file)  # noqa: S310
    img = cv2.imread(str(file))
    assert img is not None
    return img


@pytest.fixture(scope="module")
def modelli():
    from argus.visione import modelli as mod
    from argus.visione.analizzatore import Modelli

    mod.assicura(MODELLI)
    m = Modelli(MODELLI, ConfigVisione(thread=2))
    yield m
    m.chiudi()


def _classi(rilevamenti) -> set[str]:
    return {r.classe for r in rilevamenti}


def test_rilevatore_su_immagini_vere(modelli):
    r = modelli.rilevatore
    assert {"person", "cell phone"} <= _classi(r.rileva(immagine("telefono")))
    assert {"bed", "book"} <= _classi(r.rileva(immagine("letto")))
    assert {"couch", "remote"} <= _classi(r.rileva(immagine("divano")))
    assert {"person", "laptop", "chair"} <= _classi(r.rileva(immagine("scrivania")))
    assert {"person", "tv", "dining table"} <= _classi(r.rileva(immagine("salotto")))
    img = cv2.resize(immagine("salotto"), (640, 360))
    tempi = []
    for _ in range(6):
        t = time.perf_counter()
        r.rileva(img)
        tempi.append(time.perf_counter() - t)
    print(f"\nD-FINE S ({r.esecutore.motore}, 2 thread): {np.median(tempi) * 1000:.0f} ms per immagine 640x360")


def test_posa_in_piedi_e_sdraiata(modelli):
    from argus.visione.geometria import Box
    from argus.visione.posa import classifica_posa

    img = immagine("in_piedi")
    persona = max((x for x in modelli.rilevatore.rileva(img) if x.classe == "person"), key=lambda x: x.box.area)
    x1, y1, x2, y2 = persona.box.allarga(1.15, img.shape[1], img.shape[0]).interi()
    ritaglio = img[y1:y2, x1:x2]
    punti = modelli.posa.punti(ritaglio)
    assert punti is not None
    assert classifica_posa(punti, Box(0, 0, ritaglio.shape[1], ritaglio.shape[0])) == "in_piedi"
    girato = cv2.rotate(ritaglio, cv2.ROTATE_90_CLOCKWISE)
    punti_g = modelli.posa.punti(girato)
    assert classifica_posa(punti_g, Box(0, 0, girato.shape[1], girato.shape[0])) == "sdraiato"
    t = time.perf_counter()
    for _ in range(5):
        modelli.posa.punti(ritaglio)
    print(f"\nMediaPipe posa: {(time.perf_counter() - t) / 5 * 1000:.0f} ms per ritaglio")


def test_viso_trovato_e_riconosciuto(modelli):
    from argus.visione.viso import coseno

    lui = immagine("viso")
    visi = modelli.visi.trova(lui)
    assert visi, "YuNet non trova il viso"
    v1 = modelli.visi.vettore(lui, visi[0])
    # la stessa persona un po' più piccola e più scura: ancora lui
    variante = cv2.convertScaleAbs(cv2.resize(lui, None, fx=0.7, fy=0.7), alpha=0.8, beta=-10)
    v2 = modelli.visi.vettore(variante, modelli.visi.trova(variante)[0])
    altra = immagine("telefono")
    v3 = modelli.visi.vettore(altra, modelli.visi.trova(altra)[0])
    print(f"\nSFace: stesso viso {coseno(v1, v2):.2f}, persona diversa {coseno(v1, v3):.2f}")
    assert coseno(v1, v2) >= 0.363
    assert coseno(v1, v3) < 0.363
    occhi = modelli.visi.occhi(altra, modelli.visi.trova(altra)[0])
    assert occhi in ("aperti", None)


def test_siglip_riconosce_lo_stesso_oggetto(modelli):
    img = immagine("telefono")
    telefono = next(x for x in modelli.rilevatore.rileva(img) if x.classe == "cell phone")
    x1, y1, x2, y2 = telefono.box.allarga(1.1, img.shape[1], img.shape[0]).interi()
    ritaglio = img[y1:y2, x1:x2]
    letto = immagine("letto")
    libro = next(x for x in modelli.rilevatore.rileva(letto) if x.classe == "book")
    bx1, by1, bx2, by2 = libro.box.allarga(1.1, letto.shape[1], letto.shape[0]).interi()
    v_tel = modelli.vettori.vettore(ritaglio)
    v_tel2 = modelli.vettori.vettore(cv2.resize(ritaglio, None, fx=0.6, fy=0.6))
    v_lib = modelli.vettori.vettore(letto[by1:by2, bx1:bx2])
    s_uguale, s_diverso = float(v_tel @ v_tel2), float(v_tel @ v_lib)
    print(f"\nSigLIP 2: stesso telefono {s_uguale:.2f}, telefono contro libro {s_diverso:.2f}")
    assert s_uguale > 0.75
    assert s_diverso < 0.5
    t = time.perf_counter()
    for _ in range(5):
        modelli.vettori.vettore(ritaglio)
    print(f"SigLIP 2 int8: {(time.perf_counter() - t) / 5 * 1000:.0f} ms per ritaglio")


def test_pipeline_intera_con_telecamera_finta(tmp_path, modelli):
    """Registrazione del viso e del telefono, poi un minuto davanti alla telecamera finta:
    lo studente è riconosciuto, ha il suo telefono acceso in mano."""
    import psutil

    from argus.visione.flusso import TelecameraFinta
    from argus.visione.pipeline import Pipeline
    from argus.visione.ptz import PtzFinto

    img = immagine("telefono")
    piccola = cv2.resize(img, (int(img.shape[1] * 0.75), int(img.shape[0] * 0.75)))
    config = Config(telecamere=[Telecamera(id="camera", stanza="camera", tv=False)],
                    visione=ConfigVisione(thread=2, fps=2.0, fps_attesa=2.0))
    db = Database(tmp_path / "argus.db")
    lavori = CodaLavori(db, tmp_path / "lavori")
    orologio = OrologioFinto(hm("15:00"))
    camera = TelecameraFinta("camera", immagini=[piccola], principale_scala=1 / 0.75)
    ptz = PtzFinto()
    p = Pipeline(config, tmp_path, db, lavori, orologio, sorgenti={"camera": camera}, ptz={"camera": ptz},
                 modelli=modelli, scarica_modelli=False)
    p.avvia(ciclo=False)
    try:
        ok, jpeg = cv2.imencode(".jpg", img)
        modello, vettori = p.registra("vs", [jpeg.tobytes()])
        assert modello == "sface-2021dec" and vettori[0] is not None
        db.salva_vettore("vs", "vs", modello, vettori[0], "", orologio.adesso())
        modello, vettori = p.registra("tf", [jpeg.tobytes()])
        assert vettori[0] is not None
        db.salva_vettore("tf", "tf", modello, vettori[0], "", orologio.adesso())
        p.ricarica_registrati()
        p.imposta_contesto({"analizza": True})
        tempi = []
        for i in range(8):
            orologio.imposta(hm("15:00") + timedelta(seconds=5 * i))
            t = time.perf_counter()
            fatte = p.passo(adesso=1000.0 + 5 * i)
            tempi.append(time.perf_counter() - t)
            assert len(fatte) == 1
        o = fatte[0]
        assert o.studente is True
        assert "telefono_suo" in o.gettoni, o.descrizione
        m = p.minuto(hm("15:00"))
        assert m["visto"] is True and "telefono_suo" in m["in_mano"]
        assert p.scena(hm("15:00:36"))["visto"] is True
        rss = psutil.Process().memory_info().rss / 1e6
        print(f"\nPassi della visione: {np.median(tempi) * 1000:.0f} ms (mediana); memoria del processo {rss:.0f} MB")
        assert rss < 1600
    finally:
        p.ferma()
        db.chiudi()
