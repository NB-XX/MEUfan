import os
import re

# ================= 配置区 =================
REPORT_FILE = "srt_修复详细报告.txt" # 输出的报告文件名
# ==========================================

def time_to_seconds(time_str):
    time_str = time_str.replace('.', ',')
    h, m, s_ms = time_str.split(':')
    s, ms = s_ms.split(',')
    return int(h) * 3600 + int(m) * 60 + int(s) + int(ms) / 1000.0

def seconds_to_time(seconds):
    """将秒数转换回 SRT 的时间戳格式 00:00:00,000"""
    if seconds < 0:
        seconds = 0.0
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    ms = int(round((seconds - int(seconds)) * 1000))
    if ms >= 1000:
        ms -= 1000
        s += 1
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"

def read_file_safely(filepath):
    encodings = ['utf-8', 'utf-8-sig', 'gbk', 'latin-1']
    for enc in encodings:
        try:
            with open(filepath, 'r', encoding=enc) as f:
                return f.read(), enc
        except UnicodeDecodeError:
            continue
    return None, None

def process_srt_files():
    current_dir = os.getcwd()
    # 忽略已经修复过的文件，防止重复处理
    srt_files = [f for f in os.listdir(current_dir) if f.lower().endswith('.srt') and not f.endswith('_头尾修复.srt')]
    
    if not srt_files:
        print("当前文件夹下没有找到需要处理的 .srt 文件。")
        return

    print(f"找到 {len(srt_files)} 个 .srt 文件，正在执行【头尾相接】修复...\n")
    
    report_lines = []
    report_lines.append("="*60)
    report_lines.append("SRT 字幕重叠（头尾相接）修复报告")
    report_lines.append("修复逻辑：若当前句结束时间晚于下一句开始时间，则将当前句尾巴截断至下一句开头。")
    report_lines.append("="*60 + "\n")
    
    total_fixes_all = 0

    for filename in srt_files:
        filepath = os.path.join(current_dir, filename)
        content, encoding = read_file_safely(filepath)
        
        if content is None:
            print(f"❌ 无法读取文件: {filename}")
            report_lines.append(f"❌ 无法读取文件 (编码未知): {filename}\n")
            continue
            
        blocks = re.split(r'\n\s*\n', content.strip())
        parsed_blocks = []
        
        # 1. 解析读取所有字幕块
        for block in blocks:
            lines = block.split('\n')
            if len(lines) < 3: continue
                
            index = lines[0].strip()
            time_line = lines[1].strip()
            raw_text = "\n".join(lines[2:])
            
            time_match = re.search(r'(\d{2}:\d{2}:\d{2}[,\.]\d{2,3})\s*-->\s*(\d{2}:\d{2}:\d{2}[,\.]\d{2,3})', time_line)
            if not time_match: continue
                
            start_str, end_str = time_match.groups()
            
            parsed_blocks.append({
                'index': index,
                'start_sec': time_to_seconds(start_str),
                'end_sec': time_to_seconds(end_str),
                'text': raw_text
            })

        # 2. 核心逻辑：头尾相接处理并记录报告
        file_fixes = []
        
        for i in range(len(parsed_blocks) - 1):
            curr = parsed_blocks[i]
            nxt = parsed_blocks[i+1]
            
            # 发现时间轴重叠（当前句结束比下一句开始还要晚）
            if curr['end_sec'] > nxt['start_sec']:
                orig_end_sec = curr['end_sec'] # 记录原本错误的结束时间
                
                # 计算新的结束时间（接驳下一句开头，提前 1 毫秒）
                new_end_sec = nxt['start_sec'] - 0.001
                
                # 兜底：如果强行切断后发现结束时间比开始时间还早（原时间轴彻底错乱）
                if new_end_sec <= curr['start_sec']:
                    new_end_sec = curr['start_sec'] + 0.1 # 给0.1秒的极限闪烁时间
                
                # 实施修复
                curr['end_sec'] = new_end_sec
                
                # 记录到当前文件的修复日志中
                orig_time_str = f"{seconds_to_time(curr['start_sec'])} --> {seconds_to_time(orig_end_sec)}"
                new_time_str = f"{seconds_to_time(curr['start_sec'])} --> {seconds_to_time(new_end_sec)}"
                
                # 把多行文本合并成一行展示在报告里，更整洁
                flat_text = curr['text'].replace('\n', ' | ')
                
                file_fixes.append({
                    'index': curr['index'],
                    'orig': orig_time_str,
                    'new': new_time_str,
                    'text': flat_text
                })

        # 3. 如果这个文件有被修复的地方，写入新文件并添加到总报告
        if file_fixes:
            new_filename = filename.replace('.srt', '_头尾修复.srt')
            new_filepath = os.path.join(current_dir, new_filename)
            
            # 写入修复好的 SRT
            with open(new_filepath, 'w', encoding='utf-8') as f:
                for idx, b in enumerate(parsed_blocks):
                    start_str = seconds_to_time(b['start_sec'])
                    end_str = seconds_to_time(b['end_sec'])
                    
                    f.write(f"{idx + 1}\n") # 重新排序序号，防止中间有断层
                    f.write(f"{start_str} --> {end_str}\n")
                    f.write(f"{b['text']}\n\n")
            
            # 追加到文本报告
            report_lines.append(f"📁 文件：{filename} (共修复 {len(file_fixes)} 处重叠)")
            for fix in file_fixes:
                report_lines.append(f"   - 序号: {fix['index']}")
                report_lines.append(f"     修复前: {fix['orig']}")
                report_lines.append(f"     ✅修复后: {fix['new']}")
                report_lines.append(f"     文本: {fix['text']}")
                report_lines.append("-" * 40)
            report_lines.append("\n")
            
            total_fixes_all += len(file_fixes)
            print(f"✅ 已修复并生成: {new_filename} (修复 {len(file_fixes)} 处)")
        else:
            print(f"🟢 无重叠问题，无需修复: {filename}")

    # 4. 保存详细报告
    if total_fixes_all > 0:
        summary = f"🎉 修复完成！共处理了 {total_fixes_all} 处重叠时间轴。"
        report_lines.append(summary)
        with open(REPORT_FILE, 'w', encoding='utf-8') as f:
            f.write("\n".join(report_lines))
        print(f"\n{summary}")
        print(f"📄 详细修复报告已生成：{os.path.abspath(REPORT_FILE)}")
    else:
        print("\n🎉 检查完成！所有字幕时间轴正常，未发现需要头接尾修复的地方。")

if __name__ == "__main__":
    process_srt_files()