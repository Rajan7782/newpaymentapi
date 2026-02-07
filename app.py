import imaplib
import email
import os
import re
from flask import Flask, request, jsonify
from dotenv import load_dotenv

load_dotenv()

EMAIL_HOST = os.getenv("EMAIL_HOST", "imap.gmail.com")
EMAIL_USER = os.getenv("EMAIL_USER")
EMAIL_PASS = os.getenv("EMAIL_PASS")
API_SECRET = os.getenv("API_SECRET")

app = Flask(__name__)

def extract_amount(text):
    """
    Extracts amount like: Rs. 2.00 or ₹2.00
    """
    match = re.search(r"(Rs\.?|₹)\s?([0-9]+(?:\.[0-9]{1,2})?)", text)
    if match:
        return float(match.group(2))
    return None


def check_paytm_transaction(txn_id):
    try:
        mail = imaplib.IMAP4_SSL(EMAIL_HOST)
        mail.login(EMAIL_USER, EMAIL_PASS)
        mail.select("inbox")

        status, messages = mail.search(None, '(FROM "paytm.com")')
        if status != "OK":
            return False, None

        mail_ids = messages[0].split()[-20:]  # last 20 mails

        for num in mail_ids:
            _, msg_data = mail.fetch(num, "(RFC822)")
            for response in msg_data:
                if isinstance(response, tuple):
                    msg = email.message_from_bytes(response[1])

                    body = ""
                    if msg.is_multipart():
                        for part in msg.walk():
                            if part.get_content_type() == "text/plain":
                                body += part.get_payload(decode=True).decode(errors="ignore")
                    else:
                        body = msg.get_payload(decode=True).decode(errors="ignore")

                    # 🔍 TXN ID match
                    if txn_id in body:
                        amount = extract_amount(body)
                        mail.logout()
                        return True, amount

        mail.logout()
        return False, None

    except Exception as e:
        print("ERROR:", e)
        return False, None


@app.route("/verify-paytm", methods=["POST"])
def verify_paytm():
    secret = request.headers.get("x-api-key")
    if secret != API_SECRET:
        return jsonify({"success": False, "message": "Unauthorized"}), 401

    data = request.get_json()
    txn_id = data.get("txn_id")

    if not txn_id:
        return jsonify({
            "success": False,
            "message": "Transaction ID required"
        }), 400

    verified, amount = check_paytm_transaction(txn_id)

    return jsonify({
        "success": True,
        "verified": verified,
        "amount": amount
    })


@app.route("/", methods=["GET"])
def home():
    return "Paytm Verify API Running"
