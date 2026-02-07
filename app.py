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
    # Rs. 2.00 | Rs 2 | ₹2.00
    match = re.search(r"(Rs\.?|₹)\s*([0-9]+(?:\.[0-9]{1,2})?)", text, re.IGNORECASE)
    if match:
        return float(match.group(2))
    return None


def check_paytm_transaction(txn_id):
    try:
        mail = imaplib.IMAP4_SSL(EMAIL_HOST)
        mail.login(EMAIL_USER, EMAIL_PASS)
        mail.select("inbox")

        # 🔥 SUBJECT based search (IMPORTANT)
        status, messages = mail.search(
            None,
            '(SUBJECT "paid" SUBJECT "Payment" SUBJECT "received")'
        )

        if status != "OK":
            return False, None

        mail_ids = messages[0].split()[-30:]  # last 30 mails

        for num in mail_ids:
            _, msg_data = mail.fetch(num, "(RFC822)")
            for response in msg_data:
                if not isinstance(response, tuple):
                    continue

                msg = email.message_from_bytes(response[1])

                full_text = ""

                if msg.is_multipart():
                    for part in msg.walk():
                        content_type = part.get_content_type()
                        if content_type in ["text/plain", "text/html"]:
                            payload = part.get_payload(decode=True)
                            if payload:
                                full_text += payload.decode(errors="ignore")
                else:
                    payload = msg.get_payload(decode=True)
                    if payload:
                        full_text = payload.decode(errors="ignore")

                # 🔍 TXN ID match
                if txn_id in full_text:
                    amount = extract_amount(full_text)
                    mail.logout()
                    return True, amount

        mail.logout()
        return False, None

    except Exception as e:
        print("ERROR:", e)
        return False, None


@app.route("/verify-paytm", methods=["POST"])
def verify_paytm():
    if request.headers.get("x-api-key") != API_SECRET:
        return jsonify({"success": False, "message": "Unauthorized"}), 401

    data = request.get_json()
    txn_id = data.get("txn_id")

    if not txn_id:
        return jsonify({"success": False, "message": "Transaction ID required"}), 400

    verified, amount = check_paytm_transaction(txn_id)

    return jsonify({
        "success": True,
        "verified": verified,
        "amount": amount
    })


@app.route("/", methods=["GET"])
def home():
    return "Paytm Verify API Running"
