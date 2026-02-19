"""
历史记录路由 - CRUD 和下载
"""

import json
from datetime import datetime
from flask import Blueprint, jsonify, Response
from core.database import get_db
from routes.auth import login_required
from testers.text_tester import FullTestReport

records_bp = Blueprint('records', __name__)


def save_report(report: FullTestReport) -> int:
    """保存测试报告到数据库"""
    db = get_db()
    
    cursor = db.execute('''
        INSERT INTO test_records (
            provider_name, base_url, model, api_format,
            response_model, knowledge_cutoff, consistency_score, reasoning_correct, model_authenticity,
            total_requests, successful_requests, failed_requests, success_rate,
            total_time_ms, avg_latency_ms, min_latency_ms, max_latency_ms,
            p50_latency_ms, p90_latency_ms, p99_latency_ms, qps,
            total_input_tokens, total_output_tokens, total_tokens, tokens_per_second,
            price_input, price_output, estimated_cost, overall_score,
            request_details, verify_details, recommendations
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    ''', (
        report.config.name,
        report.config.base_url,
        report.config.model,
        report.config.api_format.value,
        report.model_verify.response_model if report.model_verify else '',
        report.model_verify.knowledge_cutoff if report.model_verify else '',
        report.model_verify.consistency_score if report.model_verify else 0,
        1 if report.model_verify and report.model_verify.reasoning_correct else 0,
        report.model_authenticity,
        report.benchmark.total_requests if report.benchmark else 0,
        report.benchmark.successful_requests if report.benchmark else 0,
        report.benchmark.failed_requests if report.benchmark else 0,
        report.benchmark.success_rate if report.benchmark else 0,
        report.benchmark.total_time_ms if report.benchmark else 0,
        report.benchmark.avg_latency_ms if report.benchmark else 0,
        report.benchmark.min_latency_ms if report.benchmark else 0,
        report.benchmark.max_latency_ms if report.benchmark else 0,
        report.benchmark.p50_latency_ms if report.benchmark else 0,
        report.benchmark.p90_latency_ms if report.benchmark else 0,
        report.benchmark.p99_latency_ms if report.benchmark else 0,
        report.benchmark.qps if report.benchmark else 0,
        report.benchmark.total_input_tokens if report.benchmark else 0,
        report.benchmark.total_output_tokens if report.benchmark else 0,
        report.benchmark.total_tokens if report.benchmark else 0,
        report.benchmark.tokens_per_second if report.benchmark else 0,
        report.config.price_input,
        report.config.price_output,
        report.estimated_cost,
        report.overall_score,
        json.dumps([{
            'request_id': r.request_id,
            'success': r.success,
            'latency_ms': r.latency_ms,
            'input_tokens': r.input_tokens,
            'output_tokens': r.output_tokens,
            'total_tokens': r.total_tokens,
            'error': r.error_message
        } for r in (report.benchmark.results if report.benchmark else [])]),
        json.dumps(report.model_verify.details if report.model_verify else {}),
        json.dumps(report.recommendations)
    ))
    
    db.commit()
    return cursor.lastrowid


@records_bp.route('/api/records')
@login_required
def get_records():
    """获取测试记录列表"""
    db = get_db()
    records = db.execute(
        'SELECT id, created_at, provider_name, model, model_authenticity, honesty_level, success_rate, avg_latency_ms, total_tokens, overall_score FROM test_records ORDER BY created_at DESC LIMIT 100'
    ).fetchall()
    
    return jsonify([dict(r) for r in records])


@records_bp.route('/api/record/<int:record_id>')
@login_required
def get_record(record_id):
    """获取测试记录详情"""
    db = get_db()
    record = db.execute(
        'SELECT * FROM test_records WHERE id = ?', (record_id,)
    ).fetchone()
    
    if record is None:
        return jsonify({'error': '记录不存在'}), 404
    
    return jsonify(dict(record))


@records_bp.route('/api/record/<int:record_id>', methods=['DELETE'])
@login_required
def delete_record(record_id):
    """删除测试记录"""
    db = get_db()
    db.execute('DELETE FROM test_records WHERE id = ?', (record_id,))
    db.commit()
    return jsonify({'success': True})


@records_bp.route('/api/record/<int:record_id>/download')
@login_required
def download_record(record_id):
    """下载测试报告"""
    db = get_db()
    record = db.execute(
        'SELECT * FROM test_records WHERE id = ?', (record_id,)
    ).fetchone()
    
    if record is None:
        return jsonify({'error': '记录不存在'}), 404
    
    record_dict = dict(record)
    
    # 解析 JSON 字段
    result_data = {}
    if record_dict.get('result_json'):
        try:
            result_data = json.loads(record_dict['result_json'])
        except:
            pass
    
    # 生成报告内容
    report_lines = []
    report_lines.append("=" * 60)
    report_lines.append("AI API 测试报告")
    report_lines.append("=" * 60)
    report_lines.append("")
    report_lines.append(f"服务商: {record_dict.get('provider_name', 'Unknown')}")
    report_lines.append(f"模型: {record_dict.get('model', '')}")
    report_lines.append(f"测试时间: {record_dict.get('created_at', '')}")
    report_lines.append(f"测试类型: {record_dict.get('test_type', '')}")
    report_lines.append("")
    
    # 模型验证结果
    if result_data.get('verify'):
        report_lines.append("-" * 40)
        report_lines.append("【模型真实性验证】")
        report_lines.append("-" * 40)
        verify = result_data['verify']
        report_lines.append(f"结果: {'通过' if verify.get('is_authentic') else '存疑'}")
        report_lines.append(f"响应模型: {verify.get('response_model', '')}")
        report_lines.append(f"相似度: {verify.get('similarity', 0):.2%}")
        if verify.get('reasons'):
            report_lines.append("存疑原因:")
            for reason in verify['reasons']:
                report_lines.append(f"  - {reason}")
        report_lines.append("")
    
    # 并发测试结果
    if result_data.get('benchmark'):
        report_lines.append("-" * 40)
        report_lines.append("【并发能力测试】")
        report_lines.append("-" * 40)
        bench = result_data['benchmark']
        report_lines.append(f"总请求数: {bench.get('total_requests', 0)}")
        report_lines.append(f"成功请求: {bench.get('successful_requests', 0)}")
        report_lines.append(f"成功率: {bench.get('success_rate', 0):.2%}")
        report_lines.append(f"平均延迟: {bench.get('avg_latency_ms', 0):.2f} ms")
        report_lines.append(f"最小延迟: {bench.get('min_latency_ms', 0):.2f} ms")
        report_lines.append(f"最大延迟: {bench.get('max_latency_ms', 0):.2f} ms")
        report_lines.append(f"P50 延迟: {bench.get('p50_latency_ms', 0):.2f} ms")
        report_lines.append(f"P90 延迟: {bench.get('p90_latency_ms', 0):.2f} ms")
        report_lines.append(f"P99 延迟: {bench.get('p99_latency_ms', 0):.2f} ms")
        report_lines.append(f"QPS: {bench.get('qps', 0):.2f}")
        report_lines.append("")
    
    # Token 统计
    if result_data.get('token'):
        report_lines.append("-" * 40)
        report_lines.append("【Token 统计】")
        report_lines.append("-" * 40)
        token = result_data['token']
        report_lines.append(f"总输入 Tokens: {token.get('total_input_tokens', 0)}")
        report_lines.append(f"总输出 Tokens: {token.get('total_output_tokens', 0)}")
        report_lines.append(f"总 Tokens: {token.get('total_tokens', 0)}")
        if token.get('estimated_cost'):
            report_lines.append(f"预估费用: ${token.get('estimated_cost', 0):.6f}")
        report_lines.append("")
    
    report_lines.append("=" * 60)
    report_lines.append("报告生成时间: " + datetime.now().strftime('%Y-%m-%d %H:%M:%S'))
    report_lines.append("=" * 60)
    
    report_content = "\n".join(report_lines)
    
    # 生成文件名
    filename = f"test_report_{record_dict.get('provider_name', 'unknown')}_{record_id}.txt"
    
    return Response(
        report_content,
        mimetype='text/plain',
        headers={'Content-Disposition': f'attachment; filename={filename}'}
    )


@records_bp.route('/api/record/<int:record_id>/export-html')
@login_required
def export_html_report(record_id):
    """导出 HTML 格式测试报告"""
    db = get_db()
    record = db.execute('SELECT * FROM test_records WHERE id = ?', (record_id,)).fetchone()
    
    if record is None:
        return jsonify({'error': '记录不存在'}), 404
    
    r = dict(record)
    honesty_data = {}
    if r.get('honesty_details'):
        try:
            honesty_data = json.loads(r['honesty_details'])
        except:
            pass
    
    score = round(r.get('overall_score', 0))
    score_class = 'success' if score >= 70 else 'warning' if score >= 40 else 'danger'
    
    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>API测试报告 - {r.get('provider_name', '')}</title>
<style>
* {{ margin:0; padding:0; box-sizing:border-box; }}
body {{ font-family: -apple-system, 'Segoe UI', sans-serif; background:#f0f2f5; color:#333; padding:40px; }}
.report {{ max-width:900px; margin:0 auto; background:#fff; border-radius:16px; box-shadow:0 4px 24px rgba(0,0,0,0.1); overflow:hidden; }}
.header {{ background:linear-gradient(135deg,#667eea,#764ba2); color:#fff; padding:40px; text-align:center; }}
.header h1 {{ font-size:1.8rem; margin-bottom:8px; }}
.header p {{ opacity:0.8; }}
.score-circle {{ width:100px; height:100px; border-radius:50%; background:rgba(255,255,255,0.2); display:flex; align-items:center; justify-content:center; margin:20px auto; font-size:2.5rem; font-weight:bold; }}
.section {{ padding:30px 40px; border-bottom:1px solid #eee; }}
.section h2 {{ font-size:1.2rem; color:#555; margin-bottom:16px; display:flex; align-items:center; gap:8px; }}
.section h2::before {{ content:''; width:4px; height:20px; background:#667eea; border-radius:2px; }}
.grid {{ display:grid; grid-template-columns:repeat(auto-fit, minmax(180px,1fr)); gap:16px; }}
.stat {{ background:#f8f9fa; border-radius:10px; padding:16px; text-align:center; }}
.stat .value {{ font-size:1.5rem; font-weight:bold; color:#333; }}
.stat .label {{ font-size:0.8rem; color:#888; margin-top:4px; }}
.badge {{ display:inline-block; padding:4px 12px; border-radius:20px; font-size:0.8rem; font-weight:600; }}
.badge-success {{ background:#d4edda; color:#155724; }}
.badge-warning {{ background:#fff3cd; color:#856404; }}
.badge-danger {{ background:#f8d7da; color:#721c24; }}
table {{ width:100%; border-collapse:collapse; margin-top:12px; }}
table th,table td {{ padding:10px 12px; text-align:left; border-bottom:1px solid #eee; font-size:0.9rem; }}
table th {{ color:#888; font-weight:500; }}
.footer {{ padding:20px 40px; text-align:center; color:#999; font-size:0.8rem; }}
@media print {{ body {{ padding:0; background:#fff; }} .report {{ box-shadow:none; }} }}
</style>
</head>
<body>
<div class="report">
    <div class="header">
        <h1>AI API 测试报告</h1>
        <p>{r.get('provider_name', '')} | {r.get('model', '')} | {r.get('created_at', '')[:16]}</p>
        <div class="score-circle">{score}</div>
        <p>综合评分</p>
    </div>

    <div class="section">
        <h2>模型验证</h2>
        <div class="grid">
            <div class="stat"><div class="value"><span class="badge badge-{score_class}">{r.get('model_authenticity', '未知')}</span></div><div class="label">真实性判定</div></div>
            <div class="stat"><div class="value">{r.get('response_model', '-')}</div><div class="label">响应模型</div></div>
            <div class="stat"><div class="value">{round(r.get('consistency_score', 0) * 100)}%</div><div class="label">一致性</div></div>
        </div>
    </div>"""
    
    if r.get('honesty_level'):
        hl = r['honesty_level']
        hl_class = 'success' if hl == '诚实' else 'warning' if hl == '存疑' else 'danger'
        html += f"""
    <div class="section">
        <h2>诚实性检测</h2>
        <div class="grid">
            <div class="stat"><div class="value"><span class="badge badge-{hl_class}">{hl}</span></div><div class="label">诚实性判定</div></div>
            <div class="stat"><div class="value">{r.get('honesty_score', 0)}</div><div class="label">诚实性得分</div></div>
            <div class="stat"><div class="value">{'一致' if honesty_data.get('consistency_consistent', True) else '不一致'}</div><div class="label">中英文一致性</div></div>
        </div>
    </div>"""
    
    html += f"""
    <div class="section">
        <h2>性能指标</h2>
        <div class="grid">
            <div class="stat"><div class="value">{r.get('total_requests', 0)}</div><div class="label">总请求</div></div>
            <div class="stat"><div class="value">{round(r.get('success_rate', 0) * 100)}%</div><div class="label">成功率</div></div>
            <div class="stat"><div class="value">{round(r.get('avg_latency_ms', 0) / 1000, 2)}s</div><div class="label">平均延迟</div></div>
            <div class="stat"><div class="value">{round(r.get('qps', 0), 2)}</div><div class="label">QPS</div></div>
        </div>
        <table>
            <tr><th>P50</th><th>P90</th><th>P99</th><th>最大</th></tr>
            <tr><td>{round(r.get('p50_latency_ms',0)/1000,2)}s</td><td>{round(r.get('p90_latency_ms',0)/1000,2)}s</td><td>{round(r.get('p99_latency_ms',0)/1000,2)}s</td><td>{round(r.get('max_latency_ms',0)/1000,2)}s</td></tr>
        </table>
    </div>

    <div class="section">
        <h2>Token 统计</h2>
        <div class="grid">
            <div class="stat"><div class="value">{r.get('total_input_tokens', 0)}</div><div class="label">输入 Tokens</div></div>
            <div class="stat"><div class="value">{r.get('total_output_tokens', 0)}</div><div class="label">输出 Tokens</div></div>
            <div class="stat"><div class="value">{r.get('total_tokens', 0)}</div><div class="label">总 Tokens</div></div>
            <div class="stat"><div class="value">${round(r.get('estimated_cost', 0), 4)}</div><div class="label">预估费用</div></div>
        </div>
    </div>

    <div class="footer">
        <p>AI API 测试平台 | 报告生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</p>
    </div>
</div>
</body>
</html>"""
    
    filename = f"report_{r.get('provider_name', 'api')}_{record_id}.html"
    return Response(
        html,
        mimetype='text/html',
        headers={'Content-Disposition': f'attachment; filename={filename}'}
    )
