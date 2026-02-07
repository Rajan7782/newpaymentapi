import imaplib
import email
from email.header import decode_header
import re
import os
from flask import Flask, request, jsonify
from dotenv import load_dotenv
from html import unescape

# ---------- ENV LOAD ----------
load_dotenv()

EMAIL_HOST = os.getenv("EMAIL_HOST", "imap.gmail.com")
EMAIL_USER = os.getenv("EMAIL_USER")
EMAIL_PASS = os.getenv("EMAIL_PASS")
API_SECRET = os.getenv("API_SECRET")

ALLOWED_FROM = ["no-reply@paytm.com"]

SEARCH_KEYWORDS = [
    "payment received",
    "paytm for business",
    "paid",
    "credited",
    "rs."
]

app = Flask(__name__)

# ---------- HELPERS ----------

def clean_text(text: str) -> str:
    if not text:
        return ""

    # remove non-breaking space
    text = text.replace("\xa0", " ")

    # decode html entities
    text = unescape(text)

    # remove html tags
    text = re.sub(r"<[^>]+>", " ", text)

    # normalize spaces
    return re.sub(r"\s+", " ", text).strip()


def parse_amount(text: str):
    m = re.search(
        r"(₹|rs\.?)\s*([0-9]+(?:\.[0-9]{1,2})?)",
        text,
        re.IGNORECASE,
    )
    if m:
        return float(m.group(2))
    return None


def connect_imap():
    mail = imaplib.IMAP4_SSL(EMAIL_HOST)
    mail.login(EMAIL_USER, EMAIL_PASS)
    mail.select("INBOX")
    return mail


def fetch_latest_paytm_payment():
    mail = connect_imap()

    status, messages = mail.search(None, '(FROM "no-reply@paytm.com")')
    if status != "OK":
        mail.logout()
        return None

    ids = messages[0].split()[-30:]  # last 30 emails

    for msg_id in reversed(ids):
        _, msg_data = mail.fetch(msg_id, "(RFC822)")
        msg = email.message_from_bytes(msg_data[0][1])

        from_header = (msg.get("From") or "").lower()
        if not any(a in from_header for a in ALLOWED_FROM):
            continue

        # subject
        subject_raw, enc = decode_header(msg.get("Subject"))[0]
        if isinstance(subject_raw, bytes):
            subject = subject_raw.decode(enc or "utf-8", errors="ignore")
        else:
            subject = subject_raw or ""

        # body
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
        if amount is None:
            continue

        mail.logout()
        return {
            "amount": amount,
            "subject": subject,
            "from": msg.get("From"),
            "time": msg.get("Date"),
        }

    mail.logout()
    return None


# ---------- ROUTES ----------

@app.post("/verify-paytm")
def verify_paytm():
    if request.headers.get("x-api-key") != API_SECRET:
        return jsonify({"success": False, "message": "Unauthorized"}), 401

    payment = fetch_latest_paytm_payment()

    if not payment:
        return jsonify({
            "success": True,
            "verified": False,
            "amount": None
        })

    return jsonify({
        "success": True,
        "verified": True,
        "amount": payment["amount"],
        "details": payment
    })


@app.get("/")
def home():
    return "Paytm Verify API Running"


if __name__ == "__main__":
    port = int(os.getenv("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
