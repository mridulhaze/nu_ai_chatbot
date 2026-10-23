import logging
from datetime import datetime
from fastapi import APIRouter, HTTPException, Depends, status
from pydantic import BaseModel

from backend.core.security import hash_password, verify_password, create_jwt_token, get_current_user_required, Role
from backend.core.audit import log_audit_event
from backend.models.schemas import UserLoginRequest, UserRegisterRequest, AuthTokenResponse, UserResponse
from token_service.db import get_token_db_connection

logger = logging.getLogger("NU_AUTH_API")
router = APIRouter(prefix="/api/v1/auth", tags=["Authentication & RBAC"])

def _init_users_table():
    conn = get_token_db_connection()
    with conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE NOT NULL,
                email TEXT UNIQUE,
                password_hash TEXT NOT NULL,
                full_name TEXT,
                department TEXT,
                role TEXT NOT NULL DEFAULT 'USER',
                active INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL
            )
        """)
        # Create default superadmin if not exists
        cur = conn.execute("SELECT id FROM users WHERE username = 'admin'")
        now_str = datetime.utcnow().isoformat()
        if not cur.fetchone():
            default_pwd_hash = hash_password("nu_admin_2026")
            conn.execute("""
                INSERT INTO users (username, email, password_hash, full_name, department, role, active, created_at)
                VALUES ('admin', 'admin@nu.ac.bd', ?, 'NU System Administrator', 'ICT Cell', 'SUPER_ADMIN', 1, ?)
            """, (default_pwd_hash, now_str))

        # Default solvers for each department
        solver_pwd = hash_password("nu_solver_2026")
        default_solvers = [
            ("solver_ict", "ict-support@nu.ac.bd", "ICT Support Desk Officer", "ICT Support Team"),
            ("solver_exam", "exam-controller@nu.ac.bd", "Exam Section Officer", "Controller of Examination Section"),
            ("solver_cert", "certificate@nu.ac.bd", "Certificate Records Desk", "Certificate & Academic Records Cell"),
            ("solver_adm", "admission@nu.ac.bd", "Admission Portal Officer", "Admission & Registration Cell"),
            ("solver_acc", "finance@nu.ac.bd", "Sonali Seba & Accounts Desk", "Accounts & Sonali Seba Desk"),
        ]
        for u_name, u_email, u_full, u_dept in default_solvers:
            s_cur = conn.execute("SELECT id FROM users WHERE username = ?", (u_name,))
            if not s_cur.fetchone():
                conn.execute("""
                    INSERT INTO users (username, email, password_hash, full_name, department, role, active, created_at)
                    VALUES (?, ?, ?, ?, ?, 'SOLVER', 1, ?)
                """, (u_name, u_email, solver_pwd, u_full, u_dept, now_str))

        # Default Exam Entry staff account (only Academic Exam & Results Hub + FAQ Q&A Entry)
        exam_entry_cur = conn.execute("SELECT id FROM users WHERE username = 'exam_entry'")
        if not exam_entry_cur.fetchone():
            exam_entry_pwd = hash_password("nu_exam_2026")
            conn.execute("""
                INSERT INTO users (username, email, password_hash, full_name, department, role, active, created_at)
                VALUES ('exam_entry', 'exam-entry@nu.ac.bd', ?, 'Exam & FAQ Entry Officer', 'Controller of Examination Section', 'EXAM_ENTRY', 1, ?)
            """, (exam_entry_pwd, now_str))
    conn.close()

_init_users_table()

@router.post("/register", response_model=AuthTokenResponse)
def register_user(payload: UserRegisterRequest):
    conn = get_token_db_connection()
    try:
        cur = conn.execute("SELECT id FROM users WHERE username = ?", (payload.username.strip(),))
        if cur.fetchone():
            raise HTTPException(status_code=400, detail="Username already exists.")

        pwd_hash = hash_password(payload.password)
        now_str = datetime.utcnow().isoformat()
        role = payload.role.upper() if payload.role and payload.role.upper() in ["USER", "SOLVER"] else "USER"

        with conn:
            cur = conn.execute("""
                INSERT INTO users (username, email, password_hash, full_name, role, active, created_at)
                VALUES (?, ?, ?, ?, ?, 1, ?)
            """, (payload.username.strip(), payload.email, pwd_hash, payload.full_name, role, now_str))
            user_id = cur.lastrowid

        user_dict = {
            "id": user_id,
            "username": payload.username.strip(),
            "email": payload.email,
            "full_name": payload.full_name,
            "role": role,
            "department": None,
            "active": True
        }

        token = create_jwt_token(user_dict)
        log_audit_event("USER_REGISTER", user_id=str(user_id), username=payload.username, role=role)

        return AuthTokenResponse(
            access_token=token,
            token_type="bearer",
            user=UserResponse(**user_dict)
        )
    finally:
        conn.close()

@router.post("/login", response_model=AuthTokenResponse)
def login_user(payload: UserLoginRequest):
    conn = get_token_db_connection()
    try:
        cur = conn.execute("SELECT * FROM users WHERE username = ?", (payload.username.strip(),))
        user = cur.fetchone()
        if not user or not verify_password(payload.password, user["password_hash"]):
            raise HTTPException(status_code=401, detail="Invalid username or password.")

        if not user["active"]:
            raise HTTPException(status_code=403, detail="User account is deactivated.")

        user_dict = {
            "id": user["id"],
            "username": user["username"],
            "email": user["email"],
            "full_name": user["full_name"],
            "role": user["role"],
            "department": user["department"],
            "active": bool(user["active"])
        }

        token = create_jwt_token(user_dict)
        log_audit_event("USER_LOGIN", user_id=str(user["id"]), username=user["username"], role=user["role"])

        return AuthTokenResponse(
            access_token=token,
            token_type="bearer",
            user=UserResponse(**user_dict)
        )
    finally:
        conn.close()

@router.get("/me", response_model=UserResponse)
def get_current_user_profile(user: dict = Depends(get_current_user_required)):
    return UserResponse(
        id=user["id"],
        username=user["username"],
        email=user.get("email"),
        full_name=user.get("full_name"),
        role=user["role"],
        department=user.get("department"),
        active=user.get("active", True)
    )
