"""
认证路由 - 登录/登出
"""

from functools import wraps
from flask import Blueprint, render_template, request, session, redirect, url_for
from core.settings_manager import load_settings

auth_bp = Blueprint('auth', __name__)

# 加载管理员密钥
_settings = load_settings()
ADMIN_KEY = _settings.get("admin_key", "admin123")


def login_required(f):
    """登录验证装饰器"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get('logged_in'):
            return redirect(url_for('auth.login'))
        return f(*args, **kwargs)
    return decorated_function


@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    """登录页面"""
    if request.method == 'POST':
        key = request.form.get('key', '')
        # 每次重新加载以支持动态修改
        settings = load_settings()
        admin_key = settings.get("admin_key", ADMIN_KEY)
        if key == admin_key:
            session['logged_in'] = True
            return redirect(url_for('pages.index'))
        else:
            return render_template('login.html', error='密钥错误')
    return render_template('login.html')


@auth_bp.route('/logout')
def logout():
    """登出"""
    session.pop('logged_in', None)
    return redirect(url_for('auth.login'))
