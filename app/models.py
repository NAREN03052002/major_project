# app/models.py
from app import db, login
from werkzeug.security import generate_password_hash, check_password_hash
from flask_login import UserMixin
from datetime import datetime 
import json 

@login.user_loader
def load_user(id):
    return User.query.get(int(id))

# --- NEW: DEPARTMENT MODEL (The Root Container) ---
class Department(db.Model):
    __tablename__ = 'departments'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), unique=True, nullable=False) # e.g., "Computer Science"
    
    # Relationships
    users = db.relationship('User', backref='department_link', lazy=True)
    courses = db.relationship('Course', backref='department_link', lazy=True)
    notices = db.relationship('Notice', backref='department', lazy=True)

# --- USER MODEL (Updated with Department Link) ---
class User(UserMixin, db.Model):
    __tablename__ = 'users'
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(50), unique=True, nullable=False)
    email = db.Column(db.String(100), unique=True, nullable=True)
    password_hash = db.Column(db.String(255), nullable=False)
    
    role = db.Column(db.String(20), nullable=False, default='student')
    xp = db.Column(db.Integer, default=0)
    
    # --- Student Isolation Fields ---
    student_year = db.Column(db.Integer, default=1)
    branch = db.Column(db.String(50), default='General')
    
    # --- NEW: Department Link ---
    department_id = db.Column(db.Integer, db.ForeignKey('departments.id'), nullable=True)

    # Relationships
    feedbacks_submitted = db.relationship('Feedback', 
                                          back_populates='student', 
                                          lazy=True,
                                          foreign_keys='Feedback.student_user_id')
    
    courses_taught = db.relationship('Course', 
                                     back_populates='lecturer', 
                                     lazy=True,
                                     foreign_keys='Course.lecturer_user_id')
    
    department_name = db.Column(db.String(100), default='General') 
    
    # Preferences
    pref_email_alerts = db.Column(db.Boolean, default=True)
    pref_weekly_summary = db.Column(db.Boolean, default=False)
    pref_rating_threshold = db.Column(db.Float, default=3.0)

    # Image (Profile Picture Placeholder)
    image_file = db.Column(db.String(20), nullable=False, default='default.jpg')

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    @property
    def is_admin(self):
        return self.role == 'admin'

    @property
    def is_lecturer(self):
        return self.role == 'lecturer'

    @property
    def is_student(self):
        return self.role == 'student'


# --- COURSE MODEL (Updated with Department Link) ---
class Course(db.Model):
    __tablename__ = 'courses'
    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(20), unique=True, nullable=False)
    name = db.Column(db.String(100), nullable=False)
    
    # --- NEW: Department Link ---
    department_id = db.Column(db.Integer, db.ForeignKey('departments.id'), nullable=True)
    
    # (Old string field kept for compatibility)
    department_name = db.Column(db.String(100), nullable=True)
    
    # --- Target Audience Fields ---
    target_year = db.Column(db.Integer, default=1)
    target_branch = db.Column(db.String(50), default='General')
    
    lecturer_user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    is_active = db.Column(db.Boolean, default=False) 
    
    lecturer = db.relationship('User', 
                               back_populates='courses_taught', 
                               foreign_keys=[lecturer_user_id])
    
    feedbacks = db.relationship('Feedback', 
                                 back_populates='course', 
                                 lazy=True, 
                                 cascade="all, delete-orphan",
                                 foreign_keys='Feedback.course_id')

# --- NEW: SMART ATTENDANCE MODELS ---

class AttendanceSession(db.Model):
    __tablename__ = 'attendance_sessions'
    id = db.Column(db.Integer, primary_key=True)
    course_id = db.Column(db.Integer, db.ForeignKey('courses.id'), nullable=False)
    # Stores the 6-digit numeric token for class verification
    session_token = db.Column(db.String(10), unique=True, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    expires_at = db.Column(db.DateTime, nullable=False) # 5-minute time-bound window
    lat = db.Column(db.Float, nullable=True) # Classroom GPS Geofencing
    lon = db.Column(db.Float, nullable=True)
    is_active = db.Column(db.Boolean, default=True)
    records = db.relationship('AttendanceRecord', backref='session', lazy=True)

    course = db.relationship('Course', backref=db.backref('attendance_sessions', lazy=True))

class AttendanceRecord(db.Model):
    __tablename__ = 'attendance_records'
    id = db.Column(db.Integer, primary_key=True)
    session_id = db.Column(db.Integer, db.ForeignKey('attendance_sessions.id'), nullable=False)
    student_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    # Anti-Proxy: Unique device hardware fingerprint
    device_fingerprint = db.Column(db.String(255), nullable=True)
    is_manual = db.Column(db.Boolean, default=False) # Lecturer manual override
    marked_by_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)

    student = db.relationship('User', foreign_keys=[student_id])

# --- FEEDBACK MODEL (Existing) ---
class Feedback(db.Model):
    __tablename__ = 'feedback'
    id = db.Column(db.Integer, primary_key=True)
    course_id = db.Column(db.Integer, db.ForeignKey('courses.id'), nullable=False)
    student_user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    
    student = db.relationship('User', 
                              back_populates='feedbacks_submitted', 
                              foreign_keys=[student_user_id])
    
    course = db.relationship('Course', 
                             back_populates='feedbacks', 
                             foreign_keys=[course_id])
    
    quality_rating = db.Column(db.Integer, nullable=False)
    assignment_rating = db.Column(db.Integer, nullable=False)
    grading_rating = db.Column(db.Integer, nullable=False)
    review_text = db.Column(db.Text, nullable=True)
    is_anonymous = db.Column(db.Boolean, default=False, nullable=False)
    submitted_at = db.Column(db.DateTime, default=datetime.utcnow)

    # AI Fields
    sentiment_category = db.Column(db.String(20), default='Neutral')
    sentiment_score = db.Column(db.Float, default=0.0)
    specific_emotion = db.Column(db.String(20)) 
    is_flagged_for_review = db.Column(db.Boolean, default=False)
    predicted_quality = db.Column(db.Float)
    predicted_assignment = db.Column(db.Float)
    predicted_grading = db.Column(db.Float)
    embedding_json = db.Column(db.Text, nullable=True)
    
    def set_embedding(self, vector):
        if hasattr(vector, 'tolist'):
            vector = vector.tolist()
        self.embedding_json = json.dumps(vector)

    def get_embedding(self):
        if self.embedding_json:
            return json.loads(self.embedding_json)
        return None

# --- COURSE TOPICS MODEL (Existing) ---
class CourseTopic(db.Model):
    __tablename__ = 'course_topics'
    id = db.Column(db.Integer, primary_key=True)
    course_id = db.Column(db.Integer, db.ForeignKey('courses.id'), nullable=False)
    topic_keywords = db.Column(db.String(255))
    topic_percentage = db.Column(db.Float)

# --- WHITELIST TABLE (Existing) ---
class AllowedStudent(db.Model):
    __tablename__ = 'allowed_students'
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(100), unique=True, nullable=False)
    branch = db.Column(db.String(50), nullable=False) 
    student_year = db.Column(db.Integer, nullable=False)

# --- Q&A FORUM MODELS (Existing) ---
class ForumQuestion(db.Model):
    __tablename__ = 'forum_questions'
    id = db.Column(db.Integer, primary_key=True)
    course_id = db.Column(db.Integer, db.ForeignKey('courses.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    title = db.Column(db.String(200), nullable=False)
    body = db.Column(db.Text, nullable=False)
    is_anonymous = db.Column(db.Boolean, default=False)
    upvotes = db.Column(db.Integer, default=0)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    replies = db.relationship('ForumReply', backref='question', lazy='dynamic', cascade="all, delete-orphan")
    author = db.relationship('User', backref='questions')
    course = db.relationship('Course', backref='questions')

class ForumReply(db.Model):
    __tablename__ = 'forum_replies'
    id = db.Column(db.Integer, primary_key=True)
    question_id = db.Column(db.Integer, db.ForeignKey('forum_questions.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    body = db.Column(db.Text, nullable=False)
    is_official = db.Column(db.Boolean, default=False)
    is_accepted = db.Column(db.Boolean, default=False) # Marked as Solution
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    author = db.relationship('User', backref='replies')

class ForumUpvote(db.Model):
    __tablename__ = 'forum_upvotes'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    question_id = db.Column(db.Integer, db.ForeignKey('forum_questions.id'), nullable=False)

# --- NOTIFICATION MODEL (Existing) ---
class Notification(db.Model):
    __tablename__ = 'notifications'
    id = db.Column(db.Integer, primary_key=True)
    recipient_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    actor_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False) 
    message = db.Column(db.String(255), nullable=False)
    link = db.Column(db.String(255), nullable=False)
    is_read = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    recipient = db.relationship('User', foreign_keys=[recipient_id], backref='notifications')
    actor = db.relationship('User', foreign_keys=[actor_id])

# --- NEW: LMS FEATURES MODELS ---

class Assignment(db.Model):
    __tablename__ = 'assignments'
    id = db.Column(db.Integer, primary_key=True)
    course_id = db.Column(db.Integer, db.ForeignKey('courses.id'), nullable=False)
    title = db.Column(db.String(100), nullable=False)
    description = db.Column(db.Text, nullable=False)
    due_date = db.Column(db.DateTime, nullable=False)
    max_marks = db.Column(db.Integer, default=100)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    course = db.relationship('Course', backref=db.backref('assignments', lazy=True))

class Notice(db.Model):
    __tablename__ = 'notices'
    id = db.Column(db.Integer, primary_key=True)
    department_id = db.Column(db.Integer, db.ForeignKey('departments.id'), nullable=False)
    author_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False) # HOD who posted it
    title = db.Column(db.String(100), nullable=False)
    content = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class InternalMark(db.Model):
    __tablename__ = 'internal_marks'
    id = db.Column(db.Integer, primary_key=True)
    course_id = db.Column(db.Integer, db.ForeignKey('courses.id'), nullable=False)
    student_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    assessment_name = db.Column(db.String(100), nullable=False) # e.g., "Internal 1", "Quiz 2"
    score = db.Column(db.Float, nullable=False)
    max_score = db.Column(db.Float, default=20.0)
    
    student = db.relationship('User', foreign_keys=[student_id])
    course = db.relationship('Course', foreign_keys=[course_id])




class Resource(db.Model):
    __tablename__ = 'resources'
    id = db.Column(db.Integer, primary_key=True)
    course_id = db.Column(db.Integer, db.ForeignKey('courses.id'), nullable=False)
    title = db.Column(db.String(100), nullable=False)
    file_path = db.Column(db.String(255), nullable=False) # Stores the filename
    file_type = db.Column(db.String(10), nullable=True)  # e.g., 'pdf', 'ppt'
    uploaded_at = db.Column(db.DateTime, default=datetime.utcnow)

    course = db.relationship('Course', backref=db.backref('resources', lazy=True))

