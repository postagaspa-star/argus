# Argus sul NAS: un volume su /data (database, token, config, foto registrate, voce) e uno su
# /modelli (i modelli della visione, ~185 MB, controllati con sha256).
FROM python:3.12-slim-bookworm

# MODELLI_AL_BUILD=1: i modelli si scaricano qui (sha256 controllato) e finiscono nel volume
# "modelli" la prima volta che si crea. Con 0 si scaricano al primo avvio.
ARG MODELLI_AL_BUILD=1
# GPU_INTEL=1: aggiunge il driver OpenCL per far girare il rilevatore sulla GPU del N100 con
# OpenVINO (serve anche "devices: /dev/dri" nel compose). Di base spento: si usa la CPU.
ARG GPU_INTEL=0

# Le librerie grafiche minime che MediaPipe carica anche senza schermo.
RUN apt-get update \
    && apt-get install -y --no-install-recommends tzdata libglib2.0-0 libgl1 libegl1 libgles2 \
    && if [ "$GPU_INTEL" = "1" ]; then apt-get install -y --no-install-recommends intel-opencl-icd; fi \
    && rm -rf /var/lib/apt/lists/*

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    MPLBACKEND=Agg \
    TZ=Europe/Rome \
    ARGUS_DATI=/data \
    ARGUS_MODELLI=/modelli

WORKDIR /srv/argus

COPY requirements.txt requirements-mediapipe.txt requirements-prove.txt pytest.ini ./
RUN pip install -r requirements.txt && pip install --no-deps -r requirements-mediapipe.txt

COPY argus ./argus
# Le prove viaggiano con l'immagine (pochi KB). Per farle girare:
#   docker exec argus sh -c "pip install -q -r requirements-prove.txt && python -m pytest -q"
COPY tests ./tests

RUN mkdir -p /data /modelli \
    && if [ "$MODELLI_AL_BUILD" = "1" ]; then python -m argus.visione.modelli /modelli; fi

EXPOSE 8700

# python invece di curl: l'immagine slim non ha curl.
HEALTHCHECK --interval=60s --timeout=5s --start-period=60s --retries=3 \
    CMD ["python", "-c", "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://localhost:8700/api/salute', timeout=4).status == 200 else 1)"]

CMD ["python", "-m", "argus"]
