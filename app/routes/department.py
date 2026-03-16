from flask import Blueprint, render_template, redirect, url_for, flash, request, abort
from flask_login import login_required, current_user
from app import db
from app.models import Notice, Department

bp = Blueprint('department', __name__, url_prefix='/department')

# --- 1. VIEW NOTICES (For Students & Lecturers) ---
@bp.route('/notices')
@login_required
def view_notices():
    # Security: User must have a department assigned
    if not current_user.department_id:
        flash("You are not assigned to any department yet. Please contact Admin.", "warning")
        return redirect(url_for('main.index'))

    # Fetch notices ONLY for this user's department
    notices = Notice.query.filter_by(department_id=current_user.department_id)\
        .order_by(Notice.created_at.desc()).all()
    
    department = Department.query.get(current_user.department_id)
    
    return render_template('department/notices.html', notices=notices, department=department)

# --- 2. POST NOTICE (Lecturers Only) ---
@bp.route('/notices/new', methods=['GET', 'POST'])
@login_required
def add_notice():
    # Authorization: Only Lecturers/HOD can post
    if not current_user.is_lecturer:
        abort(403) # Forbidden
        
    if not current_user.department_id:
        flash("You are not linked to a department.", "danger")
        return redirect(url_for('main.index'))

    if request.method == 'POST':
        title = request.form.get('title')
        content = request.form.get('content')
        
        notice = Notice(
            department_id=current_user.department_id,
            author_id=current_user.id,
            title=title,
            content=content
        )
        db.session.add(notice)
        db.session.commit()
        
        flash('Notice posted to Department Board!', 'success')
        return redirect(url_for('department.view_notices'))
        
    return render_template('department/add_notice.html')

# --- 3. DELETE NOTICE (Author Only) ---
@bp.route('/notices/<int:notice_id>/delete', methods=['POST'])
@login_required
def delete_notice(notice_id):
    notice = Notice.query.get_or_404(notice_id)
    
    if notice.author_id != current_user.id:
        abort(403)
        
    db.session.delete(notice)
    db.session.commit()
    flash('Notice deleted.', 'info')
    return redirect(url_for('department.view_notices'))