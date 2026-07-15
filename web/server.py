from flask import Flask, jsonify, request, make_response
import sqlite3

app = Flask(__name__)
DB = "students.db"

def get_db():
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    return conn

@app.route("/login", methods=["POST"])
def login():
    data = request.get_json()
    roll = data.get("roll_number", "")
    password = data.get("password", "")

    # Intentionally vulnerable: raw string concatenation, no parameterization
    query = f"SELECT * FROM students WHERE roll_number={roll} AND password='{password}'"

    conn = get_db()
    cur = conn.cursor()
    cur.execute(query)
    row = cur.fetchone()
    conn.close()

    if row is None:
        return jsonify({"success": False}), 401

    resp = make_response(jsonify({"success": True}))
    resp.set_cookie("roll_number", str(row["roll_number"]))
    return resp

@app.route("/my-mark", methods=["GET"])
def my_mark():
    roll = request.cookies.get("roll_number")
    if roll is None:
        return jsonify({"error": "not logged in"}), 401

    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT mark FROM students WHERE roll_number=?", (roll,))
    row = cur.fetchone()
    conn.close()

    if row is None:
        return jsonify({"error": "unknown roll number"}), 404

    return jsonify({"roll_number": int(roll), "mark": row["mark"]})

if __name__ == "__main__":
    app.run(port=5001)