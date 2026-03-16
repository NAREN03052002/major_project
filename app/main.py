# app/routes/main.py
from flask import Blueprint, render_template, redirect, url_for, flash, request, jsonify, abort
from app import db
# Added AttendanceSession and AttendanceRecord to your original model imports
from app.models import User, Course, Feedback, Assignment, Notification, InternalMark, AttendanceSession, AttendanceRecord, Resource
from flask_login import login_required, current_user
from wtforms import StringField, SubmitField, TextAreaField, IntegerField, BooleanField
from wtforms.validators import DataRequired, NumberRange
from flask_wtf import FlaskForm
from sqlalchemy.orm import joinedload
from sqlalchemy import func, or_ 
from datetime import datetime 
from . import ai 
import numpy as np
from .utils import get_trending_course
# NEW: Required for Geofencing distance calculations
from geopy.distance import geodesic 
from app.utils import award_xp


bp = Blueprint('main', __name__)

# --- Forms ---
class FeedbackForm(FlaskForm):
    quality = IntegerField('Teaching Quality', validators=[DataRequired(), NumberRange(min=1, max=5)])
    assignment = IntegerField('Assignment Load', validators=[DataRequired(), NumberRange(min=1, max=5)])
    grading = IntegerField('Grading Fairness', validators=[DataRequired(), NumberRange(min=1, max=5)])
    review_text = TextAreaField('Written Review (Optional)')
    is_anonymous = BooleanField('Submit Anonymously')
    submit = SubmitField('Submit Feedback')

# --- Routes ---

@bp.route('/')
@bp.route('/index')
def index():
    query = request.args.get('q', '')
    sort_by = request.args.get('sort', 'newest') 
    
    # 1. Base Query for Courses
    course_query = Course.query.options(db.joinedload(Course.lecturer)).filter_by(is_active=True)
    
    upcoming_assignments = []
    recent_marks = []

    # 2. Student Specific Logic (Populates Dashboard Widgets)
    if current_user.is_authenticated and current_user.is_student:
        # Filter courses for student's branch/year
        course_query = course_query.filter(
            Course.target_year == current_user.student_year,
            Course.target_branch == current_user.branch
        )

        # WIDGET 1: Upcoming Assignments (Next 3 due in future)
        upcoming_assignments = Assignment.query.join(Course).filter(
            Course.target_year == current_user.student_year,
            Course.target_branch == current_user.branch,
            Assignment.due_date >= datetime.utcnow()
        ).order_by(Assignment.due_date.asc()).limit(3).all()

        # WIDGET 2: Recent Grades (Last 3 posted)
        recent_marks = InternalMark.query.filter_by(student_id=current_user.id)\
            .order_by(InternalMark.id.desc()).limit(3).all()

    # 3. Search Logic
    if query:
        search_term = f"%{query}%"
        course_query = course_query.join(User).filter(
            or_(
                Course.name.ilike(search_term),
                Course.code.ilike(search_term),
                Course.department_name.ilike(search_term), 
                User.username.ilike(search_term) 
            )
        )
    
    # 4. Sorting Logic
    if sort_by == 'newest':
        course_query = course_query.order_by(Course.id.desc())
    elif sort_by == 'oldest':
        course_query = course_query.order_by(Course.id.asc())
    elif sort_by == 'name_asc':
        course_query = course_query.order_by(Course.name.asc())
    
    courses = course_query.all()
    trending_course, trending_rating = get_trending_course()

    return render_template('index.html', 
                           title='Dashboard', 
                           courses=courses, 
                           trending_course=trending_course, 
                           trending_rating=trending_rating,
                           upcoming_assignments=upcoming_assignments, 
                           recent_marks=recent_marks,                 
                           now=datetime.utcnow())

@bp.route('/submit/<int:course_id>', methods=['GET'])
@login_required
def submit(course_id):
    if not current_user.is_student:
        flash('Only students can submit feedback.', 'warning')
        return redirect(url_for('main.index'))
        
    course = Course.query.get_or_404(course_id)
    
    if not course.is_active:
        flash("This course is currently pending activation by the lecturer.", "warning")
        return redirect(url_for('main.index'))

    if course.target_year != current_user.student_year or course.target_branch != current_user.branch:
        flash("You do not have permission to view or rate this course.", "danger")
        return redirect(url_for('main.index'))

    form = FeedbackForm()
    
    existing = Feedback.query.filter_by(course_id=course.id, student_user_id=current_user.id).first()
    if existing:
        form.quality.data = existing.quality_rating
        form.assignment.data = existing.assignment_rating
        form.grading.data = existing.grading_rating
        form.review_text.data = existing.review_text
        form.is_anonymous.data = existing.is_anonymous

    clean_reviews = [f for f in course.feedbacks if not f.is_flagged_for_review]
    review_count = len(clean_reviews)
    avg_quality = avg_assignment = avg_grading = overall_rating = 0
    recent_reviews = []

    if review_count > 0:
        avg_quality = sum(r.quality_rating for r in clean_reviews) / review_count
        avg_assignment = sum(r.assignment_rating for r in clean_reviews) / review_count
        avg_grading = sum(r.grading_rating for r in clean_reviews) / review_count
        overall_rating = (avg_quality + avg_assignment + avg_grading) / 3
        sorted_reviews = sorted(clean_reviews, key=lambda x: x.submitted_at, reverse=True)
        text_reviews = [r for r in sorted_reviews if r.review_text]
        recent_reviews = text_reviews[:3]

    trending_course, trending_rating = get_trending_course()
    
    return render_template('submit.html', 
                           title=f'Rate {course.code}', 
                           course=course, 
                           form=form,
                           review_count=review_count,
                           overall_rating=overall_rating,
                           avg_quality=avg_quality,
                           avg_assignment=avg_assignment,
                           avg_grading=avg_grading,
                           recent_reviews=recent_reviews,
                           trending_course=trending_course,
                           trending_rating=trending_rating)

@bp.route('/api/submit_feedback/<int:course_id>', methods=['POST'])
@login_required
def submit_feedback_api(course_id):
    if not current_user.is_student:
        return jsonify({'success': False, 'message': 'Unauthorized'}), 403
        
    course = Course.query.get_or_404(course_id)
    
    if not course.is_active:
        return jsonify({'success': False, 'message': 'Course is not active'}), 403

    if course.target_year != current_user.student_year or course.target_branch != current_user.branch:
        return jsonify({'success': False, 'message': 'Unauthorized access to this course.'}), 403

    data = request.get_json()
    
    review_text = data.get('review_text', '')
    quality = int(data.get('quality'))
    assignment = int(data.get('assignment'))
    grading = int(data.get('grading'))
    is_anonymous = data.get('is_anonymous', False)

    sent_cat = "Neutral"
    sent_score = 0.0
    is_flagged = False
    pred_quality, pred_assignment, pred_grading = None, None, None
    embedding_vector = None 

    if review_text:
        if ai.toxicity_model:
            try:
                result = ai.toxicity_model(review_text)[0]
                if result['label'] == 'toxic' and result['score'] > 0.8: 
                    is_flagged = True
                    sent_cat = "Negative" 
                    sent_score = -0.99
            except Exception: pass
        
        if ai.predictive_pipeline:
            try:
                result = ai.predictive_pipeline(review_text)[0]
                star_rating = int(result['label'].split(' ')[0])
                pred_quality = float(star_rating)
                pred_assignment = float(star_rating)
                pred_grading = float(star_rating)
                
                if star_rating >= 4: sent_cat, sent_score = "Positive", result['score']
                elif star_rating == 3: sent_cat, sent_score = "Neutral", 0.0
                else: sent_cat, sent_score = "Negative", -result['score']
            except Exception: pass

        if ai.embedding_model:
            try: embedding_vector = ai.generate_embedding(review_text)
            except Exception: pass
    
    if is_flagged: sent_cat, sent_score = "Negative", -0.99

    feedback = Feedback.query.filter_by(course_id=course.id, student_user_id=current_user.id).first()
    msg = ""

    if feedback:
        feedback.quality_rating = quality
        feedback.assignment_rating = assignment
        feedback.grading_rating = grading
        feedback.review_text = review_text
        feedback.is_anonymous = is_anonymous
        feedback.sentiment_category = sent_cat
        feedback.sentiment_score = sent_score
        feedback.is_flagged_for_review = is_flagged
        feedback.predicted_quality = pred_quality
        feedback.predicted_assignment = pred_assignment
        feedback.predicted_grading = pred_grading
        if embedding_vector is not None: feedback.set_embedding(embedding_vector)
        msg = "Your previous feedback has been updated successfully!"
    else:
        feedback = Feedback(
            course_id=course.id,
            student_user_id=current_user.id,
            quality_rating=quality,
            assignment_rating=assignment,
            grading_rating=grading,
            review_text=review_text,
            is_anonymous=is_anonymous,
            sentiment_category=sent_cat,
            sentiment_score=sent_score,
            is_flagged_for_review=is_flagged,
            predicted_quality=pred_quality,
            predicted_assignment=pred_assignment,
            predicted_grading=pred_grading
        )
        if embedding_vector is not None: feedback.set_embedding(embedding_vector)
        db.session.add(feedback)
        msg = "Your feedback has been submitted successfully!"
    

    award_xp(current_user, 10)
    db.session.commit()
    return jsonify({'success': True, 'flagged': is_flagged, 'message': 'Submitted, but flagged for review.' if is_flagged else msg})

@bp.route('/course/<int:course_id>')
@login_required
def course_details(course_id):
    course = Course.query.get_or_404(course_id)
    
    if not course.is_active:
        flash("This course is currently inactive.", "warning")
        return redirect(url_for('main.index'))
    
    # Security: Ensure student belongs to this year/branch
    if current_user.is_student:
        if course.target_year != current_user.student_year or course.target_branch != current_user.branch:
            flash("You do not have permission to view this course.", "danger")
            return redirect(url_for('main.index'))

    # 1. Fetch Assignments (Sorted by Date)
    assignments = Assignment.query.filter_by(course_id=course.id).order_by(Assignment.due_date.asc()).all()

    # 2. Fetch Internal Marks for THIS student
    student_marks = []
    if current_user.is_student:
        student_marks = InternalMark.query.filter_by(
            course_id=course.id, 
            student_id=current_user.id
        ).all()

    # 3. Fetch Reviews for display
    clean_reviews = [f for f in course.feedbacks if not f.is_flagged_for_review]
    review_count = len(clean_reviews)
    
    # 4. Calculate Stats
    avg_quality = avg_assignment = avg_grading = overall_rating = 0
    if review_count > 0:
        avg_quality = sum(r.quality_rating for r in clean_reviews) / review_count
        avg_assignment = sum(r.assignment_rating for r in clean_reviews) / review_count
        avg_grading = sum(r.grading_rating for r in clean_reviews) / review_count
        overall_rating = (avg_quality + avg_assignment + avg_grading) / 3
        
    # 5. AI Data
    review_texts = [f.review_text for f in clean_reviews if f.review_text]
    professor_tags = ai.get_professor_tags(review_texts)
    wordcloud_data = ai.get_word_cloud_data(review_texts)
    
    # Chart Data
    ratings = [round((f.quality_rating + f.assignment_rating + f.grading_rating)/3) for f in clean_reviews]
    rating_counts = [ratings.count(i) for i in range(1, 6)]
    
    sentiments = [f.sentiment_category for f in clean_reviews]
    sentiment_counts = [sentiments.count('Positive'), sentiments.count('Neutral'), sentiments.count('Negative')]

    time_feedback = [f for f in clean_reviews if f.submitted_at]
    trend_dates = [f.submitted_at.strftime('%b %d %H:%M') for f in time_feedback]
    trend_scores = [f.sentiment_score for f in time_feedback]

    chart_data = {
        'rating_counts': rating_counts,
        'sentiment_counts': sentiment_counts,
        'trend_dates': trend_dates,
        'trend_scores': trend_scores
    }

    trending_course, trending_rating = get_trending_course()
    resources = Resource.query.filter_by(course_id=course.id).order_by(Resource.id.desc()).all()

    return render_template('course_details.html', 
                            course=course,
                            assignments=assignments,
                            resources=resources,
                           title=f'{course.name}', 
                           student_marks=student_marks,
                           all_feedback=clean_reviews,
                           chart_data=chart_data,
                           professor_tags=professor_tags,
                           wordcloud_data=wordcloud_data,
                           now=datetime.utcnow(),
                           trending_course=trending_course,
                           trending_rating=trending_rating)

@bp.route('/trending/<int:course_id>')
def trending_course_details(course_id):
    course = Course.query.get_or_404(course_id)
    if not course.is_active:
        flash("This course is currently inactive.", "warning")
        return redirect(url_for('main.index'))

    clean_feedback = Feedback.query.filter(Feedback.course_id == course_id, Feedback.is_flagged_for_review == False).all()
    review_count = len(clean_feedback)
    
    overall_avg = 0
    avg_quality, avg_assignment, avg_grading, avg_sentiment = 0, 0, 0, 0

    if review_count > 0:
        avg_quality = sum(f.quality_rating for f in clean_feedback) / review_count
        avg_assignment = sum(f.assignment_rating for f in clean_feedback) / review_count
        avg_grading = sum(f.grading_rating for f in clean_feedback) / review_count
        avg_sentiment = sum(f.sentiment_score for f in clean_feedback) / review_count
        overall_avg = (avg_quality + avg_assignment + avg_grading) / 3

    review_texts = [f.review_text for f in clean_feedback if f.review_text]
    topics = ai.get_topics(review_texts, n_topics=3, n_words=3)
    professor_tags = ai.get_professor_tags(review_texts)
    ai_summary = ai.generate_summary(review_texts)

    trending_course, trending_rating = get_trending_course()

    return render_template('trending_details.html', 
                           title=f'Trending Course: {course.name}', 
                           course=course,
                           overall_avg=overall_avg,
                           avg_quality=avg_quality,
                           avg_assignment=avg_assignment,
                           avg_grading=avg_grading,
                           avg_sentiment=avg_sentiment,
                           review_count=review_count,
                           topics=topics,
                           professor_tags=professor_tags, 
                           ai_summary=ai_summary,
                           trending_course=trending_course,
                           trending_rating=trending_rating)

@bp.route('/search', methods=['GET'])
def search():
    query = request.args.get('q', '')
    trending_course, trending_rating = get_trending_course()
    
    if not query:
        return render_template('search_results.html', results=[], query=None, trending_course=trending_course, trending_rating=trending_rating)

    search_base = Course.query.filter(Course.is_active == True)
    
    if current_user.is_authenticated and current_user.is_student:
        search_base = search_base.filter(
            Course.target_year == current_user.student_year,
            Course.target_branch == current_user.branch
        )

    course_matches = search_base.filter(
        (Course.name.ilike(f'%{query}%')) | 
        (Course.code.ilike(f'%{query}%')) |
        (Course.department_name.ilike(f'%{query}%')) |
        (Course.lecturer.has(User.username.ilike(f'%{query}%')))
    ).all()

    all_reviews = Feedback.query.filter(
        Feedback.is_flagged_for_review == False,
        Feedback.embedding_json.isnot(None)
    ).all()

    review_matches = ai.semantic_search(query, all_reviews, top_k=5)

    return render_template('search_results.html', 
                           query=query, 
                           courses=course_matches, 
                           reviews=review_matches,
                           trending_course=trending_course, 
                           trending_rating=trending_rating)

@bp.route('/lecturer/<int:user_id>')
def lecturer_profile(user_id):
    lecturer = User.query.get_or_404(user_id)
    if not lecturer.is_lecturer:
        flash('User is not a lecturer.', 'danger')
        return redirect(url_for('main.index'))

    courses = [c for c in lecturer.courses_taught if c.is_active]
    
    all_reviews = []
    for c in courses:
        clean = [f for f in c.feedbacks if not f.is_flagged_for_review]
        all_reviews.extend(clean)
    
    count = len(all_reviews)
    overall = 0.0
    if count > 0:
        total = sum((f.quality_rating + f.assignment_rating + f.grading_rating) / 3 for f in all_reviews)
        overall = round(total / count, 1)

    txts = [f.review_text for f in all_reviews if f.review_text]
    tags = ai.get_professor_tags(txts)
    summary = ai.generate_summary(txts)

    trending_course, trending_rating = get_trending_course()
    return render_template('lecturer_profile.html', lecturer=lecturer, courses=courses,
                           review_count=count, overall_rating=overall, tags=tags, summary=summary,
                           trending_course=trending_course, trending_rating=trending_rating)

@bp.route('/course/<int:course_id>/insights')
@login_required
def course_insights(course_id):
    course = Course.query.get_or_404(course_id)
    
    if not course.is_active:
        flash("This course is currently inactive.", "warning")
        return redirect(url_for('main.index'))
    
    if current_user.is_student:
        if course.target_year != current_user.student_year or course.target_branch != current_user.branch:
            flash("You do not have permission to view this course.", "danger")
            return redirect(url_for('main.index'))
    
    clean_reviews = [f for f in course.feedbacks if not f.is_flagged_for_review]
    review_count = len(clean_reviews)
    
    avg_quality = avg_assignment = avg_grading = overall_rating = 0
    recent_reviews = []

    if review_count > 0:
        avg_quality = sum(r.quality_rating for r in clean_reviews) / review_count
        avg_assignment = sum(r.assignment_rating for r in clean_reviews) / review_count
        avg_grading = sum(r.grading_rating for r in clean_reviews) / review_count
        overall_rating = (avg_quality + avg_assignment + avg_grading) / 3
        
        sorted_reviews = sorted(clean_reviews, key=lambda x: x.submitted_at, reverse=True)
        text_reviews = [r for r in sorted_reviews if r.review_text]
        recent_reviews = text_reviews[:5]

    trending_course, trending_rating = get_trending_course()
    
    return render_template('course_insights.html', 
                           title=f'{course.code} Insights', 
                           course=course, 
                           review_count=review_count,
                           overall_rating=overall_rating,
                           avg_quality=avg_quality,
                           avg_assignment=avg_assignment,
                           avg_grading=avg_grading,
                           recent_reviews=recent_reviews,
                           trending_course=trending_course,
                           trending_rating=trending_rating)

@bp.route('/global_chat')
@login_required
def global_chat():
    if not current_user.is_student:
        flash("Only students can access the AI Advisor.", "warning")
        return redirect(url_for('main.index'))
    return render_template('global_chat.html')

@bp.route('/api/global_chat_message', methods=['POST'])
@login_required
def global_chat_message():

    data = request.get_json()
    question = data.get("message")  

    question_lower = question.lower()

# --- BEST LECTURER QUESTION ---
    if "best lecturer" in question_lower or "best professor" in question_lower:

        result = db.session.query(
            Course.name,
        func.avg((Feedback.quality_rating + Feedback.assignment_rating + Feedback.grading_rating)/3).label("avg_score")
        ).join(Feedback).group_by(Course.id).order_by(func.avg((Feedback.quality_rating + Feedback.assignment_rating + Feedback.grading_rating)/3).desc()).first()

        if result:
            return jsonify({
                "answer": f"Based on student feedback, the course '{result.name}' currently has the highest lecturer rating."
            })


# --- HARDEST COURSE QUESTION ---
    if "hardest" in question_lower or "most difficult" in question_lower:

        result = db.session.query(
            Course.name,
            func.avg(Feedback.assignment_rating).label("difficulty")
        ).join(Feedback).group_by(Course.id).order_by(func.avg(Feedback.assignment_rating).desc()).first()

        if result:
            return jsonify({
                "answer": f"Students report that '{result.name}' has the most challenging assignments."
         })


# --- MOST RECOMMENDED COURSE ---
    if "recommended" in question_lower or "most liked" in question_lower:

        result = db.session.query(
            Course.name,
            func.avg(Feedback.sentiment_score).label("sentiment")
        ).join(Feedback).group_by(Course.id).order_by(func.avg(Feedback.sentiment_score).desc()).first()

        if result:
            return jsonify({
                "answer": f"Based on overall sentiment from reviews, '{result.name}' is the most recommended course."
            })

    # get all reviews
    all_reviews = Feedback.query.filter(Feedback.review_text != None).all()

    relevant = ai.semantic_search(question, all_reviews, top_k=15)

    try:

        if relevant:
            answer = ai.generate_rag_answer("Global", question, relevant)
        else:
            answer = ai.general_academic_answer(question)

    except Exception as e:
        print("AI ERROR:", e)
        answer = "Sorry, I encountered an error while connecting to the AI service."

    return jsonify({"answer": answer})

# --- NEW: SMART ATTENDANCE STUDENT ROUTE ---

@bp.route('/attendance/mark', methods=['POST'])
@login_required
def mark_attendance():
    """Triple-Lock Verification: Dynamic Token + GPS Geofencing + Device Binding"""
    data = request.json
    token = data.get('token')
    student_lat = data.get('lat')
    student_lon = data.get('lon')
    device_id = data.get('device_id') 

    # 1. Validate Token & Active Session
    session = AttendanceSession.query.filter_by(session_token=token, is_active=True).first()
    if not session or datetime.utcnow() > session.expires_at:
        return jsonify({"success": False, "message": "Invalid or expired session code."}), 400

    # 2. Geofencing check (50m radius)
    if session.lat and session.lon:
        if geodesic((session.lat, session.lon), (student_lat, student_lon)).meters > 50:
            return jsonify({"success": False, "message": "Location check failed. You are outside the classroom."}), 403

    # 3. Device Binding: Prevent proxy attendance (one phone per session)
    if AttendanceRecord.query.filter_by(session_id=session.id, device_fingerprint=device_id).first():
        return jsonify({"success": False, "message": "This device has already been used for this session."}), 403

    # 4. Success: Record Attendance
    if not AttendanceRecord.query.filter_by(session_id=session.id, student_id=current_user.id).first():
        db.session.add(AttendanceRecord(session_id=session.id, student_id=current_user.id, device_fingerprint=device_id))
        award_xp(current_user, 5)
        db.session.commit()

    return jsonify({"success": True, "message": "Attendance marked successfully! ✅"})

@bp.route('/student/profile')
@login_required
def student_profile():
    if not current_user.is_student:
        flash('Access restricted to students.', 'warning')
        return redirect(url_for('main.index'))
    
    my_reviews = Feedback.query.filter_by(student_user_id=current_user.id)\
                                .options(db.joinedload(Feedback.course))\
                                .order_by(Feedback.submitted_at.desc())\
                                .all()
    
    total_reviews = len(my_reviews)
    avg_given = 0.0
    if total_reviews > 0:
        total_score = sum((r.quality_rating + r.assignment_rating + r.grading_rating) / 3 for r in my_reviews)
        avg_given = round(total_score / total_reviews, 1)

    trending_course, trending_rating = get_trending_course()
    return render_template('student_profile.html', title='My Profile', reviews=my_reviews, 
                           total_reviews=total_reviews, avg_given=avg_given,
                           trending_course=trending_course, trending_rating=trending_rating)

@bp.route('/delete_feedback/<int:feedback_id>', methods=['POST'])
@login_required
def delete_feedback(feedback_id):
    feedback = Feedback.query.get_or_404(feedback_id)
    if feedback.student_user_id != current_user.id:
        flash('You do not have permission to delete this review.', 'danger')
        return redirect(url_for('main.student_profile'))
        
    db.session.delete(feedback)
    db.session.commit()
    flash('Review deleted successfully.', 'success')
    return redirect(url_for('main.student_profile'))


@bp.route('/notifications')
@login_required
def notifications():
    user_notifs = Notification.query.filter_by(recipient_id=current_user.id)\
        .order_by(Notification.created_at.desc()).all()
    
    return render_template('notifications.html', notifications=user_notifs)

@bp.route('/notifications/mark_read/<int:notif_id>')
@login_required
def mark_notification_read(notif_id):
    notif = Notification.query.get_or_404(notif_id)
    if notif.recipient_id == current_user.id:
        notif.is_read = True
        db.session.commit()
        return redirect(notif.link) 
    abort(403)

@bp.route('/notifications/clear_all')
@login_required
def clear_all_notifications():
    Notification.query.filter_by(recipient_id=current_user.id, is_read=False).update({'is_read': True})
    db.session.commit()
    flash('All notifications marked as read.', 'success')
    return redirect(url_for('main.notifications'))


@bp.route('/leaderboard')
@login_required
def leaderboard():

    

    students = User.query.filter_by(role='student')\
        .order_by(func.coalesce(User.xp, 0).desc())\
        .all()

    

    return render_template(
        'leaderboard.html',
        students=students
    )