# import flask to create the web server
from flask import Flask, jsonify

# import cors so the frontend can talk to the backend
from flask_cors import CORS

# import dotenv to load environment variables from .env file
from dotenv import load_dotenv

# load environment variables
load_dotenv()

# create the flask app
app = Flask(__name__)

# enable cors for all routes so frontend can make requests
CORS(app)

# this is the home route that returns a hello world message
@app.route("/")
def hello():
    return jsonify({"message": "Hello World from Zenith Backend!"})

# run the server on port 5000
if __name__ == "__main__":
    app.run(debug=True, port=5000)
