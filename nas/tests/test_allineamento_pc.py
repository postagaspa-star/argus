"""Allineamento col programma del PC (07/11, dopo le correzioni del PC).

- `agente_bloccato`: il guardiano lo manda quando l'agente non dà segni di vita e lo riapre.
- `non_riconosciuto:nome.exe`: nome giusto ma firma o percorso no -> sempre "altro".
- Nomi veri degli eseguibili: LM Studio è `Bionic.exe`, Wisper Ufficio `WisperUfficio.exe`.
"""

from __future__ import annotations

from argus.liste import LISTE_PARTENZA, programma_in
from argus.pc_attivita import audio_di_studio, categoria, da_giudicare, riassumi
from finti import config_con_telecamera
from test_api_servizio import Banco, esegui


def _liste() -> dict:
    return dict(LISTE_PARTENZA)


def test_evento_agente_bloccato_accettato_e_annotato(tmp_path):
    async def prova():
        async with Banco(tmp_path, config_con_telecamera()) as b:
            r = await b.post("/api/pc/evento", json={"tipo": "agente_bloccato",
                                                     "dettagli": {"pid": 4321, "secondi": 20}})
            assert r.status_code == 200 and r.json()["ok"] is True
            voci = b.s.db.registro("pc_agente_bloccato")
            assert voci
            r = await b.post("/api/pc/evento", json={"tipo": "agente_inventato", "dettagli": {}})
            assert r.status_code == 422
    esegui(prova())


def test_programma_non_riconosciuto_non_vale_mai_come_lista():
    liste = _liste()
    for processo in ("non_riconosciuto:code.exe", "non_riconosciuto:winword.exe", "non_riconosciuto:claude.exe",
                     "Non_Riconosciuto:Code.exe"):
        assert categoria({"processo": processo, "inattivo_secondi": 1}, liste, {}) == "altro", processo
    # Un browser non riconosciuto non è un browser: niente "attesa" di 20 secondi, niente giudizio.
    finto = {"processo": "non_riconosciuto:chrome.exe", "dominio": "it.wikipedia.org", "titolo": "Storia",
             "inattivo_secondi": 1}
    assert categoria(finto, liste, {}) == "altro"
    assert da_giudicare([finto], liste, {}) == []
    # Lo stesso programma riconosciuto vale come prima.
    assert categoria({"processo": "claude.exe", "inattivo_secondi": 1}, liste, {}) == "lavoro"


def test_audio_non_riconosciuto_non_e_lectio():
    liste = _liste()
    assert audio_di_studio({"audio": ["lectio.exe"]}, liste) is True
    assert audio_di_studio({"audio": ["non_riconosciuto:lectio.exe"]}, liste) is False
    minuto = riassumi([{"processo": "non_riconosciuto:lectio.exe", "audio": ["non_riconosciuto:lectio.exe"],
                        "inattivo_secondi": 2}], liste, {})
    assert minuto is not None and minuto.categoria == "altro" and minuto.audio_studio is False


def test_nomi_veri_di_lm_studio_e_wisper_ufficio():
    lavoro = LISTE_PARTENZA["lavoro"]["programmi"]
    assert programma_in("bionic.exe", lavoro)
    assert programma_in("wisperufficio.exe", lavoro)
    assert programma_in("wisper ufficio.exe", lavoro)
    assert categoria({"processo": "Bionic.exe", "inattivo_secondi": 1}, _liste(), {}) == "lavoro"
