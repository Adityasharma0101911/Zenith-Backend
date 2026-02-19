# this is the main entry point for the zenith backend

# import flask to create the web server
from flask import Flask, jsonify, request

# import cors so the frontend can talk to the backend
from flask_cors import CORS

# import database functions
from database import init_db, get_db_connection

# create the flask app
app = Flask(__name__)

# enable cors for all routes so frontend can make requests
CORS(app)

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

    # open a connection to the database
    conn = get_db_connection()

    # insert the new user into the users table
    conn.execute("INSERT INTO users (username, password) VALUES (?, ?)", (username, password))

    # save the changes to the database
    conn.commit()

    # close the connection
    conn.close()

    # return a success message
    return jsonify({"message": "user registered successfully"})

# run the server on port 5000
if __name__ == "__main__":
    # initialize the database before starting the server
    init_db()
    app.run(debug=True, port=5000)
