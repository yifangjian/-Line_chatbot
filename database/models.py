from sqlalchemy import Column, Integer, String, Boolean, DateTime, ForeignKey, Text
from sqlalchemy.sql import func
import uuid
from database.session import Base

def generate_uuid():
    return str(uuid.uuid4())

class User(Base):
    __tablename__ = "users"
    id = Column(String, primary_key=True, default=generate_uuid)
    line_uid = Column(String, unique=True, index=True, nullable=False)
    
    # --- 核心狀態紀錄 ---
    current_category = Column(String, default="文法") # 紀錄模式
    last_question_id = Column(Integer)
    last_answered_id = Column(Integer)
    
    # --- 本次練習統計 (按結束後結算用) ---
    session_count = Column(Integer, default=0)
    session_correct = Column(Integer, default=0)
    
    created_at = Column(DateTime(timezone=True), server_default=func.now())

class Question(Base):
    __tablename__ = "questions"
    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    category = Column(String, index=True) # 文法、單語、諺
    content = Column(Text, nullable=False)
    option1 = Column(String, nullable=False)
    option2 = Column(String, nullable=False)
    option3 = Column(String, nullable=False)
    option4 = Column(String, nullable=False)
    answer = Column(Integer, nullable=False)
    explanation = Column(Text)

class AnswerLog(Base):
    __tablename__ = "answer_logs"
    id = Column(String, primary_key=True, default=generate_uuid)
    user_id = Column(String, ForeignKey("users.id"))
    question_id = Column(Integer, ForeignKey("questions.id"))
    selected_option = Column(Integer)
    is_correct = Column(Boolean)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

class Proverb(Base):
    __tablename__ = "Proverb"
    id = Column(Integer, primary_key=True)  # 編號 (1-120)
    kanji = Column(String)                  # 全漢字寫法
    reading = Column(String)                # 平假名讀音
    chinese_meaning = Column(String)        # 中文意思/對應成語
    origin = Column(Text)                   # 由來・出處
    example_sentence = Column(Text)         # 情境例句