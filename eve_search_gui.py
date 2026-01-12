# -*- coding: utf-8 -*-
"""
EVE SDE Search Tool (GUI)
-------------------------
A PyQt6-based tool for searching and browsing EVE Online Static Data Export (SDE).
Supports fuzzy search, token-based matching, and automatic updates.

Author: ChuanQiong
GitHub: [Your GitHub Repo Link]
Created: 2026
"""

import sys
import os
import json
import shutil
import zipfile
import requests
from PyQt6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, 
                             QHBoxLayout, QLineEdit, QPushButton, QTableWidget, 
                             QTableWidgetItem, QHeaderView, QLabel, QMessageBox,
                             QProgressBar, QMenu, QTextEdit, QTreeWidget, QTreeWidgetItem,
                             QListWidget)
from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtGui import QIcon, QFont, QAction, QCursor

# 尝试导入 eve_search 中的配置和函数
try:
    import eve_search
    # 强制重新计算路径（防止导入缓存导致路径错误）
    if getattr(sys, 'frozen', False):
        eve_search.SDE_DIR = os.path.join(os.path.dirname(sys.executable), "eve_sde_jsonl")
except ImportError:
    eve_search = None

# 定义获取 SDE 目录的辅助函数
def get_base_dir():
    if getattr(sys, 'frozen', False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))

def get_resource_path(relative_path):
    """ 获取资源文件的绝对路径 (支持开发环境和打包环境) """
    if hasattr(sys, '_MEIPASS'):
        return os.path.join(sys._MEIPASS, relative_path)
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), relative_path)

def get_sde_dir():
    if eve_search:
        return eve_search.SDE_DIR
    return os.path.join(get_base_dir(), "eve_sde_jsonl")

class SearchWorker(QThread):
    """
    后台搜索线程
    """
    result_found = pyqtSignal(str, str, str, str, str)  # 信号：文件名, ID, 中文名, 英文名, 完整JSON字符串
    finished = pyqtSignal(int)  # 信号：总找到的数量
    error = pyqtSignal(str) # 信号：错误信息

    def __init__(self, keyword):
        super().__init__()
        self.keyword = keyword
        self.is_running = True

    def run(self):
        total_found = 0
        sde_dir = get_sde_dir()
        
        if not os.path.exists(sde_dir):
            self.error.emit(f"未找到数据目录: {sde_dir}\n请确保 'eve_sde_jsonl' 文件夹在程序同一目录下。")
            return

        files = [f for f in os.listdir(sde_dir) if f.endswith(".jsonl")]
        
        # 预处理关键词：转小写并按空格分割
        keyword_lower = self.keyword.lower()
        keywords_list = keyword_lower.split()

        for file_name in files:
            if not self.is_running:
                break
            
            file_path = os.path.join(sde_dir, file_name)
            try:
                with open(file_path, "r", encoding="utf-8") as f:
                    for line in f:
                        if not self.is_running:
                            break
                        try:
                            data = json.loads(line)
                            
                            # 获取 ID
                            item_id = data.get("_key") or data.get("id") or data.get("typeID")
                            
                            # 获取名字
                            name_data = data.get("name", {})
                            name_en = ""
                            name_zh = ""
                            if isinstance(name_data, dict):
                                name_en = name_data.get("en", "")
                                name_zh = name_data.get("zh", "")
                            elif isinstance(name_data, str):
                                name_en = name_data
                                name_zh = name_data
                            
                            # 匹配逻辑 (多关键词混杂匹配 + 模糊子序列匹配)
                            # 将中英文名合并为一个字符串进行搜索
                            full_text = (name_en + " " + name_zh).lower()
                            
                            is_match = True
                            for kw in keywords_list:
                                # 1. 尝试直接子串匹配 (最快)
                                if kw in full_text:
                                    continue
                                
                                # 2. 尝试子序列匹配 (例如 "高辟邪" 匹配 "高级辟邪")
                                # 检查 kw 中的字符是否按顺序出现在 full_text 中
                                iterator = iter(full_text)
                                if not all(char in iterator for char in kw):
                                    is_match = False
                                    break
                            
                            if is_match:
                                display_id = str(item_id) if item_id is not None else "N/A"
                                # 发送包含完整 JSON 行的信号
                                self.result_found.emit(file_name, display_id, name_zh, name_en, line.strip())
                                total_found += 1
                        except:
                            continue
            except:
                pass
        
        self.finished.emit(total_found)

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
                    
                changeds = line_data.get("changed", [])
                if not changeds: continue
                
                self.progress.emit(f"正在处理变更: {key} ({len(changeds)} 条)")
                
                # 读取对应的 jsonl 文件
                source_file = os.path.join(sde_dir, f"{key}.jsonl")
                if not os.path.exists(source_file):
                    continue
                    
                # 建立 ID 索引以便快速查找 (为了性能，可以只读取需要的行，或者全部读取建立索引)
                # 由于文件可能很大，逐行读取比较稳妥
                
                # 优化：先将 changeds 转为集合
                changed_set = set(changeds)
                
                with open(source_file, "r", encoding="utf-8") as f:
                    for f_line in f:
                        try:
                            data = json.loads(f_line)
                            item_id = data.get("_key") # 大部分表的主键是 _key
                            # 部分表可能用 id 或其他字段，这里需要根据实际情况兼容
                            # 假设 changes 日志里的 ID 对应 _key
                            
                            if item_id in changed_set:
                                # 写入变更文件
                                with open(changes_file, "a", encoding="utf-8") as cf:
                                    # 额外添加一个字段表明来源表，方便查看
                                    data["_source_table"] = key
                                    cf.write(json.dumps(data, ensure_ascii=False) + "\n")
                        except:
                            continue
            except:
                continue
                
        self.progress.emit(f"变更日志已保存: {changes_file}")


class DetailWindow(QWidget):
    """
    详情展示窗口 (树形结构)
    """
    def __init__(self, json_str, parent=None):
        super().__init__(parent, Qt.WindowType.Window)
        self.setWindowTitle("条目详细信息")
        self.resize(700, 600)
        
        layout = QVBoxLayout(self)
        
        # 1. 顶部标签
        label = QLabel("详细属性 (可右键复制):")
        label.setFont(QFont("Microsoft YaHei", 12, QFont.Weight.Bold))
        layout.addWidget(label)
        
        # 2. 树形控件
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["属性 (Key)", "值 (Value)"])
        self.tree.setColumnWidth(0, 250) # 增加 Key 列的宽度
        self.tree.setAlternatingRowColors(True)
        self.tree.setFont(QFont("Microsoft YaHei", 10))
        # 启用多选，方便复制多个
        self.tree.setSelectionMode(QTreeWidget.SelectionMode.ExtendedSelection)
        
        # 启用右键菜单
        self.tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self.show_context_menu)

        layout.addWidget(self.tree)
        
        # 3. 解析并填充数据
        try:
            data = json.loads(json_str)
            self.populate_tree(self.tree.invisibleRootItem(), data)
            self.tree.expandToDepth(0) # 默认展开第一层
        except Exception as e:
            # 如果解析失败，回退显示原始文本
            fallback_item = QTreeWidgetItem(self.tree)
            fallback_item.setText(0, "Error")
            fallback_item.setText(1, f"JSON解析失败: {e}")
            
            raw_item = QTreeWidgetItem(self.tree)
            raw_item.setText(0, "Raw Data")
            raw_item.setText(1, json_str)

        # 4. 底部按钮
        btn_layout = QHBoxLayout()
        copy_all_btn = QPushButton("复制原始JSON")
        copy_all_btn.clicked.connect(lambda: self.copy_raw(json_str))
        
        expand_btn = QPushButton("全部展开")
        expand_btn.clicked.connect(self.tree.expandAll)
        
        collapse_btn = QPushButton("全部折叠")
        collapse_btn.clicked.connect(self.tree.collapseAll)

        close_btn = QPushButton("关闭")
        close_btn.clicked.connect(self.close)
        
        btn_layout.addWidget(expand_btn)
        btn_layout.addWidget(collapse_btn)
        btn_layout.addStretch()
        btn_layout.addWidget(copy_all_btn)
        btn_layout.addWidget(close_btn)
        layout.addLayout(btn_layout)

    def populate_tree(self, parent_item, data):
        """
        递归填充树形节点
        """
        if isinstance(data, dict):
            # 对字典键进行排序，方便查看
            for key in sorted(data.keys()):
                value = data[key]
                item = QTreeWidgetItem(parent_item)
                item.setText(0, str(key))
                
                if isinstance(value, (dict, list)):
                    # 如果是复杂结构，继续递归
                    self.populate_tree(item, value)
                    # 如果是空字典或列表，显示标记
                    if not value:
                         item.setText(1, "[]" if isinstance(value, list) else "{}")
                else:
                    # 如果是基本类型，直接显示值
                    item.setText(1, str(value))
                    item.setToolTip(1, str(value)) # 添加提示以便查看长文本
                    
        elif isinstance(data, list):
            for index, value in enumerate(data):
                item = QTreeWidgetItem(parent_item)
                item.setText(0, f"[{index}]")
                
                if isinstance(value, (dict, list)):
                    self.populate_tree(item, value)
                    if not value:
                         item.setText(1, "[]" if isinstance(value, list) else "{}")
                else:
                    item.setText(1, str(value))
                    item.setToolTip(1, str(value))

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
        super().__init__(parent, Qt.WindowType.Window)
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
        super().__init__(parent, Qt.WindowType.Window)
        self.setWindowTitle(f"变更详情: {os.path.basename(file_path)}")
        self.resize(800, 600)
        
        layout = QVBoxLayout(self)
        
        self.table = QTableWidget()
        self.table.setColumnCount(4)
        self.table.setHorizontalHeaderLabels(["来源表", "ID", "名称 (若有)", "查看"])
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self.table.setAlternatingRowColors(True)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
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
                        
                        name = ""
                        name_data = data.get("name")
                        if isinstance(name_data, dict):
                            name = name_data.get("zh") or name_data.get("en") or str(name_data)
                        elif isinstance(name_data, str):
                            name = name_data
                            
                        self.table.insertRow(row)
                        self.table.setItem(row, 0, QTableWidgetItem(source))
                        self.table.setItem(row, 1, QTableWidgetItem(item_id))
                        self.table.setItem(row, 2, QTableWidgetItem(name))
                        self.table.setItem(row, 3, QTableWidgetItem("双击查看"))
                        
                        # 存储完整 JSON
                        self.table.item(row, 0).setData(Qt.ItemDataRole.UserRole, line)
                        
                        row += 1
                    except:
                        continue
        except Exception as e:
            QMessageBox.warning(self, "错误", f"无法读取文件: {e}")

    def show_detail(self, item):
        row = item.row()
        json_str = self.table.item(row, 0).data(Qt.ItemDataRole.UserRole)
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
        self.detail_windows = [] # 防止窗口被垃圾回收
        self.history_window = None

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
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents) 
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)          
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)          
        self.table.setAlternatingRowColors(True) 
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows) 
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers) # 禁止编辑
        self.table.setFont(QFont("Microsoft YaHei", 10))
        
        # 启用右键菜单
        self.table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self.show_context_menu)
        
        # 绑定双击事件
        self.table.itemDoubleClicked.connect(self.show_detail)

        layout.addWidget(self.table)

        # 4. 状态栏和进度条
        status_layout = QHBoxLayout()
        self.status_label = QLabel("准备就绪")
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 0) # 忙碌状态
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
        self.table.item(row, 0).setData(Qt.ItemDataRole.UserRole, json_str)

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
        json_str = self.table.item(row, 0).data(Qt.ItemDataRole.UserRole)
        
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
    sys.exit(app.exec())
