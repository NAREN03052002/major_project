from flask import Blueprint, render_template, redirect, url_for, flash, request, abort
from flask_login import login_required, current_user
from app import db
from app.models import Course, ForumQuestion, ForumReply, ForumUpvote, Notification


bp = Blueprint('forum', __name__, url_prefix='/forum')

@bp.after_request
def add_header(response):
    """
    Tell the browser not to cache any page in the Forum.
    This prevents the 'Back Button' from showing deleted questions.
    """
    response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    response.headers["Pragma"] = "no-cache"
    response.headers["Expires"] = "0"
    return response

@bp.route('/course/<int:course_id>')
@login_required
def index(course_id):
    course = Course.query.get_or_404(course_id)
    questions = ForumQuestion.query.filter_by(course_id=course.id).order_by(ForumQuestion.created_at.desc()).all()
    
    # Get list of question IDs the current user has already upvoted
    user_votes = ForumUpvote.query.filter_by(user_id=current_user.id).all()
    upvoted_ids = {v.question_id for v in user_votes}
    
    return render_template('forum/index.html', course=course, questions=questions, upvoted_ids=upvoted_ids)

@bp.route('/course/<int:course_id>/ask', methods=['GET', 'POST'])
@login_required
def ask_question(course_id):
    course = Course.query.get_or_404(course_id)
    
    if request.method == 'POST':
        title = request.form.get('title')
        body = request.form.get('body')
        is_anon = True if request.form.get('is_anonymous') else False
        
        # 1. Create Question with initial upvote count of 1
        question = ForumQuestion(
            course_id=course.id,
            user_id=current_user.id,
            title=title,
            body=body,
            is_anonymous=is_anon,
            upvotes=1
        )
        db.session.add(question)
        db.session.commit() # Commit to generate question.id
        
        # 2. Automatically register the self-upvote in tracking table
        self_upvote = ForumUpvote(user_id=current_user.id, question_id=question.id)
        db.session.add(self_upvote)
        db.session.commit()

        flash('Question posted successfully!', 'success')
        return redirect(url_for('forum.index', course_id=course.id))
        
    return render_template('forum/ask.html', course=course)

# @bp.route('/question/<int:question_id>', methods=['GET', 'POST'])
# @login_required
# def view_question(question_id):
#     question = ForumQuestion.query.get_or_404(question_id)
    
#     if request.method == 'POST':
#         body = request.form.get('body')
        
#         is_official = False
#         if hasattr(question.course, 'lecturer_user_id'):
#             if current_user.id == question.course.lecturer_user_id:
#                 is_official = True
        
#         reply = ForumReply(
#             question_id=question.id,
#             user_id=current_user.id,
#             body=body,
#             is_official=is_official
#         )
#         db.session.add(reply)
#         db.session.commit()
#         flash('Reply posted.', 'success')
#         return redirect(url_for('forum.view_question', question_id=question.id))

#     return render_template('forum/view_question.html', question=question)

@bp.route('/question/<int:question_id>', methods=['GET', 'POST'])
@login_required
def view_question(question_id):
    question = ForumQuestion.query.get_or_404(question_id)
    
    if request.method == 'POST':
        body = request.form.get('body')
        
        is_official = False
        if hasattr(question.course, 'lecturer_user_id'):
            if current_user.id == question.course.lecturer_user_id:
                is_official = True
        
        reply = ForumReply(
            question_id=question.id,
            user_id=current_user.id,
            body=body,
            is_official=is_official
        )
        db.session.add(reply)
        db.session.commit()
        
        # --- NEW: NOTIFICATION LOGIC ---
        # Notify the question author (if they didn't reply to themselves)
        if question.user_id != current_user.id:
            notif = Notification(
                recipient_id=question.user_id,
                actor_id=current_user.id,
                message=f"{current_user.username} replied to: {question.title[:30]}...",
                link=url_for('forum.view_question', question_id=question.id)
            )
            db.session.add(notif)
            db.session.commit()
        # -------------------------------

        flash('Reply posted.', 'success')
        return redirect(url_for('forum.view_question', question_id=question.id))

    return render_template('forum/view_question.html', question=question)



@bp.route('/question/<int:question_id>/upvote')
@login_required
def upvote(question_id):
    q = ForumQuestion.query.get_or_404(question_id)
    
    # Check if user already voted
    existing_vote = ForumUpvote.query.filter_by(user_id=current_user.id, question_id=q.id).first()
    
    if existing_vote:
        # User ALREADY voted -> Remove vote (Toggle Off)
        db.session.delete(existing_vote)
        q.upvotes = max(0, q.upvotes - 1)
    else:
        # User HAS NOT voted -> Add vote (Toggle On)
        new_vote = ForumUpvote(user_id=current_user.id, question_id=q.id)
        db.session.add(new_vote)
        q.upvotes += 1
        
    db.session.commit()
    return redirect(url_for('forum.index', course_id=q.course_id))

# --- DELETE ROUTES (With Integrity Fix) ---

# @bp.route('/question/<int:question_id>/delete', methods=['POST'])
# @login_required
# def delete_question(question_id):
#     question = ForumQuestion.query.get_or_404(question_id)
    
#     # Permission Check: User must be Author OR Lecturer
#     is_author = (question.user_id == current_user.id)
#     is_lecturer = (question.course.lecturer_user_id == current_user.id)

#     if not (is_author or is_lecturer):
#         abort(403) # Forbidden
    
#     course_id = question.course_id

#     # CRITICAL FIX: Delete related Upvotes FIRST to prevent Foreign Key Error
#     ForumUpvote.query.filter_by(question_id=question.id).delete()
    
#     # Now safe to delete the question (Replies usually cascade delete, or you can delete them here too)
#     db.session.delete(question)
#     db.session.commit()
    
#     flash('Question deleted successfully.', 'success')
#     return redirect(url_for('forum.index', course_id=course_id))

# @bp.route('/reply/<int:reply_id>/delete', methods=['POST'])
# @login_required
# def delete_reply(reply_id):
#     reply = ForumReply.query.get_or_404(reply_id)
#     question_id = reply.question_id
    
#     # Permission Check
#     is_author = (reply.user_id == current_user.id)
#     is_lecturer = (reply.question.course.lecturer_user_id == current_user.id)

#     if not (is_author or is_lecturer):
#         abort(403)

#     db.session.delete(reply)
#     db.session.commit()
#     flash('Reply deleted.', 'success')
#     return redirect(url_for('forum.view_question', question_id=question_id))
# app/routes/forum.py (Partial update for Delete Routes)

# ... (Previous imports and routes remain the same) ...

# --- STRICT DELETE ROUTES (Owner Only) ---

@bp.route('/question/<int:question_id>/delete', methods=['POST'])
@login_required
def delete_question(question_id):
    question = ForumQuestion.query.get_or_404(question_id)
    
    # STRICT CHECK: Only the author can delete
    if question.user_id != current_user.id:
        abort(403) # Forbidden
    
    course_id = question.course_id

    # 1. Delete related Upvotes first
    ForumUpvote.query.filter_by(question_id=question.id).delete()
    
    # 2. Delete the Question
    db.session.delete(question)
    db.session.commit()
    
    flash('Your question was deleted.', 'success')
    return redirect(url_for('forum.index', course_id=course_id))

@bp.route('/reply/<int:reply_id>/delete', methods=['POST'])
@login_required
def delete_reply(reply_id):
    reply = ForumReply.query.get_or_404(reply_id)
    question_id = reply.question_id
    
    # STRICT CHECK: Only the author can delete
    if reply.user_id != current_user.id:
        abort(403)

    db.session.delete(reply)
    db.session.commit()
    flash('Your reply was deleted.', 'success')
    return redirect(url_for('forum.view_question', question_id=question_id))