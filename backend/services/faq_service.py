"""
FAQ Service for National University AI Assistant
Manages parsing, indexing, searching, liking, and top-ranking FAQs from FAQ/faq.txt.
"""

import os
import re
import time
import logging
from pathlib import Path
from typing import Optional, List, Dict, Any

from db.sql_store import get_sql_store, SQLStore

logger = logging.getLogger("NU_FAQ_SERVICE")


def clean_category_name(raw: str) -> str:
    """Cleans raw category line into a clean, human-readable category name."""
    s = re.sub(r"\(.*?\)", "", raw).strip()
    s = re.sub(r"^(ক্যাটাগরি|বিষয়|বিভাগ|অধ্যায়)\s*[\d০-৯]+[:\s\-]*", "", s).strip()
    if s.startswith(":"):
        s = s[1:].strip()
    return s.strip() or "সাধারণ তথ্য"


class FAQService:
    def __init__(self, sql_store: Optional[SQLStore] = None):
        self.sql_store = sql_store or get_sql_store()
        self.base_dir = Path(__file__).resolve().parent.parent.parent
        self.faq_file_path = self.base_dir / "FAQ" / "faq.txt"

    def parse_faq_file(self, file_path: Optional[Path] = None) -> List[Dict[str, Any]]:
        target_path = file_path or self.faq_file_path
        if not target_path.exists():
            logger.warning(f"FAQ file not found at: {target_path}")
            return []

        content = target_path.read_text(encoding="utf-8")
        lines = content.splitlines()

        entries: List[Dict[str, Any]] = []
        current_cat = "সাধারণ তথ্য"
        current_q = None
        current_a_lines = []

        q_re = re.compile(r"^\s*(\d+|[০-৯]+)\.\s*প্রশ্ন\s*:\s*(.*)", re.IGNORECASE)
        a_re = re.compile(r"^\s*উত্তর\s*:\s*(.*)", re.IGNORECASE)

        for line in lines:
            line_s = line.strip()
            if line_s.startswith(("ক্যাটাগরি", "বিষয়:", "বিভাগ:")):
                if current_q and current_a_lines:
                    ans = "\n".join(current_a_lines).strip()
                    if ans:
                        entries.append({
                            "category": current_cat,
                            "question": current_q,
                            "answer": ans
                        })
                    current_q = None
                    current_a_lines = []
                current_cat = clean_category_name(line_s)
                continue

            m_q = q_re.match(line)
            if m_q:
                if current_q and current_a_lines:
                    ans = "\n".join(current_a_lines).strip()
                    if ans:
                        entries.append({
                            "category": current_cat,
                            "question": current_q,
                            "answer": ans
                        })
                current_q = m_q.group(2).strip()
                current_a_lines = []
                continue

            m_a = a_re.match(line)
            if m_a:
                current_a_lines.append(m_a.group(1).strip())
                continue

            if current_q and current_a_lines:
                current_a_lines.append(line)

        if current_q and current_a_lines:
            ans = "\n".join(current_a_lines).strip()
            if ans:
                entries.append({
                    "category": current_cat,
                    "question": current_q,
                    "answer": ans
                })

        logger.info(f"Parsed {len(entries)} valid FAQs from {target_path.name}")
        return entries

    def sync_from_file(self, file_path: Optional[Path] = None, force: bool = False) -> Dict[str, Any]:
        """
        Synchronizes all FAQs into SQLite faq_entries idempotently.
        Preserves existing user like counts.
        """
        target_path = file_path or self.faq_file_path
        parsed_entries = self.parse_faq_file(target_path)
        if not parsed_entries:
            return {"status": "error", "message": "No FAQ entries found to sync.", "synced": 0}

        synced_count = 0
        categories_seen = set()

        for idx, entry in enumerate(parsed_entries, 1):
            cat = entry["category"]
            q = entry["question"]
            a = entry["answer"]
            categories_seen.add(cat)

            source_key = f"faq_{idx:04d}"
            # Extract keywords from question & category
            tokens = [t for t in re.split(r"[\s,;()\"'.-]+", f"{q} {cat}") if len(t) > 2]
            keywords = " ".join(dict.fromkeys(tokens))

            self.sql_store.upsert_faq_record(
                question=q,
                answer=a,
                category=cat,
                source_key=source_key,
                keywords=keywords,
                source_file="FAQ/faq.txt",
                is_active=1
            )
            synced_count += 1

        logger.info(f"Successfully synced {synced_count} FAQs across {len(categories_seen)} categories.")
        return {
            "status": "success",
            "synced": synced_count,
            "categories_count": len(categories_seen),
            "source_file": str(target_path)
        }

    def ensure_seeded(self) -> None:
        """Seeds the database with FAQs on startup if empty or below threshold."""
        try:
            with self.sql_store._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT COUNT(*) as cnt FROM faq_entries WHERE is_active = 1")
                row = cursor.fetchone()
                cnt = row["cnt"] if row else 0

            if cnt < 500:
                logger.info(f"FAQ store has {cnt} entries (< 500 threshold). Running seed import...")
                self.sync_from_file()
            else:
                logger.info(f"FAQ store already populated with {cnt} active entries.")
        except Exception as e:
            logger.error(f"Error ensuring FAQ seeding: {e}", exc_info=True)

    def list_faqs(
        self,
        category: Optional[str] = None,
        search: Optional[str] = None,
        sort: str = "most_liked",
        limit: int = 30,
        offset: int = 0,
        session_id: Optional[str] = None
    ) -> Dict[str, Any]:
        return self.sql_store.list_faqs(
            category=category,
            search=search,
            sort=sort,
            limit=limit,
            offset=offset,
            session_id=session_id
        )

    def get_top_liked(self, limit: int = 10, session_id: Optional[str] = None) -> List[Dict[str, Any]]:
        return self.sql_store.get_top_liked_faqs(limit=limit, session_id=session_id)

    def get_by_id(self, faq_id: int, session_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
        return self.sql_store.get_faq_by_id(faq_id=faq_id, session_id=session_id)

    def toggle_like(self, faq_id: int, session_id: str) -> Dict[str, Any]:
        if not session_id or not session_id.strip():
            session_id = "anonymous_session"
        return self.sql_store.toggle_faq_like(faq_id=faq_id, session_id=session_id.strip())

    def get_categories(self) -> List[Dict[str, Any]]:
        return self.sql_store.get_faq_categories()

    def find_similar_faq(self, question: str, threshold: float = 0.70) -> Optional[Dict[str, Any]]:
        """
        Checks if a given question is identical or highly similar to an existing active FAQ.
        Uses normalized token overlap and difflib SequenceMatcher.
        Returns the most similar FAQ dictionary with a 'similarity' score [0.0 - 1.0], or None.
        """
        import difflib
        q_clean = re.sub(r"[^\w\s\u0980-\u09FF]", " ", question.lower()).strip()
        q_tokens = set(q_clean.split())
        if not q_clean:
            return None

        best_match = None
        best_score = 0.0

        with self.sql_store._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT id, question, answer, category, likes_count FROM faq_entries WHERE is_active = 1")
            rows = cursor.fetchall()

            for row in rows:
                existing_q = row["question"]
                ex_clean = re.sub(r"[^\w\s\u0980-\u09FF]", " ", existing_q.lower()).strip()
                if not ex_clean:
                    continue

                # Exact normalized match
                if q_clean == ex_clean:
                    res = dict(row)
                    res["similarity"] = 1.0
                    return res

                # SequenceMatcher ratio
                seq_ratio = difflib.SequenceMatcher(None, q_clean, ex_clean).ratio()

                # Jaccard word token similarity
                ex_tokens = set(ex_clean.split())
                intersection = q_tokens.intersection(ex_tokens)
                union = q_tokens.union(ex_tokens)
                jaccard = (len(intersection) / len(union)) if union else 0.0

                # Weighted combined score
                score = max(seq_ratio, 0.5 * seq_ratio + 0.5 * jaccard)

                if score > best_score:
                    best_score = score
                    best_match = dict(row)
                    best_match["similarity"] = round(best_score, 3)

        if best_match and best_score >= threshold:
            return best_match
        return None

    def add_faq_entry(
        self,
        question: str,
        answer: str,
        category: str = "সাধারণ তথ্য",
        keywords: Optional[str] = "",
        force: bool = False,
        admin_user: str = "Admin"
    ) -> Dict[str, Any]:
        """
        Inserts a new verified FAQ into SQLite faq_entries.
        Checks for duplicates or similar questions unless force=True.
        Also indexes the new FAQ in ChromaDB vector store if available.
        """
        q_str = (question or "").strip()
        a_str = (answer or "").strip()
        c_str = clean_category_name(category)

        if not q_str:
            return {"status": "error", "message": "Question cannot be empty."}
        if not a_str:
            return {"status": "error", "message": "Answer cannot be empty."}

        # Check for similar existing FAQ
        if not force:
            similar = self.find_similar_faq(q_str, threshold=0.72)
            if similar:
                return {
                    "status": "similar_exists",
                    "message": f"সদৃশ বা কাছাকাছি প্রশ্ন ডাটাবেজে ইতোমধ্যে বিদ্যমান রয়েছে ({int(similar['similarity']*100)}% মিল): '{similar['question']}'",
                    "similar_faq": similar
                }

        # Generate tokens / keywords if empty
        if not keywords:
            tokens = [t for t in re.split(r"[\s,;()\"'.-]+", f"{q_str} {c_str}") if len(t) > 2]
            kw_str = " ".join(dict.fromkeys(tokens))
        else:
            kw_str = keywords.strip()

        source_key = f"admin_faq_{int(time.time())}_{abs(hash(q_str)) % 10000}"
        source_hash = self.sql_store.compute_hash(f"{q_str}|{a_str}")

        faq_id = self.sql_store.upsert_faq_record(
            question=q_str,
            answer=a_str,
            category=c_str,
            source_key=source_key,
            keywords=kw_str,
            source_file="Admin Entry Portal",
            source_hash=source_hash,
            is_active=1
        )

        # Index in vector store for AI Counselor retrieval
        try:
            from db.vector_store import get_vector_store
            from langchain_core.documents import Document
            vstore = get_vector_store()
            if vstore:
                doc = Document(
                    page_content=f"প্রশ্ন: {q_str}\nউত্তর: {a_str}",
                    metadata={"source": "admin_faq_entry", "category": c_str, "faq_id": str(faq_id)}
                )
                vstore.split_and_add_documents([doc])
        except Exception as e:
            logger.warning(f"Vector store indexing skipped for FAQ #{faq_id}: {e}")

        logger.info(f"Admin FAQ added successfully! ID: #{faq_id}, Category: {c_str}")
        return {
            "status": "success",
            "message": "প্রশ্নোত্তর সফলভাবে ডাটাবেজে যুক্ত ও ইনডেক্স করা হয়েছে!",
            "faq_id": faq_id,
            "question": q_str,
            "category": c_str
        }

    def update_faq_entry(
        self,
        faq_id: int,
        question: str,
        answer: str,
        category: str = "সাধারণ তথ্য",
        keywords: Optional[str] = "",
        admin_user: str = "Admin"
    ) -> Dict[str, Any]:
        """Updates an existing FAQ entry in SQLite faq_entries."""
        q_str = (question or "").strip()
        a_str = (answer or "").strip()
        c_str = clean_category_name(category)
        if not q_str:
            return {"status": "error", "message": "Question cannot be empty."}
        if not a_str:
            return {"status": "error", "message": "Answer cannot be empty."}

        if not keywords:
            tokens = [t for t in re.split(r"[\s,;()\"'.-]+", f"{q_str} {c_str}") if len(t) > 2]
            kw_str = " ".join(dict.fromkeys(tokens))
        else:
            kw_str = keywords.strip()

        updated = self.sql_store.update_faq_record(
            faq_id=faq_id,
            question=q_str,
            answer=a_str,
            category=c_str,
            keywords=kw_str
        )
        if not updated:
            return {"status": "error", "message": f"FAQ #{faq_id} not found."}

        logger.info(f"Admin FAQ #{faq_id} updated by {admin_user}. Category: {c_str}")
        return {
            "status": "success",
            "message": f"প্রশ্নোত্তর (#{faq_id}) সফলভাবে আপডেট করা হয়েছে!",
            "faq_id": faq_id,
            "question": q_str,
            "answer": a_str,
            "category": c_str,
            "keywords": kw_str
        }

    def delete_faq_entry(self, faq_id: int, admin_user: str = "Admin") -> Dict[str, Any]:
        """Deletes an FAQ entry by ID from SQLite faq_entries."""
        deleted = self.sql_store.delete_faq_record(faq_id)
        if not deleted:
            return {"status": "error", "message": f"FAQ #{faq_id} not found."}
        logger.info(f"Admin FAQ #{faq_id} deleted by {admin_user}.")
        return {
            "status": "success",
            "message": f"প্রশ্নোত্তর (#{faq_id}) সফলভাবে মুছে ফেলা হয়েছে!",
            "faq_id": faq_id
        }

    def list_admin_faqs_categorywise(
        self,
        category: Optional[str] = None,
        search: Optional[str] = None,
        only_duplicates: bool = False
    ) -> Dict[str, Any]:
        """
        Lists all active FAQs grouped category-wise, with duplicate question detection.
        Marks questions that are exact normalized matches or >= 0.86 similarity as duplicates.
        """
        import difflib
        all_res = self.sql_store.list_faqs(category=None, search=None, sort="latest", limit=2000, offset=0)
        all_items = all_res.get("items", [])

        # Normalize questions & detect duplicates across the entire FAQ set
        norm_map: Dict[str, list[dict[str, Any]]] = {}
        by_cat_clean: Dict[str, list[tuple[dict[str, Any], str]]] = {}
        for item in all_items:
            q_norm = re.sub(r"[?？।!.,;:\"'()\[\]\s]+", " ", (item.get("question") or "").strip().lower()).strip()
            item["is_duplicate"] = False
            item["duplicate_ids"] = []
            norm_map.setdefault(q_norm, []).append(item)
            cat_key = item.get("category") or "সাধারণ তথ্য"
            by_cat_clean.setdefault(cat_key, []).append((item, q_norm))

        # 1. Exact normalized text duplicates (across all categories)
        for q_norm, group in norm_map.items():
            if q_norm and len(group) > 1:
                ids = [g["id"] for g in group]
                for g in group:
                    g["is_duplicate"] = True
                    g["duplicate_ids"] = [i for i in ids if i != g["id"]]

        # 2. Fast high-similarity (>= 0.86) near-duplicates within each category
        for cat_key, cat_list in by_cat_clean.items():
            n = len(cat_list)
            for i in range(n):
                item_i, q_i = cat_list[i]
                if not q_i:
                    continue
                len_i = len(q_i)
                for j in range(i + 1, n):
                    item_j, q_j = cat_list[j]
                    if not q_j or q_i == q_j or abs(len_i - len(q_j)) > 15:
                        continue
                    ratio = difflib.SequenceMatcher(None, q_i, q_j).ratio()
                    if ratio >= 0.86:
                        item_i["is_duplicate"] = True
                        item_j["is_duplicate"] = True
                        if item_j["id"] not in item_i["duplicate_ids"]:
                            item_i["duplicate_ids"].append(item_j["id"])
                        if item_i["id"] not in item_j["duplicate_ids"]:
                            item_j["duplicate_ids"].append(item_i["id"])

        duplicates_total = sum(1 for item in all_items if item.get("is_duplicate"))

        # Compute category counts on all items
        cat_counts: Dict[str, int] = {}
        for item in all_items:
            c = item.get("category") or "সাধারণ তথ্য"
            cat_counts[c] = cat_counts.get(c, 0) + 1

        # Apply filters
        filtered: list[dict[str, Any]] = []
        cat_filter = (category or "").strip()
        search_filter = (search or "").strip().lower()

        for item in all_items:
            if cat_filter and cat_filter.lower() != "all" and item.get("category") != cat_filter:
                continue
            if only_duplicates and not item.get("is_duplicate"):
                continue
            if search_filter:
                haystack = f"{item.get('question', '')} {item.get('answer', '')} {item.get('category', '')} {item.get('keywords', '')}".lower()
                if search_filter not in haystack:
                    continue
            filtered.append(item)

        # Group filtered items by category
        by_category: Dict[str, list[dict[str, Any]]] = {}
        for item in filtered:
            c = item.get("category") or "সাধারণ তথ্য"
            by_category.setdefault(c, []).append(item)

        categories_summary = [{"category": k, "count": v} for k, v in sorted(cat_counts.items(), key=lambda x: (-x[1], x[0]))]

        return {
            "status": "success",
            "total": len(filtered),
            "total_all": len(all_items),
            "duplicates_count": duplicates_total,
            "categories": categories_summary,
            "by_category": by_category,
            "items": filtered
        }


# Singleton factory
_faq_service_instance: Optional[FAQService] = None

def get_faq_service() -> FAQService:
    global _faq_service_instance
    if _faq_service_instance is None:
        _faq_service_instance = FAQService()
    return _faq_service_instance
