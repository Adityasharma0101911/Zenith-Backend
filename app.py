# main entry point for the zenith backend

from flask import Flask, jsonify, request
from flask_cors import CORS
from werkzeug.security import generate_password_hash, check_password_hash
import secrets
import os
import json
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))

from database import init_db, get_db_connection
from ai_service import get_ai_advice
from backboard_service import chat_with_ai, build_context_message, reset_ai_cache
import re
import time

app = Flask(__name__)
CORS(app, resources={r"/api/*": {"origins": "*", "methods": ["GET", "POST", "OPTIONS"], "allow_headers": ["Content-Type", "Authorization"]}})

# --- PII censoring utility ---
# strips names and locations before sending user text to ai
def censor_pii(text):
    if not text:
        return text
    # common place-related words and proper nouns (capitalized words of 2+ chars)
    # replace capitalized proper-noun sequences that look like names/places
    censored = re.sub(r'\b[A-Z][a-z]{1,}(?:\s+[A-Z][a-z]{1,})+\b', '[REDACTED]', text)
    # also redact emails
    censored = re.sub(r'[\w.+-]+@[\w-]+\.[\w.-]+', '[EMAIL]', censored)
    return censored

# handle cors preflight for all routes
@app.before_request
def handle_preflight():
    if request.method == "OPTIONS":
        resp = app.make_default_options_response()
        resp.headers["Access-Control-Allow-Origin"] = "*"
        resp.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
        resp.headers["Access-Control-Allow-Headers"] = "Content-Type, Authorization"
        return resp

# ensure tables exist on startup
init_db()

# this checks if the user's token is valid
def get_user_from_token():
    # get the authorization header from the request
    auth_header = request.headers.get("Authorization")

    # if there is no header, return nothing
    if not auth_header:
        return None

    # extract the token from "Bearer <token>"
    token = auth_header.replace("Bearer ", "")

    # open a connection to the database
    conn = get_db_connection()

    # find the user with this token
    user = conn.execute("SELECT * FROM users WHERE token = ?", (token,)).fetchone()

    # close the connection
    conn.close()

    # return the user row or None
    return user

# this is the home route that tells us the backend is running
@app.route("/")
def home():
    return jsonify({"message": "Zenith Backend Online"})

# handles user registration
@app.route("/api/register", methods=["POST"])
def register():
    # get username and password from the request body
    data = request.json
    username = data["username"]
    password = data["password"]

    # hash the password so we never store plain text
    hashed_password = generate_password_hash(password)

    # this generates a secure token for the session
    token = secrets.token_hex(16)

    # open a connection to the database
    conn = get_db_connection()

    try:
        # insert the new user with the hashed password and token
        conn.execute("INSERT INTO users (username, password, token) VALUES (?, ?, ?)", (username, hashed_password, token))

        # save the changes to the database
        conn.commit()
    except Exception:
        conn.close()
        return jsonify({"error": "username already taken"}), 409

    # close the connection
    conn.close()

    # return a success message with the token
    return jsonify({"message": "user registered successfully", "token": token})

# handles user login
@app.route("/api/login", methods=["POST"])
def login():
    # get username and password from the request body
    data = request.json
    username = data["username"]
    password = data["password"]

    # open a connection to the database
    conn = get_db_connection()

    # find the user in the database by username
    user = conn.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()

    # this checks if the password is correct
    if user and check_password_hash(user["password"], password):
        # this generates a secure token for the session
        token = secrets.token_hex(16)

        # save the new token to the database for this user
        conn.execute("UPDATE users SET token = ? WHERE id = ?", (token, user["id"]))
        conn.commit()
        conn.close()

        # password matches so return success with the token
        return jsonify({"success": True, "token": token})
    else:
        # close the connection
        conn.close()

        # wrong username or password so return 401
        return jsonify({"error": "invalid username or password"}), 401

# logs user out by clearing their token
@app.route("/api/logout", methods=["POST"])
def logout():
    user = get_user_from_token()
    if not user:
        return jsonify({"error": "unauthorized"}), 401

    conn = get_db_connection()
    conn.execute("UPDATE users SET token = NULL WHERE id = ?", (user["id"],))
    conn.commit()
    conn.close()
    return jsonify({"message": "logged out"})

# this saves the onboarding profile to the database
@app.route("/api/onboarding", methods=["POST"])
def onboarding():
    # this secures the route so only logged in users can use it
    user = get_user_from_token()

    # if no valid token, return 401
    if not user:
        return jsonify({"error": "unauthorized"}), 401

    # get the profile data from the request body
    data = request.json
    name = data.get("name", "")
    spending_profile = data.get("spending_profile", "")
    balance = data.get("balance", 0.0)

    # open a connection to the database
    conn = get_db_connection()

    # save the onboarding data to dedicated columns
    conn.execute(
        "UPDATE users SET name = ?, spending_profile = ?, balance = ? WHERE id = ?",
        (name, spending_profile, balance, user["id"])
    )

    # save the changes to the database
    conn.commit()

    # close the connection
    conn.close()

    # return a success message
    return jsonify({"message": "onboarding data saved successfully"})

# handles comprehensive survey data (get or save)
@app.route("/api/survey", methods=["GET", "POST"])
def survey():
    user = get_user_from_token()
    if not user:
        return jsonify({"error": "unauthorized"}), 401

    if request.method == "POST":
        data = request.json
        name = data.get("name", "")
        spending_profile = data.get("spending_profile", "")
        balance = data.get("balance", 0.0)
        stress_level = data.get("stress_level", 1)

        conn = get_db_connection()
        conn.execute(
            "UPDATE users SET name = ?, spending_profile = ?, balance = ?, stress_level = ?, survey_data = ? WHERE id = ?",
            (name, spending_profile, balance, stress_level, json.dumps(data), user["id"]),
        )
        conn.commit()
        conn.close()
        return jsonify({"message": "survey saved"})

    # GET — check if survey is completed and include live balance
    survey_data = user["survey_data"] if "survey_data" in user.keys() else None
    if survey_data:
        parsed = json.loads(survey_data)
        # inject live balance from users table so guardian always shows current
        parsed["balance"] = user["balance"]
        return jsonify({"completed": True, "data": parsed})
    return jsonify({"completed": False})

# this sends the user data to the dashboard
@app.route("/api/user_data", methods=["GET"])
def user_data():
    # check if the user has a valid token
    user = get_user_from_token()

    # if no valid token, return 401
    if not user:
        return jsonify({"error": "unauthorized"}), 401

    # read stress level from the dedicated column
    stress_level = user["stress_level"] if user["stress_level"] else 1

    # this calculates an overall wellness metric
    wellness_score = 100 - (stress_level * 10)

    # return the user info as json
    return jsonify({
        "username": user["username"],
        "name": user["name"] or user["username"],
        "balance": user["balance"],
        "spending_profile": user["spending_profile"],
        "stress_level": stress_level,
        "wellness_score": wellness_score,
        "survey_completed": bool(user["survey_data"] if "survey_data" in user.keys() else None),
    })

# this receives the purchase attempt
@app.route("/api/transaction/attempt", methods=["POST"])
def transaction_attempt():
    # this secures the route so only logged in users can use it
    user = get_user_from_token()

    # if no valid token, return 401
    if not user:
        return jsonify({"error": "unauthorized"}), 401

    # get the amount and item name from the request
    data = request.json
    amount = data["amount"]
    item_name = data["item_name"]

    # get the user's current balance
    user_balance = user["balance"]

    # get the user's stress level from the dedicated column
    stress_level = user["stress_level"] if user["stress_level"] else 0

    # open a connection for transaction logging
    conn = get_db_connection()

    # rule 1: block if the user cannot afford it
    if user_balance < amount:
        # log the blocked purchase attempt to the ledger
        conn.execute(
            "INSERT INTO transactions (user_id, item_name, amount, status) VALUES (?, ?, ?, ?)",
            (user["id"], item_name, amount, "BLOCKED")
        )
        conn.commit()
        conn.close()
        return jsonify({"status": "BLOCKED", "reason": "Insufficient funds."})

    # rule 2: block if the user is stressed and spending too much
    if stress_level > 7 and amount > 50:
        # log the blocked purchase attempt to the ledger
        conn.execute(
            "INSERT INTO transactions (user_id, item_name, amount, status) VALUES (?, ?, ?, ?)",
            (user["id"], item_name, amount, "BLOCKED")
        )
        conn.commit()
        conn.close()
        return jsonify({"status": "BLOCKED", "reason": "High stress impulse buy detected."})

    # rule 3: if we get here the purchase is allowed
    new_balance = user_balance - amount
    conn.execute("UPDATE users SET balance = ? WHERE id = ?", (new_balance, user["id"]))

    # log the allowed purchase to the ledger
    conn.execute(
        "INSERT INTO transactions (user_id, item_name, amount, status) VALUES (?, ?, ?, ?)",
        (user["id"], item_name, amount, "ALLOWED")
    )

    # save the changes to the database
    conn.commit()

    # close the connection
    conn.close()

    # return that the purchase was allowed
    return jsonify({"status": "ALLOWED", "amount": amount, "new_balance": new_balance})

# allows the user to update their balance manually
@app.route("/api/balance", methods=["POST"])
def update_balance():
    user = get_user_from_token()
    if not user:
        return jsonify({"error": "unauthorized"}), 401
    data = request.json
    new_balance = float(data.get("balance", 0))
    conn = get_db_connection()
    conn.execute("UPDATE users SET balance = ? WHERE id = ?", (new_balance, user["id"]))
    conn.commit()
    conn.close()
    return jsonify({"message": "balance updated", "balance": new_balance})

# this updates the user stress level in the database
@app.route("/api/update_stress", methods=["POST"])
def update_stress():
    # this secures the route so only logged in users can use it
    user = get_user_from_token()

    # if no valid token, return 401
    if not user:
        return jsonify({"error": "unauthorized"}), 401

    # get the new stress level from the request
    data = request.json
    new_stress_level = data["new_stress_level"]

    # open a connection to the database
    conn = get_db_connection()

    # save the new stress level to its dedicated column
    conn.execute("UPDATE users SET stress_level = ? WHERE id = ?", (new_stress_level, user["id"]))

    # save the changes to the database
    conn.commit()

    # close the connection
    conn.close()

    # return a success message
    return jsonify({"message": "stress level updated"})

# this creates the api endpoint to get ai insights
@app.route("/api/ai/insights", methods=["GET"])
def ai_insights():
    # this secures the route so only logged in users can use it
    user = get_user_from_token()

    # if no valid token, return 401
    if not user:
        return jsonify({"error": "unauthorized"}), 401

    # get the user's balance
    balance = user["balance"]

    # get the spending profile and stress from dedicated columns
    spending_profile = user["spending_profile"] or "Unknown"
    stress_level = user["stress_level"] if user["stress_level"] else 5

    # pass the user data to the ai for analysis
    result = get_ai_advice(spending_profile, balance, stress_level)

    # return the ai advice as json
    return jsonify({"advice": result})

# this forces a high stress low funds state for the demo
@app.route("/api/demo_mode", methods=["POST"])
def demo_mode():
    # this secures the route so only logged in users can use it
    user = get_user_from_token()

    # if no valid token, return 401
    if not user:
        return jsonify({"error": "unauthorized"}), 401

    # open a connection to the database
    conn = get_db_connection()

    # set the balance to 10 dollars and stress to 9 for the demo
    conn.execute(
        "UPDATE users SET balance = ?, stress_level = ? WHERE id = ?",
        (10.0, 9, user["id"])
    )

    # save the changes to the database
    conn.commit()

    # close the connection
    conn.close()

    # return a success message
    return jsonify({"message": "demo mode activated", "balance": 10.0, "stress_level": 9})

# this fetches the user purchase history
@app.route("/api/history", methods=["GET"])
def history():
    # this secures the route so only logged in users can use it
    user = get_user_from_token()

    # if no valid token, return 401
    if not user:
        return jsonify({"error": "unauthorized"}), 401

    # open a connection to the database
    conn = get_db_connection()

    # query the transactions table for this user ordered by newest first
    rows = conn.execute(
        "SELECT item_name, amount, status, timestamp FROM transactions WHERE user_id = ? ORDER BY timestamp DESC",
        (user["id"],)
    ).fetchall()

    # close the connection
    conn.close()

    # convert each row to a dictionary for json
    transactions = []
    for row in rows:
        transactions.append({
            "item_name": row["item_name"],
            "amount": row["amount"],
            "status": row["status"],
            "timestamp": row["timestamp"],
        })

    # return the list as json
    return jsonify({"transactions": transactions})

# proactive ai brief for jarvis-style dashboard (cached per user+section)
@app.route("/api/ai/brief", methods=["POST"])
def ai_brief():
    user = get_user_from_token()
    if not user:
        return jsonify({"error": "unauthorized"}), 401

    data = request.json
    section = data.get("section", "guardian")
    force = data.get("force", False)

    # check cache first (briefs older than 1 hour are stale)
    if not force:
        conn = get_db_connection()
        cached = conn.execute(
            "SELECT brief, created_at FROM ai_briefs WHERE user_id = ? AND section = ?",
            (user["id"], section),
        ).fetchone()
        conn.close()
        if cached:
            # check age — serve cache if under 1 hour old
            try:
                from datetime import datetime
                created = datetime.strptime(cached["created_at"], "%Y-%m-%d %H:%M:%S")
                age_seconds = (datetime.utcnow() - created).total_seconds()
                if age_seconds < 3600:
                    return jsonify({"brief": cached["brief"], "cached": True})
            except Exception:
                # if timestamp parsing fails, serve the cached version anyway
                return jsonify({"brief": cached["brief"], "cached": True})

    # get user survey data
    raw = user["survey_data"] if "survey_data" in user.keys() else None
    survey = json.loads(raw) if raw else {}

    if not survey:
        return jsonify({"brief": "Complete your survey first so I can personalize your experience."})

    # build context from survey
    context = build_context_message(section, survey)

    # section-specific prompts for proactive insights
    brief_prompts = {
        "scholar": (
            f"Based on this student's profile: {context}. "
            "Provide a personalized study brief. Start with a short greeting using their name. "
            "Then give exactly 4 specific recommendations as numbered items. "
            "Then give exactly 3 action items they should do this week, prefixed with '> '. "
            "End with one motivational sentence. Be concise, no extra formatting."
        ),
        "guardian": (
            f"Based on this user's financial profile: {context}. "
            "Provide a personalized financial brief. Start with a short greeting using their name. "
            "Then give exactly 4 specific financial insights or recommendations as numbered items. "
            "Then give exactly 3 action items for better money management, prefixed with '> '. "
            "End with one encouraging sentence. Be concise, no extra formatting."
        ),
        "vitals": (
            f"Based on this user's health profile: {context}. "
            "Provide a personalized health brief. Start with a short greeting using their name. "
            "Then give exactly 4 specific health recommendations as numbered items. "
            "Then give exactly 3 action items for this week, prefixed with '> '. "
            "End with one motivational sentence. Be concise, no extra formatting."
        ),
    }

    prompt = brief_prompts.get(section, brief_prompts["guardian"])
    response = chat_with_ai(user["id"], section, prompt, survey)

    # cache the brief for this user+section
    conn = get_db_connection()
    conn.execute(
        "INSERT OR REPLACE INTO ai_briefs (user_id, section, brief, created_at) VALUES (?, ?, ?, datetime('now'))",
        (user["id"], section, response),
    )
    conn.commit()
    conn.close()

    return jsonify({"brief": response, "cached": False})


# resets cached ai assistants and threads so they get recreated clean
@app.route("/api/ai/reset", methods=["POST"])
def ai_reset():
    user = get_user_from_token()
    if not user:
        return jsonify({"error": "unauthorized"}), 401
    reset_ai_cache()
    return jsonify({"message": "AI cache cleared. Next request will create fresh assistants."})

# ai chat for the three sections (scholar, guardian, vitals)
@app.route("/api/ai/chat", methods=["POST"])
def ai_chat():
    user = get_user_from_token()
    if not user:
        return jsonify({"error": "unauthorized"}), 401

    data = request.json
    section = data.get("section", "guardian")
    message = data.get("message", "")

    # get user survey data for context
    raw = user["survey_data"] if "survey_data" in user.keys() else None
    survey = json.loads(raw) if raw else {}

    # send to backboard ai (censor user message before sending)
    censored_message = censor_pii(message)
    response = chat_with_ai(user["id"], section, censored_message, survey)
    return jsonify({"response": response})

# ai-powered purchase evaluation — asks ai if user should buy it
@app.route("/api/purchase/evaluate", methods=["POST"])
def purchase_evaluate():
    user = get_user_from_token()
    if not user:
        return jsonify({"error": "unauthorized"}), 401

    data = request.json
    item_name = censor_pii(data.get("item_name", ""))
    amount = float(data.get("amount", 0))
    reason = censor_pii(data.get("reason", ""))

    balance = user["balance"]
    stress = user["stress_level"] if user["stress_level"] else 5
    profile = user["spending_profile"] or "Unknown"

    # build prompt for the ai to evaluate the purchase
    prompt = (
        f"The user wants to buy '{item_name}' for ${amount:.2f}. "
        f"Their current balance is ${balance:.2f}, spending profile is '{profile}', stress level is {stress}/10. "
    )
    if reason:
        prompt += f"Their reason: '{reason}'. "
    prompt += (
        "Evaluate whether they should make this purchase. "
        "Consider their financial health, balance, and stress. "
        "Start with either 'APPROVE:' or 'HOLD:' followed by a brief explanation (2-3 sentences). "
        "If you say HOLD, suggest what questions they should ask themselves before buying."
    )

    # get ai evaluation
    raw = user["survey_data"] if "survey_data" in user.keys() else None
    survey = json.loads(raw) if raw else {}
    ai_response = chat_with_ai(user["id"], "guardian", prompt, survey)

    # parse the ai verdict
    verdict = "hold"
    if ai_response.upper().startswith("APPROVE"):
        verdict = "approve"

    return jsonify({"verdict": verdict, "analysis": ai_response, "item_name": item_name, "amount": amount})

# execute a custom purchase after ai evaluation
@app.route("/api/purchase/execute", methods=["POST"])
def purchase_execute():
    user = get_user_from_token()
    if not user:
        return jsonify({"error": "unauthorized"}), 401

    data = request.json
    item_name = data.get("item_name", "")
    amount = float(data.get("amount", 0))

    balance = user["balance"]
    conn = get_db_connection()

    if balance < amount:
        conn.execute(
            "INSERT INTO transactions (user_id, item_name, amount, status) VALUES (?, ?, ?, ?)",
            (user["id"], item_name, amount, "BLOCKED"),
        )
        conn.commit()
        conn.close()
        return jsonify({"status": "BLOCKED", "reason": "Insufficient funds."})

    new_balance = balance - amount
    conn.execute("UPDATE users SET balance = ? WHERE id = ?", (new_balance, user["id"]))
    conn.execute(
        "INSERT INTO transactions (user_id, item_name, amount, status) VALUES (?, ?, ?, ?)",
        (user["id"], item_name, amount, "ALLOWED"),
    )
    conn.commit()
    conn.close()
    return jsonify({"status": "ALLOWED", "amount": amount, "new_balance": new_balance})

# run the server on port 5000
if __name__ == "__main__":
    # initialize the database before starting the server
    init_db()
    app.run(debug=True, port=5000)
