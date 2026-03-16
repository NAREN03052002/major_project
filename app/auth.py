# app/auth.py
from flask import Blueprint, render_template, redirect, url_for, flash
from app import db
from app.models import User, AllowedStudent
from flask_login import login_user, logout_user, current_user
from wtforms import StringField, PasswordField, SubmitField
from wtforms.validators import DataRequired, EqualTo, ValidationError, Email
from flask_wtf import FlaskForm
from .utils import get_trending_course

bp = Blueprint('auth', __name__)

class LoginForm(FlaskForm):
    username = StringField('Username', validators=[DataRequired()])
    password = PasswordField('Password', validators=[DataRequired()])
    submit = SubmitField('Sign In')

class RegistrationForm(FlaskForm):
    username = StringField('Username', validators=[DataRequired()])
    email = StringField('Email Address', validators=[DataRequired(), Email()])
    password = PasswordField('Password', validators=[DataRequired()])
    password2 = PasswordField('Repeat Password', validators=[DataRequired(), EqualTo('password')])
    # REMOVED: Branch and Year fields (System will auto-detect)
    submit = SubmitField('Register')

    def validate_username(self, username):
        user = User.query.filter_by(username=username.data).first()
        if user is not None:
            raise ValidationError('Please use a different username.')

    def validate_email(self, email):
        # 1. Check if user already exists
        user = User.query.filter_by(email=email.data).first()
        if user is not None:
            raise ValidationError('This email is already registered.')
            
        # 2. Check Whitelist
        valid_student = AllowedStudent.query.filter_by(email=email.data).first()
        if not valid_student:
            raise ValidationError('Access Denied: This email is not in the official student records. Contact Admin.')

@bp.route('/register', methods=['GET', 'POST'])
def register():
    if current_user.is_authenticated:
        return redirect(url_for('main.index'))
        
    form = RegistrationForm()
    if form.validate_on_submit():
        # 1. Fetch the pre-approved details
        valid_record = AllowedStudent.query.filter_by(email=form.email.data).first()
        
        # 2. Create User with AUTO-FILLED Branch & Year
        user = User(
            username=form.username.data, 
            email=form.email.data,
            role='student',
            branch=valid_record.branch,        # <--- Auto-filled
            student_year=valid_record.student_year # <--- Auto-filled
        )
        user.set_password(form.password.data)
        db.session.add(user)
        db.session.commit()
        
        flash(f'Account created! Detected: {valid_record.branch} - Year {valid_record.student_year}', 'success')
        return redirect(url_for('auth.login'))
        
    trending_course, trending_rating = get_trending_course()
    return render_template('register.html', title='Sign Up', form=form, trending_course=trending_course, trending_rating=trending_rating)

@bp.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        if current_user.is_admin: return redirect(url_for('admin.dashboard'))
        elif current_user.is_lecturer: return redirect(url_for('lecturer.dashboard'))
        else: return redirect(url_for('main.index'))
    
    form = LoginForm()
    if form.validate_on_submit():
        user = User.query.filter_by(username=form.username.data).first()
        if user is None or not user.check_password(form.password.data):
            flash('Invalid username or password', 'danger')
            return redirect(url_for('auth.login'))
        
        login_user(user)
        flash('Logged in successfully!', 'success')
        
        if user.is_admin: return redirect(url_for('admin.dashboard'))
        elif user.is_lecturer: return redirect(url_for('lecturer.dashboard'))
        else: return redirect(url_for('main.index'))
            
    trending_course, trending_rating = get_trending_course()
    return render_template('login.html', title='Sign In', form=form, trending_course=trending_course, trending_rating=trending_rating)

@bp.route('/logout')
def logout():
    logout_user()
    flash('You have been logged out.', 'success')
    return redirect(url_for('main.index'))