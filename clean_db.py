#!/usr/bin/env python3
"""
FraudOps AI — Database & Vector Store Cleanup Utility
=====================================================
Cleans all investigation cases, evidence, audit logs, orders, payments,
and resets the ChromaDB vector database while strictly preserving:
  - m_users & users (master & source domain user records)
  - app_users (login personas: Admin, Senior Investigator, Supervisor, Auditor)
  - fraud_parameters (fraud detection thresholds across all 6 sections)
"""

import os
import sys
import argparse
from pathlib import Path

# Ensure workspace root and backend are in sys.path
root_dir = str(Path(__file__).resolve().parent)
if root_dir not in sys.path:
    sys.path.insert(0, root_dir)
parent_dir = str(Path(__file__).resolve().parent.parent)
if parent_dir not in sys.path:
    sys.path.insert(0, parent_dir)

from sqlalchemy import text
try:
    from app import create_app
    from app.extensions import db
    from app.config import Config
except ImportError:
    from backend.app import create_app
    from backend.app.extensions import db
    from backend.app.config import Config

import chromadb
from chromadb.config import Settings


# ANSI Colors for terminal output
GREEN = "\033[92m"
YELLOW = "\033[93m"
RED = "\033[91m"
BLUE = "\033[94m"
CYAN = "\033[96m"
BOLD = "\033[1m"
RESET = "\033[0m"


def print_banner():
    print(f"\n{BOLD}{CYAN}================================================================================={RESET}")
    print(f"{BOLD}{CYAN}      🧹 FraudOps AI — Database & Vector DB Cleanup Utility                      {RESET}")
    print(f"{BOLD}{CYAN}================================================================================={RESET}")
    print(f"{YELLOW}• Preserves:{RESET}  {BOLD}m_users{RESET}, {BOLD}users{RESET}, {BOLD}app_users{RESET} (login personas), {BOLD}fraud_parameters{RESET}")
    print(f"{RED}• Cleans:{RESET}     Cases, Evidence, Runs, Recommendations, Audits, Orders, Payments")
    print(f"{BLUE}• Vector DB:{RESET}  ChromaDB collection '{Config.CHROMA_COLLECTION_NAME}'\n")


def clean_database(keep_standard_sops: bool = True, reindex_sops: bool = False):
    app = create_app()

    # Tables to completely clean (ordered child-to-parent)
    CLEAN_TABLES = [
        "recommendation_evidence",
        "recommendations",
        "investigation_runs",
        "case_evidence",
        "action_requests",
        "review_decisions",
        "audit_events",
        "investigation_cases",
        "m_chargebacks",
        "m_payments",
        "m_orders",
        "chargebacks",
        "payments",
        "orders",
    ]

    # Tables that MUST NEVER be deleted
    PRESERVED_TABLES = [
        ("m_users", "Master Domain Users (m_users)"),
        ("users", "Customer & Merchant Domain Users"),
        ("app_users", "System Personas / Login Accounts"),
        ("fraud_parameters", "Detection Parameter Thresholds (6 Sections)"),
    ]

    report = []

    with app.app_context():
        print(f"{BOLD}[1/3] Inspecting MySQL Database ({Config.MYSQL_DB})...{RESET}")

        # Record counts before
        counts_before = {}
        for tbl in CLEAN_TABLES:
            try:
                cnt = db.session.execute(text(f"SELECT COUNT(*) FROM `{tbl}`")).scalar()
                counts_before[tbl] = cnt
            except Exception:
                counts_before[tbl] = 0

        # Policy documents handling
        policy_cnt_before = 0
        try:
            policy_cnt_before = db.session.execute(text("SELECT COUNT(*) FROM `policy_documents`")).scalar()
        except Exception:
            pass

        print(f"  Found {sum(counts_before.values())} investigation/transaction records to clean.")

        print(f"\n{BOLD}[2/3] Cleaning MySQL Database Tables...{RESET}")
        try:
            # Disable foreign key checks for safe truncation/deletion
            db.session.execute(text("SET FOREIGN_KEY_CHECKS = 0;"))

            for tbl in CLEAN_TABLES:
                cnt_before = counts_before.get(tbl, 0)
                try:
                    db.session.execute(text(f"TRUNCATE TABLE `{tbl}`;"))
                    db.session.commit()
                    cnt_after = db.session.execute(text(f"SELECT COUNT(*) FROM `{tbl}`;")).scalar()
                    print(f"  {GREEN}✔{RESET} Truncated table {BOLD}`{tbl}`{RESET} (Deleted: {cnt_before}, Remaining: {cnt_after})")
                    report.append((tbl, cnt_before, cnt_before, cnt_after, "CLEANED"))
                except Exception:
                    # Fallback to DELETE FROM if TRUNCATE fails
                    db.session.execute(text(f"DELETE FROM `{tbl}`;"))
                    db.session.commit()
                    cnt_after = db.session.execute(text(f"SELECT COUNT(*) FROM `{tbl}`;")).scalar()
                    print(f"  {GREEN}✔{RESET} Deleted from {BOLD}`{tbl}`{RESET} (Deleted: {cnt_before - cnt_after}, Remaining: {cnt_after})")
                    report.append((tbl, cnt_before, cnt_before - cnt_after, cnt_after, "CLEANED"))

            # Handle policy_documents
            if keep_standard_sops:
                try:
                    deleted_custom = db.session.execute(
                        text("DELETE FROM `policy_documents` WHERE `document_key` NOT IN ('FRAUD_SOP_01', 'FRAUD_SOP_02', 'FRAUD_SOP_03', 'FRAUD_SOP_04', 'FRAUD_SOP_05')")
                    ).rowcount
                    db.session.commit()
                    policy_cnt_after = db.session.execute(text("SELECT COUNT(*) FROM `policy_documents`")).scalar()
                    print(f"  {GREEN}✔{RESET} Cleaned custom uploads from {BOLD}`policy_documents`{RESET} (Deleted: {deleted_custom}, Preserved 5 SOPs: {policy_cnt_after})")
                    report.append(("policy_documents (Custom Docs)", policy_cnt_before, deleted_custom, policy_cnt_after, "CUSTOM REMOVED"))
                except Exception as e:
                    print(f"  {YELLOW}⚠{RESET} policy_documents handling notice: {e}")
            else:
                db.session.execute(text("TRUNCATE TABLE `policy_documents`;"))
                db.session.commit()
                report.append(("policy_documents", policy_cnt_before, policy_cnt_before, 0, "CLEANED"))
                print(f"  {GREEN}✔{RESET} Truncated {BOLD}`policy_documents`{RESET}")

            # Re-enable foreign key checks
            db.session.execute(text("SET FOREIGN_KEY_CHECKS = 1;"))
            db.session.commit()

        except Exception as e:
            db.session.rollback()
            print(f"  {RED}✘ Error during MySQL cleanup: {e}{RESET}")
            try:
                db.session.execute(text("SET FOREIGN_KEY_CHECKS = 1;"))
                db.session.commit()
            except Exception:
                pass
            raise e

        # Report Preserved Tables
        print(f"\n{BOLD}Verifying Preserved Tables (Untouched):{RESET}")
        for tbl, desc in PRESERVED_TABLES:
            try:
                cnt = db.session.execute(text(f"SELECT COUNT(*) FROM `{tbl}`")).scalar()
                print(f"  {CYAN}★{RESET} {BOLD}`{tbl}`{RESET} ({desc}): {BOLD}{cnt} records intact{RESET}")
                report.append((f"{tbl} (PRESERVED)", cnt, 0, cnt, "PRESERVED"))
            except Exception as e:
                print(f"  {YELLOW}⚠{RESET} Could not inspect `{tbl}`: {e}")

    # =========================================================================
    # ChromaDB Vector Store Cleanup
    # =========================================================================
    print(f"\n{BOLD}[3/3] Cleaning ChromaDB Vector Store ({Config.CHROMA_PERSIST_DIRECTORY})...{RESET}")
    chroma_before = 0
    chroma_after = 0
    try:
        os.makedirs(Config.CHROMA_PERSIST_DIRECTORY, exist_ok=True)
        client = chromadb.PersistentClient(
            path=Config.CHROMA_PERSIST_DIRECTORY,
            settings=Settings(anonymized_telemetry=False)
        )

        try:
            collection = client.get_collection(name=Config.CHROMA_COLLECTION_NAME)
            chroma_before = collection.count()
            print(f"  Found collection `{Config.CHROMA_COLLECTION_NAME}` with {chroma_before} vector embeddings.")
            client.delete_collection(name=Config.CHROMA_COLLECTION_NAME)
            print(f"  {GREEN}✔{RESET} Deleted ChromaDB collection `{Config.CHROMA_COLLECTION_NAME}`.")
        except Exception:
            print(f"  Collection `{Config.CHROMA_COLLECTION_NAME}` was not found or was already empty.")

        new_col = client.create_collection(
            name=Config.CHROMA_COLLECTION_NAME,
            metadata={"description": "Approved organizational policies for fraud investigation"}
        )
        chroma_after = new_col.count()
        print(f"  {GREEN}✔{RESET} Re-created fresh empty collection `{Config.CHROMA_COLLECTION_NAME}` (Vectors: {chroma_after})")
        report.append(("ChromaDB Vector Embeddings", chroma_before, chroma_before, chroma_after, "CLEANED"))

        if reindex_sops:
            print(f"\n  {CYAN}Re-indexing 5 standard SOP policies into ChromaDB...{RESET}")
            from app.services.seed_data import seed_default_sop_policies
            with app.app_context():
                seed_default_sop_policies()
                from app.services.rag_service import PolicyRAGService
                from app.models.governance import PolicyDocument
                sops = PolicyDocument.query.all()
                for p in sops:
                    PolicyRAGService.ingest_policy(
                        document_key=p.document_key,
                        title=p.title,
                        section=p.category or "General",
                        text=p.content or p.description or p.title,
                        version=p.version or "1.0"
                    )
                fresh_count = new_col.count()
                print(f"  {GREEN}✔{RESET} Indexed {fresh_count} standard SOP vectors into ChromaDB.")

    except Exception as e:
        print(f"  {RED}✘ ChromaDB cleanup error: {e}{RESET}")
        report.append(("ChromaDB Vector Embeddings", chroma_before, 0, chroma_before, f"ERROR: {e}"))

    # =========================================================================
    # Final Pretty Summary Table
    # =========================================================================
    print(f"\n{BOLD}{CYAN}================================================================================={RESET}")
    print(f"{BOLD}{CYAN}                          CLEANUP EXECUTION SUMMARY                               {RESET}")
    print(f"{BOLD}{CYAN}================================================================================={RESET}")
    print(f"{'Target Table / Resource':<35} {'Before':<10} {'Deleted':<10} {'Remaining':<10} {'Status':<15}")
    print("-" * 81)

    for item, b, d, r, status in report:
        if status == "CLEANED":
            st_color = GREEN
        elif status == "PRESERVED":
            st_color = CYAN
        elif "REMOVED" in status:
            st_color = YELLOW
        else:
            st_color = RED

        print(f"{item:<35} {str(b):<10} {str(d):<10} {str(r):<10} {st_color}{status:<15}{RESET}")

    print("=" * 81)
    print(f"{BOLD}{GREEN}✔ Cleanup completed successfully!{RESET}\n")


def main():
    parser = argparse.ArgumentParser(
        description="Clean MySQL database tables and ChromaDB vector store while preserving users and fraud parameters."
    )
    parser.add_argument("--yes", "-y", action="store_true", help="Skip confirmation prompt.")
    parser.add_argument("--clean-all-sops", action="store_true", help="Also delete the 5 standard company SOPs.")
    parser.add_argument("--reindex-sops", action="store_true", help="Re-index standard SOPs into ChromaDB.")

    args = parser.parse_args()
    print_banner()

    if not args.yes:
        try:
            confirm = input(f"{BOLD}Are you sure you want to clean cases, evidence, audits, and vectors? (y/N): {RESET}").strip().lower()
            if confirm not in ("y", "yes"):
                print(f"{YELLOW}Operation cancelled by user.{RESET}")
                sys.exit(0)
        except (KeyboardInterrupt, EOFError):
            print(f"\n{YELLOW}Operation cancelled.{RESET}")
            sys.exit(0)

    clean_database(
        keep_standard_sops=not args.clean_all_sops,
        reindex_sops=args.reindex_sops
    )


if __name__ == "__main__":
    main()
