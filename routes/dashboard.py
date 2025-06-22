from flask import Blueprint, request, jsonify, g
from middleware.dashboard_auth import DashboardAuthMiddleware
from models.site import SiteModel
from models.onboarding import OnboardingModel
from services.jwt_service import JWTService
import logging

logger = logging.getLogger(__name__)

dashboard_bp = Blueprint('dashboard', __name__, url_prefix='/dashboard')
auth_middleware = DashboardAuthMiddleware()

@dashboard_bp.route('/auth/verify-token', methods=['POST'])
@auth_middleware.require_dashboard_auth
def verify_token():
    """
    Verify dashboard access token and return user info
    POST /dashboard/auth/verify-token
    """
    try:
        current_user = auth_middleware.get_current_user()
        
        # Get user profile and site info
        onboarding_model = OnboardingModel()
        site_model = SiteModel()
        
        # Get user profile
        profile_data = onboarding_model.supabase.table('profiles')\
            .select('*')\
            .eq('id', current_user['user_id'])\
            .single()\
            .execute()
        
        if not profile_data.data:
            return jsonify({
                'error': 'User profile not found',
                'code': 'PROFILE_NOT_FOUND'
            }), 404
        
        profile = profile_data.data
        
        # Get site info
        site_info = None
        if profile.get('site_id'):
            site_info = site_model.get_site_by_id(profile['site_id'])
        
        return jsonify({
            'success': True,
            'data': {
                'user': {
                    'id': profile['id'],
                    'email': profile['email'],
                    'name': profile.get('name'),
                    'created_at': profile.get('created_at')
                },
                'site': {
                    'site_id': profile.get('site_id'),
                    'domain': profile.get('domain'),
                    'plan': profile.get('plan', 'pro'),
                    'widget_enabled': site_info.get('widget_enabled', True) if site_info else True,
                    'theme': site_info.get('theme', 'dark') if site_info else 'dark',
                    'created_at': site_info.get('created_at') if site_info else None
                } if profile.get('site_id') else None
            }
        })
        
    except Exception as e:
        logger.error(f"Error verifying dashboard token: {str(e)}")
        return jsonify({
            'error': 'Failed to verify token',
            'code': 'VERIFICATION_FAILED'
        }), 500

@dashboard_bp.route('/auth/refresh-token', methods=['POST'])
@auth_middleware.require_dashboard_auth
def refresh_token():
    """
    Refresh dashboard access token
    POST /dashboard/auth/refresh-token
    """
    try:
        current_user = auth_middleware.get_current_user()
        jwt_service = JWTService()
        
        # Generate new access token
        new_token = jwt_service.generate_access_token(
            user_id=current_user['user_id'],
            email=current_user['email']
        )
        
        return jsonify({
            'success': True,
            'data': {
                'access_token': new_token,
                'expires_in': 3600  # 1 hour
            }
        })
        
    except Exception as e:
        logger.error(f"Error refreshing dashboard token: {str(e)}")
        return jsonify({
            'error': 'Failed to refresh token',
            'code': 'REFRESH_FAILED'
        }), 500

@dashboard_bp.route('/auth/logout', methods=['POST'])
@auth_middleware.require_dashboard_auth
def logout():
    """
    Logout from dashboard (client-side token cleanup)
    POST /dashboard/auth/logout
    """
    try:
        # For JWT tokens, we just return success
        # Token invalidation would be handled client-side
        return jsonify({
            'success': True,
            'message': 'Logged out successfully'
        })
        
    except Exception as e:
        logger.error(f"Error during dashboard logout: {str(e)}")
        return jsonify({
            'error': 'Logout failed',
            'code': 'LOGOUT_FAILED'
        }), 500

@dashboard_bp.route('/user/profile', methods=['GET'])
@auth_middleware.require_dashboard_auth
def get_user_profile():
    """
    Get current user's profile information
    GET /dashboard/user/profile
    """
    try:
        current_user = auth_middleware.get_current_user()
        onboarding_model = OnboardingModel()
        
        # Get detailed profile
        profile_data = onboarding_model.supabase.table('profiles')\
            .select('*')\
            .eq('id', current_user['user_id'])\
            .single()\
            .execute()
        
        if not profile_data.data:
            return jsonify({
                'error': 'Profile not found',
                'code': 'PROFILE_NOT_FOUND'
            }), 404
        
        profile = profile_data.data
        
        return jsonify({
            'success': True,
            'data': {
                'id': profile['id'],
                'email': profile['email'],
                'name': profile.get('name'),
                'country': profile.get('country'),
                'date_of_birth': profile.get('date_of_birth'),
                'site_id': profile.get('site_id'),
                'domain': profile.get('domain'),
                'plan': profile.get('plan', 'pro'),
                'created_at': profile.get('created_at'),
                'updated_at': profile.get('updated_at')
            }
        })
        
    except Exception as e:
        logger.error(f"Error getting user profile: {str(e)}")
        return jsonify({
            'error': 'Failed to get profile',
            'code': 'PROFILE_FETCH_FAILED'
        }), 500

@dashboard_bp.route('/user/profile', methods=['PUT'])
@auth_middleware.require_dashboard_auth
def update_user_profile():
    """
    Update current user's profile information
    PUT /dashboard/user/profile
    """
    try:
        current_user = auth_middleware.get_current_user()
        data = request.get_json()
        
        if not data:
            return jsonify({
                'error': 'Request body required',
                'code': 'DATA_REQUIRED'
            }), 400
        
        # Allowed fields to update
        allowed_fields = ['name', 'country']
        update_data = {k: v for k, v in data.items() if k in allowed_fields}
        
        if not update_data:
            return jsonify({
                'error': 'No valid fields to update',
                'code': 'INVALID_FIELDS'
            }), 400
        
        # Update profile
        onboarding_model = OnboardingModel()
        update_data['updated_at'] = 'now()'
        
        result = onboarding_model.supabase.table('profiles')\
            .update(update_data)\
            .eq('id', current_user['user_id'])\
            .execute()
        
        if not result.data:
            return jsonify({
                'error': 'Failed to update profile',
                'code': 'UPDATE_FAILED'
            }), 500
        
        return jsonify({
            'success': True,
            'message': 'Profile updated successfully',
            'data': result.data[0]
        })
        
    except Exception as e:
        logger.error(f"Error updating user profile: {str(e)}")
        return jsonify({
            'error': 'Failed to update profile',
            'code': 'UPDATE_FAILED'
        }), 500