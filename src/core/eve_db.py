import sqlite3
import os
import json

class EveDB:
    def __init__(self, db_path="eve_sde.db"):
        self.db_path = db_path
        self.conn = None

    def connect(self):
        # 增加 timeout 避免 locked
        self.conn = sqlite3.connect(self.db_path, timeout=30.0)
        self.conn.row_factory = sqlite3.Row

    def close(self):
        if self.conn:
            self.conn.close()

    def init_db(self):
        self.connect()
        try:
            cursor = self.conn.cursor()
            # Main data table
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS items (
                    id TEXT,
                    source_file TEXT,
                    name_zh TEXT,
                    name_en TEXT,
                    search_text TEXT,
                    json_data TEXT
                )
            ''')
            # Index for faster lookup by ID
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_id ON items(id)')
            # Index for exact name match (optional)
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_name_zh ON items(name_zh)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_name_en ON items(name_en)')
            
            self.conn.commit()
        finally:
            self.close()

    def clear_db(self):
        self.connect()
        try:
            self.conn.execute("DELETE FROM items")
            self.conn.commit() # 提交删除事务
            
            # VACUUM 必须在无事务状态下运行
            # 临时设置隔离级别为 None (自动提交模式) 以执行 VACUUM
            old_isolation = self.conn.isolation_level
            self.conn.isolation_level = None
            self.conn.execute("VACUUM")
            self.conn.isolation_level = old_isolation
        finally:
            self.close()

    def build_index(self, sde_dir, progress_callback=None):
        """
        Scan SDE directory and build database.
        progress_callback(filename, current, total)
        """
        self.connect()
        try:
            # Python sqlite3 会在执行 DML (INSERT) 时自动开启事务
            # 我们只需要最后 commit 即可确保所有插入在一个事务中（提高速度）
            # self.conn.execute("BEGIN TRANSACTION") # 不需要手动开启，避免冲突
            
            # Clear existing data first? Or assume this is called after clear_db
            # Let's just clear specific files if we were doing incremental, but here we do full rebuild
            
            files = [f for f in os.listdir(sde_dir) if f.endswith(".jsonl")]
            total_files = len(files)
            
            for idx, file_name in enumerate(files):
                file_path = os.path.join(sde_dir, file_name)
                
                if progress_callback:
                    progress_callback(file_name, idx + 1, total_files)
                
                with open(file_path, "r", encoding="utf-8") as f:
                    batch = []
                    for line in f:
                        try:
                            data = json.loads(line)
                            
                            item_id = data.get("_key") or data.get("id") or data.get("typeID")
                            item_id_str = str(item_id) if item_id is not None else ""
                            
                            name_data = data.get("name", {})
                            name_en = ""
                            name_zh = ""
                            
                            if isinstance(name_data, dict):
                                name_en = name_data.get("en", "")
                                name_zh = name_data.get("zh", "")
                            elif isinstance(name_data, str):
                                name_en = name_data
                                name_zh = name_data
                                
                            # Pre-compute search text (lowercase)
                            search_text = f"{item_id_str} {name_zh} {name_en}".lower()
                            
                            batch.append((
                                item_id_str,
                                file_name,
                                name_zh,
                                name_en,
                                search_text,
                                line.strip()
                            ))
                            
                            if len(batch) >= 1000:
                                self.conn.executemany(
                                    "INSERT INTO items (id, source_file, name_zh, name_en, search_text, json_data) VALUES (?, ?, ?, ?, ?, ?)",
                                    batch
                                )
                                batch = []
                        except:
                            continue
                            
                    if batch:
                        self.conn.executemany(
                            "INSERT INTO items (id, source_file, name_zh, name_en, search_text, json_data) VALUES (?, ?, ?, ?, ?, ?)",
                            batch
                        )
            
            self.conn.commit()
            return True
        except Exception as e:
            self.conn.rollback()
            print(f"Error building index: {e}")
            raise e
        finally:
            self.close()

    def search(self, keyword, limit=1000):
        self.connect()
        try:
            keyword = keyword.lower().strip()
            keywords = keyword.split()
            
            # Build query dynamically for multiple keywords (AND logic)
            query = "SELECT * FROM items WHERE "
            params = []
            
            conditions = []
            for kw in keywords:
                conditions.append("search_text LIKE ?")
                params.append(f"%{kw}%")
                
            query += " AND ".join(conditions)
            query += f" LIMIT {limit}"
            
            cursor = self.conn.execute(query, params)
            results = []
            for row in cursor:
                results.append({
                    "id": row["id"],
                    "file_name": row["source_file"],
                    "name_zh": row["name_zh"],
                    "name_en": row["name_en"],
                    "json_data": row["json_data"]
                })
                
            return results
        finally:
            self.close()

    def get_count(self):
        self.connect()
        try:
            cursor = self.conn.execute("SELECT COUNT(*) FROM items")
            return cursor.fetchone()[0]
        finally:
            self.close()
