from flask import Blueprint, render_template, redirect, url_for, flash, request
from flask_login import login_user, logout_user, current_user, login_required # Ensure login_required is imported
from app.extensions import db, login
from app.models import User
from app.forms import LoginForm, RegistrationForm

bp = Blueprint('auth', __name__)

@bp.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('main.dashboard'))
    form = LoginForm()
    if form.validate_on_submit():
        user = User.query.filter_by(username=form.username.data).first()
        if user is None or not user.check_password(form.password.data):
            flash('نام کاربری یا رمز عبور نامعتبر است.', 'danger')
            return redirect(url_for('auth.login'))
        login_user(user, remember=form.remember_me.data)
        next_page = request.args.get('next')
        if not next_page or not next_page.startswith('/'): # Basic security check for next_page
            next_page = url_for('main.dashboard')
        return redirect(next_page)
    return render_template('auth/login.html', title='ورود', form=form)

@bp.route('/logout')
@login_required # This is where login_required is typically used in auth blueprint
def logout():
    logout_user()
    flash('شما با موفقیت از سیستم خارج شدید.', 'info')
    return redirect(url_for('auth.login'))

@bp.route('/register', methods=['GET', 'POST'])
def register():
    if current_user.is_authenticated:
        return redirect(url_for('main.dashboard'))
    form = RegistrationForm()
    if form.validate_on_submit():
        user = User(username=form.username.data)
        user.set_password(form.password.data)
        db.session.add(user)
        db.session.commit()
        flash('اکانت شما با موفقیت ایجاد شد!', 'success')
        return redirect(url_for('auth.login'))
    return render_template('auth/register.html', title='ثبت نام', form=form)