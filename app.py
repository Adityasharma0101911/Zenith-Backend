# this is the main entry point for the zenith backend

# import flask to create the web server
from flask import Flask, jsonify, request

# import cors so the frontend can talk to the backend
from flask_cors import CORS

# secure password hashing
from werkzeug.security import generate_password_hash, check_password_hash

# import secrets to generate secure tokens
import secrets

# import os to access environment variables
import os

# import dotenv to load secure keys from .env file
from dotenv import load_dotenv

# this loads environment variables from the .env file
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

# run the server on port 5000
if __name__ == "__main__":
    # initialize the database before starting the server
    init_db()
    app.run(debug=True, port=5000)
