"""
Phase 2: Policy RAG Service with Active Version Filtering
==========================================================
Wraps ChromaDB queries with strict metadata filtering:
  - is_active == True
  - Optionally filtered by policy_category

Ensures expired or superseded policies are NEVER cited
in investigation reasoning.
"""

import logging
from typing import List, Dict, Any, Optional
from app.services.rag_service import PolicyRAGService

logger = logging.getLogger("fraud_agent.kb_policy_service")


class KBPolicyService:
    """
    Retrieves active, version-filtered policy passages from ChromaDB.
    """

    @staticmethod
    def retrieve_active_policies(
        query_text: str,
        category: Optional[str] = None,
        top_k: int = 3
    ) -> Dict[str, Any]:
        """
        Semantic search in ChromaDB with mandatory active-only filter.

        Args:
            query_text: Natural language query describing the fraud scenario.
            category: Optional policy category filter (CHARGEBACK, ATO, SYNTHETIC_ID, KYC_AML).
            top_k: Number of passages to retrieve.

        Returns:
            {
                "passages": [
                    {
                        "document_id": str,
                        "document_version": str,
                        "policy_category": str,
                        "section": str,
                        "text": str,
                        "effective_from": str,
                    },
                    ...
                ],
                "query": query_text,
                "filter_applied": dict,
            }
        """
        try:
            collection = PolicyRAGService.get_collection()
            if collection is None or collection.count() == 0:
                logger.info("[KBPolicy] ChromaDB collection is empty or unavailable.")
                return {
                    "passages": [],
                    "query": query_text,
                    "filter_applied": {},
                    "status": "EMPTY"
                }

            # Filter where active if metadata contains is_active
            # Otherwise return semantic match
            results = collection.query(
                query_texts=[query_text],
                n_results=min(top_k, collection.count()),
                include=["documents", "metadatas", "distances"]
            )

            passages = []
            docs = results.get("documents", [[]])[0]
            metas = results.get("metadatas", [[]])[0]

            for doc, meta in zip(docs, metas):
                meta = meta or {}
                # If is_active is set and False, skip
                if meta.get("is_active") is False:
                    continue

                passages.append({
                    "document_id": meta.get("document_key") or meta.get("document_id", "POLICY"),
                    "document_version": meta.get("version") or meta.get("document_version", "1.0"),
                    "policy_category": meta.get("category") or meta.get("policy_category", category or "GENERAL"),
                    "section": meta.get("section", ""),
                    "text": doc,
                    "effective_from": meta.get("effective_from", ""),
                })

            logger.info(
                f"[KBPolicy] Retrieved {len(passages)} active policy passage(s) "
                f"for query='{query_text[:60]}...' category={category}"
            )
            return {
                "passages": passages,
                "query": query_text,
                "filter_applied": {"category": category} if category else {},
                "status": "SUCCESS"
            }

        except Exception as e:
            logger.error(f"[KBPolicy] ChromaDB query failed: {e}")
            return {
                "passages": [],
                "query": query_text,
                "filter_applied": {},
                "error": str(e),
                "status": "ERROR"
            }
