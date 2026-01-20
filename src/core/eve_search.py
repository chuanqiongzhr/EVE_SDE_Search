import json
# -*- coding: utf-8 -*-
"""
EVE SDE Search Tool (CLI)
-------------------------
Command-line interface for searching EVE Online SDE data.

Author: ChuanQiong
Created: 2026
"""

import os
import sys

# 获取当前脚本或 EXE 所在的目录
if getattr(sys, 'frozen', False):
    # 如果是打包后的 exe
    BASE_DIR = os.path.dirname(sys.executable)
else:
    # 如果是 python 脚本
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# SDE 数据目录 (默认为当前目录下的 eve_sde_jsonl)
SDE_DIR = os.path.join(BASE_DIR, "eve_sde_jsonl")

def search_in_file(keyword, file_name):
    """
    在指定的 JSONL 文件中搜索关键词
    返回匹配到的行列表 (id, zh_name, en_name)
    """
    file_path = os.path.join(SDE_DIR, file_name)
    results = []
    keyword_lower = keyword.lower()

    try:
        with open(file_path, "r", encoding="utf-8") as f:
            for line in f:
                try:
                    data = json.loads(line)
                    
                    # 尝试获取 ID (支持 _key, id, typeID 等常见字段)
                    item_id = data.get("_key") or data.get("id") or data.get("typeID")
                    
                    # 获取 name 字典
                    name_data = data.get("name", {})
                    
                    name_en = ""
                    name_zh = ""
                    
                    # 处理不同格式的 name
                    if isinstance(name_data, dict):
                        name_en = name_data.get("en", "")
                        name_zh = name_data.get("zh", "")
                    elif isinstance(name_data, str):
                        name_en = name_data
                        name_zh = name_data
                    
                    # 如果没有名字，跳过 (或者可以搜索其他字段，暂时只搜名字)
                    if not name_en and not name_zh:
                        continue

                    # 检查匹配 (忽略大小写)
                    if keyword_lower in name_en.lower() or keyword_lower in name_zh.lower():
                        results.append((item_id, name_zh, name_en))

                except json.JSONDecodeError:
                    continue
    except Exception as e:
        # print(f"读取文件 {file_name} 出错: {e}") # 忽略读取错误，避免刷屏
        pass

    return results

def search_all_files(keyword):
    print(f"正在全库搜索 '{keyword}' ... (这可能需要几秒钟)")
    print("=" * 70)

    total_found = 0
    files = [f for f in os.listdir(SDE_DIR) if f.endswith(".jsonl")]
    
    for file_name in files:
        matches = search_in_file(keyword, file_name)
        
        if matches:
            total_found += len(matches)
            print(f"📄 文件: {file_name} (找到 {len(matches)} 项)")
            print("-" * 70)
            print(f"{'ID':<15} | {'中文名':<25} | {'英文名':<25}")
            print("-" * 70)
            
            for item_id, name_zh, name_en in matches:
                # 截断过长的名称
                display_zh = (name_zh[:23] + '..') if len(name_zh) > 23 else name_zh
                display_en = (name_en[:23] + '..') if len(name_en) > 23 else name_en
                # 处理 ID 为 None 的情况
                display_id = str(item_id) if item_id is not None else "N/A"
                
                print(f"{display_id:<15} | {display_zh:<25} | {display_en:<25}")
            
            print("=" * 70 + "\n")

    if total_found == 0:
        print("未找到任何匹配项。")
    else:
        print(f"全库搜索完成，共找到 {total_found} 个匹配项。")

if __name__ == "__main__":
    if len(sys.argv) > 1:
        search_keyword = " ".join(sys.argv[1:])
    else:
        search_keyword = "Tritanium"
        print("提示: 可以在命令行输入参数，例如: python eve_search.py 乌鸦级")
    
    search_all_files(search_keyword)
