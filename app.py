# this is the main entry point for the zenith backend

# import flask to create the web server
from flask import Flask, jsonify, request

# import cors so the frontend can talk to the backend
from flask_cors import CORS

# secure password hashing for ibm z compliance
from werkzeug.security import generate_password_hash, check_password_hash

# import secrets to generate secure tokens
import secrets

# import json to handle survey data
import json

# import os to access environment variables
import os

# import dotenv to load secure keys from .env file
from dotenv import load_dotenv

# this loads secure environment variables for enterprise compliance
load_dotenv()

# import database functions
from database import init_db, get_db_connection

# import the ai service for insights
from ai_service import get_ai_advice

# create the flask app
app = Flask(__name__)

# enable cors for all routes so frontend can make requests
CORS(app)

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

    # insert the new user with the hashed password and token
    conn.execute("INSERT INTO users (username, password, token) VALUES (?, ?, ?)", (username, hashed_password, token))

    # save the changes to the database
    conn.commit()

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

# this saves the survey to the database
@app.route("/api/onboarding", methods=["POST"])
def onboarding():
    # this secures the route so only logged in users can use it
    user = get_user_from_token()

    # if no valid token, return 401
    if not user:
        return jsonify({"error": "unauthorized"}), 401

    # get the survey data from the request body
    data = request.json
    dosha = data["dosha"]
    stress_level = data["stress_level"]
    balance = data["balance"]

    # open a connection to the database
    conn = get_db_connection()

    # build the survey answers into a string to store
    survey_json = json.dumps({"dosha": dosha, "stress_level": stress_level, "balance": balance})

    # this column stores the survey answers
    conn.execute("UPDATE users SET survey_data = ? WHERE id = ?", (survey_json, user["id"]))

    # save the changes to the database
    conn.commit()

    # close the connection
    conn.close()

    # return a success message
    return jsonify({"message": "onboarding data saved successfully"})

# this sends the user data to the dashboard
@app.route("/api/user_data", methods=["GET"])
def user_data():
    # check if the user has a valid token
    user = get_user_from_token()

    # if no valid token, return 401
    if not user:
        return jsonify({"error": "unauthorized"}), 401

    # parse the survey data if it exists
    dosha = None
    stress_level = 5
    if user["survey_data"]:
        survey = json.loads(user["survey_data"])
        dosha = survey.get("dosha")
        # try to get stress level as a number
        try:
            stress_level = int(survey.get("stress_level", 5))
        except (ValueError, TypeError):
            stress_level = 5

    # this calculates an overall wellness metric
    wellness_score = 100 - (stress_level * 10)

    # return the user info as json
    return jsonify({
        "username": user["username"],
        "balance": user["balance"],
        "dosha": dosha,
        "wellness_score": wellness_score,
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

    # get the user's stress level from their survey data
    stress_level = 0
    if user["survey_data"]:
        survey = json.loads(user["survey_data"])
        # try to get stress level as a number
        try:
            stress_level = int(survey.get("stress_level", 0))
        except (ValueError, TypeError):
            stress_level = 0

    # open a connection for transaction logging
    conn = get_db_connection()

    # this blocks the purchase if the user is broke
    if user_balance < amount:
        # this logs the blocked purchase attempt to the ledger
        conn.execute(
            "INSERT INTO transactions (user_id, item_name, amount, status) VALUES (?, ?, ?, ?)",
            (user["id"], item_name, amount, "BLOCKED")
        )
        conn.commit()
        conn.close()
        return jsonify({"status": "BLOCKED", "reason": "Insufficient funds."})

    # this blocks the purchase if the user is stressed and spending too much
    if stress_level > 7 and amount > 50:
        # this logs the blocked purchase attempt to the ledger
        conn.execute(
            "INSERT INTO transactions (user_id, item_name, amount, status) VALUES (?, ?, ?, ?)",
            (user["id"], item_name, amount, "BLOCKED")
        )
        conn.commit()
        conn.close()
        return jsonify({"status": "BLOCKED", "reason": "High stress detected. Impulse purchase blocked."})

    # if we get here, the purchase is allowed
    # deduct the amount from the user's balance
    new_balance = user_balance - amount
    conn.execute("UPDATE users SET balance = ? WHERE id = ?", (new_balance, user["id"]))

    # this logs the allowed purchase to the ledger
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

    # load the existing survey data or start fresh
    survey = {}
    if user["survey_data"]:
        survey = json.loads(user["survey_data"])

    # update the stress level in the survey data
    survey["stress_level"] = new_stress_level

    # open a connection to the database
    conn = get_db_connection()

    # save the updated survey data back to the database
    conn.execute("UPDATE users SET survey_data = ? WHERE id = ?", (json.dumps(survey), user["id"]))

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

    # get the dosha and stress from survey data
    dosha = "Unknown"
    stress_level = 5
    if user["survey_data"]:
        survey = json.loads(user["survey_data"])
        dosha = survey.get("dosha", "Unknown")
        # try to get stress level as a number
        try:
            stress_level = int(survey.get("stress_level", 5))
        except (ValueError, TypeError):
            stress_level = 5

    # pass the user data to the ai for analysis
    result = get_ai_advice(dosha, balance, stress_level)

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

    # load the existing survey data or start fresh
    survey = {}
    if user["survey_data"]:
        survey = json.loads(user["survey_data"])

    # set stress to 9 for the demo
    survey["stress_level"] = 9

    # open a connection to the database
    conn = get_db_connection()

    # set the balance to 10 dollars for the demo
    conn.execute("UPDATE users SET balance = ?, survey_data = ? WHERE id = ?",
                 (10.0, json.dumps(survey), user["id"]))

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

# run the server on port 5000
if __name__ == "__main__":
    # initialize the database before starting the server
    init_db()
    app.run(debug=True, port=5000)
