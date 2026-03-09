from flask import Blueprint, request, jsonify, session
from flask_bcrypt import Bcrypt
from pymongo import MongoClient

admin_bp = Blueprint("admin_bp", __name__)
bcrypt = Bcrypt()

client = MongoClient("mongodb://localhost:27017/")
db = client["ai_complaint_portal"]
admins_col = db["admins"]


# 1. FIX: Route to get counts for dashboard cards
@admin_bp.route('/stats_by_dept')
def stats_by_dept():
    pipeline = [{"$group": {"_id": "$assigned_department", "count": {"$sum": 1}}}]
    results = list(db.complaints.aggregate(pipeline))
    return jsonify({res['_id']: res['count'] for res in results if res['_id']})

# 2. FIX: Satisfaction Chart (Now reads from the 'feedbacks' collection you created in app.py)
@admin_bp.route('/feedback_analytics')
def feedback_analytics():
    pipeline = [
        {"$group": {"_id": "$dept_name", "avgRating": {"$avg": "$rating"}}}
    ]
    results = list(db.feedbacks.aggregate(pipeline))
    return jsonify({res['_id']: round(res['avgRating'], 1) for res in results if res['_id']})

# 3. FIX: Urgent Alerts (Now reads from 'feedbacks' collection)
@admin_bp.route('/urgent_feedback')
def urgent_feedback():
    critical = list(db.feedbacks.find({"rating": {"$lte": 2}}).sort("timestamp", -1).limit(5))
    output = []
    for item in critical:
        output.append({
            "id": item.get('complaint_id'),
            "dept": item.get('dept_name'),
            "comment": item.get('comment', "No comment")
        })
    return jsonify(output)


@admin_bp.route("/admin/login", methods=["POST"])
def admin_login():
    data = request.json
    email = data.get("email")
    password = data.get("password")

    admin = admins_col.find_one({"email": email})
    if not admin:
        return jsonify({"error": "Admin not found"}), 404

    if bcrypt.check_password_hash(admin["password"], password):
        session["admin_email"] = admin["email"]
        return jsonify({"message": "Admin login success"}), 200

    return jsonify({"error": "Wrong password"}), 401
