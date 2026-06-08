"""Shared MEUfan constants and subtitle helpers."""

import os
import re

KNOWN_LANGS = ['ko', 'en', 'ja', 'zh']
LANG_LABELS = {'ko': '한국어', 'en': 'English', 'ja': '日本語', 'zh': '中文'}
SUBTITLE_PREFIX = 'subtitles/'
LANG_ALIASES = {
    'ko': ['ko', 'kor', 'kr', 'korean'],
    'en': ['en', 'eng', 'english'],
    'ja': ['ja', 'jp', 'jpn', 'japanese'],
    'zh': ['zh', 'zh-cn', 'zh-tw', 'zh-hans', 'zh-hant', 'cn', 'chinese'],
}
DEFAULT_LANG = 'ko'


def normalize_srt_ref(filename):
    if not filename:
        return filename
    filename = filename.replace('\\', '/')
    if filename.startswith(SUBTITLE_PREFIX):
        return filename
    return SUBTITLE_PREFIX + os.path.basename(filename)


def detect_lang_from_filename(filename):
    name = os.path.basename(filename).lower()
    prefixed = re.match(r'^\[([a-z]{2}(?:-[a-z]{2,4})?)[-_][a-z0-9_-]+\]', name)
    if prefixed:
        token = prefixed.group(1)
        for lang, aliases in LANG_ALIASES.items():
            if token in aliases:
                return lang
    stem = re.sub(r'\.srt$', '', name)
    stem = re.sub(r'\.srt([._-])', r'\1', stem, flags=re.IGNORECASE)
    tokens = [token for token in re.split(r'[^a-z0-9]+', stem) if token]
    compact = stem.replace('_', '-')
    for lang, aliases in LANG_ALIASES.items():
        for alias in aliases:
            alias_tokens = [token for token in re.split(r'[^a-z0-9]+', alias) if token]
            if alias in tokens or compact.endswith('-' + alias) or compact.endswith('.' + alias) or compact.endswith('_' + alias):
                return lang
            if alias_tokens and len(alias_tokens) > 1:
                for i in range(0, len(tokens) - len(alias_tokens) + 1):
                    if tokens[i:i + len(alias_tokens)] == alias_tokens:
                        return lang
    return None


def extract_lang(filename):
    name = filename
    if name.lower().endswith('.srt'):
        name = name[:-4]
    name = re.sub(r'\.srt([._-])', r'\1', name, flags=re.IGNORECASE)
    lowered = name.lower()
    tokens = [token for token in re.split(r'[^a-z0-9]+', lowered) if token]
    compact = lowered.replace('_', '-')
    for lang, aliases in LANG_ALIASES.items():
        for alias in aliases:
            alias_tokens = [token for token in re.split(r'[^a-z0-9]+', alias) if token]
            pattern = r'([._-])' + re.escape(alias) + r'([._-](translation|translated|subtitle|subtitles))?$'
            if alias in tokens or compact.endswith('-' + alias) or compact.endswith('.' + alias):
                return re.sub(pattern, '', name, flags=re.IGNORECASE), lang
            if alias_tokens and len(alias_tokens) > 1:
                for i in range(0, len(tokens) - len(alias_tokens) + 1):
                    if tokens[i:i + len(alias_tokens)] == alias_tokens:
                        return re.sub(pattern, '', name, flags=re.IGNORECASE), lang
    return name, DEFAULT_LANG


def strip_lang_suffix(filename):
    stem = os.path.basename(filename)
    stem = re.sub(r'\.srt$', '', stem, flags=re.IGNORECASE)
    stem = re.sub(r'^\[[a-z]{2}(?:-[a-z]{2,4})?-[a-zA-Z0-9_-]+\]\s*', '', stem)
    stem = re.sub(r'\.srt([._-])', r'\1', stem, flags=re.IGNORECASE)
    for aliases in LANG_ALIASES.values():
        for alias in sorted(aliases, key=len, reverse=True):
            pattern = r'([._-])' + re.escape(alias) + r'([._-](translation|translated|subtitle|subtitles))?$'
            stem = re.sub(pattern, '', stem, flags=re.IGNORECASE)
    return stem


def detect_language(text):
    hangul = len(re.findall(r'[\uac00-\ud7af\u1100-\u11ff\u3130-\u318f]', text))
    hiragana = len(re.findall(r'[\u3040-\u309f]', text))
    katakana = len(re.findall(r'[\u30a0-\u30ff]', text))
    cjk = len(re.findall(r'[\u4e00-\u9fff]', text))
    kana = hiragana + katakana
    if kana > 5:
        return 'ja'
    if hangul > 5:
        return 'ko'
    if cjk > 5:
        return 'zh'
    return 'en'


def count_subtitles(text):
    text = text.strip()
    if not text:
        return 0
    return len(re.findall(r'\n\s*\n', text)) + 1


def parse_srt_text(text):
    blocks = re.split(r'\n\s*\n', text.strip())
    cues = []
    for block in blocks:
        lines = block.strip().splitlines()
        if len(lines) < 2:
            continue
        time_line = lines[1] if re.match(r'^\d+\s*$', lines[0]) and len(lines) > 1 else lines[0]
        text_start = 2 if time_line == (lines[1] if len(lines) > 1 else '') else 1
        match = re.match(
            r'(\d{2}):(\d{2}):(\d{2})[,.](\d{3})\s*-->\s*(\d{2}):(\d{2}):(\d{2})[,.](\d{3})',
            time_line,
        )
        if not match:
            continue
        values = [int(x) for x in match.groups()]
        start = values[0] * 3600 + values[1] * 60 + values[2] + values[3] / 1000
        end = values[4] * 3600 + values[5] * 60 + values[6] + values[7] / 1000
        cues.append({'start': round(start, 3), 'end': round(end, 3), 'text': '\n'.join(lines[text_start:]).strip()})
    return cues


def srt_time(seconds):
    ms = int(round((seconds - int(seconds)) * 1000))
    total = int(seconds)
    s = total % 60
    m = (total // 60) % 60
    h = total // 3600
    return f'{h:02d}:{m:02d}:{s:02d},{ms:03d}'


def format_srt(cues):
    blocks = []
    for i, cue in enumerate(cues, 1):
        blocks.append(f'{i}\n{srt_time(cue["start"])} --> {srt_time(cue["end"])}\n{cue["text"].strip()}')
    return '\n\n'.join(blocks) + '\n'
