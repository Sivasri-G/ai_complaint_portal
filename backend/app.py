from flask import Flask, request, jsonify, send_from_directory, abort
from flask_bcrypt import Bcrypt

from pymongo import MongoClient
import os
import re
from datetime import datetime
from flask import session, redirect, url_for
from werkzeug.utils import secure_filename
from ml.predict import predict_category

from department_mapper import get_department
from routes.admin_routes import admin_bp

# ---------------- PATH SETUP ----------------
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
FRONTEND_DIR = os.path.abspath(os.path.join(BASE_DIR, "..", "frontend"))
UPLOAD_DIR = os.path.join(BASE_DIR, "uploads")
os.makedirs(UPLOAD_DIR, exist_ok=True)

app = Flask(__name__)
app.register_blueprint(admin_bp, url_prefix='/admin')

app.secret_key = "super_secret_key_change_later"
bcrypt = Bcrypt(app)

app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=False,
    SESSION_COOKIE_PATH="/",
)

# ---------------- MONGODB ----------------
client = MongoClient("mongodb://localhost:27017/")
db = client["ai_complaint_portal"]
users_col = db["users"]
complaints_col = db["complaints"]
admins_col = db["admins"]
feedbacks_col = db["feedbacks"]

# ---------------- HELPERS ----------------
def generate_complaint_id():
    today = datetime.utcnow().strftime("%Y%m%d")
    start_of_day = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    count = complaints_col.count_documents({
        "created_at": {"$gte": start_of_day}
    }) + 1
    return f"CMP{today}{count:04d}"


# ---------------- FRONTEND ROUTES ----------------
@app.route("/")
def home():
    return send_from_directory(FRONTEND_DIR, "index.html")

@app.route("/complaint_form")
def complaint_page():
    if "user_email" not in session:
        return redirect("/")
    return send_from_directory(FRONTEND_DIR, "complaint_form.html")

@app.route("/lang/<path:filename>")
def serve_lang(filename):
    return send_from_directory(os.path.join(FRONTEND_DIR, "lang"), filename)

@app.route("/<path:filename>")
def serve_static(filename):
    return send_from_directory(FRONTEND_DIR, filename)


# ---------------- SIGNUP ----------------
@app.route("/signup", methods=["POST"])
def signup():
    data = request.json
    email = data.get("email")
    password = data.get("password")
    language = data.get("language", "en")

    if not email or not password:
        return jsonify({"error": "All fields are required"}), 400

    pattern = r'^(?=.*[a-z])(?=.*[A-Z])(?=.*\d).{8,}$'
    if not re.match(pattern, password):
        return jsonify({"error": "Password must be 8+ chars with upper, lower & number"}), 400

    if users_col.find_one({"email": email}):
        return jsonify({"error": "User already exists. Please login."}), 409

    hashed_pw = bcrypt.generate_password_hash(password).decode("utf-8")
    users_col.insert_one({
        "email": email,
        "password": hashed_pw,
        "language": language,
        "created_at": datetime.now()
    })
    return jsonify({"message": "Signup successful. Please login."}), 201


# ---------------- LOGIN ----------------
@app.route("/login", methods=["POST"])
def login():
    data = request.json
    email = data.get("email")
    password = data.get("password")

    if not email or not password:
        return jsonify({"error": "All fields required"}), 400

    user = users_col.find_one({"email": email})
    if not user:
        return jsonify({"error": "User not found. Please signup first."}), 404

    if bcrypt.check_password_hash(user["password"], password):
        session.clear()
        session["user_email"] = user["email"]
        session.modified = True
        return jsonify({"message": "Login successful", "email": user["email"]}), 200

    return jsonify({"error": "Incorrect password"}), 401


# ---------------- FORGOT PASSWORD ----------------
@app.route("/forgot-password", methods=["POST"])
def forgot_password():
    data = request.json
    email = data.get("email")
    password = data.get("password")

    if not email or not password:
        return jsonify({"error": "All fields required"}), 400

    user = users_col.find_one({"email": email})
    if not user:
        return jsonify({"error": "Email not registered"}), 404

    pattern = r'^(?=.*[a-z])(?=.*[A-Z])(?=.*\d).{8,}$'
    if not re.match(pattern, password):
        return jsonify({"error": "Password must be 8+ chars with upper, lower & number"}), 400

    hashed_pw = bcrypt.generate_password_hash(password).decode("utf-8")
    users_col.update_one({"email": email}, {"$set": {"password": hashed_pw}})
    return jsonify({"message": "Password updated successfully"}), 200


# ---------------- USER INFO ----------------
@app.route("/get_user_info")
def get_user_info():
    if "user_email" in session:
        return jsonify({"email": session["user_email"]}), 200
    return jsonify({"error": "Not logged in"}), 401


# ---------------- SUBMIT COMPLAINT ----------------
@app.route("/submit-complaint", methods=["POST"])
def submit_complaint():

    predicted_category = ""
    confidence = 0.0
    severity = None
    assigned_department = ""
    voice_file = None
    image_file = None
    input_type = "text"
    voice_text = ""
    image_text = ""

    if "user_email" not in session:
        return jsonify({"error": "Unauthorized. Please login again."}), 401

    complaint_id = request.form.get("complaint_id")
    name = request.form.get("name")
    email = session["user_email"]  # Always use session email (security fix)
    location = request.form.get("location")
    text = request.form.get("description", "").strip()

    # ---------- AUDIO UPLOAD ----------
    voice_path = None
    if "audio" in request.files:
        voice = request.files["audio"]
        if voice and voice.filename:
            timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
            ext = os.path.splitext(voice.filename)[1]
            voice_file = f"{timestamp}_voice{ext}"
            voice_path = os.path.join(UPLOAD_DIR, voice_file)
            voice.save(voice_path)
            input_type = "voice"

    # ---------- IMAGE UPLOAD ----------
    if "image" in request.files and request.files["image"].filename != "":
        image = request.files["image"]
        image_file = f"{datetime.now().strftime('%Y%m%d%H%M%S')}_{secure_filename(image.filename)}"
        image.save(os.path.join(UPLOAD_DIR, image_file))
        input_type = "image"

    # ---------- VOICE → TEXT ----------
    if voice_file:
        from utils.speech_to_text import convert_voice_to_text
        voice_full_path = os.path.join(UPLOAD_DIR, voice_file)
        voice_text = convert_voice_to_text(voice_full_path)
        if voice_text:
            text = (text + " " + voice_text).strip()

    # ---------- IMAGE → TEXT ----------
    if image_file:
        from utils.image_to_text import extract_text_from_image
        image_text = extract_text_from_image(os.path.join(UPLOAD_DIR, image_file))
        if image_text:
            text += " " + image_text

    # ---------- FINAL INPUT TYPE ----------
    if voice_file and image_file:
        input_type = "mixed"
    elif voice_file:
        input_type = "voice"
    elif image_file:
        input_type = "image"
    else:
        input_type = "text"

    # ---------- FINAL VALIDATION ----------
    from utils.translate import translate_to_english

    final_text = (text or "").strip()
    print("🧪 DEBUG final_text =", repr(final_text))

    if not final_text:
        return jsonify({"error": "Empty complaint"}), 400

    translated_text = translate_to_english(final_text)

    # ---------- KEYWORD ENHANCEMENT ----------
    voice_text_lower = translated_text.lower()
    if "bus" in voice_text_lower or "buses" in voice_text_lower:
        translated_text += " public transport bus service timing issue"
    if "water" in voice_text_lower:
        translated_text += " water supply issue pipeline problem"
    if "street light" in voice_text_lower or "light" in voice_text_lower:
        translated_text += " electricity street light power issue"
    if "road" in voice_text_lower or "pothole" in voice_text_lower:
        translated_text += " road infrastructure transport issue"

    print("🌐 Translated text:", translated_text)

    # ---------- AI PREDICTION ----------
    predicted_category, confidence = predict_category(translated_text)

    # ---------- CATEGORY OVERRIDE FIX ----------
    lower_translated = translated_text.lower()
    infra_keywords = ["road", "pothole", "bridge", "pavement", "highway", "street light", "சாலை", "பாலம்"]
    if any(word in lower_translated for word in infra_keywords):
        predicted_category = "Road & Infrastructure Issues"
        confidence = 1.0

    confidence = float(confidence)
    assigned_department = get_department(predicted_category)

    # ---------- SEVERITY ----------
    severity = request.form.get("severity")
    if not severity:
        if confidence >= 0.85:
            severity = "High"
        elif confidence >= 0.65:
            severity = "Medium"
        else:
            severity = "Low"

    print("🧠 AI FINAL INPUT:", final_text)
    print("🧠 AI RESULT:", predicted_category, confidence, severity)

    # ---------- DATABASE INSERT ----------
    complaints_col.insert_one({
        "complaint_id": complaint_id,
        "user_email": email,
        "name": name,
        "location": location,
        "complaint_text": final_text,
        "translated_text": translated_text,
        "predicted_category": predicted_category,
        "confidence": confidence,
        "assigned_department": assigned_department,
        "severity": severity,
        "input_type": input_type,
        "voice_file": voice_file,
        "image_file": image_file,
        "status": "Open",
        "created_at": datetime.utcnow(),
        "history": [{"status": "Open", "updated_at": datetime.utcnow(), "comment": "Complaint filed"}]
    })
    return jsonify({"message": "Complaint submitted successfully"}), 200


# ---------------- PREDICT CATEGORY API ----------------
@app.route("/predict-category", methods=["POST"])
def predict_category_api():
    data = request.json
    text = data.get("text", "")
    if not text.strip():
        return jsonify({"category": "", "confidence": 0})
    category, confidence = predict_category(text)
    return jsonify({"category": category, "confidence": round(confidence, 3)})


# ---------------- SESSION CHECK ----------------
@app.route("/check_login")
def check_login():
    if "user_email" in session:
        return jsonify({"status": "logged_in"}), 200
    return jsonify({"status": "not_logged_in"}), 401


# ---------------- ADMIN ROUTES ----------------
@app.route("/admin-login")
def admin_login_page():
    return send_from_directory(FRONTEND_DIR, "admin_login.html")

@app.route("/admin/login", methods=["POST"])
def admin_login():
    data = request.json
    email = data.get("email")
    password = data.get("password")

    if not email or not password:
        return jsonify({"error": "All fields required"}), 400

    admin = admins_col.find_one({"email": email})
    if not admin:
        return jsonify({"error": "Admin not found"}), 404

    if not bcrypt.check_password_hash(admin["password"], password):
        return jsonify({"error": "Invalid password"}), 401

    session.clear()
    session["admin_email"] = admin["email"]
    session["role"] = "admin"
    return jsonify({"message": "Admin login successful"}), 200

@app.route("/admin-dashboard")
def admin_dashboard():
    if "admin_email" not in session:
        return redirect("/admin-login")
    return send_from_directory(FRONTEND_DIR, "admin_dashboard.html")


from flask import Response
import csv
import io

# --- UPDATE COMPLAINT STATUS (WITH HISTORY) ---
@app.route("/admin/update_status", methods=["POST"])
def update_status():
    if "admin_email" not in session:
        return jsonify({"error": "Unauthorized"}), 401

    data = request.json
    complaint_id = data.get("complaint_id")
    new_status = data.get("status")
    comment = data.get("comment", "Status updated by admin")

    if not complaint_id or not new_status:
        return jsonify({"error": "Missing data"}), 400

    complaints_col.update_one(
        {"complaint_id": complaint_id},
        {
            "$set": {"status": new_status},
            "$push": {
                "history": {
                    "status": new_status,
                    "updated_at": datetime.utcnow(),
                    "comment": comment
                }
            }
        }
    )
    return jsonify({"message": f"Status updated to {new_status}"}), 200


# --- EXPORT DEPARTMENT DATA TO CSV ---
@app.route("/admin/export_csv/<path:dept_name>")
def export_csv(dept_name):
    if "admin_email" not in session:
        return redirect("/admin-login")

    complaints = list(complaints_col.find({"assigned_department": dept_name}, {"_id": 0}))

    def generate():
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(['ID', 'Name', 'Location', 'Text', 'Category', 'Severity', 'Status', 'Date'])
        yield output.getvalue()
        output.seek(0)
        output.truncate(0)
        for c in complaints:
            writer.writerow([
                c.get('complaint_id'), c.get('name'), c.get('location'),
                c.get('translated_text'), c.get('predicted_category'),
                c.get('severity'), c.get('status'), c.get('created_at')
            ])
            yield output.getvalue()
            output.seek(0)
            output.truncate(0)

    response = Response(generate(), mimetype='text/csv')
    response.headers.set("Content-Disposition", "attachment", filename=f"{dept_name.replace(' ', '_')}_Report.csv")
    return response


# --- ADMIN DEPARTMENT VIEW ---
@app.route("/admin/department/<path:dept_name>")
def department_view_route(dept_name):
    if "admin_email" not in session:
        return redirect("/admin-login")
    return send_from_directory(FRONTEND_DIR, "dept_details.html")

@app.route("/admin/department_data/<path:dept_name>")
def get_department_data(dept_name):
    if "admin_email" not in session:
        return jsonify({"error": "Unauthorized"}), 401
    complaints = list(complaints_col.find({"assigned_department": dept_name}, {"_id": 0}).sort("created_at", -1))
    return jsonify(complaints)

@app.route("/admin/stats_by_dept")
def get_stats_for_dashboard():
    if "admin_email" not in session:
        return jsonify({"error": "Unauthorized"}), 401
    pipeline = [{"$group": {"_id": "$assigned_department", "count": {"$sum": 1}}}]
    results = list(complaints_col.aggregate(pipeline))
    stats = {item["_id"]: item["count"] for item in results if item["_id"]}
    return jsonify(stats)

@app.route("/admin/logout")
def admin_logout():
    session.clear()
    return redirect("/")


# ---------------- USER DASHBOARD ROUTES ----------------
@app.route("/user/complaints")
def get_user_complaints():
    if "user_email" not in session:
        return jsonify({"error": "Unauthorized"}), 401
    email = session["user_email"]
    user_complaints = list(complaints_col.find({"user_email": email}, {"_id": 0}).sort("created_at", -1))
    return jsonify(user_complaints)

@app.route("/logout")
def logout():
    session.clear()
    return redirect("/")

@app.route("/user-dashboard")
def user_dashboard_page():
    if "user_email" not in session:
        return redirect("/")
    return send_from_directory(FRONTEND_DIR, "user_dashboard.html")

@app.route("/user/profile_data")
def get_user_profile_data():
    if "user_email" not in session:
        return jsonify({"error": "Unauthorized"}), 401
    user = users_col.find_one({"email": session["user_email"]}, {"_id": 0, "password": 0})
    return jsonify(user)

@app.route("/user/dashboard_stats")
def get_user_dashboard_stats():
    if "user_email" not in session:
        return jsonify({"error": "Unauthorized"}), 401

    email = session["user_email"]
    user_data = users_col.find_one({"email": email})

    total = complaints_col.count_documents({"user_email": email})
    active = complaints_col.count_documents({
        "user_email": email,
        "status": {"$in": ["Open", "In Progress"]}
    })
    resolved = complaints_col.count_documents({"user_email": email, "status": "Resolved"})

    pipeline = [
        {"$match": {"user_email": email}},
        {"$group": {"_id": "$assigned_department", "count": {"$sum": 1}}}
    ]
    categories_cursor = list(complaints_col.aggregate(pipeline))
    category_data = {item["_id"]: item["count"] for item in categories_cursor if item["_id"]}

    all_complaints = list(complaints_col.find({"user_email": email}, {"_id": 0}).sort("created_at", -1))

    return jsonify({
        "total": total,
        "active": active,
        "resolved": resolved,
        "categories": category_data,
        "complaints": all_complaints,
        "user_email": email,
        "language": user_data.get('language', 'en')
    })

@app.route('/user/update_preferences', methods=['POST'])
def update_preferences():
    lang = request.json.get('language')
    user_email = session.get('user_email')
    db.users.update_one({"email": user_email}, {"$set": {"preferred_language": lang}})
    return jsonify({"status": "success"})

@app.route('/user/update_profile', methods=['POST'])
def update_profile():
    if 'user_email' not in session:
        return jsonify({"error": "Unauthorized"}), 401

    data = request.get_json()
    new_email = data.get('email')
    new_lang = data.get('language')
    old_email = session['user_email']

    if new_email != old_email:
        if users_col.find_one({"email": new_email}):
            return jsonify({"error": "Email already in use"}), 409

    try:
        users_col.update_one({"email": old_email}, {"$set": {"email": new_email, "language": new_lang}})
        if new_email != old_email:
            complaints_col.update_many({"user_email": old_email}, {"$set": {"user_email": new_email}})
        session['user_email'] = new_email
        return jsonify({"message": "Profile updated successfully"}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/user/submit_feedback', methods=['POST'])
def submit_feedback():
    if "user_email" not in session:
        return jsonify({"error": "Unauthorized"}), 401

    data = request.get_json()
    cid = data.get('complaint_id')
    rating = int(data.get('rating', 5))
    comment = data.get('comment', "").strip()

    complaint = db.complaints.find_one({"complaint_id": cid})
    dept = complaint.get("assigned_department", "General Administration") if complaint else "General Administration"

    sentiment = "Positive"
    if rating <= 2:
        sentiment = "Critical"
    elif rating == 3:
        sentiment = "Neutral"

    feedback_doc = {
        "complaint_id": cid,
        "user_email": session["user_email"],
        "dept_name": dept,
        "rating": rating,
        "comment": comment,
        "sentiment": sentiment,
        "timestamp": datetime.utcnow()
    }
    db.feedbacks.insert_one(feedback_doc)
    return jsonify({"message": "Feedback stored and analyzed"}), 200

@app.route('/admin/feedback_analytics')
def feedback_analytics():
    if "admin_email" not in session:
        return jsonify({"error": "Unauthorized"}), 401

    pipeline = [
        {
            "$group": {
                "_id": "$dept_name",
                "avg_rating": {"$avg": "$rating"},
                "total_reviews": {"$sum": 1}
            }
        },
        {"$sort": {"avg_rating": -1}}
    ]
    results = list(db.feedbacks.aggregate(pipeline))
    chart_data = {res['_id']: round(res['avg_rating'], 1) for res in results}
    return jsonify(chart_data)

@app.route('/admin/urgent_feedback')
def urgent_feedback():
    if "admin_email" not in session:
        return jsonify([])
    low_ratings = list(db.feedbacks.find(
        {"$or": [{"rating": {"$lte": 2}}, {"sentiment": "Critical"}]},
        {"_id": 0}
    ).sort("timestamp", -1).limit(8))
    return jsonify(low_ratings)


# ── ADD THIS to app.py, just above if __name__ == "__main__": ──
# No extra libraries needed — uses only Flask (already installed)

@app.route("/user/export_summary")
def export_summary():
    if "user_email" not in session:
        return redirect("/")

    email = session["user_email"]

    # Fetch all complaints for this user
    user_complaints = list(
        complaints_col.find({"user_email": email}, {"_id": 0})
        .sort("created_at", -1)
    )

    total    = len(user_complaints)
    active   = sum(1 for c in user_complaints if c.get("status") in ["Open", "In Progress"])
    resolved = sum(1 for c in user_complaints if c.get("status") == "Resolved")
    rate     = f"{round((resolved / total) * 100)}%" if total > 0 else "0%"

    # Build complaint rows HTML
    rows_html = ""
    for c in user_complaints:
        date_val = c.get("created_at", "")
        try:
            date_str = date_val.strftime("%d %b %Y") if isinstance(date_val, datetime) else str(date_val)[:10]
        except:
            date_str = "—"

        status = c.get("status", "Open")
        status_colors = {
            "Open":        "background:#fee2e2; color:#991b1b;",
            "In Progress": "background:#fef3c7; color:#92400e;",
            "Resolved":    "background:#dcfce7; color:#166534;",
        }
        badge_style = status_colors.get(status, "background:#f1f5f9; color:#334155;")

        rows_html += f"""
        <tr>
            <td>{c.get('complaint_id', '—')}</td>
            <td>{c.get('assigned_department', '—')}</td>
            <td>{c.get('predicted_category', '—')}</td>
            <td>{c.get('severity', '—')}</td>
            <td><span style="padding:3px 10px; border-radius:5px; font-size:12px; font-weight:700; {badge_style}">{status}</span></td>
            <td>{date_str}</td>
        </tr>
        """

    # Full HTML — browser print dialog lets user Save as PDF
    html = f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <title>Complaint Summary</title>
    <style>
        * {{ margin:0; padding:0; box-sizing:border-box; }}
        body {{ font-family:'Segoe UI',Arial,sans-serif; background:#fff; color:#1e293b; padding:40px; }}

        .header {{ text-align:center; border-bottom:3px solid #3b82f6; padding-bottom:20px; margin-bottom:30px; }}
        .header h1 {{ font-size:26px; color:#0f172a; }}
        .header p  {{ font-size:13px; color:#64748b; margin-top:6px; }}

        .stats {{ display:flex; gap:20px; margin-bottom:30px; }}
        .stat-box {{ flex:1; text-align:center; padding:20px; border-radius:10px; border:1px solid #e2e8f0; }}
        .stat-box .label {{ font-size:11px; color:#64748b; text-transform:uppercase; margin-bottom:8px; }}
        .stat-box .value {{ font-size:32px; font-weight:800; }}

        h2 {{ font-size:15px; color:#0f172a; margin-bottom:12px; padding-bottom:6px; border-bottom:1px solid #e2e8f0; }}

        table {{ width:100%; border-collapse:collapse; font-size:13px; }}
        th {{ background:#0f172a; color:white; padding:10px 12px; text-align:left; font-size:12px; }}
        td {{ padding:10px 12px; border-bottom:1px solid #f1f5f9; }}
        tr:nth-child(even) td {{ background:#f8fafc; }}

        .footer {{ margin-top:30px; text-align:center; font-size:11px; color:#94a3b8; border-top:1px solid #e2e8f0; padding-top:15px; }}

        @media print {{
            body {{ padding:20px; }}
            .no-print {{ display:none; }}
        }}
    </style>
</head>
<body>

    <div class="header">
        <h1>AI Complaint Portal &mdash; Summary Report</h1>
        <p>Account: <strong>{email}</strong> &nbsp;|&nbsp; Generated: {datetime.utcnow().strftime("%d %b %Y, %H:%M")} UTC</p>
    </div>

    <div class="stats">
        <div class="stat-box">
            <div class="label">Total Filed</div>
            <div class="value" style="color:#3b82f6;">{total}</div>
        </div>
        <div class="stat-box">
            <div class="label">Active</div>
            <div class="value" style="color:#f59e0b;">{active}</div>
        </div>
        <div class="stat-box">
            <div class="label">Resolved</div>
            <div class="value" style="color:#10b981;">{resolved}</div>
        </div>
        <div class="stat-box">
            <div class="label">Resolution Rate</div>
            <div class="value" style="color:#8b5cf6;">{rate}</div>
        </div>
    </div>

    <h2>All Complaints</h2>
    <table>
        <thead>
            <tr>
                <th>Complaint ID</th>
                <th>Department</th>
                <th>Category</th>
                <th>Severity</th>
                <th>Status</th>
                <th>Date</th>
            </tr>
        </thead>
        <tbody>
            {rows_html if rows_html else '<tr><td colspan="6" style="text-align:center;color:#94a3b8;padding:20px;">No complaints found.</td></tr>'}
        </tbody>
    </table>

    <div class="footer">
        This report was automatically generated by the AI Complaint Portal.
    </div>

    <script>
        window.onload = function() {{ window.print(); }}
    </script>

</body>
</html>"""

    return html, 200, {"Content-Type": "text/html; charset=utf-8"}

# ----------------
# FIX: Track complaint — strips leading '#', backfills history for old complaints
# ----------------
@app.route("/track_complaint/<path:complaint_id>")
def track_complaint(complaint_id):
    # Strip '#' if user/frontend accidentally passes it
    complaint_id = complaint_id.lstrip("#").strip()

    complaint = complaints_col.find_one(
        {"complaint_id": {"$regex": f"^{re.escape(complaint_id)}$", "$options": "i"}},
        {"_id": 0}
    )

    if complaint:
        # Backfill history for old complaints submitted before history tracking was added
        if not complaint.get("history"):
            complaint["history"] = [{
                "status": complaint.get("status", "Open"),
                "updated_at": complaint.get("created_at", datetime.utcnow()).isoformat()
                              if isinstance(complaint.get("created_at"), datetime)
                              else str(complaint.get("created_at", "")),
                "comment": "Complaint filed (historical record)"
            }]
        return jsonify(complaint), 200

    return jsonify({"error": "Not found"}), 404


# ---------------- RUN ----------------
if __name__ == "__main__":
    app.run(debug=True)