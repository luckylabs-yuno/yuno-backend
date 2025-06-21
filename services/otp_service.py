# FILE: services/otp_service.py (COMPLETELY UPDATED)
# ============================================================================

import random
import string
from datetime import datetime, timedelta
from typing import Dict
import logging
from utils.supabase_client import get_supabase_client
from services.email_service import EmailService

logger = logging.getLogger(__name__)

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
    
    def verify_otp(self, email: str, otp_code: str) -> Dict:
        """
        Verify OTP code
        """
        try:
            # Get OTP record
            result = self.supabase.table('otp_verifications').select('*').eq('email', email.lower()).eq('otp_code', otp_code).execute()
            
            if not result.data:
                return {
                    'success': False,
                    'error': 'invalid_otp',
                    'message': 'Invalid verification code'
                }
            
            otp_record = result.data[0]
            
            # Check if already verified
            if otp_record['is_verified']:
                return {
                    'success': False,
                    'error': 'already_verified',
                    'message': 'This verification code has already been used'
                }
            
            # Check if expired
            expires_at = datetime.fromisoformat(otp_record['expires_at'].replace('Z', '+00:00'))
            if datetime.utcnow().replace(tzinfo=expires_at.tzinfo) > expires_at:
                return {
                    'success': False,
                    'error': 'expired_otp',
                    'message': 'Verification code has expired'
                }
            
            # Mark as verified
            self.supabase.table('otp_verifications').update({
                'is_verified': True
            }).eq('email', email.lower()).eq('otp_code', otp_code).execute()
            
            return {
                'success': True,
                'message': 'Email verified successfully'
            }
            
        except Exception as e:
            logger.error(f"Error in verify_otp: {str(e)}")
            return {
                'success': False,
                'error': 'internal_error',
                'message': 'An error occurred while verifying code'
            }
