from fastapi import FastAPI, Request, HTTPException
from linebot.v3 import WebhookHandler
from linebot.v3.exceptions import InvalidSignatureError
from linebot.v3.messaging import (
    Configuration, ApiClient, MessagingApi, ReplyMessageRequest, 
    TextMessage, FlexMessage, FlexContainer, PushMessageRequest
)
from linebot.v3.webhooks import MessageEvent, TextMessageContent
from dotenv import load_dotenv
import os
import google.generativeai as genai
from sqlalchemy.sql import func
from sqlalchemy import distinct, not_
import re

# 1. 載入設定
load_dotenv()
from database.session import engine, SessionLocal
from database import models

# 同步資料庫架構
models.Base.metadata.create_all(bind=engine)

# --- Gemini AI 設定 ---
genai.configure(api_key=os.getenv("GEMINI_API_KEY"))
ai_model = genai.GenerativeModel('gemini-2.5-flash')

# --- 輔助函數：美化 AI 文字 (處理 **粗體**) ---
def text_to_spans(text):
    parts = re.split(r'(\*\*.*?\*\*)', text)
    spans = []
    for part in parts:
        if part.startswith('**') and part.endswith('**'):
            content = part[2:-2]
            if content:
                spans.append({"type": "span", "text": content, "weight": "bold", "size": "sm", "color": "#000000"})
        else:
            if part:
                spans.append({"type": "span", "text": part, "size": "sm", "color": "#333333"})
    return spans

def get_gemini_analysis(q_obj):
    correct_text = getattr(q_obj, f"option{q_obj.answer}")
    prompt = f"""
    你是一位專業的台灣日文老師。請針對以下 N1 題目提供「深度解析」。
    題目：{q_obj.content}
    正確答案：{q_obj.answer} ({correct_text})

    請遵守規範：
    1. 全程台灣繁體中文，語氣親切。
    2. 重點文法與關鍵字請務必用 **文字** 包裹。
    3. 必須包含：【💡 核心語意】、【🔗 接續提醒】、【📝 生活例句】、【⚠️ 避坑指南】。
    """
    try:
        response = ai_model.generate_content(prompt)
        return response.text
    except Exception as e:
        return f"🤖 AI 老師查閱講義中發生錯誤... (Error: {e})"

# --- 進度計算函數 ---
def calculate_progress(db, user_id, category=None):
    try:
        q_query = db.query(models.Question)
        if category: q_query = q_query.filter(models.Question.category == category)
        total_q = q_query.count()
        if total_q == 0: return 0, 0, 0

        # 抓出不重複答對的題數
        correct_count = db.query(distinct(models.AnswerLog.question_id)).join(
            models.Question, models.AnswerLog.question_id == models.Question.id
        ).filter(models.AnswerLog.user_id == user_id, models.AnswerLog.is_correct == True)

        if category: correct_count = correct_count.filter(models.Question.category == category)
        c_count = correct_count.count()
        return int((c_count / total_q) * 100), c_count, total_q
    except Exception: return 0, 0, 0

# --- Flex Message 模板區 ---

def create_quiz_flex(question_obj, category):
    full_content = question_obj.content
    if "（" in full_content:
        parts = full_content.rpartition("（")
        jp_text, zh_text = parts[0].strip(), "（" + parts[2]
    else:
        jp_text, zh_text = full_content, ""

    # 新增：錯題本專屬卡片標題與顏色
    title_color = "#FF9800" if category == "錯題本" else "#1DB446"
    title_text = "N1 錯題本復仇 🗡️" if category == "錯題本" else f"N1 {category or '挑戰'} ✍️"

    bubble_json = {
        "type": "bubble", "body": { "type": "box", "layout": "vertical", "contents": [
            {"type": "text", "text": title_text, "weight": "bold", "color": title_color, "size": "sm"},
            {"type": "text", "text": jp_text, "weight": "bold", "size": "lg", "margin": "md", "wrap": True, "color": "#000000"},
            {"type": "text", "text": zh_text, "size": "xs", "color": "#888888", "margin": "sm", "wrap": True},
            {"type": "separator", "margin": "lg"},
            {"type": "box", "layout": "vertical", "margin": "lg", "spacing": "sm", "contents": [
                {"type": "text", "text": f"1️⃣ {question_obj.option1}", "size": "md", "wrap": True},
                {"type": "text", "text": f"2️⃣ {question_obj.option2}", "size": "md", "wrap": True},
                {"type": "text", "text": f"3️⃣ {question_obj.option3}", "size": "md", "wrap": True},
                {"type": "text", "text": f"4️⃣ {question_obj.option4}", "size": "md", "wrap": True}
            ]}
        ]}
    }
    return FlexMessage(alt_text="測驗開始", contents=FlexContainer.from_dict(bubble_json))

def create_result_flex(is_correct, explanation, q_obj):
    title, color = ("⭕️ 答對了！", "#1DB446") if is_correct else ("❌ 答錯了！", "#ED4C5C")
    bubble_json = {
        "type": "bubble", "body": { "type": "box", "layout": "vertical", "contents": [
            {"type": "text", "text": title, "weight": "bold", "size": "xl", "color": color},
            {"type": "text", "text": f"正確答案：{q_obj.answer}", "size": "sm", "margin": "md", "weight": "bold"},
            {"type": "separator", "margin": "lg"},
            {"type": "text", "text": explanation.replace("**", ""), "wrap": True, "size": "md", "lineSpacing": "4px"}
        ]},
        "footer": { "type": "box", "layout": "vertical", "contents": [
            {"type": "button", "style": "primary", "color": "#1DB446", "action": {"type": "message", "label": "下一題 ➡️", "text": "下一題"}}
        ]}
    }
    return FlexMessage(alt_text="結果", contents=FlexContainer.from_dict(bubble_json))

def create_progress_flex(all_stats):
    contents = []
    for cat, data in all_stats.items():
        prog, cur, tot = data
        contents.append({"type": "box", "layout": "horizontal", "margin": "md", "contents": [
            {"type": "text", "text": cat, "size": "sm", "color": "#555555", "flex": 2},
            {"type": "text", "text": f"{prog}% ({cur}/{tot})", "size": "sm", "align": "end", "flex": 4}
        ]})
        contents.append({"type": "box", "layout": "vertical", "margin": "xs", "height": "6px", "backgroundColor": "#EEEEEE", "contents": [
            {"type": "box", "layout": "vertical", "width": f"{max(prog, 1)}%", "height": "6px", "backgroundColor": "#1DB446" if cat=="總計" else "#464E5F", "contents": [{"type": "filler"}]}
        ]})
    bubble_json = {
        "type": "bubble", "header": { "type": "box", "layout": "vertical", "contents": [
            {"type": "text", "text": "🏆 N1 制霸戰報", "weight": "bold", "color": "#FFFFFF", "size": "md"}
        ], "backgroundColor": "#1DB446" }, "body": { "type": "box", "layout": "vertical", "contents": contents }
    }
    return FlexMessage(alt_text="制霸進度", contents=FlexContainer.from_dict(bubble_json))

def create_ai_flex(analysis_text):
    content_spans = text_to_spans(analysis_text)
    bubble_json = {
        "type": "bubble", "header": { "type": "box", "layout": "vertical", "contents": [
            {"type": "text", "text": "🤖 AI 老師深度講堂", "weight": "bold", "color": "#FFFFFF", "size": "md"}
        ], "backgroundColor": "#464E5F" },
        "body": { "type": "box", "layout": "vertical", "contents": [{"type": "text", "contents": content_spans, "wrap": True, "lineSpacing": "6px"}]},
        "footer": { "type": "box", "layout": "vertical", "contents": [{"type": "button", "style": "secondary", "color": "#EEEEEE", "action": {"type": "message", "label": "下一題 ➡️", "text": "下一題"}}]}
    }
    return FlexMessage(alt_text="AI解析", contents=FlexContainer.from_dict(bubble_json))

# --- FastAPI 核心 ---
app = FastAPI()
configuration = Configuration(access_token=os.getenv("LINE_CHANNEL_ACCESS_TOKEN"))
handler = WebhookHandler(os.getenv("LINE_CHANNEL_SECRET"))
MENU_MAIN_ID, MENU_MODE_ID, MENU_QUIZ_ID = os.getenv("MENU_MAIN_ID"), os.getenv("MENU_MODE_ID"), os.getenv("MENU_QUIZ_ID")

@app.post("/webhook")
async def callback(request: Request):
    signature = request.headers.get("X-Line-Signature")
    body = await request.body()
    try:
        handler.handle(body.decode("utf-8"), signature)
    except InvalidSignatureError: raise HTTPException(status_code=400)
    return "OK"

@handler.add(MessageEvent, message=TextMessageContent)
def handle_message(event):
    user_msg, user_id = event.message.text, event.source.user_id
    with ApiClient(configuration) as api_client:
        line_bot_api = MessagingApi(api_client)
        messages_to_send, db = [], SessionLocal()
        try:
            user = db.query(models.User).filter(models.User.line_uid == user_id).first()
            if not user:
                user = models.User(line_uid=user_id); db.add(user); db.commit(); db.refresh(user)

            # --- 模式切換：新增錯題本 ---
            if user_msg in ["文法", "単語", "諺", "錯題本"]:
                line_bot_api.link_rich_menu_id_to_user(user_id, MENU_MODE_ID)
                user.current_category = user_msg
                user.session_count, user.session_correct = 0, 0
                db.commit()
                emoji = "📖" if user_msg == "錯題本" else "🐰"
                messages_to_send.append(TextMessage(text=f"進入【{user_msg}】模式！{emoji}"))

            elif user_msg in ["開始測驗", "綜合測驗", "下一題"]:
                line_bot_api.link_rich_menu_id_to_user(user_id, MENU_QUIZ_ID)
                target = user.current_category or "文法"

                # --- 抽題邏輯分流 ---
                if target == "錯題本":
                    # 撈出該用戶答錯的題目 ID
                    wrong_ids = [r[0] for r in db.query(models.AnswerLog.question_id).filter(
                        models.AnswerLog.user_id == user.id, models.AnswerLog.is_correct == False
                    ).distinct().all()]

                    q = db.query(models.Question).filter(models.Question.id.in_(wrong_ids)).order_by(func.random()).first()
                    
                    if q:
                        user.last_question_id = q.id; db.commit()
                        messages_to_send.append(create_quiz_flex(q, target))
                    else:
                        messages_to_send.append(TextMessage(text="🎉 太神啦！妳目前沒有任何錯題紀錄喔！"))
                
                else:
                    # 一般模式：排除答對的題目
                    answered_correct_ids = [r[0] for r in db.query(models.AnswerLog.question_id).filter(
                        models.AnswerLog.user_id == user.id, models.AnswerLog.is_correct == True
                    ).all()]

                    q_query = db.query(models.Question).filter(models.Question.category == target)
                    if answered_correct_ids:
                        q_query = q_query.filter(not_(models.Question.id.in_(answered_correct_ids)))

                    q = q_query.order_by(func.random()).first()

                    if q:
                        user.last_question_id = q.id; db.commit()
                        messages_to_send.append(create_quiz_flex(q, target))
                    else:
                        messages_to_send.append(TextMessage(text=f"太厲害了！妳已經答對【{target}】的所有題目了！🎊\n可以去練習其他科目，或在主選單按「重置」再來一遍。"))

            elif user_msg in ["1", "2", "3", "4"]:
                if user.last_question_id:
                    q = db.query(models.Question).filter(models.Question.id == user.last_question_id).first()
                    if q:
                        is_correct = (int(user_msg) == q.answer)
                        user.session_count = (user.session_count or 0) + 1
                        
                        if is_correct: 
                            user.session_correct = (user.session_correct or 0) + 1
                            # --- 治癒機制：在錯題本答對，就洗刷冤屈 ---
                            if user.current_category == "錯題本":
                                db.query(models.AnswerLog).filter(
                                    models.AnswerLog.user_id == user.id,
                                    models.AnswerLog.question_id == q.id,
                                    models.AnswerLog.is_correct == False
                                ).delete()

                        db.add(models.AnswerLog(user_id=user.id, question_id=q.id, selected_option=int(user_msg), is_correct=is_correct))
                        messages_to_send.append(create_result_flex(is_correct, q.explanation, q))
                        user.last_answered_id, user.last_question_id = q.id, None
                        db.commit()

            elif "進度" in user_msg:
                stats = {"總計": calculate_progress(db, user.id), "文法": calculate_progress(db, user.id, "文法"), "単語": calculate_progress(db, user.id, "単語"), "諺": calculate_progress(db, user.id, "諺")}
                messages_to_send.append(create_progress_flex(stats))

            elif user_msg == "AI解析":
                if user.last_answered_id:
                    q_last = db.query(models.Question).filter(models.Question.id == user.last_answered_id).first()
                    line_bot_api.reply_message(ReplyMessageRequest(reply_token=event.reply_token, messages=[TextMessage(text="🤖 AI 老師正在整理講義中...")] ))
                    analysis = get_gemini_analysis(q_last)
                    line_bot_api.push_message(PushMessageRequest(to=user_id, messages=[create_ai_flex(analysis)]))
                    return

            elif user_msg == "結束":
                line_bot_api.link_rich_menu_id_to_user(user_id, MENU_MODE_ID)
                summary = f"✨ 練習結束！\n📊 答題數：{user.session_count or 0}\n✅ 答對：{user.session_correct or 0}"
                messages_to_send.append(TextMessage(text=summary))

            elif user_msg == "返回":
                line_bot_api.link_rich_menu_id_to_user(user_id, MENU_MAIN_ID)
                user.current_category = None; db.commit()
                messages_to_send.append(TextMessage(text="返回主功能。"))

            elif user_msg == "重置":
                db.query(models.AnswerLog).filter(models.AnswerLog.user_id == user.id).delete()
                db.commit()
                messages_to_send.append(TextMessage(text="🧹 進度與錯題紀錄已歸零！所有題目都會重新出現喔。"))

            if messages_to_send:
                line_bot_api.reply_message(ReplyMessageRequest(reply_token=event.reply_token, messages=messages_to_send))
        except Exception as e: print(f"ERROR: {e}")
        finally: db.close()