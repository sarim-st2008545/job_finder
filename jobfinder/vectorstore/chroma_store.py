"""Local persistent Chroma vector store with sentence-transformers embeddings.

If `chromadb` / `sentence-transformers` aren't installed the store gracefully
no-ops, so the rest of the pipeline keeps working in minimal installs.
"""

from __future__ import annotations

import logging
from functools import lru_cache
from typing import Any, Iterable

from ..config import get_settings

logger = logging.getLogger(__name__)


class VectorStore:
    def __init__(self, persist_dir: str, embedding_model: str) -> None:
        self.persist_dir = persist_dir
        self.embedding_model = embedding_model
        self._client = None
        self._embedder = None
        self._available = False
        try:
            import chromadb

            self._client = chromadb.PersistentClient(path=persist_dir)
            self._available = True
        except Exception as e:
            logger.warning("Chroma unavailable (%s). Vector ops will no-op.", e)

    # ---- embeddings ----

    def _embed(self, texts: list[str]) -> list[list[float]] | None:
        if not self._available:
            return None
        if self._embedder is None:
            try:
                from sentence_transformers import SentenceTransformer

                self._embedder = SentenceTransformer(self.embedding_model)
            except Exception as e:
                logger.warning(
                    "sentence-transformers unavailable (%s). Skipping embeddings.", e
                )
                self._available = False
                return None
        vecs = self._embedder.encode(texts, normalize_embeddings=True).tolist()
        return vecs

    # ---- public API ----

    def add(
        self,
        collection: str,
        ids: list[str],
        documents: list[str],
        metadatas: list[dict[str, Any]] | None = None,
    ) -> None:
        if not self._available:
            return
        embeddings = self._embed(documents)
        if embeddings is None:
            return
        col = self._client.get_or_create_collection(collection)
        col.upsert(
            ids=ids,
            documents=documents,
            metadatas=metadatas or [{} for _ in ids],
            embeddings=embeddings,
        )

    def query(
        self, collection: str, query_text: str, n_results: int = 5
    ) -> list[dict[str, Any]]:
        if not self._available:
            return []
        try:
            col = self._client.get_collection(collection)
        except Exception:
            return []
        embeddings = self._embed([query_text])
        if embeddings is None:
            return []
        res = col.query(query_embeddings=embeddings, n_results=n_results)
        out: list[dict[str, Any]] = []
        for i, _id in enumerate(res.get("ids", [[]])[0]):
            out.append(
                {
                    "id": _id,
                    "document": res["documents"][0][i],
                    "metadata": (res.get("metadatas") or [[{}]])[0][i],
                    "distance": (res.get("distances") or [[None]])[0][i],
                }
            )
        return out


@lru_cache(maxsize=1)
def get_store() -> VectorStore:
    s = get_settings()
    return VectorStore(
        persist_dir=str(s.paths.vector_store_dir),
        embedding_model=s.embedding_model,
    )
