"""Analisi di un'immagine: chi c'è, se è lo studente, dove sta, posa, cosa ha in mano, schermi.

Ritorna un'`Osservazione` (aggregatore.py). Quando non è chiaro (un telefono acceso o spento? un
libro di scuola o un fumetto? la TV è accesa?) mette in coda una foto dubbia per il modello del
PC e intanto non dice niente: nel dubbio, né avanti né punizione.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Callable

import cv2
import numpy as np

from ..config import ConfigVisione, Telecamera
from . import modelli as mod
from .aggregatore import Osservazione
from .geometria import Box
from .posa import ANCHE, SPALLE, Posa, classifica_posa, punti_mani
from .rilevatore import CIBO, Rilevamento, Rilevatore, nms
from .ragionamento import StoriaMovimento, anello, dove_sta, oggetti_della_persona, stato_schermo
from .vettori import Registrati, Vettori
from .viso import Visi

log = logging.getLogger("argus.analizzatore")

MODELLO_OGGETTI = "siglip2-base-p16-224-int8-centrato"
MODELLO_VISO = "sface-2021dec"
MEMORIA_GIUDIZI = 600.0  # secondi: per quanto vale la risposta di una foto dubbia
PAUSA_LAVORI_TIPO = 300.0
PAUSA_LAVORI = 60.0
OGNI_RITAGLIO = 3.0  # secondi tra due istantanee ad alta risoluzione della stessa telecamera
OGNI_VISO = 5.0


class Modelli:
    """I modelli, caricati una volta sola (al primo bisogno)."""

    def __init__(self, cartella: Path | str, cv: ConfigVisione):
        cartella = Path(cartella)
        p = {n: mod.percorso(cartella, n) for n in mod.MODELLI}
        nome_rilevatore = "dfine_s" if cv.modello not in mod.MODELLI else cv.modello
        inizio = time.perf_counter()
        self.rilevatore = Rilevatore(p[nome_rilevatore], cv.dispositivo, cv.thread, cv.soglia_oggetti)
        self.posa = Posa(p["posa"])
        self.visi = Visi(p["yunet"], p["sface"], p["occhi"])
        self.vettori = Vettori(p["siglip2_visione"], cv.thread)
        log.info("Modelli caricati in %.1f s (rilevatore: %s)", time.perf_counter() - inizio,
                 self.rilevatore.esecutore.motore)

    def chiudi(self) -> None:
        self.posa.chiudi()
        self.visi.chiudi()


@dataclass
class Traccia:
    id: int
    box: Box
    ultima: float
    identita: str | None = None
    somiglianza: float | None = None
    voti_altro: int = 0
    ultimo_viso: float = 0.0
    storia: StoriaMovimento = field(default_factory=StoriaMovimento)
    punti: np.ndarray | None = None
    posa: str | None = None


class Tracciatore:
    """Segue le persone tra un'immagine e l'altra (sovrapposizione dei riquadri)."""

    def __init__(self, scadenza: float = 4.0):
        self.tracce: list[Traccia] = []
        self.scadenza = scadenza
        self._prossimo = 1

    def aggiorna(self, persone: list[Box], adesso: float) -> list[Traccia]:
        libere = list(self.tracce)
        usate: list[Traccia] = []
        for box in sorted(persone, key=lambda b: -b.area):
            migliore, iou = None, 0.25
            for t in libere:
                v = t.box.iou(box)
                if v > iou:
                    migliore, iou = t, v
            if migliore is None:
                migliore = Traccia(self._prossimo, box, adesso)
                self._prossimo += 1
                self.tracce.append(migliore)
            else:
                libere.remove(migliore)
            migliore.box = box
            migliore.ultima = adesso
            usate.append(migliore)
        self.tracce = [t for t in self.tracce if adesso - t.ultima <= self.scadenza]
        return usate

    def dimentica(self) -> None:
        self.tracce = []


class Analizzatore:
    def __init__(self, modelli: Modelli, registrati: Registrati, cv: ConfigVisione,
                 crea_lavoro: Callable[[str, bytes, str, dict], None] | None = None,
                 stanze_studente: list[str] | None = None):
        self.m = modelli
        self.registrati = registrati
        self.cv = cv
        self.crea_lavoro = crea_lavoro
        self.stanze_studente = set(stanze_studente or ["camera"])
        self.tracciatori: dict[str, Tracciatore] = {}
        self.giudizi: dict[str, tuple[dict, float]] = {}  # "telefono" | "lettura" | "tv:<id>" -> (risposte, quando)
        self._lavori_fatti: dict[str, float] = {}
        self._ultimo_lavoro = -1e9
        self._ultimo_ritaglio: dict[str, float] = {}
        self._oggetti_alta: dict[str, tuple[float, Box, list[Rilevamento], np.ndarray | None, float]] = {}
        self._tv_precedente: dict[str, np.ndarray] = {}
        self._cache_vettori: dict[str, tuple[float, float | None, tuple]] = {}
        # Senza il PC per le foto dubbie (regole, sezione 6): da quando aspetta una risposta e quante
        # immagini di fila hanno una prova forte.
        self._senza_risposta_da: dict[str, float] = {}
        self._forte_di_fila: dict[str, int] = {}  # per telecamera
        self._forte_in_questa = False
        self._tel_corrente = ""

    # ---- risposte delle foto dubbie --------------------------------------------------------------

    def usa_giudizio(self, lavoro: dict) -> None:
        origine = lavoro.get("origine") or {}
        chiave = origine.get("chiave")
        if chiave and lavoro.get("risposte"):
            self.giudizi[chiave] = (lavoro["risposte"], time.monotonic())
            self._senza_risposta_da.pop(chiave, None)  # il PC c'è: si torna ad aspettare lui

    def _giudizio(self, chiave: str, adesso: float) -> dict | None:
        g = self.giudizi.get(chiave)
        if g is None or adesso - g[1] > MEMORIA_GIUDIZI:
            return None
        return g[0]

    def _chiedi(self, chiave: str, tipo: str, immagine: np.ndarray | None, contesto: str, adesso: float) -> None:
        if self.crea_lavoro is None or immagine is None or immagine.size == 0:
            return
        if adesso - self._lavori_fatti.get(chiave, -1e9) < PAUSA_LAVORI_TIPO:
            return
        if adesso - self._ultimo_lavoro < PAUSA_LAVORI:
            return
        if max(immagine.shape[:2]) > 768:
            f = 768 / max(immagine.shape[:2])
            immagine = cv2.resize(immagine, None, fx=f, fy=f, interpolation=cv2.INTER_AREA)
        ok, jpeg = cv2.imencode(".jpg", immagine, [cv2.IMWRITE_JPEG_QUALITY, 85])
        if not ok:
            return
        self._lavori_fatti[chiave] = adesso
        self._ultimo_lavoro = adesso
        self._senza_risposta_da.setdefault(chiave, adesso)
        self.crea_lavoro(tipo, jpeg.tobytes(), contesto, {"chiave": chiave})

    # ---- analisi -----------------------------------------------------------------------------

    def analizza(self, immagine: np.ndarray | None, tel: Telecamera, contesto: dict, ora: datetime,
                 adesso: float, telecamera_ferma: bool = True,
                 istantanea: Callable[[], np.ndarray | None] | None = None, tv_nella_stanza: bool = True) -> Osservazione:
        if immagine is None:
            return Osservazione(ora=ora, telecamera=tel.id, stanza=tel.stanza, ok=False)
        altezza, larghezza = immagine.shape[:2]
        rilevamenti = self.m.rilevatore.rileva(immagine)
        persone = [r.box for r in rilevamenti if r.classe == "person" and r.punteggio >= 0.5]
        tracciatore = self.tracciatori.setdefault(tel.id, Tracciatore())
        tracce = tracciatore.aggiorna(persone, adesso)
        for t in tracce:
            self._posa_traccia(immagine, t, adesso, telecamera_ferma)
            if t.identita != "studente" or adesso - t.ultimo_viso > OGNI_VISO:
                self._viso_traccia(immagine, t, adesso)

        studente = self._scegli_studente(tracce, contesto, tel, rilevamenti)
        self._tel_corrente = tel.id
        self._forte_in_questa = False
        forse = False
        if studente is None and tel.stanza in self.stanze_studente:
            for t in tracce:
                if t.identita is None and t.posa == "sdraiato" and dove_sta(t.box, t.posa, rilevamenti) == "letto":
                    forse = True
        altre = sum(1 for t in tracce if t is not studente)
        if studente is None:
            self._dopo_immagine(forte_vista=False)
            return Osservazione(ora=ora, telecamera=tel.id, stanza=tel.stanza, ok=True, forse=forse,
                                altre_persone=altre)

        dove = dove_sta(studente.box, studente.posa, rilevamenti)
        piccoli = [r for r in rilevamenti if r.classe != "person"]
        alta = self._alta_risoluzione(immagine, tel, studente, adesso, istantanea)
        if alta is not None:
            piccoli = nms(piccoli + alta[2], soglia_iou=0.3)
        mani = punti_mani(studente.punti)
        spalle_y = _y_medio(studente.punti, SPALLE)
        anche_y = _y_medio(studente.punti, ANCHE)
        oggetti = oggetti_della_persona(studente.box, mani, spalle_y, anche_y, piccoli)

        gettoni: set[str] = set()
        in_mano_parole: list[str] = []
        vicino_parole: list[str] = []
        mangia = False
        contesto_testo = f"{tel.stanza.capitalize()}, {ora.strftime('%H:%M')}."
        sorgente_ritagli, scala = (alta[3], alta[4]) if alta is not None and alta[3] is not None else (immagine, 1.0)
        for o in oggetti:
            classe = o.rilevamento.classe
            if classe in CIBO and (o.in_mano or o.davanti_al_busto):
                mangia = True
                continue
            if classe == "cell phone" and o.in_mano:
                gettone, parola = self._telefono(o, studente, sorgente_ritagli, scala, contesto_testo, adesso)
                if gettone:
                    gettoni.add(gettone)
                in_mano_parole.append(parola)
            elif classe == "book" and (o.in_mano or (o.davanti_al_busto and dove == "scrivania")):
                gettone, parola = self._libro(o, sorgente_ritagli, scala, contesto_testo, adesso)
                if gettone:
                    gettoni.add(gettone)
                (in_mano_parole if o.in_mano else vicino_parole).append(parola)
            elif classe == "remote" and o.in_mano:
                g = self._giudizio("telefono", adesso)
                if g and g.get("in_mano") == "controller":
                    gettoni.add("controller")
                    in_mano_parole.append("controller")
                else:
                    in_mano_parole.append("telecomando o controller")
            elif classe in ("cell phone", "book", "laptop", "cup", "bottle"):
                vicino_parole.append(_PAROLE.get(classe, classe))

        self._dopo_immagine(forte_vista=self._forte_in_questa)
        schermi, schermi_parole = self._schermi(immagine, tel, studente, dove, altre, rilevamenti, contesto_testo,
                                                adesso, tv_nella_stanza)
        occhi = None
        if studente.posa == "sdraiato" or not gettoni:
            occhi = self._occhi(immagine, studente)
        fermo = studente.storia.fermo()
        cx, cy = studente.box.centro
        return Osservazione(
            ora=ora, telecamera=tel.id, stanza=tel.stanza, ok=True, studente=True, dove=dove, posa=studente.posa,
            gettoni=frozenset(gettoni), schermi=frozenset(schermi), mangia=mangia, scrive=False, occhi=occhi,
            fermo=fermo, altre_persone=altre,
            descrizione={"in_mano": in_mano_parole, "vicino": vicino_parole, "schermi": schermi_parole},
            centro=(cx / larghezza, cy / altezza))

    # ---- pezzi ---------------------------------------------------------------------------------

    def _posa_traccia(self, immagine: np.ndarray, t: Traccia, adesso: float, ferma: bool) -> None:
        h, w = immagine.shape[:2]
        grande = t.box.allarga(1.15, w, h)
        x1, y1, x2, y2 = grande.interi()
        ritaglio = immagine[y1:y2, x1:x2]
        punti = None
        if ritaglio.size and min(ritaglio.shape[:2]) >= 24:
            if max(ritaglio.shape[:2]) < 256:
                f = 256 / max(ritaglio.shape[:2])
                ritaglio = cv2.resize(ritaglio, None, fx=f, fy=f, interpolation=cv2.INTER_LINEAR)
            else:
                f = 1.0
            punti = self.m.posa.punti(ritaglio)
            if punti is not None:
                punti[:, 0] = punti[:, 0] / f + x1
                punti[:, 1] = punti[:, 1] / f + y1
        t.punti = punti
        t.posa = classifica_posa(punti, t.box)
        t.storia.aggiungi(adesso, punti, t.box, ferma)

    def _viso_traccia(self, immagine: np.ndarray, t: Traccia, adesso: float, alta: np.ndarray | None = None,
                      scala: float = 1.0) -> None:
        sorgente = alta if alta is not None else immagine
        h, w = sorgente.shape[:2]
        box = t.box.scala(scala, scala)
        parte_alta = Box(box.x1, box.y1, box.x2, box.y1 + box.h * (0.6 if t.posa != "sdraiato" else 1.0))
        x1, y1, x2, y2 = parte_alta.allarga(1.2, w, h).interi()
        ritaglio = sorgente[y1:y2, x1:x2]
        if ritaglio.size == 0:
            return
        f = 1.0
        if max(ritaglio.shape[:2]) < 320:
            f = 320 / max(ritaglio.shape[:2])
            ritaglio = cv2.resize(ritaglio, None, fx=f, fy=f, interpolation=cv2.INTER_CUBIC)
        visi = self.m.visi.trova(ritaglio)
        if not visi:
            return
        viso = visi[0]
        if min(viso.box.l, viso.box.h) < 28:
            return
        t.ultimo_viso = adesso
        if not self.registrati.ha_viso:
            return
        s = self.registrati.somiglianza_viso(self.m.visi.vettore(ritaglio, viso))
        t.somiglianza = s
        if s is not None and s >= self.cv.soglia_viso:
            t.identita = "studente"
            t.voti_altro = 0
        elif s is not None and s < 0.2:
            t.voti_altro += 1
            if t.voti_altro >= 3:
                t.identita = "altro"

    def _scegli_studente(self, tracce: list[Traccia], contesto: dict, tel: Telecamera,
                         rilevamenti: list[Rilevamento]) -> Traccia | None:
        riconosciuti = [t for t in tracce if t.identita == "studente"]
        if riconosciuti:
            return max(riconosciuti, key=lambda t: t.somiglianza or 0.0)
        dm = contesto.get("dm")
        if dm:
            for t in tracce:
                if t.identita == "altro" or t.posa != "sdraiato":
                    continue
                dove = dove_sta(t.box, t.posa, rilevamenti)
                if dove not in ("letto", "divano"):
                    continue
                if dm == "valido" and contesto.get("dm_stanza") and contesto["dm_stanza"] != tel.stanza:
                    continue
                # Dopo la conferma conta solo la persona sdraiata nello stesso posto (letto o divano).
                if dm == "valido" and contesto.get("dm_dove") and contesto["dm_dove"] != dove:
                    continue
                return t
        return None

    def _alta_risoluzione(self, immagine: np.ndarray, tel: Telecamera, studente: Traccia, adesso: float,
                          istantanea: Callable[[], np.ndarray | None] | None):
        """Ogni tanto un'istantanea dal flusso principale: si cercano gli oggetti piccoli nel ritaglio
        della persona. Ritorna (quando, box persona, rilevamenti in coordinate del flusso secondario,
        immagine alta, scala) o None."""
        precedente = self._oggetti_alta.get(tel.id)
        if precedente is not None and adesso - precedente[0] < OGNI_RITAGLIO:
            if precedente[1].iou(studente.box) > 0.5:
                return precedente
            return None
        if istantanea is None:
            return None
        self._ultimo_ritaglio[tel.id] = adesso
        alta = istantanea()
        if alta is None:
            self._oggetti_alta.pop(tel.id, None)
            return None
        h, w = immagine.shape[:2]
        H, W = alta.shape[:2]
        scala = W / w
        if abs(H / h - scala) > 0.05 * scala:
            scala = min(W / w, H / h)
        box_alta = studente.box.scala(scala, scala).allarga(1.4, W, H)
        x1, y1, x2, y2 = box_alta.interi()
        ritaglio = alta[y1:y2, x1:x2]
        if ritaglio.size == 0:
            return None
        trovati = self.m.rilevatore.rileva(ritaglio, soglia=max(0.35, self.cv.soglia_oggetti - 0.1),
                                           classi={"cell phone", "book", "remote", "cup", "bottle", "laptop"} | CIBO)
        convertiti = [Rilevamento(r.classe, r.punteggio, Box((r.box.x1 + x1) / scala, (r.box.y1 + y1) / scala,
                                                              (r.box.x2 + x1) / scala, (r.box.y2 + y1) / scala))
                      for r in trovati]
        if studente.identita != "studente" or adesso - studente.ultimo_viso > OGNI_VISO:
            self._viso_traccia(immagine, studente, adesso, alta, scala)
        risultato = (adesso, studente.box, convertiti, alta, scala)
        self._oggetti_alta[tel.id] = risultato
        return risultato

    def _ritaglio(self, sorgente: np.ndarray, box: Box, scala: float, fattore: float = 1.15) -> np.ndarray:
        h, w = sorgente.shape[:2]
        x1, y1, x2, y2 = box.scala(scala, scala).allarga(fattore, w, h).interi()
        return sorgente[y1:y2, x1:x2]

    def _vettore_in_cache(self, chiave: str, ritaglio: np.ndarray, adesso: float):
        c = self._cache_vettori.get(chiave)
        if c is not None and adesso - c[0] < 8.0:
            return c[2]
        if ritaglio.size == 0 or min(ritaglio.shape[:2]) < 12:
            return None
        v = self.m.vettori.vettore(ritaglio)
        self._cache_vettori[chiave] = (adesso, None, (v,))
        return (v,)

    def _telefono(self, o, studente: Traccia, sorgente: np.ndarray, scala: float, contesto: str,
                  adesso: float) -> tuple[str | None, str]:
        box = o.rilevamento.box
        ritaglio = self._ritaglio(sorgente, box, scala)
        suo = None
        if self.registrati.telefono:
            v = self._vettore_in_cache("telefono", ritaglio, adesso)
            if v is not None:
                suo = self.registrati.somiglianza_telefono(v[0])
        intorno = anello(sorgente, box.scala(scala, scala))
        stato = stato_schermo(ritaglio, intorno)
        giudizio = self._giudizio("telefono", adesso)
        if giudizio is not None:
            cosa = giudizio.get("in_mano")
            acceso = giudizio.get("schermo_acceso") == "si" or stato == "acceso"
            if cosa == "telefono" and acceso:
                if suo is not None and suo < self.cv.soglia_telefono_altro:
                    return "telefono_altro", "un altro telefono acceso"
                return ("telefono_suo" if suo is not None and suo >= self.cv.soglia_telefono_suo else "telefono"), \
                    "telefono acceso"
            if cosa == "tablet" and acceso:
                return "tablet", "tablet acceso"
            if cosa in ("libro", "quaderno", "niente"):
                return None, "oggetto in mano (non un telefono)"
        decisione = self._senza_pc(o, suo, adesso)
        if decisione is not None:
            return decisione
        if suo is not None and suo >= self.cv.soglia_telefono_suo:
            # Il suo telefono: acceso se lo schermo si vede acceso o se lo tiene davanti al busto.
            if stato == "acceso" or (o.davanti_al_busto and stato != "spento"):
                return "telefono_suo", "telefono (suo), in uso"
            return None, "telefono (suo), non in uso"
        if stato != "spento":
            persona = self._ritaglio(sorgente, studente.box, scala, 1.3)
            self._chiedi("telefono", "oggetto_in_mano", persona, contesto, adesso)
        return None, "telefono? (da capire)"

    def _senza_pc(self, o, suo: float | None, adesso: float) -> tuple[str, str] | None:
        """Il PC non risponde alla foto dubbia da 15 minuti: il NAS decide da solo, ma SOLO con prove
        forti (telefono riconosciuto con sicurezza alta in mano in almeno 3 immagini di fila e
        chiaramente diverso dal telefono registrato). Altrimenti niente: nel dubbio, neutro."""
        cv = self.cv
        forte = (o.rilevamento.punteggio >= cv.soglia_senza_pc_rilevatore and suo is not None
                 and suo < cv.soglia_senza_pc_diverso)
        if not forte:
            return None
        self._forte_in_questa = True
        di_fila = self._forte_di_fila.get(self._tel_corrente, 0) + 1  # compresa questa immagine
        da = self._senza_risposta_da.get("telefono")
        if da is None or adesso - da < cv.minuti_senza_pc * 60:
            return None
        if di_fila < cv.immagini_senza_pc:
            return None
        return "telefono_altro", "un altro telefono o un tablet in mano (deciso senza il PC)"

    def _dopo_immagine(self, forte_vista: bool) -> None:
        """Alla fine di ogni immagine della stessa telecamera: le immagini "di fila" si contano solo
        finché ognuna ha la prova forte."""
        if forte_vista:
            self._forte_di_fila[self._tel_corrente] = self._forte_di_fila.get(self._tel_corrente, 0) + 1
        else:
            self._forte_di_fila[self._tel_corrente] = 0
        self._forte_in_questa = False

    def _libro(self, o, sorgente: np.ndarray, scala: float, contesto: str, adesso: float) -> tuple[str | None, str]:
        ritaglio = self._ritaglio(sorgente, o.rilevamento.box, scala, 1.1)
        if self.registrati.oggetti:
            v = self._vettore_in_cache(f"libro:{int(o.rilevamento.box.x1)}:{int(o.rilevamento.box.y1)}", ritaglio,
                                       adesso)
            if v is not None:
                tipo, nome, s = self.registrati.miglior_oggetto(v[0])
                if tipo and s >= self.cv.soglia_libro:
                    gettone = "libro_scuola" if tipo == "lb" else "quaderno_scuola"
                    parola = ("libro" if tipo == "lb" else "quaderno") + f" «{nome}»"
                    return gettone, parola
        giudizio = self._giudizio("lettura", adesso)
        if giudizio is not None:
            cosa = giudizio.get("lettura")
            if cosa == "libro_di_scuola":
                return "libro_scuola", "libro di scuola (visto dal PC)"
            if cosa == "quaderno_o_appunti":
                return "quaderno_scuola", "quaderno o appunti (visto dal PC)"
            if cosa in ("romanzo_o_fumetto", "rivista_o_altro"):
                return "libro_altro", "libro non di scuola"
        self._chiedi("lettura", "lettura", ritaglio, contesto, adesso)
        return "libro_dubbio", "libro sconosciuto"

    def _schermi(self, immagine: np.ndarray, tel: Telecamera, studente: Traccia, dove: str | None, altre: int,
                 rilevamenti: list[Rilevamento], contesto: str, adesso: float,
                 tv_nella_stanza: bool) -> tuple[set[str], list[str]]:
        if not tv_nella_stanza or dove == "scrivania" or altre > 0:
            return set(), []
        vicino = studente.box.allarga(1.2)
        schermi, parole = set(), []
        for r in rilevamenti:
            if r.classe != "tv" or r.box.intersezione(vicino) > 0.3 * r.box.area:
                continue
            x1, y1, x2, y2 = r.box.interi()
            ritaglio = immagine[y1:y2, x1:x2]
            chiave = f"tv:{tel.id}"
            precedente = self._tv_precedente.get(chiave)
            stato = stato_schermo(ritaglio, anello(immagine, r.box), precedente)
            if ritaglio.size:
                self._tv_precedente[chiave] = ritaglio.copy()
            giudizio = self._giudizio(chiave, adesso)
            if giudizio is not None and giudizio.get("tv_accesa") == "si":
                stato = "acceso"
            if stato == "acceso":
                schermi.add("tv")
                parole.append("televisione accesa")
            elif stato is None and giudizio is None:
                self._chiedi(chiave, "tv", immagine, contesto, adesso)
        return schermi, parole

    def _occhi(self, immagine: np.ndarray, studente: Traccia) -> str | None:
        h, w = immagine.shape[:2]
        alto = Box(studente.box.x1, studente.box.y1, studente.box.x2,
                   studente.box.y1 + studente.box.h * (0.5 if studente.posa != "sdraiato" else 1.0))
        x1, y1, x2, y2 = alto.allarga(1.2, w, h).interi()
        ritaglio = immagine[y1:y2, x1:x2]
        if ritaglio.size == 0:
            return None
        f = 1.0
        if max(ritaglio.shape[:2]) < 320:
            f = 320 / max(ritaglio.shape[:2])
            ritaglio = cv2.resize(ritaglio, None, fx=f, fy=f, interpolation=cv2.INTER_CUBIC)
        visi = self.m.visi.trova(ritaglio)
        if not visi or min(visi[0].box.l, visi[0].box.h) < 28:
            return None
        return self.m.visi.occhi(ritaglio, visi[0])

    # ---- registrazione (lb, qd, tf, vs) ----------------------------------------------------------

    def vettore_registrazione(self, tipo: str, immagine: np.ndarray) -> np.ndarray | None:
        if immagine is None or immagine.size == 0:
            return None
        if tipo == "vs":
            visi = self.m.visi.trova(immagine)
            if not visi:
                return None
            return self.m.visi.vettore(immagine, visi[0])
        classe = "cell phone" if tipo == "tf" else "book"
        trovati = [r for r in self.m.rilevatore.rileva(immagine, soglia=0.35, classi={classe})]
        if not trovati:
            return None  # l'oggetto non c'è: questa foto non vale (servizio.foto vuole almeno metà)
        migliore = max(trovati, key=lambda r: r.box.area * r.punteggio)
        h, w = immagine.shape[:2]
        x1, y1, x2, y2 = migliore.box.allarga(1.1, w, h).interi()
        ritaglio = immagine[y1:y2, x1:x2]
        if not ritaglio.size:
            return None
        return self.m.vettori.vettore(ritaglio)


_PAROLE = {"cell phone": "telefono", "book": "libro", "laptop": "portatile", "cup": "tazza", "bottle": "bottiglia"}


def _y_medio(punti: np.ndarray | None, indici: tuple[int, ...]) -> float | None:
    if punti is None:
        return None
    ys = [float(punti[i, 1]) for i in indici if punti[i, 2] >= 0.5]
    return sum(ys) / len(ys) if ys else None
