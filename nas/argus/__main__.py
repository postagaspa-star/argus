"""Avvio: python -m argus  (server sulla porta 8700)."""

from __future__ import annotations

import logging
import os

import uvicorn


def main() -> None:
    logging.basicConfig(level=os.environ.get("ARGUS_LOG", "INFO"),
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    uvicorn.run("argus.api:crea_app", factory=True, host="0.0.0.0",
                port=int(os.environ.get("ARGUS_PORTA", "8700")), log_level="warning", access_log=False)


if __name__ == "__main__":
    main()
