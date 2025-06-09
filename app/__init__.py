from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager
from config import Config
import os
from dotenv import load_dotenv 

load_dotenv()

db = SQLAlchemy()
login_manager = LoginManager()
login_manager.login_view = 'auth.login'

def create_app():
    app = Flask(__name__)
    app.config.from_object(Config)

    db.init_app(app)
    login_manager.init_app(app)

    from app.auth import bp as auth_bp
    app.register_blueprint(auth_bp, url_prefix='/auth')

    from app.main import bp as main_bp
    app.register_blueprint(main_bp)

    with app.app_context():
        # Check if any users exist, if not, create a default admin user for initial login
        from app.models import User, Settings # Import Settings model here
        if User.query.count() == 0:
            print("No users found. Creating a default admin user.")
            admin_user = User(username='admin')
            admin_user.set_password('1234') 
            db.session.add(admin_user)
            db.session.commit()
            print("Default admin user 'admin' with password 'adminpass' created.")

        # Initialize START_INVOICE_NUMBER in settings if it doesn't exist
        start_inv_setting = Settings.query.filter_by(setting_name='START_INVOICE_NUMBER').first()
        if not start_inv_setting:
            initial_invoice_num = app.config['DEFAULT_START_INVOICE_NUMBER']
            db.session.add(Settings(setting_name='START_INVOICE_NUMBER', setting_value=str(initial_invoice_num)))
            db.session.commit()
            print(f"Initial START_INVOICE_NUMBER set to {initial_invoice_num} in settings.")


        db.create_all() # Ensure tables are created (idempotent)

    return app