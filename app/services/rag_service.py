import os
import logging
from typing import List, Dict, Any, Optional
import chromadb
from chromadb.config import Settings
from app.config import Config

logger = logging.getLogger("fraud_agent.rag_service")

class PolicyRAGService:
    """Manages policy indexing and retrieval via ChromaDB."""

    _client = None
    _collection = None

    @classmethod
    def get_collection(cls):
        """Initializes and returns the ChromaDB collection."""
        if cls._collection is not None:
            return cls._collection

        try:
            os.makedirs(Config.CHROMA_PERSIST_DIRECTORY, exist_ok=True)
            cls._client = chromadb.PersistentClient(
                path=Config.CHROMA_PERSIST_DIRECTORY,
                settings=Settings(anonymized_telemetry=False)
            )
            cls._collection = cls._client.get_or_create_collection(
                name=Config.CHROMA_COLLECTION_NAME,
                metadata={"description": "Approved organizational policies for fraud investigation"}
            )
            logger.info("ChromaDB policy collection initialized successfully.")
            return cls._collection
        except Exception as e:
            logger.warning(f"ChromaDB initialization failed: {e}. Policy RAG marked unavailable.")
            return None

    @classmethod
    def retrieve_policies(cls, query: str, top_k: int = 3) -> Dict[str, Any]:
        """
        Retrieves relevant approved policy passages for a given query.
        Returns status ('AVAILABLE', 'EMPTY', 'UNAVAILABLE') and matching passages with citations.
        """
        collection = cls.get_collection()
        if collection is None:
            return {
                "status": "UNAVAILABLE",
                "message": "ChromaDB vector store is currently unreachable.",
                "passages": []
            }

        count = collection.count()
        if count == 0:
            return {
                "status": "EMPTY",
                "message": "Policy index is empty. No policy documents have been ingested yet.",
                "passages": []
            }

        try:
            results = collection.query(
                query_texts=[query],
                n_results=min(top_k, count),
                include=["documents", "metadatas", "distances"]
            )
            
            passages = []
            if results and "documents" in results and results["documents"]:
                docs = results["documents"][0]
                metas = results["metadatas"][0] if "metadatas" in results else [{}] * len(docs)
                for doc, meta in zip(docs, metas):
                    passages.append({
                        "text": doc,
                        "document_key": meta.get("document_key", "UNKNOWN_POLICY"),
                        "title": meta.get("title", "Standard Operating Procedure"),
                        "section": meta.get("section", "General"),
                        "version": meta.get("version", "1.0"),
                        "effective_date": meta.get("effective_date", "2026-01-01")
                    })

            return {
                "status": "AVAILABLE",
                "message": f"Successfully retrieved {len(passages)} policy passage(s).",
                "passages": passages
            }
        except Exception as e:
            logger.error(f"Error querying ChromaDB: {e}")
            return {
                "status": "FAILED",
                "message": f"Policy query error: {str(e)}",
                "passages": []
            }

    @classmethod
    def ingest_policy(cls, document_key: str, title: str, section: str, text: str, version: str = "1.0") -> bool:
        """Indexes an approved policy excerpt into ChromaDB with explicit metadata."""
        collection = cls.get_collection()
        if collection is None:
            return False

        doc_id = f"{document_key}_{section.lower().replace(' ', '_')}_{version}"
        try:
            collection.upsert(
                ids=[doc_id],
                documents=[text],
                metadatas=[{
                    "document_key": document_key,
                    "title": title,
                    "section": section,
                    "version": version
                }]
            )
            return True
        except Exception as e:
            logger.error(f"Failed to ingest policy into ChromaDB: {e}")
            return False
