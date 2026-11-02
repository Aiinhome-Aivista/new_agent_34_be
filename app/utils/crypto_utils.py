import secrets
import hashlib
import hmac
from datetime import datetime, timezone, timedelta
from typing import Optional, Tuple

def utc_now() -> datetime:
    return datetime.now(timezone.utc)

def generate_secure_token() -> str:
    """Generates a high-entropy cryptographically secure random token (256-bit)."""
    return secrets.token_urlsafe(32)

def hash_token(token: str) -> str:
    """Calculates SHA-256 hash of a token for safe one-way storage."""
    return hashlib.sha256(token.strip().encode("utf-8")).hexdigest()

def generate_otp() -> str:
    """Generates a secure 6-digit numeric OTP."""
    return f"{secrets.randbelow(900000) + 100000}"

def hash_otp(otp: str) -> str:
    """Hashes 6-digit OTP for secure storage."""
    return hashlib.sha256(otp.strip().encode("utf-8")).hexdigest()

def verify_otp_constant_time(provided_otp: str, stored_hash: str) -> bool:
    """Performs constant-time comparison of OTP hash to prevent timing attacks."""
    if not provided_otp or not stored_hash:
        return False
    provided_hash = hash_otp(provided_otp)
    return hmac.compare_digest(provided_hash, stored_hash)

def generate_session_token() -> str:
    """Generates a short-lived random session token after OTP verification."""
    return secrets.token_hex(24)

def mask_email(email: Optional[str]) -> str:
    """Safely masks an email address (e.g. j***n@example.com)."""
    if not email or "@" not in email:
        return "u***@example.com"
    parts = email.split("@", 1)
    name, domain = parts[0], parts[1]
    if len(name) <= 2:
        masked_name = name[0] + "***"
    else:
        masked_name = name[0] + "***" + name[-1]
    return f"{masked_name}@{domain}"

def mask_phone(phone: Optional[str]) -> str:
    """Safely masks a phone number (e.g. ******3412)."""
    if not phone:
        return "******0000"
    cleaned = "".join(ch for ch in phone if ch.isdigit())
    if len(cleaned) < 4:
        return "******"
    return "*" * (len(cleaned) - 4) + cleaned[-4:]

def mask_reference_id(ref_id: Optional[str], prefix: str = "REF") -> str:
    """Safely masks internal reference IDs (e.g. TXN-****9102)."""
    if not ref_id:
        return f"{prefix}-****0000"
    cleaned = str(ref_id).strip()
    if len(cleaned) <= 6:
        return f"{prefix}-****{cleaned[-2:]}"
    return f"{prefix}-****{cleaned[-4:]}"
