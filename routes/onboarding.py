"""
Onboarding API routes - extends your existing Flask app
"""

from flask import Blueprint, request, jsonify
import logging
from datetime import datetime
from services.jwt_service import JWTService

# Import your existing services
from services.onboarding_service import OnboardingService
from utils.helpers import ValidationHelpers, ResponseHelpers

# ADD THESE ENDPOINTS TO YOUR EXISTING routes/onboarding.py file

# At the top, add these imports:
from services.content_processor import ContentProcessor
from werkzeug.utils import secure_filename
import os
import uuid


# Initialize service
onboarding_service = OnboardingService()

# Add this constant after imports:
ALLOWED_EXTENSIONS = {'txt', 'pdf', 'doc', 'docx'}

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


onboarding_bp = Blueprint('onboarding', __name__)
logger = logging.getLogger(__name__)

content_processor = ContentProcessor(
    supabase_client=onboarding_service.onboarding_model.supabase,
    openai_api_key=os.environ.get('OPENAI_API_KEY')
)

# =============================================================================
# STEP 1: EMAIL & OTP ENDPOINTS
# =============================================================================

@onboarding_bp.route('/send-otp', methods=['POST', 'OPTIONS'])
def send_otp():
    """
    Send OTP to user's email
    POST /onboarding/send-otp
    """
    if request.method == 'OPTIONS':
        return jsonify({'status': 'ok'}), 200
    
    try:
        data = request.get_json()
        if not data:
            return jsonify(ResponseHelpers.error_response(
                "Request data is required"
            )), 400
        
        email = data.get('email')
        if not email:
            return jsonify(ResponseHelpers.error_response(
                "Email is required"
            )), 400
        
        # Validate email format
        if not ValidationHelpers.validate_email(email):
            return jsonify(ResponseHelpers.error_response(
                "Please enter a valid email address"
            )), 400
        
        # Send OTP
        result = onboarding_service.send_otp(email)
        
        if result['success']:
            return jsonify(ResponseHelpers.success_response(
                data={
                    'expires_in': result['expires_in']
                },
                message=result['message']
            )), 200
        else:
            return jsonify(ResponseHelpers.error_response(
                result['message'],
                error_code=result.get('error')
            )), 400
            
    except Exception as e:
        logger.error(f"Error in send-otp endpoint: {str(e)}")
        return jsonify(ResponseHelpers.error_response(
            "An error occurred while sending OTP"
        )), 500


@onboarding_bp.route('/verify-otp', methods=['POST', 'OPTIONS'])
def verify_otp():
    """
    Verify OTP and get temporary token
    POST /onboarding/verify-otp
    """
    if request.method == 'OPTIONS':
        return jsonify({'status': 'ok'}), 200
    
    try:
        data = request.get_json()
        if not data:
            return jsonify(ResponseHelpers.error_response(
                "Request data is required"
            )), 400
        
        email = data.get('email')
        otp_code = data.get('otp_code')
        
        if not email or not otp_code:
            return jsonify(ResponseHelpers.error_response(
                "Email and OTP code are required"
            )), 400
        
        # Verify OTP
        result = onboarding_service.verify_otp(email, otp_code)
        
        if result['success']:
            # ADD THIS: Update session to step 3
            onboarding_service.onboarding_model.update_onboarding_session(
                email=email,
                step=3,
                session_data={'otp_verified': True}
            )
            return jsonify(ResponseHelpers.success_response(
                data={
                    'temp_token': result['temp_token']
                },
                message=result['message']
            )), 200
        else:
            return jsonify(ResponseHelpers.error_response(
                result['message'],
                error_code=result.get('error')
            )), 400
            
    except Exception as e:
        logger.error(f"Error in verify-otp endpoint: {str(e)}")
        return jsonify(ResponseHelpers.error_response(
            "An error occurred while verifying OTP"
        )), 500


# ============================================================================
# UPDATED onboarding.py - Profile Endpoint
# Remove mandatory field validation
# ============================================================================

@onboarding_bp.route('/complete-profile', methods=['POST', 'OPTIONS'])
def complete_profile():
    """
    Complete profile setup - UPDATED TO ONLY REQUIRE PASSWORD
    POST /onboarding/complete-profile
    
    Body: {
        "password": "required_password",
        "name": "optional_name",
        "date_of_birth": "optional_date",
        "country": "optional_country"
    }
    """
    if request.method == 'OPTIONS':
        return jsonify({'status': 'ok'}), 200
    
    try:
        # Get temp token from Authorization header
        auth_header = request.headers.get('Authorization', '')
        if not auth_header.startswith('Bearer '):
            return jsonify(ResponseHelpers.error_response(
                "Temporary authorization token is required"
            )), 401
        
        temp_token = auth_header.replace('Bearer ', '')
        
        data = request.get_json()
        if not data:
            return jsonify(ResponseHelpers.error_response(
                "Profile data is required"
            )), 400
        
        # UPDATED: Only validate password is required
        password = data.get('password')
        if not password:
            return jsonify(ResponseHelpers.error_response(
                "Password is required"
            )), 400
        
        # Complete profile setup with only password required
        result = onboarding_service.complete_profile_setup(temp_token, data)
        
        if result['success']:
            return jsonify(ResponseHelpers.success_response(
                data={
                    'user_id': result['user_id'],
                    'access_token': result['access_token']
                },
                message=result['message']
            )), 200
        else:
            status_code = 401 if result.get('error') == 'invalid_token' else 400
            return jsonify(ResponseHelpers.error_response(
                result['message'],
                error_code=result.get('error'),
                details=result.get('details')
            )), status_code
            
    except Exception as e:
        logger.error(f"Error in complete-profile endpoint: {str(e)}")
        return jsonify(ResponseHelpers.error_response(
            "An error occurred while completing profile"
        )), 500



# =============================================================================
# STEP 4: DOMAIN SETUP
# =============================================================================

@onboarding_bp.route('/setup-domain', methods=['POST', 'OPTIONS'])
def setup_domain():
    """
    Setup user's domain and create site
    POST /onboarding/setup-domain
    """
    if request.method == 'OPTIONS':
        return jsonify({'status': 'ok'}), 200
    
    try:
        # Get access token from Authorization header
        auth_header = request.headers.get('Authorization', '')
        if not auth_header.startswith('Bearer '):
            return jsonify(ResponseHelpers.error_response(
                "Authorization token is required"
            )), 401
        
        access_token = auth_header.replace('Bearer ', '')
        
        data = request.get_json()
        if not data:
            return jsonify(ResponseHelpers.error_response(
                "Domain data is required"
            )), 400
        
        domain = data.get('domain')
        if not domain:
            return jsonify(ResponseHelpers.error_response(
                "Domain is required"
            )), 400
        
        # Setup domain
        result = onboarding_service.setup_domain(access_token, domain)
        
        if result['success']:
            # ADD THIS: Update session to step 5
            # First get email from token
            jwt_service = JWTService()
            token_payload = jwt_service.verify_token(access_token)
            if token_payload and token_payload.get('email'):
                onboarding_service.onboarding_model.update_onboarding_session(
                    email=token_payload['email'],
                    step=5,
                    session_data={'site_id': result['site_id'], 'domain': result['domain']}
                )
            return jsonify(ResponseHelpers.success_response(
                data={
                    'site_id': result['site_id'],
                    'domain': result['domain'],
                    'scraping_status': result['scraping_status']
                },
                message=result['message']
            )), 200
        else:
            status_code = 401 if result.get('error') == 'invalid_token' else 400
            return jsonify(ResponseHelpers.error_response(
                result['message'],
                error_code=result.get('error')
            )), status_code
            
    except Exception as e:
        logger.error(f"Error in setup-domain endpoint: {str(e)}")
        return jsonify(ResponseHelpers.error_response(
            "An error occurred while setting up domain"
        )), 500


@onboarding_bp.route('/scraping-status/<site_id>', methods=['GET', 'OPTIONS'])
def get_scraping_status(site_id):
    """
    Get website scraping status
    GET /onboarding/scraping-status/<site_id>
    """
    if request.method == 'OPTIONS':
        return jsonify({'status': 'ok'}), 200
    
    try:
        # Get scraping status
        result = onboarding_service.get_scraping_status(site_id)
        
        return jsonify(ResponseHelpers.success_response(
            data=result,
            message="Scraping status retrieved"
        )), 200
        
    except Exception as e:
        logger.error(f"Error getting scraping status for {site_id}: {str(e)}")
        return jsonify(ResponseHelpers.error_response(
            "An error occurred while getting scraping status"
        )), 500




# =============================================================================
# STEP 6: WIDGET VERIFICATION
# =============================================================================

@onboarding_bp.route('/generate-widget-script', methods=['GET', 'OPTIONS'])
def generate_widget_script():
    """
    Generate widget script for user to embed
    GET /onboarding/generate-widget-script
    """
    if request.method == 'OPTIONS':
        return jsonify({'status': 'ok'}), 200
    
    try:
        # Get access token
        auth_header = request.headers.get('Authorization', '')
        if not auth_header.startswith('Bearer '):
            return jsonify(ResponseHelpers.error_response(
                "Authorization token is required"
            )), 401
        
        access_token = auth_header.replace('Bearer ', '')
        
        # Generate widget script
        result = onboarding_service.generate_widget_script(access_token)
        
        if result['success']:
            return jsonify(ResponseHelpers.success_response(
                data={
                    'site_id': result['site_id'],
                    'widget_script': result['widget_script'],
                    'instructions': result['instructions']
                },
                message="Widget script generated successfully"
            )), 200
        else:
            status_code = 401 if result.get('error') == 'invalid_token' else 400
            return jsonify(ResponseHelpers.error_response(
                result['message'],
                error_code=result.get('error')
            )), status_code
            
    except Exception as e:
        logger.error(f"Error in generate-widget-script endpoint: {str(e)}")
        return jsonify(ResponseHelpers.error_response(
            "An error occurred while generating widget script"
        )), 500


# Also update the verify_widget endpoint in routes/onboarding.py to accept page_url

@onboarding_bp.route('/verify-widget', methods=['POST', 'OPTIONS'])
def verify_widget():
    """
    Verify widget installation on user's website
    POST /onboarding/verify-widget
    Body: {
        "page_url": "https://example.com/specific-page" (optional)
    }
    """
    if request.method == 'OPTIONS':
        return jsonify({'status': 'ok'}), 200
    
    try:
        # Get access token
        auth_header = request.headers.get('Authorization', '')
        if not auth_header.startswith('Bearer '):
            return jsonify(ResponseHelpers.error_response(
                "Authorization token is required"
            )), 401
        
        access_token = auth_header.replace('Bearer ', '')
        
        # Get optional page URL
        data = request.get_json() or {}
        page_url = data.get('page_url')
        
        # Verify widget installation
        result = onboarding_service.verify_widget_installation(access_token, page_url)
        
        if result['success']:
            return jsonify(ResponseHelpers.success_response(
                data={
                    'verified': result['verified'],
                    'next_step': result.get('next_step'),
                    'redirect_url': result.get('redirect_url')
                },
                message=result['message']
            )), 200
        else:
            return jsonify(ResponseHelpers.error_response(
                result['message'],
                error_code=result.get('error'),
                details={
                    'verified': result.get('verified', False),
                    'troubleshooting': result.get('troubleshooting', [])
                }
            )), 400
            
    except Exception as e:
        logger.error(f"Error in verify-widget endpoint: {str(e)}")
        return jsonify(ResponseHelpers.error_response(
            "An error occurred while verifying widget"
        )), 500



# =============================================================================
# GENERAL ONBOARDING ENDPOINTS
# =============================================================================

@onboarding_bp.route('/state', methods=['GET', 'OPTIONS'])
def get_onboarding_state():
    """
    Get current onboarding state for user
    GET /onboarding/state?email=user@example.com
    """
    if request.method == 'OPTIONS':
        return jsonify({'status': 'ok'}), 200
    
    try:
        email = request.args.get('email')
        if not email:
            return jsonify(ResponseHelpers.error_response(
                "Email parameter is required"
            )), 400
        
        # Get onboarding state
        state = onboarding_service.get_onboarding_state(email)
        
        return jsonify(ResponseHelpers.success_response(
            data=state,
            message="Onboarding state retrieved"
        )), 200
        
    except Exception as e:
        logger.error(f"Error getting onboarding state: {str(e)}")
        return jsonify(ResponseHelpers.error_response(
            "An error occurred while getting onboarding state"
        )), 500


@onboarding_bp.route('/content-status/<site_id>', methods=['GET', 'OPTIONS'])
def get_content_status(site_id):
    """
    Get content processing status for a site
    GET /onboarding/content-status/<site_id>
    """
    if request.method == 'OPTIONS':
        return jsonify({'status': 'ok'}), 200
    
    try:
        # Get content uploads for site
        uploads = onboarding_service.onboarding_model.get_site_content_uploads(site_id)
        
        # Calculate summary stats
        total_uploads = len(uploads)
        completed_uploads = len([u for u in uploads if u['processing_status'] == 'completed'])
        failed_uploads = len([u for u in uploads if u['processing_status'] == 'failed'])
        pending_uploads = total_uploads - completed_uploads - failed_uploads
        
        return jsonify(ResponseHelpers.success_response(
            data={
                'site_id': site_id,
                'total_uploads': total_uploads,
                'completed_uploads': completed_uploads,
                'failed_uploads': failed_uploads,
                'pending_uploads': pending_uploads,
                'uploads': uploads
            },
            message="Content status retrieved"
        )), 200
        
    except Exception as e:
        logger.error(f"Error getting content status for {site_id}: {str(e)}")
        return jsonify(ResponseHelpers.error_response(
            "An error occurred while getting content status"
        )), 500


@onboarding_bp.route('/complete', methods=['POST', 'OPTIONS'])
def complete_onboarding():
    """
    Mark onboarding as completed (can be called from any step)
    POST /onboarding/complete
    """
    if request.method == 'OPTIONS':
        return jsonify({'status': 'ok'}), 200
    
    try:
        # Get access token
        auth_header = request.headers.get('Authorization', '')
        if not auth_header.startswith('Bearer '):
            return jsonify(ResponseHelpers.error_response(
                "Authorization token is required"
            )), 401
        
        access_token = auth_header.replace('Bearer ', '')
        
        # Verify token and get email
        from services.jwt_service import JWTService
        jwt_service = JWTService()
        token_payload = jwt_service.verify_token(access_token)
        
        if not token_payload:
            return jsonify(ResponseHelpers.error_response(
                "Invalid or expired token"
            )), 401
        
        email = token_payload.get('email')
        if not email:
            return jsonify(ResponseHelpers.error_response(
                "Email not found in token"
            )), 400
        
        # Complete onboarding
        success = onboarding_service.onboarding_model.complete_onboarding(email)
        
        if success:
            return jsonify(ResponseHelpers.success_response(
                data={
                    'completed': True,
                    'redirect_url': 'https://dashboard.helloyuno.com'
                },
                message="Onboarding completed successfully!"
            )), 200
        else:
            return jsonify(ResponseHelpers.error_response(
                "Failed to complete onboarding"
            )), 500
            
    except Exception as e:
        logger.error(f"Error completing onboarding: {str(e)}")
        return jsonify(ResponseHelpers.error_response(
            "An error occurred while completing onboarding"
        )), 500


# =============================================================================
# UTILITY ENDPOINTS
# =============================================================================

@onboarding_bp.route('/health', methods=['GET', 'OPTIONS'])
def health_check():
    """Health check for onboarding service"""
    if request.method == 'OPTIONS':
        return jsonify({'status': 'ok'}), 200
    
    try:
        # Test database connection
        stats = onboarding_service.onboarding_model.get_onboarding_stats()
        
        return jsonify({
            'status': 'healthy',
            'service': 'onboarding',
            'timestamp': datetime.utcnow().isoformat(),
            'stats': stats
        }), 200
        
    except Exception as e:
        logger.error(f"Onboarding health check failed: {str(e)}")
        return jsonify({
            'status': 'unhealthy',
            'service': 'onboarding',
            'error': str(e),
            'timestamp': datetime.utcnow().isoformat()
        }), 500


@onboarding_bp.route('/validate-email', methods=['POST', 'OPTIONS'])
def validate_email():
    """
    Validate email format (utility endpoint)
    POST /onboarding/validate-email
    """
    if request.method == 'OPTIONS':
        return jsonify({'status': 'ok'}), 200
    
    try:
        data = request.get_json()
        if not data:
            return jsonify(ResponseHelpers.error_response(
                "Email is required"
            )), 400
        
        email = data.get('email')
        if not email:
            return jsonify(ResponseHelpers.error_response(
                "Email is required"
            )), 400
        
        is_valid = ValidationHelpers.validate_email(email)
        
        return jsonify(ResponseHelpers.success_response(
            data={
                'email': email,
                'valid': is_valid
            },
            message="Email validation completed"
        )), 200
        
    except Exception as e:
        logger.error(f"Error validating email: {str(e)}")
        return jsonify(ResponseHelpers.error_response(
            "An error occurred while validating email"
        )), 500


@onboarding_bp.route('/validate-domain', methods=['POST', 'OPTIONS'])
def validate_domain():
    """
    Validate domain format (utility endpoint)
    POST /onboarding/validate-domain
    """
    if request.method == 'OPTIONS':
        return jsonify({'status': 'ok'}), 200
    
    try:
        data = request.get_json()
        if not data:
            return jsonify(ResponseHelpers.error_response(
                "Domain is required"
            )), 400
        
        domain = data.get('domain')
        if not domain:
            return jsonify(ResponseHelpers.error_response(
                "Domain is required"
            )), 400
        
        # Clean and validate domain
        from services.domain_service import DomainService
        domain_service = DomainService()
        
        clean_domain = domain_service.clean_domain(domain)
        is_valid = domain_service.validate_domain_format(clean_domain)
        
        return jsonify(ResponseHelpers.success_response(
            data={
                'original_domain': domain,
                'clean_domain': clean_domain,
                'valid': is_valid
            },
            message="Domain validation completed"
        )), 200
        
    except Exception as e:
        logger.error(f"Error validating domain: {str(e)}")
        return jsonify(ResponseHelpers.error_response(
            "An error occurred while validating domain"
        )), 500


# =============================================================================
# ERROR HANDLERS
# =============================================================================

@onboarding_bp.errorhandler(404)
def not_found(error):
    """Handle 404 errors"""
    return jsonify(ResponseHelpers.error_response(
        "Endpoint not found",
        error_code="not_found"
    )), 404


@onboarding_bp.errorhandler(405)
def method_not_allowed(error):
    """Handle 405 errors"""
    return jsonify(ResponseHelpers.error_response(
        "Method not allowed",
        error_code="method_not_allowed"
    )), 405


@onboarding_bp.errorhandler(500)
def internal_error(error):
    """Handle 500 errors"""
    logger.error(f"Internal server error in onboarding: {error}")
    return jsonify(ResponseHelpers.error_response(
        "Internal server error",
        error_code="internal_error"
    )), 500

# Add this to your routes/onboarding.py

@onboarding_bp.route('/debug/email-comprehensive', methods=['POST', 'OPTIONS'])
def comprehensive_email_debug():
    """Comprehensive email service debugging"""
    if request.method == 'OPTIONS':
        return jsonify({'status': 'ok'}), 200
    
    try:
        import os
        from services.email_service import EmailService
        
        data = request.get_json()
        test_email = data.get('email', 'test@example.com') if data else 'test@example.com'
        
        debug_info = {
            'timestamp': datetime.utcnow().isoformat(),
            'test_email': test_email
        }
        
        # 1. Check environment variables
        resend_key = os.getenv('RESEND_API_KEY')
        from_email = os.getenv('RESEND_FROM_EMAIL')
        
        debug_info['environment'] = {
            'RESEND_API_KEY_set': bool(resend_key),
            'RESEND_API_KEY_prefix': resend_key[:15] + '...' if resend_key else None,
            'RESEND_FROM_EMAIL': from_email,
            'RESEND_FROM_EMAIL_set': bool(from_email)
        }
        
        # 2. Test resend module import
        try:
            import resend
            debug_info['resend_module'] = {
                'imported': True,
                'version': getattr(resend, '__version__', 'unknown'),
                'api_key_set_in_module': hasattr(resend, 'api_key') and bool(resend.api_key)
            }
        except Exception as e:
            debug_info['resend_module'] = {
                'imported': False,
                'error': str(e)
            }
        
        # 3. Test EmailService initialization
        try:
            email_service = EmailService()
            debug_info['email_service'] = {
                'initialized': True,
                'from_email': email_service.from_email,
                'api_key_available': bool(email_service.api_key)
            }
            
            # 4. Test connection
            connection_test = email_service.test_connection()
            debug_info['connection_test'] = connection_test
            
            # 5. Test actual OTP email
            if connection_test.get('success'):
                otp_test = email_service.send_otp_email(test_email, '123456')
                debug_info['otp_email_test'] = otp_test
            else:
                debug_info['otp_email_test'] = {
                    'skipped': 'Connection test failed'
                }
                
        except Exception as e:
            debug_info['email_service'] = {
                'initialized': False,
                'error': str(e),
                'error_type': type(e).__name__
            }
        
        return jsonify(debug_info), 200
        
    except Exception as e:
        logger.error(f"Comprehensive email debug failed: {str(e)}")
        return jsonify({
            'error': str(e),
            'error_type': type(e).__name__,
            'timestamp': datetime.utcnow().isoformat()
        }), 500


@onboarding_bp.route('/debug/resend-raw-test', methods=['POST', 'OPTIONS'])
def resend_raw_test():
    """Test Resend API directly without our wrapper"""
    if request.method == 'OPTIONS':
        return jsonify({'status': 'ok'}), 200
    
    try:
        import os
        import resend
        
        # Set API key directly
        api_key = os.getenv('RESEND_API_KEY')
        from_email = os.getenv('RESEND_FROM_EMAIL', 'say@helloyuno.com')
        
        if not api_key:
            return jsonify({
                'error': 'RESEND_API_KEY not set',
                'timestamp': datetime.utcnow().isoformat()
            }), 400
        
        resend.api_key = api_key
        
        data = request.get_json()
        test_email = data.get('email', 'test@example.com') if data else 'test@example.com'
        
        # Simple test email
        params = {
            "from": from_email,
            "to": [test_email],
            "subject": "Yuno API Test",
            "text": "This is a raw test of the Resend API from Yuno backend."
        }
        
        logger.info(f"🔬 Raw Resend test - API Key: {api_key[:15]}...")
        logger.info(f"🔬 Raw Resend test - From: {from_email}")
        logger.info(f"🔬 Raw Resend test - To: {test_email}")
        
        response = resend.Emails.send(params)
        
        logger.info(f"🔬 Raw Resend response: {response}")
        
        return jsonify({
            'success': True,
            'params_sent': params,
            'resend_response': response,
            'response_type': type(response).__name__,
            'timestamp': datetime.utcnow().isoformat()
        }), 200
        
    except Exception as e:
        logger.error(f"Raw Resend test failed: {str(e)}")
        import traceback
        return jsonify({
            'error': str(e),
            'error_type': type(e).__name__,
            'traceback': traceback.format_exc(),
            'timestamp': datetime.utcnow().isoformat()
        }), 500


# Replace these endpoints in routes/onboarding.py - Fixed to use correct column name

@onboarding_bp.route('/upload-text', methods=['POST'])
def upload_text_content():
    """Process text content upload - Fixed site check"""
    try:
        data = request.get_json()
        site_id = data.get('site_id')
        content = data.get('content')
        
        if not site_id or not content:
            return jsonify({'error': 'Site ID and content required'}), 400
        
        # Verify site exists - FIXED to use site_id column
        site_check = onboarding_service.onboarding_model.supabase\
            .table('sites')\
            .select('site_id')\
            .eq('site_id', site_id)\
            .single()\
            .execute()
            
        if not site_check.data:
            return jsonify({'error': 'Invalid site ID'}), 404
        
        # Create upload record
        upload_id = str(uuid.uuid4())
        onboarding_service.onboarding_model.supabase.table('content_uploads').insert({
            'id': upload_id,
            'site_id': site_id,
            'content_type': 'text',
            'content_text': content[:5000],  # Store first 5000 chars
            'processing_status': 'processing'
        }).execute()
        
        # Process content
        result = content_processor.process_text_content(site_id, content, upload_id)
        
        # Update upload status
        status = 'completed' if result['success'] else 'failed'
        onboarding_service.onboarding_model.supabase.table('content_uploads')\
            .update({
                'processing_status': status,
                'metadata': result
            })\
            .eq('id', upload_id)\
            .execute()
        
        return jsonify({
            'success': result['success'],
            'upload_id': upload_id,
            'message': 'Text content processed',
            'chunks_processed': result.get('chunks_processed', 0)
        })
        
    except Exception as e:
        logger.error(f"Error uploading text: {str(e)}")
        return jsonify({'error': 'Failed to process text'}), 500

@onboarding_bp.route('/upload-file', methods=['POST'])
def upload_file_content():
    """Process file upload - Fixed site check"""
    try:
        if 'file' not in request.files:
            return jsonify({'error': 'No file provided'}), 400
            
        file = request.files['file']
        site_id = request.form.get('site_id')
        
        if not site_id:
            return jsonify({'error': 'Site ID required'}), 400
            
        if file.filename == '':
            return jsonify({'error': 'No file selected'}), 400
            
        if not allowed_file(file.filename):
            return jsonify({'error': f'Invalid file type. Allowed: {", ".join(ALLOWED_EXTENSIONS)}'}), 400
        
        # Verify site exists - FIXED to use site_id column
        site_check = onboarding_service.onboarding_model.supabase\
            .table('sites')\
            .select('site_id')\
            .eq('site_id', site_id)\
            .single()\
            .execute()
            
        if not site_check.data:
            return jsonify({'error': 'Invalid site ID'}), 404
        
        # Check file size (25MB limit)
        file.seek(0, os.SEEK_END)
        file_size = file.tell()
        file.seek(0)
        
        if file_size > 25 * 1024 * 1024:
            return jsonify({'error': 'File too large. Maximum 25MB'}), 400
        
        # Save to Supabase Storage
        upload_id = str(uuid.uuid4())
        file_ext = file.filename.rsplit('.', 1)[1].lower()
        storage_path = f"uploads/{site_id}/{upload_id}.{file_ext}"
        
        # Upload to storage
        file_data = file.read()
        storage_response = onboarding_service.onboarding_model.supabase\
            .storage.from_('content-uploads')\
            .upload(storage_path, file_data)
        
        # Create upload record
        onboarding_service.onboarding_model.supabase.table('content_uploads').insert({
            'id': upload_id,
            'site_id': site_id,
            'content_type': 'file',
            'file_path': storage_path,
            'processing_status': 'processing',
            'metadata': {
                'filename': secure_filename(file.filename),
                'size': file_size
            }
        }).execute()
        
        # Process file
        result = content_processor.process_file_upload(
            site_id, 
            storage_path, 
            file.filename, 
            upload_id
        )
        
        # Update status
        status = 'completed' if result['success'] else 'failed'
        onboarding_service.onboarding_model.supabase.table('content_uploads')\
            .update({
                'processing_status': status,
                'metadata': {
                    'filename': file.filename,
                    'size': file_size,
                    'result': result
                }
            })\
            .eq('id', upload_id)\
            .execute()
        
        return jsonify({
            'success': result['success'],
            'upload_id': upload_id,
            'message': 'File processed successfully' if result['success'] else 'File processing failed'
        })
        
    except Exception as e:
        logger.error(f"Error uploading file: {str(e)}")
        return jsonify({'error': 'Failed to process file'}), 500

@onboarding_bp.route('/update-contact-info', methods=['POST'])
def update_contact_info():
    """Update contact information for site - Fixed site check"""
    try:
        data = request.get_json()
        site_id = data.get('site_id')
        contact_info = data.get('contact_info', {})
        
        if not site_id:
            return jsonify({'error': 'Site ID required'}), 400
            
        if not contact_info.get('supportEmail'):
            return jsonify({'error': 'Support email is required'}), 400
        
        # Verify site exists - FIXED to use site_id column
        site_check = onboarding_service.onboarding_model.supabase\
            .table('sites')\
            .select('site_id')\
            .eq('site_id', site_id)\
            .single()\
            .execute()
            
        if not site_check.data:
            return jsonify({'error': 'Invalid site ID'}), 404
        
        # Process contact info
        success = content_processor.process_contact_info(site_id, contact_info)
        
        if success:
            # GET EMAIL FROM TOKEN (add this part)
            auth_header = request.headers.get('Authorization', '')
            if auth_header.startswith('Bearer '):
                access_token = auth_header.replace('Bearer ', '')
                jwt_service = JWTService()
                token_payload = jwt_service.verify_token(access_token)
                
                if token_payload and token_payload.get('email'):
                    # Update session - user can now proceed to widget
                    onboarding_service.onboarding_model.update_onboarding_session(
                        email=token_payload['email'],
                        step=6,  # Move to widget setup
                        session_data={
                            'contact_info_added': True,
                            'content_ready': True
                        }
                    )    
            return jsonify({
                'success': True,
                'message': 'Contact information updated'
            })
        else:
            return jsonify({'error': 'Failed to update contact info'}), 500
            
    except Exception as e:
        logger.error(f"Error updating contact info: {str(e)}")
        return jsonify({'error': 'Internal server error'}), 500

@onboarding_bp.route('/upload-status/<upload_id>', methods=['GET'])
def get_upload_status(upload_id):
    """Get upload processing status"""
    try:
        result = onboarding_service.onboarding_model.supabase\
            .table('content_uploads')\
            .select('*')\
            .eq('id', upload_id)\
            .single()\
            .execute()
        
        if not result.data:
            return jsonify({'error': 'Upload not found'}), 404
        
        upload = result.data
        return jsonify({
            'upload_id': upload['id'],
            'status': upload['processing_status'],
            'content_type': upload['content_type'],
            'created_at': upload['created_at'],
            'metadata': upload.get('metadata', {})
        })
        
    except Exception as e:
        logger.error(f"Error getting upload status: {str(e)}")
        return jsonify({'error': 'Failed to get status'}), 500

# Add/update these endpoints in routes/onboarding.py for proper state management

@onboarding_bp.route('/get-user-state', methods=['GET'])
def get_user_state():
    """
    Get user's current onboarding state with proper authentication
    GET /onboarding/get-user-state
    """
    try:
        # Get JWT token
        auth_header = request.headers.get('Authorization', '')
        if not auth_header.startswith('Bearer '):
            return jsonify({'error': 'Authorization required'}), 401
            
        access_token = auth_header.replace('Bearer ', '')
        
        # Verify token and get email
        from services.jwt_service import JWTService
        jwt_service = JWTService()
        token_payload = jwt_service.verify_token(access_token)
        
        if not token_payload:
            return jsonify({'error': 'Invalid token'}), 401
            
        email = token_payload.get('email')
        if not email:
            # Try to get email from user_id if available
            user_id = token_payload.get('sub') or token_payload.get('user_id')
            if user_id:
                # Get email from profiles
                user_data = onboarding_service.onboarding_model.supabase\
                    .table('profiles')\
                    .select('email')\
                    .eq('id', user_id)\
                    .single()\
                    .execute()
                    
                if user_data.data:
                    email = user_data.data.get('email')
                    
        if not email:
            return jsonify({'error': 'User email not found'}), 400
            
        # Get onboarding session
        session = onboarding_service.onboarding_model.get_onboarding_session(email)
        
        # Get user profile
        profile_data = onboarding_service.onboarding_model.supabase\
            .table('profiles')\
            .select('*')\
            .eq('email', email)\
            .single()\
            .execute()
            
        profile = profile_data.data if profile_data.data else None
        
        # Determine current step based on data
        current_step = 1  # Default to step 1
        session_data = {}
        
        if session:
            current_step = session.get('current_step', 1)
            session_data = session.get('session_data', {})
            
        # Override step based on actual progress
        if profile:
            if profile.get('site_id'):
                # Has site_id, at least step 4 completed
                current_step = max(current_step, 5)
                session_data['site_id'] = profile['site_id']
                session_data['domain'] = profile.get('domain')
                
                # Check if widget is verified
                site_data = onboarding_service.onboarding_model.supabase\
                    .table('sites')\
                    .select('widget_verified')\
                    .eq('site_id', profile['site_id'])\
                    .single()\
                    .execute()
                    
                if site_data.data and site_data.data.get('widget_verified'):
                    current_step = 7  # Completed
            elif profile.get('name'):
                # Has profile data, at least step 3 completed
                current_step = max(current_step, 4)
                
        # Check if email is verified
        elif email:
            # Check OTP verification
            otp_data = onboarding_service.onboarding_model.supabase\
                .table('otp_verifications')\
                .select('is_verified')\
                .eq('email', email)\
                .eq('is_verified', True)\
                .order('created_at', desc=True)\
                .limit(1)\
                .execute()
                
            if otp_data.data:
                current_step = max(current_step, 3)  # OTP verified, go to profile
                
        return jsonify({
            'success': True,
            'current_step': current_step,
            'email': email,
            'session_data': session_data,
            'profile': {
                'name': profile.get('name') if profile else None,
                'site_id': profile.get('site_id') if profile else None,
                'domain': profile.get('domain') if profile else None
            },
            'completed': current_step >= 7
        })
        
    except Exception as e:
        logger.error(f"Error getting user state: {str(e)}")
        return jsonify({'error': 'Failed to get user state'}), 500

@onboarding_bp.route('/update-step', methods=['POST'])
def update_onboarding_step():
    """
    Update user's current onboarding step
    POST /onboarding/update-step
    """
    try:
        # Get JWT token
        auth_header = request.headers.get('Authorization', '')
        if not auth_header.startswith('Bearer '):
            return jsonify({'error': 'Authorization required'}), 401
            
        access_token = auth_header.replace('Bearer ', '')
        
        # Verify token
        from services.jwt_service import JWTService
        jwt_service = JWTService()
        token_payload = jwt_service.verify_token(access_token)
        
        if not token_payload:
            return jsonify({'error': 'Invalid token'}), 401
            
        email = token_payload.get('email')
        if not email:
            return jsonify({'error': 'Email not found'}), 400
            
        data = request.get_json()
        new_step = data.get('step')
        session_data = data.get('session_data', {})
        
        if not new_step:
            return jsonify({'error': 'Step number required'}), 400
            
        # Update or create session
        success = onboarding_service.onboarding_model.update_onboarding_session(
            email=email,
            step=new_step,
            session_data=session_data
        )
        
        if success:
            return jsonify({
                'success': True,
                'message': f'Updated to step {new_step}'
            })
        else:
            return jsonify({'error': 'Failed to update step'}), 500
            
    except Exception as e:
        logger.error(f"Error updating step: {str(e)}")
        return jsonify({'error': 'Failed to update step'}), 500

@onboarding_bp.route('/resume', methods=['GET'])
def resume_onboarding():
    """
    Get the appropriate route to resume onboarding
    GET /onboarding/resume
    """
    try:
        # Get JWT token
        auth_header = request.headers.get('Authorization', '')
        if not auth_header.startswith('Bearer '):
            # No token, start from beginning
            return jsonify({
                'success': True,
                'redirect_to': '/onboarding',
                'step': 1,
                'message': 'Start onboarding'
            })
            
        access_token = auth_header.replace('Bearer ', '')
        
        # Get user state
        from services.jwt_service import JWTService
        jwt_service = JWTService()
        token_payload = jwt_service.verify_token(access_token)
        
        if not token_payload:
            return jsonify({
                'success': True,
                'redirect_to': '/onboarding',
                'step': 1,
                'message': 'Invalid token, please start over'
            })
            
        email = token_payload.get('email')
        if not email:
            return jsonify({
                'success': True,
                'redirect_to': '/onboarding',
                'step': 1,
                'message': 'Please start onboarding'
            })
            
        # Get current state
        state_response = get_user_state()
        state_data = state_response[0].get_json()
        
        if not state_data.get('success'):
            return jsonify({
                'success': True,
                'redirect_to': '/onboarding',
                'step': 1,
                'message': 'Please start onboarding'
            })
            
        current_step = state_data.get('current_step', 1)
        
        # Map steps to routes
        step_routes = {
            1: '/onboarding',
            2: '/onboarding/verify-otp',
            3: '/onboarding/profile-setup',
            4: '/onboarding/domain-setup',
            5: '/onboarding/content-upload',
            6: '/onboarding/widget-script',
            7: '/onboarding/complete'
        }
        
        redirect_to = step_routes.get(current_step, '/onboarding')
        
        return jsonify({
            'success': True,
            'redirect_to': redirect_to,
            'step': current_step,
            'email': email,
            'session_data': state_data.get('session_data', {}),
            'message': f'Resume from step {current_step}'
        })
        
    except Exception as e:
        logger.error(f"Error resuming onboarding: {str(e)}")
        return jsonify({
            'success': True,
            'redirect_to': '/onboarding',
            'step': 1,
            'message': 'Error occurred, please start over'
        })

# For Content Ingestion - Update your routes/onboarding.py



# 2. Create a "skip content" endpoint for users who want to skip optional content
@onboarding_bp.route('/skip-content', methods=['POST'])
def skip_content_upload():
    """Skip optional content upload and proceed to widget setup"""
    try:
        auth_header = request.headers.get('Authorization', '')
        if not auth_header.startswith('Bearer '):
            return jsonify({'error': 'Authorization required'}), 401
            
        access_token = auth_header.replace('Bearer ', '')
        jwt_service = JWTService()
        token_payload = jwt_service.verify_token(access_token)
        
        if not token_payload:
            return jsonify({'error': 'Invalid token'}), 401
            
        email = token_payload.get('email')
        if not email:
            return jsonify({'error': 'Email not found'}), 400
            
        # Update session to widget step
        onboarding_service.onboarding_model.update_onboarding_session(
            email=email,
            step=6,  # Move to widget setup
            session_data={
                'content_skipped': True
            }
        )
        
        return jsonify({
            'success': True,
            'message': 'Proceeding to widget setup'
        })
        
    except Exception as e:
        logger.error(f"Error skipping content: {str(e)}")
        return jsonify({'error': 'Failed to skip content'}), 500

# 3. Create a combined "content complete" endpoint
@onboarding_bp.route('/content-complete', methods=['POST'])
def mark_content_complete():
    """Mark content ingestion as complete and move to widget setup"""
    try:
        auth_header = request.headers.get('Authorization', '')
        if not auth_header.startswith('Bearer '):
            return jsonify({'error': 'Authorization required'}), 401
            
        access_token = auth_header.replace('Bearer ', '')
        jwt_service = JWTService()
        token_payload = jwt_service.verify_token(access_token)
        
        if not token_payload:
            return jsonify({'error': 'Invalid token'}), 401
            
        email = token_payload.get('email')
        data = request.get_json()
        
        # Check what content was added
        content_summary = {
            'contact_info_added': data.get('contact_info_added', False),
            'text_uploaded': data.get('text_uploaded', False),
            'files_uploaded': data.get('files_uploaded', False),
            'upload_ids': data.get('upload_ids', [])
        }
        
        # Update session to widget step
        onboarding_service.onboarding_model.update_onboarding_session(
            email=email,
            step=6,  # Move to widget setup
            session_data={
                'content_complete': True,
                'content_summary': content_summary
            }
        )
        
        return jsonify({
            'success': True,
            'message': 'Content ingestion complete, proceeding to widget setup',
            'next_step': 6
        })
        
    except Exception as e:
        logger.error(f"Error marking content complete: {str(e)}")
        return jsonify({'error': 'Failed to complete content step'}), 500