# app/api.py
from flask import Blueprint, jsonify
from app.models import Course
from . import ai

# We set the url_prefix so all routes here start with /api/v1
bp = Blueprint('api_public', __name__, url_prefix='/api/v1')

# --- 1. Health Check Endpoint (Monitoring) ---
@bp.route('/health', methods=['GET'])
def health_check():
    """
    Returns the status of the application and AI models.
    Used by cloud platforms (like Render/AWS) to know if the app is alive.
    """
    # Check if AI models are loaded
    ai_status = {
        "sentiment": "active" if ai.sentiment_pipeline else "inactive",
        "toxicity": "active" if ai.toxicity_model else "inactive",
        "predictive": "active" if ai.predictive_pipeline else "inactive"
    }
    
    # Determine overall health
    status = "healthy"
    if "inactive" in ai_status.values():
        status = "degraded"

    return jsonify({
        "status": status,
        "service": "AI Powered Academic Analytics Platform API",
        "ai_models": ai_status
    }), 200

# --- 2. Public Read-Only API (Data Access) ---
@bp.route('/courses', methods=['GET'])
def get_courses():
    """
    Returns a JSON list of all courses.
    """
    courses = Course.query.all()
    data = []
    for c in courses:
        data.append({
            "id": c.id,
            "code": c.code,
            "name": c.name,
            "lecturer": c.lecturer.username
        })
    return jsonify(data), 200

@bp.route('/courses/<int:course_id>', methods=['GET'])
def get_course_details(course_id):
    """
    Returns JSON details for a specific course, including calculated average.
    """
    course = Course.query.get_or_404(course_id)
    
    # Calculate average from clean reviews only
    clean_feedback = [f for f in course.feedbacks if not f.is_flagged_for_review]
    avg_rating = 0.0
    if clean_feedback:
        total_score = sum((f.quality_rating + f.assignment_rating + f.grading_rating) / 3 for f in clean_feedback)
        avg_rating = round(total_score / len(clean_feedback), 1)

    return jsonify({
        "id": course.id,
        "code": course.code,
        "name": course.name,
        "lecturer": course.lecturer.username,
        "review_count": len(clean_feedback),
        "average_rating": avg_rating
    }), 200