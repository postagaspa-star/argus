"""La pipeline della visione senza modelli: velocità per telecamera, inseguimento, pausa,
risposte delle foto dubbie, registrazione senza modelli."""

from __future__ import annotations

import time
from datetime import timedelta

import numpy as np

from argus.config import Config, ConfigVisione, Telecamera
from argus.db import Database
from argus.lavori import CodaLavori
from argus.tempo import OrologioFinto
from argus.visione.aggregatore import Osservazione
from argus.visione.flusso import TelecameraFinta
from argus.visione.pipeline import Pipeline
from argus.visione.ptz import PtzFinto
from simulatore import hm


class AnalizzatoreFinto:
    def __init__(self, dove_lo_vedo: str):
        self.dove_lo_vedo = dove_lo_vedo
        self.chiamate: list[str] = []
        self.giudizi: list[dict] = []

    def analizza(self, immagine, tel, contesto, ora, adesso, telecamera_ferma=True, istantanea=None,
                 tv_nella_stanza=True):
        self.chiamate.append(tel.id)
        lui = tel.id == self.dove_lo_vedo
        return Osservazione(ora=ora, telecamera=tel.id, stanza=tel.stanza, ok=immagine is not None, studente=lui,
                            dove="scrivania" if lui else None, posa="seduto" if lui else None,
                            centro=(0.9, 0.5) if lui else None)

    def usa_giudizio(self, lavoro: dict) -> None:
        self.giudizi.append(lavoro)


def _pipeline(tmp_path, ora="15:00"):
    config = Config(telecamere=[Telecamera(id="camera", stanza="camera"),
                                Telecamera(id="salotto", stanza="salotto e cucina")],
                    visione=ConfigVisione(fps=2.0, fps_attesa=0.5))
    db = Database(tmp_path / "argus.db")
    lavori = CodaLavori(db, tmp_path / "lavori")
    orologio = OrologioFinto(hm(ora))
    img = np.zeros((36, 64, 3), np.uint8)
    sorgenti = {"camera": TelecameraFinta("camera", immagini=[img]),
                "salotto": TelecameraFinta("salotto", immagini=[img])}
    ptz = {"camera": PtzFinto()}
    p = Pipeline(config, tmp_path, db, lavori, orologio, sorgenti=sorgenti, ptz=ptz,
                 cartella_modelli=tmp_path / "modelli", scarica_modelli=False)
    return p, db, lavori, orologio, ptz["camera"]


def test_piu_veloce_dove_c_e_lo_studente(tmp_path):
    p, db, lavori, orologio, ptz = _pipeline(tmp_path)
    finto = AnalizzatoreFinto("camera")
    p.analizzatore = finto
    p.avvia(ciclo=False)
    p.imposta_contesto({"analizza": True})
    t = 0.0
    while t < 10.0:
        orologio.imposta(hm("15:00") + timedelta(seconds=t))
        p.passo(adesso=100.0 + t)
        t += 0.25
    assert 19 <= finto.chiamate.count("camera") <= 21  # 2 al secondo
    assert 5 <= finto.chiamate.count("salotto") <= 6  # 0,5 al secondo
    m = p.minuto(hm("15:00"))
    assert m["visto"] and m["stanza"] == "camera" and m["dove"] == "scrivania"
    time.sleep(0.5)  # lo Stop dell'impulso parte da un timer
    assert ("muovi", 0.5, 0.0) in ptz.comandi and ("ferma",) in ptz.comandi
    p.ferma()
    db.chiudi()


def test_prima_delle_11_si_guarda_piano(tmp_path):
    p, db, lavori, orologio, ptz = _pipeline(tmp_path, ora="09:00")
    finto = AnalizzatoreFinto("camera")
    p.analizzatore = finto
    p.avvia(ciclo=False)
    t = 0.0
    while t < 10.0:
        p.passo(adesso=100.0 + t)
        t += 0.25
    assert finto.chiamate.count("camera") <= 6
    p.ferma()
    db.chiudi()


def test_risposte_delle_foto_dubbie_arrivano_all_analizzatore(tmp_path):
    import cv2
    p, db, lavori, orologio, ptz = _pipeline(tmp_path)
    finto = AnalizzatoreFinto("camera")
    p.analizzatore = finto
    p.avvia(ciclo=False)
    ok, jpeg = cv2.imencode(".jpg", np.zeros((8, 8, 3), np.uint8))
    id_l = lavori.aggiungi("oggetto_in_mano", jpeg.tobytes(), "Camera.", {"chiave": "telefono"}, orologio.adesso())
    lavori.rispondi(id_l, {"in_mano": "telefono", "schermo_acceso": "si"}, 1000, "finto", orologio.adesso())
    assert finto.giudizi and finto.giudizi[0]["origine"] == {"chiave": "telefono"}
    p.ferma()
    db.chiudi()


def test_senza_modelli_niente_analisi_e_registrazione_senza_vettori(tmp_path):
    p, db, lavori, orologio, ptz = _pipeline(tmp_path)
    p.avvia(ciclo=False)
    assert p.passo(adesso=1.0) == []
    assert p.errore_modelli
    modello, vettori = p.registra("lb", [b"x", b"y"])
    assert modello is None and vettori == [None, None]
    assert p.telecamere() == {"camera": "assente", "salotto": "assente"}  # in pausa, mai lette
    p.ferma()
    db.chiudi()


def test_ciclo_vero_in_pausa_e_attivo(tmp_path):
    p, db, lavori, orologio, ptz = _pipeline(tmp_path)
    finto = AnalizzatoreFinto("camera")
    p.analizzatore = finto
    p.avvia()
    time.sleep(0.3)
    assert finto.chiamate == []  # contesto: non analizzare
    p.imposta_contesto({"analizza": True})
    time.sleep(6.0)
    assert finto.chiamate
    assert p.telecamere() == {"camera": "ok", "salotto": "ok"}
    p.ferma()
    db.chiudi()
