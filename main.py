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

# --- 輔助函數：美化 AI 文字 ---
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
        print(f"❌ [AI 解析錯誤]: {e}")
        return f"🤖 AI 老師查閱講義中發生錯誤... (Error: {e})"

# --- 進度計算函數 ---
def calculate_progress(db, user_id, category=None):
    try:
        q_query = db.query(models.Question)
        if category: q_query = q_query.filter(models.Question.category == category)
        total_q = q_query.count()
        if total_q == 0: return 0, 0, 0

        correct_count = db.query(distinct(models.AnswerLog.question_id)).join(
            models.Question, models.AnswerLog.question_id == models.Question.id
        ).filter(models.AnswerLog.user_id == user_id, models.AnswerLog.is_correct == True)

        if category: correct_count = correct_count.filter(models.Question.category == category)
        c_count = correct_count.count()
        return int((c_count / total_q) * 100), c_count, total_q
    except Exception: return 0, 0, 0

# --- Flex Message 模板區 ---
def create_quiz_flex(question_obj, category):
    full_content = question_obj.content or "（無題目內容）"
    if "（" in full_content:
        parts = full_content.rpartition("（")
        jp_text, zh_text = parts[0].strip(), "（" + parts[2]
    else:
        jp_text, zh_text = full_content, " "

    # 防止選項是空的
    opt1 = question_obj.option1 or "暫無選項"
    opt2 = question_obj.option2 or "暫無選項"
    opt3 = question_obj.option3 or "暫無選項"
    opt4 = question_obj.option4 or "暫無選項"

    title_color = "#FF9800" if category == "錯題" else "#1DB446"
    title_text = "N1 錯題復仇 🗡️" if category == "錯題" else f"N1 {category or '挑戰'} ✍️"

    # 先建立基本內容（只有標題和大字題目）
    body_contents = [
        {"type": "text", "text": title_text, "weight": "bold", "color": title_color, "size": "sm"},
        {"type": "text", "text": jp_text or " ", "weight": "bold", "size": "lg", "margin": "md", "wrap": True, "color": "#000000"}
    ]
    
    # 【關鍵防呆】：只有當 zh_text 裡面真的有字時，才把這個灰色區塊加進去
    if zh_text and zh_text.strip():
        body_contents.append({"type": "text", "text": zh_text, "size": "xs", "color": "#888888", "margin": "sm", "wrap": True})

    # 把底下的分隔線跟選項補上
    body_contents.extend([
        {"type": "separator", "margin": "lg"},
        {"type": "box", "layout": "vertical", "margin": "lg", "spacing": "sm", "contents": [
            {"type": "text", "text": f"1️⃣ {opt1}", "size": "md", "wrap": True},
            {"type": "text", "text": f"2️⃣ {opt2}", "size": "md", "wrap": True},
            {"type": "text", "text": f"3️⃣ {opt3}", "size": "md", "wrap": True},
            {"type": "text", "text": f"4️⃣ {opt4}", "size": "md", "wrap": True}
        ]}
    ])

    bubble_json = {
        "type": "bubble", 
        "body": { "type": "box", "layout": "vertical", "contents": body_contents }
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
            {"type": "text", "text": "🏆 大會考 制霸戰報", "weight": "bold", "color": "#FFFFFF", "size": "md"}
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


def create_guide_flex():
    bubble_json = {
      "type": "bubble",
      "hero": {
        "type": "image",
        "url": "https://images.unsplash.com/photo-1542224566-6e85f2e6772f?ixlib=rb-1.2.1&auto=format&fit=crop&w=1000&q=80",
        "size": "full",
        "aspectRatio": "20:13",
        "aspectMode": "cover"
      },
      "body": {
        "type": "box",
        "layout": "vertical",
        "contents": [
          {
            "type": "text",
            "text": "📖 使用指南",
            "weight": "bold",
            "size": "xl",
            "color": "#1DB446"
          },
          {
            "type": "box",
            "layout": "vertical",
            "margin": "lg",
            "spacing": "md",
            "contents": [
              {
                "type": "box",
                "layout": "baseline",
                "spacing": "md",
                "contents": [
                  {"type": "text", "text": "🐰", "flex": 1, "size": "sm", "align": "center"},
                  {"type": "box", "layout": "vertical", "flex": 9, "contents": [
                      {"type": "text", "text": "1. 開始測驗", "weight": "bold", "color": "#1DB446", "size": "sm"},
                      {"type": "text", "text": "點選下方選單「文法」、「単語」或「諺語」開始練習。", "wrap": True, "color": "#666666", "size": "sm"}
                  ]}
                ]
              },
              {
                "type": "box",
                "layout": "baseline",
                "spacing": "md",
                "contents": [
                  {"type": "text", "text": "綜合", "flex": 2, "size": "xs", "color": "#888888", "align": "center"},
                  {"type": "box", "layout": "vertical", "flex": 8, "contents": [
                      {"type": "text", "text": "2. 綜合測驗", "weight": "bold", "color": "#1DB446", "size": "sm"},
                      {"type": "text", "text": "隨機從所有題目中抽題，挑戰妳的反應力！", "wrap": True, "color": "#666666", "size": "sm"}
                  ]}
                ]
              },
              {
                "type": "box",
                "layout": "baseline",
                "spacing": "md",
                "contents": [
                  {"type": "text", "text": "錯題本", "flex": 2, "size": "xs", "color": "#888888", "align": "center"},
                  {"type": "box", "layout": "vertical", "flex": 8, "contents": [
                      {"type": "text", "text": "3. 錯題復仇", "weight": "bold", "color": "#1DB446", "size": "sm"},
                      {"type": "text", "text": "按「錯題本」會專門練習妳答錯過的題目。", "wrap": True, "color": "#666666", "size": "sm"}
                  ]}
                ]
              },
              {
                "type": "box",
                "layout": "baseline",
                "spacing": "md",
                "contents": [
                  {"type": "text", "text": "📚", "flex": 1, "size": "sm", "align": "center"},
                  {"type": "box", "layout": "vertical", "flex": 9, "contents": [
                      {"type": "text", "text": "4. 諺語查詢", "weight": "bold", "color": "#1DB446", "size": "sm"},
                      {"type": "text", "text": "直接輸入數字 (1-200) 可查閱特定諺語卡。", "wrap": True, "color": "#666666", "size": "sm"}
                  ]}
                ]
              }
            ]
          },
          {
            "type": "box",
            "layout": "vertical",
            "margin": "xl",
            "contents": [
              {"type": "text", "text": "✨ 長按句子可以複製日文句子喔！", "size": "xxs", "color": "#aaaaaa", "wrap": True}
            ]
          }
        ]
      }
    }
    return FlexMessage(alt_text="使用指南", contents=FlexContainer.from_dict(bubble_json))


def create_proverb_detail_flex(p):
    bubble_json = {
      "type": "bubble",
      "header": { "type": "box", "layout": "vertical", "contents": [
          {"type": "text", "text": f"🏮 諺語百科 No.{p.id}", "weight": "bold", "color": "#FFFFFF", "size": "sm"}
      ], "backgroundColor": "#62442F" },
      "body": { "type": "box", "layout": "vertical", "spacing": "md", "contents": [
          {"type": "text", "text": p.kanji, "weight": "bold", "size": "xl", "wrap": True, "color": "#000000"},
          {"type": "text", "text": p.reading, "size": "sm", "color": "#888888", "margin": "xs"},
          {"type": "separator", "margin": "md"},
          {"type": "box", "layout": "vertical", "contents": [
              {"type": "text", "text": "【意思】", "size": "xs", "color": "#62442F", "weight": "bold"},
              {"type": "text", "text": p.chinese_meaning, "size": "sm", "wrap": True, "margin": "xs"}
          ]},
          {"type": "box", "layout": "vertical", "contents": [
              {"type": "text", "text": "【由來】", "size": "xs", "color": "#62442F", "weight": "bold"},
              {"type": "text", "text": p.origin, "size": "sm", "wrap": True, "margin": "xs"}
          ]},
          {"type": "box", "layout": "vertical", "contents": [
              {"type": "text", "text": "【例句】", "size": "xs", "color": "#62442F", "weight": "bold"},
              {"type": "text", "text": p.example_sentence, "size": "sm", "wrap": True, "margin": "xs", "color": "#555555"}
          ]}
      ]}
    }
    return FlexMessage(alt_text=f"諺語詳情: {p.kanji}", contents=FlexContainer.from_dict(bubble_json))

# --- FastAPI 核心 ---
app = FastAPI()
configuration = Configuration(access_token=os.getenv("LINE_CHANNEL_ACCESS_TOKEN"))
handler = WebhookHandler(os.getenv("LINE_CHANNEL_SECRET"))
MENU_MAIN_ID = os.getenv("MENU_MAIN_ID")
MENU_MODE_ID = os.getenv("MENU_MODE_ID")
MENU_QUIZ_ID = os.getenv("MENU_QUIZ_ID")

@app.post("/webhook")
async def callback(request: Request):
    print("🚀 [系統] 收到 LINE 的敲門了！")
    signature = request.headers.get("X-Line-Signature")
    body = await request.body()
    try:
        handler.handle(body.decode("utf-8"), signature)
    except InvalidSignatureError: 
        print("❌ [錯誤] 簽章驗證失敗 (可能是 .env 裡的 LINE_CHANNEL_SECRET 設錯了)")
        raise HTTPException(status_code=400)
    except Exception as e:
        print(f"❌ [錯誤] webhook 發生未知問題: {e}")
    return "OK"

@handler.add(MessageEvent, message=TextMessageContent)
def handle_message(event):
    user_msg, user_id = event.message.text, event.source.user_id
    print(f"📩 [訊息進來了] 用戶說了: {user_msg}")
    
    with ApiClient(configuration) as api_client:
        line_bot_api = MessagingApi(api_client)
        messages_to_send, db = [], SessionLocal()
        try:
            user = db.query(models.User).filter(models.User.line_uid == user_id).first()
            if not user:
                user = models.User(line_uid=user_id); db.add(user); db.commit(); db.refresh(user)

            # --- 模式切換與錯題清單 ---
            if user_msg in ["文法", "単語", "諺"]:
                if MENU_MODE_ID: line_bot_api.link_rich_menu_id_to_user(user_id, MENU_MODE_ID)
                user.current_category = user_msg
                user.session_count, user.session_correct = 0, 0
                db.commit()
                messages_to_send.append(TextMessage(text=f"進入【{user_msg}】模式！🐰"))

            elif user_msg == "錯題":
                # 取得當前科目 (如果沒有或是剛好在綜合測驗，預設為文法)
                base_cat = user.current_category.replace("_錯題", "") if user.current_category else "文法"
                if base_cat == "綜合測驗": base_cat = "文法"
                
                # 標記進入「該科目的專屬錯題模式」
                user.current_category = f"{base_cat}_錯題"
                user.session_count, user.session_correct = 0, 0
                db.commit()

                # 透過 JOIN 嚴格篩選出「該科目」的錯題
                wrong_ids = [r[0] for r in db.query(models.AnswerLog.question_id).join(
                    models.Question, models.AnswerLog.question_id == models.Question.id
                ).filter(
                    models.AnswerLog.user_id == user.id, 
                    models.AnswerLog.is_correct == False,
                    models.Question.category == base_cat
                ).distinct().all()]

                if not wrong_ids:
                    messages_to_send.append(TextMessage(text=f"🎉 太神啦！妳目前沒有任何【{base_cat}】的錯題紀錄喔！"))
                else:
                    wrong_questions = db.query(models.Question).filter(models.Question.id.in_(wrong_ids)).limit(20).all()
                    list_text = f"📖 妳目前共有 {len(wrong_ids)} 題【{base_cat}】錯題待消滅\n"
                    list_text += "(以下列出最新 20 題供妳複習)：\n\n" if len(wrong_ids) > 20 else "：\n\n"

                    for i, q in enumerate(wrong_questions, 1):
                        correct_opt = getattr(q, f"option{q.answer}")
                        short_content = q.content[:18] + "..." if len(q.content) > 18 else q.content
                        list_text += f"🔹 {short_content}\n✅ 答案：{correct_opt}\n\n"

                    list_text += "複習完畢後，請點擊「開始測驗」來消滅它們吧！🗡️"
                    messages_to_send.append(TextMessage(text=list_text))

            # --- 抽題邏輯 ---
            elif user_msg in ["開始測驗", "綜合測驗", "下一題"]:
                if MENU_QUIZ_ID: line_bot_api.link_rich_menu_id_to_user(user_id, MENU_QUIZ_ID)

                # 【新增】：如果按鈕是綜合測驗，強制將當前模式切換為綜合測驗
                if user_msg == "綜合測驗":
                    user.current_category = "綜合測驗"
                    user.session_count, user.session_correct = 0, 0
                    db.commit()

                target = user.current_category or "文法"

                # 處理「單科錯題模式」
                if target and target.endswith("_錯題"):
                    base_cat = target.replace("_錯題", "")
                    wrong_ids = [r[0] for r in db.query(models.AnswerLog.question_id).filter(
                        models.AnswerLog.user_id == user.id, models.AnswerLog.is_correct == False
                    ).distinct().all()]

                    # 【關鍵改動】：抽題時多加一個條件，只抽 base_cat 這個科目的錯題
                    q = db.query(models.Question).filter(
                        models.Question.id.in_(wrong_ids),
                        models.Question.category == base_cat
                    ).order_by(func.random()).first()
                    
                    if q:
                        user.last_question_id = q.id; db.commit()
                        messages_to_send.append(create_quiz_flex(q, "錯題"))
                    else:
                        messages_to_send.append(TextMessage(text=f"🎉 太神啦！【{base_cat}】的錯題已經全部清空囉！"))
                
                else:
                    answered_correct_ids = [r[0] for r in db.query(models.AnswerLog.question_id).filter(
                        models.AnswerLog.user_id == user.id, models.AnswerLog.is_correct == True
                    ).all()]

                    # 先抓出所有題目
                    q_query = db.query(models.Question)
                    
                    # 【核心修改】：只有當目標「不是」綜合測驗時，才去限制特定科目
                    if target != "綜合測驗":
                        q_query = q_query.filter(models.Question.category == target)

                    # 排除已經答對的題目
                    if answered_correct_ids:
                        q_query = q_query.filter(not_(models.Question.id.in_(answered_correct_ids)))

                    # 隨機抽出一題
                    q = q_query.order_by(func.random()).first()

                    if q:
                        user.last_question_id = q.id; db.commit()
                        # 卡片標題會自動變成 "N1 綜合測驗 ✍️"
                        messages_to_send.append(create_quiz_flex(q, target))
                    else:
                        messages_to_send.append(TextMessage(text=f"太厲害了！妳已經答對【{target}】的所有題目了！🎊\n可以去練習其他科目，或在主選單按「重置」再來一遍。"))

            # --- 諺語編號查詢 (1-120) ---
            # 邏輯：如果輸入的是數字，且目前「沒有」正在答題，就視為查詢諺語
            elif user_msg.isdigit() and not user.last_question_id:
                proverb_id = int(user_msg)
                p = db.query(models.Proverb).filter(models.Proverb.id == proverb_id).first()
                if p:
                    messages_to_send.append(create_proverb_detail_flex(p))
                else:
                    messages_to_send.append(TextMessage(text=f"找不到編號 {proverb_id} 的諺語喔！請輸入 1-120 之間的數字。"))

            # --- 答題邏輯 (選項 1, 2, 3, 4) ---
            elif user_msg in ["1", "2", "3", "4"] and user.last_question_id:
                if user.last_question_id:
                    q = db.query(models.Question).filter(models.Question.id == user.last_question_id).first()
                    if q:
                        is_correct = (int(user_msg) == q.answer)
                        user.session_count = (user.session_count or 0) + 1
                        
                        if is_correct: 
                            user.session_correct = (user.session_correct or 0) + 1
                            if user.current_category == "錯題":
                                db.query(models.AnswerLog).filter(
                                    models.AnswerLog.user_id == user.id,
                                    models.AnswerLog.question_id == q.id,
                                    models.AnswerLog.is_correct == False
                                ).delete()

                        db.add(models.AnswerLog(user_id=user.id, question_id=q.id, selected_option=int(user_msg), is_correct=is_correct))
                        messages_to_send.append(create_result_flex(is_correct, q.explanation, q))
                        user.last_answered_id, user.last_question_id = q.id, None
                        db.commit()

            # --- 其他功能 ---
            elif user_msg == "使用方法":
                messages_to_send.append(create_guide_flex())

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
                if MENU_MODE_ID: line_bot_api.link_rich_menu_id_to_user(user_id, MENU_MODE_ID)
                summary = f"✨ 練習結束！\n📊 答題數：{user.session_count or 0}\n✅ 答對：{user.session_correct or 0}"
                messages_to_send.append(TextMessage(text=summary))

            elif user_msg == "返回":
                if MENU_MAIN_ID: line_bot_api.link_rich_menu_id_to_user(user_id, MENU_MAIN_ID)
                user.current_category = None; db.commit()
                messages_to_send.append(TextMessage(text="返回主功能。"))

            elif user_msg == "重置":
                target = user.current_category

                # 情況 1：在特定單科模式下 (只重置該科)
                if target in ["文法", "単語", "諺"]:
                    target_q_ids = [q[0] for q in db.query(models.Question.id).filter(models.Question.category == target).all()]
                    if target_q_ids:
                        db.query(models.AnswerLog).filter(
                            models.AnswerLog.user_id == user.id,
                            models.AnswerLog.question_id.in_(target_q_ids)
                        ).delete(synchronize_session=False)
                        db.commit()
                    messages_to_send.append(TextMessage(text=f"🧹 【{target}】的進度與錯題已獨立歸零！"))

                # 情況 2：在特定科目的錯題模式下 (只清除該科目的答錯紀錄)
                elif target and target.endswith("_錯題"):
                    base_cat = target.replace("_錯題", "")
                    target_q_ids = [q[0] for q in db.query(models.Question.id).filter(models.Question.category == base_cat).all()]
                    
                    if target_q_ids:
                        db.query(models.AnswerLog).filter(
                            models.AnswerLog.user_id == user.id,
                            models.AnswerLog.question_id.in_(target_q_ids),
                            models.AnswerLog.is_correct == False
                        ).delete(synchronize_session=False)
                        db.commit()
                    messages_to_send.append(TextMessage(text=f"✨ 【{base_cat}】的錯題紀錄已獨立清除！錯題本空囉。"))

                # 情況 3：在綜合測驗 或 剛進去還沒選模式 (核彈級全刪)
                else:
                    db.query(models.AnswerLog).filter(models.AnswerLog.user_id == user.id).delete(synchronize_session=False)
                    db.commit()
                    messages_to_send.append(TextMessage(text="💥 所有科目的進度與錯題紀錄已「全部」歸零！大洗牌完成。"))

            # --- 傳送訊息 ---
            if messages_to_send:
                line_bot_api.reply_message(ReplyMessageRequest(reply_token=event.reply_token, messages=messages_to_send))
        except Exception as e: 
            print(f"❌ [執行邏輯錯誤]: {e}")
        finally: 
            db.close()