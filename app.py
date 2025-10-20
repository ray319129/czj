import os
import json
import random
import urllib.parse
import pandas as pd
import requests
from bs4 import BeautifulSoup
from flask import Flask, request, send_from_directory, abort
from linebot import LineBotApi, WebhookHandler
from linebot.models import (
    MessageEvent, TextMessage, TextSendMessage, ImageSendMessage,
    QuickReply, QuickReplyButton, MessageAction
)
from linebot.exceptions import LineBotApiError, InvalidSignatureError
from datetime import datetime, timedelta

# 使用環境變數來設定敏感資訊
LINE_CHANNEL_ACCESS_TOKEN = os.getenv("LINE_CHANNEL_ACCESS_TOKEN")
LINE_CHANNEL_SECRET = os.getenv("LINE_CHANNEL_SECRET")
RENDER_EXTERNAL_URL = os.getenv("RENDER_EXTERNAL_URL", "http://localhost:8000")
MEME_PAGE_URL = os.getenv("MEME_PAGE_URL")  # 設定網頁 URL

# 確認環境變數是否正確載入
if not LINE_CHANNEL_ACCESS_TOKEN or not LINE_CHANNEL_SECRET:
    raise ValueError("環境變數未正確設定，請確認 LINE_CHANNEL_ACCESS_TOKEN 和 LINE_CHANNEL_SECRET 已配置。")

# Line Bot 設定
line_bot_api = LineBotApi(LINE_CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(LINE_CHANNEL_SECRET)

# Flask 應用
app = Flask(__name__)

# 路徑設定
STATIC_IMAGE_PATH = "photo"  # 放置圖片的資料夾
json_file_path = os.path.join(os.path.dirname(__file__), 'assets', 'image_data.json')
excel_file_path = os.path.join(os.path.dirname(__file__), 'assets', '甄嬛傳直播馬拉松2025.xlsx')

# 設定資料儲存路徑
# 如果在 Render 上執行，使用 /data 目錄；否則使用本地的 data 目錄
if os.path.exists('/data'):
    DATA_DIR = '/data'
else:
    DATA_DIR = os.path.join(os.path.dirname(__file__), 'data')

incense_file_path = os.path.join(DATA_DIR, 'incense_count.json')

# 確保資料目錄存在
os.makedirs(DATA_DIR, exist_ok=True)

# 在初始化時添加
if not os.path.exists(os.path.dirname(incense_file_path)):
    os.makedirs(os.path.dirname(incense_file_path))

# 嘗試打開文件
try:
    with open(json_file_path, 'r', encoding='utf-8') as f:
        # 讀取檔案
        data = f.read()
        print("文件讀取成功")
except FileNotFoundError:
    print(f"錯誤: 找不到文件 {json_file_path}")
# 載入 JSON 資料庫
with open(json_file_path, 'r', encoding='utf-8') as f:
    image_data = json.load(f)

# 用戶狀態儲存
user_states = {}
user_last_image_index = {}

# Google Sheets API 設定
SCOPES = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
GOOGLE_SHEETS_CREDENTIALS = os.getenv('GOOGLE_SHEETS_CREDENTIALS')
SHEET_URL = os.getenv('SHEET_URL')  # Google Sheet 的網址

# 定義檔案路徑
incense_file_path = "assets/incense_data.json"

# 初始化時間戳記錄
user_timestamps = {}

def load_meme_data_from_web():
    try:
        # 發送 GET 請求到網頁
        response = requests.get(MEME_PAGE_URL)
        response.encoding = 'utf-8'  # 確保正確處理中文
        
        # 使用 BeautifulSoup 解析網頁
        soup = BeautifulSoup(response.text, 'html.parser')
        
        # 初始化 meme_data 字典
        meme_data = {}
        
        # 解析表格
        table = soup.find('table')
        if not table:
            print("找不到表格")
            return {}
            
        rows = table.find_all('tr')[1:]  # 跳過標題列
        for row in rows:
            cols = row.find_all('td')
            if len(cols) >= 12:  # 確保有足夠的欄位
                episode = cols[0].text.strip()  # 集數
                summary = cols[1].text.strip()  # 重點摘要
                
                # 正確組合日期和時間
                first_round = f"{cols[2].text.strip()} {cols[3].text.strip()}"   # 首輪
                second_round = f"{cols[4].text.strip()} {cols[5].text.strip()}"  # 二輪
                third_round = f"{cols[6].text.strip()} {cols[7].text.strip()}"   # 三輪
                fourth_round = f"{cols[8].text.strip()} {cols[9].text.strip()}"  # 四輪
                fifth_round = f"{cols[10].text.strip()} {cols[11].text.strip()}" # 五輪
                
                if summary:  # 使用重點摘要作為 key
                    meme_data[summary] = {
                        "episode": episode,
                        "first": first_round.strip(),
                        "second": second_round.strip(),
                        "third": third_round.strip(),
                        "fourth": fourth_round.strip(),
                        "fifth": fifth_round.strip()
                    }
        
        return meme_data
    except Exception as e:
        print(f"讀取網頁資料時發生錯誤: {str(e)}")
        return {}

# 載入梗資料
meme_data = load_meme_data_from_web()

# 定義狀態常量
STATE_INIT = 'initial'
STATE_WAITING_SEARCH_TYPE = 'waiting_search_type'
STATE_WAITING_ID = 'waiting_id'
STATE_WAITING_KEYWORD = 'waiting_keyword'
STATE_WAITING_QUESTION = 'waiting_question'
STATE_WAITING_SHOULD_I = 'waiting_should_i'
STATE_WAITING_CHARACTER = 'waiting_character'
STATE_WAITING_MEME = 'waiting_meme'  # 新增等待梗的狀態

# 讀取上香次數和時間記錄
def load_incense_count():
    try:
        if os.path.exists(incense_file_path):
            with open(incense_file_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
                return data.get('total_count', 0), data.get('user_counts', {})
        return 0, {}
    except Exception as e:
        print(f"Error loading incense count: {str(e)}")
        return 0, {}

# 保存上香次數和時間記錄
def save_incense_count(total_count, user_counts):
    try:
        with open(incense_file_path, 'w', encoding='utf-8') as f:
            json.dump({
                'total_count': total_count,
                'user_counts': user_counts
            }, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"Error saving incense count: {str(e)}")

# 初始化上香計數器和時間記錄
total_incense_count, user_incense_counts = load_incense_count()

# 用戶指令時間戳記錄
user_command_timestamps = {}
# 用戶超限提醒時間戳記錄
user_limit_warnings = {}

def check_command_rate_limit(user_id):
    current_time = datetime.now().timestamp()
    # 獲取用戶的指令時間戳記錄
    if user_id not in user_command_timestamps:
        user_command_timestamps[user_id] = []
    
    # 清理超過10秒的記錄
    ten_seconds_ago = current_time - 10
    user_command_timestamps[user_id] = [t for t in user_command_timestamps[user_id] if t > ten_seconds_ago]
    
    # 檢查10秒內的指令次數
    if len(user_command_timestamps[user_id]) >= 7:
        # 檢查是否已經發送過警告
        last_warning = user_limit_warnings.get(user_id, 0)
        if current_time - last_warning > 10:  # 如果是新的超限週期
            user_limit_warnings[user_id] = current_time
            return False, "小主慢一點，朕跟不上了～請等待幾秒再試"
        return False, None  # 已經警告過，直接忽略
    
    # 記錄新的指令時間戳
    user_command_timestamps[user_id].append(current_time)
    return True, None

@app.route("/callback", methods=['POST'])
def callback():
    signature = request.headers['X-Line-Signature']
    body = request.get_data(as_text=True)
    
    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        abort(400)
    return 'OK'

@app.route('/images/<path:filename>')
def serve_image(filename):
    decoded_filename = urllib.parse.unquote(filename)
    return send_from_directory(STATIC_IMAGE_PATH, decoded_filename)

def create_navigation_buttons(is_group=False):
    # 根據是否為群組來決定按鈕文字
    prev_text = "!上一張" if is_group else "上一張"
    next_text = "!下一張" if is_group else "下一張"
    menu_text = "!menu" if is_group else "menu"
    
    return QuickReply(items=[
        QuickReplyButton(action=MessageAction(label="上一張", text=prev_text)),
        QuickReplyButton(action=MessageAction(label="下一張", text=next_text)),
        QuickReplyButton(action=MessageAction(label="Menu", text=menu_text))
    ])

def send_image_by_index(event, index):
    user_id = event.source.user_id
    image_keys = list(image_data.keys())
    if 0 <= index < len(image_keys):
        img = image_data[image_keys[index]]
        encoded_path = urllib.parse.quote(img['path'])
        image_url = f"{RENDER_EXTERNAL_URL}/images/{encoded_path}"
        image_message = ImageSendMessage(
            original_content_url=image_url,
            preview_image_url=image_url
        )
        # 檢查是否為群組訊息
        is_group = event.source.type == 'group'
        info_message = TextSendMessage(
            text=f"【{img['id']}】 {img['name']}",
            quick_reply=create_navigation_buttons(is_group)
        )
        line_bot_api.reply_message(event.reply_token, [image_message, info_message])
        user_last_image_index[user_id] = index
    else:
        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(text="沒有更多圖片了。")
        )

def handle_id_search(user_message, event):
    user_id = event.source.user_id
    for index, (img_name, img) in enumerate(image_data.items()):
        if img["id"].lower() == user_message.lower():
            send_image_by_index(event, index)
            user_states[user_id] = STATE_INIT
            return True
    return False

def handle_keyword_search(user_message, event):
    try:
        matched_images = []
        for img_name, img in image_data.items():
            if user_message.lower() in img["name"].lower() or user_message.lower() in img.get("description", "").lower():
                matched_images.append(img)
        if matched_images:
            message = "找到以下符合關鍵字的圖片：\n"
            for img in matched_images:
                message += f"【{img['id']}】 {img['name']}\n"
            message += "請輸入圖片編號來查看圖片。"
            user_states[event.source.user_id] = STATE_WAITING_ID
            # 檢查是否為群組訊息
            is_group = event.source.type == 'group'
            line_bot_api.reply_message(
                event.reply_token,
                TextSendMessage(
                    text=message,
                    quick_reply=create_navigation_buttons(is_group)  # 傳入群組狀態
                )
            )
            return True
        else:
            line_bot_api.reply_message(
                event.reply_token,
                TextSendMessage(text="查無符合資料")
            )
            return False
    except Exception as e:
        print(f"關鍵字搜尋發生錯誤: {str(e)}")
        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(text="搜尋失敗，請稍後再試")
        )
        return False

def handle_meme_search(user_message, event):
    try:
        # 每次搜尋時重新載入資料
        meme_data = load_meme_data_from_web()
        if not meme_data:
            line_bot_api.reply_message(
                event.reply_token,
                TextSendMessage(text="無法取得資料，請稍後再試")
            )
            return
        
        # 搜尋符合關鍵字的迷因
        matches = []
        search_term = user_message.lower()
        for meme_name, info in meme_data.items():
            if search_term in meme_name.lower():
                message = f"重點摘要：{meme_name}\n"
                message += f"集數：{info['episode']}\n"
                message += f"首輪：{info['first']}\n"
                message += f"二輪：{info['second']}\n"
                message += f"三輪：{info['third']}\n"
                message += f"四輪：{info['fourth']}\n"
                message += f"五輪：{info['fifth']}"
                matches.append(message)

        if matches:
            response = "\n\n".join(matches)
            line_bot_api.reply_message(
                event.reply_token,
                TextSendMessage(text=response)
            )
        else:
            line_bot_api.reply_message(
                event.reply_token,
                TextSendMessage(text="找不到符合的重點摘要")
            )
    except Exception as e:
        print(f"查梗功能發生錯誤: {str(e)}")
        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(text="搜尋失敗，請稍後再試")
        )
    finally:
        # 重置狀態
        user_states[event.source.user_id] = STATE_INIT

def handle_lottery(event):
    user_id = event.source.user_id
    random_index = random.randint(0, len(image_data) - 1)
    img = list(image_data.values())[random_index]
    encoded_path = urllib.parse.quote(img['path'])
    image_url = f"{RENDER_EXTERNAL_URL}/images/{encoded_path}"
    image_message = ImageSendMessage(
        original_content_url=image_url,
        preview_image_url=image_url
    )
    # 檢查是否為群組訊息
    is_group = event.source.type == 'group'
    info_message = TextSendMessage(
        text=f"【{img['id']}】 {img['name']}",
        quick_reply=create_navigation_buttons(is_group)  # 傳入群組狀態
    )
    line_bot_api.reply_message(event.reply_token, [image_message, info_message])
    user_last_image_index[user_id] = random_index

def handle_character_search(user_message, event):
    try:
        matched_images = []
        print(f"搜尋角色: {user_message}")  # 調試信息
        
        # 確保 user_message 不為空
        if not user_message:
            line_bot_api.reply_message(
                event.reply_token,
                TextSendMessage(text="請輸入角色名稱")
            )
            return False
            
        # 遍歷所有圖片尋找匹配的角色
        for img_name, img in image_data.items():
            # 使用 get 方法安全地獲取 character 值，如果不存在則返回空字符串
            character = img.get("character", "")
            if character and user_message.lower() == character.lower():
                matched_images.append(img)
                    
        print(f"找到 {len(matched_images)} 張匹配的圖片")  # 調試信息
        
        if matched_images:
            message = f"找到以下【{user_message}】的圖片：\n"
            for img in matched_images:
                # 在群組中顯示時加上 ! 前綴
                if event.source.type == 'group':
                    message += f"【!{img['id']}】 {img['name']}\n"
                else:
                    message += f"【{img['id']}】 {img['name']}\n"
            message += "請輸入圖片編號來查看圖片。"
            user_states[event.source.user_id] = STATE_WAITING_ID
            
            # 只在私聊時添加快速回覆按鈕
            if event.source.type != 'group':
                line_bot_api.reply_message(
                    event.reply_token, 
                    TextSendMessage(
                        text=message,
                        quick_reply=create_navigation_buttons(False)
                    )
                )
            else:
                line_bot_api.reply_message(
                    event.reply_token, 
                    TextSendMessage(text=message)
                )
            return True
        else:
            line_bot_api.reply_message(
                event.reply_token,
                TextSendMessage(text=f"找不到【{user_message}】的圖片")
            )
            return False
            
    except Exception as e:
        print(f"角色搜尋錯誤: {str(e)}")  # 錯誤日誌
        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(text="搜尋過程發生錯誤，請稍後再試")
        )
        return False

def check_incense_limit(user_id):
    current_time = datetime.now().timestamp()
    # 獲取用戶的時間戳記錄，如果不存在則創建空列表
    user_times = user_timestamps.get(user_id, [])
    
    # 清理超過5分鐘的記錄
    five_minutes_ago = current_time - (5 * 60)
    user_times = [t for t in user_times if t > five_minutes_ago]
    
    # 檢查5分鐘內的上香次數
    if len(user_times) >= 5:
        return False, "你的香還沒熄呢 過幾分鐘再來看看"
    
    return True, None

def handle_incense(event):
    global total_incense_count, user_incense_counts, user_timestamps
    user_id = event.source.user_id
    
    # 檢查上香限制
    can_incense, message = check_incense_limit(user_id)
    if not can_incense:
        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(text=message)
        )
        return
    
    # 更新總次數
    total_incense_count += 1
    # 更新使用者次數
    user_incense_counts[user_id] = user_incense_counts.get(user_id, 0) + 1
    
    # 更新時間戳記錄
    current_time = datetime.now().timestamp()
    if user_id not in user_timestamps:
        user_timestamps[user_id] = []
    user_timestamps[user_id].append(current_time)
    
    # 保存新的計數和時間戳
    save_incense_count(total_incense_count, user_incense_counts)
    
    # 找到 a0368 圖片的索引
    for index, (img_name, img) in enumerate(image_data.items()):
        if img["id"] == "a0368":
            # 發送圖片
            encoded_path = urllib.parse.quote(img['path'])
            image_url = f"{RENDER_EXTERNAL_URL}/images/{encoded_path}"
            image_message = ImageSendMessage(
                original_content_url=image_url,
                preview_image_url=image_url
            )
            # 發送計數訊息
            user_count = user_incense_counts[user_id]
            count_message = TextSendMessage(
                text=f"已上香 {user_count} 次\n目前小主們共上香 {total_incense_count} 次"
            )
            line_bot_api.reply_message(event.reply_token, [image_message, count_message])
            return

def handle_incense_ranking(event):
    # 取得前十名上香次數最多的使用者
    sorted_users = sorted(user_incense_counts.items(), key=lambda x: x[1], reverse=True)[:10]
    
    # 建立排行榜訊息
    ranking_message = "✨ 上香排行榜 TOP 10 ✨\n"
    for i, (user_id, count) in enumerate(sorted_users, 1):
        try:
            # 取得使用者資料
            profile = line_bot_api.get_profile(user_id)
            user_name = profile.display_name
        except:
            user_name = "神秘小主"
        
        # 根據排名加入不同的表情符號
        if i == 1:
            emoji = "👑"
        elif i == 2:
            emoji = "🥈"
        elif i == 3:
            emoji = "🥉"
        else:
            emoji = "🙏"
            
        ranking_message += f"{emoji} 第{i}名：{user_name} - {count}柱香\n"
    
    line_bot_api.reply_message(
        event.reply_token,
        TextSendMessage(text=ranking_message)
    )

def handle_special_commands(user_message, event):
    user_id = event.source.user_id  # 新增這行來取得 user_id
    if user_message.lower() == "上香":
        handle_incense(event)
        return True
    elif user_message.lower() == "上香排行榜":
        handle_incense_ranking(event)
        return True
    elif user_message.lower() == "查梗":
        user_states[event.source.user_id] = STATE_WAITING_MEME
        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(text="請輸入要查詢的梗名稱：")
        )
        return True
    elif user_message.lower() == "列梗":
        handle_list_memes(event)
        return True
    elif user_message.lower() == "角色":
        user_states[event.source.user_id] = STATE_WAITING_CHARACTER
        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(text="請輸入角色名稱來查詢圖片：")
        )
        return True
    elif user_message.lower() == "我該嗎":
        user_states[event.source.user_id] = STATE_WAITING_SHOULD_I
        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(text="告訴朕你在猶豫什麼...")
        )
        return True
    elif user_message.lower() == "看見甄相":
        user_states[event.source.user_id] = STATE_WAITING_QUESTION
        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(text="告訴朕你想問的問題...")
        )
        return True
    elif user_message.lower() == "每日運勢":
        # 定義運勢圖片的 ID 列表
        fortune_ids = ["a0417", "a0199", "a0013", "a0414", "a0519"]
        # 隨機選擇一個 ID
        random_fortune_id = random.choice(fortune_ids)
        # 找到對應的圖片索引
        for index, (img_name, img) in enumerate(image_data.items()):
            if img["id"] == random_fortune_id:
                send_image_by_index(event, index)
                break
        return True
    elif user_message.lower() == "id":
        user_states[event.source.user_id] = STATE_WAITING_ID
        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(text="請輸入圖片編號（例如：a0001）：")
        )
        return True
    elif user_message.lower() == "menu":
        return True  # 直接返回，不做任何回應
    elif user_message.lower() == "抽":
        handle_lottery(event)
        return True
    elif user_message.lower() == "下一張":
        if user_id in user_last_image_index:
            send_image_by_index(event, user_last_image_index[user_id] + 1)
            return True
    elif user_message.lower() == "上一張":
        if user_id in user_last_image_index:
            send_image_by_index(event, user_last_image_index[user_id] - 1)
            return True
    return False

def handle_question_answer(event):
    # 定義解答圖片的 ID 列表
    answer_ids = ["a0261", "a0157", "a0299", "a0220", "a0452", 
                 "a0517", "a0202", "a0182", "a0222", "a0466", 
                 "a0427", "a0404", "a0236", "a0155", "a0371", 
                 "a0441", "a0292", "a0457", "a0411", "a0373"]
    # 隨機選擇一個答案
    random_answer_id = random.choice(answer_ids)
    # 找到對應的圖片索引
    for index, (img_name, img) in enumerate(image_data.items()):
        if img["id"] == random_answer_id:
            send_image_by_index(event, index)
            break

def handle_should_i_answer(event):
    # 定義解答圖片的 ID 列表
    answer_ids = ["a0182", "a0202"]
    # 隨機選擇一個答案
    random_answer_id = random.choice(answer_ids)
    # 找到對應的圖片索引
    for index, (img_name, img) in enumerate(image_data.items()):
        if img["id"] == random_answer_id:
            send_image_by_index(event, index)
            break

def handle_list_memes(event):
    message = "目前所有的梗：\n"
    for meme_key in meme_data.keys():
        message += f"- {meme_key}\n"
    message += "\n可使用「查梗」來查詢特定梗的詳細資訊"
    
    line_bot_api.reply_message(
        event.reply_token,
        TextSendMessage(text=message)
    )

@handler.add(MessageEvent, message=TextMessage)
def handle_message(event):
    user_message = event.message.text.strip()
    user_id = event.source.user_id
    
    # 在群組中，只回應特定前綴的指令
    if event.source.type == 'group':
        if not user_message.startswith('!'): 
            return
        user_message = user_message[1:]

    try:
        # 檢查指令頻率限制
        can_command, limit_message = check_command_rate_limit(user_id)
        if not can_command:
            if limit_message:  # 只有在有訊息時才回覆
                line_bot_api.reply_message(
                    event.reply_token,
                    TextSendMessage(text=limit_message)
                )
            return

        # 初始化用戶狀態
        if user_id not in user_states:
            user_states[user_id] = STATE_INIT

        # 處理特殊指令
        if handle_special_commands(user_message.lower(), event):
            return
            
        # 根據用戶狀態處理不同的情況
        current_state = user_states.get(user_id, STATE_INIT)
        
        if current_state == STATE_WAITING_CHARACTER:
            handle_character_search(user_message, event)
            user_states[user_id] = STATE_INIT
            return
            
        elif current_state == STATE_WAITING_QUESTION:
            handle_question_answer(event)
            user_states[user_id] = STATE_INIT
            return
            
        elif current_state == STATE_WAITING_SHOULD_I:
            handle_should_i_answer(event)
            user_states[user_id] = STATE_INIT
            return
            
        elif current_state == STATE_WAITING_MEME:
            handle_meme_search(user_message, event)
            # 狀態會在 handle_meme_search 中被重置
            return
            
        elif current_state == STATE_WAITING_ID:
            if handle_id_search(user_message, event):
                user_states[user_id] = STATE_INIT
                return
        
        # 檢查是否為圖片編號
        if user_message.lower().startswith('a') and user_message[1:].isdigit():
            if handle_id_search(user_message, event):
                return
        
        # 嘗試關鍵字搜尋
        if handle_keyword_search(user_message, event):
            return
                
        # 如果都沒有匹配到任何處理方式，回覆提示訊息
        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(text="查無符合資料")
        )
        
    except Exception as e:
        print(f"Error in handle_message: {str(e)}")
        line_bot_api.reply_message(
            event.reply_token,
            TextSendMessage(text="處理訊息時發生錯誤，請稍後再試")
        )
        # 發生錯誤時也重置狀態
        user_states[user_id] = STATE_INIT

if __name__ == "__main__":
    port = int(os.getenv("PORT", 8000))
    app.run(host="0.0.0.0", port=port)