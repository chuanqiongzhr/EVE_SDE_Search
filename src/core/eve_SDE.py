# -*- coding: utf-8 -*-
"""
EVE SDE Updater Script
----------------------
Handles downloading, extracting, and processing updates for EVE Online SDE.

Author: ChuanQiong
Created: 2026
"""

import requests
import os
import zipfile
import os
import shutil
import json

def read_SDE_latest_info():
    url = "https://developers.eveonline.com/static-data/tranquility/latest.jsonl"
    filename = "latest.jsonl"
    response = requests.get(url, stream=True).json()
    return response['_key'], response['buildNumber'], response['releaseDate']

def download_latest_eve_SDE_json():
    url = "https://developers.eveonline.com/static-data/eve-online-static-data-latest-jsonl.zip"
    filename = "eve_SDE_jsonl.zip"
    response = requests.get(url, stream=True)
    with open(filename, "wb") as f:
        shutil.copyfileobj(response.raw, f)
    print(f"下载完成，文件保存在: {filename}")
    # 解压
    print("正在解压...")
    with zipfile.ZipFile(filename, 'r') as zf:
        zf.extractall("eve_sde_jsonl")
    # 清理压缩包
    os.remove(filename)
    print(f"解压完成，文件保存在目录: eve_sde_jsonl")

def download_latest_eve_SDE_yaml():
    url = "https://developers.eveonline.com/static-data/eve-online-static-data-latest-yaml.zip"
    filename = "eve_SDE_yaml.zip"
    response = requests.get(url, stream=True)
    with open(filename, "wb") as f:
        shutil.copyfileobj(response.raw, f)
    print(f"下载完成，文件保存在: {filename}")
    # 解压
    print("正在解压...")
    with zipfile.ZipFile(filename, 'r') as zf:
        zf.extractall("eve_sde_yaml")
    # 清理压缩包
    os.remove(filename)
    print(f"解压完成，文件保存在目录: eve_sde_yaml")

def update_SDE():
    # 在文件夹_sde_jsonl和_sde_yaml和read_SDE_latest_info返回的buildNumber进行对比，不一致则更新
    latest_key, latest_buildNumber, latest_releaseDate = read_SDE_latest_info()
    if not os.path.exists("eve_sde_jsonl"): # or not os.path.exists("eve_sde_yaml"):
        print("SDE 文件夹不存在，正在下载最新版本...")
        download_latest_eve_SDE_json()
        # download_latest_eve_SDE_yaml()
    else:
        print("SDE 文件夹已存在，正在对比版本...")
        with open("eve_sde_jsonl/_sde.jsonl", "r", encoding="utf-8") as f:
            line = f.readline()  # 读取第一行
            data = json.loads(line)  # 解析 JSON 数据
            current_buildNumber = data["buildNumber"]
        if current_buildNumber != latest_buildNumber:
            print(f"目前版本{current_buildNumber}发现新的版本: {latest_buildNumber}，正在下载...")
            download_latest_eve_SDE_json()
            # download_latest_eve_SDE_yaml()
            print(f"更新完成，版本号: {latest_buildNumber}")
        else:
            print("目前版本已是最新版本，无需更新")
    print("SDE 更新完成")

def get_SDE_update():
    latest_key, latest_buildNumber, latest_releaseDate = read_SDE_latest_info()
    update_SDE()
    url = f"https://developers.eveonline.com/static-data/tranquility/changes/{latest_buildNumber}.jsonl"
    response = requests.get(url, stream=True).iter_lines()
    # 替换非法字符
    safe_release_date = latest_releaseDate.replace(":", "-")
    # 检查并创建目录
    output_dir = "eve_sde_update"
    os.makedirs(output_dir, exist_ok=True)  # 如果目录不存在，则创建
    changes_file = f"eve_sde_update/eve_sde_changes_{safe_release_date}.jsonl"
    
    # 清空或创建变更文件
    with open(changes_file, "w", encoding="utf-8") as cf:
        pass
        
    for line in response:
        if not line: continue
        try:
            line_data = json.loads(line)
            key = line_data.get("_key")
            
            if key == '_meta':
                print(f"更新版本号：{line_data['buildNumber']} 发布日期：{line_data['releaseDate']}")
                continue
                
            added_ids = set(line_data.get("added", []))
            changed_ids = set(line_data.get("changed", []))
            removed_ids = set(line_data.get("removed", []))
            
            if not (added_ids or changed_ids or removed_ids): continue
            
            print(f"处理变更: {key} (新增:{len(added_ids)} 修改:{len(changed_ids)} 删除:{len(removed_ids)})")
            
            # 1. Removed
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
            
            # 2. Added/Changed
            if added_ids or changed_ids:
                source_path = f"eve_sde_jsonl/{key}.jsonl"
                if os.path.exists(source_path):
                    with open(source_path, "r", encoding="utf-8") as f:
                        for f_line in f:
                            try:
                                data = json.loads(f_line)
                                item_id = data.get("_key")
                                status = None
                                if item_id in added_ids:
                                    status = "added"
                                elif item_id in changed_ids:
                                    status = "changed"
                                
                                if status:
                                    data["_source_table"] = key
                                    data["_status"] = status
                                    with open(changes_file, "a", encoding="utf-8") as cf:
                                        cf.write(json.dumps(data, ensure_ascii=False) + "\n")
                            except: pass
        except Exception as e:
            print(f"Error processing line: {e}")
            
    print(f"更新完成，变更文件保存在: {changes_file}")
    

if __name__ == "__main__":
    # download_latest_eve_SDE_json()
    # changes = get_SDE_update()
    # print(changes)
    # download_latest_eve_SDE_yaml()
    get_SDE_update()
    pass