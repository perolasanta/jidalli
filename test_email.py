# test_email.py
import asyncio
from fastapi_mail import FastMail, MessageSchema, ConnectionConfig

async def test_email():
    conf = ConnectionConfig(
        MAIL_USERNAME="y652edb617cd423",
        MAIL_PASSWORD="78c2d63880cfb2",
        MAIL_FROM="test@example.com",
        MAIL_PORT=2525,
        MAIL_SERVER="sandbox.smtp.mailtrap.io",
        MAIL_STARTTLS=True,
        MAIL_SSL_TLS=False,
        USE_CREDENTIALS=True,
        VALIDATE_CERTS=True
    )
    
    message = MessageSchema(
        subject="Test Email",
        recipients=["test@example.com"],
        body="This is a test email from Tournament Manager",
        subtype="plain"
    )
    
    fm = FastMail(conf)
    try:
        await fm.send_message(message)
        print("✓ Email sent successfully!")
    except Exception as e:
        print(f"✗ Error: {e}")

if __name__ == "__main__":
    asyncio.run(test_email())