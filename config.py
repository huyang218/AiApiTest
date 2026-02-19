"""
API 服务商配置文件
在这里添加要测试的服务商配置
"""

from api_tester import ApiConfig, ApiFormat


# ============== 服务商配置 ==============
# 在下面添加你要测试的服务商

PROVIDERS = [
    # 示例配置（请替换为你的实际配置）
    # ApiConfig(
    #     name="Anthropic官方",
    #     base_url="https://api.anthropic.com",
    #     api_key="your-api-key-here",
    #     model="claude-sonnet-4-5-20250929",
    #     api_format=ApiFormat.ANTHROPIC,
    #     price_input=3.0,     # 输入价格 $/1M tokens
    #     price_output=15.0    # 输出价格 $/1M tokens
    # ),
    
    # 添加更多服务商...
    # ApiConfig(
    #     name="服务商名称",
    #     base_url="https://api.example.com",
    #     api_key="your-api-key-here",
    #     model="model-name",
    #     api_format=ApiFormat.ANTHROPIC,  # 或 ApiFormat.OPENAI
    #     price_input=0.0,
    #     price_output=0.0
    # ),
]


# ============== 测试参数 ==============

# 每个服务商的请求数量
NUM_REQUESTS = 10

# 并发数量
CONCURRENCY = 5
