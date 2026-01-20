# EVE Online SDE Search Tool

![Python](https://img.shields.io/badge/Python-3.8%2B-blue)
![PyQt5](https://img.shields.io/badge/GUI-PyQt5-green)
![EVE Online](https://img.shields.io/badge/Game-EVE%20Online-orange)

这是一个专为 EVE Online 玩家和开发者设计的静态数据导出 (SDE) 浏览与搜索工具。它提供了极速的本地搜索体验、自动化的数据更新以及详细的版本变更对比功能。

## ✨ 核心功能

### 🔍 极速搜索
*   **毫秒级响应**：基于 SQLite 构建本地索引，支持百万级数据秒搜。
*   **混合查询**：支持 **中文名称**、**英文名称**、**Type ID** 混合模糊搜索（空格分隔）。
*   **智能排序**：根据匹配度自动排序结果。

### 📊 深度详情面板
*   **可视化 JSON 树**：以美观的树形结构展示复杂的 SDE 数据，支持一键展开/折叠。
*   **智能 ID 解析**：自动识别属性中的 ID 字段（如 `graphicID`, `typeID`），并直接显示对应的物品名称，无需手动二次查询。
*   **代码级高亮**：根据数据类型（字符串、数字、布尔值）自动着色，阅读体验媲美 IDE。
*   **富文本支持**：完美渲染游戏内的 HTML 格式描述文本。

### 🔄 自动化更新与 Diff
*   **一键更新**：自动检测 EVE 官方开发者服务器的最新 SDE 版本并下载。
*   **变更追踪**：自动生成版本更新日志，记录新增、修改和删除的条目。
*   **差异对比 (Diff)**：内置 Diff 查看器，通过双栏视图高亮显示版本更新前后的属性变化（<font color="green">新增</font>/<font color="red">删除</font>/<font color="blue">修改</font>）。

## 🚀 快速开始

### 环境要求
*   Python 3.8 或更高版本
*   Windows / macOS / Linux

### 安装步骤

1.  **克隆项目**
    ```bash
    git clone <repository-url>
    cd EVE_SDE_Search
    ```

2.  **安装依赖**
    ```bash
    pip install -r requirements.txt
    ```

3.  **运行程序**
    ```bash
    python main.py
    ```

> **注意**：首次运行时，程序会提示构建索引。请点击 **Yes**，这可能需要几十秒时间，但构建完成后即可享受极速搜索。

## 📂 项目结构

```text
EVE_SDE_Search/
├── data/               # 存放数据库索引 (eve_sde.db)
├── eve_sde_jsonl/      # EVE SDE 原始数据文件 (自动下载)
├── eve_sde_update/     # 版本更新日志
├── resources/          # 图片等资源文件
├── src/                # 源代码
│   ├── core/           # 核心逻辑 (搜索、数据库、更新)
│   └── gui/            # 图形界面 (PyQt5)
├── main.py             # 程序入口
└── requirements.txt    # 依赖列表
```

## 🛠️ 技术栈

*   **GUI 框架**: PyQt5
*   **数据库**: SQLite3
*   **网络请求**: Requests
*   **数据处理**: JSON, Difflib

## 📝 常见问题

**Q: 搜索结果显示 ID 为空或 N/A？**
A: 请尝试点击主界面的“重建索引”按钮，确保数据库是最新的。

**Q: 如何查看版本更新的具体内容？**
A: 点击主界面右上角的“更新历史”，双击任意一条更新日志，然后在弹出的列表中双击蓝色（修改）或绿色（新增）的条目即可查看 Diff。

## License

MIT License
