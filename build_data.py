#!/usr/bin/env python3
"""
Build mapping.json from youtube CSV and SRT subtitle files.
Supports multi-language SRTs: *.ko.srt, *.en.srt, *.ja.srt (plain .srt = Korean).
Matches SRT files to CSV entries by title similarity.
"""

import csv
import json
import os
import re
import sys
import io
from collections import defaultdict
from difflib import SequenceMatcher
from pathlib import Path

# Fix Windows console encoding
if sys.platform == 'win32':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

BASE_DIR = Path(__file__).parent
SUBTITLE_DIR = BASE_DIR / 'subtitles'

# Language configuration
KNOWN_LANGS = ['ko', 'en', 'ja', 'zh']
LANG_LABELS = {'ko': '한국어', 'en': 'English', 'ja': '日本語', 'zh': '中文'}
DEFAULT_LANG = 'ko'
SUBTITLE_PREFIX = 'subtitles/'
LANG_ALIASES = {
    'ko': ['ko', 'kor', 'kr', 'korean'],
    'en': ['en', 'eng', 'english'],
    'ja': ['ja', 'jp', 'jpn', 'japanese'],
    'zh': ['zh', 'zh-cn', 'zh-tw', 'zh-hans', 'zh-hant', 'cn', 'chinese'],
}


def normalize_srt_ref(filename):
    filename = (filename or '').replace('\\', '/')
    if filename.startswith(SUBTITLE_PREFIX):
        return filename
    return SUBTITLE_PREFIX + os.path.basename(filename)


def extract_lang(filename):
    """Extract (base_stem, lang_code) from an SRT filename.
    'video.ko.srt' -> ('video', 'ko')
    'video.en.srt' -> ('video', 'en')
    'video.srt'     -> ('video', 'ko')  -- default Korean
    """
    name = filename
    if name.lower().endswith('.srt'):
        name = name[:-4]  # strip .srt
    prefixed = re.match(r'^\[([a-z]{2}(?:-[a-z]{2,4})?)-[a-zA-Z0-9_-]+\]\s*(.+)$', name)
    if prefixed:
        lang_token = prefixed.group(1).lower()
        for lang, aliases in LANG_ALIASES.items():
            if lang_token in aliases:
                return prefixed.group(2), lang
    name = re.sub(r'\.srt([._-])', r'\1', name, flags=re.IGNORECASE)
    lowered = name.lower()
    tokens = [token for token in re.split(r'[^a-z0-9]+', lowered) if token]
    compact = lowered.replace('_', '-')
    for lang, aliases in LANG_ALIASES.items():
        for alias in aliases:
            alias_tokens = [token for token in re.split(r'[^a-z0-9]+', alias) if token]
            if alias in tokens or compact.endswith('-' + alias) or compact.endswith('.' + alias):
                return re.sub(r'([._-])' + re.escape(alias) + r'([._-](translation|translated|subtitle|subtitles))?$', '', name, flags=re.IGNORECASE), lang
            if alias_tokens and len(alias_tokens) > 1:
                for i in range(0, len(tokens) - len(alias_tokens) + 1):
                    if tokens[i:i + len(alias_tokens)] == alias_tokens:
                        return re.sub(r'([._-])' + re.escape(alias) + r'([._-](translation|translated|subtitle|subtitles))?$', '', name, flags=re.IGNORECASE), lang
    return name, DEFAULT_LANG


def parse_srt(filepath):
    """Parse an SRT file into a list of subtitle entries."""
    with open(filepath, 'r', encoding='utf-8') as f:
        content = f.read()

    blocks = re.split(r'\n\s*\n', content.strip())
    subtitles = []

    for block in blocks:
        lines = block.strip().split('\n')
        if len(lines) < 2:
            continue

        timestamp_line = lines[1] if len(lines) > 1 else ''
        match = re.match(
            r'(\d{2}):(\d{2}):(\d{2})[,.](\d{3})\s*-->\s*(\d{2}):(\d{2}):(\d{2})[,.](\d{3})',
            timestamp_line
        )
        if not match:
            continue

        start_h, start_m, start_s, start_ms = [int(x) for x in match.groups()[:4]]
        end_h, end_m, end_s, end_ms = [int(x) for x in match.groups()[4:]]

        start_sec = start_h * 3600 + start_m * 60 + start_s + start_ms / 1000
        end_sec = end_h * 3600 + end_m * 60 + end_s + end_ms / 1000

        text = '\n'.join(lines[2:]).strip()

        subtitles.append({
            'start': round(start_sec, 3),
            'end': round(end_sec, 3),
            'text': text
        })

    return subtitles


def clean_title(title):
    """Extract a clean comparable version of a title."""
    t = title.strip()
    t = re.sub(r'^\d+\s*[-–—]\s*', '', t)
    # Strip language suffix for matching
    for lang in KNOWN_LANGS:
        suffix = '.' + lang
        if t.lower().endswith(suffix):
            t = t[:-len(suffix)]
            break
    t = t.replace('｜', '|')
    t = re.sub(r'\.srt$', '', t, flags=re.IGNORECASE)
    t = re.sub(r'\s+', ' ', t).strip()
    return t


def similarity(a, b):
    """Compute string similarity between 0 and 1."""
    return SequenceMatcher(None, a.lower(), b.lower()).ratio()


def extract_video_id(url):
    """Extract YouTube video ID from URL."""
    match = re.search(r'watch\?v=([a-zA-Z0-9_-]+)', url)
    if match:
        return match.group(1)
    return None


def parse_csv_comma(filepath):
    """Parse the comma-separated CSV file."""
    entries = []
    with open(filepath, 'r', encoding='utf-8') as f:
        reader = csv.reader(f)
        next(reader)  # Skip header

        for row in reader:
            if len(row) < 4:
                continue
            url = row[1].strip() if len(row) > 1 else ''
            title = row[3].strip() if len(row) > 3 else ''
            vid = extract_video_id(url)
            if vid and title:
                entries.append({
                    'video_id': vid,
                    'title': title,
                    'clean_title': clean_title(title)
                })

    return entries


def discover_srt_groups(base_dir):
    """Discover all SRT files, grouped by base_stem.
    Returns: { base_stem: { 'ko': ('filename.srt', [subtitles]), 'en': (...) } }
    """
    groups = defaultdict(dict)
    for srt_path in sorted(base_dir.glob('*.srt')):
        base_stem, lang = extract_lang(srt_path.name)
        subtitles = parse_srt(srt_path)
        groups[base_stem][lang] = (normalize_srt_ref(srt_path.name), subtitles)
        print(f"  [{lang}] {srt_path.name}: {len(subtitles)} subtitles (stem: {base_stem[:50]}...)")

    return dict(groups)


def main():
    csv_path = BASE_DIR / 'youtube-2026-05-30.csv'
    if not csv_path.exists():
        print(f"CSV file not found: {csv_path}")
        sys.exit(1)

    csv_entries = parse_csv_comma(csv_path)
    print(f"Parsed {len(csv_entries)} CSV entries")

    # Discover SRT files grouped by base stem
    srt_groups = discover_srt_groups(SUBTITLE_DIR)
    total_files = sum(len(langs) for langs in srt_groups.values())
    print(f"\nFound {len(srt_groups)} SRT groups ({total_files} files)")

    # Build list of SRT "entries" for matching (one per group)
    # Each group is treated as one unit for matching purposes
    srt_group_list = []
    for base_stem, lang_dict in srt_groups.items():
        # Use the Korean (or first available) filename for matching
        primary_lang = 'ko' if 'ko' in lang_dict else next(iter(lang_dict))
        srt_group_list.append({
            'base_stem': base_stem,
            'clean_title': clean_title(base_stem),
            'lang_files': lang_dict,  # {lang: (filename, subtitles)}
            'primary_file': lang_dict[primary_lang][0]
        })

    # Match SRT groups to CSV using global best-match-first strategy
    pairs = []
    for ci, csv_entry in enumerate(csv_entries):
        for si, group in enumerate(srt_group_list):
            score = similarity(csv_entry['clean_title'], group['clean_title'])
            pairs.append((score, ci, si))

    pairs.sort(key=lambda x: x[0], reverse=True)

    used_csv = set()
    used_srt = set()
    csv_to_srt = {}

    for score, ci, si in pairs:
        if ci not in used_csv and si not in used_srt and score > 0.55:
            used_csv.add(ci)
            used_srt.add(si)
            csv_to_srt[ci] = si

    # Build output
    mapping = {'videos': []}
    matched_count = 0
    total_subs = 0

    for ci, csv_entry in enumerate(csv_entries):
        entry = {
            'videoId': csv_entry['video_id'],
            'videoUrl': f'https://www.youtube.com/watch?v={csv_entry["video_id"]}',
            'title': csv_entry['title'],
            'duration': 0,
            'publishedAt': '',
            'subtitles': {}
        }

        if ci in csv_to_srt:
            si = csv_to_srt[ci]
            group = srt_group_list[si]
            score = similarity(csv_entry['clean_title'], group['clean_title'])

            # Build subtitles dict: lang -> filename
            for lang, (filename, subs) in group['lang_files'].items():
                entry['subtitles'][lang] = filename
                total_subs += len(subs)

            matched_count += 1
            langs_str = '/'.join(group['lang_files'].keys())
            print(f"  OK [{score:.2f}] {csv_entry['title'][:50]}...")
            print(f"        -> [{langs_str}] {group['primary_file'][:50]}...")
        else:
            print(f"  -- No SRT: {csv_entry['title'][:60]}...")

        mapping['videos'].append(entry)

    # Show unmatched SRT groups
    unmatched = [srt_group_list[i] for i in range(len(srt_group_list)) if i not in used_srt]
    if unmatched:
        print(f"\nUnmatched SRT groups ({len(unmatched)}):")
        for u in unmatched:
            langs = '/'.join(u['lang_files'].keys())
            print(f"  - [{langs}] {u['primary_file']}")

    # Write mapping.json
    out_path = BASE_DIR / 'mapping.json'
    with open(out_path, 'w', encoding='utf-8') as f:
        json.dump(mapping, f, ensure_ascii=False, indent=2)

    total_srt_files = sum(len(v['subtitles']) for v in mapping['videos'])
    print(f"\nDone: {out_path}")
    print(f"  {len(mapping['videos'])} videos ({matched_count} with subtitles)")
    print(f"  {total_srt_files} SRT files, {total_subs} subtitle entries")
    print(f"\n  Supported languages: {', '.join(f'{k}({v})' for k, v in LANG_LABELS.items())}")
    print(f"  To add a new language: drop .ko.srt / .en.srt / .ja.srt files + run this script")
    print(f"  To fix subtitles: edit the .srt file directly + refresh the page")


if __name__ == '__main__':
    main()
