import logging
from flask import Blueprint, request, jsonify
from backend.app.models.governance import AppUser
from backend.app.extensions import db

logger = logging.getLogger("fraud_agent.api.auth")
auth_bp = Blueprint("auth", __name__)

@auth_bp.route("/personas", methods=["GET"])
def get_personas():
    """Returns available personas from MySQL database for fast login and persona switching."""
    try:
        users = AppUser.query.filter_by(status="ACTIVE").order_by(AppUser.created_at.asc()).all()
        result = []
        for u in users:
            d = u.to_dict()
            # In development/demo mode, include sample demo password hint so the user can easily test
            demo_pass = "admin@123" if u.role == "ADMIN" else (
                "analyst123" if "INVESTIGATOR" in u.role else (
                    "riskops99" if u.role == "SUPERVISOR" else "audit2024"
                )
            )
            d["demo_password"] = demo_pass
            result.append(d)
        return jsonify(result), 200
    except Exception as e:
        logger.error(f"Error fetching personas: {e}")
        return jsonify({"error": "Failed to fetch personas", "message": str(e)}), 500

@auth_bp.route("/login", methods=["POST"])
def login():
    """Authenticates application users (Investigator, Supervisor, Admin, Auditor) against MySQL."""
    data = request.get_json(silent=True) or {}
    email = data.get("email", "").strip()
    password = data.get("password", "").strip()

    if not email or not password:
        return jsonify({"error": "Bad Request", "message": "Email and password are required"}), 400

    try:
        user = AppUser.query.filter_by(email=email).first()
        if not user:
            return jsonify({"error": "Unauthorized", "message": "User not found in system records"}), 401

        if user.status != "ACTIVE":
            return jsonify({"error": "Forbidden", "message": f"Account status is {user.status}"}), 403

        # Check password hash
        if not user.check_password(password):
            return jsonify({"error": "Unauthorized", "message": "Invalid password credentials"}), 401

        user_data = user.to_dict()
        return jsonify({
            "status": "SUCCESS",
            "message": "Authentication successful",
            "user": user_data,
            "token": f"bearer-token-{user.id}"
        }), 200

    except Exception as e:
        logger.error(f"Login error: {e}")
        return jsonify({"error": "Internal Server Error", "message": str(e)}), 500

@auth_bp.route("/me", methods=["GET"])
def get_current_user():
    """Returns currently authenticated user profile."""
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer bearer-token-"):
        user_id = auth_header.replace("Bearer bearer-token-", "").strip()
        user = AppUser.query.filter_by(id=user_id).first()
        if user:
            return jsonify(user.to_dict()), 200
    return jsonify({"error": "Unauthorized", "message": "Valid session token required"}), 401
