import os
import requests
from dotenv import load_dotenv

# 讀取 .env 裡的 LINE 金鑰
load_dotenv()
token = os.getenv("LINE_CHANNEL_ACCESS_TOKEN")

if not token:
    print("🚨 致命錯誤：找不到 LINE 金鑰！")
    exit()

token = token.strip()
headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

def create_rich_menu(name, image_path, areas):
    # 1. 建立選單框架 (走一般通道 api.line.me)
    data = {
        "size": {"width": 2500, "height": 1686},
        "selected": True,
        "name": name,
        "chatBarText": "點擊打開選單",
        "areas": areas
    }
    print(f"準備上傳 {name}...")
    res = requests.post("https://api.line.me/v2/bot/richmenu", headers=headers, json=data)
    
    if res.status_code != 200:
        print(f"❌ 建立框架失敗: {res.text}")
        return None

    menu_id = res.json().get("richMenuId")
    
    # 2. 上傳對應的圖片 (走專屬貨物通道 api-data.line.me ！！！)
    with open(image_path, "rb") as f:
        image_data = f.read()
        img_headers = {"Authorization": f"Bearer {token}", "Content-Type": "image/jpeg"}
        
        # 關鍵修改在這裡：網址變成了 api-data.line.me
        upload_res = requests.post(
            f"https://api-data.line.me/v2/bot/richmenu/{menu_id}/content", 
            headers=img_headers, 
            data=image_data
        )
        
        if upload_res.status_code == 200:
            print(f"✅ {name} 上傳成功！ID: {menu_id}\n")
            return menu_id
        else:
            print(f"❌ 圖片上傳失敗 ({upload_res.status_code}): {upload_res.text}")
            return None

# ================= 定義三個選單的按鈕座標與文字 =================

areas_main = [
    {"bounds": {"x": 0, "y": 0, "width": 833, "height": 843}, "action": {"type": "message", "text": "文法"}},
    {"bounds": {"x": 833, "y": 0, "width": 833, "height": 843}, "action": {"type": "message", "text": "単語"}},
    {"bounds": {"x": 1666, "y": 0, "width": 834, "height": 843}, "action": {"type": "message", "text": "諺"}},
    {"bounds": {"x": 0, "y": 843, "width": 833, "height": 843}, "action": {"type": "message", "text": "綜合測驗"}},
    {"bounds": {"x": 833, "y": 843, "width": 833, "height": 843}, "action": {"type": "message", "text": "總進度"}},
    {"bounds": {"x": 1666, "y": 843, "width": 834, "height": 843}, "action": {"type": "message", "text": "使用方法"}}
]

areas_mode = [
    {"bounds": {"x": 0, "y": 0, "width": 833, "height": 843}, "action": {"type": "message", "text": "錯題"}},
    {"bounds": {"x": 833, "y": 0, "width": 833, "height": 843}, "action": {"type": "message", "text": "進度"}},
    {"bounds": {"x": 1666, "y": 0, "width": 834, "height": 843}, "action": {"type": "message", "text": "重置"}},
    {"bounds": {"x": 0, "y": 843, "width": 833, "height": 843}, "action": {"type": "message", "text": "返回"}},
    {"bounds": {"x": 833, "y": 843, "width": 1667, "height": 843}, "action": {"type": "message", "text": "開始測驗"}}
]

areas_quiz = [
    {"bounds": {"x": 0, "y": 0, "width": 625, "height": 843}, "action": {"type": "message", "text": "1"}},
    {"bounds": {"x": 625, "y": 0, "width": 625, "height": 843}, "action": {"type": "message", "text": "2"}},
    {"bounds": {"x": 1250, "y": 0, "width": 625, "height": 843}, "action": {"type": "message", "text": "3"}},
    {"bounds": {"x": 1875, "y": 0, "width": 625, "height": 843}, "action": {"type": "message", "text": "4"}},
    {"bounds": {"x": 0, "y": 843, "width": 1250, "height": 843}, "action": {"type": "message", "text": "AI解析"}},
    {"bounds": {"x": 1250, "y": 843, "width": 1250, "height": 843}, "action": {"type": "message", "text": "結束"}}
]

print("🚀 開始佈署 LINE 圖文選單...\n")
main_id = create_rich_menu("Main_Menu", "assets/menu_main.jpg", areas_main)
mode_id = create_rich_menu("Mode_Menu", "assets/menu_mode.jpg", areas_mode)
quiz_id = create_rich_menu("Quiz_Menu", "assets/menu_quiz.jpg", areas_quiz)

if main_id:
    res = requests.post(f"https://api.line.me/v2/bot/user/all/richmenu/{main_id}", headers=headers)
    if res.status_code == 200:
        print("🎉 已將「主選單」設為所有用戶的預設選單！")
    else:
        print(f"❌ 設定預設選單失敗: {res.text}")