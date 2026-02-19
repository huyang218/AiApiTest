"""
数据库管理模块
"""

import sqlite3
from flask import g

DATABASE = 'api_tests.db'


def get_db():
    """获取数据库连接"""
    if 'db' not in g:
        g.db = sqlite3.connect(DATABASE)
        g.db.row_factory = sqlite3.Row
    return g.db


def close_db(error=None):
    """关闭数据库连接"""
    db = g.pop('db', None)
    if db is not None:
        db.close()


def init_db():
    """初始化数据库"""
    conn = sqlite3.connect(DATABASE)
    cursor = conn.cursor()
    
    # 测试记录表
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS test_records (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            provider_name TEXT NOT NULL,
            base_url TEXT NOT NULL,
            model TEXT NOT NULL,
            api_format TEXT NOT NULL,
            
            -- 模型验证结果
            response_model TEXT,
            knowledge_cutoff TEXT,
            consistency_score REAL,
            reasoning_correct INTEGER,
            model_authenticity TEXT,
            
            -- 性能测试结果
            total_requests INTEGER,
            successful_requests INTEGER,
            failed_requests INTEGER,
            success_rate REAL,
            total_time_ms REAL,
            avg_latency_ms REAL,
            min_latency_ms REAL,
            max_latency_ms REAL,
            p50_latency_ms REAL,
            p90_latency_ms REAL,
            p99_latency_ms REAL,
            qps REAL,
            
            -- Token 统计
            total_input_tokens INTEGER,
            total_output_tokens INTEGER,
            total_tokens INTEGER,
            tokens_per_second REAL,
            
            -- 价格
            price_input REAL,
            price_output REAL,
            estimated_cost REAL,
            
            -- 评分
            overall_score REAL,
            
            -- 详细数据 (JSON)
            request_details TEXT,
            verify_details TEXT,
            recommendations TEXT
        )
    ''')
    
    # 添加诚实性检测字段（兼容已有数据库）
    try:
        cursor.execute('ALTER TABLE test_records ADD COLUMN honesty_score REAL')
    except:
        pass
    try:
        cursor.execute('ALTER TABLE test_records ADD COLUMN honesty_level TEXT')
    except:
        pass
    try:
        cursor.execute('ALTER TABLE test_records ADD COLUMN honesty_details TEXT')
    except:
        pass
    
    conn.commit()
    conn.close()
    print("数据库初始化完成")
