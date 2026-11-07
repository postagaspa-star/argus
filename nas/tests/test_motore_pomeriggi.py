"""Pomeriggi interi simulati minuto per minuto: studio, pranzo, distrazione, fuori vista."""

from argus.motore import Classe, PcMinuto
from simulatore import (FERMO, FUORI, MANGIA, STUDIA_LIBRO, STUDIA_PC, TELEFONO, Sim, hm)


def test_pomeriggio_perfetto():
    s = Sim()
    s.arriva("13:30")
    s.tratto("13:31", "14:00", **MANGIA)
    s.tratto("14:00", "14:30", **STUDIA_LIBRO)
    s.tratto("14:30", "15:00", **STUDIA_PC)
    s.tratto("15:00", "16:00", **TELEFONO)  # dopo la quota è libero: non conta
    assert s.m.giorno.fatta_alle == hm("14:59")
    assert s.m.giorno.agg_distrazione == 0
    assert s.conta(Classe.STUDIO) == 60
    assert s.conta(Classe.DISTRAZIONE) == 0
    assert s.m.modalita(hm("15:30")) == "libero"
    assert [v.testo for v in s.voci] == ["Fatto per oggi. Sei libero."]


def test_pranzo_di_sopra_entro_un_ora_tutto_neutro():
    s = Sim()
    s.arriva("13:30", visto_prima="07:15")
    s.tratto("13:31", "13:40", visto=True, stanza="salotto e cucina", dove="in_piedi", posa="in_piedi")
    s.tratto("13:40", "14:35", **FUORI)  # 55 minuti fuori
    s.tratto("14:35", "15:35", **STUDIA_LIBRO)
    assert s.m.giorno.agg_distrazione == 0
    assert s.conta(Classe.DISTRAZIONE) == 0
    assert s.m.giorno.pranzo == "usata"
    assert s.m.giorno.fatta_alle is not None
    assert all(v.motivo != "fuori_vista" for v in s.voci)


def test_pranzo_oltre_un_ora_conta_solo_dal_61_minuto():
    """Fuori 65 minuti: i primi 60 restano neutri (niente all'indietro), dal 61° distrazione subito,
    senza altri 5 minuti di grazia, con l'avviso a voce."""
    s = Sim()
    s.arriva("13:30", visto_prima="07:15")
    s.tratto("13:31", "13:35", visto=True, stanza="salotto e cucina", dove="in_piedi", posa="in_piedi")
    s.tratto("13:35", "14:40", **FUORI)  # 65 minuti fuori: 13:35-14:34 pranzo, 14:35-14:39 oltre
    assert s.conta(Classe.NEUTRO, "13:35", "14:35") == 60
    assert s.classe("14:35") == Classe.DISTRAZIONE
    assert s.conta(Classe.DISTRAZIONE, "14:35", "14:40") == 5
    assert s.m.giorno.agg_distrazione == 5
    assert s.m.giorno.pranzo == "persa"
    ev = s.eventi("pranzo")[-1].dettagli
    assert ev["esito"] == "non tornato entro 60 minuti" and ev["minuti_neutri"] == 60
    assert [v.testo for v in s.voci if v.motivo == "fuori_vista"] == [
        "Non ti vedo da un'ora: da adesso il tempo conta. Se ti serve una pausa, scrivila nel terminale."]
    s.tratto("14:40", "14:41", **STUDIA_LIBRO)
    assert s.m.giorno.agg_distrazione == 5


def test_pranzo_oltre_un_ora_si_ferma_con_la_pausa():
    """Dopo l'ora del pranzo scrive una pausa: da lì è neutro finché la pausa dura."""
    s = Sim()
    s.arriva("13:30", visto_prima="07:15")
    s.tratto("13:31", "13:35", visto=True, stanza="salotto e cucina", dove="in_piedi", posa="in_piedi")
    s.tratto("13:35", "14:37", **FUORI)  # 60 neutri + 2 distrazione (14:35, 14:36)
    assert s.m.giorno.agg_distrazione == 2
    assert s.cmd("ps m: spesa con mamma & t: 10", "14:37").ok
    s.tratto("14:37", "14:47", **FUORI)
    assert s.conta(Classe.NEUTRO, "14:37", "14:47") == 10
    assert s.m.giorno.agg_distrazione == 2


def test_pranzo_oltre_un_ora_niente_grazia_anche_dopo_il_pc():
    """Se dopo l'ora qualcuno usa il PC su una cosa permessa è neutro; appena il PC non è più in uso
    il fuori vista conta subito, senza ripartire dai 5 minuti neutri."""
    s = Sim()
    s.arriva("13:30", visto_prima="07:15")
    s.tratto("13:31", "13:35", visto=True, stanza="salotto e cucina", dove="in_piedi", posa="in_piedi")
    s.tratto("13:35", "14:36", **FUORI)  # 60 neutri + 1 distrazione
    s.tratto("14:36", "14:40", visto=False, pc=PcMinuto("studio", True))
    assert s.conta(Classe.NEUTRO, "14:36", "14:40") == 4
    s.tratto("14:40", "14:42", **FUORI)
    assert s.conta(Classe.DISTRAZIONE, "14:40", "14:42") == 2
    assert s.m.giorno.agg_distrazione == 3


def test_niente_pranzo_se_ha_gia_mangiato_davanti_alla_telecamera():
    s = Sim()
    s.arriva("13:30")
    s.tratto("13:31", "13:45", **MANGIA)
    s.tratto("13:45", "14:00", **FUORI)  # 15 minuti fuori: 5 neutri + 10 distrazione
    assert s.m.giorno.pranzo == "disponibile"
    assert s.m.giorno.agg_distrazione == 10


def test_sparizione_dopo_30_minuti_dall_arrivo_non_e_pranzo():
    s = Sim()
    s.arriva("13:30", visto_prima="07:00")
    s.m.giorno.visto_mangiare = False
    s.tratto("13:31", "14:05", visto=True, stanza="camera", dove="in_piedi", posa="in_piedi")
    s.tratto("14:05", "14:15", **FUORI)
    assert s.m.giorno.pranzo == "disponibile"
    assert s.m.giorno.agg_distrazione == 5


def test_telefono_primo_minuto_avviso_poi_conta_doppio():
    s = Sim()
    s.arriva()
    s.tratto("14:00", "14:20", **STUDIA_LIBRO)
    s.tratto("14:20", "14:30", **TELEFONO)
    s.tratto("14:30", "14:40", **STUDIA_LIBRO)
    assert s.classe("14:20") == Classe.NEUTRO  # filtro dei falsi allarmi
    assert s.conta(Classe.DISTRAZIONE, "14:20", "14:30") == 9
    assert s.m.giorno.agg_distrazione == 9
    assert s.m.totale() == 69
    assert s.m.fatti() == 30
    v = [x for x in s.voci if x.motivo == "distrazione"]
    assert len(v) == 1 and v[0].testo == "Torna a studiare: mancano 40 minuti."
    assert v[0].stanza == "camera"
    ep = s.episodi("distrazione")
    assert len(ep) == 1 and ep[0].minuti == 9 and ep[0].aggiunta == 9


def test_telefono_per_meno_di_un_minuto_niente():
    s = Sim()
    s.arriva()
    s.tratto("14:00", "14:10", **STUDIA_LIBRO)
    s.minuto("14:10", **TELEFONO)
    s.tratto("14:11", "14:20", **STUDIA_LIBRO)
    assert s.m.giorno.agg_distrazione == 0
    assert s.conta(Classe.DISTRAZIONE) == 0


def test_episodio_resta_aperto_finche_non_torna_a_studiare():
    s = Sim()
    s.arriva()
    s.tratto("14:00", "14:05", **TELEFONO)  # 1 neutro + 4 distrazione
    s.tratto("14:05", "14:08", **FERMO)  # in piedi, niente in mano: nel dubbio neutro
    s.tratto("14:08", "14:10", **TELEFONO)  # stesso episodio: contano subito
    assert s.conta(Classe.DISTRAZIONE) == 6
    assert s.classe("14:06") == Classe.NEUTRO
    s.tratto("14:10", "14:11", **STUDIA_LIBRO)
    assert len(s.episodi("distrazione")) == 1


def test_tetto_distrazioni_60():
    s = Sim()
    s.arriva()
    s.tratto("14:00", "16:00", **TELEFONO)
    assert s.m.giorno.agg_distrazione == 60
    assert s.m.totale() == 120


def test_fuori_vista_cinque_minuti_neutri():
    s = Sim()
    s.arriva("13:30", visto_prima="07:00")
    s.tratto("13:31", "14:10", **MANGIA)  # ha mangiato: niente pranzo
    s.tratto("14:10", "14:15", **FUORI)
    s.tratto("14:15", "14:20", **STUDIA_LIBRO)
    assert s.m.giorno.agg_distrazione == 0
    assert [v.testo for v in s.voci if v.motivo == "fuori_vista"] == [
        "Non ti vedo da 5 minuti. Se ti serve una pausa, scrivila nel terminale."]


def test_fuori_vista_dal_sesto_minuto_distrazione():
    s = Sim()
    s.arriva("13:30")
    s.tratto("13:31", "14:10", **MANGIA)
    s.tratto("14:10", "14:22", **FUORI)
    assert s.conta(Classe.NEUTRO, "14:10", "14:15") == 5
    assert s.conta(Classe.DISTRAZIONE, "14:15", "14:22") == 7
    assert s.m.giorno.agg_distrazione == 7
    # avviso al quinto minuto, non un altro al sesto
    assert len([v for v in s.voci if v.motivo in ("fuori_vista", "distrazione")]) == 1


def test_telecamere_spente_neutro_mai_imbroglio():
    """Regole 5 (rivista il 07/11): senza occhi non c'è prova, quindi niente punizione."""
    s = Sim()
    s.arriva("13:30")
    s.tratto("13:31", "14:00", **MANGIA)
    s.tratto("14:00", "14:10", visto=False, telecamere_ok=False)
    assert s.conta(Classe.IMBROGLIO) == 0
    assert s.m.giorno.agg_distrazione == 0
    assert s.conta(Classe.NEUTRO, "14:00", "14:10") == 10


def test_pc_usato_su_studio_senza_vederlo_nel_dubbio_neutro():
    s = Sim()
    s.arriva("13:30")
    s.tratto("13:31", "14:00", **MANGIA)
    s.tratto("14:00", "14:20", visto=False, pc=PcMinuto("studio", True))
    assert s.conta(Classe.NEUTRO, "14:00", "14:20") == 20
    assert s.m.giorno.agg_distrazione == 0
    assert s.m.giorno.studio == 0  # non avanza: non si vede che è lui


def test_pc_su_studio_ma_lui_sul_divano_non_e_studio():
    s = Sim()
    s.arriva()
    s.tratto("14:00", "14:10", visto=True, stanza="camera", dove="divano", posa="seduto",
             pc=PcMinuto("studio", True))
    assert s.m.giorno.studio == 0


def test_svago_sul_pc_e_distrazione():
    s = Sim()
    s.arriva()
    s.tratto("14:00", "14:05", visto=True, stanza="camera", dove="scrivania", posa="seduto",
             pc=PcMinuto("svago", True))
    assert s.conta(Classe.DISTRAZIONE) == 4


def test_youtube_in_attesa_di_giudizio_nel_dubbio_neutro():
    s = Sim()
    s.arriva()
    s.tratto("14:00", "14:05", visto=True, stanza="camera", dove="scrivania", posa="seduto",
             pc=PcMinuto("attesa", True))
    assert s.conta(Classe.NEUTRO, "14:00", "14:05") == 5


def test_lectio_con_le_cuffie_anche_sdraiato():
    s = Sim()
    s.arriva()
    s.tratto("14:00", "14:30", visto=True, stanza="camera", dove="letto", posa="sdraiato",
             pc=PcMinuto("sempre", False, audio_studio=True))
    assert s.m.giorno.studio == 30
    # ma se dorme no
    s.tratto("14:30", "14:40", visto=True, stanza="camera", dove="letto", posa="sdraiato", dorme=True,
             pc=PcMinuto("sempre", False, audio_studio=True))
    assert s.m.giorno.studio == 30


def test_telefono_batte_il_pc_di_studio():
    s = Sim()
    s.arriva()
    s.tratto("14:00", "14:05", visto=True, stanza="camera", dove="scrivania", posa="seduto",
             in_mano={"telefono_suo"}, pc=PcMinuto("studio", True))
    assert s.m.giorno.studio == 0
    assert s.conta(Classe.DISTRAZIONE) == 4


def test_leggere_altro_dormire_mangiare_neutri():
    s = Sim()
    s.arriva()
    s.tratto("14:00", "14:10", visto=True, stanza="camera", dove="divano", posa="seduto",
             in_mano={"libro_altro"})
    s.tratto("14:10", "14:20", visto=True, stanza="camera", dove="letto", posa="sdraiato", dorme=True)
    s.tratto("14:20", "14:30", **MANGIA)
    assert s.conta(Classe.NEUTRO, "14:00", "14:30") == 30
    assert s.m.giorno.agg_distrazione == 0


def test_voce_mai_piu_di_una_ogni_due_minuti():
    s = Sim()
    s.arriva()
    s.tratto("14:00", "14:02", **TELEFONO)  # avviso alle 14:00
    s.tratto("14:02", "14:03", **STUDIA_LIBRO)
    s.minuto("14:03", **TELEFONO)  # nuovo episodio: avviso, ma sono passati 3 minuti: ok
    s.tratto("14:04", "14:05", **STUDIA_LIBRO)
    s.minuto("14:05", **TELEFONO)  # nuovo episodio dopo 2 minuti dall'ultima frase: ok
    s.tratto("14:06", "14:07", **STUDIA_LIBRO)
    s.minuto("14:07", **TELEFONO)  # 2 minuti esatti: ok
    s.minuto("14:08", **STUDIA_LIBRO)
    s.minuto("14:08", **TELEFONO)  # minuto già classificato: ignorato
    tempi = [e for e in s.voci]
    assert len(tempi) == 4


def test_stato_pc_durante_lo_studio():
    s = Sim()
    s.arriva()
    s.tratto("14:00", "14:25", **STUDIA_LIBRO)
    st = s.m.stato_pc(hm("14:25:30"))
    assert st["modalita"] == "studio"
    assert st["quota"] == {"fatti": 25, "totale": 60, "sospeso": 0, "aggiunte": 0,
                           "pausa_disponibile": 20, "fine_prevista": "15:00"}
    assert st["classe_adesso"] == "studio"
    assert st["comando_attivo"] is None
    assert st["messaggio_copertura"] == "Adesso è tempo di studio. Mancano 35 minuti."
    assert st["quota_fatta_oggi"] is False


def test_sblocco_di_emergenza_niente_punizioni_ma_lo_studio_conta():
    s = Sim()
    s.arriva()
    s.m.sblocco(hm("16:00"), hm("14:00"))
    assert s.m.modalita(hm("14:00")) == "libero"
    s.tratto("14:00", "14:20", **TELEFONO)
    s.tratto("14:20", "14:40", **FUORI)
    s.tratto("14:40", "14:50", **STUDIA_LIBRO)
    assert s.m.giorno.agg_distrazione == 0
    assert s.m.giorno.studio == 10
    assert not s.voci
    s.tratto("16:00", "16:05", **TELEFONO)
    assert s.m.modalita(hm("16:05")) == "studio"
    assert s.m.giorno.agg_distrazione == 4
