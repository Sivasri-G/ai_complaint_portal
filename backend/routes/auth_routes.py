from flask import Blueprint, request, jsonify
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime

auth_bp = Blueprint("auth", __name__)

def init_auth_routes(db):
    users = db.users

    # ================= SIGN UP =================
    @auth_bp.route("/signup", methods=["POST"])
    def signup():
        data = request.json

        name = data.get("name")
        email = data.get("email")
        password = data.get("password")

        # 🔴 Validation
        if not name or not email or not password:
            return jsonify({"error": "All fields are required"}), 400

        if users.find_one({"email": email}):
            return jsonify({"error": "Email already registered"}), 400

        hashed_password = generate_password_hash(password)

        users.insert_one({
            "name": name,
            "email": email,
            "password": hashed_password,
            "role": "user",
            "created_at": datetime.utcnow()
        })

        return jsonify({"message": "Signup successful"}), 201

    # ================= LOGIN =================
    @auth_bp.route("/login", methods=["POST"])
    def login():
        data = request.json

        email = data.get("email")
        password = data.get("password")

        if not email or not password:
            return jsonify({"error": "Email and password required"}), 400

        user = users.find_one({"email": email})

        if not user or not check_password_hash(user["password"], password):
            return jsonify({"error": "Invalid email or password"}), 401

        return jsonify({
            "message": "Login successful",
            "role": user["role"],
            "name": user["name"]
        }), 200

    return auth_bp
