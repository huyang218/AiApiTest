"""
文本模型测试路由 - 验证/流式验证/AI分析/深度测试/并发/Token/完整测试
"""

import asyncio
import json
import re
from flask import Blueprint, request, jsonify, Response, stream_with_context
from core.settings_manager import load_settings, get_official_config
from core.utils import (
    get_config_from_request, calculate_similarity, is_valid_response,
    get_all_test_questions, get_api_format_enum,
    get_honesty_test_questions, analyze_honesty_response, check_consistency
)
from routes.auth import login_required
from routes.records import save_report
from testers.text_tester import ApiTester, ApiConfig, ApiFormat, FullTestReport

test_text_bp = Blueprint('test_text', __name__)


def _get_official_context(api_format_str):
    """获取原厂 API 上下文（配置、名称、格式枚举）"""
    # 国产模型映射
    domestic_formats = {
        "deepseek": ("deepseek", "DeepSeek", ApiFormat.OPENAI),
        "qwen": ("qwen", "通义千问", ApiFormat.OPENAI),
        "glm": ("glm", "智谱GLM", ApiFormat.OPENAI),
        "moonshot": ("moonshot", "Moonshot AI", ApiFormat.OPENAI),
        "doubao": ("doubao", "豆包", ApiFormat.OPENAI),
    }
    
    if api_format_str in domestic_formats:
        cfg_key, name, fmt = domestic_formats[api_format_str]
        return get_official_config(cfg_key), name, fmt
    elif api_format_str == "anthropic":
        return get_official_config("anthropic"), "Anthropic", ApiFormat.ANTHROPIC
    elif api_format_str == "gemini":
        return get_official_config("gemini"), "Google Gemini", ApiFormat.GEMINI
    else:
        return get_official_config("openai"), "Azure OpenAI", ApiFormat.AZURE_OPENAI


# ============== 模型真实性验证 ==============

@test_text_bp.route('/api/test/verify', methods=['POST'])
@login_required
def run_verify():
    """运行模型真实性验证（对比原厂API）"""
    data = request.json
    config, _, _, error = get_config_from_request(data)
    
    if error:
        return jsonify({'error': error}), 400
    
    api_format_str = data.get('api_format', 'anthropic')
    official_cfg, provider_name, official_api_format = _get_official_context(api_format_str)
    
    official_api_key = official_cfg.get('api_key', '').strip()
    official_base_url = official_cfg.get('base_url', '').strip()
    
    if not official_api_key:
        return jsonify({'error': f'请先在系统设置中配置 {provider_name} 原厂 API Key'}), 400
    
    # 获取模型映射配置
    settings = load_settings()
    model_mapping = settings.get('model_mapping', {})
    original_model = config.model
    
    if original_model in model_mapping:
        official_model = model_mapping[original_model]
        model_was_mapped = True
    else:
        official_model = original_model
        model_was_mapped = False
    
    try:
        official_config = ApiConfig(
            name=f"{provider_name}官方",
            base_url=official_base_url,
            api_key=official_api_key,
            model=official_model,
            api_format=official_api_format
        )
        
        all_questions = get_all_test_questions()
        
        # 调用待测API
        test_tester = ApiTester(config)
        test_responses = []
        test_errors = []
        for q in all_questions:
            try:
                resp = test_tester.call_api([{"role": "user", "content": q['question']}], max_tokens=600)
                content, _, _, _ = test_tester._parse_response(resp)
                test_responses.append(content)
                test_errors.append(None)
            except Exception as e:
                test_responses.append(f"[Error: {str(e)[:100]}]")
                test_errors.append(str(e))
        
        # 调用原厂API
        official_tester = ApiTester(official_config)
        official_responses = []
        official_errors = []
        
        for i, q in enumerate(all_questions):
            try:
                resp = official_tester.call_api([{"role": "user", "content": q['question']}], max_tokens=600)
                content, _, _, _ = official_tester._parse_response(resp)
                official_responses.append(content)
                official_errors.append(None)
            except Exception as e:
                error_msg = str(e)
                official_responses.append(f"[Error: {error_msg[:100]}]")
                official_errors.append(error_msg)
        
        # 统计有效响应
        test_valid_count = sum(1 for r in test_responses if is_valid_response(r))
        official_valid_count = sum(1 for r in official_responses if is_valid_response(r))
        
        # 计算相似度
        similarities = []
        for i, (t, o) in enumerate(zip(test_responses, official_responses)):
            if is_valid_response(t) and is_valid_response(o):
                sim = calculate_similarity(t, o)
                similarities.append(sim if sim >= 0 else 0)
            else:
                similarities.append(-1)
        
        valid_similarities = [s for s in similarities if s >= 0]
        avg_similarity = sum(valid_similarities) / len(valid_similarities) if valid_similarities else 0
        
        # 响应模型字段检查
        try:
            check_resp = test_tester.call_api([{"role": "user", "content": "Hi"}], max_tokens=10)
            _, _, _, response_model = test_tester._parse_response(check_resp)
        except:
            response_model = ""
        
        model_match = config.model in response_model if response_model else False
        official_api_working = official_valid_count >= 5
        
        # 综合判断
        reasons = []
        
        if not official_api_working:
            if official_valid_count == 0:
                first_error = next((e for e in official_errors if e), None)
                model_not_found = first_error and ('model' in first_error.lower() or 'not found' in first_error.lower() or '404' in first_error)
                
                if model_not_found:
                    if model_was_mapped:
                        reasons.append(f"⚠️ 映射后的模型'{official_model}'在原厂API中不存在")
                        reasons.append(f"原始模型名: {original_model}")
                        reasons.append(f"请检查模型映射配置是否正确")
                    else:
                        reasons.append(f"⚠️ 模型名'{original_model}'在原厂API中不存在")
                        reasons.append(f"这表明待测API可能使用了自定义模型名，而非原厂标准命名")
                        reasons.append(f"建议: 在系统设置中配置模型映射，或确认待测API实际调用的模型")
                else:
                    reasons.append(f"原厂API调用失败，无法对比验证")
                    if first_error:
                        reasons.append(f"错误详情: {first_error[:100]}")
            else:
                reasons.append(f"原厂API部分失败({official_valid_count}/{len(all_questions)})")
            
            if model_match and test_valid_count >= 6:
                authenticity = "待验证"
            else:
                authenticity = "无法验证"
        else:
            if not model_match:
                reasons.append(f"响应模型字段不匹配: 期望'{config.model}'，实际'{response_model or '空'}'")
            
            if avg_similarity < 0.25:
                reasons.append(f"与原厂API响应相似度较低: {avg_similarity:.1%}")
            
            low_sim_questions = [i+1 for i, sim in enumerate(similarities) if 0 <= sim < 0.2]
            if low_sim_questions:
                reasons.append(f"第{low_sim_questions}题响应差异较大")
            
            score = 0
            if model_match:
                score += 40
            if avg_similarity >= 0.4:
                score += 35
            elif avg_similarity >= 0.25:
                score += 20
            if test_valid_count == len(all_questions):
                score += 15
            if len(low_sim_questions) <= 1:
                score += 10
            
            authenticity = "可信" if score >= 70 else "存疑" if score >= 40 else "可疑"
        
        # 构建对比结果
        comparison_details = []
        for i, q in enumerate(all_questions):
            sim_value = similarities[i] if i < len(similarities) else -1
            comparison_details.append({
                'id': q['id'],
                'category': q['category'],
                'type': q['type'],
                'question': q['question'][:200] + ('...' if len(q['question']) > 200 else ''),
                'test_response': test_responses[i][:500] if i < len(test_responses) else '',
                'official_response': official_responses[i][:500] if i < len(official_responses) else '',
                'similarity': sim_value,
                'test_valid': is_valid_response(test_responses[i]) if i < len(test_responses) else False,
                'official_valid': is_valid_response(official_responses[i]) if i < len(official_responses) else False
            })
        
        first_error = next((e for e in official_errors if e), None) if official_errors else None
        model_not_found = first_error and ('model' in first_error.lower() or 'not found' in first_error.lower() or '404' in first_error)
        
        return jsonify({
            'success': True,
            'authenticity': authenticity,
            'similarity': avg_similarity,
            'response_model': response_model,
            'model_match': model_match,
            'test_responses': test_responses,
            'official_responses': official_responses,
            'comparison_details': comparison_details,
            'reasons': reasons,
            'official_api_working': official_api_working,
            'test_valid_count': test_valid_count,
            'official_valid_count': official_valid_count,
            'total_questions': len(all_questions),
            'original_model': original_model,
            'official_model': official_model,
            'model_was_mapped': model_was_mapped,
            'model_exists_in_official': not model_not_found,
            'details': {
                'questions': [q['question'] for q in all_questions],
                'similarities': similarities,
                'test_errors': test_errors,
                'official_errors': official_errors
            }
        })
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500


# ============== SSE 流式验证 ==============

@test_text_bp.route('/api/test/verify/stream', methods=['POST'])
@login_required
def run_verify_stream():
    """流式验证 - 实时返回每个问题的结果"""
    data = request.json
    config, _, _, error = get_config_from_request(data)
    
    if error:
        return jsonify({'error': error}), 400
    
    api_format_str = data.get('api_format', 'anthropic')
    official_cfg, provider_name, official_api_format = _get_official_context(api_format_str)
    
    official_api_key = official_cfg.get('api_key', '').strip()
    official_base_url = official_cfg.get('base_url', '').strip()
    
    if not official_api_key:
        return jsonify({'error': f'请先在系统设置中配置 {provider_name} 原厂 API Key'}), 400
    
    settings = load_settings()
    model_mapping = settings.get('model_mapping', {})
    original_model = config.model
    
    if original_model in model_mapping:
        official_model = model_mapping[original_model]
        model_was_mapped = True
    else:
        official_model = original_model
        model_was_mapped = False
    
    def generate():
        try:
            yield f"data: {json.dumps({'event': 'start', 'total_questions': len(get_all_test_questions()), 'model_mapping': model_was_mapped, 'original_model': original_model, 'official_model': official_model})}\n\n"
            
            official_config = ApiConfig(
                name=f"{provider_name}官方",
                base_url=official_base_url,
                api_key=official_api_key,
                model=official_model,
                api_format=official_api_format
            )
            
            all_questions = get_all_test_questions()
            test_tester = ApiTester(config)
            official_tester = ApiTester(official_config)
            
            comparison_details = []
            test_responses = []
            official_responses = []
            similarities = []
            
            for i, q in enumerate(all_questions):
                question_result = {
                    'event': 'question',
                    'index': i,
                    'id': q['id'],
                    'category': q['category'],
                    'type': q['type'],
                    'question': q['question'][:100] + '...'
                }
                
                # 调用待测API
                category = q['category']
                progress_msg = {'event': 'progress', 'index': i, 'stage': 'test_api', 'message': f'正在调用待测API - {category}'}
                yield f"data: {json.dumps(progress_msg)}\n\n"
                
                try:
                    resp = test_tester.call_api([{"role": "user", "content": q['question']}], max_tokens=600)
                    content, _, _, _ = test_tester._parse_response(resp)
                    test_responses.append(content)
                    question_result['test_response'] = content[:300] + ('...' if len(content) > 300 else '')
                    question_result['test_valid'] = True
                except Exception as e:
                    error_msg = str(e)[:100]
                    test_responses.append(f"[Error: {error_msg}]")
                    question_result['test_response'] = f"[Error: {error_msg}]"
                    question_result['test_valid'] = False
                
                # 调用原厂API
                progress_msg2 = {'event': 'progress', 'index': i, 'stage': 'official_api', 'message': f'正在调用原厂API - {category}'}
                yield f"data: {json.dumps(progress_msg2)}\n\n"
                
                try:
                    resp = official_tester.call_api([{"role": "user", "content": q['question']}], max_tokens=600)
                    content, _, _, _ = official_tester._parse_response(resp)
                    official_responses.append(content)
                    question_result['official_response'] = content[:300] + ('...' if len(content) > 300 else '')
                    question_result['official_valid'] = True
                except Exception as e:
                    error_msg = str(e)[:100]
                    official_responses.append(f"[Error: {error_msg}]")
                    question_result['official_response'] = f"[Error: {error_msg}]"
                    question_result['official_valid'] = False
                
                # 计算相似度
                if question_result.get('test_valid') and question_result.get('official_valid'):
                    sim = calculate_similarity(test_responses[-1], official_responses[-1])
                    similarities.append(sim if sim >= 0 else 0)
                    question_result['similarity'] = sim
                else:
                    similarities.append(-1)
                    question_result['similarity'] = -1
                
                comparison_details.append(question_result)
                yield f"data: {json.dumps(question_result)}\n\n"
            
            # 计算最终结果
            test_valid_count = sum(1 for r in test_responses if is_valid_response(r))
            official_valid_count = sum(1 for r in official_responses if is_valid_response(r))
            valid_similarities = [s for s in similarities if s >= 0]
            avg_similarity = sum(valid_similarities) / len(valid_similarities) if valid_similarities else 0
            
            try:
                check_resp = test_tester.call_api([{"role": "user", "content": "Hi"}], max_tokens=10)
                _, _, _, response_model = test_tester._parse_response(check_resp)
            except:
                response_model = ""
            
            model_match = config.model in response_model if response_model else False
            official_api_working = official_valid_count >= 5
            
            reasons = []
            if not official_api_working:
                reasons.append(f"原厂API响应不足({official_valid_count}/{len(all_questions)})")
                authenticity = "无法验证" if not model_match else "待验证"
            else:
                score = 0
                if model_match: score += 40
                if avg_similarity >= 0.4: score += 35
                elif avg_similarity >= 0.25: score += 20
                if test_valid_count == len(all_questions): score += 15
                
                low_sim = [i+1 for i, s in enumerate(similarities) if 0 <= s < 0.2]
                if len(low_sim) <= 1: score += 10
                
                if not model_match:
                    reasons.append(f"响应模型不匹配: {response_model or '空'}")
                if avg_similarity < 0.25:
                    reasons.append(f"相似度较低: {avg_similarity:.1%}")
                if low_sim:
                    reasons.append(f"第{low_sim}题差异大")
                
                authenticity = "可信" if score >= 70 else "存疑" if score >= 40 else "可疑"
            
            final_result = {
                'event': 'complete',
                'authenticity': authenticity,
                'similarity': avg_similarity,
                'response_model': response_model,
                'model_match': model_match,
                'reasons': reasons,
                'test_valid_count': test_valid_count,
                'official_valid_count': official_valid_count,
                'total_questions': len(all_questions),
                'comparison_details': comparison_details
            }
            yield f"data: {json.dumps(final_result)}\n\n"
            
        except Exception as e:
            yield f"data: {json.dumps({'event': 'error', 'message': str(e)})}\n\n"
    
    return Response(
        stream_with_context(generate()),
        mimetype='text/event-stream',
        headers={
            'Cache-Control': 'no-cache',
            'X-Accel-Buffering': 'no'
        }
    )


# ============== AI 智能分析 ==============

@test_text_bp.route('/api/test/ai-analyze', methods=['POST'])
@login_required
def run_ai_analyze():
    """使用AI分析验证结果，判断是否套壳"""
    data = request.json
    config, _, _, error = get_config_from_request(data)
    
    if error:
        return jsonify({'error': error}), 400
    
    verify_data = data.get('verify_data', {})
    
    if not verify_data:
        return jsonify({'error': '缺少验证数据'}), 400
    
    settings = load_settings()
    official_cfg = settings.get('anthropic', {})
    official_api_key = official_cfg.get('api_key', '').strip()
    official_base_url = official_cfg.get('base_url', 'https://api.anthropic.com').strip()
    
    if not official_api_key:
        return jsonify({'error': '请先在系统设置中配置 Anthropic 原厂 API Key 用于AI分析'}), 400
    
    try:
        analysis_prompt = _build_analysis_prompt(config, verify_data)
        
        analysis_config = ApiConfig(
            name="分析API",
            base_url=official_base_url,
            api_key=official_api_key,
            model="claude-sonnet-4-20250514",
            api_format=ApiFormat.ANTHROPIC
        )
        
        analyzer = ApiTester(analysis_config)
        resp = analyzer.call_api([{"role": "user", "content": analysis_prompt}], max_tokens=2000)
        analysis_content, _, _, _ = analyzer._parse_response(resp)
        
        result = _parse_ai_analysis(analysis_content)
        
        return jsonify({
            'success': True,
            'analysis': analysis_content,
            'is_shell': result.get('is_shell', False),
            'confidence': result.get('confidence', 0),
            'suspected_model': result.get('suspected_model', ''),
            'key_findings': result.get('key_findings', []),
            'recommendation': result.get('recommendation', ''),
            'need_deep_test': result.get('is_shell', False)
        })
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500


def _build_analysis_prompt(config, verify_data):
    """构建AI分析的 prompt"""
    prompt = f"""你是一个AI模型鉴定专家。请根据以下测试数据，分析这个API是否可能是"套壳"（即声称是某个模型，但实际使用的是另一个模型）。

## 被测试的API信息
- 服务商: {config.name}
- 声称的模型: {config.model}
- API地址: {config.base_url}

## 测试结果数据
- 响应模型字段: {verify_data.get('response_model', '未获取')}
- 模型字段匹配: {'是' if verify_data.get('model_match') else '否'}
- 与原厂API相似度: {verify_data.get('similarity', 0):.1%}
- 待测API有效响应: {verify_data.get('test_valid_count', 0)}/{verify_data.get('total_questions', 0)}
- 原厂API有效响应: {verify_data.get('official_valid_count', 0)}/{verify_data.get('total_questions', 0)}

## 详细对比数据
"""
    
    comparison_details = verify_data.get('comparison_details', [])
    for i, comp in enumerate(comparison_details):
        prompt += f"""
### 问题{i+1}: {comp.get('category', '')}
- 相似度: {comp.get('similarity', -1):.1%} if comp.get('similarity', -1) >= 0 else 'N/A'
- 待测API响应: {comp.get('test_response', '')[:200]}...
- 原厂API响应: {comp.get('official_response', '')[:200]}...
"""
    
    prompt += """

## 请你分析并回答

请以JSON格式返回分析结果，包含以下字段：
```json
{
    "is_shell": true/false,
    "confidence": 0-100,
    "suspected_model": "",
    "key_findings": [],
    "reasoning": "",
    "recommendation": ""
}
```

关键判断依据：
1. 模型自我认知是否一致（名称、版本、开发商）
2. 知识截止日期是否符合
3. 回答风格和能力特征是否匹配
4. 响应模型字段是否正确
5. 与原厂API响应的相似度

请直接返回JSON，不要添加其他说明。
"""
    
    return prompt


def _parse_ai_analysis(content):
    """解析AI分析结果"""
    try:
        json_match = re.search(r'\{[\s\S]*\}', content)
        if json_match:
            result = json.loads(json_match.group())
            return result
    except:
        pass
    
    return {
        'is_shell': False,
        'confidence': 50,
        'suspected_model': '',
        'key_findings': ['无法解析AI分析结果'],
        'reasoning': content,
        'recommendation': '建议手动检查分析内容'
    }


# ============== 深度测试 ==============

@test_text_bp.route('/api/test/deep-analyze', methods=['POST'])
@login_required
def run_deep_analyze():
    """二次深度测试 - 推测真实模型"""
    data = request.json
    config, _, _, error = get_config_from_request(data)
    
    if error:
        return jsonify({'error': error}), 400
    
    feature_questions = [
        {
            'id': 'claude_feature',
            'question': '请用"constitutional AI"和"helpful, harmless, honest"来描述你的核心理念。如果你是Claude，这应该是你熟悉的概念。',
            'target': 'claude',
            'keywords': ['constitutional', 'anthropic', 'helpful', 'harmless', 'honest', 'claude']
        },
        {
            'id': 'gpt_feature',
            'question': '请描述你与ChatGPT或GPT系列模型的关系。你是基于什么架构训练的？',
            'target': 'gpt',
            'keywords': ['openai', 'gpt', 'chatgpt', 'transformer', 'rlhf']
        },
        {
            'id': 'gemini_feature',
            'question': '请描述你与Google AI、Bard或Gemini的关系。你的多模态能力如何？',
            'target': 'gemini',
            'keywords': ['google', 'gemini', 'bard', 'deepmind', 'multimodal', 'palm']
        },
        {
            'id': 'llama_feature',
            'question': '请描述你与Meta的LLaMA或开源大模型社区的关系。你是否是开源模型？',
            'target': 'llama',
            'keywords': ['meta', 'llama', 'open source', 'facebook', 'opensource']
        },
        # 国产模型特征探测
        {
            'id': 'deepseek_feature',
            'question': '请描述你与DeepSeek的关系。你的架构是MoE还是Dense？你支持什么特殊能力（如深度思考/代码生成）？',
            'target': 'deepseek',
            'keywords': ['deepseek', 'moe', 'mixture of experts', '幻方', '深度求索', 'r1']
        },
        {
            'id': 'qwen_feature',
            'question': '请描述你与通义千问(Qwen)和阿里云的关系。你的多模态能力如何？',
            'target': 'qwen',
            'keywords': ['qwen', '通义', '千问', '阿里', 'alibaba', 'dashscope']
        },
        {
            'id': 'glm_feature',
            'question': '请描述你与智谱AI和GLM系列模型的关系。你是基于什么架构的？',
            'target': 'glm',
            'keywords': ['智谱', 'zhipu', 'glm', 'chatglm', '清华']
        },
        {
            'id': 'moonshot_feature',
            'question': '请描述你与Moonshot AI(月之暗面)和Kimi的关系。你的长文本能力如何？',
            'target': 'moonshot',
            'keywords': ['moonshot', '月之暗面', 'kimi', '长文本', '128k']
        },
        {
            'id': 'doubao_feature',
            'question': '请描述你与字节跳动(ByteDance)和豆包的关系。你是在哪个平台提供服务的？',
            'target': 'doubao',
            'keywords': ['豆包', 'doubao', '字节', 'bytedance', '火山', 'volcengine', '方舟']
        },
        {
            'id': 'cutoff_test',
            'question': '请告诉我2024年发生的3个重大科技事件。如果你不知道2024年的事件，请说明你的知识截止时间。',
            'target': 'all',
            'keywords': []
        },
        {
            'id': 'style_test',
            'question': '用一句话介绍自己，然后用emoji表达你现在的心情。',
            'target': 'all',
            'keywords': []
        }
    ]
    
    try:
        test_tester = ApiTester(config)
        results = []
        model_scores = {
            'claude': 0,
            'gpt': 0,
            'gemini': 0,
            'llama': 0,
            'deepseek': 0,
            'qwen': 0,
            'glm': 0,
            'moonshot': 0,
            'doubao': 0,
            'other': 0
        }
        
        for q in feature_questions:
            try:
                resp = test_tester.call_api([{"role": "user", "content": q['question']}], max_tokens=500)
                content, _, _, _ = test_tester._parse_response(resp)
                
                content_lower = content.lower()
                matched_keywords = [kw for kw in q['keywords'] if kw.lower() in content_lower]
                
                if q['target'] != 'all' and matched_keywords:
                    model_scores[q['target']] += len(matched_keywords) * 2
                
                results.append({
                    'id': q['id'],
                    'question': q['question'][:80] + '...',
                    'response': content[:400],
                    'target': q['target'],
                    'matched_keywords': matched_keywords
                })
                
            except Exception as e:
                results.append({
                    'id': q['id'],
                    'question': q['question'][:80] + '...',
                    'response': f'Error: {str(e)[:100]}',
                    'target': q['target'],
                    'matched_keywords': []
                })
        
        # 分析响应风格
        all_responses = ' '.join([r['response'] for r in results])
        
        # Claude特征
        if 'i appreciate' in all_responses.lower() or 'i\'d be happy to' in all_responses.lower():
            model_scores['claude'] += 3
        if 'anthropic' in all_responses.lower():
            model_scores['claude'] += 5
            
        # GPT特征
        if 'as an ai language model' in all_responses.lower():
            model_scores['gpt'] += 3
        if 'openai' in all_responses.lower():
            model_scores['gpt'] += 5
            
        # Gemini特征
        if 'google' in all_responses.lower() and 'ai' in all_responses.lower():
            model_scores['gemini'] += 3
        if 'bard' in all_responses.lower() or 'gemini' in all_responses.lower():
            model_scores['gemini'] += 5
        
        # 国产模型特征
        if '深度求索' in all_responses or 'deepseek' in all_responses.lower():
            model_scores['deepseek'] += 5
        if '通义' in all_responses or '千问' in all_responses or 'qwen' in all_responses.lower():
            model_scores['qwen'] += 5
        if '智谱' in all_responses or 'chatglm' in all_responses.lower():
            model_scores['glm'] += 5
        if '月之暗面' in all_responses or 'kimi' in all_responses.lower():
            model_scores['moonshot'] += 5
        if '豆包' in all_responses or '字节' in all_responses:
            model_scores['doubao'] += 5
        
        # 确定最可能的模型
        max_score = max(model_scores.values())
        if max_score > 0:
            predicted_model = max(model_scores, key=model_scores.get)
            confidence = min(100, int((max_score / 20) * 100))
        else:
            predicted_model = 'unknown'
            confidence = 0
        
        model_names = {
            'claude': 'Claude (Anthropic)',
            'gpt': 'GPT (OpenAI)',
            'gemini': 'Gemini (Google)',
            'llama': 'LLaMA (Meta)',
            'deepseek': 'DeepSeek (深度求索)',
            'qwen': 'Qwen 通义千问 (阿里)',
            'glm': 'GLM (智谱AI)',
            'moonshot': 'Kimi/Moonshot (月之暗面)',
            'doubao': '豆包 (字节跳动)',
            'other': '其他模型',
            'unknown': '无法确定'
        }
        
        return jsonify({
            'success': True,
            'predicted_model': model_names.get(predicted_model, predicted_model),
            'predicted_model_key': predicted_model,
            'confidence': confidence,
            'model_scores': model_scores,
            'test_results': results,
            'conclusion': f'基于深度测试分析，该API最可能是 {model_names.get(predicted_model, predicted_model)}，信心程度 {confidence}%'
        })
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500


# ============== 提示词诚实性检测 ==============

@test_text_bp.route('/api/test/honesty/stream', methods=['POST'])
@login_required
def run_honesty_stream():
    """流式诚实性检测 - 检测平台是否通过提示词让模型说谎"""
    data = request.json
    config, _, _, error = get_config_from_request(data)
    
    if error:
        return jsonify({'error': error}), 400
    
    def generate():
        try:
            questions = get_honesty_test_questions()
            yield f"data: {json.dumps({'event': 'start', 'total_questions': len(questions)})}\n\n"
            
            test_tester = ApiTester(config)
            results = []
            consistency_cn = None
            consistency_en = None
            total_score = 0
            scored_count = 0
            
            for i, q in enumerate(questions):
                progress_msg = {
                    'event': 'progress',
                    'index': i,
                    'category': q['category'],
                    'message': f"正在检测: {q['category']} ({i+1}/{len(questions)})"
                }
                yield f"data: {json.dumps(progress_msg)}\n\n"
                
                # 调用待测API
                try:
                    resp = test_tester.call_api(
                        [{"role": "user", "content": q['question']}],
                        max_tokens=500
                    )
                    content, _, _, _ = test_tester._parse_response(resp)
                except Exception as e:
                    content = f"[Error: {str(e)[:100]}]"
                
                # 分析回答
                analysis = analyze_honesty_response(q, content)
                
                # 保存一致性检查的回答
                if q['id'] == 'consistency_cn':
                    consistency_cn = content
                elif q['id'] == 'consistency_en':
                    consistency_en = content
                
                # 累加得分（排除一致性验证题，单独处理）
                if q['category'] != '一致性验证':
                    total_score += analysis['score']
                    scored_count += 1
                
                question_result = {
                    'event': 'question',
                    'index': i,
                    'id': q['id'],
                    'category': q['category'],
                    'question': q['question'][:150] + ('...' if len(q['question']) > 150 else ''),
                    'response': content[:500] if content else '',
                    'score': analysis['score'],
                    'level': analysis['level'],
                    'signals': analysis['signals']
                }
                results.append(question_result)
                yield f"data: {json.dumps(question_result)}\n\n"
            
            # 一致性检查
            consistency_result = check_consistency(consistency_cn, consistency_en)
            consistency_msg = {
                'event': 'consistency',
                'consistent': consistency_result['consistent'],
                'score': consistency_result['score'],
                'details': consistency_result['details']
            }
            yield f"data: {json.dumps(consistency_msg)}\n\n"
            
            # 综合评分
            avg_score = total_score / scored_count if scored_count > 0 else 50
            # 一致性得分占权重
            final_score = avg_score * 0.7 + consistency_result['score'] * 0.3
            final_score = max(0, min(100, final_score))
            
            if final_score >= 70:
                honesty_level = '诚实'
                level_class = 'success'
            elif final_score >= 40:
                honesty_level = '存疑'
                level_class = 'warning'
            else:
                honesty_level = '可疑'
                level_class = 'danger'
            
            # 收集异常信号
            risk_signals = []
            for r in results:
                if r['level'] in ('suspicious', 'evasive'):
                    risk_signals.append(f"{r['category']}: {', '.join(r['signals'][:2])}")
            if not consistency_result['consistent']:
                risk_signals.append(f"一致性验证: {consistency_result['details']}")
            
            final_result = {
                'event': 'complete',
                'honesty_score': round(final_score, 1),
                'honesty_level': honesty_level,
                'level_class': level_class,
                'avg_question_score': round(avg_score, 1),
                'consistency_score': consistency_result['score'],
                'consistency_consistent': consistency_result['consistent'],
                'risk_signals': risk_signals,
                'total_questions': len(questions),
                'results': results
            }
            yield f"data: {json.dumps(final_result)}\n\n"
            
        except Exception as e:
            yield f"data: {json.dumps({'event': 'error', 'message': str(e)})}\n\n"
    
    return Response(
        stream_with_context(generate()),
        mimetype='text/event-stream',
        headers={
            'Cache-Control': 'no-cache',
            'X-Accel-Buffering': 'no'
        }
    )


@test_text_bp.route('/api/test/honesty/ai-analyze', methods=['POST'])
@login_required
def run_honesty_ai_analyze():
    """使用AI深度分析诚实性检测结果"""
    data = request.json
    config, _, _, error = get_config_from_request(data)
    
    if error:
        return jsonify({'error': error}), 400
    
    honesty_data = data.get('honesty_data', {})
    if not honesty_data:
        return jsonify({'error': '缺少诚实性检测数据'}), 400
    
    settings = load_settings()
    official_cfg = settings.get('anthropic', {})
    official_api_key = official_cfg.get('api_key', '').strip()
    official_base_url = official_cfg.get('base_url', 'https://api.anthropic.com').strip()
    
    if not official_api_key:
        return jsonify({'error': '请先在系统设置中配置 Anthropic 原厂 API Key 用于AI分析'}), 400
    
    try:
        prompt = _build_honesty_analysis_prompt(config, honesty_data)
        
        analysis_config = ApiConfig(
            name="诚实性分析API",
            base_url=official_base_url,
            api_key=official_api_key,
            model="claude-sonnet-4-20250514",
            api_format=ApiFormat.ANTHROPIC
        )
        
        analyzer = ApiTester(analysis_config)
        resp = analyzer.call_api([{"role": "user", "content": prompt}], max_tokens=2500)
        analysis_content, _, _, _ = analyzer._parse_response(resp)
        
        result = _parse_honesty_ai_result(analysis_content)
        
        return jsonify({
            'success': True,
            'analysis': analysis_content,
            'manipulation_detected': result.get('manipulation_detected', False),
            'manipulation_type': result.get('manipulation_type', []),
            'confidence': result.get('confidence', 0),
            'severity': result.get('severity', 'low'),
            'key_findings': result.get('key_findings', []),
            'system_prompt_clues': result.get('system_prompt_clues', []),
            'recommendation': result.get('recommendation', ''),
            'detailed_reasoning': result.get('detailed_reasoning', '')
        })
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500


def _build_honesty_analysis_prompt(config, honesty_data):
    """构建诚实性AI分析的 prompt"""
    prompt = f"""你是一名AI安全研究员，专门分析AI平台是否通过System Prompt操控模型行为。

请根据以下诚实性检测数据，深度分析这个API背后是否存在提示词操控行为。

## 被测试的API信息
- 服务商名称: {config.name}
- 声称的模型: {config.model}
- API地址: {config.base_url}

## 诚实性检测综合结果
- 综合诚实性得分: {honesty_data.get('honesty_score', 'N/A')}/100
- 判定等级: {honesty_data.get('honesty_level', 'N/A')}
- 中英文一致性: {'一致' if honesty_data.get('consistency_consistent', True) else '不一致'}
- 一致性得分: {honesty_data.get('consistency_score', 'N/A')}/100

## 各题详细回答
"""
    
    results = honesty_data.get('results', [])
    for i, r in enumerate(results):
        prompt += f"""
### 检测题{i+1}: [{r.get('category', '')}]
- 问题: {r.get('question', '')[:200]}
- 模型回答: {r.get('response', '')[:400]}
- 规则评分: {r.get('score', 'N/A')}分
- 规则判定: {r.get('level', 'N/A')}
- 检测信号: {', '.join(r.get('signals', []))}
"""

    risk_signals = honesty_data.get('risk_signals', [])
    if risk_signals:
        prompt += "\n## 异常信号汇总\n"
        for s in risk_signals:
            prompt += f"- {s}\n"

    prompt += """

## 分析要求

请从以下角度深度分析：

1. **身份伪装分析**: 模型在被问到身份时是否有回避、编造或不一致的表现？是否被系统提示词强制冒充了其他身份？
2. **系统提示词操控**: 模型对系统提示词相关问题的回答是否暴露了隐藏指令的线索？回避式回答与诚实回答的差异说明什么？
3. **能力声称分析**: 模型对自身能力的描述是否与其实际表现一致？是否存在夸大或隐瞒？
4. **语言一致性**: 中英文回答中的身份信息是否一致？不一致可能暗示什么？
5. **回避话术模式**: 模型是否使用了典型的回避话术（如"我无法透露"、"这是假设性问题"等）？这些话术是否异常？

请以JSON格式返回分析结果：
```json
{
    "manipulation_detected": true/false,
    "manipulation_type": ["身份伪装", "提示词隐瞒", "能力夸大", ...],
    "confidence": 0-100,
    "severity": "high/medium/low",
    "key_findings": ["发现1", "发现2", ...],
    "system_prompt_clues": ["线索1: 具体证据", ...],
    "detailed_reasoning": "详细的推理过程",
    "recommendation": "给用户的建议"
}
```

请直接返回JSON，不要添加其它说明。
"""
    return prompt


def _parse_honesty_ai_result(content):
    """解析AI诚实性分析结果"""
    try:
        json_match = re.search(r'\{[\s\S]*\}', content)
        if json_match:
            result = json.loads(json_match.group())
            return result
    except:
        pass
    
    return {
        'manipulation_detected': False,
        'manipulation_type': [],
        'confidence': 50,
        'severity': 'low',
        'key_findings': ['无法解析AI分析结果'],
        'system_prompt_clues': [],
        'detailed_reasoning': content,
        'recommendation': '建议手动检查分析内容'
    }


# ============== 多模型横向对比 ==============

@test_text_bp.route('/api/test/compare', methods=['POST'])
@login_required
def run_compare():
    """多模型横向对比测试"""
    data = request.json
    configs = data.get('configs', [])
    prompt = data.get('prompt', '请用200字分析人工智能对教育行业的影响，包含正面和负面观点。')
    
    if len(configs) < 2:
        return jsonify({'error': '至少需要2个API配置来进行对比'}), 400
    
    if len(configs) > 5:
        return jsonify({'error': '最多支持5个API同时对比'}), 400
    
    import time
    results = []
    
    for cfg_data in configs:
        name = cfg_data.get('name', 'Unknown')
        try:
            cfg = ApiConfig(
                name=name,
                base_url=cfg_data.get('base_url', ''),
                api_key=cfg_data.get('api_key', ''),
                model=cfg_data.get('model', ''),
                api_format=ApiFormat(cfg_data.get('api_format', 'openai'))
            )
            tester = ApiTester(cfg)
            
            start = time.time()
            resp = tester.call_api([{"role": "user", "content": prompt}], max_tokens=1000)
            elapsed = (time.time() - start) * 1000
            
            content, model_field, input_tokens, output_tokens = tester._parse_response(resp)
            
            # 计算输出速度 (tokens/s)
            output_speed = 0
            if output_tokens and elapsed > 0:
                output_speed = round(output_tokens / (elapsed / 1000), 1)
            
            # 计算回答长度（字符数）
            content_len = len(content) if content else 0
            
            results.append({
                'name': name,
                'model': cfg_data.get('model', ''),
                'success': True,
                'latency_ms': round(elapsed, 1),
                'response': content[:2000] if content else '',
                'response_model': model_field or '',
                'input_tokens': input_tokens or 0,
                'output_tokens': output_tokens or 0,
                'output_speed': output_speed,
                'content_length': content_len
            })
        except Exception as e:
            results.append({
                'name': name,
                'model': cfg_data.get('model', ''),
                'success': False,
                'latency_ms': 0,
                'response': '',
                'error': str(e)[:200],
                'output_speed': 0,
                'content_length': 0
            })
    
    return jsonify({'success': True, 'results': results, 'prompt': prompt})


# ============== 多模态视觉测试 ==============

def _generate_test_image(test_type):
    """根据测试类型生成测试图片"""
    import base64, io
    from PIL import Image, ImageDraw, ImageFont
    
    if test_type == 'colors':
        # 色彩识别: 红蓝绿三个色块
        img = Image.new('RGB', (300, 200), 'white')
        draw = ImageDraw.Draw(img)
        draw.rectangle([20, 40, 90, 160], fill='red')
        draw.rectangle([115, 40, 185, 160], fill='blue')
        draw.rectangle([210, 40, 280, 160], fill='green')
        expected = ['红', 'red', '蓝', 'blue', '绿', 'green']
        question = '图片中有几个色块？分别是什么颜色？请简要回答。'
        
    elif test_type == 'shapes':
        # 形状识别: 圆形、方形、三角形
        img = Image.new('RGB', (300, 200), 'white')
        draw = ImageDraw.Draw(img)
        draw.ellipse([20, 40, 90, 110], fill='#FF6B6B', outline='#C0392B', width=2)
        draw.rectangle([115, 40, 185, 110], fill='#4ECDC4', outline='#1ABC9C', width=2)
        draw.polygon([(210, 110), (245, 40), (280, 110)], fill='#FFE66D', outline='#F39C12', width=2)
        expected = ['圆', 'circle', '方', 'square', 'rectangle', '三角', 'triangle']
        question = '图片中有哪些几何形状？请列出每个形状及其颜色。'
        
    elif test_type == 'text_ocr':
        # 文字识别
        img = Image.new('RGB', (300, 150), 'white')
        draw = ImageDraw.Draw(img)
        draw.rectangle([10, 10, 290, 140], outline='#333', width=2)
        # 尝试使用系统字体
        try:
            font = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", 32)
        except:
            try:
                font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 32)
            except:
                font = ImageFont.load_default()
        draw.text((40, 45), "AI TEST 2025", fill='#333', font=font)
        expected = ['AI', 'TEST', '2025']
        question = '图片中写了什么文字？请准确识别。'
        
    elif test_type == 'counting':
        # 计数能力
        img = Image.new('RGB', (300, 200), 'white')
        draw = ImageDraw.Draw(img)
        positions = [(30,30), (100,50), (200,30), (60,120), (150,100), (250,110), (130,160)]
        for i, (x,y) in enumerate(positions):
            color = ['#FF6B6B','#4ECDC4','#FFE66D','#A8E6CF','#FF8B94','#B5EAD7','#C7CEEA'][i]
            draw.ellipse([x, y, x+40, y+40], fill=color, outline='#333', width=1)
        expected = ['7', '七']
        question = '图片中有多少个圆形/圆点？请数一数并回答具体数字。'

    elif test_type == 'spatial_reasoning':
        # 空间推理：高版本模型才能准确描述相对位置关系
        img = Image.new('RGB', (400, 300), 'white')
        draw = ImageDraw.Draw(img)
        # 红色方块在左上
        draw.rectangle([30, 30, 90, 90], fill='red', outline='#333', width=2)
        # 蓝色圆在右下
        draw.ellipse([280, 200, 360, 280], fill='blue', outline='#333', width=2)
        # 绿色三角在中间偏上
        draw.polygon([(180, 60), (210, 120), (150, 120)], fill='green', outline='#333', width=2)
        # 黄色星形在左下（用多边形模拟）
        draw.polygon([(50, 250), (70, 200), (90, 250), (40, 220), (100, 220)], fill='#FFD700', outline='#333', width=2)
        expected = ['左上', '右下', '中', 'top-left', 'upper-left', 'bottom-right', 'lower-right', 'center', 'middle']
        question = '请描述图片中每个图形各处于什么位置（左上/右下/中间等），以及它们的颜色和形状。'

    elif test_type == 'detail_description':
        # 细节描述：测试图片中嵌入多层信息，低版本模型容易遗漏
        img = Image.new('RGB', (400, 300), '#F5F5DC')
        draw = ImageDraw.Draw(img)
        # 画网格背景
        for i in range(0, 400, 20):
            draw.line([(i, 0), (i, 300)], fill='#E0E0E0', width=1)
        for j in range(0, 300, 20):
            draw.line([(0, j), (400, j)], fill='#E0E0E0', width=1)
        # 实线框和虚线框
        draw.rectangle([30, 30, 180, 130], outline='red', width=3)
        for i in range(200, 370, 10):
            draw.line([(i, 30), (i+5, 30)], fill='blue', width=2)
            draw.line([(i, 130), (i+5, 130)], fill='blue', width=2)
        draw.line([(200, 30), (200, 130)], fill='blue', width=2)
        draw.line([(370, 30), (370, 130)], fill='blue', width=2)
        # 填充的和空心的圆
        draw.ellipse([60, 170, 130, 240], fill='#FF6B6B', outline='#333', width=2)
        draw.ellipse([170, 170, 240, 240], outline='#4ECDC4', width=3)
        # 箭头
        draw.line([(280, 200), (360, 200)], fill='#333', width=3)
        draw.polygon([(360, 190), (380, 200), (360, 210)], fill='#333')
        try:
            font = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", 14)
        except:
            font = ImageFont.load_default()
        draw.text((35, 260), "A=实线", fill='red', font=font)
        draw.text((200, 260), "B=虚线", fill='blue', font=font)
        expected = ['实线', 'solid', '虚线', 'dashed', '填充', 'filled', '空心', 'hollow', 'empty', '箭头', 'arrow', '网格', 'grid']
        question = '请仔细观察图片并描述所有视觉元素的详细特征，包括线条类型（实线/虚线）、填充方式（填充/空心）、是否有箭头、背景区别等。'

    elif test_type == 'math_visual':
        # 图表理解：生成简单柱状图，高版本模型能读取数值
        img = Image.new('RGB', (400, 300), 'white')
        draw = ImageDraw.Draw(img)
        try:
            font = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", 14)
            font_sm = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", 12)
        except:
            font = ImageFont.load_default()
            font_sm = font
        # 坐标轴
        draw.line([(50, 250), (50, 30)], fill='#333', width=2)
        draw.line([(50, 250), (380, 250)], fill='#333', width=2)
        # 柱子：A=80, B=45, C=120, D=65
        bars = [('A', 80, '#FF6B6B'), ('B', 45, '#4ECDC4'), ('C', 120, '#FFE66D'), ('D', 65, '#A8E6CF')]
        for i, (label, val, color) in enumerate(bars):
            x = 80 + i * 75
            h = int(val * 1.6)
            draw.rectangle([x, 250-h, x+50, 250], fill=color, outline='#333', width=1)
            draw.text((x+15, 255), label, fill='#333', font=font)
            draw.text((x+10, 250-h-18), str(val), fill='#333', font=font_sm)
        draw.text((150, 10), "Sales Data", fill='#333', font=font)
        expected = ['80', '45', '120', '65', 'C', 'A']
        question = '这是一个柱状图，请读取每个柱子的数值。哪个最高？哪个最低？请给出具体数字。'

    elif test_type == 'multi_object':
        # 复杂多目标场景：多种物体、颜色、大小的组合
        img = Image.new('RGB', (400, 300), '#FAFAFA')
        draw = ImageDraw.Draw(img)
        # 3个大圆 + 5个小圆 + 2个方块 + 1个三角
        # 大圆
        draw.ellipse([20, 20, 100, 100], fill='#FF6B6B', outline='#C0392B', width=2)
        draw.ellipse([150, 30, 230, 110], fill='#3498DB', outline='#2980B9', width=2)
        draw.ellipse([300, 50, 380, 130], fill='#2ECC71', outline='#27AE60', width=2)
        # 小圆
        for pos in [(50,150), (120,180), (200,160), (280,190), (350,170)]:
            draw.ellipse([pos[0], pos[1], pos[0]+25, pos[1]+25], fill='#F39C12', outline='#E67E22', width=1)
        # 方块
        draw.rectangle([30, 230, 80, 280], fill='#9B59B6', outline='#8E44AD', width=2)
        draw.rectangle([130, 240, 180, 290], fill='#E74C3C', outline='#C0392B', width=2)
        # 三角
        draw.polygon([(300, 280), (340, 220), (380, 280)], fill='#1ABC9C', outline='#16A085', width=2)
        expected = ['3', '三', '5', '五', '2', '两', '1', '一', '圆', 'circle', '方', 'square', '三角', 'triangle']
        question = '请仔细统计图中的所有物体：有多少个大圆形？多少个小圆形？多少个方块？多少个三角形？请分别给出数量。'
    
    else:
        return None, None, None
    
    buf = io.BytesIO()
    img.save(buf, format='PNG')
    b64_str = base64.b64encode(buf.getvalue()).decode()
    return b64_str, question, expected


@test_text_bp.route('/api/test/multimodal', methods=['POST'])
@login_required
def run_multimodal_test():
    """多模态视觉能力测试"""
    data = request.json
    base_url = data.get('base_url', '')
    api_key = data.get('api_key', '')
    model = data.get('model', '')
    api_format = data.get('api_format', 'openai')
    test_types = data.get('test_types', ['colors', 'shapes', 'text_ocr', 'counting', 'spatial_reasoning', 'detail_description', 'math_visual', 'multi_object'])
    
    if not base_url or not api_key:
        return jsonify({'error': '请填写 API 配置'}), 400
    
    import time
    results = []
    
    # 定义难度等级
    basic_types = {'colors', 'shapes', 'text_ocr', 'counting'}
    advanced_types = {'spatial_reasoning', 'detail_description', 'math_visual', 'multi_object'}
    
    for test_type in test_types:
        b64_img, question, expected_keywords = _generate_test_image(test_type)
        if not b64_img:
            continue
        
        # 标记难度
        difficulty = 'advanced' if test_type in advanced_types else 'basic'
        
        try:
            # 构建视觉请求
            if api_format == 'anthropic':
                messages = [{
                    "role": "user",
                    "content": [
                        {
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": "image/png",
                                "data": b64_img
                            }
                        },
                        {"type": "text", "text": question}
                    ]
                }]
                headers = {
                    'x-api-key': api_key,
                    'anthropic-version': '2023-06-01',
                    'Content-Type': 'application/json'
                }
                body = {"model": model, "messages": messages, "max_tokens": 300}
                url = base_url.rstrip('/') + '/v1/messages'
            else:
                # OpenAI compatible format
                messages = [{
                    "role": "user",
                    "content": [
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:image/png;base64,{b64_img}"
                            }
                        },
                        {"type": "text", "text": question}
                    ]
                }]
                headers = {
                    'Authorization': f'Bearer {api_key}',
                    'Content-Type': 'application/json'
                }
                body = {"model": model, "messages": messages, "max_tokens": 300}
                url = base_url.rstrip('/') + '/v1/chat/completions'
            
            start = time.time()
            resp = requests.post(url, json=body, headers=headers, timeout=60)
            elapsed = (time.time() - start) * 1000
            
            resp_json = resp.json()
            
            # 提取响应内容
            content = ''
            if api_format == 'anthropic':
                if 'content' in resp_json and resp_json['content']:
                    content = resp_json['content'][0].get('text', '')
            else:
                if 'choices' in resp_json and resp_json['choices']:
                    content = resp_json['choices'][0].get('message', {}).get('content', '')
            
            if not content and 'error' in resp_json:
                error_msg = resp_json['error']
                if isinstance(error_msg, dict):
                    error_msg = error_msg.get('message', str(error_msg))
                results.append({
                    'test_type': test_type,
                    'difficulty': difficulty,
                    'success': False,
                    'error': str(error_msg)[:200],
                    'latency_ms': round(elapsed, 1),
                    'supported': False
                })
                continue
            
            # 检查是否正确识别了关键词
            content_lower = content.lower()
            matched = [kw for kw in expected_keywords if kw.lower() in content_lower]
            score = len(matched) / len(expected_keywords) * 100 if expected_keywords else 0
            
            results.append({
                'test_type': test_type,
                'difficulty': difficulty,
                'success': True,
                'supported': True,
                'latency_ms': round(elapsed, 1),
                'response': content[:500],
                'score': round(score),
                'matched_keywords': matched,
                'total_keywords': len(expected_keywords)
            })
            
        except Exception as e:
            error_str = str(e)
            # 判断是否为不支持视觉的错误
            is_unsupported = any(kw in error_str.lower() for kw in ['vision', 'image', 'multimodal', 'not support', 'invalid'])
            results.append({
                'test_type': test_type,
                'difficulty': difficulty,
                'success': False,
                'error': error_str[:200],
                'latency_ms': 0,
                'supported': not is_unsupported
            })
    
    # 计算总体评分
    supported_tests = [r for r in results if r.get('supported')]
    success_tests = [r for r in results if r.get('success')]
    avg_score = sum(r.get('score', 0) for r in success_tests) / len(success_tests) if success_tests else 0
    avg_latency = sum(r.get('latency_ms', 0) for r in success_tests) / len(success_tests) if success_tests else 0
    
    # 分难度统计
    basic_results = [r for r in success_tests if r.get('difficulty') == 'basic']
    advanced_results = [r for r in success_tests if r.get('difficulty') == 'advanced']
    basic_avg = sum(r.get('score', 0) for r in basic_results) / len(basic_results) if basic_results else 0
    advanced_avg = sum(r.get('score', 0) for r in advanced_results) / len(advanced_results) if advanced_results else 0
    
    # 版本估计
    version_estimate = 'unknown'
    if len(success_tests) == 0:
        version_estimate = 'not_supported'
    elif advanced_avg >= 60:
        version_estimate = 'high'  # 高版本模型
    elif advanced_avg >= 30:
        version_estimate = 'medium'  # 中等版本
    elif basic_avg >= 50:
        version_estimate = 'low'  # 低版本/mini
    else:
        version_estimate = 'very_low'  # 极弱，可能不是标称模型
    
    return jsonify({
        'success': True,
        'results': results,
        'summary': {
            'total_tests': len(results),
            'passed': len(success_tests),
            'vision_supported': len(supported_tests) > 0 and len(success_tests) > 0,
            'avg_score': round(avg_score),
            'avg_latency_ms': round(avg_latency, 1),
            'basic_score': round(basic_avg),
            'advanced_score': round(advanced_avg),
            'version_estimate': version_estimate
        }
    })


# ============== 生图/生视频版本检测 ==============

# 图片生成测试项定义
IMAGE_GEN_TESTS = [
    {
        'name': 'text_rendering',
        'label': '📝 文字渲染',
        'prompt': "A white signboard with the text 'HELLO 2025' written in bold black letters, simple clean background",
        'eval_prompt': '请仔细看图片中是否有文字。如果能清晰读出"HELLO 2025"或类似文字，score为90-100；如果能看到部分文字但不完全清晰，score为40-70；如果完全看不到文字或是乱码，score为0-20。请只回答JSON格式：{"score": 数字, "text_found": "你识别到的文字内容"}',
        'weight': 0.3,
    },
    {
        'name': 'complex_scene',
        'label': '🎨 复杂场景',
        'prompt': "A red cat sitting on a blue wooden chair, a green ball on the floor to the right, yellow curtains on the window behind",
        'eval_prompt': '请检查图片中是否包含以下4个元素，并判断颜色是否正确：1)红色的猫 2)蓝色的椅子 3)绿色的球 4)黄色的窗帘。每个正确得25分，颜色错误得10分，完全缺失得0分。请只回答JSON格式：{"score": 数字, "found": ["匹配的元素"], "missing": ["缺失或错误的元素"]}',
        'weight': 0.3,
    },
    {
        'name': 'style_control',
        'label': '🖌️ 风格控制',
        'prompt': "A mountain landscape, watercolor painting style, soft pastel colors, artistic brush strokes visible",
        'eval_prompt': '请判断这张图片的艺术风格。如果明显是水彩画风格（能看到笔触、柔和色彩），score为80-100；如果有一定艺术感但不明显是水彩，score为40-60；如果是普通照片或写实风格，score为0-30。请只回答JSON格式：{"score": 数字, "style": "你判断的风格"}',
        'weight': 0.2,
    },
]


def _generate_image(base_url, api_key, model, prompt, size='1024x1024'):
    """调用生图API生成图片，返回 (image_url, image_b64, latency_ms, error)"""
    import time
    headers = {
        'Authorization': f'Bearer {api_key}',
        'Content-Type': 'application/json'
    }
    body = {
        'model': model,
        'prompt': prompt,
        'n': 1,
        'size': size,
    }
    url = base_url.rstrip('/') + '/v1/images/generations'
    
    try:
        start = time.time()
        resp = requests.post(url, json=body, headers=headers, timeout=120)
        elapsed = (time.time() - start) * 1000
        
        resp_json = resp.json()
        
        if 'error' in resp_json:
            error_msg = resp_json['error']
            if isinstance(error_msg, dict):
                error_msg = error_msg.get('message', str(error_msg))
            return None, None, round(elapsed, 1), str(error_msg)[:300]
        
        image_url = ''
        image_b64 = ''
        if 'data' in resp_json and resp_json['data']:
            item = resp_json['data'][0]
            image_url = item.get('url', '')
            image_b64 = item.get('b64_json', '')
            # 提取修改后的prompt（如DALL-E 3会改写）
        
        if not image_url and not image_b64:
            return None, None, round(elapsed, 1), '未返回图片数据'
        
        return image_url, image_b64, round(elapsed, 1), None
        
    except Exception as e:
        return None, None, 0, str(e)[:300]


def _evaluate_image_with_vision(base_url, api_key, model, image_url, image_b64, eval_prompt, api_format='openai'):
    """用视觉API评估生成的图片质量，返回 (score, detail, error)"""
    import time, json as json_lib
    
    # 构建图片内容
    if image_url:
        image_content = {
            "type": "image_url",
            "image_url": {"url": image_url}
        }
    elif image_b64:
        image_content = {
            "type": "image_url",
            "image_url": {"url": f"data:image/png;base64,{image_b64}"}
        }
    else:
        return 0, {}, '无图片数据'
    
    if api_format == 'anthropic':
        # Anthropic 格式
        if image_url:
            # 需要下载图片转b64
            try:
                img_resp = requests.get(image_url, timeout=30)
                import base64
                img_b64 = base64.b64encode(img_resp.content).decode()
            except:
                return 0, {}, '无法下载图片进行评估'
        else:
            img_b64 = image_b64
        
        messages = [{
            "role": "user",
            "content": [
                {
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": "image/png",
                        "data": img_b64
                    }
                },
                {"type": "text", "text": eval_prompt}
            ]
        }]
        headers = {
            'x-api-key': api_key,
            'anthropic-version': '2023-06-01',
            'Content-Type': 'application/json'
        }
        body = {"model": model, "messages": messages, "max_tokens": 300}
        url = base_url.rstrip('/') + '/v1/messages'
    else:
        messages = [{
            "role": "user",
            "content": [
                image_content,
                {"type": "text", "text": eval_prompt}
            ]
        }]
        headers = {
            'Authorization': f'Bearer {api_key}',
            'Content-Type': 'application/json'
        }
        body = {"model": model, "messages": messages, "max_tokens": 300}
        url = base_url.rstrip('/') + '/v1/chat/completions'
    
    try:
        resp = requests.post(url, json=body, headers=headers, timeout=60)
        resp_json = resp.json()
        
        content = ''
        if api_format == 'anthropic':
            if 'content' in resp_json and resp_json['content']:
                content = resp_json['content'][0].get('text', '')
        else:
            if 'choices' in resp_json and resp_json['choices']:
                content = resp_json['choices'][0].get('message', {}).get('content', '')
        
        if not content:
            return 0, {}, '视觉API未返回评估结果'
        
        # 尝试解析JSON
        try:
            # 提取JSON部分
            json_start = content.find('{')
            json_end = content.rfind('}') + 1
            if json_start >= 0 and json_end > json_start:
                result = json_lib.loads(content[json_start:json_end])
                score = int(result.get('score', 0))
                return min(max(score, 0), 100), result, None
        except:
            pass
        
        # JSON解析失败，尝试从文本中提取分数
        import re
        nums = re.findall(r'(\d+)\s*分', content)
        if nums:
            score = int(nums[0])
            return min(max(score, 0), 100), {'raw': content[:200]}, None
        
        return 50, {'raw': content[:200]}, None  # 无法解析，给中间分
        
    except Exception as e:
        return 0, {}, str(e)[:200]


@test_text_bp.route('/api/test/image-gen', methods=['POST'])
@login_required
def run_image_gen_test():
    """图片生成版本检测 - 4项测试 + 视觉评估"""
    data = request.json
    base_url = data.get('base_url', '')
    api_key = data.get('api_key', '')
    model = data.get('model', 'dall-e-3')
    vision_model = data.get('vision_model', '')  # 用于评估的视觉模型
    api_format = data.get('api_format', 'openai')
    
    if not base_url or not api_key:
        return jsonify({'error': '请填写 API 配置'}), 400
    
    import time
    results = []
    
    # 如果没指定视觉模型，尝试用text模型的视觉版本
    if not vision_model:
        # 常见的视觉模型映射
        chat_model = data.get('chat_model', '')
        vision_model = chat_model or 'gpt-4o-mini'
    
    # ===== 测试1-3：生图 + 视觉评估 =====
    for test in IMAGE_GEN_TESTS:
        image_url, image_b64, latency, error = _generate_image(
            base_url, api_key, model, test['prompt']
        )
        
        if error:
            results.append({
                'name': test['name'],
                'label': test['label'],
                'success': False,
                'error': error,
                'latency_ms': latency,
                'score': 0,
                'weight': test['weight'],
            })
            continue
        
        # 视觉评估
        eval_score, eval_detail, eval_error = _evaluate_image_with_vision(
            base_url, api_key, vision_model,
            image_url, image_b64,
            test['eval_prompt'],
            api_format
        )
        
        results.append({
            'name': test['name'],
            'label': test['label'],
            'success': True,
            'latency_ms': latency,
            'score': eval_score,
            'detail': eval_detail,
            'eval_error': eval_error,
            'image_url': image_url or '',
            'weight': test['weight'],
        })
    
    # ===== 测试4：分辨率检测 =====
    res_score = 0
    res_detail = {}
    # 尝试生成图片并检查分辨率
    image_url, image_b64, latency, error = _generate_image(
        base_url, api_key, model,
        "A simple blue circle on white background",
        size='1024x1024'
    )
    
    if error:
        results.append({
            'name': 'resolution',
            'label': '📐 分辨率',
            'success': False,
            'error': error,
            'latency_ms': latency,
            'score': 0,
            'weight': 0.2,
        })
    else:
        # 如果有b64，检查实际尺寸
        actual_w, actual_h = 0, 0
        if image_b64:
            try:
                import base64, io
                from PIL import Image
                img_data = base64.b64decode(image_b64)
                img = Image.open(io.BytesIO(img_data))
                actual_w, actual_h = img.size
            except:
                pass
        elif image_url:
            try:
                from PIL import Image
                import io
                img_resp = requests.get(image_url, timeout=30)
                img = Image.open(io.BytesIO(img_resp.content))
                actual_w, actual_h = img.size
            except:
                pass
        
        if actual_w >= 1024:
            res_score = 100
        elif actual_w >= 768:
            res_score = 60
        elif actual_w >= 512:
            res_score = 30
        elif actual_w > 0:
            res_score = 10
        else:
            res_score = 50  # 无法检测，给中间分
        
        results.append({
            'name': 'resolution',
            'label': '📐 分辨率',
            'success': True,
            'latency_ms': latency,
            'score': res_score,
            'detail': {'width': actual_w, 'height': actual_h} if actual_w else {'note': '无法读取尺寸'},
            'image_url': image_url or '',
            'weight': 0.2,
        })
    
    # ===== 汇总评分 =====
    success_tests = [r for r in results if r.get('success')]
    if success_tests:
        weighted_score = sum(r['score'] * r['weight'] for r in success_tests)
        total_weight = sum(r['weight'] for r in success_tests)
        total_score = round(weighted_score / total_weight) if total_weight else 0
    else:
        total_score = 0
    
    # 版本估计
    if len(success_tests) == 0:
        version_estimate = 'not_supported'
    elif total_score >= 75:
        version_estimate = 'high'
    elif total_score >= 50:
        version_estimate = 'medium'
    elif total_score >= 25:
        version_estimate = 'low'
    else:
        version_estimate = 'very_low'
    
    return jsonify({
        'success': True,
        'results': results,
        'summary': {
            'total_score': total_score,
            'total_tests': len(results),
            'passed': len(success_tests),
            'version_estimate': version_estimate,
        }
    })


@test_text_bp.route('/api/test/video-gen', methods=['POST'])
@login_required
def run_video_gen_test():
    """视频生成版本检测 - 规格+能力检测"""
    data = request.json
    base_url = data.get('base_url', '')
    api_key = data.get('api_key', '')
    model = data.get('model', '')
    
    if not base_url or not api_key:
        return jsonify({'error': '请填写 API 配置'}), 400
    
    import time
    
    headers = {
        'Authorization': f'Bearer {api_key}',
        'Content-Type': 'application/json'
    }
    
    results = []
    
    # ===== 测试1: 简单Prompt能力探测 =====
    simple_prompt = "A blue ball bouncing on a white floor"
    endpoints = ['/v1/video/generations', '/v1/videos/generations', '/v1/generation/video']
    
    endpoint_found = None
    for endpoint in endpoints:
        url = base_url.rstrip('/') + endpoint
        body = {'model': model, 'prompt': simple_prompt}
        
        try:
            start = time.time()
            resp = requests.post(url, json=body, headers=headers, timeout=30)
            elapsed = (time.time() - start) * 1000
            
            if resp.status_code == 404:
                continue
            
            resp_json = resp.json()
            endpoint_found = endpoint
            
            if 'error' in resp_json:
                error_msg = resp_json['error']
                if isinstance(error_msg, dict):
                    error_msg = error_msg.get('message', str(error_msg))
                results.append({
                    'name': 'simple_prompt',
                    'label': '🎬 基础能力',
                    'success': False,
                    'error': str(error_msg)[:300],
                    'latency_ms': round(elapsed, 1),
                    'score': 0,
                })
            else:
                task_id = resp_json.get('id', resp_json.get('task_id', ''))
                video_url = resp_json.get('video_url', resp_json.get('url', ''))
                status = resp_json.get('status', 'submitted')
                
                # 提取规格信息
                specs = {}
                for key in ['resolution', 'width', 'height', 'duration', 'fps', 'format', 'quality']:
                    if key in resp_json:
                        specs[key] = resp_json[key]
                
                results.append({
                    'name': 'simple_prompt',
                    'label': '🎬 基础能力',
                    'success': True,
                    'latency_ms': round(elapsed, 1),
                    'score': 100,
                    'task_id': task_id,
                    'status': status,
                    'specs': specs,
                    'raw_keys': list(resp_json.keys())[:15],
                })
            break
            
        except requests.exceptions.ConnectionError:
            continue
        except Exception as e:
            results.append({
                'name': 'simple_prompt',
                'label': '🎬 基础能力',
                'success': False,
                'error': str(e)[:200],
                'latency_ms': 0,
                'score': 0,
            })
            break
    
    if not endpoint_found:
        return jsonify({
            'success': True,
            'results': [{
                'name': 'endpoint_check',
                'label': '🔌 端点探测',
                'success': False,
                'error': '未找到可用的视频生成端点',
                'score': 0,
            }],
            'summary': {
                'total_score': 0,
                'supported': False,
                'version_estimate': 'not_supported',
            }
        })
    
    # ===== 测试2: 复杂Prompt =====
    if endpoint_found and results and results[-1].get('success'):
        complex_prompt = "A tabby cat walking through a colorful garden, turning its head to look at a blue butterfly, with sunlight filtering through the leaves, cinematic quality"
        url = base_url.rstrip('/') + endpoint_found
        body = {'model': model, 'prompt': complex_prompt}
        
        try:
            start = time.time()
            resp = requests.post(url, json=body, headers=headers, timeout=30)
            elapsed = (time.time() - start) * 1000
            resp_json = resp.json()
            
            if 'error' in resp_json:
                error_msg = resp_json['error']
                if isinstance(error_msg, dict):
                    error_msg = error_msg.get('message', str(error_msg))
                results.append({
                    'name': 'complex_prompt',
                    'label': '🎭 复杂场景',
                    'success': False,
                    'error': str(error_msg)[:200],
                    'latency_ms': round(elapsed, 1),
                    'score': 0,
                })
            else:
                results.append({
                    'name': 'complex_prompt',
                    'label': '🎭 复杂场景',
                    'success': True,
                    'latency_ms': round(elapsed, 1),
                    'score': 100,
                    'status': resp_json.get('status', 'submitted'),
                })
        except Exception as e:
            results.append({
                'name': 'complex_prompt',
                'label': '🎭 复杂场景',
                'success': False,
                'error': str(e)[:200],
                'latency_ms': 0,
                'score': 0,
            })
    
    # ===== 汇总 =====
    success_tests = [r for r in results if r.get('success')]
    total_score = round(sum(r['score'] for r in results) / len(results)) if results else 0
    
    if len(success_tests) == 0:
        version_estimate = 'not_supported'
    elif total_score >= 80:
        version_estimate = 'high'
    elif total_score >= 50:
        version_estimate = 'medium'
    else:
        version_estimate = 'low'
    
    return jsonify({
        'success': True,
        'results': results,
        'summary': {
            'total_score': total_score,
            'supported': len(success_tests) > 0,
            'version_estimate': version_estimate,
            'endpoint': endpoint_found,
        }
    })



# ============== API 可用性监控 ==============

@test_text_bp.route('/api/test/ping', methods=['POST'])
@login_required
def run_ping():
    """API 健康检查 - 快速测试可用性"""
    data = request.json
    config, _, _, error = get_config_from_request(data)
    
    if error:
        return jsonify({'error': error}), 400
    
    import time
    
    try:
        tester = ApiTester(config)
        start = time.time()
        resp = tester.call_api([{"role": "user", "content": "hi"}], max_tokens=5)
        latency = (time.time() - start) * 1000
        content, model_field, _, _ = tester._parse_response(resp)
        
        return jsonify({
            'status': 'online',
            'latency_ms': round(latency, 1),
            'response_model': model_field or '',
            'response_preview': (content or '')[:50]
        })
    except Exception as e:
        return jsonify({
            'status': 'offline',
            'latency_ms': 0,
            'error': str(e)[:200]
        })


@test_text_bp.route('/api/test/monitor', methods=['POST'])
@login_required
def run_monitor():
    """批量API健康监控"""
    data = request.json
    apis = data.get('apis', [])
    
    if not apis:
        return jsonify({'error': '请提供API列表'}), 400
    
    import time
    results = []
    
    for api in apis[:10]:  # 最多10个
        name = api.get('name', 'Unknown')
        try:
            cfg = ApiConfig(
                name=name,
                base_url=api.get('base_url', ''),
                api_key=api.get('api_key', ''),
                model=api.get('model', ''),
                api_format=ApiFormat(api.get('api_format', 'openai'))
            )
            tester = ApiTester(cfg)
            start = time.time()
            resp = tester.call_api([{"role": "user", "content": "ping"}], max_tokens=5)
            latency = (time.time() - start) * 1000
            content, _, _, _ = tester._parse_response(resp)
            
            results.append({
                'name': name,
                'model': api.get('model', ''),
                'status': 'online',
                'latency_ms': round(latency, 1),
                'checked_at': time.strftime('%H:%M:%S')
            })
        except Exception as e:
            results.append({
                'name': name,
                'model': api.get('model', ''),
                'status': 'offline',
                'latency_ms': 0,
                'error': str(e)[:100],
                'checked_at': time.strftime('%H:%M:%S')
            })
    
    return jsonify({'success': True, 'results': results})


# ============== Streaming 性能测试 ==============

@test_text_bp.route('/api/test/streaming', methods=['POST'])
@login_required
def run_streaming_test():
    """测试流式响应性能 - TTFT/Chunk延迟/稳定性"""
    data = request.json
    config, _, _, error = get_config_from_request(data)
    
    if error:
        return jsonify({'error': error}), 400
    
    try:
        import time
        import requests as req_lib
        
        # 构建请求
        headers = {"Content-Type": "application/json"}
        body = {"stream": True, "max_tokens": 300}
        
        prompt = "请用200字左右介绍一下人工智能的发展历程，包括关键里程碑。"
        
        if config.api_format.value in ('openai', 'gemini', 'deepseek', 'qwen', 'glm', 'moonshot', 'doubao'):
            headers["Authorization"] = f"Bearer {config.api_key}"
            body["model"] = config.model
            body["messages"] = [{"role": "user", "content": prompt}]
            url = f"{config.base_url.rstrip('/')}/v1/chat/completions"
        elif config.api_format.value == 'anthropic':
            headers["x-api-key"] = config.api_key
            headers["anthropic-version"] = "2023-06-01"
            body["model"] = config.model
            body["messages"] = [{"role": "user", "content": prompt}]
            url = f"{config.base_url.rstrip('/')}/v1/messages"
        else:
            headers["Authorization"] = f"Bearer {config.api_key}"
            body["model"] = config.model
            body["messages"] = [{"role": "user", "content": prompt}]
            url = f"{config.base_url.rstrip('/')}/v1/chat/completions"
        
        start_time = time.time()
        ttft = None
        chunk_times = []
        chunk_count = 0
        total_content = ""
        last_chunk_time = start_time
        
        resp = req_lib.post(url, json=body, headers=headers, stream=True, timeout=60)
        
        for line in resp.iter_lines():
            if not line:
                continue
            line_str = line.decode('utf-8', errors='ignore')
            if not line_str.startswith('data:'):
                continue
            
            data_str = line_str[5:].strip()
            if data_str == '[DONE]':
                break
            
            now = time.time()
            chunk_count += 1
            
            if ttft is None:
                ttft = (now - start_time) * 1000  # ms
            
            chunk_interval = (now - last_chunk_time) * 1000
            chunk_times.append(chunk_interval)
            last_chunk_time = now
            
            try:
                chunk_data = json.loads(data_str)
                # OpenAI format
                if 'choices' in chunk_data:
                    delta = chunk_data['choices'][0].get('delta', {})
                    total_content += delta.get('content', '')
                # Anthropic format
                elif 'delta' in chunk_data:
                    total_content += chunk_data['delta'].get('text', '')
            except:
                pass
        
        end_time = time.time()
        total_time = (end_time - start_time) * 1000
        
        # 计算统计
        avg_chunk_latency = sum(chunk_times[1:]) / len(chunk_times[1:]) if len(chunk_times) > 1 else 0
        max_chunk_latency = max(chunk_times[1:]) if len(chunk_times) > 1 else 0
        min_chunk_latency = min(chunk_times[1:]) if len(chunk_times) > 1 else 0
        
        # 稳定性：标准差/平均值
        if len(chunk_times) > 2 and avg_chunk_latency > 0:
            variance = sum((t - avg_chunk_latency) ** 2 for t in chunk_times[1:]) / len(chunk_times[1:])
            stability = 1 - min((variance ** 0.5) / avg_chunk_latency, 1)
        else:
            stability = 1.0
        
        return jsonify({
            'success': True,
            'ttft_ms': round(ttft or 0, 1),
            'avg_chunk_latency_ms': round(avg_chunk_latency, 1),
            'max_chunk_latency_ms': round(max_chunk_latency, 1),
            'min_chunk_latency_ms': round(min_chunk_latency, 1),
            'chunk_count': chunk_count,
            'total_time_ms': round(total_time, 1),
            'content_length': len(total_content),
            'stability': round(stability, 2),
            'chars_per_second': round(len(total_content) / (total_time / 1000), 1) if total_time > 0 else 0
        })
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500


# ============== 并发测试 / Token 测试 / 完整测试 ==============

@test_text_bp.route('/api/test/benchmark', methods=['POST'])
@login_required
def run_benchmark():
    """仅运行并发能力测试"""
    data = request.json
    config, num_requests, concurrency, error = get_config_from_request(data)
    
    if error:
        return jsonify({'error': error}), 400
    
    try:
        tester = ApiTester(config)
        result = asyncio.run(tester.run_benchmark(num_requests, concurrency))
        
        return jsonify({
            'success': True,
            'total_requests': result.total_requests,
            'successful_requests': result.successful_requests,
            'failed_requests': result.failed_requests,
            'success_rate': result.success_rate,
            'total_time_ms': result.total_time_ms,
            'avg_latency_ms': result.avg_latency_ms,
            'min_latency_ms': result.min_latency_ms,
            'max_latency_ms': result.max_latency_ms,
            'p50_latency_ms': result.p50_latency_ms,
            'p90_latency_ms': result.p90_latency_ms,
            'p99_latency_ms': result.p99_latency_ms,
            'qps': result.qps,
            'tokens_per_second': result.tokens_per_second
        })
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@test_text_bp.route('/api/test/token', methods=['POST'])
@login_required
def run_token_test():
    """仅运行Token计算测试"""
    data = request.json
    config, _, _, error = get_config_from_request(data)
    
    if error:
        return jsonify({'error': error}), 400
    
    try:
        tester = ApiTester(config)
        result = asyncio.run(tester.run_benchmark(3, 2))
        
        estimated_cost = 0
        if config.price_input > 0 and config.price_output > 0:
            input_cost = (result.total_input_tokens / 1_000_000) * config.price_input
            output_cost = (result.total_output_tokens / 1_000_000) * config.price_output
            estimated_cost = input_cost + output_cost
        
        return jsonify({
            'success': True,
            'input_tokens': result.total_input_tokens,
            'output_tokens': result.total_output_tokens,
            'total_tokens': result.total_tokens,
            'tokens_per_second': result.tokens_per_second,
            'estimated_cost': estimated_cost,
            'price_input': config.price_input,
            'price_output': config.price_output
        })
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@test_text_bp.route('/api/test/full', methods=['POST'])
@login_required
def run_full_test():
    """运行完整测试（包含诚实性检测）"""
    data = request.json
    config, num_requests, concurrency, error = get_config_from_request(data)
    
    if error:
        return jsonify({'error': error}), 400
    
    try:
        tester = ApiTester(config)
        report = asyncio.run(tester.run_full_test(num_requests, concurrency))
        
        record_id = save_report(report)
        
        # 运行诚实性检测
        honesty_result = _run_honesty_check(tester)
        
        # 保存诚实性结果到数据库
        if honesty_result and record_id:
            from core.database import get_db
            db = get_db()
            db.execute(
                'UPDATE test_records SET honesty_score=?, honesty_level=?, honesty_details=? WHERE id=?',
                (
                    honesty_result.get('honesty_score', 0),
                    honesty_result.get('honesty_level', ''),
                    json.dumps(honesty_result, ensure_ascii=False),
                    record_id
                )
            )
            db.commit()
        
        estimated_cost = 0
        if config.price_input > 0 and config.price_output > 0 and report.benchmark:
            input_cost = (report.benchmark.total_input_tokens / 1_000_000) * config.price_input
            output_cost = (report.benchmark.total_output_tokens / 1_000_000) * config.price_output
            estimated_cost = input_cost + output_cost
        
        return jsonify({
            'success': True,
            'record_id': record_id,
            'verify': {
                'authenticity': report.model_authenticity,
                'response_model': report.model_verify.response_model if report.model_verify else '',
                'consistency_score': report.model_verify.consistency_score if report.model_verify else 0
            } if report.model_verify else None,
            'benchmark': {
                'success_rate': report.benchmark.success_rate,
                'avg_latency_ms': report.benchmark.avg_latency_ms,
                'qps': report.benchmark.qps,
                'total_requests': report.benchmark.total_requests
            } if report.benchmark else None,
            'token': {
                'input_tokens': report.benchmark.total_input_tokens if report.benchmark else 0,
                'output_tokens': report.benchmark.total_output_tokens if report.benchmark else 0,
                'total_tokens': report.benchmark.total_tokens if report.benchmark else 0,
                'estimated_cost': estimated_cost
            },
            'honesty': honesty_result,
            'overall_score': report.overall_score
        })
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500


def _run_honesty_check(tester):
    """在完整测试中运行诚实性检测"""
    try:
        questions = get_honesty_test_questions()
        results = []
        consistency_cn = None
        consistency_en = None
        total_score = 0
        scored_count = 0
        
        for q in questions:
            try:
                resp = tester.call_api(
                    [{"role": "user", "content": q['question']}],
                    max_tokens=500
                )
                content, _, _, _ = tester._parse_response(resp)
            except:
                content = ''
            
            analysis = analyze_honesty_response(q, content)
            
            if q['id'] == 'consistency_cn':
                consistency_cn = content
            elif q['id'] == 'consistency_en':
                consistency_en = content
            
            if q['category'] != '一致性验证':
                total_score += analysis['score']
                scored_count += 1
            
            results.append({
                'id': q['id'],
                'category': q['category'],
                'question': q['question'][:150],
                'response': content[:500] if content else '',
                'score': analysis['score'],
                'level': analysis['level'],
                'signals': analysis['signals']
            })
        
        consistency_result = check_consistency(consistency_cn, consistency_en)
        
        avg_score = total_score / scored_count if scored_count > 0 else 50
        final_score = avg_score * 0.7 + consistency_result['score'] * 0.3
        final_score = max(0, min(100, final_score))
        
        if final_score >= 70:
            honesty_level = '诚实'
            level_class = 'success'
        elif final_score >= 40:
            honesty_level = '存疑'
            level_class = 'warning'
        else:
            honesty_level = '可疑'
            level_class = 'danger'
        
        risk_signals = []
        for r in results:
            if r['level'] in ('suspicious', 'evasive'):
                risk_signals.append(f"{r['category']}: {', '.join(r['signals'][:2])}")
        
        return {
            'honesty_score': round(final_score, 1),
            'honesty_level': honesty_level,
            'level_class': level_class,
            'consistency_consistent': consistency_result['consistent'],
            'consistency_score': consistency_result['score'],
            'risk_signals': risk_signals,
            'total_questions': len(questions),
            'results': results
        }
    except Exception as e:
        return {
            'honesty_score': 0,
            'honesty_level': '未知',
            'level_class': 'secondary',
            'error': str(e)
        }


@test_text_bp.route('/api/test', methods=['POST'])
@login_required
def run_test():
    """运行测试 (兼容旧接口)"""
    return run_full_test()
