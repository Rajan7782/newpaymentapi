import imaplib
import email
from email.header import decode_header
import re
import os
from flask import Flask, request, jsonify
from dotenv import load_dotenv

# ---------- ENV LOAD ----------
load_dotenv()

EMAIL_HOST = os.getenv("EMAIL_HOST", "imap.gmail.com")
EMAIL_USER = os.getenv("EMAIL_USER")
EMAIL_PASS = os.getenv("EMAIL_PASS")

SEARCH_KEYWORDS = [
    k.strip().lower()
    for k in os.getenv(
        "SEARCH_KEYWORDS",
        "payment received,paytm for business,upi,credited"
    ).split(",")
]

ALLOWED_FROM = [
    s.strip().lower()
    for s in os.getenv("ALLOWED_FROM", "no-reply@paytm.com").split(",")
]

app = Flask(__name__)

# ---------- TEXT CLEANER (🔥 MAIN FIX) ----------

def clean_text(text: str) -> str:
    if not text:
        return ""
    # non-breaking space fix
    text = text.replace("\xa0", " ")
    # normalize spaces
    return re.sub(r"\s+", " ", text).strip()

# ---------- HELPERS ----------

def parse_amount(text: str):
    patterns = [
        r"₹\s*([0-9,]+\.?\d*)",
        r"rs\.?\s*([0-9,]+\.?\d*)",
        r"inr\s*([0-9,]+\.?\d*)",
    ]
    for p in patterns:
        m = re.search(p, text, re.IGNORECASE)
        if m:
            return m.group(1)
    return None


def parse_sender(body: str):
    patterns = [
        r"\b([a-z0-9._-]+@[a-z]{2,15})\b",
        r"bhim\s+upi\s+([a-z0-9._-]+@[a-z]{2,15})",
        r"vpa[:\s]+([a-z0-9._-]+@[a-z]{2,15})",
        r"from[:\s]+([a-z0-9._-]+@[a-z]{2,15})",
    ]
    for p in patterns:
        m = re.search(p, body, re.IGNORECASE)
        if m:
            return m.group(1).strip()
    return None


def parse_order_id(text: str):
    m = re.search(r"order id[:\s]+([a-z0-9]+)", text, re.IGNORECASE)
    if m:
        return m.group(1).strip()
    return None


def connect_imap():
    if not EMAIL_USER or not EMAIL_PASS:
        raise RuntimeError("EMAIL_USER / EMAIL_PASS env vars missing")

    mail = imaplib.IMAP4_SSL(EMAIL_HOST)
    mail.login(EMAIL_USER, EMAIL_PASS)
    mail.select("INBOX")
    return mail


def fetch_transaction(tx_id: str):
    mail = connect_imap()

    status, messages = mail.search(None, f'TEXT "{tx_id}"')
    if status != "OK":
        mail.logout()
        raise Exception("IMAP search failed")

    ids = messages[0].split()

    for msg_id in ids:
        _, msg_data = mail.fetch(msg_id, "(RFC822)")
        msg = email.message_from_bytes(msg_data[0][1])

        from_header = msg.get("From", "") or ""
        if not any(a in from_header.lower() for a in ALLOWED_FROM):
            continue

        subject_raw, encoding = decode_header(msg.get("Subject"))[0]
        subject = (
            subject_raw.decode(encoding or "utf-8", errors="ignore")
            if isinstance(subject_raw, bytes)
            else subject_raw or ""
        )

        body = ""
        if msg.is_multipart():
            for part in msg.walk():
                if part.get_content_type() in ("text/plain", "text/html"):
                    payload = part.get_payload(decode=True)
                    if payload:
                        body += payload.decode("utf-8", errors="ignore")
        else:
            payload = msg.get_payload(decode=True)
            if payload:
                body += payload.decode("utf-8", errors="ignore")

        combined = clean_text(subject + "\n" + body).lower()

        if not any(k in combined for k in SEARCH_KEYWORDS):
            continue

        order_id_in_mail = parse_order_id(combined)
        if not order_id_in_mail or order_id_in_mail.lower() != tx_id.lower():
            continue

        amount = parse_amount(combined)
        sender = parse_sender(combined)
        email_time = msg.get("Date", "")

        mail.logout()
        return {
            "tx_id": tx_id,
            "order_id": order_id_in_mail,
            "amount": amount,
            "sender": sender,
            "subject": subject,
            "time": email_time,
            "from": from_header,
        }

    mail.logout()
    return None


# ---------- TX ID GETTER (GET + POST) ----------

def get_tx_id():
    keys = [
        "tx_id",
        "txn_id",
        "trx",
        "id",
        "transaction_id",
        "transection_id",
    ]

    for key in keys:
        val = request.args.get(key)
        if val and val.strip():
            return val.strip()

    if request.is_json:
        data = request.get_json(silent=True) or {}
        for key in keys:
            val = data.get(key)
            if val and str(val).strip():
                return str(val).strip()

    return None


# ---------- ROUTES ----------

@app.route("/trx", methods=["GET", "POST"])
def trx_api():
    tx_id = get_tx_id()

    if not tx_id:
        return jsonify({
            "ok": False,
            "error": "Missing tx_id. Use GET ?tx_id= or POST JSON body"
        }), 400

    try:
        result = fetch_transaction(tx_id)
    except Exception as e:
        # 🔥 encoding-safe error
        err = str(e).encode("utf-8", errors="ignore").decode("utf-8")
        return jsonify({"ok": False, "error": err}), 500

    if not result:
        return jsonify({
            "ok": True,
            "found": False,
            "message": "No valid Paytm payment email found for this Order ID."
        })

    return jsonify({
        "ok": True,
        "found": True,
        "transaction": result
    })


@app.get("/health")
def health():
    return {"ok": True, "allowed_from": ALLOWED_FROM}


if __name__ == "__main__":
    port = int(os.getenv("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
