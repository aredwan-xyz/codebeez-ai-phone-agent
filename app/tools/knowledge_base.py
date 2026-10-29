"""
RAG knowledge base tool.

Stores text chunks in PostgreSQL + a FAISS index for fast semantic search.
Embeddings generated with Anthropic's claude-3-haiku or OpenAI text-embedding-3-small.
"""

from typing import Any

import numpy as np
import structlog

from app.config import get_settings
from app.db.base import AsyncSessionLocal
from app.db.models import KnowledgeChunk
from app.models.call import CallSession
from app.tools.registry import ToolRegistry

log = structlog.get_logger()
settings = get_settings()

_faiss_index = None
_chunk_ids: list[int] = []


async def _get_embedding(text: str) -> list[float]:
    """Generate an embedding using OpenAI (or swap for another provider)."""
    try:
        import openai

        client = openai.AsyncOpenAI()
        resp = await client.embeddings.create(
            model="text-embedding-3-small",
            input=text,
        )
        return resp.data[0].embedding
    except Exception:
        # Fallback: simple TF-IDF-style bag-of-words (no external dependency)
        words = text.lower().split()
        vec = np.zeros(512, dtype=np.float32)
        for w in words:
            idx = hash(w) % 512
            vec[idx] += 1.0
        norm = np.linalg.norm(vec)
        if norm > 0:
            vec /= norm
        return vec.tolist()


async def _load_index():
    """Load FAISS index from DB embeddings on startup."""
    global _faiss_index, _chunk_ids
    try:
        import faiss

        async with AsyncSessionLocal() as db:
            from sqlalchemy import select

            result = await db.execute(select(KnowledgeChunk))
            chunks = result.scalars().all()

        if not chunks:
            return

        embeddings = [c.embedding for c in chunks if c.embedding]
        if not embeddings:
            return

        dim = len(embeddings[0])
        _faiss_index = faiss.IndexFlatL2(dim)
        mat = np.array(embeddings, dtype=np.float32)
        _faiss_index.add(mat)
        _chunk_ids = [c.id for c in chunks if c.embedding]
        log.info("kb.index_loaded", chunks=len(_chunk_ids))
    except Exception as e:
        log.warning("kb.index_load_failed", error=str(e))


@ToolRegistry.register(
    name="search_knowledge_base",
    description=(
        "Search the company knowledge base for relevant information. "
        "Use when the caller asks a question about products, policies, pricing, "
        "hours, or anything factual that you should look up rather than guess."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "The question or topic to search for"},
            "top_k": {
                "type": "integer",
                "default": 3,
                "description": "Number of results to return",
            },
        },
        "required": ["query"],
    },
)
async def search_knowledge_base(args: dict, session: CallSession) -> dict[str, Any]:
    query = args["query"]
    top_k = min(args.get("top_k", 3), 5)

    try:
        if _faiss_index is None:
            await _load_index()

        if _faiss_index is None or len(_chunk_ids) == 0:
            return {"results": [], "note": "Knowledge base is empty"}

        embedding = await _get_embedding(query)
        vec = np.array([embedding], dtype=np.float32)
        distances, indices = _faiss_index.search(vec, top_k)

        async with AsyncSessionLocal() as db:
            from sqlalchemy import select

            matched_ids = [_chunk_ids[i] for i in indices[0] if i < len(_chunk_ids)]
            result = await db.execute(
                select(KnowledgeChunk).where(KnowledgeChunk.id.in_(matched_ids))
            )
            chunks = {c.id: c for c in result.scalars().all()}

        results = []
        for i, idx in enumerate(indices[0]):
            if idx < len(_chunk_ids):
                chunk = chunks.get(_chunk_ids[idx])
                if chunk:
                    results.append(
                        {
                            "content": chunk.content,
                            "source": chunk.source,
                            "relevance_score": float(1 / (1 + distances[0][i])),
                        }
                    )

        return {"results": results, "total": len(results)}
    except Exception as e:
        log.exception("kb.search.error")
        return {"error": str(e)}


async def ingest_document(source: str, content: str):
    """Chunk and embed a document into the knowledge base."""
    chunk_size = 500
    overlap = 50
    words = content.split()
    chunks = []
    i = 0
    while i < len(words):
        chunk = " ".join(words[i : i + chunk_size])
        chunks.append(chunk)
        i += chunk_size - overlap

    async with AsyncSessionLocal() as db:
        for chunk_text in chunks:
            embedding = await _get_embedding(chunk_text)
            record = KnowledgeChunk(source=source, content=chunk_text, embedding=embedding)
            db.add(record)
        await db.commit()

    log.info("kb.ingested", source=source, chunks=len(chunks))
    await _load_index()
