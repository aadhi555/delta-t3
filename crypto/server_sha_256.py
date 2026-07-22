from flask import Flask, jsonify, request
import hashlib

app = Flask(__name__)

PIN = "4812"       # secret PIN, kept server-side only
SALT = "salt"

def compute_hash(pin: str) -> str:
    return hashlib.sha256((pin + SALT).encode()).hexdigest()

@app.route("/get-flag-hash", methods=["GET"])
def get_flag_hash():
    return jsonify({
        "message": "Find the 4-digit PIN whose MD5(PIN+salt) matches this hash.",
        "hash": compute_hash(PIN)
    })

@app.route("/submit-pin", methods=["POST"])
def submit_pin():
    data = request.get_json()
    guess = data.get("pin", "")
    if compute_hash(guess) == compute_hash(PIN):
        return jsonify({"success": True, "flag": "CTF{md5_pin_cracked}"})
    return jsonify({"success": False}), 401

if __name__ == "__main__":
    app.run(port=5001)