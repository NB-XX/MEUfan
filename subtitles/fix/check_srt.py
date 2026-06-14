import os
import re

# ================= 配置区 =================
MAX_CHARS = 200           # 允许的最大字符数（超过此数值视为异常）
MAX_DURATION_SEC = 20.0  # 允许的最大单句时长（单位：秒，超过此数值视为异常）
REPORT_FILE = "srt_异常检查报告.txt" # 输出报告的文件名
# ==========================================

def time_to_seconds(time_str):
    """将 SRT 时间戳 (00:00:00,000 或 00:00:00.000) 转换为秒数"""
    time_str = time_str.replace('.', ',') # 兼容某些使用点号的格式
    h, m, s_ms = time_str.split(':')
    s, ms = s_ms.split(',')
    return int(h) * 3600 + int(m) * 60 + int(s) + int(ms) / 1000.0

def clean_text(text):
    """清理字幕文本：去除HTML/特效标签、去除换行符，以便准确计算字符数"""
    # 移除类似 <font color="#fff"> 或 <i> 的标签
    text_no_tags = re.sub(r'<[^>]+>', '', text)
    # 移除大括号特效标签，如 {\an8}
    text_no_tags = re.sub(r'\{[^}]+\}', '', text_no_tags)
    # 替换换行符为空格，去除两端空白
    text_clean = text_no_tags.replace('\n', ' ').strip()
    return text_clean

def read_file_safely(filepath):
    """尝试使用不同编码读取文件，解决乱码报错问题"""
    encodings = ['utf-8', 'utf-8-sig', 'gbk', 'latin-1']
    for enc in encodings:
        try:
            with open(filepath, 'r', encoding=enc) as f:
                return f.read()
        except UnicodeDecodeError:
            continue
    return None

def check_srt_files():
    current_dir = os.getcwd()
    srt_files = [f for f in os.listdir(current_dir) if f.lower().endswith('.srt')]
    
    if not srt_files:
        print("当前文件夹下没有找到 .srt 文件。")
        return

    print(f"找到 {len(srt_files)} 个 .srt 文件，正在检查...")
    
    report_lines = []
    report_lines.append("="*50)
    report_lines.append("SRT 字幕异常检查报告")
    report_lines.append(f"检查标准：单条时长 > {MAX_DURATION_SEC}秒 或 字符数 > {MAX_CHARS}个")
    report_lines.append("="*50 + "\n")
    
    total_anomalies = 0

    for filename in srt_files:
        filepath = os.path.join(current_dir, filename)
        content = read_file_safely(filepath)
        
        if content is None:
            report_lines.append(f"❌ 无法读取文件 (编码未知): {filename}\n")
            continue
            
        # 按照空行分割每一个字幕块
        blocks = re.split(r'\n\s*\n', content.strip())
        
        file_anomalies = []
        
        for block in blocks:
            lines = block.split('\n')
            if len(lines) < 3:
                continue # 不是标准的字幕块格式
                
            index = lines[0].strip()
            time_line = lines[1].strip()
            raw_text = "\n".join(lines[2:])
            
            # 提取时间戳
            time_match = re.search(r'(\d{2}:\d{2}:\d{2}[,\.]\d{2,3})\s*-->\s*(\d{2}:\d{2}:\d{2}[,\.]\d{2,3})', time_line)
            if not time_match:
                continue
                
            start_time, end_time = time_match.groups()
            duration = time_to_seconds(end_time) - time_to_seconds(start_time)
            
            # 提取并清理文本
            text = clean_text(raw_text)
            text_length = len(text)
            
            # 判断是否异常
            is_too_long = duration > MAX_DURATION_SEC
            is_too_many_chars = text_length > MAX_CHARS
            
            if is_too_long or is_too_many_chars:
                reasons = []
                if is_too_long: reasons.append(f"时长异常 ({duration:.2f}秒)")
                if is_too_many_chars: reasons.append(f"字符过多 ({text_length}个字符)")
                
                file_anomalies.append({
                    'index': index,
                    'time': time_line,
                    'reasons': " + ".join(reasons),
                    'text': text
                })
        
        # 如果当前文件有异常，记录到报告中
        if file_anomalies:
            report_lines.append(f"📁 文件：{filename} (发现 {len(file_anomalies)} 处异常)")
            for an in file_anomalies:
                report_lines.append(f"   - 序号: {an['index']}")
                report_lines.append(f"     时间: {an['time']}")
                report_lines.append(f"     原因: {an['reasons']}")
                report_lines.append(f"     文本: {an['text']}")
                report_lines.append("-" * 30)
            report_lines.append("\n")
            total_anomalies += len(file_anomalies)

    # 汇总结果
    if total_anomalies == 0:
        summary = "🎉 检查完毕！所有文件均未发现异常。"
    else:
        summary = f"⚠️ 检查完毕！共发现 {total_anomalies} 处异常，详情已保存到报告中。"
        
    report_lines.append(summary)
    
    # 写入报告文件
    with open(REPORT_FILE, 'w', encoding='utf-8') as f:
        f.write("\n".join(report_lines))
        
    print(summary)
    print(f"报告文件已生成：{os.path.abspath(REPORT_FILE)}")

if __name__ == "__main__":
    check_srt_files()