# app/utils.py
from app import db
from app.models import Course, Feedback
from sqlalchemy import func
def award_xp(user, points):
    """
    Safely add XP to a student.
    """

    if not user:
        return

    if user.role == "student":

        # If xp is None, initialize it
        if user.xp is None:
            user.xp = 0

        user.xp += points

def get_trending_course():
    """
    Calculates the highest-rated course based on *clean* Phase 1 feedback.
    Returns the Course object and its average rating, or (None, 0) if no data.
    """
    # A course needs at least 2 *clean* reviews to be "trending"
    MIN_REVIEWS_FOR_TRENDING = 2 

    # 1. Create a subquery to calculate avg ratings and count for clean feedback
    # A "clean" review is one that is NOT flagged as toxic
    clean_feedback_subquery = db.session.query(
        Feedback.course_id,
        # Calculate the overall average for each review
        func.avg((Feedback.quality_rating + Feedback.assignment_rating + Feedback.grading_rating) / 3.0).label('overall_avg'),
        func.count(Feedback.id).label('review_count')
    ).filter(
        Feedback.is_flagged_for_review == False
    ).group_by(
        Feedback.course_id
    ).subquery() # This turns it into a virtual table

    # 2. Find the top course from this subquery
    trending_course_query = db.session.query(
        Course,
        clean_feedback_subquery.c.overall_avg
    ).join(
        clean_feedback_subquery,
        Course.id == clean_feedback_subquery.c.course_id
    ).filter(
        # Make sure it meets our minimum review count
        clean_feedback_subquery.c.review_count >= MIN_REVIEWS_FOR_TRENDING
    ).order_by(
        # Find the one with the highest average rating
        db.desc('overall_avg')
    ).first() # Get only the top one

    if trending_course_query:
        # We have a winner
        course = trending_course_query[0]
        avg_rating = trending_course_query[1]
        return course, avg_rating
    
    # No courses meet the criteria
    return None, 0.0