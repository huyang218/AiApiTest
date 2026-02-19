"""
AI API 测试平台 - Web 应用入口
"""

import json
import secrets
from flask import Flask

from core.database import init_db, close_db
from routes.auth import auth_bp
from routes.pages import pages_bp
from routes.test_text import test_text_bp
from routes.records import records_bp


def create_app():
    """创建并配置 Flask 应用"""
    app = Flask(__name__)
    app.secret_key = secrets.token_hex(32)

    # 自定义 Jinja2 过滤器
    @app.template_filter('from_json')
    def from_json_filter(value):
        """JSON 字符串转对象"""
        if value:
            try:
                return json.loads(value)
            except:
                return []
        return []

    # 注册数据库清理
    app.teardown_appcontext(close_db)

    # 注册蓝图
    app.register_blueprint(auth_bp)
    app.register_blueprint(pages_bp)
    app.register_blueprint(test_text_bp)
    app.register_blueprint(records_bp)

    return app


# ============== 启动 ==============

if __name__ == '__main__':
    init_db()
    app = create_app()
    app.run(debug=False, host='0.0.0.0', port=5001, threaded=True)
