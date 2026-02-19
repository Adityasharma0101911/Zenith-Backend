# this is the main entry point for the zenith backend

# import flask to create the web server
from flask import Flask, jsonify

# import cors so the frontend can talk to the backend
from flask_cors import CORS

# import init_db to set up the database tables
from database import init_db

# create the flask app
app = Flask(__name__)

# enable cors for all routes so frontend can make requests
CORS(app)

# this is the home route that tells us the backend is running
@app.route("/")
def home():
    return jsonify({"message": "Zenith Backend Online"})

# run the server on port 5000
if __name__ == "__main__":
    # initialize the database before starting the server
    init_db()
    app.run(debug=True, port=5000)
