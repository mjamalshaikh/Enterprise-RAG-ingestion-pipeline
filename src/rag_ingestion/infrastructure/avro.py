"""Local Avro encoding for versioned, checked-in event contracts."""

from __future__ import annotations

from io import BytesIO
from typing import Any

from fastavro import parse_schema, schemaless_reader, schemaless_writer


class AvroSerializer:
    """Encode one known event contract without an external schema registry."""

    def __init__(self, schema: dict[str, Any]) -> None:
        self._schema = parse_schema(schema)

    def serialize(self, record: dict[str, Any]) -> bytes:
        buffer = BytesIO()
        schemaless_writer(buffer, self._schema, record)
        return buffer.getvalue()

    def deserialize(self, payload: bytes) -> dict[str, Any]:
        return schemaless_reader(BytesIO(payload), self._schema)
