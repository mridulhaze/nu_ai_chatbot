import json
import logging
from typing import List, Optional, Dict, Any
from datetime import datetime
from fastapi import APIRouter, HTTPException, Depends, Query

from backend.core.security import get_current_user_required, get_current_user_optional, require_roles, Role
from backend.models.schemas import (
    TokenAdminDetail,
    TokenAssignRequest,
    TokenStatusUpdateRequest,
    TokenSolveRequest, TokenReturnRequest,
    SolverSchema,
    ServiceTypeSchema
)
from backend.services.token_service import get_token_domain_service
from token_service.db import get_token_db_connection

logger = logging.getLogger("NU_ADMIN_API")
router = APIRouter(prefix="/api/v1/admin", tags=["Admin & Solver Operations"])

@router.get("/dashboard-stats")
def get_dashboard_statistics(user: dict = Depends(get_current_user_required)):
    conn = get_token_db_connection()
    try:
        total = conn.execute("SELECT COUNT(*) as c FROM token_requests").fetchone()["c"]
        pending = conn.execute("SELECT COUNT(*) as c FROM token_requests WHERE status = 'PENDING'").fetchone()["c"]
        assigned = conn.execute("SELECT COUNT(*) as c FROM token_requests WHERE status = 'ASSIGNED'").fetchone()["c"]
        processing = conn.execute("SELECT COUNT(*) as c FROM token_requests WHERE status = 'PROCESSING'").fetchone()["c"]
        solved = conn.execute("SELECT COUNT(*) as c FROM token_requests WHERE status = 'SOLVED'").fetchone()["c"]
        closed = conn.execute("SELECT COUNT(*) as c FROM token_requests WHERE status = 'CLOSED'").fetchone()["c"]
        rejected = conn.execute("SELECT COUNT(*) as c FROM token_requests WHERE status = 'REJECTED'").fetchone()["c"]

        # Solved today
        today_str = datetime.utcnow().strftime("%Y-%m-%d")
        solved_today = conn.execute("SELECT COUNT(*) as c FROM token_requests WHERE status = 'SOLVED' AND solved_date LIKE ?", (f"{today_str}%",)).fetchone()["c"]

        return {
            "total_tokens": total,
            "pending": pending,
            "assigned": assigned,
            "processing": processing,
            "solved": solved,
            "closed": closed,
            "rejected": rejected,
            "solved_today": solved_today
        }
    finally:
        conn.close()

@router.get("/tokens", response_model=List[TokenAdminDetail])
def list_admin_tokens(
    status: Optional[str] = Query(None),
    service_type: Optional[str] = Query(None),
    solver_id: Optional[int] = Query(None),
    limit: int = Query(100, ge=1, le=500),
    user: dict = Depends(get_current_user_required)
):
    service = get_token_domain_service()
    conn = get_token_db_connection()
    try:
        query = "SELECT token_id FROM token_requests WHERE 1=1"
        params = []

        user_role = user.get("role", "USER")
        if user_role == "SOLVER":
            user_dept = (user.get("department") or "").strip()
            user_full_name = (user.get("full_name") or "").strip()

            s_rows = conn.execute("""
                SELECT id, solver_name FROM token_solvers
                WHERE solver_name = ? OR department = ? OR solver_name LIKE ? OR department LIKE ?
            """, (user_dept, user_dept, f"%{user_dept}%", f"%{user_dept}%")).fetchall()
            s_ids = [r["id"] for r in s_rows]
            s_names = list(set([r["solver_name"] for r in s_rows] + [user_dept, user_full_name]))

            conds = []
            if s_ids:
                seq = ','.join(['?'] * len(s_ids))
                conds.append(f"solver_id IN ({seq})")
                params.extend(s_ids)
            if s_names:
                nseq = ','.join(['?'] * len(s_names))
                conds.append(f"solver_name IN ({nseq})")
                params.extend(s_names)
            if user_dept:
                conds.append("solver_name LIKE ?")
                params.append(f"%{user_dept}%")

            if conds:
                query += f" AND ({' OR '.join(conds)})"
            else:
                query += " AND 1=0"

        if status:
            query += " AND status = ?"
            params.append(status.upper())
        if service_type:
            query += " AND service_type = ?"
            params.append(service_type.upper())
        if solver_id:
            query += " AND solver_id = ?"
            params.append(solver_id)

        query += " ORDER BY id DESC LIMIT ?"
        params.append(limit)

        cur = conn.execute(query, params)
        token_ids = [r["token_id"] for r in cur.fetchall()]

        results = []
        for tid in token_ids:
            detail = service.get_admin_token_detail(tid)
            if detail:
                results.append(detail)
        return results
    finally:
        conn.close()

@router.get("/tokens/{token_id}", response_model=TokenAdminDetail)
def get_token_admin_detail(token_id: str, user: dict = Depends(get_current_user_required)):
    service = get_token_domain_service()
    detail = service.get_admin_token_detail(token_id.strip().upper())
    if not detail:
        raise HTTPException(status_code=404, detail=f"Token {token_id} not found.")
    return detail

@router.post("/tokens/{token_id}/assign")
def assign_token_solver(
    token_id: str,
    payload: TokenAssignRequest,
    user: dict = Depends(require_roles([Role.ADMIN, Role.SUPER_ADMIN]))
):
    service = get_token_domain_service()
    ok, msg = service.assign_solver(
        token_id=token_id.strip().upper(),
        solver_id=payload.solver_id,
        changed_by=user.get("username", "ADMIN"),
        admin_note=payload.admin_note
    )
    if not ok:
        raise HTTPException(status_code=400, detail=msg)
    return {"success": True, "message": msg}

@router.post("/tokens/{token_id}/status")
def update_token_status_endpoint(
    token_id: str,
    payload: TokenStatusUpdateRequest,
    user: dict = Depends(require_roles([Role.SOLVER, Role.ADMIN, Role.SUPER_ADMIN]))
):
    service = get_token_domain_service()
    ok, msg = service.update_status(
        token_id=token_id.strip().upper(),
        new_status=payload.status,
        changed_by=user.get("username", "ADMIN"),
        message=payload.message,
        admin_note=payload.admin_note
    )
    if not ok:
        raise HTTPException(status_code=400, detail=msg)
    return {"success": True, "message": msg}

@router.post("/tokens/{token_id}/return-to-admin")
def return_token_to_admin_endpoint(
    token_id: str,
    payload: TokenReturnRequest,
    user: dict = Depends(require_roles([Role.SOLVER, Role.ADMIN, Role.SUPER_ADMIN]))
):
    service = get_token_domain_service()
    solver_name = payload.solver_name or user.get("full_name") or user.get("username")
    reason = payload.reason or payload.return_reason or "Returned to admin"
    ok, msg = service.return_to_admin(
        token_id=token_id.strip().upper(),
        reason=reason,
        solver_name=solver_name,
        changed_by=user.get("username", "SOLVER")
    )
    if not ok:
        raise HTTPException(status_code=400, detail=msg)
    return {"success": True, "message": msg}

@router.post("/tokens/{token_id}/solve")
def solve_token_endpoint(
    token_id: str,
    payload: TokenSolveRequest,
    user: dict = Depends(require_roles([Role.SOLVER, Role.ADMIN, Role.SUPER_ADMIN]))
):
    service = get_token_domain_service()
    solver_name = payload.solver_name or user.get("full_name") or user.get("username")
    ok, msg = service.solve_token(
        token_id=token_id.strip().upper(),
        solve_message=payload.solve_message,
        solver_name=solver_name,
        changed_by=user.get("username", "SOLVER"),
        admin_note=payload.admin_note
    )
    if not ok:
        raise HTTPException(status_code=400, detail=msg)
    return {"success": True, "message": msg}

@router.get("/audit-logs")
def view_audit_logs(
    limit: int = Query(50, ge=1, le=200),
    user: dict = Depends(require_roles([Role.ADMIN, Role.SUPER_ADMIN]))
):
    conn = get_token_db_connection()
    try:
        cur = conn.execute("""
            SELECT id, timestamp, action, username, role, resource_type, resource_id, success, details_json
            FROM audit_logs
            ORDER BY id DESC
            LIMIT ?
        """, (limit,))
        return [dict(r) for r in cur.fetchall()]
    finally:
        conn.close()

# --- User & Department Solver Management Endpoints ---

from pydantic import BaseModel
from backend.core.security import hash_password

class AdminCreateUserRequest(BaseModel):
    username: str
    password: str
    email: Optional[str] = None
    full_name: Optional[str] = None
    department: Optional[str] = None
    role: str = "SOLVER"

class AdminUpdatePasswordRequest(BaseModel):
    new_password: str

@router.get("/users")
def list_system_users(user: dict = Depends(require_roles([Role.ADMIN, Role.SUPER_ADMIN]))):
    conn = get_token_db_connection()
    try:
        cur = conn.execute("""
            SELECT id, username, email, full_name, department, role, active, created_at
            FROM users
            ORDER BY id ASC
        """)
        return [dict(r) for r in cur.fetchall()]
    finally:
        conn.close()

@router.post("/users")
def create_system_user(payload: AdminCreateUserRequest, user: dict = Depends(require_roles([Role.ADMIN, Role.SUPER_ADMIN]))):
    conn = get_token_db_connection()
    try:
        cur = conn.execute("SELECT id FROM users WHERE username = ?", (payload.username.strip(),))
        if cur.fetchone():
            raise HTTPException(status_code=400, detail=f"Username '{payload.username}' already exists.")

        pwd_hash = hash_password(payload.password)
        now_str = datetime.utcnow().isoformat()
        role = payload.role.upper() if payload.role.upper() in ["ADMIN", "SOLVER", "EXAM_ENTRY", "USER", "SUPER_ADMIN"] else "SOLVER"

        with conn:
            cur = conn.execute("""
                INSERT INTO users (username, email, password_hash, full_name, department, role, active, created_at)
                VALUES (?, ?, ?, ?, ?, ?, 1, ?)
            """, (payload.username.strip(), payload.email, pwd_hash, payload.full_name, payload.department, role, now_str))
            new_id = cur.lastrowid

            # If department solver, ensure solver team row exists in token_solvers
            if role == "SOLVER" and payload.department:
                sol_cur = conn.execute("SELECT id FROM token_solvers WHERE solver_name = ? OR department = ?", (payload.full_name or payload.username, payload.department))
                if not sol_cur.fetchone():
                    conn.execute("""
                        INSERT INTO token_solvers (solver_name, department, email, phone, active)
                        VALUES (?, ?, ?, '+88029291000', 1)
                    """, (payload.full_name or payload.username, payload.department, payload.email))

        return {"success": True, "id": new_id, "username": payload.username, "message": f"User {payload.username} created successfully."}
    finally:
        conn.close()

@router.put("/users/{user_id}/status")
def toggle_user_active_status(user_id: int, user: dict = Depends(require_roles([Role.ADMIN, Role.SUPER_ADMIN]))):
    conn = get_token_db_connection()
    try:
        cur = conn.execute("SELECT id, active, username FROM users WHERE id = ?", (user_id,))
        row = cur.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="User not found.")
        new_status = 0 if row["active"] else 1
        with conn:
            conn.execute("UPDATE users SET active = ? WHERE id = ?", (new_status, user_id))
        return {"success": True, "active": bool(new_status), "message": f"User status updated."}
    finally:
        conn.close()

@router.put("/users/{user_id}/password")
def admin_reset_user_password(user_id: int, payload: AdminUpdatePasswordRequest, user: dict = Depends(require_roles([Role.ADMIN, Role.SUPER_ADMIN]))):
    if len(payload.new_password) < 4:
        raise HTTPException(status_code=400, detail="Password must be at least 4 characters.")
    conn = get_token_db_connection()
    try:
        cur = conn.execute("SELECT id FROM users WHERE id = ?", (user_id,))
        if not cur.fetchone():
            raise HTTPException(status_code=404, detail="User not found.")
        pwd_hash = hash_password(payload.new_password)
        with conn:
            conn.execute("UPDATE users SET password_hash = ? WHERE id = ?", (pwd_hash, user_id))
        return {"success": True, "message": "Password reset successfully."}
    finally:
        conn.close()

@router.delete("/users/{user_id}")
def delete_system_user(user_id: int, user: dict = Depends(require_roles([Role.SUPER_ADMIN]))):
    conn = get_token_db_connection()
    try:
        cur = conn.execute("SELECT username FROM users WHERE id = ?", (user_id,))
        row = cur.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="User not found.")
        if row["username"] == "admin":
            raise HTTPException(status_code=400, detail="Cannot delete default superadmin account.")
        with conn:
            conn.execute("DELETE FROM users WHERE id = ?", (user_id,))
        return {"success": True, "message": f"User {row['username']} deleted successfully."}
    finally:
        conn.close()

# --- Crawler MCP & Website Map Admin Endpoints ---

from mcp_servers.crawler_mcp import get_crawler_mcp_server

@router.get("/crawler/website-map")
def admin_get_website_map(user: dict = Depends(require_roles([Role.SOLVER, Role.ADMIN, Role.SUPER_ADMIN]))):
    server = get_crawler_mcp_server()
    return server.get_website_map()

@router.get("/crawler/stats")
def admin_get_crawler_stats(user: dict = Depends(require_roles([Role.SOLVER, Role.ADMIN, Role.SUPER_ADMIN]))):
    server = get_crawler_mcp_server()
    return server.get_crawl_statistics()

@router.post("/crawler/pause")
def admin_pause_crawler(user: dict = Depends(require_roles([Role.SOLVER, Role.ADMIN, Role.SUPER_ADMIN]))):
    server = get_crawler_mcp_server()
    return server.pause_crawl()

@router.post("/crawler/resume")
def admin_resume_crawler(user: dict = Depends(require_roles([Role.SOLVER, Role.ADMIN, Role.SUPER_ADMIN]))):
    server = get_crawler_mcp_server()
    return server.resume_crawl()

@router.post("/crawler/stop")
def admin_stop_crawler(user: dict = Depends(require_roles([Role.SOLVER, Role.ADMIN, Role.SUPER_ADMIN]))):
    server = get_crawler_mcp_server()
    return server.stop_crawl()

@router.post("/crawler/retry-failed")
def admin_retry_crawler_failed(user: dict = Depends(require_roles([Role.SOLVER, Role.ADMIN, Role.SUPER_ADMIN]))):
    server = get_crawler_mcp_server()
    return server.retry_failed_urls()

# --- System Activity, Service Logs & Report Export Endpoints ---

from fastapi import Response
from backend.services.activity_tracker import get_activity_tracker
from backend.services.report_exporter import get_report_exporter

@router.get("/logs/summary")
def get_system_logs_summary(user: dict = Depends(get_current_user_required)):
    """Returns aggregated system metrics: services provided, barcodes generated, tokens solved/processed/pending."""
    tracker = get_activity_tracker()
    return tracker.get_summary_metrics()

@router.get("/logs/records")
def get_system_log_records(
    event_type: Optional[str] = Query(None),
    service_code: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    search: Optional[str] = Query(None),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    user: dict = Depends(get_current_user_required)
):
    """Fetches paginated tabular audit & activity logs."""
    tracker = get_activity_tracker()
    return tracker.get_activity_records(
        event_type=event_type,
        service_code=service_code,
        status=status,
        search=search,
        limit=limit,
        offset=offset
    )

@router.get("/logs/export/excel")
def export_system_activity_excel(user: dict = Depends(get_current_user_required)):
    """Generates and downloads a multi-sheet formatted Excel report (.xlsx)."""
    exporter = get_report_exporter()
    excel_bytes = exporter.generate_excel_report()
    filename = f"NU_System_Activity_Report_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.xlsx"
    return Response(
        content=excel_bytes,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename={filename}"}
    )

@router.get("/logs/export/pdf")
def export_system_activity_pdf(user: dict = Depends(get_current_user_required)):
    """Generates and downloads an executive PDF audit report (.pdf)."""
    exporter = get_report_exporter()
    pdf_bytes = exporter.generate_pdf_report()
    filename = f"NU_System_Activity_Report_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.pdf"
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f"attachment; filename={filename}"}
    )

@router.post("/activity/record-qr")
def record_qr_generation_event(payload: Dict[str, Any] = None):
    """Logs a QR/Barcode generation event."""
    tracker = get_activity_tracker()
    tracker.record_event(
        event_type="BARCODE_GENERATED",
        service_code="MOBILE_QR",
        user_identifier=(payload or {}).get("identifier", "STUDENT_MOBILE"),
        details="Generated QR/Barcode for mobile instant chat and token tracking",
        status="SUCCESS"
    )
    return {"success": True, "message": "QR generation recorded"}



from fastapi.responses import FileResponse
from fastapi import UploadFile, File
from backend.services.backup_service import get_backup_service

@router.get("/backup/list", summary="List all system backups")
def get_backup_list(user: dict = Depends(get_current_user_required)):
    if user.get("role") not in ["SUPER_ADMIN", "ADMIN"]:
        raise HTTPException(status_code=403, detail="Permission denied.")
    backup_svc = get_backup_service()
    return {"success": True, "backups": backup_svc.list_backups()}

@router.post("/backup/create", summary="Generate portable full system backup ZIP")
def create_system_backup(user: dict = Depends(get_current_user_required)):
    if user.get("role") not in ["SUPER_ADMIN", "ADMIN"]:
        raise HTTPException(status_code=403, detail="Permission denied.")
    backup_svc = get_backup_service()
    backup_path, meta = backup_svc.create_backup()
    return FileResponse(
        path=str(backup_path),
        filename=backup_path.name,
        media_type="application/zip"
    )

@router.post("/backup/restore", summary="Restore full system from uploaded backup ZIP")
async def restore_system_backup(file: UploadFile = File(...), user: dict = Depends(get_current_user_required)):
    if user.get("role") != "SUPER_ADMIN":
        raise HTTPException(status_code=403, detail="Only SUPER_ADMIN can perform full system restore.")
    
    if not file.filename.endswith(".zip"):
        raise HTTPException(status_code=400, detail="Invalid file type. Please upload a valid .zip backup archive.")

    content = await file.read()
    backup_svc = get_backup_service()
    try:
        res = backup_svc.restore_backup(content, filename=file.filename)
        return res
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# --- Hermes Agent Interactive Learning Brain Admin Endpoints ---
from backend.services.hermes_brain_service import get_hermes_brain

@router.get("/hermes/status", summary="Get Hermes Learning Brain status")
def get_hermes_brain_status(user: dict = Depends(get_current_user_required)):
    brain = get_hermes_brain()
    return brain.get_brain_status()

@router.post("/hermes/trigger-cycle", summary="Trigger autonomous Hermes learning cycle")
def trigger_hermes_learning_cycle(limit: int = 25, user: dict = Depends(get_current_user_required)):
    brain = get_hermes_brain()
    return brain.run_interactive_learning_cycle(limit_gaps=limit)

@router.post("/hermes/resolve-gap/{gap_id}", summary="Auto-resolve single knowledge gap with Hermes")
def hermes_resolve_gap(gap_id: int, user: dict = Depends(get_current_user_required)):
    brain = get_hermes_brain()
    return brain.auto_resolve_gap(gap_id)

@router.post("/hermes/extract-notice/{notice_id}", summary="Extract structured FAQs from notice with Hermes")
def hermes_extract_notice_faqs(notice_id: int, user: dict = Depends(get_current_user_required)):
    brain = get_hermes_brain()
    return brain.extract_notice_faqs(notice_id)

@router.get("/hermes/suggest-solution/{token_id}", summary="Solver Co-Pilot solution recommendation")
def hermes_suggest_token_solution(token_id: str, user: dict = Depends(get_current_user_required)):
    brain = get_hermes_brain()
    return brain.suggest_token_solution(token_id)

# --- Many-to-Many Knowledge Base Q&A Management Endpoints ---
from db.sql_store import get_sql_store
from backend.models.schemas import QAKnowledgeCreateRequest

@router.get("/qa-knowledge", summary="Get all Many-to-Many Q&A Knowledge records")
def list_qa_knowledge(limit: int = 100, user: dict = Depends(get_current_user_required)):
    sql_store = get_sql_store()
    records = sql_store.get_all_qa_knowledge(limit=limit)
    return {"status": "success", "count": len(records), "data": records}

@router.post("/qa-knowledge", summary="Create a new Many-to-Many Q&A record")
def create_qa_knowledge(payload: QAKnowledgeCreateRequest, user: dict = Depends(get_current_user_required)):
    if not payload.primary_question.strip():
        raise HTTPException(status_code=400, detail="Primary question cannot be empty.")
    if not payload.answer_variants:
        raise HTTPException(status_code=400, detail="At least one answer must be provided.")

    sql_store = get_sql_store()
    qa_id = sql_store.insert_qa_knowledge(
        primary_question=payload.primary_question,
        category=payload.category,
        tags=payload.tags or "",
        question_variants=payload.question_variants,
        answer_variants=[{"answer_text": ans, "is_primary": (1 if i == 0 else 0), "language": "bn"} for i, ans in enumerate(payload.answer_variants)]
    )

    # Ingest into vector store if available
    try:
        from db.vector_store import get_vector_store
        vstore = get_vector_store()
        if vstore:
            # Index all question variants + primary answer
            for q_var in payload.question_variants + [payload.primary_question]:
                if q_var.strip():
                    vstore.add_documents(
                        texts=[f"প্রশ্ন: {q_var.strip()}\nউত্তর: {payload.answer_variants[0]}"],
                        metadatas=[{"source": "admin_qa_knowledge", "category": payload.category, "qa_id": qa_id}],
                        ids=[f"admin_qa_{qa_id}_{abs(hash(q_var)) % 100000}"]
                    )
    except Exception as e:
        logger.warning(f"Vector indexing for Q&A {qa_id} skipped: {e}")

    return {
        "status": "success",
        "message": "Many-to-Many Q&A knowledge created and indexed successfully!",
        "qa_id": qa_id
    }

@router.delete("/qa-knowledge/{qa_id}", summary="Delete a Many-to-Many Q&A record")
def delete_qa_knowledge_endpoint(qa_id: int, user: dict = Depends(get_current_user_required)):
    sql_store = get_sql_store()
    deleted = sql_store.delete_qa_knowledge(qa_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Q&A entry not found.")
    return {"status": "success", "message": f"Q&A record {qa_id} deleted successfully."}

@router.post("/sync-and-maintain", summary="One-click asynchronous knowledge synchronization and maintenance")
def trigger_sync_and_maintain(user: dict = Depends(get_current_user_required)):
    """
    Executes a comprehensive, non-destructive maintenance workflow:
    1. Validates database connection & schema
    2. Runs incremental crawl of official notice source & portals
    3. Content-hash deduplicates and vector-indexes only new/changed items
    4. Runs consistency check and status reporting
    """
    from crawler.scheduler import run_full_crawl, get_crawler_status
    import threading

    state = get_crawler_status()
    if state.get("is_running"):
        return {
            "status": "in_progress",
            "message": "A knowledge synchronization job is already actively running.",
            "last_run": state.get("last_run"),
            "state": state
        }

    def _sync_worker():
        try:
            logger.info("Executing Admin One-Click Sync & Maintain Knowledge workflow...")
            result = run_full_crawl()
            logger.info(f"Sync & Maintain Knowledge completed: {result.get('status')}")
        except Exception as e_sync:
            logger.error(f"Error during Sync & Maintain Knowledge: {e_sync}", exc_info=True)

    threading.Thread(target=_sync_worker, daemon=True, name="NU_Admin_SyncMaintain_Worker").start()

    return {
        "status": "started",
        "message": "Knowledge sync and maintenance workflow initiated in the background.",
        "initiated_at": datetime.utcnow().isoformat() + "Z"
    }

@router.get("/sync-status", summary="Get status of knowledge synchronization and maintenance")
def get_sync_maintenance_status(user: dict = Depends(get_current_user_required)):
    from crawler.scheduler import get_crawler_status
    state = get_crawler_status()
    sql_store = get_sql_store()
    recent_notices_count = len(sql_store.get_recent_notices(limit=1000))
    return {
        "status": "success",
        "crawler_state": state,
        "indexed_notices_count": recent_notices_count,
        "scheduler_interval_minutes": 30
    }

# --- Academic Examination Information Management Admin Endpoints ---
from backend.models.schemas import (
    AcademicExamCreateUpdateRequest, AcademicExamResponse,
    AcademicStaticInfoRequest, AcademicStaticInfoResponse
)

@router.get("/academic-exams", summary="List academic examination records with filtering and pagination")
def list_admin_academic_exams(
    program_type: Optional[str] = Query(None, description="Honours, Degree Pass, Master's, Professional"),
    examination_year: Optional[str] = Query(None, description="e.g. 2024, 2025"),
    part: Optional[str] = Query(None, description="Part 1, Part 2, Part 3, Part 4, or N/A"),
    semester: Optional[str] = Query(None, description="Semester 1 through 8, or N/A"),
    course_name: Optional[str] = Query(None, description="e.g. CSE, BBA"),
    results_published: Optional[str] = Query(None, description="Yes / No"),
    search: Optional[str] = Query(None, description="Search by year, exam date, or remarks"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    user: dict = Depends(get_current_user_required)
):
    sql_store = get_sql_store()
    items, total = sql_store.list_academic_exam_info(
        program_type=program_type,
        examination_year=examination_year,
        part=part,
        semester=semester,
        course_name=course_name,
        results_published=results_published,
        search=search,
        limit=limit,
        offset=offset
    )
    return {
        "status": "success",
        "total": total,
        "count": len(items),
        "limit": limit,
        "offset": offset,
        "data": items
    }

@router.get("/academic-exams/{record_id}", summary="Get single academic examination record by ID")
def get_admin_academic_exam(
    record_id: int,
    user: dict = Depends(get_current_user_required)
):
    sql_store = get_sql_store()
    item = sql_store.get_academic_exam_info_by_id(record_id)
    if not item:
        raise HTTPException(status_code=404, detail=f"Academic examination record #{record_id} not found.")
    return {"status": "success", "data": item}

@router.post("/academic-exams", summary="Create or update an academic examination record")
def create_or_update_academic_exam(
    payload: AcademicExamCreateUpdateRequest,
    user: dict = Depends(require_roles([Role.EXAM_ENTRY, Role.ADMIN, Role.SUPER_ADMIN]))
):
    username = user.get("username", "Admin")
    sql_store = get_sql_store()
    saved = sql_store.upsert_academic_exam_info(payload.dict(), user_name=username)
    return {
        "status": "success",
        "message": f"Successfully saved examination record for {payload.program_type} ({payload.part}) - {payload.examination_year}.",
        "data": saved
    }

@router.put("/academic-exams/{record_id}", summary="Update an existing academic examination record")
def update_admin_academic_exam(
    record_id: int,
    payload: AcademicExamCreateUpdateRequest,
    user: dict = Depends(require_roles([Role.EXAM_ENTRY, Role.ADMIN, Role.SUPER_ADMIN]))
):
    sql_store = get_sql_store()
    existing = sql_store.get_academic_exam_info_by_id(record_id)
    if not existing:
        raise HTTPException(status_code=404, detail=f"Record #{record_id} not found.")

    username = user.get("username", "Admin")
    data = payload.dict()
    saved = sql_store.upsert_academic_exam_info(data, user_name=username)
    return {
        "status": "success",
        "message": f"Successfully updated record #{record_id}.",
        "data": saved
    }

@router.delete("/academic-exams/{record_id}", summary="Delete an academic examination record")
def delete_admin_academic_exam(
    record_id: int,
    user: dict = Depends(require_roles([Role.EXAM_ENTRY, Role.ADMIN, Role.SUPER_ADMIN]))
):
    sql_store = get_sql_store()
    deleted = sql_store.delete_academic_exam_info(record_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Record not found.")
    return {"status": "success", "message": f"Record #{record_id} deleted successfully."}

# --- Legacy Static Info Routes (Maintained for Backward Compatibility) ---
@router.get("/academic-static", summary="List academic examination & result static schedules")
def list_academic_static(
    program_type: Optional[str] = Query(None, description="Honours, Degree Pass, Master's, Professional"),
    user: dict = Depends(get_current_user_required)
):
    sql_store = get_sql_store()
    items = sql_store.list_academic_static_info(program_type=program_type)
    return {"status": "success", "count": len(items), "data": items}

@router.get("/academic-static/{program_type}/{part_or_year}", summary="Get single static schedule")
def get_academic_static(
    program_type: str,
    part_or_year: str,
    user: dict = Depends(get_current_user_required)
):
    sql_store = get_sql_store()
    item = sql_store.get_academic_static_info(program_type=program_type, part_or_year=part_or_year)
    if not item:
        raise HTTPException(status_code=404, detail="Schedule record not found.")
    return {"status": "success", "data": item}

@router.post("/academic-static", summary="Create or update static academic exam & result info")
def upsert_academic_static(
    payload: AcademicStaticInfoRequest,
    user: dict = Depends(require_roles([Role.EXAM_ENTRY, Role.ADMIN, Role.SUPER_ADMIN]))
):
    sql_store = get_sql_store()
    saved = sql_store.upsert_academic_exam_info(payload.dict(), user_name=user.get("username", "Admin"))
    return {
        "status": "success",
        "message": f"Successfully updated schedule for {payload.program_type} ({payload.part_or_year}).",
        "data": saved
    }

@router.delete("/academic-static/{entry_id}", summary="Delete academic schedule entry")
def delete_academic_static(entry_id: int, user: dict = Depends(require_roles([Role.EXAM_ENTRY, Role.ADMIN, Role.SUPER_ADMIN]))):
    sql_store = get_sql_store()
    deleted = sql_store.delete_academic_exam_info(entry_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Entry not found.")
    return {"status": "success", "message": f"Deleted entry {entry_id}."}


# --- Admin FAQ Question & Answer Input Management Endpoints ---
from backend.services.faq_service import get_faq_service

class AdminCreateFAQRequest(BaseModel):
    question: str
    answer: str
    category: Optional[str] = "সাধারণ তথ্য"
    keywords: Optional[str] = ""
    force: Optional[bool] = False

@router.post("/faqs", summary="Add FAQ Question & Answer with Similarity Checking")
def admin_add_faq_endpoint(
    payload: AdminCreateFAQRequest,
    user: dict = Depends(require_roles([Role.EXAM_ENTRY, Role.ADMIN, Role.SUPER_ADMIN]))
):
    faq_service = get_faq_service()
    result = faq_service.add_faq_entry(
        question=payload.question,
        answer=payload.answer,
        category=payload.category or "সাধারণ তথ্য",
        keywords=payload.keywords or "",
        force=bool(payload.force),
        admin_user=user.get("username", "Admin")
    )
    if result["status"] == "error":
        raise HTTPException(status_code=400, detail=result["message"])
    return result

@router.post("/faqs/check-similar", summary="Check if similar question exists before submission")
def check_similar_faq_endpoint(
    payload: Dict[str, Any],
    user: Optional[dict] = Depends(get_current_user_optional)
):
    q = (payload.get("question") or "").strip()
    if not q:
        return {"has_similar": False}
    faq_service = get_faq_service()
    similar = faq_service.find_similar_faq(q, threshold=0.70)
    return {
        "has_similar": bool(similar),
        "similar_faq": similar
    }


@router.post("/update-recent-notices", summary="Immediate sync of recent notices & knowledge base")
def admin_update_recent_notices_endpoint(
    payload: Optional[Dict[str, Any]] = None,
    user: Optional[dict] = Depends(get_current_user_optional)
):
    from fastapi.responses import JSONResponse
    from crawler.scheduler import sync_recent_notices, get_crawler_status
    status = get_crawler_status()
    if status.get("is_running"):
        return JSONResponse(status_code=409, content={"status": "busy", "message": "Crawler or synchronizer is already running."})
    max_rows = payload.get("max_rows", 80) if payload else 80
    return sync_recent_notices(max_rows=max_rows)


# --- Google Gemini API Health Check & User Rate Limit Diagnostic Endpoints ---
def perform_gemini_api_health_check(
    live_test: bool = True,
    custom_api_key: Optional[str] = None,
    test_prompt: str = "Reply with OK"
) -> Dict[str, Any]:
    import time as _time
    from google import genai
    from google.genai import types
    from backend.config import settings
    from backend.rate_limiter import rate_limiter

    raw_key = (custom_api_key if custom_api_key is not None else settings.GEMINI_API_KEY) or ""
    api_key = raw_key.strip()
    has_api_key = bool(api_key)
    if len(api_key) >= 10:
        masked_key = f"{api_key[:6]}...{api_key[-4:]}"
    elif has_api_key:
        masked_key = f"{api_key[:2]}***"
    else:
        masked_key = "Not Configured (Missing)"

    candidate_models = []
    for m in [settings.PRIMARY_MODEL] + list(settings.FALLBACK_MODELS) + ["gemini-2.5-flash", "gemini-2.0-flash"]:
        if m and m not in candidate_models:
            candidate_models.append(m)

    gemini_status = "MISSING_KEY"
    is_working = False
    key_valid = False
    quota_status = "UNCONFIGURED"
    status_label = "API Key Not Configured (এপিআই কি নেই)"
    active_working_model = None
    sample_reply = None
    error_detail = None
    latency_ms = 0.0
    tested_models = []

    if has_api_key:
        if not live_test:
            gemini_status = "CONFIGURED"
            key_valid = len(api_key) >= 20
            is_working = key_valid
            quota_status = "READY"
            status_label = "Configured & Ready (কনফিগার করা আছে)"
        else:
            t_start = _time.time()
            try:
                client = genai.Client(api_key=api_key)
                last_err_str = ""
                for model_name in candidate_models[:4]:
                    m_t0 = _time.time()
                    try:
                        resp = client.models.generate_content(
                            model=model_name,
                            contents=test_prompt or "Reply with OK",
                            config=types.GenerateContentConfig(
                                max_output_tokens=12,
                                temperature=0.0,
                            )
                        )
                        m_lat = round((_time.time() - m_t0) * 1000, 1)
                        reply_text = (resp.text or "OK").strip()
                        tested_models.append({
                            "model": model_name,
                            "status": "WORKING",
                            "latency_ms": m_lat,
                            "detail": reply_text[:40],
                            "reply_preview": reply_text[:40]
                        })
                        active_working_model = model_name
                        sample_reply = reply_text[:80]
                        latency_ms = m_lat
                        is_working = True
                        key_valid = True
                        gemini_status = "HEALTHY"
                        quota_status = "AVAILABLE"
                        status_label = "Working & Valid (সচল ও বৈধ)"
                        break
                    except Exception as m_err:
                        m_lat = round((_time.time() - m_t0) * 1000, 1)
                        err_s = str(m_err)
                        last_err_str = err_s
                        upper_err = err_s.upper()
                        if "API_KEY_INVALID" in upper_err or "INVALID_ARGUMENT" in upper_err and "API KEY" in upper_err or "401" in upper_err:
                            tested_models.append({
                                "model": model_name,
                                "status": "INVALID_KEY",
                                "latency_ms": m_lat,
                                "detail": err_s[:120],
                                "error": err_s[:120]
                            })
                            gemini_status = "INVALID_KEY"
                            is_working = False
                            key_valid = False
                            quota_status = "UNAUTHORIZED"
                            status_label = "Invalid API Key (অবৈধ এপিআই কি)"
                            error_detail = err_s[:200]
                            break
                        elif "429" in upper_err or "RESOURCE_EXHAUSTED" in upper_err or "QUOTA" in upper_err:
                            tested_models.append({
                                "model": model_name,
                                "status": "RATE_LIMITED",
                                "latency_ms": m_lat,
                                "detail": "Quota / Rate Limit Exceeded (429)",
                                "error": "Quota / Rate Limit Exceeded (429)"
                            })
                            key_valid = True
                            gemini_status = "RATE_LIMITED"
                            quota_status = "QUOTA_EXCEEDED"
                            status_label = "Valid Key — Quota / Rate Limit Reached (লিমিট পূর্ণ)"
                            error_detail = err_s[:200]
                        else:
                            tested_models.append({
                                "model": model_name,
                                "status": "ERROR",
                                "latency_ms": m_lat,
                                "detail": err_s[:120],
                                "error": err_s[:120]
                            })

                if not latency_ms:
                    latency_ms = round((_time.time() - t_start) * 1000, 1)

                if not is_working and gemini_status not in ("INVALID_KEY", "RATE_LIMITED"):
                    gemini_status = "DEGRADED"
                    key_valid = len(api_key) >= 20
                    quota_status = "MODEL_OR_NETWORK_ISSUE"
                    status_label = "Degraded / Model Unavailable (সংযোগ বা মডেল ত্রুটি)"
                    error_detail = last_err_str[:200]
            except Exception as outer_e:
                latency_ms = round((_time.time() - t_start) * 1000, 1)
                gemini_status = "ERROR"
                is_working = False
                key_valid = False
                quota_status = "ERROR"
                status_label = "API Check Failed (যাচাই ব্যর্থ)"
                error_detail = str(outer_e)[:200]

    # User Rate Limiter Inspection
    now_ts = _time.time()
    window_start = now_ts - 60.0
    per_ip_limit = int(getattr(rate_limiter, "limit", settings.RATE_LIMIT_PER_MINUTE))
    active_ips = []
    total_requests_last_min = 0
    throttled_ips_count = 0

    for ip, timestamps in list(rate_limiter.requests.items()):
        valid_ts = [t for t in timestamps if t > window_start]
        rate_limiter.requests[ip] = valid_ts
        req_count = len(valid_ts)
        if req_count > 0:
            total_requests_last_min += req_count
            is_throttled = per_ip_limit > 0 and req_count >= per_ip_limit
            if is_throttled:
                throttled_ips_count += 1
            active_ips.append({
                "ip": ip,
                "requests_last_minute": req_count,
                "requests_in_last_minute": req_count,
                "limit_per_minute": per_ip_limit,
                "remaining_requests": max(0, per_ip_limit - req_count) if per_ip_limit > 0 else 9999,
                "usage_percent": round(min(100.0, (req_count / per_ip_limit) * 100.0), 1) if per_ip_limit > 0 else 0.0,
                "is_rate_limited": is_throttled,
                "is_throttled": is_throttled
            })

    active_ips.sort(key=lambda x: x["requests_last_minute"], reverse=True)
    checked_at_str = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")

    return {
        "status": "success",
        "checked_at": checked_at_str,
        "gemini_api": {
            "status": gemini_status,
            "status_label": status_label,
            "message": status_label,
            "checked_at": checked_at_str,
            "is_working": is_working,
            "key_valid": key_valid,
            "has_api_key": has_api_key,
            "masked_api_key": masked_key,
            "key_length": len(api_key),
            "quota_status": quota_status,
            "primary_model": settings.PRIMARY_MODEL,
            "active_working_model": active_working_model or settings.PRIMARY_MODEL,
            "fallback_models": settings.FALLBACK_MODELS,
            "embedding_model": settings.EMBEDDING_MODEL,
            "latency_ms": latency_ms,
            "sample_reply": sample_reply,
            "error_detail": error_detail,
            "tested_models": tested_models
        },
        "user_rate_limit": {
            "limit_per_minute": per_ip_limit,
            "env_default_limit": settings.RATE_LIMIT_PER_MINUTE,
            "window_seconds": 60,
            "active_users_count": len(active_ips),
            "total_requests_last_minute": total_requests_last_min,
            "throttled_users_count": throttled_ips_count,
            "captcha_bypass_enabled": True,
            "active_ips": active_ips[:25]
        }
    }


@router.get("/api-health-check", summary="Check Google Gemini API validity, working status, and user rate limits")
def admin_get_api_health_check(
    live_test: bool = Query(True, description="Perform live probe to Google Gemini API"),
    user: Optional[dict] = Depends(get_current_user_optional)
):
    return perform_gemini_api_health_check(live_test=live_test)


@router.post("/api-health-check", summary="Run live Google Gemini API diagnostic check with optional custom key/prompt")
def admin_post_api_health_check(
    payload: Optional[Dict[str, Any]] = None,
    user: Optional[dict] = Depends(get_current_user_optional)
):
    data = payload or {}
    live_test = bool(data.get("live_test", True))
    custom_key = data.get("custom_api_key") or data.get("api_key")
    test_prompt = data.get("test_prompt") or "Reply with OK"
    return perform_gemini_api_health_check(
        live_test=live_test,
        custom_api_key=custom_key,
        test_prompt=test_prompt
    )


@router.post("/api-health-check/rate-limit", summary="Update user rate limit (RPM) or reset throttled user IPs")
def admin_update_user_rate_limit(
    payload: Dict[str, Any],
    user: Optional[dict] = Depends(get_current_user_optional)
):
    from backend.rate_limiter import rate_limiter
    action = (payload.get("action") or "").strip().lower()
    reset_all = bool(payload.get("reset_all", False)) or (action == "reset_all")
    new_limit = payload.get("limit_per_minute")
    target_ip = (payload.get("ip") or "").strip()
    messages = []

    if reset_all:
        rate_limiter.requests.clear()
        messages.append("সকল ব্যবহারকারীর রেট লিমিট কাউন্টার রিসেট করা হয়েছে (All user rate limit counters cleared).")

    if action == "reset_ip" and target_ip:
        rate_limiter.reset_ip(target_ip)
        messages.append(f"IP {target_ip} এর রেট লিমিট রিসেট করা হয়েছে।")

    if new_limit is not None:
        try:
            val = int(new_limit)
            if val < 1 or val > 10000:
                raise ValueError("Limit must be between 1 and 10000")
            rate_limiter.limit = val
            messages.append(f"ব্যবহারকারীর প্রতি মিনিটের রিকোয়েস্ট লিমিট {val} RPM-এ উন্নীত করা হয়েছে।")
        except ValueError as ve:
            raise HTTPException(status_code=400, detail=str(ve))

    if not messages:
        raise HTTPException(status_code=400, detail="Provide 'limit_per_minute', 'reset_all', or 'action' ('reset_all' / 'reset_ip').")

    snapshot = perform_gemini_api_health_check(live_test=False)
    return {
        "status": "success",
        "message": " ".join(messages),
        "limit_per_minute": rate_limiter.limit,
        "user_rate_limit": snapshot["user_rate_limit"]
    }

@router.post("/api-health-check/update-key", summary="Change and persist a new Google Gemini API Key in .env and live RAG engine")
def admin_update_gemini_api_key(
    payload: Dict[str, Any],
    user: Optional[dict] = Depends(get_current_user_optional)
):
    import os
    import re
    from pathlib import Path
    from backend.config import settings
    from google import genai

    raw_key = (payload.get("new_api_key") or payload.get("api_key") or "").strip().strip('"').strip("'")
    live_test = bool(payload.get("live_test", True))

    if not raw_key or len(raw_key) < 15:
        raise HTTPException(
            status_code=400,
            detail="একটি বৈধ Google Gemini API Key প্রদান করুন (Minimum 15 characters, e.g., AIzaSy...)."
        )

    # 1. Update in-memory settings and environment variable immediately
    os.environ["GEMINI_API_KEY"] = raw_key
    settings.GEMINI_API_KEY = raw_key

    # 2. Persist into project .env file so restarts keep the new API key
    env_path = Path(__file__).resolve().parent.parent.parent / ".env"
    try:
        if env_path.exists():
            env_content = env_path.read_text(encoding="utf-8")
            env_nl = "\r\n" if "\r\n" in env_content else "\n"
            if re.search(r"^GEMINI_API_KEY\s*=", env_content, flags=re.MULTILINE):
                env_content = re.sub(
                    r"^GEMINI_API_KEY\s*=.*$",
                    f"GEMINI_API_KEY={raw_key}",
                    env_content,
                    flags=re.MULTILINE
                )
            else:
                if not env_content.endswith(("\n", "\r\n")):
                    env_content += env_nl
                env_content += f"GEMINI_API_KEY={raw_key}{env_nl}"
            env_path.write_text(env_content, encoding="utf-8")
        else:
            env_path.write_text(f"GEMINI_API_KEY={raw_key}\n", encoding="utf-8")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to write new API key to .env file: {e}")

    # 3. Hot-reload live RAG Engine & Vector Store embeddings without server restart
    try:
        from backend.rag_engine import get_rag_engine
        rag = get_rag_engine()
        rag.api_key = raw_key
        rag.client = genai.Client(api_key=raw_key)
    except Exception:
        pass

    try:
        from db.vector_store import get_vector_store, ResilientEmbeddings
        vs = get_vector_store()
        vs.embeddings = ResilientEmbeddings(api_key=raw_key)
    except Exception:
        pass

    # 4. Run health check on the newly activated key
    report = perform_gemini_api_health_check(live_test=live_test, custom_api_key=raw_key)
    report["key_updated"] = True
    report["update_message"] = (
        "✅ নতুন Google Gemini API Key সফলভাবে সংরক্ষণ (.env) ও সক্রিয় (Hot-Reload) করা হয়েছে! "
        "(New Gemini API Key saved and activated immediately without server restart.)"
    )
    return report

