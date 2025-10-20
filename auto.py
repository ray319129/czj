import os
import json
import re

# 圖片資料夾路徑
image_directory = "photo"  # 改為相對路徑
json_file_path = "assets/image_data.json"  # 改為相對路徑

# 初始化圖片資料
image_data = {}

# 如果 JSON 文件已存在，讀取原有資料
if os.path.exists(json_file_path):
    with open(json_file_path, 'r', encoding='utf-8') as json_file:
        image_data = json.load(json_file)

# 創建一個映射來存儲文件名到完整路徑的對應關係
file_path_map = {}
for root, dirs, files in os.walk(image_directory):
    for filename in files:
        if filename.endswith((".jpg", ".png", ".jpeg", ".PNG")):
            # 獲取相對於 photo 資料夾的路徑
            rel_path = os.path.relpath(root, image_directory)
            if rel_path == ".":
                file_path = filename
            else:
                file_path = f"{rel_path}/{filename}"
            
            # 存儲文件名到完整路徑的映射
            base_name = os.path.splitext(filename)[0]
            file_path_map[base_name] = file_path

# 更新現有數據的路徑
for image_name, image_info in image_data.items():
    if image_name in file_path_map:
        image_info['path'] = file_path_map[image_name]

# 計數器初始化，根據現有資料最大 ID 確保新 ID 連續
existing_ids = [int(v["id"][1:]) for v in image_data.values()]
counter = max(existing_ids, default=0) + 1

# 添加新圖片
for base_name, file_path in file_path_map.items():
    if base_name not in image_data:
        # 生成新ID
        image_id = f"a{counter:04d}"
        
        # 從路徑中提取角色名稱
        path_parts = file_path.split('/')
        character_name = "未知角色"
        
        # 優先從資料夾名稱中提取角色名稱
        for part in path_parts:
            character_match = re.search(r"【(.+?)】", part)
            if character_match:
                character_name = character_match.group(1)
                break
        
        # 如果資料夾名稱沒有角色名稱，則從文件名提取
        if character_name == "未知角色":
            character_match = re.search(r"【(.+?)】", base_name)
            if character_match:
                character_name = character_match.group(1)
        
        image_data[base_name] = {
            "id": image_id,
            "name": base_name,
            "path": file_path,
            "character": character_name
        }
        counter += 1

# 將結果寫入 JSON 文件
with open(json_file_path, 'w', encoding='utf-8') as json_file:
    json.dump(image_data, json_file, ensure_ascii=False, indent=4)

print(f"JSON 文件已儲存至 {json_file_path}")
