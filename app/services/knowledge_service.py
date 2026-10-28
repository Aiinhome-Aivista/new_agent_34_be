import io
import os
import uuid
import logging
from typing import Dict, Any, List
from backend.app.extensions import db
from backend.app.models.governance import PolicyDocument
from backend.app.services.rag_service import PolicyRAGService

logger = logging.getLogger("fraud_agent.knowledge_service")

class KnowledgeService:
    """Manages company private policy document upload, text extraction, and vector indexing."""

    @classmethod
    def process_and_index_document_stream(
        cls,
        file_bytes: bytes,
        filename: str,
        document_key: str,
        title: str,
        category: str = "GENERAL",
        action_impact: str = "ADVISORY",
        version: str = "1.0",
        description: str = ""
    ):
        """
        Generator that extracts text from document, upserts database record,
        embeds vector chunks into ChromaDB, and yields real-time progress events.
        """
        yield {
            "event": "extracting",
            "status": "PROCESSING",
            "current": 0,
            "total": 100,
            "percent": 10,
            "filename": filename,
            "message": f"Extracting text from {filename}..."
        }

        extracted_text = ""
        ext = os.path.splitext(filename)[1].lower()

        if ext == ".pdf":
            try:
                import pypdf
                reader = pypdf.PdfReader(io.BytesIO(file_bytes))
                pages_text = []
                for p_idx, page in enumerate(reader.pages):
                    t = page.extract_text()
                    if t:
                        pages_text.append(f"--- Page {p_idx+1} ---\n{t.strip()}")
                extracted_text = "\n\n".join(pages_text)
            except Exception as e:
                logger.error(f"PDF extraction failed: {e}")
                raise ValueError(f"Could not read PDF content: {str(e)}")
        else:
            try:
                extracted_text = file_bytes.decode("utf-8", errors="replace").strip()
            except Exception as e:
                raise ValueError(f"Could not decode text file: {str(e)}")

        if not extracted_text:
            raise ValueError("Document appears to be empty or contains no extractable text.")

        yield {
            "event": "saving",
            "status": "PROCESSING",
            "current": 1,
            "total": 100,
            "percent": 25,
            "message": f"Saving policy '{title}' metadata to MySQL governance registry..."
        }

        # 1. Upsert into MySQL PolicyDocument
        doc_key_clean = document_key.strip().upper()
        policy = PolicyDocument.query.filter_by(document_key=doc_key_clean).first()
        if not policy:
            policy = PolicyDocument(
                id=str(uuid.uuid4()),
                document_key=doc_key_clean,
                title=title.strip(),
                version=version.strip(),
                category=category.strip().upper(),
                action_impact=action_impact.strip().upper(),
                description=description.strip() or f"Company policy document imported from {filename}",
                content=extracted_text[:1800],
                status="APPROVED",
                source_reference=filename
            )
            db.session.add(policy)
        else:
            policy.title = title.strip()
            policy.version = version.strip()
            policy.category = category.strip().upper()
            policy.action_impact = action_impact.strip().upper()
            if description:
                policy.description = description.strip()
            policy.content = extracted_text[:1800]
            policy.source_reference = filename

        db.session.commit()

        # 2. Chunk text and index into ChromaDB
        chunks = cls._chunk_text(extracted_text, chunk_size=750, overlap=100)
        total_chunks = len(chunks)
        indexed_chunks = 0

        yield {
            "event": "chunking",
            "status": "PROCESSING",
            "current": 0,
            "total": total_chunks,
            "percent": 35,
            "total_chunks": total_chunks,
            "message": f"Generated {total_chunks} semantic chunks. Vectorizing into ChromaDB..."
        }

        for i, chunk in enumerate(chunks):
            current_num = i + 1
            percent = min(96, round(35 + (current_num / total_chunks) * 60))
            section_name = f"Section_{current_num}"

            success = PolicyRAGService.ingest_policy(
                document_key=doc_key_clean,
                title=title,
                section=section_name,
                text=chunk,
                version=version
            )
            if success:
                indexed_chunks += 1

            yield {
                "event": "indexing",
                "status": "PROCESSING",
                "current": current_num,
                "total": total_chunks,
                "percent": percent,
                "item_id": f"Chunk {current_num}/{total_chunks}",
                "message": f"Vectorized chunk {current_num} of {total_chunks} ({doc_key_clean} - {section_name})..."
            }

        logger.info(f"Knowledge Document {doc_key_clean} ingested: {indexed_chunks}/{total_chunks} chunks indexed in ChromaDB.")

        yield {
            "event": "complete",
            "status": "SUCCESS",
            "document_key": doc_key_clean,
            "title": title,
            "category": category,
            "total_characters": len(extracted_text),
            "chunks_indexed": indexed_chunks,
            "total_chunks": total_chunks,
            "current": total_chunks,
            "total": total_chunks,
            "percent": 100,
            "filename": filename,
            "message": f"Successfully processed and indexed '{title}' ({indexed_chunks} vector chunks in ChromaDB)."
        }

    @classmethod
    def process_and_index_document(
        cls,
        file_bytes: bytes,
        filename: str,
        document_key: str,
        title: str,
        category: str = "GENERAL",
        action_impact: str = "ADVISORY",
        version: str = "1.0",
        description: str = ""
    ) -> Dict[str, Any]:
        """Synchronous wrapper for process_and_index_document_stream."""
        final_res = None
        for step in cls.process_and_index_document_stream(
            file_bytes=file_bytes,
            filename=filename,
            document_key=document_key,
            title=title,
            category=category,
            action_impact=action_impact,
            version=version,
            description=description
        ):
            if step.get("event") == "complete":
                final_res = step

        if final_res:
            return {
                "status": final_res.get("status", "SUCCESS"),
                "document_key": final_res.get("document_key"),
                "title": final_res.get("title"),
                "category": final_res.get("category"),
                "total_characters": final_res.get("total_characters", 0),
                "chunks_indexed": final_res.get("chunks_indexed", 0),
                "filename": final_res.get("filename"),
                "message": final_res.get("message")
            }
        raise ValueError("Document processing failed.")

    @classmethod
    def reindex_all_policies(cls) -> Dict[str, Any]:
        """Reads all policies from MySQL and re-indexes them into ChromaDB vector collection."""
        policies = PolicyDocument.query.all()
        total_chunks = 0
        success_docs = 0

        for pol in policies:
            text_to_index = pol.content or pol.description or pol.title
            chunks = cls._chunk_text(text_to_index, chunk_size=750, overlap=100)
            for i, chunk in enumerate(chunks):
                sec = f"Clause_{i+1}"
                if PolicyRAGService.ingest_policy(pol.document_key, pol.title, sec, chunk, pol.version):
                    total_chunks += 1
            success_docs += 1

        return {
            "status": "SUCCESS",
            "policies_reindexed": success_docs,
            "total_chunks": total_chunks,
            "message": f"Re-indexed {success_docs} policies into vector knowledge store."
        }

    @classmethod
    def _chunk_text(cls, text: str, chunk_size: int = 750, overlap: int = 100) -> List[str]:
        """Simple recursive-friendly text chunker with overlap."""
        if len(text) <= chunk_size:
            return [text]

        chunks = []
        start = 0
        while start < len(text):
            end = start + chunk_size
            chunk = text[start:end]

            # Try to break at newline or space if not at end
            if end < len(text):
                last_space = chunk.rfind(" ")
                last_newline = chunk.rfind("\n")
                break_point = max(last_space, last_newline)
                if break_point > chunk_size // 2:
                    chunk = text[start:start + break_point]
                    end = start + break_point

            cleaned = chunk.strip()
            if cleaned:
                chunks.append(cleaned)
            start = end - overlap

        return chunks
