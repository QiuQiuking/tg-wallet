import sqlite3
from typing import List, Dict

DB_PATH = "watches.db"

def init_db():
    """初始化数据库，创建监听表"""
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS watches (
            chat_id TEXT,
            address TEXT,
            PRIMARY KEY (chat_id, address)
        )
    """)
    conn.commit()
    conn.close()

def add_watch(chat_id: str, address: str):
    """添加监听地址"""
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute(
        "INSERT OR IGNORE INTO watches(chat_id, address) VALUES(?, ?)",
        (chat_id, address)
    )
    conn.commit()
    conn.close()

def remove_watch(chat_id: str, address: str):
    """移除监听地址"""
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute(
        "DELETE FROM watches WHERE chat_id=? AND address=?",
        (chat_id, address)
    )
    conn.commit()
    conn.close()

def list_watch(chat_id: str) -> List[str]:
    """列出某个聊天的所有监听地址"""
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("SELECT address FROM watches WHERE chat_id=?", (chat_id,))
    rows = [row[0] for row in cur.fetchall()]
    conn.close()
    return rows

def all_watches() -> Dict[str, List[str]]:
    """返回所有监听记录，按 chat_id 分组"""
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("SELECT chat_id, address FROM watches")
    watches: Dict[str, List[str]] = {}
    for chat_id, address in cur.fetchall():
        watches.setdefault(chat_id, []).append(address)
    conn.close()
    return watches
