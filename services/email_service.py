# UPDATED: services/email_service.py
# Enhanced with better error handling and debugging

import resend
import os
from typing import Dict, Optional
import logging

logger = logging.getLogger(__name__)

class EmailService:
    def __init__(self):
        # Set Resend API key from environment
        self.api_key = os.getenv('RESEND_API_KEY')
        self.from_email = os.getenv('RESEND_FROM_EMAIL', 'say@helloyuno.com')
        
        # Set the API key for resend module
        if self.api_key:
            resend.api_key = self.api_key
            logger.info(f"✅ Resend API key set: {self.api_key[:10]}...")
        else:
            logger.error("❌ RESEND_API_KEY not found in environment variables")
        
        logger.info(f"📧 From email configured: {self.from_email}")
    
    def send_otp_email(self, to_email: str, otp_code: str, user_name: str = None) -> Dict:
        """
        Send OTP verification email using Resend
        """
        try:
            # Check if API key is available
            if not self.api_key:
                logger.error("❌ No Resend API key available")
                return {
                    'success': False,
                    'error': 'no_api_key',
                    'message': 'Resend API key not configured'
                }
            
            # Create personalized greeting
            greeting = f"Hi {user_name}," if user_name else "Hi there,"
            
            logger.info(f"📧 Preparing to send OTP email from {self.from_email} to {to_email}")
            
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
            
            # Prepare email parameters
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
            
            logger.info(f"📤 Sending email with params: from={self.from_email}, to={to_email}, subject=Your Yuno verification code")
            
            # Send the email
            email_response = resend.Emails.send(params)
            
            # Enhanced logging for response
            logger.info(f"📨 Resend API response type: {type(email_response)}")
            logger.info(f"📨 Resend API response: {email_response}")
            
            if email_response and hasattr(email_response, 'get'):
                email_id = email_response.get('id', 'unknown')
                logger.info(f"✅ OTP email sent successfully to {to_email}, Resend ID: {email_id}")
                
                return {
                    'success': True,
                    'message': 'Verification email sent successfully',
                    'email_id': email_id
                }
            elif email_response:
                # Handle case where response is not a dict
                logger.info(f"✅ OTP email sent successfully to {to_email}, Response: {email_response}")
                return {
                    'success': True,
                    'message': 'Verification email sent successfully',
                    'email_id': str(email_response)
                }
            else:
                logger.error(f"❌ No response from Resend API")
                return {
                    'success': False,
                    'error': 'no_response',
                    'message': 'No response from email service'
                }
            
        except Exception as e:
            logger.error(f"💥 Exception in send_otp_email: {type(e).__name__}: {str(e)}")
            import traceback
            logger.error(f"💥 Full traceback: {traceback.format_exc()}")
            
            return {
                'success': False,
                'error': 'email_send_failed',
                'message': f'Failed to send verification email: {str(e)}'
            }
    
    def test_connection(self) -> Dict:
        """Test Resend API connection"""
        try:
            if not self.api_key:
                return {
                    'success': False,
                    'error': 'No API key configured'
                }
            
            # Try to get account info or send a simple test
            logger.info(f"🧪 Testing Resend connection with API key: {self.api_key[:10]}...")
            
            # Simple test email
            test_params = {
                "from": self.from_email,
                "to": ["test@resend.dev"],  # Resend's test email
                "subject": "Test Connection",
                "text": "This is a test email to verify API connection."
            }
            
            response = resend.Emails.send(test_params)
            logger.info(f"🧪 Test response: {response}")
            
            return {
                'success': True,
                'message': 'Connection test successful',
                'response': str(response)
            }
            
        except Exception as e:
            logger.error(f"🧪 Connection test failed: {str(e)}")
            return {
                'success': False,
                'error': str(e)
            }