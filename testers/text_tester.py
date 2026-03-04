"""
通用 AI API 测试框架
支持验证：价格对账、模型真实性、并发性能
"""

import asyncio
import aiohttp
import requests
import time
import json
import statistics
import random
from dataclasses import dataclass, field
from typing import List, Optional, Dict, Any
from datetime import datetime
from enum import Enum
import csv
import os


class ApiFormat(Enum):
    """API 格式类型"""
    ANTHROPIC = "anthropic"        # Anthropic 原生格式
    OPENAI = "openai"              # OpenAI 兼容格式
    AZURE_OPENAI = "azure_openai"  # Azure OpenAI 格式
    GEMINI = "gemini"              # Google Gemini 格式
    # 国产模型 (均使用 OpenAI 兼容格式)
    DEEPSEEK = "deepseek"
    QWEN = "qwen"
    GLM = "glm"
    MOONSHOT = "moonshot"
    DOUBAO = "doubao"


@dataclass
class ApiConfig:
    """API 配置"""
    name: str                          # 服务商名称
    base_url: str                      # API 基础 URL
    api_key: str                       # API 密钥
    model: str                         # 模型名称
    api_format: ApiFormat = ApiFormat.ANTHROPIC  # API 格式
    price_input: float = 0.0           # 输入价格 ($/1M tokens)
    price_output: float = 0.0          # 输出价格 ($/1M tokens)
    
    def __post_init__(self):
        # 移除末尾斜杠
        self.base_url = self.base_url.rstrip('/')


@dataclass
class RequestResult:
    """单次请求结果"""
    request_id: int
    success: bool
    latency_ms: float
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    error_message: str = ""
    response_content: str = ""


@dataclass 
class ModelVerifyResult:
    """模型验证结果"""
    response_model: str = ""
    self_reported_version: str = ""
    knowledge_cutoff: str = ""
    consistency_score: float = 0.0  # 一致性得分 0-1
    reasoning_correct: bool = False
    details: Dict[str, str] = field(default_factory=dict)


@dataclass
class BenchmarkResult:
    """并发测试结果"""
    total_requests: int = 0
    successful_requests: int = 0
    failed_requests: int = 0
    success_rate: float = 0.0
    
    total_time_ms: float = 0
    avg_latency_ms: float = 0
    min_latency_ms: float = 0
    max_latency_ms: float = 0
    p50_latency_ms: float = 0
    p90_latency_ms: float = 0
    p99_latency_ms: float = 0
    qps: float = 0
    
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    total_tokens: int = 0
    tokens_per_second: float = 0
    
    results: List[RequestResult] = field(default_factory=list)


@dataclass
class FullTestReport:
    """完整测试报告"""
    config: ApiConfig = None
    test_time: str = ""
    
    # 模型验证
    model_verify: ModelVerifyResult = None
    model_authenticity: str = ""  # 真实/可疑/未知
    
    # 并发测试
    benchmark: BenchmarkResult = None
    
    # 价格计算
    estimated_cost: float = 0.0
    
    # 综合评分
    overall_score: float = 0.0
    recommendations: List[str] = field(default_factory=list)


# ============== 复杂测试问题库 ==============
COMPLEX_PROMPTS = [
    """请分析以下Python代码的时间复杂度和空间复杂度，并给出优化建议：
```python
def find_duplicates(arr):
    duplicates = []
    for i in range(len(arr)):
        for j in range(i + 1, len(arr)):
            if arr[i] == arr[j] and arr[i] not in duplicates:
                duplicates.append(arr[i])
    return duplicates

def merge_sort(arr):
    if len(arr) <= 1:
        return arr
    mid = len(arr) // 2
    left = merge_sort(arr[:mid])
    right = merge_sort(arr[mid:])
    return merge(left, right)
```""",

    """请设计一个高并发的短链接服务系统，需要考虑以下方面：
1. 系统架构设计（包括负载均衡、缓存策略、数据库选型）
2. 短链接生成算法（如何保证唯一性、如何处理碰撞）
3. 高可用性设计（如何处理单点故障、数据备份策略）
4. 性能优化方案（如何支持每秒10万次请求）
请给出详细的技术方案。""",

    """请解决以下数学问题并详细说明推理过程：
有一个农场主有若干只鸡和兔子。他数了数，发现总共有35个头和94只脚。
1. 请用代数方法求解鸡和兔子各有多少只
2. 请推导出一个通用公式，给定任意的头数H和脚数F，求鸡和兔子的数量""",

    """请对以下新闻文本进行深度分析：
"随着人工智能技术的快速发展，大型语言模型（LLM）正在重塑各行各业的工作方式。根据最新研究报告，到2025年，全球将有超过70%的企业在日常运营中使用某种形式的AI辅助工具。"
请完成：
1. 提取文章的关键信息点（至少5个）
2. 分析文章的立场和倾向性
3. 识别文中可能存在的逻辑漏洞""",

    """请实现一个LRU（最近最少使用）缓存，要求：
1. 支持 get(key) 和 put(key, value) 操作，时间复杂度都是 O(1)
2. 缓存容量有限，当容量满时需要删除最久未使用的项
3. 用Python实现完整代码，包含详细注释
4. 分析你的实现的时间和空间复杂度""",

    """请为一个在线教育平台设计数据库schema，平台需要支持：
- 用户管理（学生、教师、管理员）
- 课程管理（课程信息、章节、视频）
- 学习进度跟踪
- 评论和评分系统
请提供关键表的SQL建表语句和重要的索引设计。""",

    """请详细解释当用户在浏览器地址栏输入 https://www.example.com 并按下回车后，发生的完整网络通信过程：
1. DNS解析过程
2. TCP三次握手
3. TLS/SSL握手过程
4. HTTP请求和响应""",

    """请解释并比较以下机器学习概念：
1. 监督学习 vs 无监督学习 vs 强化学习的区别和应用场景
2. 过拟合和欠拟合的原因、识别方法和解决方案
3. 交叉验证的原理""",

    """请分析以下Web应用代码中存在的安全漏洞，并给出修复建议：
```python
@app.route('/login', methods=['POST'])
def login():
    username = request.form['username']
    password = request.form['password']
    query = f"SELECT * FROM users WHERE username='{username}' AND password='{password}'"
    cursor.execute(query)
    return "Login result"
```""",

    """请解释分布式系统中的CAP定理：
1. 什么是一致性、可用性和分区容错性？
2. 为什么不能同时满足这三个特性？
3. 常见的分布式数据库是如何在CAP之间做取舍的？""",
]


class ApiTester:
    """API 测试器"""
    
    def __init__(self, config: ApiConfig):
        self.config = config
    
    def _get_headers(self) -> dict:
        """获取请求头"""
        if self.config.api_format == ApiFormat.ANTHROPIC:
            return {
                "x-api-key": self.config.api_key,
                "anthropic-version": "2023-06-01",
                "Content-Type": "application/json"
            }
        elif self.config.api_format == ApiFormat.AZURE_OPENAI:
            return {
                "api-key": self.config.api_key,
                "Content-Type": "application/json"
            }
        elif self.config.api_format == ApiFormat.GEMINI:
            return {
                "Content-Type": "application/json"
            }
        else:  # OpenAI format
            return {
                "Authorization": f"Bearer {self.config.api_key}",
                "Content-Type": "application/json"
            }
    
    def _get_endpoint(self) -> str:
        """获取 API 端点"""
        if self.config.api_format == ApiFormat.ANTHROPIC:
            return f"{self.config.base_url}/v1/messages"
        elif self.config.api_format == ApiFormat.AZURE_OPENAI:
            # Azure OpenAI 格式: {base_url}/deployments/{model}/chat/completions?api-version=2024-02-15-preview
            return f"{self.config.base_url}/deployments/{self.config.model}/chat/completions?api-version=2024-02-15-preview"
        elif self.config.api_format == ApiFormat.GEMINI:
            # Gemini 格式: {base_url}/v1beta/models/{model}:generateContent?key={api_key}
            return f"{self.config.base_url}/v1beta/models/{self.config.model}:generateContent?key={self.config.api_key}"
        else:
            return f"{self.config.base_url}/v1/chat/completions"
    
    def _build_payload(self, messages: list, max_tokens: int = 1024) -> dict:
        """构建请求体"""
        if self.config.api_format == ApiFormat.ANTHROPIC:
            return {
                "model": self.config.model,
                "messages": messages,
                "max_tokens": max_tokens
            }
        elif self.config.api_format == ApiFormat.GEMINI:
            # Gemini 格式转换
            contents = []
            for msg in messages:
                role = "user" if msg["role"] == "user" else "model"
                contents.append({
                    "role": role,
                    "parts": [{"text": msg["content"]}]
                })
            return {
                "contents": contents,
                "generationConfig": {
                    "maxOutputTokens": max_tokens
                }
            }
        else:
            return {
                "model": self.config.model,
                "messages": messages,
                "max_tokens": max_tokens
            }
    
    def _parse_response(self, data: dict) -> tuple:
        """解析响应，返回 (content, input_tokens, output_tokens, model)"""
        if self.config.api_format == ApiFormat.ANTHROPIC:
            content = data.get("content", [{}])[0].get("text", "")
            usage = data.get("usage", {})
            input_tokens = usage.get("input_tokens", 0)
            output_tokens = usage.get("output_tokens", 0)
            model = data.get("model", "")
        elif self.config.api_format == ApiFormat.GEMINI:
            # Gemini 响应格式
            candidates = data.get("candidates", [{}])
            if candidates:
                parts = candidates[0].get("content", {}).get("parts", [{}])
                content = parts[0].get("text", "") if parts else ""
            else:
                content = ""
            usage = data.get("usageMetadata", {})
            input_tokens = usage.get("promptTokenCount", 0)
            output_tokens = usage.get("candidatesTokenCount", 0)
            model = data.get("modelVersion", self.config.model)
        else:
            content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
            usage = data.get("usage", {})
            input_tokens = usage.get("prompt_tokens", 0)
            output_tokens = usage.get("completion_tokens", 0)
            model = data.get("model", "")
        
        return content, input_tokens, output_tokens, model
    
    def call_api(self, messages: list, max_tokens: int = 1024) -> dict:
        """同步调用 API"""
        response = requests.post(
            self._get_endpoint(),
            headers=self._get_headers(),
            json=self._build_payload(messages, max_tokens),
            timeout=120
        )
        return response.json()
    
    def _build_tools_payload(self, messages: list, tools: list, max_tokens: int = 1024) -> dict:
        """构建带 tools 的请求体，兼容各 API 格式"""
        if self.config.api_format == ApiFormat.ANTHROPIC:
            # Anthropic 格式: tools 用 input_schema 替代 parameters
            anthropic_tools = []
            for t in tools:
                func = t.get("function", {})
                anthropic_tools.append({
                    "name": func.get("name", ""),
                    "description": func.get("description", ""),
                    "input_schema": func.get("parameters", {})
                })
            return {
                "model": self.config.model,
                "messages": messages,
                "max_tokens": max_tokens,
                "tools": anthropic_tools
            }
        elif self.config.api_format == ApiFormat.GEMINI:
            # Gemini 格式: functionDeclarations
            contents = []
            for msg in messages:
                role = "user" if msg["role"] == "user" else "model"
                contents.append({
                    "role": role,
                    "parts": [{"text": msg["content"]}]
                })
            func_declarations = []
            for t in tools:
                func = t.get("function", {})
                func_declarations.append({
                    "name": func.get("name", ""),
                    "description": func.get("description", ""),
                    "parameters": func.get("parameters", {})
                })
            return {
                "contents": contents,
                "tools": [{"functionDeclarations": func_declarations}],
                "generationConfig": {
                    "maxOutputTokens": max_tokens
                }
            }
        else:
            # OpenAI 及兼容格式 (含国产模型)
            return {
                "model": self.config.model,
                "messages": messages,
                "max_tokens": max_tokens,
                "tools": tools
            }
    
    def _parse_tool_calls(self, data: dict) -> tuple:
        """
        解析 tool_call 响应，返回 (tool_calls_list, text_content, error)
        tool_calls_list: [{'name': str, 'arguments': dict/str}, ...]
        """
        try:
            if self.config.api_format == ApiFormat.ANTHROPIC:
                # Anthropic: content 数组中 type="tool_use" 的项
                content_blocks = data.get("content", [])
                tool_calls = []
                text_content = ""
                for block in content_blocks:
                    if block.get("type") == "tool_use":
                        tool_calls.append({
                            "name": block.get("name", ""),
                            "arguments": block.get("input", {})
                        })
                    elif block.get("type") == "text":
                        text_content += block.get("text", "")
                return tool_calls, text_content, None
                
            elif self.config.api_format == ApiFormat.GEMINI:
                # Gemini: candidates[0].content.parts 中的 functionCall
                candidates = data.get("candidates", [])
                tool_calls = []
                text_content = ""
                if candidates:
                    parts = candidates[0].get("content", {}).get("parts", [])
                    for part in parts:
                        if "functionCall" in part:
                            fc = part["functionCall"]
                            tool_calls.append({
                                "name": fc.get("name", ""),
                                "arguments": fc.get("args", {})
                            })
                        elif "text" in part:
                            text_content += part.get("text", "")
                return tool_calls, text_content, None
                
            else:
                # OpenAI 兼容格式
                choices = data.get("choices", [{}])
                message = choices[0].get("message", {}) if choices else {}
                text_content = message.get("content", "") or ""
                raw_tool_calls = message.get("tool_calls", [])
                tool_calls = []
                for tc in raw_tool_calls:
                    func = tc.get("function", {})
                    tool_calls.append({
                        "name": func.get("name", ""),
                        "arguments": func.get("arguments", "{}")
                    })
                return tool_calls, text_content, None
                
        except Exception as e:
            return [], "", str(e)
    
    def call_api_with_tools(self, messages: list, tools: list, max_tokens: int = 1024) -> dict:
        """同步调用带 tools 的 API"""
        response = requests.post(
            self._get_endpoint(),
            headers=self._get_headers(),
            json=self._build_tools_payload(messages, tools, max_tokens),
            timeout=120
        )
        return response.json()
    
    async def call_api_async(
        self, 
        session: aiohttp.ClientSession,
        request_id: int,
        messages: list,
        semaphore: asyncio.Semaphore,
        max_tokens: int = 256
    ) -> RequestResult:
        """异步调用 API"""
        async with semaphore:
            start_time = time.perf_counter()
            
            try:
                async with session.post(
                    self._get_endpoint(),
                    headers=self._get_headers(),
                    json=self._build_payload(messages, max_tokens),
                    timeout=aiohttp.ClientTimeout(total=120)
                ) as response:
                    end_time = time.perf_counter()
                    latency_ms = (end_time - start_time) * 1000
                    
                    if response.status == 200:
                        data = await response.json()
                        content, input_tokens, output_tokens, _ = self._parse_response(data)
                        
                        return RequestResult(
                            request_id=request_id,
                            success=True,
                            latency_ms=latency_ms,
                            input_tokens=input_tokens,
                            output_tokens=output_tokens,
                            total_tokens=input_tokens + output_tokens,
                            response_content=content[:100]
                        )
                    else:
                        error_text = await response.text()
                        return RequestResult(
                            request_id=request_id,
                            success=False,
                            latency_ms=latency_ms,
                            error_message=f"HTTP {response.status}: {error_text[:200]}"
                        )
                        
            except asyncio.TimeoutError:
                end_time = time.perf_counter()
                return RequestResult(
                    request_id=request_id,
                    success=False,
                    latency_ms=(end_time - start_time) * 1000,
                    error_message="请求超时"
                )
            except Exception as e:
                end_time = time.perf_counter()
                return RequestResult(
                    request_id=request_id,
                    success=False,
                    latency_ms=(end_time - start_time) * 1000,
                    error_message=str(e)
                )
    
    # ============== 模型验证 ==============
    
    # 复杂验证问题集
    VERIFY_QUESTIONS = {
        # 高级推理测试
        "logic_puzzle": {
            "question": """请解决这个复杂逻辑谜题，并展示你的推理过程：

有5个人（Alice, Bob, Carol, Dave, Eve）参加编程比赛，已知：
1. Alice 的排名比 Bob 好（数字小）
2. Carol 不是第一名也不是最后一名
3. Dave 的排名恰好比 Eve 差2名
4. Bob 的排名是奇数
5. 第三名的人名字以元音字母开头

请推导每个人的排名（1-5），并解释推理过程。""",
            "max_tokens": 800,
            "check": lambda r: ("alice" in r.lower() and "1" in r) or ("eve" in r.lower() and "2" in r)
        },
        
        # 数学推理
        "math_reasoning": {
            "question": """一道需要仔细思考的数学题：

一个水箱有A、B两个进水管和一个排水管C。
- 单独开A管，6小时可注满水箱
- 单独开B管，8小时可注满水箱  
- 单独开C管，12小时可排空满水箱

如果水箱初始为空，同时打开A、B、C三个管，需要多少小时才能注满水箱？
请给出详细的计算过程和最终答案。""",
            "max_tokens": 600,
            "check": lambda r: "4.8" in r or "24/5" in r or "4小时48分" in r
        },
        
        # 代码理解与调试
        "code_analysis": {
            "question": """分析以下Python代码的bug并给出修复方案：

```python
def find_pairs_with_sum(arr, target):
    seen = {}
    pairs = []
    for i, num in enumerate(arr):
        complement = target - num
        if complement in seen:
            pairs.append((complement, num))
        seen[num] = i
    return pairs

# 测试用例
result = find_pairs_with_sum([1, 2, 3, 2, 4], 4)
print(result)  # 期望输出所有和为4的不重复数对
```

问题：
1. 这段代码有什么潜在问题？
2. 如果输入数组有重复元素，会发生什么？
3. 请给出修复后的代码。""",
            "max_tokens": 1000,
            "check": lambda r: "重复" in r or "duplicate" in r.lower() or "覆盖" in r
        },
        
        # 多语言理解
        "multilingual": {
            "question": """请完成以下多语言任务：

1. 将这句话翻译成法语、德语和日语：
   "The early bird catches the worm, but the second mouse gets the cheese."

2. 解释这句话的深层含义和文化背景

3. 用中文创作一个类似含义的原创谚语""",
            "max_tokens": 800,
            "check": lambda r: any(lang in r.lower() for lang in ["français", "deutsch", "日本語", "早起", "cheese", "fromage"])
        },
        
        # 批判性思维
        "critical_thinking": {
            "question": """请分析以下论证中的逻辑谬误：

"所有成功的企业家都早起。马克·扎克伯格是成功的企业家。
因此，如果你想成功，你必须每天早上5点起床。
而且，我认识一个每天早起的人，他现在是百万富翁，
这证明了早起确实能让人成功。"

请：
1. 找出论证中至少3个逻辑谬误
2. 解释每个谬误为什么是错误的
3. 如何改进这个论证使其更加合理""",
            "max_tokens": 800,
            "check": lambda r: any(term in r.lower() for term in ["谬误", "fallacy", "因果", "相关", "归纳"])
        },
        
        # 创意写作（测试高级模型的创造力）
        "creative": {
            "question": """请用"量子纠缠"的概念作为核心隐喻，写一首关于异地恋的现代诗（10-15行）。

要求：
1. 必须准确使用量子物理概念（如叠加态、测量坍缩、非定域性）
2. 诗歌要有情感深度
3. 结构要有层次感""",
            "max_tokens": 600,
            "check": lambda r: any(term in r for term in ["纠缠", "坍缩", "叠加", "quantum", "entangle"])
        }
    }
    
    def verify_model(self) -> ModelVerifyResult:
        """验证模型真实性 - 使用复杂问题"""
        result = ModelVerifyResult()
        
        print(f"\n{'='*50}")
        print(f"模型验证: {self.config.name}")
        print(f"{'='*50}")
        
        # 测试1: 检查响应 model 字段
        print("\n[1/7] 检查 API 响应 model 字段...")
        try:
            messages = [{"role": "user", "content": "Hi"}]
            response = self.call_api(messages, max_tokens=50)
            _, _, _, model = self._parse_response(response)
            result.response_model = model
            result.details["response_model"] = model
            print(f"      响应模型: {model}")
        except Exception as e:
            result.details["response_model_error"] = str(e)
            print(f"      错误: {e}")
        
        # 测试2: 模型自我介绍（更详细的问题）
        print("\n[2/7] 模型身份深度询问...")
        try:
            messages = [{"role": "user", "content": """Please provide detailed information about yourself:
1. Your exact model name and version
2. Your training cutoff date
3. Who created/trained you
4. What are your key capabilities and limitations
5. How do you differ from other AI models like GPT-4 or Gemini?

Be specific and accurate."""}]
            response = self.call_api(messages, max_tokens=500)
            content, _, _, _ = self._parse_response(response)
            result.self_reported_version = content[:800]
            result.details["self_intro"] = content[:800]
            print(f"      {content[:150]}...")
        except Exception as e:
            result.details["self_intro_error"] = str(e)
        
        # 测试3: 知识截止日期验证
        print("\n[3/7] 知识时效性测试...")
        try:
            messages = [{"role": "user", "content": """回答以下关于你知识库的问题：
1. 你的知识截止日期是什么时候？
2. 你知道2024年美国总统大选的结果吗？
3. 你知道 Claude 3.5 Sonnet 是什么时候发布的吗？
请分别回答。"""}]
            response = self.call_api(messages, max_tokens=300)
            content, _, _, _ = self._parse_response(response)
            result.knowledge_cutoff = content[:400]
            result.details["knowledge_cutoff"] = content[:400]
            print(f"      {content[:150]}...")
        except Exception as e:
            result.details["knowledge_cutoff_error"] = str(e)
        
        # 测试4: 复杂逻辑推理
        print("\n[4/7] 复杂逻辑推理测试...")
        reasoning_score = 0
        try:
            q = self.VERIFY_QUESTIONS["logic_puzzle"]
            messages = [{"role": "user", "content": q["question"]}]
            response = self.call_api(messages, max_tokens=q["max_tokens"])
            content, _, _, _ = self._parse_response(response)
            result.details["logic_puzzle"] = content[:1000]
            if q["check"](content):
                reasoning_score += 1
            print(f"      逻辑推理: {'通过' if q['check'](content) else '需验证'}")
        except Exception as e:
            result.details["logic_puzzle_error"] = str(e)
        
        # 测试5: 数学推理
        print("\n[5/7] 数学推理能力测试...")
        try:
            q = self.VERIFY_QUESTIONS["math_reasoning"]
            messages = [{"role": "user", "content": q["question"]}]
            response = self.call_api(messages, max_tokens=q["max_tokens"])
            content, _, _, _ = self._parse_response(response)
            result.details["math_reasoning"] = content[:800]
            if q["check"](content):
                reasoning_score += 1
            print(f"      数学推理: {'正确' if q['check'](content) else '需验证'}")
        except Exception as e:
            result.details["math_reasoning_error"] = str(e)
        
        # 测试6: 代码分析
        print("\n[6/7] 代码理解与分析测试...")
        try:
            q = self.VERIFY_QUESTIONS["code_analysis"]
            messages = [{"role": "user", "content": q["question"]}]
            response = self.call_api(messages, max_tokens=q["max_tokens"])
            content, _, _, _ = self._parse_response(response)
            result.details["code_analysis"] = content[:1000]
            if q["check"](content):
                reasoning_score += 1
            print(f"      代码分析: {'深入' if q['check'](content) else '基础'}")
        except Exception as e:
            result.details["code_analysis_error"] = str(e)
        
        # 设置推理得分
        result.reasoning_correct = reasoning_score >= 2
        result.details["reasoning_score"] = f"{reasoning_score}/3"
        
        # 测试7: 一致性检查（多角度询问）
        print("\n[7/7] 多角度一致性检查...")
        consistency_count = 0
        responses = []
        questions = [
            "Are you Claude? Answer only Yes or No.",
            "你是由 Anthropic 公司开发的吗？只回答是或否。",
            "Is your name GPT? Answer only Yes or No.",
            "你的模型架构是 Transformer 吗？只回答是或否。",
        ]
        expected = [True, True, False, True]  # Claude的预期回答
        
        try:
            for i, q in enumerate(questions):
                messages = [{"role": "user", "content": q}]
                response = self.call_api(messages, max_tokens=50)
                content, _, _, _ = self._parse_response(response)
                responses.append(content.strip())
                
                # 检查回答是否符合预期
                is_yes = 'yes' in content.lower() or '是' in content
                if (expected[i] and is_yes) or (not expected[i] and not is_yes):
                    consistency_count += 1
            
            result.consistency_score = consistency_count / len(questions) if questions else 0
            result.details["consistency_responses"] = responses
            result.details["consistency_questions"] = questions
            print(f"      一致性得分: {result.consistency_score:.0%} ({consistency_count}/{len(questions)})")
        except Exception as e:
            result.details["consistency_error"] = str(e)
        
        return result
    
    # ============== 并发测试 ==============
    
    async def run_benchmark(
        self,
        num_requests: int = 10,
        concurrency: int = 5,
        progress_callback=None
    ) -> BenchmarkResult:
        """运行并发压力测试"""
        
        print(f"\n{'='*50}")
        print(f"并发测试: {self.config.name}")
        print(f"{'='*50}")
        print(f"请求数: {num_requests}, 并发数: {concurrency}")
        
        prompts = COMPLEX_PROMPTS.copy()
        random.shuffle(prompts)
        
        semaphore = asyncio.Semaphore(concurrency)
        connector = aiohttp.TCPConnector(limit=concurrency, limit_per_host=concurrency)
        
        async with aiohttp.ClientSession(connector=connector) as session:
            tasks = []
            for i in range(num_requests):
                prompt = prompts[i % len(prompts)]
                messages = [{"role": "user", "content": prompt}]
                task = self.call_api_async(session, i + 1, messages, semaphore)
                tasks.append(task)
            
            start_time = time.perf_counter()
            
            results = []
            completed = 0
            for coro in asyncio.as_completed(tasks):
                result = await coro
                results.append(result)
                completed += 1
                
                status = "✓" if result.success else "✗"
                info = f"tokens: {result.total_tokens}" if result.success else result.error_message[:30]
                print(f"[{completed}/{num_requests}] #{result.request_id} {status} | {result.latency_ms:.0f}ms | {info}")
                
                if progress_callback:
                    progress_callback(completed, num_requests)
            
            end_time = time.perf_counter()
            total_time_ms = (end_time - start_time) * 1000
        
        return self._generate_benchmark_result(results, total_time_ms)
    
    def _generate_benchmark_result(self, results: List[RequestResult], total_time_ms: float) -> BenchmarkResult:
        """生成测试结果"""
        br = BenchmarkResult()
        br.results = results
        br.total_requests = len(results)
        br.total_time_ms = total_time_ms
        
        successful = [r for r in results if r.success]
        br.successful_requests = len(successful)
        br.failed_requests = len(results) - len(successful)
        br.success_rate = len(successful) / len(results) if results else 0
        
        if successful:
            latencies = sorted([r.latency_ms for r in successful])
            n = len(latencies)
            
            br.avg_latency_ms = statistics.mean(latencies)
            br.min_latency_ms = min(latencies)
            br.max_latency_ms = max(latencies)
            br.p50_latency_ms = latencies[int(n * 0.5)]
            br.p90_latency_ms = latencies[int(n * 0.9)] if n >= 10 else latencies[-1]
            br.p99_latency_ms = latencies[int(n * 0.99)] if n >= 100 else latencies[-1]
            
            br.total_input_tokens = sum(r.input_tokens for r in successful)
            br.total_output_tokens = sum(r.output_tokens for r in successful)
            br.total_tokens = sum(r.total_tokens for r in successful)
        
        if total_time_ms > 0:
            br.qps = (br.successful_requests / total_time_ms) * 1000
            br.tokens_per_second = (br.total_tokens / total_time_ms) * 1000
        
        return br
    
    # ============== 完整测试 ==============
    
    async def run_full_test(
        self,
        num_requests: int = 10,
        concurrency: int = 5
    ) -> FullTestReport:
        """运行完整测试"""
        
        report = FullTestReport()
        report.config = self.config
        report.test_time = datetime.now().isoformat()
        
        # 1. 模型验证
        report.model_verify = self.verify_model()
        
        # 判断模型真实性
        model_match = self.config.model in report.model_verify.response_model
        consistency_ok = report.model_verify.consistency_score >= 0.5
        reasoning_ok = report.model_verify.reasoning_correct
        
        if model_match and consistency_ok and reasoning_ok:
            report.model_authenticity = "可信"
        elif model_match or consistency_ok:
            report.model_authenticity = "存疑"
        else:
            report.model_authenticity = "可疑"
        
        # 2. 并发测试
        report.benchmark = await self.run_benchmark(num_requests, concurrency)
        
        # 3. 价格计算
        if self.config.price_input > 0 and self.config.price_output > 0:
            input_cost = (report.benchmark.total_input_tokens / 1_000_000) * self.config.price_input
            output_cost = (report.benchmark.total_output_tokens / 1_000_000) * self.config.price_output
            report.estimated_cost = input_cost + output_cost
        
        # 4. 综合评分 (0-100)
        score = 0
        # 成功率 (40分)
        score += report.benchmark.success_rate * 40
        # 模型真实性 (30分)
        if report.model_authenticity == "可信":
            score += 30
        elif report.model_authenticity == "存疑":
            score += 15
        # 性能 (30分) - 基于延迟
        if report.benchmark.avg_latency_ms > 0:
            latency_score = max(0, 30 - (report.benchmark.avg_latency_ms / 5000) * 30)
            score += latency_score
        
        report.overall_score = min(100, score)
        
        # 5. 建议
        if report.benchmark.success_rate < 1.0:
            report.recommendations.append(f"成功率 {report.benchmark.success_rate:.0%}，存在请求失败情况")
        if report.model_authenticity != "可信":
            report.recommendations.append(f"模型真实性{report.model_authenticity}，建议进一步验证")
        if report.benchmark.avg_latency_ms > 30000:
            report.recommendations.append(f"平均延迟 {report.benchmark.avg_latency_ms/1000:.1f}s 较高")
        
        return report


# ============== 报告生成 ==============

def generate_markdown_report(reports: List[FullTestReport], output_file: str = None) -> str:
    """生成 Markdown 格式的完整报告"""
    
    if output_file is None:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_file = f"api_test_report_{timestamp}.md"
    
    lines = []
    lines.append("# AI API 服务商测试报告")
    lines.append(f"\n**生成时间**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append(f"\n**测试服务商数量**: {len(reports)}")
    
    # 总览表格
    lines.append("\n## 📊 总览对比")
    lines.append("\n| 服务商 | 模型 | 真实性 | 成功率 | 平均延迟 | QPS | 总Tokens | 预估费用 | 评分 |")
    lines.append("|--------|------|--------|--------|----------|-----|----------|----------|------|")
    
    for r in reports:
        cost_str = f"${r.estimated_cost:.4f}" if r.estimated_cost > 0 else "-"
        lines.append(
            f"| {r.config.name} | {r.config.model[:20]} | {r.model_authenticity} | "
            f"{r.benchmark.success_rate:.0%} | {r.benchmark.avg_latency_ms/1000:.1f}s | "
            f"{r.benchmark.qps:.2f} | {r.benchmark.total_tokens:,} | {cost_str} | "
            f"**{r.overall_score:.0f}** |"
        )
    
    # 详细报告
    for i, r in enumerate(reports, 1):
        lines.append(f"\n---\n")
        lines.append(f"## {i}. {r.config.name}")
        lines.append(f"\n**测试时间**: {r.test_time}")
        lines.append(f"\n**API 配置**:")
        lines.append(f"- Base URL: `{r.config.base_url}`")
        lines.append(f"- 模型: `{r.config.model}`")
        lines.append(f"- API 格式: {r.config.api_format.value}")
        
        # 模型验证
        lines.append(f"\n### 🔍 模型验证")
        lines.append(f"\n| 检查项 | 结果 |")
        lines.append(f"|--------|------|")
        lines.append(f"| API 响应模型 | `{r.model_verify.response_model}` |")
        lines.append(f"| 知识截止日期 | {r.model_verify.knowledge_cutoff[:50] if r.model_verify.knowledge_cutoff else 'N/A'} |")
        lines.append(f"| 一致性得分 | {r.model_verify.consistency_score:.0%} |")
        lines.append(f"| 推理测试 | {'通过 ✓' if r.model_verify.reasoning_correct else '需验证'} |")
        lines.append(f"| **综合判定** | **{r.model_authenticity}** |")
        
        # 性能测试
        lines.append(f"\n### ⚡ 性能测试")
        lines.append(f"\n| 指标 | 数值 |")
        lines.append(f"|------|------|")
        lines.append(f"| 总请求数 | {r.benchmark.total_requests} |")
        lines.append(f"| 成功请求 | {r.benchmark.successful_requests} |")
        lines.append(f"| 失败请求 | {r.benchmark.failed_requests} |")
        lines.append(f"| 成功率 | {r.benchmark.success_rate:.1%} |")
        lines.append(f"| 总耗时 | {r.benchmark.total_time_ms/1000:.2f}s |")
        lines.append(f"| QPS | {r.benchmark.qps:.2f} |")
        lines.append(f"| 平均延迟 | {r.benchmark.avg_latency_ms/1000:.2f}s |")
        lines.append(f"| P50 延迟 | {r.benchmark.p50_latency_ms/1000:.2f}s |")
        lines.append(f"| P90 延迟 | {r.benchmark.p90_latency_ms/1000:.2f}s |")
        lines.append(f"| P99 延迟 | {r.benchmark.p99_latency_ms/1000:.2f}s |")
        
        # Token 统计
        lines.append(f"\n### 💰 Token 对账")
        lines.append(f"\n| 项目 | 数量 |")
        lines.append(f"|------|------|")
        lines.append(f"| 输入 Tokens | {r.benchmark.total_input_tokens:,} |")
        lines.append(f"| 输出 Tokens | {r.benchmark.total_output_tokens:,} |")
        lines.append(f"| 总 Tokens | {r.benchmark.total_tokens:,} |")
        lines.append(f"| Tokens/秒 | {r.benchmark.tokens_per_second:.1f} |")
        if r.estimated_cost > 0:
            lines.append(f"| **预估费用** | **${r.estimated_cost:.4f}** |")
        
        # 建议
        if r.recommendations:
            lines.append(f"\n### ⚠️ 注意事项")
            for rec in r.recommendations:
                lines.append(f"- {rec}")
        
        lines.append(f"\n### 📈 综合评分: **{r.overall_score:.0f}/100**")
    
    content = "\n".join(lines)
    
    with open(output_file, 'w', encoding='utf-8') as f:
        f.write(content)
    
    print(f"\n报告已保存到: {output_file}")
    return output_file


def generate_json_report(reports: List[FullTestReport], output_file: str = None) -> str:
    """生成 JSON 格式的详细报告"""
    
    if output_file is None:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_file = f"api_test_report_{timestamp}.json"
    
    data = {
        "generated_at": datetime.now().isoformat(),
        "total_providers": len(reports),
        "reports": []
    }
    
    for r in reports:
        report_data = {
            "provider": r.config.name,
            "base_url": r.config.base_url,
            "model": r.config.model,
            "api_format": r.config.api_format.value,
            "test_time": r.test_time,
            "model_verification": {
                "response_model": r.model_verify.response_model,
                "knowledge_cutoff": r.model_verify.knowledge_cutoff,
                "consistency_score": r.model_verify.consistency_score,
                "reasoning_correct": r.model_verify.reasoning_correct,
                "authenticity": r.model_authenticity,
                "details": r.model_verify.details
            },
            "benchmark": {
                "total_requests": r.benchmark.total_requests,
                "successful_requests": r.benchmark.successful_requests,
                "failed_requests": r.benchmark.failed_requests,
                "success_rate": r.benchmark.success_rate,
                "total_time_ms": r.benchmark.total_time_ms,
                "latency": {
                    "avg_ms": r.benchmark.avg_latency_ms,
                    "min_ms": r.benchmark.min_latency_ms,
                    "max_ms": r.benchmark.max_latency_ms,
                    "p50_ms": r.benchmark.p50_latency_ms,
                    "p90_ms": r.benchmark.p90_latency_ms,
                    "p99_ms": r.benchmark.p99_latency_ms
                },
                "qps": r.benchmark.qps,
                "tokens_per_second": r.benchmark.tokens_per_second
            },
            "token_usage": {
                "input_tokens": r.benchmark.total_input_tokens,
                "output_tokens": r.benchmark.total_output_tokens,
                "total_tokens": r.benchmark.total_tokens
            },
            "estimated_cost": r.estimated_cost,
            "overall_score": r.overall_score,
            "recommendations": r.recommendations,
            "request_details": [
                {
                    "request_id": req.request_id,
                    "success": req.success,
                    "latency_ms": req.latency_ms,
                    "input_tokens": req.input_tokens,
                    "output_tokens": req.output_tokens,
                    "total_tokens": req.total_tokens,
                    "error": req.error_message
                }
                for req in r.benchmark.results
            ]
        }
        data["reports"].append(report_data)
    
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    
    print(f"JSON 报告已保存到: {output_file}")
    return output_file


# ============== 主函数 ==============

async def test_providers(configs: List[ApiConfig], num_requests: int = 10, concurrency: int = 5) -> List[FullTestReport]:
    """测试多个服务商"""
    reports = []
    
    for i, config in enumerate(configs, 1):
        print(f"\n{'#'*60}")
        print(f"# 测试服务商 [{i}/{len(configs)}]: {config.name}")
        print(f"{'#'*60}")
        
        tester = ApiTester(config)
        report = await tester.run_full_test(num_requests, concurrency)
        reports.append(report)
    
    return reports


async def main():
    """示例主函数"""
    
    # 配置要测试的服务商
    configs = [
        ApiConfig(
            name="示例服务商",
            base_url="https://api.example.com",
            api_key="your-api-key-here",
            model="claude-sonnet-4-5-20250929",
            api_format=ApiFormat.ANTHROPIC,
            price_input=3.0,    # $/1M tokens
            price_output=15.0   # $/1M tokens
        ),
        # 添加更多服务商...
    ]
    
    # 运行测试
    reports = await test_providers(configs, num_requests=10, concurrency=5)
    
    # 生成报告
    generate_markdown_report(reports)
    generate_json_report(reports)
    
    print("\n" + "="*60)
    print("所有测试完成！")
    print("="*60)


if __name__ == "__main__":
    asyncio.run(main())
