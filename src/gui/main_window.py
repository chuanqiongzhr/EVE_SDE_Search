# -*- coding: utf-8 -*-
"""
EVE SDE Search Tool (GUI)
-------------------------
A PyQt6-based tool for searching and browsing EVE Online Static Data Export (SDE).
Supports fuzzy search, token-based matching, and automatic updates.

Author: ChuanQiong
Created: 2026
"""

import sys
import os
import json
import shutil
import zipfile
import requests
from PyQt5.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, 
                             QHBoxLayout, QLineEdit, QPushButton, QTableWidget, 
                             QTableWidgetItem, QHeaderView, QLabel, QMessageBox,
                             QProgressBar, QMenu, QTextEdit, QTreeWidget, QTreeWidgetItem,
                             QListWidget, QAction, QTabWidget, QSplitter, QGroupBox, QFormLayout, QTextBrowser)
from PyQt5.QtCore import Qt, QThread, pyqtSignal
from PyQt5.QtGui import QIcon, QFont, QCursor

# 尝试导入 eve_search 中的配置和函数
try:
    from src.core import eve_search
    # 强制重新计算路径（防止导入缓存导致路径错误）
    if getattr(sys, 'frozen', False):
        eve_search.SDE_DIR = os.path.join(os.path.dirname(sys.executable), "eve_sde_jsonl")
except ImportError:
    eve_search = None

# 定义获取 SDE 目录的辅助函数
def get_base_dir():
    if getattr(sys, 'frozen', False):
        return os.path.dirname(sys.executable)
    # 开发环境下，base_dir 应该是项目根目录
    # main_window.py 在 src/gui/ 下，所以需要往上找两级
    return os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

def get_resource_path(relative_path):
    """ 获取资源文件的绝对路径 (支持开发环境和打包环境) """
    if hasattr(sys, '_MEIPASS'):
        return os.path.join(sys._MEIPASS, relative_path)
    return os.path.join(get_base_dir(), relative_path)

def get_sde_dir():
    if eve_search:
        # 确保 eve_search 使用正确的 SDE 路径
        eve_search.SDE_DIR = os.path.join(get_base_dir(), "eve_sde_jsonl")
        return eve_search.SDE_DIR
    return os.path.join(get_base_dir(), "eve_sde_jsonl")

from src.core import eve_db

class IndexWorker(QThread):
    """
    后台索引构建线程
    """
    progress = pyqtSignal(str, int) # 消息, 进度(0-100)
    finished = pyqtSignal(bool, str) # 是否成功, 消息
    
    def run(self):
        try:
            self.progress.emit("正在初始化数据库...", 0)
            db_path = os.path.join(get_base_dir(), "data", "eve_sde.db")
            db = eve_db.EveDB(db_path)
            db.init_db()
            db.clear_db()
            
            sde_dir = get_sde_dir()
            if not os.path.exists(sde_dir):
                self.finished.emit(False, f"数据目录不存在: {sde_dir}")
                return

            def callback(filename, current, total):
                percent = int((current / total) * 100)
                self.progress.emit(f"正在索引: {filename} ({current}/{total})", percent)
                
            db.build_index(sde_dir, callback)
            self.finished.emit(True, "索引构建完成！")
            
        except Exception as e:
            self.finished.emit(False, f"索引构建失败: {e}")

class SearchWorker(QThread):
    """
    后台搜索线程 (DB版)
    """
    result_found = pyqtSignal(str, str, str, str, str)  # 信号：文件名, ID, 中文名, 英文名, 完整JSON字符串
    finished = pyqtSignal(int)  # 信号：总找到的数量
    error = pyqtSignal(str) # 信号：错误信息

    def __init__(self, keyword):
        super().__init__()
        self.keyword = keyword
        self.is_running = True

    def run(self):
        try:
            db_path = os.path.join(get_base_dir(), "data", "eve_sde.db")
            db = eve_db.EveDB(db_path)
            if not os.path.exists(db.db_path):
                 self.error.emit("索引数据库不存在，请先构建索引。")
                 return
                 
            results = db.search(self.keyword)
            
            for res in results:
                if not self.is_running: break
                self.result_found.emit(
                    res["file_name"], 
                    str(res["id"]), 
                    res["name_zh"], 
                    res["name_en"], 
                    res["json_data"]
                )
                
            self.finished.emit(len(results))
            
        except Exception as e:
            self.error.emit(f"搜索出错: {e}")

    def stop(self):
        self.is_running = False

class UpdateWorker(QThread):
    """
    后台更新线程
    """
    progress = pyqtSignal(str) # 进度消息
    finished = pyqtSignal(bool, str) # 是否成功, 消息
    
    def run(self):
        try:
            self.progress.emit("正在检查最新版本信息...")
            latest_key, latest_buildNumber, latest_releaseDate = self.read_SDE_latest_info()
            
            sde_dir = get_sde_dir()
            current_buildNumber = None
            
            # 检查本地版本
            sde_meta_path = os.path.join(sde_dir, "_sde.jsonl")
            if os.path.exists(sde_meta_path):
                try:
                    with open(sde_meta_path, "r", encoding="utf-8") as f:
                        line = f.readline()
                        data = json.loads(line)
                        current_buildNumber = data.get("buildNumber")
                except:
                    pass
            
            if current_buildNumber == latest_buildNumber:
                self.progress.emit("当前已是最新版本，无需更新数据包。")
            else:
                self.progress.emit(f"发现新版本: {latest_buildNumber} (当前: {current_buildNumber})，开始下载...")
                self.download_latest_eve_SDE_json()
                self.progress.emit("SDE 数据包更新完成！")
            
            # 生成变更日志
            self.progress.emit("正在获取变更详细信息...")
            self.get_SDE_update(latest_buildNumber, latest_releaseDate)
            
            self.finished.emit(True, f"更新流程结束。最新版本: {latest_buildNumber}")
            
        except Exception as e:
            self.finished.emit(False, f"更新失败: {str(e)}")

    def read_SDE_latest_info(self):
        url = "https://developers.eveonline.com/static-data/tranquility/latest.jsonl"
        response = requests.get(url, stream=True).json()
        return response['_key'], response['buildNumber'], response['releaseDate']

    def download_latest_eve_SDE_json(self):
        url = "https://developers.eveonline.com/static-data/eve-online-static-data-latest-jsonl.zip"
        filename = "eve_SDE_jsonl.zip"
        base_dir = get_base_dir()
        file_path = os.path.join(base_dir, filename)
        
        self.progress.emit("正在下载 eve_SDE_jsonl.zip ...")
        response = requests.get(url, stream=True)
        with open(file_path, "wb") as f:
            shutil.copyfileobj(response.raw, f)
            
        self.progress.emit("下载完成，正在解压...")
        extract_path = os.path.join(base_dir, "eve_sde_jsonl")
        
        # 确保目录存在
        if not os.path.exists(extract_path):
            os.makedirs(extract_path)
            
        with zipfile.ZipFile(file_path, 'r') as zf:
            zf.extractall(extract_path) # 这里通常压缩包里已经包含了 eve_sde_jsonl 文件夹，或者直接是文件
            # 注意：如果压缩包结构不同，可能需要调整解压路径
            # 假设压缩包根目录就是 jsonl 文件，或者包含在一个文件夹里
            # 如果解压出来多了一层目录，需要处理，这里暂时假设覆盖解压
            
        os.remove(file_path)
        self.progress.emit("解压完成。")

    def get_SDE_update(self, latest_buildNumber, latest_releaseDate):
        url = f"https://developers.eveonline.com/static-data/tranquility/changes/{latest_buildNumber}.jsonl"
        self.progress.emit(f"正在下载变更日志: {url}")
        
        response = requests.get(url, stream=True)
        
        safe_release_date = latest_releaseDate.replace(":", "-")
        output_dir = os.path.join(get_base_dir(), "eve_sde_update")
        os.makedirs(output_dir, exist_ok=True)
        
        changes_file = os.path.join(output_dir, f"eve_sde_changes_{safe_release_date}.jsonl")
        
        # 如果文件已存在，可能无需重新生成，但为了保险还是覆盖或检查
        # 这里选择覆盖
        with open(changes_file, "w", encoding="utf-8") as cf:
             pass # 清空文件

        sde_dir = get_sde_dir()

        for line in response.iter_lines():
            if not line: continue
            try:
                line_data = json.loads(line)
                key = line_data.get("_key")
                
                if key == '_meta':
                    continue
                
                # 获取变更列表
                added_ids = set(line_data.get("added", []))
                changed_ids = set(line_data.get("changed", []))
                removed_ids = set(line_data.get("removed", []))
                is_file_added = line_data.get("fileAdded", False)
                
                total_changes = len(added_ids) + len(changed_ids) + len(removed_ids)
                if total_changes == 0 and not is_file_added: continue
                
                msg = f"正在处理变更: {key} (新增:{len(added_ids)} 修改:{len(changed_ids)} 删除:{len(removed_ids)})"
                if is_file_added:
                    msg += " [新文件]"
                self.progress.emit(msg)
                
                # 1. 处理删除项 (无需读取原文件，因为原文件里已经没了)
                if removed_ids:
                    with open(changes_file, "a", encoding="utf-8") as cf:
                        for rid in removed_ids:
                            record = {
                                "_key": rid,
                                "_source_table": key,
                                "_status": "removed",
                                "name": {"en": "(Item Removed)", "zh": "(条目已删除)"}
                            }
                            cf.write(json.dumps(record, ensure_ascii=False) + "\n")

                # 2. 处理新增和修改项 (需要读取新文件获取详情)
                if added_ids or changed_ids or is_file_added:
                    source_file = os.path.join(sde_dir, f"{key}.jsonl")
                    
                    # 特殊处理：如果是 fileAdded 导致的新增，源文件可能就是这个 key
                    # 如果 key 本身不在 SDE_DIR 中（虽然不应该），需要下载？
                    # 这里假设 download_latest_eve_SDE_json 已经把新文件解压好了
                    
                    if not os.path.exists(source_file):
                        continue
                        
                    with open(source_file, "r", encoding="utf-8") as f:
                        for f_line in f:
                            try:
                                data = json.loads(f_line)
                                item_id = data.get("_key") 
                                
                                status = None
                                if item_id in added_ids:
                                    status = "added"
                                elif item_id in changed_ids:
                                    status = "changed"
                                 # 兼容 fileAdded 导致的 implicit added
                                elif is_file_added:
                                     status = "added"
                                
                                if status:
                                    # 写入变更文件
                                    with open(changes_file, "a", encoding="utf-8") as cf:
                                        data["_source_table"] = key
                                        data["_status"] = status
                                        cf.write(json.dumps(data, ensure_ascii=False) + "\n")
                            except:
                                continue
            except:
                continue
                
        self.progress.emit(f"变更日志已保存: {changes_file}")


import difflib

class DetailWindow(QWidget):
    """
    详情展示窗口 (增强版)
    """
    def __init__(self, json_str, parent=None):
        super().__init__(parent, Qt.Window)
        self.setWindowTitle("条目详细信息")
        self.resize(1000, 800)
        
        # 解析数据
        try:
            self.full_data = json.loads(json_str)
        except:
            self.full_data = {}
            
        # 检查是否包含 diff 数据 (old/new)
        self.has_diff = False
        if isinstance(self.full_data, dict) and "old" in self.full_data and "new" in self.full_data:
            self.has_diff = True
            
        # 确定要显示的数据 (如果有 diff，显示 new；否则显示全部)
        self.display_data = self.full_data.get("new", self.full_data) if self.has_diff else self.full_data
        if not isinstance(self.display_data, dict):
            self.display_data = {}

        main_layout = QVBoxLayout(self)
        
        # --- 顶部区域：基本信息 ---
        # 使用 Splitter 允许调整上下比例
        splitter = QSplitter(Qt.Vertical)
        
        top_widget = QWidget()
        top_layout = QVBoxLayout(top_widget)
        top_layout.setContentsMargins(0, 0, 0, 0)
        
        # 1. 标题头 (名字 + ID)
        header_group = QGroupBox("基本信息 (Basic Info)")
        header_layout = QVBoxLayout(header_group)
        
        title_line = QHBoxLayout()
        
        # 获取名字和ID
        name_zh = self.get_value(self.display_data, "name.zh") or self.get_value(self.display_data, "name") or "N/A"
        name_en = self.get_value(self.display_data, "name.en")
        item_id = self.display_data.get("_key") or self.display_data.get("id") or self.display_data.get("typeID") or "N/A"
        
        name_label = QLabel(f"{name_zh}")
        name_label.setFont(QFont("Microsoft YaHei", 16, QFont.Bold))
        title_line.addWidget(name_label)
        
        if name_en and name_en != name_zh:
            en_label = QLabel(f"({name_en})")
            en_label.setFont(QFont("Microsoft YaHei", 12))
            title_line.addWidget(en_label)
            
        title_line.addStretch()
        
        id_label = QLabel(f"ID: {item_id}")
        id_label.setFont(QFont("Consolas", 12, QFont.Bold))
        id_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        title_line.addWidget(id_label)
        
        header_layout.addLayout(title_line)
        top_layout.addWidget(header_group)
        
        # 2. 描述信息 (如果存在)
        desc = self.get_value(self.display_data, "description.zh") or self.get_value(self.display_data, "description.en") or self.get_value(self.display_data, "description")
        if desc:
            desc_group = QGroupBox("描述 (Description)")
            desc_layout = QVBoxLayout(desc_group)
            self.desc_browser = QTextBrowser()
            self.desc_browser.setOpenExternalLinks(True)
            self.desc_browser.setHtml(str(desc))
            self.desc_browser.setMaximumHeight(200) # 限制高度
            desc_layout.addWidget(self.desc_browser)
            top_layout.addWidget(desc_group)
            
        splitter.addWidget(top_widget)

        # --- 底部区域：属性树 ---
        bottom_widget = QWidget()
        bottom_layout = QVBoxLayout(bottom_widget)
        bottom_layout.setContentsMargins(0, 0, 0, 0)
        
        self.tabs = QTabWidget()
        
        # Tab 1: 完整属性
        self.tree_tab = QWidget()
        tree_tab_layout = QVBoxLayout(self.tree_tab)
        
        # 搜索框 (已删除，根据用户需求)
        # search_layout = QHBoxLayout()
        # ...
        
        # 树控件
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["属性 (Key)", "值 (Value)"])
        self.tree.setColumnWidth(0, 300)
        self.tree.setAlternatingRowColors(False) # QSS 自定义了背景，关闭默认交替
        self.tree.setSelectionMode(QTreeWidget.ExtendedSelection)
        self.tree.setContextMenuPolicy(Qt.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self.show_context_menu)
        
        # === 美化样式 (QSS) ===
        self.tree.setStyleSheet("""
            QTreeWidget {
                background-color: #ffffff;
                border: 1px solid #e0e0e0;
                border-radius: 6px;
                font-family: "Segoe UI", "Microsoft YaHei";
                font-size: 14px;
                outline: 0;
            }
            QTreeWidget::item {
                height: 32px;
                border-bottom: 1px solid #f5f5f5;
                padding-left: 5px;
            }
            QTreeWidget::item:hover {
                background-color: #f0f7ff;
            }
            QTreeWidget::item:selected {
                background-color: #e6f2ff;
                color: #333333;
                border-left: 3px solid #0078d4;
            }
            QHeaderView::section {
                background-color: #f8f9fa;
                padding: 8px;
                border: none;
                border-bottom: 2px solid #e0e0e0;
                font-weight: bold;
                font-family: "Segoe UI", "Microsoft YaHei";
                font-size: 13px;
                color: #555555;
            }
        """)
        self.tree.setIndentation(25)
        self.tree.setAnimated(True) # 启用动画
        self.tree.setRootIsDecorated(True)
        
        tree_tab_layout.addWidget(self.tree)
        
        self.populate_tree(self.tree.invisibleRootItem(), self.display_data)
        self.tree.expandToDepth(0)
        
        self.tabs.addTab(self.tree_tab, "所有属性 (Properties)")
        
        # Tab 2: 差异对比 (如果存在)
        if self.has_diff:
            self.diff_widget = QWidget()
            diff_layout = QVBoxLayout(self.diff_widget)
            
            diff_label = QLabel("版本差异对比 (Old vs New):")
            diff_label.setFont(QFont("Microsoft YaHei", 10, QFont.Bold))
            diff_layout.addWidget(diff_label)
            
            self.diff_text = QTextEdit()
            self.diff_text.setReadOnly(True)
            self.diff_text.setFont(QFont("Consolas", 10))
            diff_layout.addWidget(self.diff_text)
            
            self.tabs.addTab(self.diff_widget, "差异对比 (Diff)")
            self.show_diff()
            
        bottom_layout.addWidget(self.tabs)
        splitter.addWidget(bottom_widget)
        
        main_layout.addWidget(splitter)

        # 底部按钮栏
        btn_layout = QHBoxLayout()
        
        expand_btn = QPushButton("展开所有")
        expand_btn.clicked.connect(self.tree.expandAll)
        collapse_btn = QPushButton("折叠所有")
        collapse_btn.clicked.connect(self.tree.collapseAll)
        
        copy_all_btn = QPushButton("复制原始JSON")
        copy_all_btn.clicked.connect(lambda: self.copy_raw(json_str))
        
        close_btn = QPushButton("关闭")
        close_btn.clicked.connect(self.close)
        
        btn_layout.addWidget(expand_btn)
        btn_layout.addWidget(collapse_btn)
        btn_layout.addStretch()
        btn_layout.addWidget(copy_all_btn)
        btn_layout.addWidget(close_btn)
        main_layout.addLayout(btn_layout)

    def get_value(self, data, path):
        """ 安全获取嵌套字典的值 (path: 'a.b.c') """
        keys = path.split('.')
        curr = data
        for k in keys:
            if isinstance(curr, dict) and k in curr:
                curr = curr[k]
            else:
                return None
        return curr

    def filter_tree(self, text):
        """ 过滤树节点 """
        text = text.lower()
        
        def traverse(item):
            found = False
            # 检查当前节点
            if text in item.text(0).lower() or text in item.text(1).lower():
                found = True
            
            # 检查子节点
            for i in range(item.childCount()):
                child = item.child(i)
                if traverse(child):
                    found = True
            
            item.setHidden(not found)
            if found:
                item.setExpanded(True) # 展开匹配项
            return found

        root = self.tree.invisibleRootItem()
        for i in range(root.childCount()):
            traverse(root.child(i))

    def show_diff(self):
        old_json = json.dumps(self.full_data.get("old", {}), indent=2, ensure_ascii=False, sort_keys=True)
        new_json = json.dumps(self.full_data.get("new", {}), indent=2, ensure_ascii=False, sort_keys=True)
        
        diff = difflib.ndiff(old_json.splitlines(), new_json.splitlines())
        
        html = []
        for line in diff:
            if line.startswith("+ "):
                html.append(f'<span style="background-color: #e6ffec; color: #24292e;">{line}</span>')
            elif line.startswith("- "):
                html.append(f'<span style="background-color: #ffebe9; color: #24292e;">{line}</span>')
            elif line.startswith("? "):
                continue
            else:
                html.append(f'<span style="color: #6a737d;">{line}</span>')
        
        self.diff_text.setHtml("<br>".join(html))

    def get_id_name(self, item_id):
        """
        尝试从数据库查询 ID 对应的名称
        """
        if not item_id or str(item_id) == "0":
            return None
            
        try:
            db_path = os.path.join(get_base_dir(), "data", "eve_sde.db")
            if not os.path.exists(db_path):
                return None
                
            # 这里为了简单直接用 sqlite3，避免频繁开关连接
            # 实际生产中最好复用连接池，但这里只是偶尔查询，影响不大
            import sqlite3
            conn = sqlite3.connect(db_path, timeout=5)
            cursor = conn.cursor()
            cursor.execute("SELECT name_zh, name_en FROM items WHERE id = ?", (str(item_id),))
            row = cursor.fetchone()
            conn.close()
            
            if row:
                zh, en = row
                if zh: return zh
                if en: return en
                
            return None
        except:
            return None

    def populate_tree(self, parent_item, data):
        """
        递归填充树形节点 (带样式 + ID解析)
        """
        # 定义样式字体
        font_key = QFont("Segoe UI", 10)
        font_key.setBold(True)
        
        font_value = QFont("Consolas", 10) # 等宽字体适合显示数值和代码
        
        # 颜色定义
        COLOR_STRING = Qt.GlobalColor.darkGreen
        COLOR_NUMBER = Qt.GlobalColor.blue
        COLOR_BOOL = Qt.GlobalColor.darkMagenta
        COLOR_NULL = Qt.GlobalColor.gray
        COLOR_KEY = Qt.GlobalColor.black
        COLOR_ID_LINK = Qt.GlobalColor.darkCyan # 关联ID的颜色

        if isinstance(data, dict):
            for key in sorted(data.keys()):
                value = data[key]
                item = QTreeWidgetItem(parent_item)
                
                # 设置 Key 样式
                item.setText(0, str(key))
                item.setFont(0, font_key)
                item.setForeground(0, COLOR_KEY)
                
                if isinstance(value, (dict, list)):
                    self.populate_tree(item, value)
                    if not value:
                         item.setText(1, "[]" if isinstance(value, list) else "{}")
                         item.setForeground(1, COLOR_NULL)
                else:
                    # 检查是否是 ID 字段
                    display_text = str(value)
                    is_id_field = False
                    
                    if isinstance(value, (int, str)) and str(key).lower().endswith("id"):
                        # 尝试查询 ID 名称
                        linked_name = self.get_id_name(value)
                        if linked_name:
                            display_text = f"{value} ({linked_name})"
                            is_id_field = True
                    
                    item.setText(1, display_text)
                    item.setFont(1, font_value)
                    item.setToolTip(1, display_text)
                    
                    # 设置 Value 颜色
                    if is_id_field:
                        item.setForeground(1, COLOR_ID_LINK)
                        # 可以加粗或者下划线提示比较特殊
                        f = QFont(font_value)
                        f.setBold(True)
                        item.setFont(1, f)
                    elif isinstance(value, str):
                        item.setForeground(1, COLOR_STRING)
                    elif isinstance(value, (int, float)):
                        item.setForeground(1, COLOR_NUMBER)
                    elif isinstance(value, bool):
                        item.setForeground(1, COLOR_BOOL)
                    elif value is None:
                        item.setText(1, "null")
                        item.setForeground(1, COLOR_NULL)
                    
        elif isinstance(data, list):
            for index, value in enumerate(data):
                item = QTreeWidgetItem(parent_item)
                
                # 数组索引样式
                item.setText(0, f"[{index}]")
                item.setFont(0, font_key)
                item.setForeground(0, Qt.GlobalColor.darkGray)
                
                if isinstance(value, (dict, list)):
                    self.populate_tree(item, value)
                    if not value:
                         item.setText(1, "[]" if isinstance(value, list) else "{}")
                         item.setForeground(1, COLOR_NULL)
                else:
                    item.setText(1, str(value))
                    item.setFont(1, font_value)
                    item.setToolTip(1, str(value))
                    
                    if isinstance(value, str):
                        item.setForeground(1, COLOR_STRING)
                    elif isinstance(value, (int, float)):
                        item.setForeground(1, COLOR_NUMBER)
                    elif isinstance(value, bool):
                        item.setForeground(1, COLOR_BOOL)
                    elif value is None:
                        item.setText(1, "null")
                        item.setForeground(1, COLOR_NULL)

    def copy_raw(self, text):
        QApplication.clipboard().setText(text)
        QMessageBox.information(self, "提示", "原始 JSON 已复制到剪贴板！")

    def show_context_menu(self, position):
        selected_items = self.tree.selectedItems()
        if not selected_items:
            return

        menu = QMenu()
        
        # 动作：复制值
        copy_value_action = QAction("复制值 (Value)", self)
        copy_value_action.triggered.connect(lambda: self.copy_selected_items(selected_items, "value"))
        
        # 动作：复制键
        copy_key_action = QAction("复制键 (Key)", self)
        copy_key_action.triggered.connect(lambda: self.copy_selected_items(selected_items, "key"))
        
        # 动作：复制键值对
        copy_pair_action = QAction("复制键值对 (Key: Value)", self)
        copy_pair_action.triggered.connect(lambda: self.copy_selected_items(selected_items, "pair"))
        
        menu.addAction(copy_value_action)
        menu.addAction(copy_key_action)
        menu.addAction(copy_pair_action)
        
        menu.exec(self.tree.viewport().mapToGlobal(position))

    def copy_selected_items(self, items, mode):
        text_list = []
        for item in items:
            key = item.text(0)
            value = item.text(1)
            
            if mode == "value":
                if value: text_list.append(value)
            elif mode == "key":
                if key: text_list.append(key)
            elif mode == "pair":
                if value:
                    text_list.append(f"{key}: {value}")
                else:
                    text_list.append(key)
        
        if text_list:
            final_text = "\n".join(text_list)
            QApplication.clipboard().setText(final_text)

class UpdateHistoryWindow(QWidget):
    """
    更新历史窗口
    """
    def __init__(self, parent=None):
        super().__init__(parent, Qt.Window)
        self.setWindowTitle("更新历史记录")
        self.resize(600, 400)
        
        layout = QVBoxLayout(self)
        
        label = QLabel("本地更新日志 (双击查看):")
        layout.addWidget(label)
        
        self.list_widget = QListWidget()
        self.list_widget.itemDoubleClicked.connect(self.open_log)
        layout.addWidget(self.list_widget)
        
        self.refresh_logs()
        
        refresh_btn = QPushButton("刷新列表")
        refresh_btn.clicked.connect(self.refresh_logs)
        layout.addWidget(refresh_btn)
        
        self.detail_windows = []

    def refresh_logs(self):
        self.list_widget.clear()
        update_dir = os.path.join(get_base_dir(), "eve_sde_update")
        if not os.path.exists(update_dir):
            self.list_widget.addItem("暂无更新记录")
            return
            
        files = [f for f in os.listdir(update_dir) if f.endswith(".jsonl")]
        # 按时间倒序
        files.sort(reverse=True)
        
        for f in files:
            self.list_widget.addItem(f)

    def open_log(self, item):
        file_name = item.text()
        if not file_name.endswith(".jsonl"):
            return
            
        file_path = os.path.join(get_base_dir(), "eve_sde_update", file_name)
        
        # 读取文件内容，每一行是一个变更记录
        # 由于可能很多，我们可以用一个列表展示
        viewer = ChangeLogViewer(file_path)
        viewer.show()
        self.detail_windows.append(viewer)
        self.detail_windows = [w for w in self.detail_windows if w.isVisible()]

class ChangeLogViewer(QWidget):
    """
    展示具体的变更日志内容
    """
    def __init__(self, file_path, parent=None):
        super().__init__(parent, Qt.Window)
        self.setWindowTitle(f"变更详情: {os.path.basename(file_path)}")
        self.resize(800, 600)
        
        layout = QVBoxLayout(self)
        
        self.table = QTableWidget()
        self.table.setColumnCount(5)
        self.table.setHorizontalHeaderLabels(["状态", "来源表", "ID", "名称 (若有)", "查看"])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.Stretch)
        self.table.setAlternatingRowColors(True)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.itemDoubleClicked.connect(self.show_detail)
        
        layout.addWidget(self.table)
        
        self.load_data(file_path)
        self.detail_windows = []

    def load_data(self, file_path):
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                row = 0
                for line in f:
                    try:
                        data = json.loads(line)
                        source = data.get("_source_table", "Unknown")
                        item_id = str(data.get("_key") or data.get("id") or "N/A")
                        status = data.get("_status", "changed") # 默认为 changed (兼容旧日志)
                        
                        name = ""
                        name_data = data.get("name")
                        if isinstance(name_data, dict):
                            name = name_data.get("zh") or name_data.get("en") or str(name_data)
                        elif isinstance(name_data, str):
                            name = name_data
                            
                        self.table.insertRow(row)
                        
                        # status item with color
                        status_item = QTableWidgetItem(self.translate_status(status))
                        if status == "added":
                            status_item.setForeground(Qt.GlobalColor.darkGreen)
                        elif status == "removed":
                            status_item.setForeground(Qt.GlobalColor.red)
                        elif status == "changed":
                            status_item.setForeground(Qt.GlobalColor.blue)
                        
                        self.table.setItem(row, 0, status_item)
                        self.table.setItem(row, 1, QTableWidgetItem(source))
                        self.table.setItem(row, 2, QTableWidgetItem(item_id))
                        self.table.setItem(row, 3, QTableWidgetItem(name))
                        self.table.setItem(row, 4, QTableWidgetItem("双击查看"))
                        
                        # 存储完整 JSON
                        self.table.item(row, 0).setData(Qt.UserRole, line)
                        
                        row += 1
                    except:
                        continue
        except Exception as e:
            QMessageBox.warning(self, "错误", f"无法读取文件: {e}")

    def translate_status(self, status):
        if status == "added": return "新增"
        if status == "removed": return "删除"
        if status == "changed": return "修改"
        return status

    def show_detail(self, item):
        row = item.row()
        json_str = self.table.item(row, 0).data(Qt.UserRole)
        if json_str:
            detail_win = DetailWindow(json_str)
            detail_win.show()
            self.detail_windows.append(detail_win)
            self.detail_windows = [w for w in self.detail_windows if w.isVisible()]

class EveSearchApp(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("EVE SDE 数据库搜索工具")
        self.resize(1000, 700)
        
        # 设置窗口图标
        icon_path = get_resource_path("1.jpg")
        if os.path.exists(icon_path):
            self.setWindowIcon(QIcon(icon_path))
            
        self.setup_ui()
        self.worker = None
        self.update_worker = None
        self.index_worker = None
        self.detail_windows = [] # 防止窗口被垃圾回收
        self.history_window = None
        
        # 启动时检查索引
        QThread.msleep(100) # Give UI a moment
        self.check_index_on_startup()

    def check_index_on_startup(self):
        db_path = os.path.join(get_base_dir(), "data", "eve_sde.db")
        if not os.path.exists(db_path):
            reply = QMessageBox.question(self, "索引缺失", "未检测到搜索索引数据库，是否立即构建？\n(构建索引可以显著加快搜索速度)",
                                         QMessageBox.Yes | QMessageBox.No, QMessageBox.Yes)
            if reply == QMessageBox.Yes:
                self.start_index_build()

    def start_index_build(self):
        if self.index_worker and self.index_worker.isRunning():
            return
            
        self.rebuild_btn.setEnabled(False)
        self.search_btn.setEnabled(False)
        self.progress_bar.show()
        
        self.index_worker = IndexWorker()
        self.index_worker.progress.connect(self.index_progress)
        self.index_worker.finished.connect(self.index_finished)
        self.index_worker.start()
        
    def index_progress(self, msg, percent):
        self.status_label.setText(msg)
        self.progress_bar.setValue(percent)
        
    def index_finished(self, success, msg):
        self.rebuild_btn.setEnabled(True)
        self.search_btn.setEnabled(True)
        self.progress_bar.hide()
        self.status_label.setText(msg)
        
        if success:
            QMessageBox.information(self, "完成", msg)
        else:
            QMessageBox.critical(self, "失败", msg)

    def setup_ui(self):
        # 主窗口部件
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        layout = QVBoxLayout(central_widget)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(15)

        # 1. 标题区域
        title_layout = QHBoxLayout()
        title_label = QLabel("EVE Online SDE Search")
        title_label.setFont(QFont("Microsoft YaHei", 18, QFont.Weight.Bold))
        title_layout.addStretch()
        title_layout.addWidget(title_label)
        title_layout.addStretch()
        
        # 添加更新相关按钮
        self.update_btn = QPushButton("检查更新")
        self.update_btn.clicked.connect(self.start_update)
        title_layout.addWidget(self.update_btn)
        
        self.rebuild_btn = QPushButton("重建索引")
        self.rebuild_btn.clicked.connect(self.start_index_build)
        title_layout.addWidget(self.rebuild_btn)
        
        self.history_btn = QPushButton("更新历史")
        self.history_btn.clicked.connect(self.show_history)
        title_layout.addWidget(self.history_btn)
        
        layout.addLayout(title_layout)

        # 2. 搜索输入区域
        search_layout = QHBoxLayout()
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("请输入关键词 (例如: 乌鸦级, Tritanium, 34 ...)")
        self.search_input.setFont(QFont("Microsoft YaHei", 12))
        self.search_input.setMinimumHeight(40)
        self.search_input.returnPressed.connect(self.start_search) # 回车搜索
        
        self.search_btn = QPushButton("搜索")
        self.search_btn.setFont(QFont("Microsoft YaHei", 12))
        self.search_btn.setMinimumHeight(40)
        self.search_btn.setMinimumWidth(100)
        self.search_btn.clicked.connect(self.start_search)

        search_layout.addWidget(self.search_input)
        search_layout.addWidget(self.search_btn)
        layout.addLayout(search_layout)

        # 3. 结果表格
        self.table = QTableWidget()
        self.table.setColumnCount(4)
        self.table.setHorizontalHeaderLabels(["源文件", "ID", "中文名称", "英文名称"])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents) 
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)          
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.Stretch)          
        self.table.setAlternatingRowColors(True) 
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows) 
        self.table.setEditTriggers(QTableWidget.NoEditTriggers) # 禁止编辑
        self.table.setFont(QFont("Microsoft YaHei", 10))
        
        # 启用右键菜单
        self.table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self.show_context_menu)
        
        # 绑定双击事件
        self.table.itemDoubleClicked.connect(self.show_detail)

        layout.addWidget(self.table)

        # 4. 状态栏和进度条
        status_layout = QHBoxLayout()
        self.status_label = QLabel("准备就绪")
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.hide()
        
        status_layout.addWidget(self.status_label)
        status_layout.addStretch()
        status_layout.addWidget(self.progress_bar)
        layout.addLayout(status_layout)

    def start_search(self):
        keyword = self.search_input.text().strip()
        if not keyword:
            QMessageBox.warning(self, "提示", "请输入搜索关键词！")
            return

        if self.worker and self.worker.isRunning():
            self.worker.stop()
            self.worker.wait()

        self.table.setRowCount(0)
        self.status_label.setText(f"正在全库搜索: '{keyword}' ...")
        self.search_btn.setText("停止")
        self.search_btn.clicked.disconnect()
        self.search_btn.clicked.connect(self.stop_search)
        self.search_input.setEnabled(False)
        self.progress_bar.setRange(0, 0) # 忙碌状态
        self.progress_bar.show()

        self.worker = SearchWorker(keyword)
        self.worker.result_found.connect(self.add_result)
        self.worker.finished.connect(self.search_finished)
        self.worker.error.connect(self.search_error)
        self.worker.start()

    def stop_search(self):
        if self.worker and self.worker.isRunning():
            self.worker.stop()
            self.status_label.setText("搜索已手动停止")
            self.search_finished(self.table.rowCount())

    def add_result(self, file_name, item_id, name_zh, name_en, json_str):
        row = self.table.rowCount()
        self.table.insertRow(row)
        
        self.table.setItem(row, 0, QTableWidgetItem(file_name))
        self.table.setItem(row, 1, QTableWidgetItem(item_id))
        self.table.setItem(row, 2, QTableWidgetItem(name_zh))
        self.table.setItem(row, 3, QTableWidgetItem(name_en))
        
        # 将完整 JSON 存储在第一个单元格的 UserRole 数据中，方便后续获取
        self.table.item(row, 0).setData(Qt.UserRole, json_str)

    def search_finished(self, total_count):
        self.status_label.setText(f"搜索完成，共找到 {total_count} 个结果。")
        self.reset_ui_state()

    def search_error(self, error_msg):
        QMessageBox.critical(self, "错误", error_msg)
        self.status_label.setText("发生错误")
        self.reset_ui_state()

    def reset_ui_state(self):
        self.progress_bar.hide()
        self.search_input.setEnabled(True)
        self.search_btn.setText("搜索")
        try:
            self.search_btn.clicked.disconnect()
        except:
            pass
        self.search_btn.clicked.connect(self.start_search)
        self.search_input.setFocus()

    def show_context_menu(self, position):
        # 获取选中的行
        indexes = self.table.selectedIndexes()
        if not indexes:
            return
            
        row = indexes[0].row()
        
        # 获取数据
        file_name = self.table.item(row, 0).text()
        item_id = self.table.item(row, 1).text()
        name_zh = self.table.item(row, 2).text()
        name_en = self.table.item(row, 3).text()
        
        menu = QMenu()
        
        # 定义动作
        copy_id_action = QAction(f"复制 ID: {item_id}", self)
        copy_zh_action = QAction(f"复制中文名: {name_zh}", self)
        copy_en_action = QAction(f"复制英文名: {name_en}", self)
        view_detail_action = QAction("查看详细信息", self)
        
        # 绑定动作
        copy_id_action.triggered.connect(lambda: self.copy_to_clipboard(item_id, "ID"))
        copy_zh_action.triggered.connect(lambda: self.copy_to_clipboard(name_zh, "中文名"))
        copy_en_action.triggered.connect(lambda: self.copy_to_clipboard(name_en, "英文名"))
        view_detail_action.triggered.connect(lambda: self.show_detail_by_row(row))
        
        menu.addAction(copy_id_action)
        menu.addAction(copy_zh_action)
        menu.addAction(copy_en_action)
        menu.addSeparator()
        menu.addAction(view_detail_action)
        
        menu.exec(self.table.viewport().mapToGlobal(position))

    def copy_to_clipboard(self, text, type_name):
        clipboard = QApplication.clipboard()
        clipboard.setText(text)
        self.status_label.setText(f"已复制 {type_name}: {text}")

    def show_detail(self, item):
        self.show_detail_by_row(item.row())

    def show_detail_by_row(self, row):
        # 从第一列的 UserRole 获取完整 JSON
        json_str = self.table.item(row, 0).data(Qt.UserRole)
        
        if json_str:
            detail_win = DetailWindow(json_str)
            detail_win.show()
            self.detail_windows.append(detail_win) # 保持引用
            
            # 清理已关闭的窗口引用
            self.detail_windows = [w for w in self.detail_windows if w.isVisible()]

    def start_update(self):
        if self.update_worker and self.update_worker.isRunning():
            QMessageBox.warning(self, "提示", "更新正在进行中，请稍候...")
            return
            
        self.update_btn.setEnabled(False)
        self.progress_bar.show()
        self.status_label.setText("正在启动更新流程...")
        
        self.update_worker = UpdateWorker()
        self.update_worker.progress.connect(self.update_progress)
        self.update_worker.finished.connect(self.update_finished)
        self.update_worker.start()
        
    def update_progress(self, msg):
        self.status_label.setText(msg)
        
    def update_finished(self, success, msg):
        self.update_btn.setEnabled(True)
        self.progress_bar.hide()
        self.status_label.setText(msg)
        
        if success:
            QMessageBox.information(self, "更新完成", msg)
            # 自动打开历史记录
            self.show_history()
        else:
            QMessageBox.critical(self, "更新失败", msg)

    def show_history(self):
        if not self.history_window:
            self.history_window = UpdateHistoryWindow()
        
        self.history_window.refresh_logs()
        self.history_window.show()
        self.history_window.raise_()

if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    window = EveSearchApp()
    window.show()
    sys.exit(app.exec_())
