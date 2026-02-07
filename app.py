import imaplib
import email
import os
import re
import sys
from flask import Flask, request, jsonify
from dotenv import load_dotenv
from html import unescape

# ---------------- BASIC SETUP ----------------
load_dotenv()
sys.stdout.reconfigure(encoding="utf-8")

EMAIL_HOST = os.getenv("EMAIL_HOST", "imap.gmail.com")
EMAIL_USER = os.getenv("EMAIL_USER")
EMAIL_PASS = os.getenv("EMAIL_PASS")
API_SECRET = os.getenv("API_SECRET")

app = Flask(__name__)

# ---------------- HELPERS ----------------
def clean_html(raw_html: str) -> str:
    if not raw_html:
        return ""

    # fix Paytm non-breaking space issue
    raw_html = raw_html.replace("\xa0", " ")

    # remove HTML tags
    text = re.sub(r"<[^>]+>", " ", raw_html)

    # decode html entities
    text = unescape(text)

    # normalize spaces
    text = re.sub(r"\s+", " ", text).strip()
    return text


def extract_amount(text: str):
    """
    Matches:
    ₹2 | ₹ 2 | ₹2.00 | Rs.2 | Rs 2.00
    """
    if not text:
        return None

    match = re.search(
        r"(₹|rs\.?)\s*([0-9]+(?:\.[0-9]{1,2})?)",
        text,
        re.IGNORECASE
    )
    if match:
        return float(match.group(2))
    return None


def check_paytm_transaction():
    try:
        mail = imaplib.IMAP4_SSL(EMAIL_HOST)
        mail.login(EMAIL_USER, EMAIL_PASS)
        mail.select("inbox")

        # ONLY official Paytm mails
        status, messages = mail.search(
            None,
            '(FROM "no-reply@paytm.com")'
        )
        if status != "OK":
            mail.logout()
            return False, None

        mail_ids = messages[0].split()[-40:]  # last 40 mails

        for num in reversed(mail_ids):
            _, msg_data = mail.fetch(num, "(RFC822)")
            for response in msg_data:
                if not isinstance(response, tuple):
                    continue

                msg = email.message_from_bytes(response[1])
                subject = msg.get("Subject", "")

                full_text = ""

                if msg.is_multipart():
                    for part in msg.walk():
                        if part.get_content_type() in ("text/html", "text/plain"):
                            payload = part.get_payload(decode=True)
                            if payload:
                                full_text += payload.decode("utf-8", errors="ignore")
                else:
                    payload = msg.get_payload(decode=True)
                    if payload:
                        full_text = payload.decode("utf-8", errors="ignore")

                cleaned = clean_html(full_text + " " + subject)
                amount = extract_amount(cleaned)

                if amount is not None:
                    mail.logout()
                    return True, amount

        mail.logout()
        return False, None

    except Exception as e:
        print("ERROR:", str(e).encode("utf-8", errors="ignore"))
        return False, None


# ---------------- ROUTES ----------------
@app.route("/verify-paytm", methods=["POST"])
def verify_paytm():
    if request.headers.get("x-api-key") != API_SECRET:
        return jsonify({
            "success": False,
            "message": "Unauthorized"
        }), 401

    verified, amount = check_paytm_transaction()

    return jsonify({
        "success": True,
        "verified": verified,
        "amount": amount
    })


@app.route("/", methods=["GET"])
def home():
    return "Paytm Verify API Running"


# ---------------- RUN ----------------
if __name__ == "__main__":
    app.run()
