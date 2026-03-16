from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from flask_login import LoginManager
from config import Config
import os
from sqlalchemy import MetaData


# Define naming convention for constraints to fix SQLite migration issues
naming_convention = {
    "ix": 'ix_%(column_0_label)s',
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s"
}

# Initialize extensions
db = SQLAlchemy(metadata=MetaData(naming_convention=naming_convention))
migrate = Migrate()
login = LoginManager()
login.login_view = 'auth.login'
login.login_message = 'Please log in to access this page.'
login.login_message_category = 'danger'

def create_app(config_class=Config):
    app = Flask(__name__)
    app.config.from_object(config_class)

    # Initialize extensions with the app
    db.init_app(app)
    migrate.init_app(app, db)
    login.init_app(app)

    # Load AI models (stub function from app/ai.py)
    from . import ai
    ai.init_ai()
    print("AI models loading...")

    # --- Register Blueprints ---
    
    # Authentication routes (login, register, logout)
    from app.auth import bp as auth_bp
    app.register_blueprint(auth_bp, url_prefix='/auth')
    
    # Main routes (student dashboard, submit feedback)
    from app.main import bp as main_bp
    app.register_blueprint(main_bp, url_prefix='/')

    # Admin routes (manage lecturers, delete toxic reviews)
    from app.admin import bp as admin_bp
    app.register_blueprint(admin_bp, url_prefix='/admin')
    
    # Lecturer routes (view courses, analytics, moderation queues)
    from app.lecturer import bp as lecturer_bp
    app.register_blueprint(lecturer_bp, url_prefix='/lecturer')

    # Public API Blueprint (Phase 4)
    from app.api import bp as api_bp
    app.register_blueprint(api_bp)


    from app.routes.department import bp as department_bp
    app.register_blueprint(department_bp)

    # --- NEW: Q&A FORUM BLUEPRINT ---
    from app.routes import forum
    app.register_blueprint(forum.bp)
    # --------------------------------

    @app.route('/test')
    def test():
        return "App is running!"
    
    # app/__init__.py inside create_app()

    # ... (existing blueprint registrations) ...

    # --- ADD THIS CONTEXT PROCESSOR ---
    @app.context_processor
    # --- CONTEXT PROCESSOR (Fixed with Imports) ---
    @app.context_processor
    def inject_notifications():
        # 1. Add these imports right here to fix the NameError
        from flask_login import current_user
        from app.models import Notification 
        
        # 2. The logic remains the same
        if current_user.is_authenticated:
            unread_count = Notification.query.filter_by(
                recipient_id=current_user.id, 
                is_read=False
            ).count()
            return dict(unread_count=unread_count)
        
        return dict(unread_count=0)
    # ----------------------------------------------
    # ----------------------------------

    return app

    