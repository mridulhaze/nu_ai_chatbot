import hmac
import hashlib
import base64
import json
import time
from typing import Optional, Dict, Any, List
from enum import Enum
from fastapi import HTTPException, Header, Depends, status
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from .config import settings

def _get_encryption_key() -> bytes:
    raw = settings.CREDENTIAL_ENCRYPTION_KEY or settings.JWT_SECRET or "nu-secret-key-2026"
    return hashlib.sha256(raw.encode("utf-8")).digest()

def encrypt_credential_data(plain_text: str) -> str:
    """Encrypts credential data using AES-256-GCM authenticated encryption."""
    if not plain_text:
        return ""
    key = _get_encryption_key()
    aesgcm = AESGCM(key)
    nonce = hashlib.sha256(f"{time.time()}_{plain_text}".encode()).digest()[:12]
    ciphertext = aesgcm.encrypt(nonce, plain_text.encode("utf-8"), None)
    return base64.urlsafe_b64encode(nonce + ciphertext).decode("utf-8")

def decrypt_credential_data(cipher_text: str) -> Optional[str]:
    """Decrypts AES-256-GCM ciphertext. Returns None if invalid or tampered."""
    if not cipher_text:
        return None
    try:
        key = _get_encryption_key()
        aesgcm = AESGCM(key)
        raw_bytes = base64.urlsafe_b64decode(cipher_text.encode("utf-8"))
        nonce = raw_bytes[:12]
        ciphertext = raw_bytes[12:]
        decrypted = aesgcm.decrypt(nonce, ciphertext, None)
        return decrypted.decode("utf-8")
    except Exception:
        return None

class Role(str, Enum):
    USER = "USER"
    SOLVER = "SOLVER"
    EXAM_ENTRY = "EXAM_ENTRY"
    ADMIN = "ADMIN"
    SUPER_ADMIN = "SUPER_ADMIN"

ROLE_HIERARCHY = {
    Role.USER: 1,
    Role.SOLVER: 2,
    Role.EXAM_ENTRY: 2,
    Role.ADMIN: 3,
    Role.SUPER_ADMIN: 4
}

def hash_password(password: str) -> str:
    """Secure password hash using PBKDF2-HMAC-SHA256."""
    salt = hashlib.sha256(str(time.time()).encode()).hexdigest()[:16]
    derived = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("utf-8"), 100000)
    return f"{salt}${derived.hex()}"

def verify_password(password: str, hashed: str) -> bool:
    """Verifies a password against PBKDF2 hashed string."""
    try:
        salt, hx = hashed.split("$")
        derived = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("utf-8"), 100000)
        return hmac.compare_digest(derived.hex(), hx)
    except Exception:
        return False

def _base64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode('utf-8').rstrip('=')

def _base64url_decode(data: str) -> bytes:
    padding = '=' * (4 - (len(data) % 4))
    return base64.urlsafe_b64decode(data + padding)

def create_jwt_token(payload: Dict[str, Any], expires_in_minutes: Optional[int] = None) -> str:
    """Creates a signed HS256 JWT token without external dependencies."""
    exp = int(time.time()) + ((expires_in_minutes or settings.JWT_EXPIRE_MINUTES) * 60)
    body = {**payload, "exp": exp, "iat": int(time.time())}
    
    header = {"alg": "HS256", "typ": "JWT"}
    hdr_b64 = _base64url_encode(json.dumps(header).encode('utf-8'))
    body_b64 = _base64url_encode(json.dumps(body).encode('utf-8'))
    
    signing_input = f"{hdr_b64}.{body_b64}".encode('utf-8')
    signature = hmac.new(settings.JWT_SECRET.encode('utf-8'), signing_input, hashlib.sha256).digest()
    sig_b64 = _base64url_encode(signature)
    
    return f"{hdr_b64}.{body_b64}.{sig_b64}"

def decode_jwt_token(token: str) -> Optional[Dict[str, Any]]:
    """Decodes and verifies a signed HS256 JWT token."""
    try:
        parts = token.split(".")
        if len(parts) != 3:
            return None
        
        hdr_b64, body_b64, sig_b64 = parts
        signing_input = f"{hdr_b64}.{body_b64}".encode('utf-8')
        expected_sig = hmac.new(settings.JWT_SECRET.encode('utf-8'), signing_input, hashlib.sha256).digest()
        
        if not hmac.compare_digest(_base64url_encode(expected_sig), sig_b64):
            return None
        
        body = json.loads(_base64url_decode(body_b64).decode('utf-8'))
        if body.get("exp") and body["exp"] < time.time():
            return None
        return body
    except Exception:
        return None

def get_current_user_optional(authorization: Optional[str] = Header(None)) -> Optional[Dict[str, Any]]:
    """Extracts authenticated user if Bearer token is provided."""
    if not authorization or not authorization.startswith("Bearer "):
        return None
    token = authorization.split("Bearer ", 1)[1].strip()
    return decode_jwt_token(token)

def get_current_user_required(authorization: Optional[str] = Header(None)) -> Dict[str, Any]:
    """Strictly requires authentication."""
    user = get_current_user_optional(authorization)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication token required or expired."
        )
    return user

def require_roles(allowed_roles: List[Role]):
    """Role-based authorization dependency."""
    def dependency(user: Dict[str, Any] = Depends(get_current_user_required)) -> Dict[str, Any]:
        user_role = user.get("role", Role.USER)
        if user_role not in [r.value for r in allowed_roles]:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Access forbidden. Required role: {[r.value for r in allowed_roles]}"
            )
        return user
    return dependency
