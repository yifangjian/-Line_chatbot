import os
from database.session import SessionLocal, engine
from database.models import Base, Question
from dotenv import load_dotenv

# 1. 確保載入環境變數
load_dotenv()

def seed_questions():
    # 2. 強制執行「建立表格」！如果 Supabase 沒表，它會自動幫你蓋好
    print("正在檢查資料庫表格...")
    Base.metadata.create_all(bind=engine)
    
    db = SessionLocal()
    
    # 這裡放入你從 Gemini 拿到的 N1 題目 (我先放一題示範)
    sample_questions = [
       {
        "category": "文法",
        "content": "実際に見（　）、対策はたてられない。（如果不親自看一看，就無法制定對策。）",
        "option1": "ないことには",
        "option2": "ないまでも",
        "option3": "たところで",
        "option4": "たきり",
        "answer": 1,
        "explanation": "【意味】：**如果不先做某事，後項就無法達成**。相當於「如果不……就不……」。\n【接續】：動詞**ない形**＋ことには。\n【注意】：後項多接續**負面表現**或**表示不可能**的文句（如：～られない）。"
    },
    {
        "category": "文法",
        "content": "予習し（　）、この講義はわからないだろう。（如果不預習，大概就聽不懂這堂課吧。）",
        "option1": "ないばかりか",
        "option2": "ないことには",
        "option3": "ないこともない",
        "option4": "ないですむ",
        "answer": 2,
        "explanation": "【意味】：**如果不……就不……**。表示前項是後項判斷的必要前提。\n【接續】：動詞**ない形**＋ことには。\n【注意】：後項常帶有說話人的**負面預測**或**困難點**。"
    },
    {
        "category": "文法",
        "content": "雨が降ら（　）、しばらく給水制限は続く。（如果不下雨，限水措施還會持續一陣子。）",
        "option1": "ないかぎり",
        "option2": "ないものの",
        "option3": "ないことには",
        "option4": "ないせいで",
        "answer": 3,
        "explanation": "【意味】：如果不發生某種情況，目前的**負面狀態就會持續**。\n【接續】：動詞**ない形**＋ことには。\n【注意】：本句強調「降雨」是解除負面現狀的**必要條件**。"
    },
    {
        "category": "文法",
        "content": "部長の許可の（　）、この仕事は進められない。（如果沒有部長的許可，這項工作就無法進展。）",
        "option1": "ないことには",
        "option2": "ないもので",
        "option3": "ないおかげで",
        "option4": "ない以上は",
        "answer": 1,
        "explanation": "【意味】：**若沒有……的話，就無法……**。\n【接續】：名詞＋**のない**＋ことには（或 がない）。\n【注意】：後項接**可能形的否定**，強調程序上的限制。"
    },
    {
        "category": "文法",
        "content": "あちらから電話が（　）、こちらから連絡の方法はない。（如果對方不打電話過來，我也沒辦法主動聯絡。）",
        "option1": "ないことによって",
        "option2": "ないことには",
        "option3": "ないばかりに",
        "option4": "ないといっても",
        "answer": 2,
        "explanation": "【意味】：如果不……，就沒有辦法進行後續動作。強調**唯一的前提條件**。\n【接續】：名詞＋**がない**＋ことには。\n【注意】：後項常接**「方法はない」**等表達走投無路的詞彙。"
    },
    {
        "category": "文法",
        "content": "旅行し（　）、視野が広がらない。（如果不去旅行，眼界就不會開闊。）",
        "option1": "ないことには",
        "option2": "たあげく",
        "option3": "ないことだ",
        "option4": "た末に",
        "answer": 1,
        "explanation": "【意味】：如果不親自體驗，就無法獲得成長。常用於說明**道理或經驗談**。\n【接續】：動詞**ない形**＋ことには。\n【注意】：此句型**不能接續「意志、打算」**，後項必須是自然產生的結果或狀態。"
    }
    ]

    try:
        print(f"準備匯入 {len(sample_questions)} 題 N1 文法...")
        for q in sample_questions:
            # 檢查是否重複
            exists = db.query(Question).filter(Question.content == q["content"]).first()
            if not exists:
                # 這裡使用了 **q 自動展開成欄位，所以 models.py 的欄位名稱必須跟 JSON 一模一樣
                new_q = Question(**q)
                db.add(new_q)
        
        db.commit()
        print("🎉 ✅ 恭喜！題庫已成功匯入 Supabase！")
    except Exception as e:
        print(f"❌ 匯入失敗，原因: {e}")
        db.rollback()
    finally:
        db.close()

if __name__ == "__main__":
    seed_questions()