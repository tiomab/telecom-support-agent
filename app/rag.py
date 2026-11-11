"""RAG: chunk the knowledge base by headings, embed it into Chroma, search it.

Run `python -m app.ingest` once (and again after editing data/kb/*.md).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import chromadb

from app import config


@dataclass
class Chunk:
    id: str
    text: str
    source: str   # file name, e.g. roaming.md
    section: str  # "Roaming > Travel Pass"


def chunk_markdown(path: Path) -> list[Chunk]:
    """Split one markdown file into chunks, one per `## ` section.

    Each chunk is prefixed with "<doc title> > <section>" so the embedding
    knows the context even when the section text alone is ambiguous.
    """
    text = path.read_text(encoding="utf-8")
    title_match = re.search(r"^# (.+)$", text, re.MULTILINE)
    title = title_match.group(1).strip() if title_match else path.stem

    parts = re.split(r"^## ", text, flags=re.MULTILINE)
    chunks: list[Chunk] = []
    for i, part in enumerate(parts[1:]):  # parts[0] is the title / intro
        heading, _, body = part.partition("\n")
        section = f"{title} > {heading.strip()}"
        body = body.strip()
        if not body:
            continue
        chunks.append(
            Chunk(
                id=f"{path.name}#{i}",
                text=f"{section}\n{body}",
                source=path.name,
                section=section,
            )
        )
    return chunks


def _collection(embedding_function=None, reset: bool = False):
    client = chromadb.PersistentClient(path=str(config.CHROMA_DIR))
    if reset:
        try:
            client.delete_collection(config.COLLECTION)
        except Exception:
            pass
    kwargs = {"metadata": {"hnsw:space": "cosine"}}
    if embedding_function is not None:
        kwargs["embedding_function"] = embedding_function
    return client.get_or_create_collection(config.COLLECTION, **kwargs)


def build_index(embedding_function=None) -> int:
    """(Re)build the vector index from data/kb. Returns the number of chunks."""
    chunks = [c for p in sorted(config.KB_DIR.glob("*.md")) for c in chunk_markdown(p)]
    col = _collection(embedding_function, reset=True)
    col.add(
        ids=[c.id for c in chunks],
        documents=[c.text for c in chunks],
        metadatas=[{"source": c.source, "section": c.section} for c in chunks],
    )
    return len(chunks)


def search(query: str, top_k: int = config.SEARCH_TOP_K, embedding_function=None) -> list[dict]:
    """Return the top_k most similar chunks with source and similarity score."""
    col = _collection(embedding_function)
    res = col.query(query_texts=[query], n_results=top_k)
    hits = []
    for doc, meta, dist in zip(res["documents"][0], res["metadatas"][0], res["distances"][0]):
        hits.append(
            {
                "source": meta["source"],
                "section": meta["section"],
                "score": round(1 - dist, 3),  # cosine similarity
                "text": doc,
            }
        )
    return hits
