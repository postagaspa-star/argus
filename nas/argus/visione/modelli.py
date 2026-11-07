"""I modelli della visione: da dove si scaricano, controllo sha256, licenza.

Si scaricano al build dell'immagine Docker (o al primo avvio) in una cartella che è un volume:
    python -m argus.visione.modelli /modelli
Ogni file si controlla con lo sha256: se non torna, si cancella e si riprova (mai usare un file
diverso da quello previsto). Tutti i link sono fissati a una versione precisa.
"""

from __future__ import annotations

import hashlib
import logging
import sys
import urllib.request
from dataclasses import dataclass
from pathlib import Path

log = logging.getLogger("argus.modelli")

HF = "https://huggingface.co"
MP = "https://storage.googleapis.com/mediapipe-models"


@dataclass(frozen=True)
class Modello:
    nome: str
    file: str
    url: str
    sha256: str
    byte: int
    licenza: str
    a_cosa_serve: str


MODELLI: dict[str, Modello] = {m.nome: m for m in [
    Modello("dfine_s", "dfine_s_coco.onnx",
            f"{HF}/onnx-community/dfine_s_coco-ONNX/resolve/a3cf03147a9b86c78475139115c8ac142577352d/onnx/model.onnx",
            "cd8a49a945feda6d28c6304ae8ae85c2759ba1d78a5a83a22c5ce8db82ef7238", 41535197, "Apache-2.0",
            "rilevatore di oggetti COCO (D-FINE S)"),
    Modello("siglip2_visione", "siglip2_base_p16_224_vision_int8.onnx",
            f"{HF}/onnx-community/siglip2-base-patch16-224-ONNX/resolve/ba1f3b0843f24bc5417d38e19c37b287d719b2f4/onnx/vision_model_int8.onnx",
            "0dd31785a2713f1113ef2272472165c69d580473dae38d7b47568ac587795e70", 94553333, "Apache-2.0",
            "vettori di immagine per riconoscere libri, quaderni e telefono (SigLIP 2 base, solo parte visiva)"),
    Modello("yunet", "face_detection_yunet_2023mar.onnx",
            f"{HF}/opencv/face_detection_yunet/resolve/3cc26e7f1014a5ee5d74a42acee58bafc9d0a310/face_detection_yunet_2023mar.onnx",
            "8f2383e4dd3cfbb4553ea8718107fc0423210dc964f9f4280604804ed2552fa4", 232589, "MIT",
            "trova i visi (OpenCV YuNet)"),
    Modello("sface", "face_recognition_sface_2021dec.onnx",
            f"{HF}/opencv/face_recognition_sface/resolve/3d7082438a6e4551e840c9b2bb60b71e8da4b524/face_recognition_sface_2021dec.onnx",
            "0ba9fbfa01b5270c96627c4ef784da859931e02f04419c829e83484087c34e79", 38696353, "Apache-2.0",
            "riconosce il viso dello studente (OpenCV SFace)"),
    Modello("posa", "pose_landmarker_lite.task",
            f"{MP}/pose_landmarker/pose_landmarker_lite/float16/1/pose_landmarker_lite.task",
            "59929e1d1ee95287735ddd833b19cf4ac46d29bc7afddbbf6753c459690d574a", 5777746, "Apache-2.0",
            "posa del corpo (MediaPipe Pose Landmarker lite)"),
    Modello("occhi", "face_landmarker.task",
            f"{MP}/face_landmarker/face_landmarker/float16/1/face_landmarker.task",
            "64184e229b263107bc2b804c6625db1341ff2bb731874b0bcc2fe6544e0bc9ff", 3758596, "Apache-2.0",
            "occhi aperti o chiusi (MediaPipe Face Landmarker, blendshapes)"),
]}


class ErroreModello(Exception):
    pass


def sha256_file(percorso: Path) -> str:
    h = hashlib.sha256()
    with open(percorso, "rb") as f:
        for blocco in iter(lambda: f.read(1 << 20), b""):
            h.update(blocco)
    return h.hexdigest()


def percorso(cartella: Path | str, nome: str) -> Path:
    return Path(cartella) / MODELLI[nome].file


def controlla(cartella: Path | str, nome: str) -> bool:
    p = percorso(cartella, nome)
    m = MODELLI[nome]
    return p.exists() and p.stat().st_size == m.byte and sha256_file(p) == m.sha256


def scarica(cartella: Path | str, nome: str, tentativi: int = 3) -> Path:
    m = MODELLI[nome]
    destinazione = percorso(cartella, nome)
    destinazione.parent.mkdir(parents=True, exist_ok=True)
    if controlla(cartella, nome):
        return destinazione
    for tentativo in range(1, tentativi + 1):
        parziale = destinazione.with_suffix(destinazione.suffix + ".part")
        log.info("Scarico %s (%.1f MB), tentativo %d", m.file, m.byte / 1e6, tentativo)
        try:
            with urllib.request.urlopen(m.url, timeout=60) as r, open(parziale, "wb") as f:  # noqa: S310 - URL fisso
                while True:
                    blocco = r.read(1 << 20)
                    if not blocco:
                        break
                    f.write(blocco)
        except OSError as e:
            log.warning("Scaricamento di %s fallito: %s", m.file, e)
            parziale.unlink(missing_ok=True)
            continue
        if sha256_file(parziale) != m.sha256:
            log.warning("sha256 di %s non torna: lo butto", m.file)
            parziale.unlink(missing_ok=True)
            continue
        parziale.replace(destinazione)
        return destinazione
    raise ErroreModello(f"Non riesco a scaricare {m.file} con lo sha256 giusto")


def assicura(cartella: Path | str, nomi: list[str] | None = None) -> dict[str, Path]:
    return {n: scarica(cartella, n) for n in (nomi or list(MODELLI))}


if __name__ == "__main__":  # pragma: no cover - usato dal Dockerfile
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    destinazione = Path(sys.argv[1] if len(sys.argv) > 1 else "/modelli")
    for nome, p in assicura(destinazione).items():
        print(f"ok {nome}: {p}")
