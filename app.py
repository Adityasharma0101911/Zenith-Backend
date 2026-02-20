# main entry point for the zenith backend

from flask import Flask, jsonify, request, g
from flask_cors import CORS
from werkzeug.security import generate_password_hash, check_password_hash
import secrets
import os
import json
from dotenv import load_dotenv
from concurrent.futures import ThreadPoolExecutor

load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))

from database import init_db, get_db_connection
from ai_service import get_ai_advice
from backboard_service import chat_with_ai, build_context_message, reset_ai_cache
import re
import time

app = Flask(__name__)
CORS(app, resources={r"/api/*": {"origins": "*", "methods": ["GET", "POST", "OPTIONS"], "allow_headers": ["Content-Type", "Authorization"]}})

# thread pool for offloading blocking ai calls so the server stays responsive
ai_executor = ThreadPoolExecutor(max_workers=4)

# --- per-request db connection using flask g ---
# this opens one connection per request and reuses it everywhere
def get_db():
    if "db" not in g:
        g.db = get_db_connection()
    return g.db

@app.teardown_appcontext
def close_db(exception):
    db = g.pop("db", None)
    if db is not None:
        db.close()

# --- PII censoring utility ---
# strips names and locations before sending user text to ai
def censor_pii(text):
    if not text:
        return text
    # common place-related words and proper nouns (capitalized words of 2+ chars)
    # replace capitalized proper-noun sequences that look like names/places
    censored = re.sub(r'\b[A-Z][a-z]{2,}(?:\s+[A-Z][a-z]{2,}){2,}\b', '[REDACTED]', text)
    # also redact emails
    censored = re.sub(r'[\w.+-]+@[\w-]+\.[\w.-]+', '[EMAIL]', censored)
    return censored

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

    # use the per-request db connection instead of opening a new one
    conn = get_db()

    # find the user with this token
    user = conn.execute("SELECT * FROM users WHERE token = ?", (token,)).fetchone()

    # return the user row or None (connection stays open for the rest of the request)
    return user

# this is the home route that tells us the backend is running
@app.route("/")
def home():
    return jsonify({"message": "Zenith Backend Online"})

# lightweight health check — no tokens spent, no threads created
@app.route("/api/health")
def health():
    server_ok = True
    ai_ok = False
    try:
        # just check if backboard api responds to a simple GET (no messages sent)
        import requests as req
        base = os.getenv("BACKBOARD_BASE_URL", "https://app.backboard.io/api")
        key = os.getenv("BACKBOARD_API_KEY")
        r = req.get(f"{base}/assistants", headers={"X-API-Key": key}, timeout=5)
        ai_ok = r.status_code in (200, 401, 403)  # any response = api is reachable
    except Exception:
        ai_ok = False
    return jsonify({"server": server_ok, "ai": ai_ok})

# handles user registration
@app.route("/api/register", methods=["POST"])
def register():
    # get username and password from the request body
    data = request.json
    if not data or "username" not in data or "password" not in data:
        return jsonify({"error": "username and password are required"}), 400
    username = data["username"]
    password = data["password"]

    # hash the password so we never store plain text
    hashed_password = generate_password_hash(password)

    # this generates a secure token for the session
    token = secrets.token_hex(16)

    # use the per-request db connection
    conn = get_db()

    try:
        # insert the new user with the hashed password and token
        conn.execute("INSERT INTO users (username, password, token) VALUES (?, ?, ?)", (username, hashed_password, token))

        # save the changes to the database
        conn.commit()
    except Exception:
        return jsonify({"error": "username already taken"}), 409

    # return a success message with the token
    return jsonify({"message": "user registered successfully", "token": token})

# handles user login
@app.route("/api/login", methods=["POST"])
def login():
    # get username and password from the request body
    data = request.json
    if not data or "username" not in data or "password" not in data:
        return jsonify({"error": "username and password are required"}), 400
    username = data["username"]
    password = data["password"]

    # open a connection to the database
    conn = get_db()

    # find the user in the database by username
    user = conn.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()

    # this checks if the password is correct
    if user and check_password_hash(user["password"], password):
        # this generates a secure token for the session
        token = secrets.token_hex(16)

        # save the new token to the database for this user
        conn.execute("UPDATE users SET token = ? WHERE id = ?", (token, user["id"]))
        conn.commit()

        # password matches so return success with the token
        return jsonify({"success": True, "token": token})
    else:
        # wrong username or password so return 401
        return jsonify({"error": "invalid username or password"}), 401

# logs user out by clearing their token
@app.route("/api/logout", methods=["POST"])
def logout():
    user = get_user_from_token()
    if not user:
        return jsonify({"error": "unauthorized"}), 401

    conn = get_db()
    conn.execute("UPDATE users SET token = NULL WHERE id = ?", (user["id"],))
    conn.commit()
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

    # use the per-request db connection
    conn = get_db()

    # save the onboarding data to dedicated columns
    conn.execute(
        "UPDATE users SET name = ?, spending_profile = ?, balance = ? WHERE id = ?",
        (name, spending_profile, balance, user["id"])
    )

    # save the changes to the database
    conn.commit()

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

        conn = get_db()
        conn.execute(
            "UPDATE users SET name = ?, spending_profile = ?, balance = ?, stress_level = ?, survey_data = ? WHERE id = ?",
            (name, spending_profile, balance, stress_level, json.dumps(data), user["id"]),
        )
        conn.commit()
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
    amount = data.get("amount", 0)
    item_name = data.get("item_name", "")

    if not isinstance(amount, (int, float)) or amount <= 0:
        return jsonify({"error": "Amount must be a positive number"}), 400

    # get the user's stress level from the dedicated column
    stress_level = user["stress_level"] if user["stress_level"] else 0

    # open a connection for transaction logging
    conn = get_db()

    # rule 2: block if the user is stressed and spending too much
    if stress_level > 7 and amount > 50:
        # log the blocked purchase attempt to the ledger
        conn.execute(
            "INSERT INTO transactions (user_id, item_name, amount, status) VALUES (?, ?, ?, ?)",
            (user["id"], item_name, amount, "BLOCKED")
        )
        conn.commit()
        return jsonify({"status": "BLOCKED", "reason": "High stress impulse buy detected."})

    # rule 1: block if the user cannot afford it
    cursor = conn.execute("UPDATE users SET balance = balance - ? WHERE id = ? AND balance >= ?", (amount, user["id"], amount))
    if cursor.rowcount == 0:
        # log the blocked purchase attempt to the ledger
        conn.execute(
            "INSERT INTO transactions (user_id, item_name, amount, status) VALUES (?, ?, ?, ?)",
            (user["id"], item_name, amount, "BLOCKED")
        )
        conn.commit()
        return jsonify({"status": "BLOCKED", "reason": "Insufficient funds."})

    # rule 3: if we get here the purchase is allowed
    new_balance = conn.execute("SELECT balance FROM users WHERE id = ?", (user["id"],)).fetchone()["balance"]

    # log the allowed purchase to the ledger
    conn.execute(
        "INSERT INTO transactions (user_id, item_name, amount, status) VALUES (?, ?, ?, ?)",
        (user["id"], item_name, amount, "ALLOWED")
    )

    # save the changes to the database
    conn.commit()

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
    conn = get_db()
    conn.execute("UPDATE users SET balance = ? WHERE id = ?", (new_balance, user["id"]))
    conn.commit()
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
    conn = get_db()

    # save the new stress level to its dedicated column
    conn.execute("UPDATE users SET stress_level = ? WHERE id = ?", (new_stress_level, user["id"]))

    # log the check-in to the pulse history table for the heatmap
    conn.execute("INSERT INTO pulse_logs (user_id, stress_level) VALUES (?, ?)", (user["id"], new_stress_level))

    # save the changes to the database
    conn.commit()

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
    result = get_ai_advice(user["id"], spending_profile, balance, stress_level)

    # return the ai advice as json
    return jsonify({"advice": result})

# this fetches the user purchase history
@app.route("/api/history", methods=["GET"])
def history():
    # this secures the route so only logged in users can use it
    user = get_user_from_token()

    # if no valid token, return 401
    if not user:
        return jsonify({"error": "unauthorized"}), 401

    # open a connection to the database
    conn = get_db()

    # query the transactions table for this user ordered by newest first
    rows = conn.execute(
        "SELECT item_name, amount, status, timestamp FROM transactions WHERE user_id = ? ORDER BY timestamp DESC",
        (user["id"],)
    ).fetchall()

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

# fetches historical pulse check logs for the calendar heatmap
@app.route("/api/pulse_history", methods=["GET"])
def pulse_history():
    user = get_user_from_token()
    if not user:
        return jsonify({"error": "unauthorized"}), 401

    conn = get_db()
    # retrieve up to 365 days of history
    rows = conn.execute(
        "SELECT stress_level, date(timestamp) as log_date FROM pulse_logs WHERE user_id = ? ORDER BY timestamp DESC LIMIT 365",
        (user["id"],)
    ).fetchall()

    history = [{"stress_level": row["stress_level"], "date": row["log_date"]} for row in rows]
    return jsonify({"history": history})

# proactive ai brief for jarvis-style dashboard (cached per user+section)
@app.route("/api/ai/brief", methods=["POST"])
def ai_brief():
    user = get_user_from_token()
    if not user:
        return jsonify({"error": "unauthorized"}), 401

    data = request.json
    section = data.get("section", "guardian")
    force = data.get("force", False)

    # serve cached brief unless force refresh requested
    if not force:
        conn = get_db()
        cached = conn.execute(
            "SELECT brief FROM ai_briefs WHERE user_id = ? AND section = ?",
            (user["id"], section),
        ).fetchone()
        if cached:
            return jsonify({"brief": cached["brief"], "cached": True})

    # get user survey data
    raw = user["survey_data"] if "survey_data" in user.keys() else None
    survey = json.loads(raw) if raw else {}

    if not survey:
        return jsonify({"brief": "Complete your survey first so I can personalize your experience.\n> What can Zenith do for me?\n> How does the AI personalization work?\n> What data do you need from me?"})

    # build context from survey
    context = build_context_message(section, survey)

    # section-specific prompts for proactive insights — jarvis style
    # format: greeting paragraph, then numbered insights, then > example questions
    brief_prompts = {
        "scholar": (
            f"Based on this student's profile: {context}. "
            "Give a personalized study brief using EXACTLY this format (no markdown, no bold, no bullet points):\n"
            "First, write a warm 2-sentence greeting paragraph about their profile.\n"
            "Then write exactly 3 numbered insights/recommendations (e.g. '1. ...' on separate lines).\n"
            "Then write exactly 3 lines starting with '> ' — these are example questions the student could ask you "
            "(e.g. '> How can I improve my study habits?'). Make them relevant to their profile.\n"
            "End with one short encouraging closing line."
        ),
        "guardian": (
            f"Based on this user's financial profile: {context}. "
            "Give a personalized financial brief using EXACTLY this format (no markdown, no bold, no bullet points):\n"
            "First, write a warm 2-sentence greeting paragraph about their financial profile.\n"
            "Then write exactly 3 numbered insights/recommendations (e.g. '1. ...' on separate lines).\n"
            "Then write exactly 3 lines starting with '> ' — these are example questions the user could ask you "
            "(e.g. '> Should I increase my emergency fund?'). Make them specific to their profile.\n"
            "End with one short encouraging closing line."
        ),
        "vitals": (
            f"Based on this user's health profile: {context}. "
            "Give a personalized health brief using EXACTLY this format (no markdown, no bold, no bullet points):\n"
            "First, write a warm 2-sentence greeting paragraph about their health profile.\n"
            "Then write exactly 3 numbered insights/recommendations (e.g. '1. ...' on separate lines).\n"
            "Then write exactly 3 lines starting with '> ' — these are example questions the user could ask you "
            "(e.g. '> What exercises are best for my goals?'). Make them relevant to their profile.\n"
            "End with one short motivating closing line."
        ),
    }

    prompt = brief_prompts.get(section, brief_prompts["guardian"])

    # offload the blocking ai call to a background thread so other requests aren't blocked
    try:
        future = ai_executor.submit(chat_with_ai, user["id"], section, prompt, survey)
        response = future.result(timeout=60)
    except Exception as e:
        print(f"[AI] brief generation error: {e}")
        response = "I'm having trouble generating your brief right now. Please try refreshing in a moment."

    # cache the brief for this user+section
    conn = get_db()
    conn.execute(
        "INSERT OR REPLACE INTO ai_briefs (user_id, section, brief, created_at) VALUES (?, ?, ?, datetime('now'))",
        (user["id"], section, response),
    )
    conn.commit()

    return jsonify({"brief": response, "cached": False})


# resets cached ai assistants and threads so they get recreated clean
@app.route("/api/ai/reset", methods=["POST"])
def ai_reset():
    user = get_user_from_token()
    if not user:
        return jsonify({"error": "unauthorized"}), 401
    reset_ai_cache(user["id"])
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

    # offload the blocking ai call to a background thread
    try:
        future = ai_executor.submit(chat_with_ai, user["id"], section, censored_message, survey)
        response = future.result(timeout=60)
    except Exception as e:
        print(f"[AI] chat error: {e}")
        response = "Sorry, the AI is taking too long to respond. Please try again."
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

    # build prompt for the ai to evaluate the purchase — jarvis style
    prompt = (
        f"The user wants to buy '{item_name}' for ${amount:.2f}. "
        f"Their current balance is ${balance:.2f}, spending profile is '{profile}', stress level is {stress}/10. "
    )
    if reason:
        prompt += f"Their reason: '{reason}'. "
    prompt += (
        "Evaluate this purchase like a trusted advisor. "
        "Consider their balance, spending habits, and stress level. "
        "You MUST start your response with exactly 'APPROVE:' or 'HOLD:' (this is required for parsing). "
        "Then explain your reasoning conversationally in 2-3 sentences — like you're talking to a friend. "
        "No markdown, no lists, no bold text. Just natural speech. "
        "If you say HOLD, gently nudge them to think about whether they truly need it right now."
    )

    try:
        # get ai evaluation — offload to thread pool
        raw = user["survey_data"] if "survey_data" in user.keys() else None
        survey = json.loads(raw) if raw else {}
        future = ai_executor.submit(chat_with_ai, user["id"], "guardian", prompt, survey)
        ai_response = future.result(timeout=60)

        # parse the ai verdict
        verdict = "hold"
        if ai_response.upper().startswith("APPROVE"):
            verdict = "approve"

        return jsonify({"verdict": verdict, "analysis": ai_response, "item_name": item_name, "amount": amount})
    except Exception as e:
        print(f"[AI] purchase evaluate error: {e}")
        return jsonify({"error": f"AI evaluation failed: {str(e)}"}), 500

# execute a custom purchase after ai evaluation
@app.route("/api/purchase/execute", methods=["POST"])
def purchase_execute():
    user = get_user_from_token()
    if not user:
        return jsonify({"error": "unauthorized"}), 401

    data = request.json
    item_name = data.get("item_name", "")
    amount = float(data.get("amount", 0))

    if amount <= 0:
        return jsonify({"error": "Amount must be positive"}), 400

    conn = get_db()

    cursor = conn.execute("UPDATE users SET balance = balance - ? WHERE id = ? AND balance >= ?", (amount, user["id"], amount))
    if cursor.rowcount == 0:
        conn.execute(
            "INSERT INTO transactions (user_id, item_name, amount, status) VALUES (?, ?, ?, ?)",
            (user["id"], item_name, amount, "BLOCKED"),
        )
        conn.commit()
        return jsonify({"status": "BLOCKED", "reason": "Insufficient funds."})

    new_balance = conn.execute("SELECT balance FROM users WHERE id = ?", (user["id"],)).fetchone()["balance"]
    conn.execute(
        "INSERT INTO transactions (user_id, item_name, amount, status) VALUES (?, ?, ?, ?)",
        (user["id"], item_name, amount, "ALLOWED"),
    )
    conn.commit()
    return jsonify({"status": "ALLOWED", "amount": amount, "new_balance": new_balance})

# add income to balance and log the transaction
@app.route("/api/income", methods=["POST"])
def add_income():
    user = get_user_from_token()
    if not user:
        return jsonify({"error": "unauthorized"}), 401

    data = request.json
    source = data.get("source", "Income")
    amount = float(data.get("amount", 0))

    if amount <= 0:
        return jsonify({"error": "Amount must be positive"}), 400

    conn = get_db()
    conn.execute("UPDATE users SET balance = balance + ? WHERE id = ?", (amount, user["id"]))
    new_balance = conn.execute("SELECT balance FROM users WHERE id = ?", (user["id"],)).fetchone()["balance"]
    conn.execute(
        "INSERT INTO transactions (user_id, item_name, amount, status) VALUES (?, ?, ?, ?)",
        (user["id"], f"Income: {source}", amount, "INCOME"),
    )
    conn.commit()
    return jsonify({"message": "income added", "balance": new_balance})

# run the server on port 5000
if __name__ == "__main__":
    # initialize the database before starting the server
    init_db()
    app.run(debug=True, port=5000)
