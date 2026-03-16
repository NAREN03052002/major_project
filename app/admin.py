# app/admin.py
from flask import Blueprint, render_template, redirect, url_for, flash, request
from app import db
from app.models import User, Course, AllowedStudent
from flask_login import login_required, current_user
from werkzeug.security import generate_password_hash
from functools import wraps
import csv
import io

bp = Blueprint('admin', __name__, url_prefix='/admin')

def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated or not current_user.is_admin:
            flash('Admin access required.', 'danger')
            return redirect(url_for('main.index'))
        return f(*args, **kwargs)
    return decorated_function

@bp.route('/dashboard')
@login_required
@admin_required
def dashboard():
    lecturers = User.query.filter_by(role='lecturer').all()
    courses = Course.query.all()
    
    # --- Whitelist Filtering Logic ---
    branch_filter = request.args.get('branch') # Get filter from URL (e.g., ?branch=MCA)
    
    query = AllowedStudent.query
    if branch_filter and branch_filter != 'All':
        query = query.filter_by(branch=branch_filter)
    
    # Sort results: First by Branch, then Year, then Email
    whitelist_data = query.order_by(AllowedStudent.branch, AllowedStudent.student_year, AllowedStudent.email).all()
    
    # Get total count (for the badge)
    whitelist_count = AllowedStudent.query.count()
    
    # Get list of unique branches for the dropdown menu
    unique_branches = db.session.query(AllowedStudent.branch).distinct().all()
    branches = [b[0] for b in unique_branches]
    
    return render_template('admin/dashboard.html', 
                           lecturers=lecturers, 
                           courses=courses,
                           whitelist_count=whitelist_count,
                           whitelist_data=whitelist_data, 
                           branches=branches,             
                           current_filter=branch_filter)

@bp.route('/upload_courses', methods=['POST'])
@login_required
@admin_required
def upload_courses():
    if 'file' not in request.files:
        flash('No file part', 'danger')
        return redirect(url_for('admin.dashboard'))
        
    file = request.files['file']
    if file.filename == '':
        flash('No selected file', 'danger')
        return redirect(url_for('admin.dashboard'))
        
    if file:
        stream = io.StringIO(file.stream.read().decode("UTF8"), newline=None)
        csv_input = csv.reader(stream)
        
        try:
            count = 0
            skipped = 0
            
            for row in csv_input:
                # Expected Format: code, name, lecturer_email, branch, year, department(optional)
                if len(row) < 5: continue
                
                # Header check
                if row[0].lower() == 'code': continue
                
                code = row[0].strip()
                name = row[1].strip()
                lec_email = row[2].strip()
                branch = row[3].strip()
                try:
                    year = int(row[4].strip())
                except ValueError:
                    skipped += 1
                    continue
                
                dept = row[5].strip() if len(row) > 5 else "General"

                # 1. Find the Lecturer
                lecturer = User.query.filter_by(email=lec_email, role='lecturer').first()
                if not lecturer:
                    # If lecturer doesn't exist, we can't assign the course
                    skipped += 1
                    continue

                # 2. Check if Course Exists
                existing = Course.query.filter_by(code=code).first()
                if not existing:
                    new_course = Course(
                        code=code,
                        name=name,
                        lecturer_user_id=lecturer.id,
                        target_branch=branch,
                        target_year=year,
                        department=dept,
                        is_active=False # Default to inactive so lecturer confirms it
                    )
                    db.session.add(new_course)
                    count += 1
                else:
                    skipped += 1
            
            db.session.commit()
            if count > 0:
                flash(f'Successfully added {count} courses.', 'success')
            if skipped > 0:
                flash(f'Skipped {skipped} rows (duplicates or lecturer email not found).', 'warning')
                
        except Exception as e:
            db.session.rollback()
            flash(f'Error processing CSV: {str(e)}', 'danger')
            
    return redirect(url_for('admin.dashboard'))

@bp.route('/upload_students', methods=['POST'])
@login_required
@admin_required
def upload_students():
    if 'file' not in request.files:
        flash('No file part', 'danger')
        return redirect(url_for('admin.dashboard'))
        
    file = request.files['file']
    if file.filename == '':
        flash('No selected file', 'danger')
        return redirect(url_for('admin.dashboard'))
        
    if file:
        stream = io.StringIO(file.stream.read().decode("UTF8"), newline=None)
        csv_input = csv.reader(stream)
        
        try:
            added_count = 0
            updated_count = 0
            
            for row in csv_input:
                # Expected Format: email, branch, year
                if len(row) < 3: continue
                if row[0].lower() == 'email': continue
                
                email = row[0].strip()
                branch = row[1].strip()
                try:
                    year = int(row[2].strip())
                except ValueError:
                    continue
                
                # 1. Check if student is already in Whitelist
                whitelist_entry = AllowedStudent.query.filter_by(email=email).first()
                
                if whitelist_entry:
                    # --- UPDATE LOGIC (Promotion) ---
                    # Only update if details changed
                    if whitelist_entry.student_year != year or whitelist_entry.branch != branch:
                        whitelist_entry.student_year = year
                        whitelist_entry.branch = branch
                        updated_count += 1
                        
                        # CRITICAL: Also update the active User account if they have registered!
                        active_user = User.query.filter_by(email=email).first()
                        if active_user:
                            active_user.student_year = year
                            active_user.branch = branch
                else:
                    # --- CREATE LOGIC (New Admission) ---
                    new_student = AllowedStudent(email=email, branch=branch, student_year=year)
                    db.session.add(new_student)
                    added_count += 1
            
            db.session.commit()
            
            msg = []
            if added_count > 0: msg.append(f"Added {added_count} new students.")
            if updated_count > 0: msg.append(f"Promoted/Updated {updated_count} students.")
            
            if msg:
                flash(" ".join(msg), 'success')
            else:
                flash("No changes detected. Database is up to date.", 'info')
                
        except Exception as e:
            db.session.rollback()
            flash(f'Error processing CSV: {str(e)}', 'danger')
            
    return redirect(url_for('admin.dashboard'))

@bp.route('/create_lecturer', methods=['GET', 'POST'])
@login_required
@admin_required
def create_lecturer():
    if request.method == 'POST':
        username = request.form.get('username')
        email = request.form.get('email')
        password = request.form.get('password')
        department = request.form.get('department')
        
        # Check existing
        user = User.query.filter_by(email=email).first()
        if user:
            flash('Email already exists.', 'danger')
            return redirect(url_for('admin.create_lecturer'))
        
        # Create Lecturer (Hardcoded Role)
        new_user = User(
            username=username, 
            email=email, 
            role='lecturer', 
            department=department,
            password_hash=generate_password_hash(password)
        )
        db.session.add(new_user)
        db.session.commit()
        
        # Optional: Assign Initial Subject
        subject_name = request.form.get('subject_name')
        subject_code = request.form.get('subject_code')
        
        if subject_name and subject_code:
            existing_course = Course.query.filter_by(code=subject_code).first()
            if existing_course:
                flash(f'Lecturer created, but Course "{subject_code}" already exists.', 'warning')
            else:
                # Note: Created as inactive, no target branch set here (can edit later)
                new_course = Course(
                    name=subject_name, 
                    code=subject_code, 
                    lecturer_user_id=new_user.id, 
                    is_active=False
                )
                db.session.add(new_course)
                db.session.commit()
                flash(f'Lecturer and subject {subject_code} assigned successfully!', 'success')
                return redirect(url_for('admin.dashboard'))

        flash('Lecturer account created successfully.', 'success')
        return redirect(url_for('admin.dashboard'))
        
    return render_template('admin/create_user.html')

@bp.route('/manage_courses/<int:lecturer_id>', methods=['GET', 'POST'])
@login_required
@admin_required
def manage_courses(lecturer_id):
    lecturer = User.query.get_or_404(lecturer_id)
    
    if lecturer.role != 'lecturer':
        flash('User is not a lecturer.', 'warning')
        return redirect(url_for('admin.dashboard'))

    if request.method == 'POST':
        action = request.form.get('action')
        
        if action == 'add':
            code = request.form.get('code')
            name = request.form.get('name')
            target_branch = request.form.get('target_branch')
            target_year = request.form.get('target_year')
            
            if Course.query.filter_by(code=code).first():
                flash(f'Course code {code} already exists.', 'danger')
            else:
                new_course = Course(
                    name=name, 
                    code=code, 
                    lecturer_user_id=lecturer.id,
                    is_active=False,
                    target_branch=target_branch,
                    target_year=int(target_year)
                )
                db.session.add(new_course)
                db.session.commit()
                flash(f'Subject assigned for {target_branch} Year {target_year}. Lecturer must activate it.', 'success')
                
        elif action == 'delete':
            course_id = request.form.get('course_id')
            course = Course.query.get(course_id)
            if course and course.lecturer_user_id == lecturer.id:
                db.session.delete(course)
                db.session.commit()
                flash('Subject removed.', 'success')

        return redirect(url_for('admin.manage_courses', lecturer_id=lecturer.id))

    return render_template('admin/manage_courses.html', lecturer=lecturer)

@bp.route('/delete_student/<int:student_id>', methods=['POST'])
@login_required
@admin_required
def delete_student(student_id):
    student = AllowedStudent.query.get_or_404(student_id)
    email_to_remove = student.email
    
    db.session.delete(student)
    db.session.commit()
    
    flash(f'Removed {email_to_remove} from the whitelist.', 'success')
    return redirect(url_for('admin.dashboard'))

# --- NEW: Delete Lecturer Route ---
@bp.route('/delete_lecturer/<int:user_id>', methods=['POST'])
@login_required
@admin_required
def delete_lecturer(user_id):
    lecturer = User.query.get_or_404(user_id)
    
    if lecturer.role != 'lecturer':
        flash('Cannot delete this user. They are not a lecturer.', 'danger')
        return redirect(url_for('admin.dashboard'))
    
    # 1. Delete all courses assigned to this lecturer first
    courses = Course.query.filter_by(lecturer_user_id=lecturer.id).all()
    for course in courses:
        db.session.delete(course)
        
    # 2. Delete the Lecturer
    username = lecturer.username
    db.session.delete(lecturer)
    db.session.commit()
    
    flash(f'Lecturer {username} and their assigned courses have been deleted.', 'success')
    return redirect(url_for('admin.dashboard'))