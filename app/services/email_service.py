import smtplib
import logging
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from datetime import datetime
from typing import List, Dict, Any, Optional
from app.config import Config

logger = logging.getLogger("fraud_agent.email_service")

class EmailService:
    """Production SMTP Email Dispatcher for Fraud Operations."""

    @staticmethod
    def _create_smtp_connection():
        """Establishes and authenticates an SMTP connection."""
        host = Config.SMTP_HOST
        port = Config.SMTP_PORT
        user = Config.SMTP_USER
        password = Config.SMTP_PASSWORD
        use_tls = Config.SMTP_USE_TLS

        if not user or not password:
            raise ValueError("SMTP credentials (SMTP_USER, SMTP_PASSWORD) are not configured in environment.")

        server = smtplib.SMTP(host, port, timeout=15)
        if use_tls:
            server.starttls()
        server.login(user, password)
        return server

    @classmethod
    def send_evidence_request_email(
        cls,
        to_email: str,
        customer_name: str,
        case_reference: str,
        portal_url: str,
        requested_documents: List[Any],
        reason: str,
        expires_at: str
    ) -> Dict[str, Any]:
        """
        Dispatches an official, branded HTML evidence request email with the secure portal link.
        """
        if not to_email:
            logger.warning("[EMAIL] Cannot send evidence request: empty recipient address.")
            return {"success": False, "error": "Empty recipient email"}

        from_email = Config.SMTP_FROM_EMAIL or Config.SMTP_USER
        subject = f"Action Required: Transaction Verification Request [{case_reference}]"

        # Format requested documents checklist
        doc_items_html = ""
        doc_items_text = ""
        for doc in requested_documents:
            label = doc.get("label", doc.get("key", str(doc))) if isinstance(doc, dict) else str(doc)
            doc_items_html += f"<li style='margin-bottom: 6px;'><strong>{label}</strong></li>"
            doc_items_text += f" - {label}\n"

        if not doc_items_html:
            doc_items_html = "<li><strong>Government Photo ID & Purchase Proof</strong></li>"
            doc_items_text = " - Government Photo ID & Purchase Proof\n"

        # Format readable expiry date
        expiry_display = expires_at
        try:
            dt = datetime.fromisoformat(expires_at.replace("Z", "+00:00"))
            expiry_display = dt.strftime("%d %b %Y, %I:%M %p UTC")
        except Exception:
            pass

        # HTML Body
        html_content = f"""<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <title>{subject}</title>
</head>
<body style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; background-color: #F1F5F9; margin: 0; padding: 24px;">
  <div style="max-width: 600px; margin: 0 auto; background: #FFFFFF; border-radius: 12px; overflow: hidden; border: 1px solid #E2E8F0; box-shadow: 0 4px 6px -1px rgba(0,0,0,0.05);">
    
    <!-- Header -->
    <div style="background-color: #0F172A; padding: 24px 32px; color: #FFFFFF;">
      <div style="font-size: 11px; font-weight: 700; text-transform: uppercase; letter-spacing: 0.08em; color: #FF5A14; margin-bottom: 4px;">
        Fraud &amp; Risk Operations Desk
      </div>
      <h1 style="margin: 0; font-size: 20px; font-weight: 700;">Action Required: Transaction Verification</h1>
    </div>

    <!-- Body -->
    <div style="padding: 32px; color: #334155; font-size: 14px; line-height: 1.6;">
      <p style="margin-top: 0;">Dear <strong>{customer_name or 'Account Holder'}</strong>,</p>
      
      <p>
        As part of our continuous fraud monitoring and account protection protocols, our compliance desk requires additional documentation to substantiate a recent high-priority transaction.
      </p>

      <!-- Case summary card -->
      <div style="background-color: #F8FAFC; border-left: 4px solid #FF5A14; padding: 14px 18px; margin: 20px 0; border-radius: 0 8px 8px 0;">
        <div style="font-size: 12px; color: #64748B;">Case Reference:</div>
        <div style="font-size: 16px; font-weight: 700; color: #0F172A; font-family: monospace;">{case_reference}</div>
        <div style="margin-top: 8px; font-size: 13px;"><strong>Verification Reason:</strong> {reason}</div>
      </div>

      <p style="margin-bottom: 8px;"><strong>Requested Verification Documents:</strong></p>
      <ul style="margin-top: 0; padding-left: 20px; color: #1E293B;">
        {doc_items_html}
      </ul>

      <!-- CTA Button -->
      <div style="text-align: center; margin: 32px 0;">
        <a href="{portal_url}" style="background-color: #FF5A14; color: #FFFFFF; text-decoration: none; padding: 14px 28px; border-radius: 8px; font-weight: 700; font-size: 15px; display: inline-block; box-shadow: 0 4px 6px -1px rgba(255, 90, 20, 0.3);">
          Open Evidence Submission Portal &rarr;
        </a>
      </div>

      <div style="background-color: #EFF6FF; border: 1px solid #BFDBFE; border-radius: 8px; padding: 12px 16px; font-size: 12px; color: #1E40AF; margin-bottom: 24px;">
        <strong>Security Notice:</strong> This link is cryptographically protected and valid until <strong>{expiry_display}</strong>. You will be required to complete a 2-factor OTP challenge to verify your identity before uploading.
      </div>

      <p style="font-size: 12px; color: #64748B; word-break: break-all;">
        If the button above does not work, copy and paste this link into your browser:<br>
        <a href="{portal_url}" style="color: #2563EB;">{portal_url}</a>
      </p>
    </div>

    <!-- Footer -->
    <div style="background-color: #F8FAFC; padding: 16px 32px; border-top: 1px solid #E2E8F0; font-size: 11px; color: #94A3B8; text-align: center;">
      This is an automated security transmission. If you did not authorize this activity, please contact our 24/7 Security Operations Center immediately.
    </div>
  </div>
</body>
</html>
"""

        # Plain Text Fallback
        text_content = f"""Action Required: Transaction Verification Request [{case_reference}]

Dear {customer_name or 'Account Holder'},

Our compliance desk requires supporting documentation for a recent transaction.

Case Reference: {case_reference}
Verification Reason: {reason}

Requested Documents:
{doc_items_text}

Submit your evidence and transaction statement at the secure portal:
{portal_url}

Link expires on: {expiry_display}
"""

        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = f"Fraud & Compliance Operations <{from_email}>"
        msg["To"] = to_email
        msg.attach(MIMEText(text_content, "plain"))
        msg.attach(MIMEText(html_content, "html"))

        try:
            server = cls._create_smtp_connection()
            server.sendmail(from_email, [to_email], msg.as_string())
            server.quit()
            logger.info(f"[EMAIL_SUCCESS] Dispatched evidence request email to {to_email} (Case: {case_reference})")
            return {"success": True, "recipient": to_email}
        except Exception as e:
            logger.error(f"[EMAIL_ERROR] Failed to send evidence request email to {to_email}: {e}")
            return {"success": False, "error": str(e)}

    @classmethod
    def send_otp_email(
        cls,
        to_email: str,
        customer_name: str,
        otp_code: str,
        expires_minutes: int = 10
    ) -> Dict[str, Any]:
        """
        Dispatches a 6-digit OTP verification code email.
        """
        if not to_email:
            return {"success": False, "error": "Empty recipient email"}

        from_email = Config.SMTP_FROM_EMAIL or Config.SMTP_USER
        subject = f"{otp_code} is your Verification Code - Evidence Submission Portal"

        html_content = f"""<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <title>{subject}</title>
</head>
<body style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background-color: #F8FAFC; margin: 0; padding: 24px;">
  <div style="max-width: 500px; margin: 0 auto; background: #FFFFFF; border-radius: 12px; padding: 32px; border: 1px solid #E2E8F0; text-align: center;">
    <div style="font-size: 11px; font-weight: 700; color: #FF5A14; text-transform: uppercase; letter-spacing: 0.08em; margin-bottom: 8px;">
      Identity Verification
    </div>
    <h2 style="margin: 0 0 12px; font-size: 20px; color: #0F172A;">Your One-Time Passcode</h2>
    <p style="color: #475569; font-size: 14px; line-height: 1.5; margin-bottom: 24px;">
      Use the 6-digit verification code below to authenticate and access the Evidence Submission Portal.
    </p>

    <!-- OTP Code Box -->
    <div style="background-color: #F1F5F9; border: 2px dashed #CBD5E1; border-radius: 10px; padding: 18px; margin-bottom: 24px;">
      <span style="font-family: monospace; font-size: 34px; font-weight: 800; letter-spacing: 8px; color: #0F172A;">
        {otp_code}
      </span>
    </div>

    <p style="font-size: 12px; color: #64748B; margin-bottom: 16px;">
      This code is valid for <strong>{expires_minutes} minutes</strong>. For your security, never share this code with anyone.
    </p>

    <div style="border-top: 1px solid #E2E8F0; padding-top: 16px; font-size: 11px; color: #94A3B8;">
      Fraud Prevention &amp; Account Protection Desk
    </div>
  </div>
</body>
</html>
"""

        text_content = f"""Your verification code is: {otp_code}

Valid for {expires_minutes} minutes.
Never share this code with anyone.

Fraud & Compliance Operations
"""

        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = f"Fraud & Compliance Desk <{from_email}>"
        msg["To"] = to_email
        msg.attach(MIMEText(text_content, "plain"))
        msg.attach(MIMEText(html_content, "html"))

        try:
            server = cls._create_smtp_connection()
            server.sendmail(from_email, [to_email], msg.as_string())
            server.quit()
            logger.info(f"[EMAIL_SUCCESS] Dispatched OTP '{otp_code}' to {to_email}")
            return {"success": True, "recipient": to_email}
        except Exception as e:
            logger.error(f"[EMAIL_ERROR] Failed to send OTP email to {to_email}: {e}")
            return {"success": False, "error": str(e)}

