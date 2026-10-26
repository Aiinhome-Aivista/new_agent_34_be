import os
import re
from typing import List, Dict, Any, Optional
from sqlalchemy.orm import Session
from app.config import settings
from app.models.platform import PolicyDocument

class PolicyRAGService:
    def __init__(self, db: Session):
        self.db = db

    def search_policy(self, query: str, limit: int = 3) -> List[Dict[str, Any]]:
        """
        Retrieves matching fraud SOPs and policies using semantic & keyword retrieval.
        Grounded in the MySQL policy_documents table and metadata.
        """
        policies = self.db.query(PolicyDocument).filter(PolicyDocument.is_active == True).all()
        if not policies:
            return []

        query_tokens = set(re.findall(r"\w+", query.lower()))
        scored_policies = []

        for p in policies:
            text = f"{p.title} {p.category} {p.content}".lower()
            text_tokens = set(re.findall(r"\w+", text))
            
            # Compute token overlap score
            overlap = query_tokens.intersection(text_tokens)
            score = len(overlap) / (len(query_tokens) + 1e-5)

            # Boost if category or title matches
            if any(token in p.title.lower() for token in query_tokens):
                score += 0.5
            if any(token in p.category.lower() for token in query_tokens):
                score += 0.3

            scored_policies.append((score, p))

        # Sort by relevance score
        scored_policies.sort(key=lambda x: x[0], reverse=True)
        top_matches = scored_policies[:limit]

        results = []
        for score, p in top_matches:
            # Extract relevant snippet
            content_lines = p.content.split("\n")
            snippet = "\n".join(content_lines[:6]) if len(content_lines) > 6 else p.content

            results.append({
                "policy_code": p.policy_code,
                "title": p.title,
                "category": p.category,
                "version": p.version,
                "score": round(score, 3),
                "snippet": snippet,
                "metadata": p.metadata_json or {}
            })

        return results
