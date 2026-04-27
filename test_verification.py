import smtplib
from email.message import EmailMessage

SMTP_USER = "sayaksmnt@gmail.com"
SMTP_PASSWORD = "edtr zrls ulzr capa"  # paste your real App Password
TEST_RECIPIENT = "failing-user-email-here@example.com"  # the email that doesn't receive

msg = EmailMessage()
msg["Subject"] = "Geo Artemis Test"
msg["From"] = f"Geo Artemis <{SMTP_USER}>"
msg["To"] = TEST_RECIPIENT
msg.set_content("This is a test email.")

try:
    with smtplib.SMTP("smtp.gmail.com", 587) as s:
        s.set_debuglevel(2)
        s.starttls()
        s.login(SMTP_USER, SMTP_PASSWORD)
        s.send_message(msg)
        print("\n SUCCESS - email was accepted by Gmail")
except Exception as e:
    print(f"\n FAILED: {e}")