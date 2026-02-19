"""
页面路由 - 首页/历史/详情/设置
"""

from flask import Blueprint, render_template, request, redirect, url_for, jsonify
from core.database import get_db
from core.settings_manager import get_settings, save_settings, mask_key, get_official_config
from routes.auth import login_required

pages_bp = Blueprint('pages', __name__)


@pages_bp.route('/')
@login_required
def index():
    """首页 - 测试页面"""
    return render_template('index.html')


@pages_bp.route('/compare')
@login_required
def compare():
    """多模型对比页面"""
    return render_template('compare.html')


@pages_bp.route('/history')
@login_required
def history():
    """历史记录页面"""
    db = get_db()
    records = db.execute(
        'SELECT * FROM test_records ORDER BY created_at DESC LIMIT 100'
    ).fetchall()
    return render_template('history.html', records=records)


@pages_bp.route('/record/<int:record_id>')
@login_required
def record_detail(record_id):
    """测试记录详情"""
    db = get_db()
    record = db.execute(
        'SELECT * FROM test_records WHERE id = ?', (record_id,)
    ).fetchone()
    
    if record is None:
        return "记录不存在", 404
    
    return render_template('record_detail.html', record=record)


@pages_bp.route('/settings', methods=['GET', 'POST'])
@login_required
def settings_page():
    """系统设置页面"""
    if request.method == 'POST':
        settings = get_settings()
        
        # OpenAI 配置
        settings['openai'] = {
            'api_key': request.form.get('openai_api_key', '').strip(),
            'base_url': request.form.get('openai_base_url', 'https://api.openai.com').strip()
        }
        
        # Anthropic 配置
        settings['anthropic'] = {
            'api_key': request.form.get('anthropic_api_key', '').strip(),
            'base_url': request.form.get('anthropic_base_url', 'https://api.anthropic.com').strip()
        }
        
        # Azure OpenAI 配置
        settings['azure_openai'] = {
            'api_key': request.form.get('azure_api_key', '').strip(),
            'base_url': request.form.get('azure_base_url', '').strip()
        }
        
        # Gemini 配置
        settings['gemini'] = {
            'api_key': request.form.get('gemini_api_key', '').strip(),
            'base_url': request.form.get('gemini_base_url', 'https://generativelanguage.googleapis.com').strip()
        }
        
        # 国产模型配置
        settings['deepseek'] = {
            'api_key': request.form.get('deepseek_api_key', '').strip(),
            'base_url': request.form.get('deepseek_base_url', 'https://api.deepseek.com').strip()
        }
        settings['qwen'] = {
            'api_key': request.form.get('qwen_api_key', '').strip(),
            'base_url': request.form.get('qwen_base_url', 'https://dashscope.aliyuncs.com/compatible-mode').strip()
        }
        settings['glm'] = {
            'api_key': request.form.get('glm_api_key', '').strip(),
            'base_url': request.form.get('glm_base_url', 'https://open.bigmodel.cn/api/paas').strip()
        }
        settings['moonshot'] = {
            'api_key': request.form.get('moonshot_api_key', '').strip(),
            'base_url': request.form.get('moonshot_base_url', 'https://api.moonshot.cn').strip()
        }
        settings['doubao'] = {
            'api_key': request.form.get('doubao_api_key', '').strip(),
            'base_url': request.form.get('doubao_base_url', 'https://ark.cn-beijing.volces.com/api').strip()
        }
        
        # 登录密钥
        new_admin_key = request.form.get('admin_key', '').strip()
        if new_admin_key:
            settings['admin_key'] = new_admin_key
        
        # 模型映射配置
        mapping_keys = request.form.getlist('mapping_key[]')
        mapping_values = request.form.getlist('mapping_value[]')
        model_mapping = {}
        for k, v in zip(mapping_keys, mapping_values):
            k = k.strip()
            v = v.strip()
            if k and v:
                model_mapping[k] = v
        settings['model_mapping'] = model_mapping
        
        save_settings(settings)
        return redirect(url_for('pages.settings_page'))
    
    settings = get_settings()
    
    # 隐藏 API Keys
    masked_keys = {
        'masked_openai': mask_key(settings.get('openai', {}).get('api_key', '')),
        'masked_anthropic': mask_key(settings.get('anthropic', {}).get('api_key', '')),
        'masked_azure': mask_key(settings.get('azure_openai', {}).get('api_key', '')),
        'masked_gemini': mask_key(settings.get('gemini', {}).get('api_key', '')),
        'masked_deepseek': mask_key(settings.get('deepseek', {}).get('api_key', '')),
        'masked_qwen': mask_key(settings.get('qwen', {}).get('api_key', '')),
        'masked_glm': mask_key(settings.get('glm', {}).get('api_key', '')),
        'masked_moonshot': mask_key(settings.get('moonshot', {}).get('api_key', '')),
        'masked_doubao': mask_key(settings.get('doubao', {}).get('api_key', '')),
    }
    
    return render_template('settings.html', settings=settings, **masked_keys)


@pages_bp.route('/api/settings')
@login_required
def get_settings_api():
    """获取系统设置"""
    settings = get_settings()
    
    result = {
        'has_openai_key': bool(settings.get('openai', {}).get('api_key')),
        'has_anthropic_key': bool(settings.get('anthropic', {}).get('api_key')),
        'has_azure_key': bool(settings.get('azure_openai', {}).get('api_key')),
        'has_gemini_key': bool(settings.get('gemini', {}).get('api_key')),
        'openai_base_url': settings.get('openai', {}).get('base_url', 'https://api.openai.com'),
        'anthropic_base_url': settings.get('anthropic', {}).get('base_url', 'https://api.anthropic.com'),
        'azure_base_url': settings.get('azure_openai', {}).get('base_url', ''),
        'gemini_base_url': settings.get('gemini', {}).get('base_url', 'https://generativelanguage.googleapis.com'),
    }
    
    # 国产模型配置状态
    for provider in ['deepseek', 'qwen', 'glm', 'moonshot', 'doubao']:
        result[f'has_{provider}_key'] = bool(settings.get(provider, {}).get('api_key'))
        result[f'{provider}_base_url'] = settings.get(provider, {}).get('base_url', '')
    
    return jsonify(result)
