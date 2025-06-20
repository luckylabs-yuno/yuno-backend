"""
Onboarding data model - extends your existing models structure
"""
import os
import logging
from supabase import create_client, Client
from typing import Dict, List, Optional
from datetime import datetime, timedelta
import secrets
import hashlib

logger = logging.getLogger(__name__)

class OnboardingModel:
    def __init__(self):
        supabase_url = os.getenv("SUPABASE_URL")
        supabase_key = os.getenv("SUPABASE_KEY")
        
        if not supabase_url or not supabase_key:
            raise ValueError("SUPABASE_URL and SUPABASE_KEY environment variables are required")
        
        self.supabase: Client = create_client(supabase_url, supabase_key)
    
    # =============================================================================
    # OTP MANAGEMENT
    # =============================================================================
    
    def create_otp(self, email: str) -> str:
        """
        Create and store OTP for email verification
        
        Args:
            email: User's email address
            
        Returns:
            Generated OTP code
        """
        try:
            # Generate 6-digit OTP
            otp_code = str(secrets.randbelow(900000) + 100000)
            
            # Set expiry to 10 minutes from now
            expires_at = datetime.utcnow() + timedelta(minutes=10)
            
            # Store in database
            self.supabase.table('otp_verifications').insert({
                'email': email,
                'otp_code': otp_code,
                'expires_at': expires_at.isoformat(),
                'is_verified': False
            }).execute()
            
            logger.info(f"OTP created for email: {email}")
            return otp_code
            
        except Exception as e:
            logger.error(f"Error creating OTP for {email}: {str(e)}")
            raise
    
    def verify_otp(self, email: str, otp_code: str) -> bool:
        """
        Verify OTP code for email
        
        Args:
            email: User's email address
            otp_code: OTP code to verify
            
        Returns:
            True if OTP is valid and not expired
        """
        try:
            # Get the latest OTP for this email
            response = self.supabase.table('otp_verifications')\
                .select('*')\
                .eq('email', email)\
                .eq('otp_code', otp_code)\
                .eq('is_verified', False)\
                .order('created_at', desc=True)\
                .limit(1)\
                .execute()
            
            if not response.data:
                logger.warning(f"Invalid OTP for email: {email}")
                return False
            
            otp_record = response.data[0]
            
            # Check if OTP has expired
            expires_at = datetime.fromisoformat(otp_record['expires_at'].replace('Z', '+00:00'))
            if datetime.utcnow() > expires_at.replace(tzinfo=None):
                logger.warning(f"Expired OTP for email: {email}")
                return False
            
            # Mark OTP as verified
            self.supabase.table('otp_verifications')\
                .update({'is_verified': True})\
                .eq('id', otp_record['id'])\
                .execute()
            
            logger.info(f"OTP verified successfully for email: {email}")
            return True
            
        except Exception as e:
            logger.error(f"Error verifying OTP for {email}: {str(e)}")
            return False
    
    def cleanup_expired_otps(self) -> int:
        """
        Clean up expired OTP records (run this periodically)
        
        Returns:
            Number of records deleted
        """
        try:
            # Delete OTPs older than 1 hour
            cutoff_time = datetime.utcnow() - timedelta(hours=1)
            
            response = self.supabase.table('otp_verifications')\
                .delete()\
                .lt('expires_at', cutoff_time.isoformat())\
                .execute()
            
            deleted_count = len(response.data) if response.data else 0
            logger.info(f"Cleaned up {deleted_count} expired OTP records")
            return deleted_count
            
        except Exception as e:
            logger.error(f"Error cleaning up expired OTPs: {str(e)}")
            return 0
    
    # =============================================================================
    # ONBOARDING SESSION MANAGEMENT
    # =============================================================================
    
    def get_onboarding_session(self, email: str) -> Optional[Dict]:
        """
        Get onboarding session for email
        
        Args:
            email: User's email address
            
        Returns:
            Onboarding session data or None
        """
        try:
            response = self.supabase.table('onboarding_sessions')\
                .select('*')\
                .eq('email', email)\
                .order('created_at', desc=True)\
                .limit(1)\
                .execute()
            
            return response.data[0] if response.data else None
            
        except Exception as e:
            logger.error(f"Error getting onboarding session for {email}: {str(e)}")
            return None
    
    def create_onboarding_session(self, email: str, step: int = 1, session_data: Dict = None) -> str:
        """
        Create new onboarding session
        
        Args:
            email: User's email address
            step: Current step number
            session_data: Additional session data
            
        Returns:
            Session ID
        """
        try:
            response = self.supabase.table('onboarding_sessions')\
                .insert({
                    'email': email,
                    'current_step': step,
                    'session_data': session_data or {}
                })\
                .execute()
            
            session_id = response.data[0]['id']
            logger.info(f"Onboarding session created for {email}: {session_id}")
            return session_id
            
        except Exception as e:
            logger.error(f"Error creating onboarding session for {email}: {str(e)}")
            raise
    
    def update_onboarding_session(self, email: str, step: int = None, session_data: Dict = None) -> bool:
        """
        Update onboarding session
        
        Args:
            email: User's email address
            step: New step number (optional)
            session_data: Session data to merge (optional)
            
        Returns:
            True if updated successfully
        """
        try:
            # Get current session
            current_session = self.get_onboarding_session(email)
            if not current_session:
                # Create new session if none exists
                self.create_onboarding_session(email, step or 1, session_data)
                return True
            
            # Prepare update data
            update_data = {}
            if step is not None:
                update_data['current_step'] = step
            
            if session_data:
                # Merge with existing session data
                existing_data = current_session.get('session_data', {})
                existing_data.update(session_data)
                update_data['session_data'] = existing_data
            
            if update_data:
                self.supabase.table('onboarding_sessions')\
                    .update(update_data)\
                    .eq('id', current_session['id'])\
                    .execute()
                
                logger.info(f"Onboarding session updated for {email}")
            
            return True
            
        except Exception as e:
            logger.error(f"Error updating onboarding session for {email}: {str(e)}")
            return False
    
    def complete_onboarding(self, email: str) -> bool:
        """
        Mark onboarding as completed
        
        Args:
            email: User's email address
            
        Returns:
            True if marked as completed
        """
        try:
            # Update onboarding session
            self.supabase.table('onboarding_sessions')\
                .update({
                    'completed_at': datetime.utcnow().isoformat()
                })\
                .eq('email', email)\
                .execute()
            
            # Update profile
            self.supabase.table('profiles')\
                .update({
                    'onboarding_completed': True,
                    'updated_at': datetime.utcnow().isoformat()
                })\
                .eq('id', self._get_user_id_by_email(email))\
                .execute()
            
            logger.info(f"Onboarding completed for {email}")
            return True
            
        except Exception as e:
            logger.error(f"Error completing onboarding for {email}: {str(e)}")
            return False
    
    # =============================================================================
    # SITE MANAGEMENT
    # =============================================================================
    
    def generate_site_id(self, domain: str) -> str:
        """
        Generate unique site_id for domain
        
        Args:
            domain: Domain name
            
        Returns:
            Unique site_id
        """
        try:
            # Create entropy from domain + timestamp + random
            entropy = f"{domain}_{int(datetime.utcnow().timestamp())}_{secrets.token_hex(8)}"
            
            # Generate hash and take first 12 characters
            hash_obj = hashlib.sha256(entropy.encode())
            site_id = hash_obj.hexdigest()[:12]
            
            # Check if site_id already exists (very unlikely but good practice)
            existing = self.supabase.table('sites')\
                .select('site_id')\
                .eq('site_id', site_id)\
                .execute()
            
            if existing.data:
                # Regenerate if collision (extremely rare)
                return self.generate_site_id(domain + "_retry")
            
            return site_id
            
        except Exception as e:
            logger.error(f"Error generating site_id for {domain}: {str(e)}")
            raise
    
    def create_site(self, user_id: str, domain: str, site_id: str = None) -> str:
        """
        Create new site record
        
        Args:
            user_id: User UUID from auth.users
            domain: Clean domain name
            site_id: Optional custom site_id
            
        Returns:
            Created site_id
        """
        try:
            if not site_id:
                site_id = self.generate_site_id(domain)
            
            # Create site record
            self.supabase.table('sites').insert({
                'site_id': site_id,
                'user_id': user_id,
                'domain': domain,
                'base_url': f"https://{domain}",
                'plan_active': True,
                'widget_enabled': True,
                'plan_type': 'free-trial',
                'theme': 'dark'
            }).execute()
            
            # Update profile with site_id
            self.supabase.table('profiles')\
                .update({
                    'site_id': site_id,
                    'domain': domain,
                    'updated_at': datetime.utcnow().isoformat()
                })\
                .eq('id', user_id)\
                .execute()
            
            logger.info(f"Site created: {site_id} for domain: {domain}")
            return site_id
            
        except Exception as e:
            logger.error(f"Error creating site for {domain}: {str(e)}")
            raise
    
    # =============================================================================
    # CONTENT UPLOADS
    # =============================================================================
    
    def create_content_upload(self, site_id: str, upload_type: str, **kwargs) -> str:
        """
        Create content upload record
        
        Args:
            site_id: Site identifier
            upload_type: 'file' or 'text'
            **kwargs: Additional fields (content_text, file_path, file_name, etc.)
            
        Returns:
            Upload ID
        """
        try:
            upload_data = {
                'site_id': site_id,
                'upload_type': upload_type,
                'processing_status': 'queued'
            }
            upload_data.update(kwargs)
            
            response = self.supabase.table('content_uploads')\
                .insert(upload_data)\
                .execute()
            
            upload_id = response.data[0]['id']
            logger.info(f"Content upload created: {upload_id} for site: {site_id}")
            return upload_id
            
        except Exception as e:
            logger.error(f"Error creating content upload for {site_id}: {str(e)}")
            raise
    
    def update_content_upload_status(self, upload_id: str, status: str, **kwargs) -> bool:
        """
        Update content upload status
        
        Args:
            upload_id: Upload identifier
            status: New status ('processing', 'completed', 'failed')
            **kwargs: Additional fields to update
            
        Returns:
            True if updated successfully
        """
        try:
            update_data = {'processing_status': status}
            update_data.update(kwargs)
            
            self.supabase.table('content_uploads')\
                .update(update_data)\
                .eq('id', upload_id)\
                .execute()
            
            logger.info(f"Content upload {upload_id} status updated to: {status}")
            return True
            
        except Exception as e:
            logger.error(f"Error updating content upload {upload_id}: {str(e)}")
            return False
    
    def get_site_content_uploads(self, site_id: str) -> List[Dict]:
        """
        Get all content uploads for a site
        
        Args:
            site_id: Site identifier
            
        Returns:
            List of content upload records
        """
        try:
            response = self.supabase.table('content_uploads')\
                .select('*')\
                .eq('site_id', site_id)\
                .order('created_at', desc=True)\
                .execute()
            
            return response.data or []
            
        except Exception as e:
            logger.error(f"Error getting content uploads for {site_id}: {str(e)}")
            return []
    
    # =============================================================================
    # HELPER METHODS
    # =============================================================================
    
    def _get_user_id_by_email(self, email: str) -> Optional[str]:
        """Get user ID from email (helper method)"""
        try:
            # This might need adjustment based on your auth setup
            response = self.supabase.table('profiles')\
                .select('id')\
                .eq('metadata->email', email)\
                .limit(1)\
                .execute()
            
            return response.data[0]['id'] if response.data else None
            
        except Exception as e:
            logger.error(f"Error getting user ID for {email}: {str(e)}")
            return None
    
    def get_onboarding_stats(self) -> Dict:
        """Get overall onboarding statistics"""
        try:
            # Total sessions
            total_sessions = self.supabase.table('onboarding_sessions')\
                .select('id', count='exact')\
                .execute()
            
            # Completed sessions
            completed_sessions = self.supabase.table('onboarding_sessions')\
                .select('id', count='exact')\
                .not_.is_('completed_at', 'null')\
                .execute()
            
            # Active sessions (last 24 hours)
            yesterday = datetime.utcnow() - timedelta(days=1)
            active_sessions = self.supabase.table('onboarding_sessions')\
                .select('id', count='exact')\
                .gte('created_at', yesterday.isoformat())\
                .execute()
            
            return {
                'total_sessions': total_sessions.count,
                'completed_sessions': completed_sessions.count,
                'active_sessions': active_sessions.count,
                'completion_rate': (completed_sessions.count / max(total_sessions.count, 1)) * 100
            }
            
        except Exception as e:
            logger.error(f"Error getting onboarding stats: {str(e)}")
            return {}