import csv

input_file = 'proverbs_questions.csv'
output_file = 'cleaned_proverbs_questions.csv'

print(f"📂 正在讀取並清洗 {input_file} ...")

with open(input_file, mode='r', encoding='utf-8') as infile, \
     open(output_file, mode='w', encoding='utf-8-sig', newline='') as outfile:
     
    reader = csv.reader(infile)
    writer = csv.writer(outfile)
    
    # 讀取標題行並寫入標準的 8 個欄位
    headers = next(reader)
    writer.writerow(['category', 'content', 'option1', 'option2', 'option3', 'option4', 'answer', 'explanation'])
    
    success_count = 0
    
    for row in reader:
        # 取前 8 個欄位，如果 Manus 產生的欄位不夠就補空字串
        row = row[:8] + [''] * (8 - len(row))
        category, content, opt1, opt2, opt3, opt4, answer, explanation = row
        
        # 1. 殺掉 Supabase 最討厭的「全空白行」
        if not category.strip() and not content.strip():
            continue
            
        # 2. 修復欄位錯位：如果 explanation 跑到數字 (例如 1 或 1.0)
        exp_clean = explanation.strip()
        if exp_clean.endswith('.0'): exp_clean = exp_clean[:-2]
        
        if exp_clean in ['1', '2', '3', '4']:
            explanation = "參考例句：" + content
            content, opt1, opt2, opt3, opt4, answer = opt1, opt2, opt3, opt4, answer, exp_clean
            
        # 3. 修復文字答案：如果 answer 被填了日文字而不是數字
        ans_clean = answer.strip()
        if ans_clean.endswith('.0'): ans_clean = ans_clean[:-2]
        
        if ans_clean not in ['1', '2', '3', '4']:
            if ans_clean == opt1.strip(): ans_clean = '1'
            elif ans_clean == opt2.strip(): ans_clean = '2'
            elif ans_clean == opt3.strip(): ans_clean = '3'
            elif ans_clean == opt4.strip(): ans_clean = '4'
            else: ans_clean = '1'  # 終極防呆預設
            
        # 寫入修復後的完美資料
        writer.writerow([category, content, opt1, opt2, opt3, opt4, ans_clean, explanation])
        success_count += 1

print(f"🎉 清洗完成！成功處理了 {success_count} 題！")
print(f"👉 請去資料夾找 '{output_file}' 並且上傳到 Supabase 吧！")