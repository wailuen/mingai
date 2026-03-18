"""
Shared test fixtures for pgvector search tests.

Imported by both unit and integration test files.
Uses 1536-dim embeddings matching EMBEDDING_MODEL=text-embedding-3-small.
"""
import hashlib
import random
import uuid


def make_embedding(seed: int | None = None) -> list[float]:
    """Generate a random 1536-dim embedding (text-embedding-3-small compatible)."""
    rng = random.Random(seed)
    return [rng.uniform(-1, 1) for _ in range(1536)]


def make_chunk(
    tenant_id: str,
    index_id: str,
    chunk_key: str | None = None,
    content: str = "test content",
    title: str = "test title",
    source_type: str = "sharepoint",
    source_file_id: str = "file1.txt",
    embedding: list[float] | None = None,
    content_hash: str | None = None,
    user_id: str | None = None,
    conversation_id: str | None = None,
) -> dict:
    key = chunk_key or f"{index_id}_{source_file_id}_{uuid.uuid4().hex[:8]}"
    return {
        "chunk_key": key,
        "tenant_id": tenant_id,
        "index_id": index_id,
        "source_type": source_type,
        "user_id": user_id,
        "conversation_id": conversation_id,
        "integration_id": None,
        "content": content,
        "title": title,
        "source_url": None,
        "file_name": source_file_id,
        "file_type": "txt",
        "chunk_type": "text",
        "chunk_index": 0,
        "source_file_id": source_file_id,
        "content_hash": content_hash or hashlib.sha256(content.encode()).hexdigest(),
        "etag": None,
        "source_modified_at": None,
        "file_size_bytes": None,
        "embedding": embedding or make_embedding(),
    }
