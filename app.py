import imaplib
import email
from email.header import decode_header
import re
import os
import sys
from flask import Flask, request, jsonify
from dotenv import load_dotenv

# 🔥 FORCE UTF-8 (MOST IMPORTANT LINE)
sys.stdout.reconfigure(encoding="utf-8")

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

# ---------- CLEANER (ABSOLUTE SAFE) ----------
def clean_text(text: str) -> str:
    if not text:
        return ""
    # remove non-breaking space
    text = text.replace("\xa0", " ")
    # normalize
    text = re.sub(r"\s+", " ", text)
    return text.strip()

# ---------- HELPERS ----------
def parse_amount(text: str):
    m = re.search(
        r"(₹|rs\.?|inr)\s*([0-9]+(?:\.[0-9]{1,2})?)",
        text,
        re.IGNORECASE,
    )
    if m:
        return m.group(2)
    return None


def connect_imap():
    if not EMAIL_USER or not EMAIL_PASS:
        raise RuntimeError("EMAIL_USER or EMAIL_PASS missing")

    mail = imaplib.IMAP4_SSL(EMAIL_HOST)
    mail.login(EMAIL_USER, EMAIL_PASS)
    mail.select("INBOX")
    return mail


def fetch_transaction(tx_id: str):
    mail = connect_imap()

    status, messages = mail.search(None, f'TEXT "{tx_id}"')
    if status != "OK":
        mail.logout()
        return None

    for msg_id in messages[0].split():
        _, msg_data = mail.fetch(msg_id, "(RFC822)")
        msg = email.message_from_bytes(msg_data[0][1])

        from_header = msg.get("From", "").lower()
        if not any(a in from_header for a in ALLOWED_FROM):
            continue

        subject_raw, enc = decode_header(msg.get("Subject"))[0]
        subject = (
            subject_raw.decode(enc or "utf-8", errors="ignore")
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
                body = payload.decode("utf-8", errors="ignore")

        combined = clean_text(subject + " " + body).lower()

        if not any(k in combined for k in SEARCH_KEYWORDS):
            continue

        amount = parse_amount(combined)
        if amount:
            mail.logout()
            return {
                "tx_id": tx_id,
                "amount": amount,
                "from": msg.get("From"),
                "time": msg.get("Date"),
            }

    mail.logout()
    return None


def get_tx_id():
    keys = ["tx_id", "txn_id", "trx", "transaction_id", "transection_id"]

    for k in keys:
        v = request.args.get(k)
        if v:
            return v.strip()

    if request.is_json:
        data = request.get_json(silent=True) or {}
        for k in keys:
            v = data.get(k)
            if v:
                return str(v).strip()

    return None


# ---------- ROUTES ----------
@app.route("/trx", methods=["GET", "POST"])
def trx_api():
    tx_id = get_tx_id()

    if not tx_id:
        return jsonify({"ok": False, "error": "Missing tx_id"}), 400

    try:
        result = fetch_transaction(tx_id)
    except Exception:
        # 🔥 NEVER return raw exception
        return jsonify({
            "ok": False,
            "error": "Internal mail processing error"
        }), 500

    if not result:
        return jsonify({
            "ok": True,
            "found": False
        })

    return jsonify({
        "ok": True,
        "found": True,
        "transaction": result
    })


@app.get("/health")
def health():
    return {"ok": True}


if __name__ == "__main__":
    port = int(os.getenv("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
