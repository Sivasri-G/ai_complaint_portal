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
# ... after app = Flask(__name__)
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
complaints_col = db["complaints"] # NEW COLLECTION FOR COMPLAINTS
admins_col = db["admins"]
feedbacks_col = db["feedbacks"] # Collection for Admin Analytics
# ---------------- FRONTEND ROUTES ----------------
def generate_complaint_id():
    today = datetime.utcnow().strftime("%Y%m%d")
    start_of_day = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)

    count = complaints_col.count_documents({
        "created_at": {"$gte": start_of_day}
    }) + 1

    return f"CMP{today}{count:04d}"


@app.route("/") 
def home():
    return send_from_directory(FRONTEND_DIR, "index.html")

@app.route("/complaint_form")
def complaint_page():
    print("🔥 complaint_form route HIT")
    print("FRONTEND_DIR =", FRONTEND_DIR)
    print("Files =", os.listdir(FRONTEND_DIR))

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
        
        # We return 200. We do NOT tell the frontend where to go here.
        # The frontend script.js will handle staying on the index page.
        return jsonify({
            "message": "Login successful",
            "email": user["email"]
        }), 200

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


# Add this route in app.py
@app.route("/get_user_info")
def get_user_info():
    if "user_email" in session:
        return jsonify({"email": session["user_email"]}), 200
    return jsonify({"error": "Not logged in"}), 401

# Ensure this line in submit_complaint matches the frontend key
# Change 'text' to 'description' or vice-versa. Let's use 'description':
@app.route("/submit-complaint", methods=["POST"])
def submit_complaint():

    # ---------- INITIAL SAFE DEFAULTS ----------
    predicted_category = ""
    confidence = 0.0
    severity = None
    assigned_department = ""

    voice_file = None
    image_file = None
    input_type = "text"
 
    voice_text = ""
    image_text = ""
    # ---------- BASIC FORM DATA ----------
    # SECURITY FIX: Only allow submission if a session exists
    if "user_email" not in session:
        return jsonify({"error": "Unauthorized. Please login again."}), 401
    complaint_id = request.form.get("complaint_id")
    name = request.form.get("name")
    # CRITICAL FIX: We ignore request.form.get("email") to prevent the 'jeevi' bug
    # We strictly use the email from the login session
    email = session["user_email"]
    location = request.form.get("location")

    # ---------- TEXT INPUT ----------
    text = request.form.get("description", "").strip()

    # ---------- AUDIO UPLOAD ----------
    voice_file = None
    voice_path = None

    if "audio" in request.files:
        voice = request.files["audio"]

        if voice and voice.filename:
            timestamp = datetime.now().strftime("%Y%m%d%H%M%S")

            ext = os.path.splitext(voice.filename)[1]  # ✅ keep real extension
            voice_file = f"{timestamp}_voice{ext}"
            voice_path = os.path.join(UPLOAD_DIR, voice_file)

            voice.save(voice_path)
            input_type = "voice"

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
    # --------- VOICE TEXT ENHANCEMENT ----------
    voice_text = translated_text.lower()

    if "bus" in voice_text or "buses" in voice_text:
        translated_text += " public transport bus service timing issue"

    if "water" in voice_text:
        translated_text += " water supply issue pipeline problem"

    if "street light" in voice_text or "light" in voice_text:
        translated_text += " electricity street light power issue"

    if "road" in voice_text or "pothole" in voice_text:
        translated_text += " road infrastructure transport issue"

    print("🌐 Translated text:", translated_text)


    print("🎙️ Original voice file:", voice_file)
    if voice_text:
      print("📝 Extracted voice text:", voice_text)

    print("📝 Final extracted text:", final_text)

    # ---------- AI PREDICTION ----------
    predicted_category, confidence = predict_category(translated_text)
    
    # ==================== ADD THIS FIX HERE ====================
    lower_translated = translated_text.lower()
    
    # 1. FIX ROAD MISCLASSIFICATION
    infra_keywords = ["road", "pothole", "bridge", "pavement", "highway", "street light", "சாலை", "பாலம்"]
    if any(word in lower_translated for word in infra_keywords):
        predicted_category = "Road & Infrastructure Issues"
        confidence = 1.0  # Force high confidence for correct routing

    # Continue with existing logic...
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

    # ---------- LOGGING ----------
    print("🧠 AI FINAL INPUT:", final_text)
    print("🧠 AI RESULT:", predicted_category, confidence, severity)

    # ---------- DATABASE INSERT ----------
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
        # ADD THIS LINE:
        "history": [{"status": "Open", "updated_at": datetime.utcnow(), "comment": "Complaint filed"}]
    })
    return jsonify({"message": "Complaint submitted successfully"}), 200


@app.route("/predict-category", methods=["POST"])
def predict_category_api():
        print("🔥 PREDICT API HIT")   # 👈 ADD THIS
        data = request.json
        print("📥 DATA RECEIVED:", data)  # 👈 ADD THIS

        text = data.get("text", "")

        if not text.strip():
            return jsonify({"category": "", "confidence": 0})

        category, confidence = predict_category(text)

        return jsonify({
        "category": category,
        "confidence": round(confidence, 3),
        
    })

@app.route("/check_login")
def check_login():
    if "user_email" in session:
        return jsonify({"status": "logged_in"}), 200
    return jsonify({"status": "not_logged_in"}), 401

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

    # ✅ LOGIN SUCCESS
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
    # This grabs the comment from the admin; defaults if empty
    comment = data.get("comment", "Status updated by admin") 

    if not complaint_id or not new_status:
        return jsonify({"error": "Missing data"}), 400

    # Update the main status AND push a new entry into the history list
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

# --- NEW: EXPORT DEPARTMENT DATA TO CSV ---
@app.route("/admin/export_csv/<path:dept_name>")
def export_csv(dept_name):
    if "admin_email" not in session:
        return redirect("/admin-login")

    # Fetch complaints for this specific department
    complaints = list(complaints_col.find({"assigned_department": dept_name}, {"_id": 0}))
    
    def generate():
        output = io.StringIO()
        writer = csv.writer(output)
        
        # CSV Headers
        writer.writerow(['ID', 'Name', 'Location', 'Text', 'Category', 'Severity', 'Status', 'Date'])
        yield output.getvalue()
        output.seek(0)
        output.truncate(0)

        for c in complaints:
            writer.writerow([
                c.get('complaint_id'),
                c.get('name'),
                c.get('location'),
                c.get('translated_text'),
                c.get('predicted_category'),
                c.get('severity'),
                c.get('status'),
                c.get('created_at')
            ])
            yield output.getvalue()
            output.seek(0)
            output.truncate(0)

    response = Response(generate(), mimetype='text/csv')
    response.headers.set("Content-Disposition", "attachment", filename=f"{dept_name.replace(' ', '_')}_Report.csv")
    return response

# ---------------- ADMIN INTERACTIVE ROUTES ----------------

# 1. This route opens the dept_details.html page
@app.route("/admin/department/<path:dept_name>")
def department_view_route(dept_name):
    if "admin_email" not in session:
        return redirect("/admin-login")
    return send_from_directory(FRONTEND_DIR, "dept_details.html")

# 2. This route provides the DATA for the table inside dept_details.html
@app.route("/admin/department_data/<path:dept_name>")
def get_department_data(dept_name):
    if "admin_email" not in session:
        return jsonify({"error": "Unauthorized"}), 401
    
    # Matches the 'assigned_department' field in your MongoDB
    complaints = list(complaints_col.find({"assigned_department": dept_name}, {"_id": 0}).sort("created_at", -1))
    return jsonify(complaints)

# 3. This route provides the COUNTS for the dashboard cards
@app.route("/admin/stats_by_dept")
def get_stats_for_dashboard():
    if "admin_email" not in session:
        return jsonify({"error": "Unauthorized"}), 401
    
    pipeline = [
        {"$group": {"_id": "$assigned_department", "count": {"$sum": 1}}}
    ]
    results = list(complaints_col.aggregate(pipeline))
    stats = {item["_id"]: item["count"] for item in results if item["_id"]}
    return jsonify(stats)

# 4. Logout Route
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
    # Fetch all complaints submitted by this specific user
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
    
    # Fetch user details (excluding password)
    user = users_col.find_one({"email": session["user_email"]}, {"_id": 0, "password": 0})
    return jsonify(user)

from flask import Flask, request, jsonify, session, send_from_directory
from datetime import datetime

# ... (Existing imports and MongoDB setup) ...

from flask import Flask, request, jsonify, session, send_from_directory
from datetime import datetime

# ... (Existing imports: MongoClient, bcrypt, etc.) ...
@app.route("/user/dashboard_stats")
def get_user_dashboard_stats():
    if "user_email" not in session:
        return jsonify({"error": "Unauthorized"}), 401
    
    email = session["user_email"]
    
    # Fetch user data from DB to get their specific language too
    user_data = users_col.find_one({"email": email})
    
    total = complaints_col.count_documents({"user_email": email})
    active = complaints_col.count_documents({
        "user_email": email, 
        "status": {"$in": ["Open", "In Progress"]}
    })
    resolved = complaints_col.count_documents({"user_email": email, "status": "Resolved"})
    
    # Category Data for Chart
    # Use aggregation to get counts per department for this specific user
    pipeline = [
        {"$match": {"user_email": email}},
        {"$group": {"_id": "$assigned_department", "count": {"$sum": 1}}}
    ]
    categories_cursor = list(complaints_col.aggregate(pipeline))
    category_data = {item["_id"]: item["count"] for item in categories_cursor if item["_id"]}

    # Recent Activity
    all_complaints = list(complaints_col.find({"user_email": email}, {"_id": 0})
                         .sort("created_at", -1))

    # Explicitly return the user_email key to fix the "undefined" error
    return jsonify({
        "total": total,
        "active": active,
        "resolved": resolved,
        "categories": category_data,
        "complaints": all_complaints,
        "user_email": email,
        "language": user_data.get('language', 'en') # Pass the real language from DB
    })

@app.route('/user/update_preferences', methods=['POST'])
def update_preferences():
    # Only pull language, do NOT pull email from the user's request
    lang = request.json.get('language')
    user_email = session.get('user_email') # Use the session email instead of request
    
    db.users.update_one(
        {"email": user_email},
        {"$set": {"preferred_language": lang}}
    )
    return jsonify({"status": "success"})

@app.route('/user/update_profile', methods=['POST'])
def update_profile():
    if 'user_email' not in session:
        return jsonify({"error": "Unauthorized"}), 401
    
    data = request.get_json()
    new_email = data.get('email')
    new_lang = data.get('language')
    old_email = session['user_email']

    # Safety: check if the new email is already taken by another user
    if new_email != old_email:
        if users_col.find_one({"email": new_email}):
            return jsonify({"error": "Email already in use"}), 409

    try:
        # Update user record
        users_col.update_one({"email": old_email}, {"$set": {"email": new_email, "language": new_lang}})
        # Keep complaints linked to the user
        if new_email != old_email:
            complaints_col.update_many({"user_email": old_email}, {"$set": {"user_email": new_email}})
        
        session['user_email'] = new_email 
        return jsonify({"message": "Profile updated successfully"}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    
# FIND your current @app.route('/user/submit_feedback') and REPLACE it with this:
@app.route('/user/submit_feedback', methods=['POST'])
def submit_feedback():
    if "user_email" not in session:
        return jsonify({"error": "Unauthorized"}), 401

    data = request.get_json()
    cid = data.get('complaint_id')
    rating = int(data.get('rating', 5))
    comment = data.get('comment', "").strip()
    
    # 1. Verification: Get Dept Name from the original complaint
    complaint = db.complaints.find_one({"complaint_id": cid})
    dept = complaint.get("assigned_department", "General Administration") if complaint else "General Administration"

    # 2. Modern Feature: Simple Sentiment Analysis
    # We tag feedback so the admin can filter "Angry" users
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
        "sentiment": sentiment, # NEW: Track sentiment for modern UI
        "timestamp": datetime.utcnow()
    }

    db.feedbacks.insert_one(feedback_doc)
    
    # Optional: If rating is 1, we could automatically "Re-open" the complaint
    # if rating == 1:
    #     db.complaints.update_one({"complaint_id": cid}, {"$set": {"status": "Re-opened"}})

    return jsonify({"message": "Feedback stored and analyzed"}), 200   
     
# FIND your current @app.route('/admin/feedback_analytics') and REPLACE it with this:
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
        {"$sort": {"avg_rating": -1}} # Sort by highest rating for the leaderboard
    ]
    
    results = list(db.feedbacks.aggregate(pipeline))
    
    # Format data for the chart and the leaderboard
    chart_data = {res['_id']: round(res['avg_rating'], 1) for res in results}
    
    return jsonify(chart_data)

@app.route('/admin/urgent_feedback')
def urgent_feedback():
    if "admin_email" not in session:
        return jsonify([])
    
    # Fetch feedback flagged as 'Critical' or with low ratings
    low_ratings = list(db.feedbacks.find(
        {"$or": [{"rating": {"$lte": 2}}, {"sentiment": "Critical"}]}, 
        {"_id": 0}
    ).sort("timestamp", -1).limit(8))
    
    return jsonify(low_ratings)


import pdfkit
from flask import render_template, make_response

@app.route("/user/download_receipt/<complaint_id>")
def download_receipt(complaint_id):
    if "user_email" not in session:
        return "Unauthorized", 401
    
    # Fetch complaint details
    complaint = complaints_col.find_one({"complaint_id": complaint_id})
    
    # Create a simple HTML template for the PDF
    html = f"""
    <html>
        <body style="font-family: Arial, sans-serif; padding: 50px;">
            <h1>Complaint Receipt</h1>
            <hr>
            <p><strong>ID:</strong> {complaint['complaint_id']}</p>
            <p><strong>Status:</strong> {complaint['status']}</p>
            <p><strong>Department:</strong> {complaint['assigned_department']}</p>
            <p><strong>Date Filed:</strong> {complaint['created_at']}</p>
            <br>
            <p>Thank you for using the AI Complaint Portal.</p>
        </body>
    </html>
    """
    
    pdf = pdfkit.from_string(html, False)
    response = make_response(pdf)
    response.headers['Content-Type'] = 'application/pdf'
    response.headers['Content-Disposition'] = f'attachment; filename=Receipt_{complaint_id}.pdf'
    return response 


# ---------------- RUN ----------------
if __name__ == "__main__":
    app.run(debug=True)

