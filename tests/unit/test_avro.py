from rag_ingestion.infrastructure.avro import AvroSerializer


SCHEMA = {
    "type": "record",
    "name": "Event",
    "fields": [{"name": "event_id", "type": "string"}],
}


def test_serializer_round_trips_a_local_avro_contract() -> None:
    serializer = AvroSerializer(SCHEMA)

    assert serializer.deserialize(serializer.serialize({"event_id": "evt-1"})) == {
        "event_id": "evt-1"
    }
