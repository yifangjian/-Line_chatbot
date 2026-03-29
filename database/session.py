from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base
import os
from dotenv import load_dotenv

# 載入 .env 檔案
load_dotenv()

# 取得資料庫網址
DATABASE_URL = os.getenv("DATABASE_URL")

# 建立與資料庫的連線引擎 (engine)
# pool_pre_ping=True 是為了防止雲端資料庫連線過久斷開
engine = create_engine(DATABASE_URL, pool_pre_ping=True)

# 建立一個與資料庫溝通的對話小幫手 (Session)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# 宣告資料表結構的基礎類別 (Base)
Base = declarative_base()

# 建立一個依賴函數，讓 FastAPI 每次處理請求時都能取得資料庫連線
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()