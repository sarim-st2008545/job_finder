"""Vector store package (Chroma-backed)."""

from .chroma_store import VectorStore, get_store

__all__ = ["VectorStore", "get_store"]
