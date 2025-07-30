# app/__init__.py
from flask import Flask
from dotenv import load_dotenv
from datetime import datetime
import jdatetime 
import os

load_dotenv()

from .config import Config
from .extensions import db, login, babel

def to_jalali(gregorian_date):
    if gregorian_date is None:
        return ""
    try:
        jd_date = jdatetime.date.fromgregorian(date=gregorian_date)
        return jd_date.strftime('%Y/%m/%d')
    except Exception:
        return gregorian_date 

def format_currency(value):
    try:
        return f"{float(value):,.2f}"
    except (ValueError, TypeError):
        return "0.00"

def get_locale():
    return 'fa'

def create_app(config_class=Config):
    app = Flask(__name__, instance_relative_config=True)
    app.config.from_object(config_class)
    try:
        os.makedirs(app.instance_path)
    except OSError:
        pass

    db.init_app(app)
    login.init_app(app)
    babel.init_app(app, locale_selector=get_locale)

    # ثبت فیلترهای سفارشی در محیط Jinja2
    app.jinja_env.filters['to_jalali'] = to_jalali
    app.jinja_env.filters['format_currency'] = format_currency

    from app.auth import bp as auth_bp
    app.register_blueprint(auth_bp, url_prefix='/auth')

    from app.main import bp as main_bp
    app.register_blueprint(main_bp)

    @app.context_processor
    def inject_now():
        return {'now': datetime.utcnow()}

    return app