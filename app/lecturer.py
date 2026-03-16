# app/routes/lecturer.py
# app/routes/lecturer.py
import os
import csv
import io
import random
from datetime import datetime, timedelta

from flask import Blueprint, render_template, redirect, url_for, flash, make_response, request, jsonify, current_app
from flask_login import login_required, current_user
from functools import wraps
from sqlalchemy import or_, and_, func
from sqlalchemy.orm import joinedload
from werkzeug.security import check_password_hash, generate_password_hash
from werkzeug.utils import secure_filename

from app import db
from app.models import User, Course, Feedback, Assignment, InternalMark, AttendanceSession, AttendanceRecord, Resource
from . import ai
from .utils import get_trending_course

bp = Blueprint('lecturer', __name__, url_prefix='/lecturer')

# --- Decorator ---
def lecturer_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated or not current_user.is_lecturer:
            flash('You do not have permission to access this page.', 'danger')
            return redirect(url_for('main.index'))
        return f(*args, **kwargs)
    return decorated_function

@bp.route('/resource/<int:resource_id>/delete', methods=['POST'])
@login_required
@lecturer_required
def delete_resource(resource_id):
    """Allows lecturers to remove uploaded materials."""
    resource = Resource.query.get_or_404(resource_id)
    course_id = resource.course_id
    if resource.course.lecturer_user_id != current_user.id:
        flash('Unauthorized.', 'danger')
        return redirect(url_for('lecturer.dashboard'))
    
    # Optional: Delete the actual file from storage
    try:
        file_path = os.path.join(current_app.root_path, 'static/uploads', resource.file_path)
        if os.path.exists(file_path):
            os.remove(file_path)
    except:
        pass

    db.session.delete(resource)
    db.session.commit()
    flash('Resource deleted.', 'success')
    return redirect(url_for('lecturer.course_details', course_id=course_id))

# --- SMART ATTENDANCE ROUTES ---

@bp.route('/course/<int:course_id>/attendance/start', methods=['POST']) 
@login_required
@lecturer_required
def start_attendance(course_id):
    AttendanceSession.query.filter_by(course_id=course_id, is_active=True).update({"is_active": False})
    data = request.json
    six_digit_code = str(random.randint(100000, 999999))
    new_session = AttendanceSession(
        course_id=course_id,
        session_token=six_digit_code,
        lat=data.get('lat'),
        lon=data.get('lon'),
        expires_at=datetime.utcnow() + timedelta(minutes=5)
    )
    db.session.add(new_session)
    db.session.commit()
    return jsonify({"success": True, "session_id": new_session.id})

@bp.route('/attendance/<int:session_id>/refresh', methods=['POST'])
@login_required
@lecturer_required
def refresh_token(session_id):
    session = AttendanceSession.query.get_or_404(session_id)
    if not session.is_active or datetime.utcnow() > session.expires_at:
        return jsonify({"success": False, "message": "Session Expired"})
    new_code = str(random.randint(100000, 999999))
    session.session_token = new_code
    db.session.commit()
    return jsonify({"success": True, "token": new_code})

@bp.route('/attendance/view/<int:session_id>')
@login_required
@lecturer_required
def view_attendance_session(session_id):
    session = AttendanceSession.query.get_or_404(session_id)
    course = Course.query.get(session.course_id)
    students = User.query.filter_by(role='student', student_year=course.target_year, branch=course.target_branch).order_by(User.username.asc()).all()
    return render_template('lecturer/attendance.html', session=session, course=course, students=students)

@bp.route('/attendance/<int:session_id>/end', methods=['POST'])
@login_required
@lecturer_required
def end_attendance(session_id):
    session = AttendanceSession.query.get_or_404(session_id)
    session.is_active = False
    session.expires_at = datetime.utcnow()
    db.session.commit()
    return jsonify({"success": True})

@bp.route('/attendance/manual_mark', methods=['POST'])
@login_required
@lecturer_required
def mark_manual():
    data = request.json
    exists = AttendanceRecord.query.filter_by(session_id=data.get('session_id'), student_id=data.get('student_id')).first()
    if not exists:
        db.session.add(AttendanceRecord(session_id=data.get('session_id'), student_id=data.get('student_id'), is_manual=True, marked_by_id=current_user.id))
        db.session.commit()
    return jsonify({"success": True})

@bp.route('/attendance/<int:session_id>/get_present')
@login_required
@lecturer_required
def get_present_students(session_id):
    records = AttendanceRecord.query.filter_by(session_id=session_id).all()
    student_list = [{"name": r.student.username} for r in records]
    return jsonify({"students": student_list})

@bp.route('/attendance/download/<int:session_id>')  
@login_required
@lecturer_required
def download_attendance(session_id):
    session = AttendanceSession.query.get_or_404(session_id)
    records = AttendanceRecord.query.filter_by(session_id=session_id).all()
    si = io.StringIO()
    cw = csv.writer(si)
    cw.writerow(['Student Name', 'Timestamp', 'Verification Type'])
    for r in records:
        v_type = "Manual" if r.is_manual else "Smart (GPS/Device)"
        cw.writerow([r.student.username, r.timestamp.strftime('%Y-%m-%d %H:%M'), v_type])
    output = make_response(si.getvalue())
    output.headers["Content-Disposition"] = f"attachment; filename=attendance_{session.course.code}_{session.created_at.strftime('%Y-%m-%d')}.csv"
    output.headers["Content-type"] = "text/csv"
    return output

# --- DASHBOARD ---

@bp.route('/dashboard', methods=['GET'])
@login_required
@lecturer_required
def dashboard():
    active_courses = Course.query.filter_by(lecturer_user_id=current_user.id, is_active=True).all()
    pending_subjects = Course.query.filter_by(lecturer_user_id=current_user.id, is_active=False).all()
    course_ids = [c.id for c in active_courses]

    # CORRECTED: Fetch all attendance sessions for history logs
    attendance_history = AttendanceSession.query.filter(AttendanceSession.course_id.in_(course_ids))\
        .order_by(AttendanceSession.created_at.desc()).all()

    all_feedback = Feedback.query.filter(Feedback.course_id.in_(course_ids)).options(joinedload(Feedback.course), joinedload(Feedback.student)).all()
    clean_feedback = [f for f in all_feedback if not f.is_flagged_for_review]

    course_analytics = []
    for course in active_courses:
        af = [f for f in clean_feedback if f.course_id == course.id]
        txts = [f.review_text for f in af if f.review_text]
        topics = ai.get_topics(txts, n_topics=3, n_words=3)
        avg_o = sum((f.quality_rating + f.assignment_rating + f.grading_rating)/3 for f in af) / len(af) if af else 0
        avg_s = sum(f.sentiment_score for f in af) / len(af) if af else 0
        course_analytics.append({'id': course.id, 'name': course.name, 'code': course.code, 'review_count': len(af), 'overall': avg_o, 'sentiment': avg_s, 'topics': topics})
    
    trending_course, trending_rating = get_trending_course()

    return render_template('lecturer/dashboard.html', 
                           title='Lecturer Dashboard', 
                           analytics=course_analytics, 
                           pending_subjects=pending_subjects, 
                           attendance_history=attendance_history, 
                           mismatched_reviews=[], 
                           trending_course=trending_course, 
                           trending_rating=trending_rating)

# --- PRESERVED MANAGEMENT ROUTES ---

@bp.route('/activate_course', methods=['POST'])
@login_required
@lecturer_required
def activate_course():
    course_id = request.form.get('course_id')
    course = Course.query.filter_by(id=course_id, lecturer_user_id=current_user.id).first()
    if course:
        course.is_active = True
        db.session.commit()
        flash(f'Feedback form for {course.name} has been activated!', 'success')
    else: flash('Invalid subject selected.', 'danger')
    return redirect(url_for('lecturer.dashboard'))

@bp.route('/course/<int:course_id>')
@login_required
@lecturer_required
def course_details(course_id):
    course = Course.query.get_or_404(course_id)
    if course.lecturer_user_id != current_user.id:
        flash('You do not have permission to view this course.', 'danger')
        return redirect(url_for('lecturer.dashboard'))
    all_feedback = Feedback.query.filter_by(course_id=course.id).options(joinedload(Feedback.student)).order_by(Feedback.submitted_at.asc()).all()
    clean_feedback = [f for f in all_feedback if not f.is_flagged_for_review]
    review_texts = [f.review_text for f in clean_feedback if f.review_text]
    professor_tags = ai.get_professor_tags(review_texts)
    wordcloud_data = ai.get_word_cloud_data(review_texts)
    ratings = [round((f.quality_rating + f.assignment_rating + f.grading_rating)/3) for f in clean_feedback]
    rating_counts = [ratings.count(i) for i in range(1, 6)]
    sentiments = [f.sentiment_category for f in clean_feedback]
    sentiment_counts = [sentiments.count('Positive'), sentiments.count('Neutral'), sentiments.count('Negative')]
    time_feedback = [f for f in clean_feedback if f.submitted_at]
    trend_dates = [f.submitted_at.strftime('%b %d %H:%M') for f in time_feedback]
    trend_scores = [f.sentiment_score for f in time_feedback]
    chart_data = {'rating_counts': rating_counts, 'sentiment_counts': sentiment_counts, 'trend_dates': trend_dates, 'trend_scores': trend_scores}
    trending_course, trending_rating = get_trending_course()
    return render_template('lecturer/course_details.html', title=f"Feedback for {course.name}", course=course, all_feedback=all_feedback, chart_data=chart_data, professor_tags=professor_tags, wordcloud_data=wordcloud_data, trending_course=trending_course, trending_rating=trending_rating)

@bp.route('/course/<int:course_id>/add_assignment', methods=['GET', 'POST'])
@login_required
@lecturer_required
def add_assignment(course_id):
    course = Course.query.get_or_404(course_id)
    if course.lecturer_user_id != current_user.id:
        flash('Unauthorized.', 'danger')
        return redirect(url_for('lecturer.dashboard'))
    if request.method == 'POST':
        title, description, due_date_str, max_marks = request.form.get('title'), request.form.get('description'), request.form.get('due_date'), request.form.get('max_marks', 100)
        try:
            due_date = datetime.strptime(due_date_str, '%Y-%m-%d')
            assignment = Assignment(course_id=course.id, title=title, description=description, due_date=due_date, max_marks=int(max_marks))
            db.session.add(assignment); db.session.commit()
            flash(f'Assignment "{title}" created!', 'success')
            return redirect(url_for('lecturer.course_details', course_id=course.id))
        except ValueError:
            flash('Invalid date format.', 'danger')
            return redirect(url_for('lecturer.add_assignment', course_id=course.id))
    return render_template('lecturer/add_assignment.html', course=course)

@bp.route('/assignment/<int:assignment_id>/delete', methods=['POST'])
@login_required
@lecturer_required
def delete_assignment(assignment_id):
    assignment = Assignment.query.get_or_404(assignment_id)
    course_id = assignment.course_id
    if assignment.course.lecturer_user_id != current_user.id:
        flash('Unauthorized.', 'danger')
        return redirect(url_for('main.index'))
    db.session.delete(assignment); db.session.commit()
    flash('Assignment deleted.', 'success')
    return redirect(url_for('lecturer.course_details', course_id=course_id))

@bp.route('/course/<int:course_id>/summarize', methods=['POST'])
@login_required
@lecturer_required
def summarize_course(course_id):
    course = Course.query.get_or_404(course_id)
    if course.lecturer_user_id != current_user.id:
        flash('Unauthorized.', 'danger')
        return redirect(url_for('lecturer.dashboard'))
    feedbacks = Feedback.query.filter_by(course_id=course.id).all()
    review_texts = [f.review_text for f in feedbacks if f.review_text]
    if len(review_texts) < 3: flash("Need at least 3 reviews.", "warning")
    else:
        summary = ai.generate_summary(review_texts)
        flash(f"AI SUMMARY: {summary}", "info")
    return redirect(url_for('lecturer.course_details', course_id=course.id))

@bp.route('/download_report/<int:course_id>')
@login_required
@lecturer_required
def download_report(course_id):
    course = Course.query.get_or_404(course_id)
    if course.lecturer_user_id != current_user.id:
        flash('Unauthorized.', 'danger')
        return redirect(url_for('lecturer.dashboard'))
    feedbacks = Feedback.query.filter_by(course_id=course.id).all()
    si = io.StringIO()
    cw = csv.writer(si)
    cw.writerow(['Feedback ID', 'Quality', 'Review', 'Sentiment', 'Submitted At'])
    for f in feedbacks: cw.writerow([f.id, f.quality_rating, f.review_text, f.sentiment_category, f.submitted_at])
    output = make_response(si.getvalue())
    output.headers["Content-Disposition"] = f"attachment; filename=report_{course.code}.csv"
    output.headers["Content-type"] = "text/csv"
    return output

@bp.route('/settings')
@login_required 
@lecturer_required
def settings():
    trending_course, trending_rating = get_trending_course()
    return render_template('lecturer/settings.html', title="Account Settings", trending_course=trending_course, trending_rating=trending_rating)

@bp.route('/change-password', methods=['POST']) 
@login_required 
@lecturer_required
def change_password():
    current_pw, new_pw, confirm_pw = request.form.get('current_password'), request.form.get('new_password'), request.form.get('confirm_password')
    if not check_password_hash(current_user.password_hash, current_pw): flash('Incorrect current password.', 'danger'); return redirect(url_for('lecturer.settings'))
    if new_pw != confirm_pw: flash('New passwords do not match.', 'danger'); return redirect(url_for('lecturer.settings'))
    current_user.password_hash = generate_password_hash(new_pw); db.session.commit()
    flash('Password updated!', 'success'); return redirect(url_for('lecturer.settings'))

@bp.route('/update-preferences', methods=['POST']) 
@login_required 
@lecturer_required
def update_preferences():
    current_user.pref_email_alerts, current_user.pref_weekly_summary = bool(request.form.get('email_alerts')), bool(request.form.get('weekly_summary'))
    try: current_user.pref_rating_threshold = float(request.form.get('rating_threshold', 3.0))
    except ValueError: current_user.pref_rating_threshold = 3.0
    db.session.commit(); flash('Preferences saved.', 'success'); return redirect(url_for('lecturer.settings'))

@bp.route('/update-profile', methods=['POST']) 
@login_required 
@lecturer_required
def update_profile():
    new_name, new_dept = request.form.get('display_name'), request.form.get('department')
    if new_name: current_user.username = new_name
    if new_dept: current_user.department = new_dept
    db.session.commit(); flash('Profile updated.', 'success'); return redirect(url_for('lecturer.settings'))

@bp.route('/course/<int:course_id>/marks', methods=['GET', 'POST']) 
@login_required 
@lecturer_required
def manage_marks(course_id):
    course = Course.query.get_or_404(course_id)
    if course.lecturer_user_id != current_user.id: flash('Unauthorized.', 'danger'); return redirect(url_for('lecturer.dashboard'))
    students = User.query.filter_by(role='student', student_year=course.target_year, branch=course.target_branch).order_by(User.username.asc()).all()
    if request.method == 'POST':
        assessment_name, max_score, count = request.form.get('assessment_name'), request.form.get('max_score', 20), 0
        for student in students:
            score_val = request.form.get(f'score_{student.id}')
            if score_val and score_val.strip() != '':
                try:
                    score_float = float(score_val)
                    existing_mark = InternalMark.query.filter_by(course_id=course.id, student_id=student.id, assessment_name=assessment_name).first()
                    if existing_mark: existing_mark.score, existing_mark.max_score = score_float, float(max_score)
                    else: db.session.add(InternalMark(course_id=course.id, student_id=student.id, assessment_name=assessment_name, score=score_float, max_score=float(max_score)))
                    count += 1
                except ValueError: continue
        db.session.commit(); flash(f'Updated marks for {count} students.', 'success')
        return redirect(url_for('lecturer.course_details', course_id=course.id))
    return render_template('lecturer/manage_marks.html', course=course, students=students)

@bp.route('/course/<int:course_id>/upload_resource', methods=['GET','POST'])
@login_required
def upload_resource(course_id):
    course = Course.query.get_or_404(course_id)

    if request.method == "POST":
        title = request.form.get("title")
        file = request.files.get("file")

        if not file:
            flash("No file selected.", "danger")
            return redirect(request.url)

        filename = secure_filename(file.filename)

        upload_folder = os.path.join("app", "static", "uploads")

        if not os.path.exists(upload_folder):
            os.makedirs(upload_folder)

        file_path = os.path.join(upload_folder, filename)

        file.save(file_path)

        resource = Resource(
            course_id=course.id,
            title=title,
            file_path=filename
        )

        db.session.add(resource)
        db.session.commit()

        flash("Resource uploaded successfully!", "success")

        return redirect(url_for("lecturer.course_details", course_id=course.id))

    return render_template("lecturer/upload_resource.html", course=course)