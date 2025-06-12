# sjt_app/app/__init__.py

from flask import Flask, request
from .config import Config
from .extensions import db, login, babel

def get_locale():
    return 'fa'

def create_app(config_class=Config):
    app = Flask(__name__)
    app.config.from_object(config_class)

    db.init_app(app)
    login.init_app(app)

    babel.init_app(app, locale_selector=get_locale)

    from app.auth import bp as auth_bp
    app.register_blueprint(auth_bp, url_prefix='/auth')

    from app.main import bp as main_bp
    app.register_blueprint(main_bp)

    return app