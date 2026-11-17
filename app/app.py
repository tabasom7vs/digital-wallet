
from flask import Flask, request, jsonify
import sqlite3
import secrets
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__)

DATABASE = "wallet.db"


def get_db():
    return sqlite3.connect(DATABASE)


def init_db():
    db = get_db()

    db.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password TEXT NOT NULL,
            balance REAL DEFAULT 0,
            token TEXT
        )
    """)

    db.execute("""
        CREATE TABLE IF NOT EXISTS transactions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            sender TEXT NOT NULL,
            receiver TEXT NOT NULL,
            amount REAL NOT NULL,
            type TEXT NOT NULL,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    """)

    db.commit()
    db.close()


def get_user():
    token = request.headers.get("Authorization", "").replace("Bearer ", "")

    if not token:
        return None

    db = get_db()
    user = db.execute(
        "SELECT id, username, balance FROM users WHERE token = ?",
        (token,)
    ).fetchone()
    db.close()

    return user


@app.route("/")
def home():
    return jsonify({"message": "Digital Wallet API is running"})


@app.route("/api/register", methods=["POST"])
def register():
    data = request.get_json() or {}

    username = data.get("username")
    password = data.get("password")

    if not username or not password:
        return jsonify({"error": "Username and password are required"}), 400

    db = get_db()

    try:
        hashed_password = generate_password_hash(password)

        db.execute(
            "INSERT INTO users (username, password) VALUES (?, ?)",
            (username, hashed_password)
        )

        db.commit()
        return jsonify({"message": "Account created successfully"}), 201

    except sqlite3.IntegrityError:
        return jsonify({"error": "Username already exists"}), 409

    finally:
        db.close()


@app.route("/api/login", methods=["POST"])
def login():
    data = request.get_json() or {}

    username = data.get("username")
    password = data.get("password")

    db = get_db()

    user = db.execute(
        "SELECT id, password FROM users WHERE username = ?",
        (username,)
    ).fetchone()

    if not user or not check_password_hash(user[1], password or ""):
        db.close()
        return jsonify({"error": "Invalid username or password"}), 401

    token = secrets.token_hex(32)

    db.execute(
        "UPDATE users SET token = ? WHERE id = ?",
        (token, user[0])
    )

    db.commit()
    db.close()

    return jsonify({
        "message": "Login successful",
        "token": token
    })


@app.route("/api/profile")
def profile():
    user = get_user()

    if not user:
        return jsonify({"error": "Unauthorized"}), 401

    return jsonify({
        "id": user[0],
        "username": user[1],
        "balance": user[2]
    })


@app.route("/api/deposit", methods=["POST"])
def deposit():
    user = get_user()

    if not user:
        return jsonify({"error": "Unauthorized"}), 401

    data = request.get_json() or {}
    amount = data.get("amount")

    if isinstance(amount, bool) or not isinstance(amount, (int, float)) or amount <= 0:
        return jsonify({"error": "Invalid amount"}), 400

    db = get_db()

    db.execute(
        "UPDATE users SET balance = balance + ? WHERE id = ?",
        (amount, user[0])
    )

    db.execute(
        """INSERT INTO transactions (sender, receiver, amount, type)
           VALUES (?, ?, ?, ?)""",
        ("SYSTEM", user[1], amount, "deposit")
    )

    db.commit()
    db.close()

    return jsonify({"message": "Deposit successful"})


@app.route("/api/transfer", methods=["POST"])
def transfer():
    user = get_user()

    if not user:
        return jsonify({"error": "Unauthorized"}), 401

    data = request.get_json() or {}

    receiver = data.get("receiver")
    amount = data.get("amount")

    if not receiver or isinstance(amount, bool) or not isinstance(amount, (int, float)) or amount <= 0:
        return jsonify({"error": "Invalid receiver or amount"}), 400

    if receiver == user[1]:
        return jsonify({"error": "Cannot transfer to yourself"}), 400

    db = get_db()

    try:
        db.execute("BEGIN IMMEDIATE")

        sender = db.execute(
            "SELECT balance FROM users WHERE id = ?",
            (user[0],)
        ).fetchone()

        target = db.execute(
            "SELECT id FROM users WHERE username = ?",
            (receiver,)
        ).fetchone()

        if not target:
            db.rollback()
            return jsonify({"error": "Receiver not found"}), 404

        if sender[0] < amount:
            db.rollback()
            return jsonify({"error": "Insufficient balance"}), 400

        db.execute(
            "UPDATE users SET balance = balance - ? WHERE id = ?",
            (amount, user[0])
        )

        db.execute(
            "UPDATE users SET balance = balance + ? WHERE id = ?",
            (amount, target[0])
        )

        db.execute(
            """INSERT INTO transactions (sender, receiver, amount, type)
               VALUES (?, ?, ?, ?)""",
            (user[1], receiver, amount, "transfer")
        )

        db.commit()

        return jsonify({"message": "Transfer successful"})

    except Exception:
        db.rollback()
        return jsonify({"error": "Transfer failed"}), 500

    finally:
        db.close()


@app.route("/api/transactions")
def transactions():
    user = get_user()

    if not user:
        return jsonify({"error": "Unauthorized"}), 401

    db = get_db()

    records = db.execute(
        """SELECT sender, receiver, amount, type, created_at
           FROM transactions
           WHERE sender = ? OR receiver = ?
           ORDER BY id DESC""",
        (user[1], user[1])
    ).fetchall()

    db.close()

    result = [
        {
            "sender": row[0],
            "receiver": row[1],
            "amount": row[2],
            "type": row[3],
            "date": row[4]
        }
        for row in records
    ]

    return jsonify(result)


if __name__ == "__main__":
    init_db()
    app.run(host="0.0.0.0", port=5000)
