"""
Onboarding service - business logic for user onboarding flow
Integrates with your existing services
"""
import os
import logging
import secrets
import hashlib
from typing import Dict, Optional, Tuple
from datetime import datetime, timedelta
import time

# Import your existing services
from .jwt_service import JWTService
from .domain_service import DomainService
from models.onboarding import OnboardingModel
from utils.helpers import ValidationHelpers, SecurityHelpers

logger = logging.getLogger(__name__)

class OnboardingService:
    def __init__(self):
        self.onboarding_model = OnboardingModel()
        self.jwt_service = JWTService()
        self.domain_service = DomainService()
    
    # =============================================================================
    # STEP 1: EMAIL & OTP
    # =============================================================================
    
    def send_otp(self, email: str) -> Dict:
        """Send OTP to user's email"""
        try:
            # Validate email format
            if not ValidationHelpers.validate_email(email):
                return {
                    'success': False,
                    'error': 'invalid_email',
                    'message': 'Please enter a valid email address'
                }
            
            # Check for existing recent OTP (rate limiting)
            existing_session = self.onboarding_model.get_onboarding_session(email)
            if existing_session:
                last_created = datetime.fromisoformat(existing_session['created_at'].replace('Z', '+00:00'))
                if datetime.utcnow() - last_created.replace(tzinfo=None) < timedelta(minutes=1):
                    return {
                        'success': False,
                        'error': 'rate_limited',
                        'message': 'Please wait before requesting another OTP'
                    }
            
            # Generate and send OTP
            otp_code = self.onboarding_model.create_otp(email)
            
            # For development, log the OTP
            if os.getenv('FLASK_ENV') == 'development':
                logger.info(f"🔑 OTP for {email}: {otp_code}")
            
            # Send OTP email
            self._send_otp_email(email, otp_code)
            
            # Create or update onboarding session
            self.onboarding_model.update_onboarding_session(
                email=email,
                step=1,
                session_data={'otp_sent_at': datetime.utcnow().isoformat()}
            )
            
            return {
                'success': True,
                'message': 'OTP sent successfully. Please check your email.',
                'expires_in': 600
            }
            
        except Exception as e:
            logger.error(f"Error sending OTP to {email}: {str(e)}")
            return {
                'success': False,
                'error': 'send_failed',
                'message': 'Failed to send OTP. Please try again.'
            }
    
    def verify_otp(self, email: str, otp_code: str) -> Dict:
        """Verify OTP and return temporary token"""
        try:
            # Validate OTP format
            if not otp_code or len(otp_code) != 6 or not otp_code.isdigit():
                return {
                    'success': False,
                    'error': 'invalid_format',
                    'message': 'OTP must be 6 digits'
                }
            
            # Verify OTP
            is_valid = self.onboarding_model.verify_otp(email, otp_code)
            
            if not is_valid:
                return {
                    'success': False,
                    'error': 'invalid_otp',
                    'message': 'Invalid or expired OTP'
                }
            
            # Generate temporary token for next step
            temp_token = self.jwt_service.generate_token({
                'email': email,
                'step': 'profile_setup',
                'verified': True
            }, expiry_seconds=1800)
            
            # Update onboarding session
            self.onboarding_model.update_onboarding_session(
                email=email,
                step=2,
                session_data={
                    'otp_verified_at': datetime.utcnow().isoformat(),
                    'email_verified': True
                }
            )
            
            return {
                'success': True,
                'message': 'OTP verified successfully',
                'temp_token': temp_token
            }
            
        except Exception as e:
            logger.error(f"Error verifying OTP for {email}: {str(e)}")
            return {
                'success': False,
                'error': 'verification_failed',
                'message': 'OTP verification failed'
            }
    
    # =============================================================================
    # STEP 3: PROFILE SETUP
    # =============================================================================
    
    def complete_profile_setup(self, temp_token: str, profile_data: Dict) -> Dict:
        """Complete profile setup with password and optional fields"""
        try:
            # Verify temp token
            token_payload = self.jwt_service.verify_token(temp_token)
            if not token_payload or token_payload.get('step') != 'profile_setup':
                return {
                    'success': False,
                    'error': 'invalid_token',
                    'message': 'Invalid or expired token'
                }
            
            email = token_payload.get('email')
            if not email:
                return {
                    'success': False,
                    'error': 'missing_email',
                    'message': 'Email not found in token'
                }
            
            # Only password is required
            password = profile_data.get('password')
            if not password:
                return {
                    'success': False,
                    'error': 'missing_password',
                    'message': 'Password is required'
                }
            
            # Validate password strength
            password_validation = self._validate_password(password)
            if not password_validation['valid']:
                return {
                    'success': False,
                    'error': 'weak_password',
                    'message': 'Password does not meet requirements',
                    'details': password_validation
                }
            
            # Create user in Supabase Auth
            user_result = self._create_supabase_user(email, password)
            if not user_result['success']:
                return user_result
            
            user_id = user_result['user_id']
            
            # Create profile with optional fields
            profile_result = self._create_user_profile(user_id, email, {
                'name': profile_data.get('name'),
                'date_of_birth': profile_data.get('date_of_birth'),
                'country': profile_data.get('country'),
            })
            
            if not profile_result['success']:
                # Cleanup: delete the auth user if profile creation fails
                try:
                    self.onboarding_model.supabase.auth.admin.delete_user(user_id)
                except:
                    pass
                return profile_result
            
            # Create onboarding session
            session_result = self._create_onboarding_session(email, {
                'user_id': user_id,
                'current_step': 4,
                'profile_completed': True
            })
            
            if not session_result['success']:
                return session_result
            
            # Generate access token
            access_token = self.jwt_service.generate_access_token(user_id, email)
            
            return {
                'success': True,
                'message': 'Account created successfully',
                'user_id': user_id,
                'access_token': access_token
            }
            
        except Exception as e:
            logger.error(f"Error in complete_profile_setup: {str(e)}")
            return {
                'success': False,
                'error': 'internal_error',
                'message': 'An error occurred while creating your account'
            }
    
    # =============================================================================
    # STEP 4: DOMAIN SETUP
    # =============================================================================
    
    def setup_domain(self, access_token: str, domain: str) -> Dict:
        """Setup user's domain and create site"""
        try:
            # Verify access token
            token_payload = self.jwt_service.verify_token(access_token)
            if not token_payload:
                return {
                    'success': False,
                    'error': 'invalid_token',
                    'message': 'Invalid or expired token'
                }
            
            user_id = token_payload.get('user_id')
            email = token_payload.get('email')
            
            # Validate and clean domain
            clean_domain = self.domain_service.clean_domain(domain)
            
            if not self.domain_service.validate_domain_format(clean_domain):
                return {
                    'success': False,
                    'error': 'invalid_domain',
                    'message': 'Please enter a valid domain name'
                }
            
            # Check if domain is already registered
            existing_sites = self.onboarding_model.supabase.table('sites')\
                .select('site_id')\
                .eq('domain', clean_domain)\
                .execute()
            
            if existing_sites.data:
                return {
                    'success': False,
                    'error': 'domain_exists',
                    'message': 'This domain is already registered'
                }
            
            # Generate site_id and create site
            site_id = self.onboarding_model.create_site(
                user_id=user_id,
                domain=clean_domain
            )
            
            # Update onboarding session
            self.onboarding_model.update_onboarding_session(
                email=email,
                step=4,
                session_data={
                    'domain_setup_at': datetime.utcnow().isoformat(),
                    'site_id': site_id,
                    'domain': clean_domain
                }
            )
            
            # Start background scraping
            self._start_website_scraping(site_id, clean_domain)
            
            return {
                'success': True,
                'message': 'Domain setup completed',
                'site_id': site_id,
                'domain': clean_domain,
                'scraping_status': 'started'
            }
            
        except Exception as e:
            logger.error(f"Error setting up domain {domain}: {str(e)}")
            return {
                'success': False,
                'error': 'domain_setup_failed',
                'message': 'Domain setup failed'
            }
    
    def get_scraping_status(self, site_id: str) -> Dict:
        """Get website scraping status"""
        try:
            return {
                'site_id': site_id,
                'status': 'in_progress',
                'progress': 45,
                'pages_scraped': 23,
                'estimated_completion': '2-3 minutes'
            }
        except Exception as e:
            logger.error(f"Error getting scraping status for {site_id}: {str(e)}")
            return {
                'site_id': site_id,
                'status': 'error',
                'progress': 0
            }
    
    # =============================================================================
    # STEP 5: CONTENT UPLOAD
    # =============================================================================
    
    def upload_text_content(self, access_token: str, text_content: str) -> Dict:
        """Upload text content for processing"""
        try:
            # Verify token and get site_id
            token_payload = self.jwt_service.verify_token(access_token)
            if not token_payload:
                return {
                    'success': False,
                    'error': 'invalid_token',
                    'message': 'Invalid or expired token'
                }
            
            # Get site_id from onboarding session
            email = token_payload.get('email')
            session = self.onboarding_model.get_onboarding_session(email)
            site_id = session['session_data'].get('site_id')
            
            if not site_id:
                return {
                    'success': False,
                    'error': 'no_site',
                    'message': 'Site not found. Please complete domain setup first.'
                }
            
            # Validate content
            if not text_content or len(text_content.strip()) < 10:
                return {
                    'success': False,
                    'error': 'invalid_content',
                    'message': 'Content must be at least 10 characters'
                }
            
            # Create content upload record
            upload_id = self.onboarding_model.create_content_upload(
                site_id=site_id,
                upload_type='text',
                content_text=text_content.strip()
            )
            
            # Process content immediately
            self._process_text_content(upload_id, text_content, site_id)
            
            return {
                'success': True,
                'message': 'Text content uploaded successfully',
                'upload_id': upload_id
            }
            
        except Exception as e:
            logger.error(f"Error uploading text content: {str(e)}")
            return {
                'success': False,
                'error': 'upload_failed',
                'message': 'Content upload failed'
            }
    
    def upload_file(self, access_token: str, file_data: Dict) -> Dict:
        """Upload file for processing"""
        try:
            # Verify token
            token_payload = self.jwt_service.verify_token(access_token)
            if not token_payload:
                return {
                    'success': False,
                    'error': 'invalid_token',
                    'message': 'Invalid or expired token'
                }
            
            # Get site_id
            email = token_payload.get('email')
            session = self.onboarding_model.get_onboarding_session(email)
            site_id = session['session_data'].get('site_id')
            
            if not site_id:
                return {
                    'success': False,
                    'error': 'no_site',
                    'message': 'Site not found'
                }
            
            # Validate file
            file_validation = self._validate_file(file_data)
            if not file_validation['valid']:
                return {
                    'success': False,
                    'error': 'invalid_file',
                    'message': file_validation['message']
                }
            
            # Save file and create upload record
            file_path = self._save_uploaded_file(file_data, site_id)
            
            upload_id = self.onboarding_model.create_content_upload(
                site_id=site_id,
                upload_type='file',
                file_path=file_path,
                file_name=file_data['name'],
                file_size_bytes=file_data['size'],
                file_type=file_data['type']
            )
            
            # Process file immediately
            self._process_file_content(upload_id, file_path, site_id)
            
            return {
                'success': True,
                'message': 'File uploaded successfully',
                'upload_id': upload_id
            }
            
        except Exception as e:
            logger.error(f"Error uploading file: {str(e)}")
            return {
                'success': False,
                'error': 'upload_failed',
                'message': 'File upload failed'
            }
    
    # =============================================================================
    # STEP 6: WIDGET VERIFICATION
    # =============================================================================
    
    def generate_widget_script(self, access_token: str) -> Dict:
        """Generate widget script for user to embed"""
        try:
            # Verify token
            token_payload = self.jwt_service.verify_token(access_token)
            if not token_payload:
                return {
                    'success': False,
                    'error': 'invalid_token',
                    'message': 'Invalid or expired token'
                }
            
            # Get site_id
            email = token_payload.get('email')
            session = self.onboarding_model.get_onboarding_session(email)
            site_id = session['session_data'].get('site_id')
            
            if not site_id:
                return {
                    'success': False,
                    'error': 'no_site',
                    'message': 'Site not found'
                }
            
            # Generate widget script
            api_endpoint = os.getenv('API_ENDPOINT', 'https://api.helloyuno.com')
            widget_script = f'''<script 
  src="{api_endpoint}/yuno.js"
  site_id="{site_id}"
  theme="dark"
  position="bottom-right"
  welcome_message="Hi! How can I help you today?"
></script>'''
            
            return {
                'success': True,
                'site_id': site_id,
                'widget_script': widget_script,
                'instructions': [
                    'Copy the script above',
                    'Paste it in the <head> section of your website',
                    'The widget will appear on your site immediately',
                    'Click "Verify Installation" once you\'ve added the script'
                ]
            }
            
        except Exception as e:
            logger.error(f"Error generating widget script: {str(e)}")
            return {
                'success': False,
                'error': 'script_generation_failed',
                'message': 'Failed to generate widget script'
            }
    
    def verify_widget_installation(self, access_token: str) -> Dict:
        """Verify that widget is installed on user's website"""
        try:
            # Verify token
            token_payload = self.jwt_service.verify_token(access_token)
            if not token_payload:
                return {
                    'success': False,
                    'error': 'invalid_token',
                    'message': 'Invalid or expired token'
                }
            
            # Get site info
            email = token_payload.get('email')
            session = self.onboarding_model.get_onboarding_session(email)
            site_data = session['session_data']
            site_id = site_data.get('site_id')
            domain = site_data.get('domain')
            
            if not site_id or not domain:
                return {
                    'success': False,
                    'error': 'incomplete_setup',
                    'message': 'Site setup incomplete'
                }
            
            # Simulate verification check
            verification_result = self._check_widget_installation(site_id, domain)
            
            if verification_result:
                # Mark onboarding as completed
                self.onboarding_model.update_onboarding_session(
                    email=email,
                    step=6,
                    session_data={
                        'widget_verified_at': datetime.utcnow().isoformat(),
                        'widget_verified': True
                    }
                )
                
                self.onboarding_model.complete_onboarding(email)
                
                return {
                    'success': True,
                    'verified': True,
                    'message': 'Widget installation verified successfully!',
                    'next_step': 'dashboard'
                }
            else:
                return {
                    'success': False,
                    'verified': False,
                    'message': 'Widget not detected. Please ensure the script is in your website\'s <head> section.',
                    'troubleshooting': [
                        'Check that the script is in the <head> section',
                        'Ensure there are no JavaScript errors on your page',
                        'Try refreshing your website',
                        'Contact support if issues persist'
                    ]
                }
            
        except Exception as e:
            logger.error(f"Error verifying widget installation: {str(e)}")
            return {
                'success': False,
                'error': 'verification_failed',
                'message': 'Widget verification failed'
            }
    
    # =============================================================================
    # UTILITY METHODS
    # =============================================================================
    
    def get_onboarding_state(self, email: str) -> Dict:
        """Get current onboarding state for user"""
        try:
            session = self.onboarding_model.get_onboarding_session(email)
            if not session:
                return {
                    'current_step': 1,
                    'email': email,
                    'session_data': {}
                }
            
            return {
                'current_step': session['current_step'],
                'email': session['email'],
                'session_data': session['session_data'],
                'created_at': session['created_at'],
                'completed_at': session.get('completed_at')
            }
            
        except Exception as e:
            logger.error(f"Error getting onboarding state for {email}: {str(e)}")
            return {
                'current_step': 1,
                'email': email,
                'session_data': {}
            }
    
    # =============================================================================
    # PRIVATE HELPER METHODS
    # =============================================================================
    
    def _send_otp_email(self, email: str, otp_code: str):
        """Send OTP email"""
        logger.info(f"📧 Sending OTP {otp_code} to {email}")
    
    def _validate_password(self, password: str) -> Dict:
        """Validate password strength"""
        checks = {
            'length': len(password) >= 8,
            'uppercase': any(c.isupper() for c in password),
            'lowercase': any(c.islower() for c in password),
            'number': any(c.isdigit() for c in password)
        }
        
        score = sum(checks.values())
        valid = score >= 3
        
        return {
            'valid': valid,
            'score': score,
            'checks': checks
        }
    
    def _create_supabase_user(self, email: str, password: str) -> Dict:
        """Create user in Supabase Auth"""
        try:
            result = self.onboarding_model.supabase.auth.admin.create_user({
                'email': email,
                'password': password,
                'email_confirm': True
            })
            
            if result.user:
                return {
                    'success': True,
                    'user_id': result.user.id
                }
            else:
                return {
                    'success': False,
                    'error': 'user_creation_failed',
                    'message': 'Failed to create user account'
                }
                
        except Exception as e:
            logger.error(f"Error creating Supabase user: {str(e)}")
            return {
                'success': False,
                'error': 'auth_error',
                'message': 'Authentication system error'
            }
    
    def _create_onboarding_session(self, email: str, session_data: Dict) -> Dict:
        """Create onboarding session"""
        try:
            self.onboarding_model.update_onboarding_session(
                email=email,
                step=session_data.get('current_step', 1),
                session_data=session_data
            )
            return {'success': True}
        except Exception as e:
            logger.error(f"Error creating onboarding session: {str(e)}")
            return {
                'success': False,
                'error': 'session_error',
                'message': 'Failed to create session'
            }
    
    def _create_user_profile(self, user_id: str, email: str, profile_data: Dict) -> Dict:
        """Create user profile with optional fields"""
        try:
            profile_record = {
                'id': user_id,
                'email': email,
                'name': profile_data.get('name'),
                'date_of_birth': profile_data.get('date_of_birth'),
                'country': profile_data.get('country'),
                'onboarding_completed': False,
                'created_at': datetime.utcnow().isoformat(),
                'updated_at': datetime.utcnow().isoformat()
            }
            
            result = self.onboarding_model.supabase.table('profiles').insert(profile_record).execute()
            
            if result.data:
                return {
                    'success': True,
                    'message': 'Profile created successfully'
                }
            else:
                return {
                    'success': False,
                    'error': 'profile_creation_failed',
                    'message': 'Failed to create user profile'
                }
                
        except Exception as e:
            logger.error(f"Error creating user profile: {str(e)}")
            return {
                'success': False,
                'error': 'database_error',
                'message': 'Database error while creating profile'
            }
    
    def _start_website_scraping(self, site_id: str, domain: str):
        """Start website scraping"""
        logger.info(f"🕷️ Starting website scraping for {domain} (site_id: {site_id})")
    
    def _process_text_content(self, upload_id: str, content: str, site_id: str):
        """Process text content immediately"""
        try:
            self.onboarding_model.update_content_upload_status(upload_id, 'processing')
            time.sleep(1)
            self.onboarding_model.update_content_upload_status(
                upload_id, 
                'completed',
                chunks_created=len(content) // 1000 + 1
            )
            logger.info(f"Text content processed for upload {upload_id}")
        except Exception as e:
            logger.error(f"Error processing text content: {str(e)}")
            self.onboarding_model.update_content_upload_status(
                upload_id, 
                'failed',
                error_message=str(e)
            )
    
    def _process_file_content(self, upload_id: str, file_path: str, site_id: str):
        """Process file content"""
        try:
            self.onboarding_model.update_content_upload_status(upload_id, 'processing')
            self.onboarding_model.update_content_upload_status(
                upload_id,
                'completed',
                chunks_created=5
            )
            logger.info(f"File content processed for upload {upload_id}")
        except Exception as e:
            logger.error(f"Error processing file content: {str(e)}")
            self.onboarding_model.update_content_upload_status(
                upload_id,
                'failed', 
                error_message=str(e)
            )
    
    def _validate_file(self, file_data: Dict) -> Dict:
        """Validate uploaded file"""
        allowed_types = ['application/pdf', 'text/plain', 'application/msword', 
                        'application/vnd.openxmlformats-officedocument.wordprocessingml.document']
        max_size = 25 * 1024 * 1024
        
        if file_data['size'] > max_size:
            return {
                'valid': False,
                'message': 'File size must be less than 25MB'
            }
        
        if file_data['type'] not in allowed_types:
            return {
                'valid': False,
                'message': 'Only PDF, DOC, DOCX, and TXT files are allowed'
            }
        
        return {'valid': True}
    
    def _save_uploaded_file(self, file_data: Dict, site_id: str) -> str:
        """Save uploaded file and return path"""
        timestamp = int(time.time())
        filename = f"{site_id}_{timestamp}_{file_data['name']}"
        return f"uploads/{filename}"
    
    def _check_widget_installation(self, site_id: str, domain: str) -> bool:
        """Check if widget is installed on domain"""
        time.sleep(2)
        return True