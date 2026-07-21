# Work item: Hybrid storage schema

- Recorded at: 2026-07-21T15:42:27+05:00
- Status: completed

## Prompt

> Generate database script for both postgresql and qdrant as we shall save both dense and sparse vector as we shall use bge-m3 as we intend to search hybrid i.e dense and sparse in one go . please ensure that all typical functional and non functional requirements required for a enterprise RAG are fulfilled following 20-90 rule.

## Outcome

Added the PostgreSQL metadata migration, Qdrant BGE-M3 dense/sparse collection bootstrap script, hybrid retrieval storage contract, and 20–90 enterprise baseline documentation.
