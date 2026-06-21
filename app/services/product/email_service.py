"""Email service for transactional emails."""
import logging
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from app.core.config import get_settings

logger = logging.getLogger(__name__)


class EmailService:
    @staticmethod
    def _get_connection():
        settings = get_settings()
        try:
            server = smtplib.SMTP(settings.smtp_host or "localhost", int(settings.smtp_port or 587))
            server.ehlo()
            server.starttls()
            if settings.smtp_username and settings.smtp_password:
                server.login(settings.smtp_username, settings.smtp_password)
            return server
        except Exception as e:
            logger.error(f"SMTP connection failed: {e}")
            return None

    @staticmethod
    def send_email(to_email: str, subject: str, html_body: str, text_body: str = ""):
        settings = get_settings()
        sender = settings.smtp_from_email or "noreply@signalflow.com"
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = sender
        msg["To"] = to_email
        if text_body:
            msg.attach(MIMEText(text_body, "plain"))
        msg.attach(MIMEText(html_body, "html"))
        server = EmailService._get_connection()
        if not server:
            logger.warning(f"Email not sent to {to_email} (no SMTP connection)")
            return False
        try:
            server.sendmail(sender, [to_email], msg.as_string())
            server.quit()
            logger.info(f"Email sent to {to_email}: {subject}")
            return True
        except Exception as e:
            logger.error(f"Failed to send email to {to_email}: {e}")
            return False

    @staticmethod
    def send_password_reset(to_email: str, reset_token: str, user_name: str = ""):
        settings = get_settings()
        frontend_url = settings.frontend_url or "http://localhost:3000"
        reset_url = f"{frontend_url}/reset-password?token={reset_token}"
        html = f"""
        <div style="font-family: Arial, sans-serif; max-width: 480px; margin: 0 auto;">
            <h2 style="color: #1A1A2E;">Reset Your Password</h2>
            <p>Hi{' ' + user_name if user_name else ''},</p>
            <p>We received a request to reset your password. Click the button below to set a new one:</p>
            <a href="{reset_url}" style="display:inline-block;padding:12px 24px;background:#E94560;color:#fff;text-decoration:none;border-radius:6px;font-weight:bold;">Reset Password</a>
            <p style="margin-top:16px;color:#6B7280;font-size:13px;">This link expires in 1 hour. If you didn't request this, you can safely ignore this email.</p>
            <hr style="border:none;border-top:1px solid #E5E7EB;margin:24px 0;">
            <p style="color:#9CA3AF;font-size:12px;">SignalFlow — AI Visibility Platform</p>
        </div>"""
        return EmailService.send_email(to_email, "Reset Your Password — SignalFlow", html)

    @staticmethod
    def send_welcome(to_email: str, user_name: str = ""):
        settings = get_settings()
        frontend_url = settings.frontend_url or "http://localhost:3000"
        html = f"""
        <div style="font-family: Arial, sans-serif; max-width: 480px; margin: 0 auto;">
            <h2 style="color: #1A1A2E;">Welcome to SignalFlow!</h2>
            <p>Hi{' ' + user_name if user_name else ''},</p>
            <p>Your account is ready. Here's how to get started:</p>
            <ol>
                <li><strong>Set up your brand</strong> — Paste your website URL and we'll analyze it automatically.</li>
                <li><strong>Generate personas</strong> — We'll create customer profiles from your brand info.</li>
                <li><strong>Discover opportunities</strong> — Find Reddit threads where your expertise fits.</li>
                <li><strong>Track AI visibility</strong> — Monitor how AI models recommend your brand.</li>
            </ol>
            <a href="{frontend_url}/app/dashboard" style="display:inline-block;padding:12px 24px;background:#E94560;color:#fff;text-decoration:none;border-radius:6px;font-weight:bold;">Go to Dashboard</a>
            <hr style="border:none;border-top:1px solid #E5E7EB;margin:24px 0;">
            <p style="color:#9CA3AF;font-size:12px;">SignalFlow — AI Visibility Platform</p>
        </div>"""
        return EmailService.send_email(to_email, "Welcome to SignalFlow!", html)

    @staticmethod
    def send_invitation(to_email: str, workspace_name: str, inviter_name: str, token: str):
        settings = get_settings()
        frontend_url = settings.frontend_url or "http://localhost:3000"
        accept_url = f"{frontend_url}/accept-invite?token={token}"
        html = f"""
        <div style="font-family: Arial, sans-serif; max-width: 480px; margin: 0 auto;">
            <h2 style="color: #1A1A2E;">You're Invited!</h2>
            <p>{inviter_name} invited you to join <strong>{workspace_name}</strong> on SignalFlow.</p>
            <a href="{accept_url}" style="display:inline-block;padding:12px 24px;background:#E94560;color:#fff;text-decoration:none;border-radius:6px;font-weight:bold;">Accept Invitation</a>
            <p style="margin-top:16px;color:#6B7280;font-size:13px;">This invitation expires in 7 days.</p>
            <hr style="border:none;border-top:1px solid #E5E7EB;margin:24px 0;">
            <p style="color:#9CA3AF;font-size:12px;">SignalFlow — AI Visibility Platform</p>
        </div>"""
        return EmailService.send_email(to_email, f"Join {workspace_name} on SignalFlow", html)

    @staticmethod
    def send_visibility_alert(to_email: str, brand_name: str, model_name: str, old_sov: float, new_sov: float):
        change = new_sov - old_sov
        direction = "dropped" if change < 0 else "increased"
        html = f"""
        <div style="font-family: Arial, sans-serif; max-width: 480px; margin: 0 auto;">
            <h2 style="color: {'#E74C3C' if change < 0 else '#16A085'};">Visibility Alert</h2>
            <p>Your brand <strong>{brand_name}</strong> share of voice on <strong>{model_name}</strong> has {direction} by {abs(change):.1f}%.</p>
            <p>Previous: {old_sov:.1f}% → Current: {new_sov:.1f}%</p>
            <a href="#" style="display:inline-block;padding:12px 24px;background:#0F3460;color:#fff;text-decoration:none;border-radius:6px;font-weight:bold;">View Details</a>
            <hr style="border:none;border-top:1px solid #E5E7EB;margin:24px 0;">
            <p style="color:#9CA3AF;font-size:12px;">SignalFlow — AI Visibility Platform</p>
        </div>"""
        return EmailService.send_email(to_email, f"Visibility {direction.title()}: {brand_name} on {model_name}", html)
