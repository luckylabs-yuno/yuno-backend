"""
Onboarding API routes - extends your existing Flask app
"""
from flask import Blueprint, request, jsonify
import logging
from datetime import datetime

# Import your existing services
from services.onboarding_service import OnboardingService
from utils.helpers import ValidationHelpers, ResponseHelpers

onboarding_bp = Blueprint('onboarding', __name__)
logger = logging.getLogger(__name__)

# Initialize service
onboarding_service = OnboardingService()

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
# STEP 5: CONTENT UPLOAD
# =============================================================================

@onboarding_bp.route('/upload-text', methods=['POST', 'OPTIONS'])
def upload_text():
    """
    Upload text content for processing
    POST /onboarding/upload-text
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
        
        data = request.get_json()
        if not data:
            return jsonify(ResponseHelpers.error_response(
                "Text content is required"
            )), 400
        
        text_content = data.get('content')
        if not text_content:
            return jsonify(ResponseHelpers.error_response(
                "Text content is required"
            )), 400
        
        # Upload text content
        result = onboarding_service.upload_text_content(access_token, text_content)
        
        if result['success']:
            return jsonify(ResponseHelpers.success_response(
                data={
                    'upload_id': result['upload_id']
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
        logger.error(f"Error in upload-text endpoint: {str(e)}")
        return jsonify(ResponseHelpers.error_response(
            "An error occurred while uploading text content"
        )), 500


@onboarding_bp.route('/upload-file', methods=['POST', 'OPTIONS'])
def upload_file():
    """
    Upload file for processing
    POST /onboarding/upload-file
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
        
        # Check if file is present
        if 'file' not in request.files:
            return jsonify(ResponseHelpers.error_response(
                "No file provided"
            )), 400
        
        file = request.files['file']
        if file.filename == '':
            return jsonify(ResponseHelpers.error_response(
                "No file selected"
            )), 400
        
        # Prepare file data
        file_data = {
            'name': file.filename,
            'type': file.content_type,
            'size': len(file.read()),
            'content': file.read()
        }
        file.seek(0)  # Reset file pointer
        
        # Upload file
        result = onboarding_service.upload_file(access_token, file_data)
        
        if result['success']:
            return jsonify(ResponseHelpers.success_response(
                data={
                    'upload_id': result['upload_id']
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
        logger.error(f"Error in upload-file endpoint: {str(e)}")
        return jsonify(ResponseHelpers.error_response(
            "An error occurred while uploading file"
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


@onboarding_bp.route('/verify-widget', methods=['POST', 'OPTIONS'])
def verify_widget():
    """
    Verify widget installation on user's website
    POST /onboarding/verify-widget
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
        
        # Verify widget installation
        result = onboarding_service.verify_widget_installation(access_token)
        
        if result['success']:
            return jsonify(ResponseHelpers.success_response(
                data={
                    'verified': result['verified'],
                    'next_step': result.get('next_step')
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