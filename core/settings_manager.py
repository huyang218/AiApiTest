"""
系统配置管理模块
"""

import json
import os

SETTINGS_FILE = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'settings.json')


def load_settings():
    """加载系统配置"""
    default_settings = {
        "anthropic": {
            "api_key": "",
            "base_url": "https://api.anthropic.com"
        },
        "azure_openai": {
            "api_key": "",
            "base_url": ""
        },
        "gemini": {
            "api_key": "",
            "base_url": "https://generativelanguage.googleapis.com"
        },
        "deepseek": {
            "api_key": "",
            "base_url": "https://api.deepseek.com"
        },
        "qwen": {
            "api_key": "",
            "base_url": "https://dashscope.aliyuncs.com/compatible-mode"
        },
        "glm": {
            "api_key": "",
            "base_url": "https://open.bigmodel.cn/api/paas"
        },
        "moonshot": {
            "api_key": "",
            "base_url": "https://api.moonshot.cn"
        },
        "doubao": {
            "api_key": "",
            "base_url": "https://ark.cn-beijing.volces.com/api"
        },
        "admin_key": "admin123"
    }
    try:
        with open(SETTINGS_FILE, 'r') as f:
            settings = json.load(f)
            # 兼容旧配置格式
            if "official_api_key" in settings:
                settings["anthropic"] = {
                    "api_key": settings.get("official_api_key", ""),
                    "base_url": settings.get("official_base_url", "https://api.anthropic.com")
                }
            return {**default_settings, **settings}
    except:
        return default_settings


def save_settings(settings):
    """保存系统配置"""
    with open(SETTINGS_FILE, 'w') as f:
        json.dump(settings, f, indent=4, ensure_ascii=False)


def get_settings():
    """获取当前配置"""
    return load_settings()


def get_official_config(api_format):
    """根据 API 格式获取对应的原厂配置"""
    settings = get_settings()
    
    # 国产模型使用各自的原厂配置
    domestic_providers = {
        "deepseek": "deepseek",
        "qwen": "qwen",
        "glm": "glm",
        "moonshot": "moonshot",
        "doubao": "doubao",
    }
    
    if api_format in domestic_providers:
        return settings.get(domestic_providers[api_format], {})
    elif api_format == "anthropic":
        return settings.get("anthropic", {})
    elif api_format == "gemini":
        return settings.get("gemini", {})
    else:  # openai / azure_openai
        return settings.get("azure_openai", {})


def mask_key(key):
    """隐藏 API Key 中间部分"""
    if key and len(key) > 20:
        return key[:10] + "..." + key[-10:]
    return key or ""
