"""Pensiero (sospeso) e imbroglio (regole sezioni 6 e 7)."""

from datetime import date

from argus.motore import Classe, Mezzanotte
from simulatore import (FUORI, MANGIA, PENSA, STUDIA_LIBRO, TABLET, TELEFONO, TV_CONSOLE, Sim, hm)


def _pronto(s: Sim) -> None:
    s.arriva("13:30")
    s.tratto("13:31", "14:00", **MANGIA)


# --- pensiero -----------------------------------------------------------------------------------

def test_pensiero_giudicato_studio_conta_dopo():
    s = Sim()
    _pronto(s)
    s.tratto("14:00", "14:10", **STUDIA_LIBRO)
    s.tratto("14:10", "14:18", **PENSA)  # 8 minuti in sospeso
    assert s.m.sospeso() == 8
    assert s.m.stato_pc(hm("14:18:10"))["classe_adesso"] == "sospeso"
    s.tratto("14:18", "14:26", **STUDIA_LIBRO)  # 8 minuti di studio vero dopo
    assert len(s.domande_pensiero) == 1
    d = s.domande_pensiero[0]
    assert d.minuti == 8 and d.inizio == hm("14:10") and d.fine == hm("14:18")
    assert s.m.giorno.studio == 18
    s._registra(s.m.giudizio_pensiero(d.id, "studio", hm("14:26:30")))
    assert s.m.giorno.studio == 26
    assert s.m.sospeso() == 0


def test_pensiero_al_massimo_10_minuti():
    s = Sim()
    _pronto(s)
    s.tratto("14:00", "14:15", visto=True, stanza="camera", dove="divano", posa="seduto", pensiero=True)
    s.tratto("14:15", "14:30", **STUDIA_LIBRO)
    d = s.domande_pensiero[0]
    s.m.giudizio_pensiero(d.id, "studio", hm("14:30"))
    assert s.m.giorno.studio == 15 + 10


def test_pensiero_dopo_troppo_corto_neutro_senza_chiedere():
    s = Sim()
    _pronto(s)
    s.tratto("14:00", "14:10", **PENSA)
    s.tratto("14:10", "14:15", **STUDIA_LIBRO)  # solo 5 minuti di studio
    s.tratto("14:15", "14:45", **FUORI)  # finestra di 30 minuti passata
    assert not s.domande_pensiero
    assert s.m.sospeso() == 0
    assert s.episodi("sospeso")[-1].dettagli["esito"] == "neutro"


def test_pensiero_giudicato_non_studio_o_dubbio_neutro():
    for esito in ("non_studio", "non_si_capisce"):
        s = Sim()
        _pronto(s)
        s.tratto("14:00", "14:05", **PENSA)
        s.tratto("14:05", "14:10", **STUDIA_LIBRO)
        s.m.giudizio_pensiero(s.domande_pensiero[0].id, esito, hm("14:10"))
        assert s.m.giorno.studio == 5


def test_pensiero_senza_giudizio_entro_mezzanotte_neutro():
    s = Sim()
    _pronto(s)
    s.tratto("14:00", "14:05", **PENSA)
    s.tratto("14:05", "14:10", **STUDIA_LIBRO)
    d = s.domande_pensiero[0]
    eff = s.m.allinea(hm("00:00", date(2026, 11, 10)))
    assert any(isinstance(e, Mezzanotte) for e in eff)
    # il giudizio arriva tardi: non cambia niente
    s.m.giudizio_pensiero(d.id, "studio", hm("00:05", date(2026, 11, 10)))
    assert s.m.giorno.studio == 0


def test_pensiero_in_piedi_o_a_letto_non_e_sospeso():
    s = Sim()
    _pronto(s)
    s.tratto("14:00", "14:05", visto=True, stanza="camera", dove="letto", posa="sdraiato", pensiero=True)
    assert s.conta(Classe.SOSPESO) == 0


def test_studio_dopo_il_pensiero_puo_chiudere_la_quota_col_giudizio():
    s = Sim()
    _pronto(s)
    s.tratto("14:00", "14:10", **PENSA)
    s.tratto("14:10", "15:00", **STUDIA_LIBRO)  # 50 minuti
    d = s.domande_pensiero[0]
    s._registra(s.m.giudizio_pensiero(d.id, "studio", hm("15:00:10")))
    assert s.m.giorno.fatta_alle is not None
    assert "Fatto per oggi. Sei libero." in [v.testo for v in s.voci]


# --- imbroglio ----------------------------------------------------------------------------------

def test_tablet_imbroglio_30_una_volta_per_episodio():
    s = Sim()
    _pronto(s)
    s.tratto("14:00", "14:20", **TABLET)
    assert s.m.giorno.agg_imbroglio == 30
    assert s.conta(Classe.IMBROGLIO) == 20
    assert [v.testo for v in s.voci] == ["Quello non è un dispositivo di studio: altri 30 minuti."]
    s.tratto("14:20", "14:30", **STUDIA_LIBRO)
    s.tratto("14:30", "14:32", **TABLET)  # nuovo episodio
    assert s.m.giorno.agg_imbroglio == 60


def test_imbroglio_breve_interruzione_stesso_episodio():
    s = Sim()
    _pronto(s)
    s.tratto("14:00", "14:05", **TABLET)
    s.tratto("14:05", "14:08", visto=True, stanza="camera", dove="divano", posa="seduto")
    s.tratto("14:08", "14:10", **TABLET)
    assert s.m.giorno.agg_imbroglio == 30
    s.tratto("14:10", "14:15", visto=True, stanza="camera", dove="divano", posa="seduto")
    s.tratto("14:15", "14:16", **TABLET)  # 5 minuti senza: episodio nuovo
    assert s.m.giorno.agg_imbroglio == 60


def test_tv_con_console_spegne_la_presa():
    s = Sim()
    _pronto(s)
    s.tratto("14:00", "14:03", **TV_CONSOLE)
    assert s.m.giorno.agg_imbroglio == 30
    assert [(p.dispositivo, p.stanza) for p in s.prese] == [("console", "salotto e cucina")]


def test_tv_accesa_davanti_imbroglio_e_presa():
    s = Sim()
    _pronto(s)
    s.tratto("14:00", "14:02", visto=True, stanza="salotto e cucina", dove="divano", posa="seduto",
             schermi={"tv"})
    assert s.m.giorno.agg_imbroglio == 30
    assert s.prese[0].dispositivo == "tv"


def test_tv_accesa_ma_pc_su_studio_non_e_imbroglio():
    from argus.motore import PcMinuto
    s = Sim()
    _pronto(s)
    s.tratto("14:00", "14:10", visto=True, stanza="camera", dove="scrivania", posa="seduto",
             schermi={"tv"}, pc=PcMinuto("studio", True))
    assert s.m.giorno.agg_imbroglio == 0
    assert s.m.giorno.studio == 10


def test_telefono_suo_e_distrazione_altro_telefono_imbroglio():
    s = Sim()
    _pronto(s)
    s.tratto("14:00", "14:03", **TELEFONO)
    assert s.m.giorno.agg_imbroglio == 0
    s.tratto("14:03", "14:05", **STUDIA_LIBRO)
    s.tratto("14:05", "14:07", visto=True, stanza="camera", dove="divano", posa="seduto",
             in_mano={"telefono_altro"})
    assert s.m.giorno.agg_imbroglio == 30


def test_tetto_totale_delle_aggiunte_120():
    s = Sim()
    _pronto(s)
    s.tratto("14:00", "15:10", **TELEFONO)  # 60 di distrazione (tetto)
    assert s.m.giorno.agg_distrazione == 60
    for inizio, fine, pausa_fine in (("15:10", "15:12", "15:20"), ("15:20", "15:22", "15:30"),
                                     ("15:30", "15:32", "15:40")):
        s.tratto(inizio, fine, **TABLET)
        s.tratto(fine, pausa_fine, **STUDIA_LIBRO)
    assert s.m.giorno.agg_imbroglio == 60  # 30 + 30 + 0: il tetto totale è 120
    assert s.m.aggiunte() == 120
    assert s.m.totale() == 180


def test_voce_imbroglio_saltata_se_appena_parlato():
    s = Sim()
    _pronto(s)
    s.minuto("14:00", **TELEFONO)  # avviso distrazione alle 14:00
    s.minuto("14:01", **TABLET)  # imbroglio un minuto dopo: +30 ma niente voce
    assert s.m.giorno.agg_imbroglio == 30
    assert [v.motivo for v in s.voci] == ["distrazione"]


def test_imbroglio_fuori_vista_non_esiste():
    s = Sim()
    _pronto(s)
    s.tratto("14:00", "14:10", visto=False, schermi={"tv"})
    assert s.m.giorno.agg_imbroglio == 0
