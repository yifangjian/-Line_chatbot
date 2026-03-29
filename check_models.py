import google.generativeai as genai
import os
from dotenv import load_dotenv

load_dotenv()
genai.configure(api_key=os.getenv("GEMINI_API_KEY"))

print("--- 妳的 API Key 可以使用的模型清單 ---")
try:
    for m in genai.list_models():
        if 'generateContent' in m.supported_generation_methods:
            print(f"型號名稱: {m.name}")
except Exception as e:
    print(f"查詢失敗，可能是 API Key 錯誤或網路問題: {e}")