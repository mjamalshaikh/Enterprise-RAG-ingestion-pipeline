"""Create the declared RAG ingestion Kafka topics if they do not already exist."""

from __future__ import annotations

from rag_ingestion.config.settings import get_settings
from rag_ingestion.infrastructure.kafka_topics import ensure_pipeline_topics


def main() -> None:
    settings = get_settings()
    topics = ensure_pipeline_topics(
        settings.kafka_bootstrap_servers,
        partitions=settings.kafka_topic_partitions,
        replication_factor=settings.kafka_topic_replication_factor,
    )
    print(f"Kafka topics ready: {', '.join(topics)}")


if __name__ == "__main__":
    main()
