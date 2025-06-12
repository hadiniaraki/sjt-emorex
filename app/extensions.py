from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager
from flask_babel import Babel

db = SQLAlchemy()
login = LoginManager()
login.login_view = 'auth.login'
login.login_message = 'برای دسترسی به این صفحه، باید وارد شوید.'
babel = Babel()