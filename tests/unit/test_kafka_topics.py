from rag_ingestion.infrastructure.kafka_topics import pipeline_topic_specs


def test_pipeline_topic_declarations_include_event_retry_and_dlq_topics() -> None:
    topics = {spec.name: spec for spec in pipeline_topic_specs()}

    assert "rag.ingestion.v1.document.submitted" in topics
    assert "rag.ingestion.v1.document-fetcher.retry" in topics
    assert "rag.ingestion.v1.indexer.dlq" in topics
    assert topics["rag.ingestion.v1.document.submitted"].retention_ms == 7 * 24 * 60 * 60 * 1000
    assert topics["rag.ingestion.v1.document-fetcher.retry"].retention_ms == 24 * 60 * 60 * 1000
