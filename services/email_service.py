# ============================================================================
# NEW FILE: services/email_service.py
# Resend.com integration for OTP emails
# ============================================================================

import resend
import os
from typing import Dict, Optional
import logging

logger = logging.getLogger(__name__)

class EmailService:
    def __init__(self):
        # Set Resend API key from environment
        resend.api_key = os.getenv('RESEND_API_KEY')
        self.from_email = os.getenv('RESEND_FROM_EMAIL', 'onboarding@helloyuno.com')
        
        if not resend.api_key:
            logger.warning("RESEND_API_KEY not found in environment variables")
    
    def send_otp_email(self, to_email: str, otp_code: str, user_name: str = None) -> Dict:
        """
        Send OTP verification email using Resend
        
        Args:
            to_email: Recipient email address
            otp_code: 6-digit OTP code
            user_name: Optional user name for personalization
            
        Returns:
            Dict with success status and message
        """
        try:
            # Create personalized greeting
            greeting = f"Hi {user_name}," if user_name else "Hi there,"
            
            # HTML email template
            html_content = f"""
            <!DOCTYPE html>
            <html>
            <head>
                <meta charset="utf-8">
                <meta name="viewport" content="width=device-width, initial-scale=1.0">
                <title>Yuno Verification Code</title>
                <style>
                    body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; margin: 0; padding: 0; background-color: #f5f5f5; }}
                    .container {{ max-width: 600px; margin: 0 auto; background-color: #ffffff; }}
                    .header {{ background: linear-gradient(135deg, #FF6B35 0%, #FF8C42 100%); padding: 40px 20px; text-align: center; }}
                    .logo {{ color: white; font-size: 28px; font-weight: bold; margin: 0; }}
                    .content {{ padding: 40px 20px; }}
                    .otp-code {{ background-color: #f8f9fa; border: 2px dashed #FF6B35; border-radius: 12px; padding: 20px; text-align: center; margin: 30px 0; }}
                    .code {{ font-size: 32px; font-weight: bold; color: #FF6B35; letter-spacing: 8px; font-family: 'Courier New', monospace; }}
                    .footer {{ background-color: #f8f9fa; padding: 20px; text-align: center; color: #666; font-size: 14px; }}
                </style>
            </head>
            <body>
                <div class="container">
                    <div class="header">
                        <h1 class="logo">🤖 Yuno</h1>
                        <p style="color: rgba(255,255,255,0.9); margin: 10px 0 0 0; font-size: 18px;">Your AI chatbot is almost ready!</p>
                    </div>
                    
                    <div class="content">
                        <h2 style="color: #333; margin-bottom: 20px;">{greeting}</h2>
                        
                        <p style="color: #666; line-height: 1.6; font-size: 16px;">
                            Welcome to Yuno! To complete your account setup and start building your AI chatbot, 
                            please verify your email address with the code below:
                        </p>
                        
                        <div class="otp-code">
                            <p style="margin: 0 0 10px 0; color: #666; font-size: 14px;">Your verification code:</p>
                            <div class="code">{otp_code}</div>
                            <p style="margin: 10px 0 0 0; color: #999; font-size: 12px;">This code expires in 10 minutes</p>
                        </div>
                        
                        <p style="color: #666; line-height: 1.6; font-size: 16px;">
                            If you didn't request this verification code, you can safely ignore this email.
                        </p>
                        
                        <p style="color: #666; line-height: 1.6; font-size: 16px;">
                            Need help? Reply to this email or visit our 
                            <a href="https://helloyuno.com/support" style="color: #FF6B35;">support center</a>.
                        </p>
                    </div>
                    
                    <div class="footer">
                        <p>© 2025 Yuno. All rights reserved.</p>
                        <p>
                            <a href="https://helloyuno.com" style="color: #FF6B35; text-decoration: none;">helloyuno.com</a> | 
                            <a href="https://helloyuno.com/privacy" style="color: #666; text-decoration: none;">Privacy Policy</a>
                        </p>
                    </div>
                </div>
            </body>
            </html>
            """
            
            # Plain text fallback
            text_content = f"""
            {greeting}
            
            Welcome to Yuno! To complete your account setup, please verify your email address with this code:
            
            {otp_code}
            
            This code expires in 10 minutes.
            
            If you didn't request this verification code, you can safely ignore this email.
            
            Need help? Visit https://helloyuno.com/support
            
            © 2025 Yuno. All rights reserved.
            """
            
            # Send email via Resend
            params = {
                "from": self.from_email,
                "to": [to_email],
                "subject": f"Your Yuno verification code: {otp_code}",
                "html": html_content,
                "text": text_content,
                "tags": [
                    {"name": "category", "value": "onboarding"},
                    {"name": "type", "value": "otp_verification"}
                ]
            }
            
            # Send the email
            email_response = resend.Emails.send(params)
            
            logger.info(f"OTP email sent successfully to {to_email}, Resend ID: {email_response.get('id', 'unknown')}")
            
            return {
                'success': True,
                'message': 'Verification email sent successfully',
                'email_id': email_response.get('id')
            }
            
        except Exception as e:
            logger.error(f"Failed to send OTP email to {to_email}: {str(e)}")
            return {
                'success': False,
                'error': 'email_send_failed',
                'message': f'Failed to send verification email: {str(e)}'
            }
    
    def send_welcome_email(self, to_email: str, user_name: str, site_id: str) -> Dict:
        """
        Send welcome email after successful onboarding
        """
        try:
            html_content = f"""
            <!DOCTYPE html>
            <html>
            <head>
                <meta charset="utf-8">
                <title>Welcome to Yuno!</title>
                <style>
                    body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; margin: 0; padding: 0; background-color: #f5f5f5; }}
                    .container {{ max-width: 600px; margin: 0 auto; background-color: #ffffff; }}
                    .header {{ background: linear-gradient(135deg, #FF6B35 0%, #FF8C42 100%); padding: 40px 20px; text-align: center; }}
                    .content {{ padding: 40px 20px; }}
                    .button {{ display: inline-block; background: linear-gradient(135deg, #FF6B35 0%, #FF8C42 100%); color: white; padding: 15px 30px; text-decoration: none; border-radius: 8px; font-weight: bold; margin: 20px 0; }}
                </style>
            </head>
            <body>
                <div class="container">
                    <div class="header">
                        <h1 style="color: white; margin: 0;">🎉 Welcome to Yuno!</h1>
                        <p style="color: rgba(255,255,255,0.9); margin: 10px 0 0 0;">Your AI chatbot is ready to go!</p>
                    </div>
                    
                    <div class="content">
                        <h2>Hi {user_name},</h2>
                        
                        <p>Congratulations! Your Yuno AI chatbot has been successfully set up and is ready to engage with your website visitors.</p>
                        
                        <p><strong>Your Site ID:</strong> <code>{site_id}</code></p>
                        
                        <a href="https://dashboard.helloyuno.com" class="button">Go to Dashboard</a>
                        
                        <h3>What's Next?</h3>
                        <ul>
                            <li>Visit your dashboard to customize your chatbot</li>
                            <li>Monitor conversations and analytics</li>
                            <li>Add more content to improve responses</li>
                        </ul>
                        
                        <p>Need help? Our support team is here for you at support@helloyuno.com</p>
                    </div>
                </div>
            </body>
            </html>
            """
            
            params = {
                "from": self.from_email,
                "to": [to_email],
                "subject": "🎉 Welcome to Yuno - Your AI chatbot is ready!",
                "html": html_content,
                "tags": [
                    {"name": "category", "value": "onboarding"},
                    {"name": "type", "value": "welcome"}
                ]
            }
            
            email_response = resend.Emails.send(params)
            
            return {
                'success': True,
                'message': 'Welcome email sent successfully',
                'email_id': email_response.get('id')
            }
            
        except Exception as e:
            logger.error(f"Failed to send welcome email to {to_email}: {str(e)}")
            return {
                'success': False,
                'error': 'email_send_failed',
                'message': f'Failed to send welcome email: {str(e)}'
            }

# ============================================================================
# UPDATED otp_service.py to use Resend instead of SendGrid/SMTP
# ============================================================================

from services.email_service import EmailService

class OTPService:
    def __init__(self):
        self.email_service = EmailService()
        self.supabase = get_supabase_client()
    
    def send_otp(self, email: str) -> Dict:
        """
        Generate and send OTP using Resend email service
        """
        try:
            # Generate 6-digit OTP
            otp_code = str(random.randint(100000, 999999))
            expires_at = datetime.utcnow() + timedelta(minutes=10)
            
            # Store OTP in database
            otp_record = {
                'email': email.lower(),
                'otp_code': otp_code,
                'expires_at': expires_at.isoformat(),
                'is_verified': False,
                'created_at': datetime.utcnow().isoformat()
            }
            
            # Delete any existing OTPs for this email
            self.supabase.table('otp_verifications').delete().eq('email', email.lower()).execute()
            
            # Insert new OTP
            result = self.supabase.table('otp_verifications').insert(otp_record).execute()
            
            if not result.data:
                return {
                    'success': False,
                    'error': 'database_error',
                    'message': 'Failed to store OTP in database'
                }
            
            # Send email via Resend
            email_result = self.email_service.send_otp_email(email, otp_code)
            
            if email_result['success']:
                return {
                    'success': True,
                    'message': 'Verification code sent to your email'
                }
            else:
                # Delete OTP if email failed to send
                self.supabase.table('otp_verifications').delete().eq('email', email.lower()).execute()
                return email_result
                
        except Exception as e:
            logger.error(f"Error in send_otp: {str(e)}")
            return {
                'success': False,
                'error': 'internal_error',
                'message': 'An error occurred while sending verification code'
            }