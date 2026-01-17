import sqlite3
import os

DB_PATH = os.path.join(os.path.dirname(__file__), 'power.db')

SCHEMA_PATH = os.path.join(os.path.dirname(__file__), 'power_schema.sql')
# SCHEMA_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'power_schema.sql')

def init_db():
    if not os.path.exists(DB_PATH):
        print(f"[init_db] DB不存在，准备初始化，SCHEMA_PATH={SCHEMA_PATH}")
        with open(SCHEMA_PATH, 'r', encoding='utf-8') as f:
            schema = f.read()
        print(f"[init_db] 读取SQL内容：{schema[:100]}...")  # 打印前100字符
        conn = sqlite3.connect(DB_PATH)
        try:
            conn.executescript(schema)
            conn.commit()
            print("[init_db] 建表SQL已执行")
        finally:
            conn.close()

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn
