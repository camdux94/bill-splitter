import os
import sqlite3
import uuid
from flask import Flask, request, jsonify, render_template
from flask_cors import CORS
from dotenv import load_dotenv

from receipt_ocr import extract_receipt
from split_logic import compute_tally, payment_links

load_dotenv()
app = Flask(__name__)
CORS(app)

DB_PATH = "bills.db"


def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_db()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS bills (
            bill_id TEXT PRIMARY KEY,
            restaurant_name TEXT,
            tax REAL,
            venmo_handle TEXT,
            cashapp_handle TEXT,
            zelle_handle TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS items (
            item_id TEXT PRIMARY KEY,
            bill_id TEXT,
            name TEXT,
            price REAL,
            quantity INTEGER
        );
        CREATE TABLE IF NOT EXISTS claims (
            bill_id TEXT,
            item_id TEXT,
            person TEXT
        );
        CREATE TABLE IF NOT EXISTS tips (
            bill_id TEXT,
            person TEXT,
            tip_amount REAL,
            PRIMARY KEY (bill_id, person)
        );
        CREATE TABLE IF NOT EXISTS paid_status (
            bill_id TEXT,
            person TEXT,
            paid INTEGER DEFAULT 0,
            PRIMARY KEY (bill_id, person)
        );
    """)
    conn.commit()
    conn.close()


init_db()


@app.route("/")
def index():
    return render_template("create.html")


@app.route("/bill/<bill_id>")
def bill_page(bill_id):
    return render_template("bill.html", bill_id=bill_id)


@app.route("/scan-receipt", methods=["POST"])
def scan_receipt():
    if "image" not in request.files:
        return jsonify({"error": "No image uploaded."}), 400
    file = request.files["image"]
    image_bytes = file.read()
    media_type = file.mimetype or "image/jpeg"

    result = extract_receipt(image_bytes, media_type)
    if "error" in result:
        return jsonify(result), 400
    return jsonify(result)


@app.route("/create-bill", methods=["POST"])
def create_bill():
    data = request.json or {}
    restaurant_name = data.get("restaurant_name", "Bill").strip() or "Bill"
    items = data.get("items", [])
    tax = float(data.get("tax", 0))
    venmo = data.get("venmo_handle", "").strip() or None
    cashapp = data.get("cashapp_handle", "").strip() or None
    zelle = data.get("zelle_handle", "").strip() or None

    if not items:
        return jsonify({"error": "A bill needs at least one item."}), 400

    bill_id = uuid.uuid4().hex[:10]
    conn = get_db()
    conn.execute(
        "INSERT INTO bills (bill_id, restaurant_name, tax, venmo_handle, cashapp_handle, zelle_handle) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (bill_id, restaurant_name, tax, venmo, cashapp, zelle)
    )
    for item in items:
        item_id = uuid.uuid4().hex[:10]
        conn.execute(
            "INSERT INTO items (item_id, bill_id, name, price, quantity) VALUES (?, ?, ?, ?, ?)",
            (item_id, bill_id, item.get("name", "Item"), float(item.get("price", 0)), int(item.get("quantity", 1)))
        )
    conn.commit()
    conn.close()

    return jsonify({"bill_id": bill_id})


@app.route("/bill/<bill_id>/data", methods=["GET"])
def bill_data(bill_id):
    conn = get_db()
    bill = conn.execute("SELECT * FROM bills WHERE bill_id = ?", (bill_id,)).fetchone()
    if not bill:
        conn.close()
        return jsonify({"error": "Bill not found."}), 404

    items = conn.execute("SELECT * FROM items WHERE bill_id = ?", (bill_id,)).fetchall()
    claims = conn.execute("SELECT * FROM claims WHERE bill_id = ?", (bill_id,)).fetchall()
    tips_rows = conn.execute("SELECT * FROM tips WHERE bill_id = ?", (bill_id,)).fetchall()
    paid_rows = conn.execute("SELECT * FROM paid_status WHERE bill_id = ?", (bill_id,)).fetchall()
    conn.close()

    items_list = [dict(i) for i in items]
    claims_list = [dict(c) for c in claims]
    tips = {r["person"]: r["tip_amount"] for r in tips_rows}
    paid = {r["person"]: bool(r["paid"]) for r in paid_rows}

    tally = compute_tally(items_list, claims_list, bill["tax"], tips)
    bill_subtotal = tally.pop("_bill_subtotal", 0)

    handles = {
        "venmo": bill["venmo_handle"],
        "cashapp": bill["cashapp_handle"],
        "zelle": bill["zelle_handle"],
    }

    people_data = {}
    for person, t in tally.items():
        links = payment_links(handles, t["total"], note=f"{bill['restaurant_name']} split")
        people_data[person] = {
            **t,
            "paid": paid.get(person, False),
            "payment_links": links,
        }

    return jsonify({
        "bill_id": bill_id,
        "restaurant_name": bill["restaurant_name"],
        "tax": bill["tax"],
        "bill_subtotal": bill_subtotal,
        "items": items_list,
        "claims": claims_list,
        "people": people_data,
        "handles_set": {k: v is not None for k, v in handles.items()},
    })


@app.route("/bill/<bill_id>/claim", methods=["POST"])
def claim_items(bill_id):
    data = request.json or {}
    person = data.get("person", "").strip()
    item_ids = data.get("item_ids", [])

    if not person:
        return jsonify({"error": "Please provide a name."}), 400

    conn = get_db()
    # Replace this person's claims wholesale — simpler than diffing, and the
    # frontend always sends the person's full current selection.
    conn.execute("DELETE FROM claims WHERE bill_id = ? AND person = ?", (bill_id, person))
    for item_id in item_ids:
        conn.execute("INSERT INTO claims (bill_id, item_id, person) VALUES (?, ?, ?)", (bill_id, item_id, person))
    conn.commit()
    conn.close()

    return jsonify({"status": "ok"})


@app.route("/bill/<bill_id>/tip", methods=["POST"])
def set_tip(bill_id):
    data = request.json or {}
    person = data.get("person", "").strip()
    tip_amount = float(data.get("tip_amount", 0))

    if not person:
        return jsonify({"error": "Please provide a name."}), 400

    conn = get_db()
    conn.execute(
        "INSERT INTO tips (bill_id, person, tip_amount) VALUES (?, ?, ?) "
        "ON CONFLICT(bill_id, person) DO UPDATE SET tip_amount = excluded.tip_amount",
        (bill_id, person, tip_amount)
    )
    conn.commit()
    conn.close()

    return jsonify({"status": "ok"})


@app.route("/bill/<bill_id>/paid", methods=["POST"])
def set_paid(bill_id):
    data = request.json or {}
    person = data.get("person", "").strip()
    paid = bool(data.get("paid", False))

    if not person:
        return jsonify({"error": "Please provide a name."}), 400

    conn = get_db()
    conn.execute(
        "INSERT INTO paid_status (bill_id, person, paid) VALUES (?, ?, ?) "
        "ON CONFLICT(bill_id, person) DO UPDATE SET paid = excluded.paid",
        (bill_id, person, int(paid))
    )
    conn.commit()
    conn.close()

    return jsonify({"status": "ok"})


if __name__ == "__main__":
    app.run(debug=True)
