"""Container entry point that dispatches an implemented ingestion worker."""

from __future__ import annotations

import argparse
import importlib
import logging
from collections.abc import Callable

from rag_ingestion.config.settings import get_settings
from rag_ingestion.infrastructure.observability import (
    configure_observability,
    shutdown_observability,
)


WORKER_MODULES = {
    "document-fetcher": "rag_ingestion.workers.document_fetcher",
    "content-extractor": "rag_ingestion.workers.content_extractor",
    "chunker": "rag_ingestion.workers.chunker",
    "embedder": "rag_ingestion.workers.embedder",
    "indexer": "rag_ingestion.workers.indexer",
}
logger = logging.getLogger(__name__)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run one RAG ingestion worker stage.")
    parser.add_argument("--worker", choices=sorted(WORKER_MODULES), required=True)
    worker_name = parser.parse_args().worker
    module_name = WORKER_MODULES[worker_name]
    configure_observability(get_settings())

    try:
        module = importlib.import_module(module_name)
        run: Callable[[], None] = module.run
    except (ImportError, AttributeError) as error:
        logger.exception("Unable to start worker '%s': %s", worker_name, error)
        message = (
            f"Worker '{worker_name}' is not implemented. "
            f"Create {module_name}.run() before deploying this container."
        )
        raise SystemExit(message) from error

    try:
        run()
    except Exception as error:
        logger.exception(
            "Worker '%s' stopped because of an unhandled exception: %s", worker_name, error
        )
        raise
    finally:
        shutdown_observability()


if __name__ == "__main__":
    main()
