"""Esecuzione dei modelli ONNX: OpenVINO sulla GPU Intel se c'è e funziona, se no ONNX Runtime sulla CPU.

Misure sul PC di sviluppo (vedi NOTE-COSTRUTTORE.md): per D-FINE S ONNX Runtime e OpenVINO su CPU
sono simili; per SigLIP 2 int8 ONNX Runtime è molto meglio (OpenVINO non gestisce bene la
quantizzazione dinamica e usa quasi 1 GB). Quindi: CPU = ONNX Runtime per tutti; GPU = OpenVINO
solo per il rilevatore, se /dev/dri esiste e una prova di esecuzione riesce.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

import numpy as np

log = logging.getLogger("argus.esecutore")


def gpu_intel_disponibile() -> bool:
    return os.path.exists("/dev/dri") and any(n.startswith("renderD") for n in os.listdir("/dev/dri"))


class Esecutore:
    """Un modello pronto da eseguire. `esegui(x)` ritorna la lista delle uscite (numpy)."""

    def __init__(self, percorso: Path | str, dispositivo: str = "auto", thread: int = 2,
                 prova: np.ndarray | None = None):
        self.percorso = str(percorso)
        self.motore = "onnxruntime-cpu"
        self._ov = None
        self._ort = None
        voglio_gpu = dispositivo.upper() == "GPU" or (dispositivo == "auto" and gpu_intel_disponibile())
        if voglio_gpu:
            try:
                self._prepara_openvino_gpu(prova)
            except Exception as e:  # noqa: BLE001 - qualsiasi problema della GPU: si torna alla CPU
                log.warning("GPU Intel non usabile (%s): uso la CPU", e)
                self._ov = None
        if self._ov is None:
            self._prepara_onnxruntime(thread)

    def _prepara_openvino_gpu(self, prova: np.ndarray | None) -> None:
        import openvino as ov

        core = ov.Core()
        if "GPU" not in core.available_devices:
            raise RuntimeError("OpenVINO non vede la GPU")
        compilato = core.compile_model(self.percorso, "GPU", {"PERFORMANCE_HINT": "LATENCY"})
        richiesta = compilato.create_infer_request()
        if prova is not None:
            richiesta.infer({0: prova})
        self._ov = richiesta
        self._ov_uscite = compilato.outputs
        self.motore = "openvino-gpu"
        log.info("Modello %s su GPU Intel (OpenVINO)", Path(self.percorso).name)

    def _prepara_onnxruntime(self, thread: int) -> None:
        import onnxruntime as ort

        opzioni = ort.SessionOptions()
        opzioni.intra_op_num_threads = max(1, thread)
        opzioni.inter_op_num_threads = 1
        opzioni.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL
        opzioni.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
        opzioni.enable_cpu_mem_arena = False  # meno memoria tenuta da parte (NAS con poca RAM)
        self._ort = ort.InferenceSession(self.percorso, opzioni, providers=["CPUExecutionProvider"])
        self._nome_ingresso = self._ort.get_inputs()[0].name
        self.motore = "onnxruntime-cpu"

    def esegui(self, x: np.ndarray) -> list[np.ndarray]:
        if self._ov is not None:
            risultato = self._ov.infer({0: x})
            return [np.asarray(risultato[u]) for u in self._ov_uscite]
        return self._ort.run(None, {self._nome_ingresso: x})
