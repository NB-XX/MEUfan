#!/usr/bin/env python3
"""Rename all SRT files to standardized format: [lang-videoId] sanitized-title.srt"""
import json
import os
import re
from pathlib import Path

BASE_DIR = Path(__file__).parent
SUBTITLE_DIR = BASE_DIR / 'subtitles'
MAPPING_PATH = BASE_DIR / 'mapping.json'

def sanitize_title(name):
    """Remove characters unsafe for filenames in the title portion only."""
    name = re.sub(r'[/\\:*?"<>|]', '_', name)
    name = re.sub(r'[\x00-\x1f]', '', name)
    name = re.sub(r'\s+', ' ', name).strip()
    if len(name) > 120:
        name = name[:120]
    return name

def make_filename(lang, video_id, title):
    """Build standardized filename: [lang-videoId] sanitized-title.srt"""
    return f'[{lang}-{video_id}] {sanitize_title(title)}.srt'

# Load mapping
with open(MAPPING_PATH, 'r', encoding='utf-8') as f:
    mapping = json.load(f)

renames = []
errors = []
unchanged = 0

for v in mapping['videos']:
    vid = v['videoId']
    title = v['title']
    subs = v.get('subtitles', {})
    if not subs:
        continue
    new_subs = {}
    for lang, old_rel_path in subs.items():
        old_path = BASE_DIR / old_rel_path
        if not old_path.exists():
            errors.append(f"MISSING: {old_rel_path}")
            new_subs[lang] = old_rel_path
            continue

        new_name = make_filename(lang, vid, title)
        new_rel = f'subtitles/{new_name}'
        new_path = BASE_DIR / new_rel

        if old_path.resolve() == new_path.resolve():
            unchanged += 1
            new_subs[lang] = old_rel_path
            continue

        # Handle duplicate filename (two languages for same video)
        counter = 1
        while new_path.exists() and old_path.resolve() != new_path.resolve():
            new_name = f'[{lang}-{vid}-{counter}] {sanitize_title(title)}.srt'
            new_rel = f'subtitles/{new_name}'
            new_path = BASE_DIR / new_rel
            counter += 1

        renames.append((old_path, new_path, lang, vid))
        new_subs[lang] = new_rel

    v['subtitles'] = new_subs

# Preview
print(f"\n{'='*60}")
print(f"Will rename {len(renames)} files ({unchanged} unchanged):")
for old, new, lang, vid in renames[:10]:
    print(f"  [{lang}] {old.name[:60]}...")
    print(f"      -> {new.name[:60]}...")
if len(renames) > 10:
    print(f"  ... and {len(renames)-10} more")

if errors:
    print(f"\nMISSING ({len(errors)}):")
    for e in errors:
        print(f"  {e}")

if not renames:
    print("\nNothing to rename.")
    exit(0)

print(f"\nType 'yes' to confirm: ", end='')
confirm = input().strip()
if confirm.lower() != 'yes':
    print("Aborted.")
    exit(0)

# Do renames
for old, new, lang, vid in renames:
    old.rename(new)
    print(f"OK: {old.name[:50]}... -> {new.name[:50]}...")

# Write updated mapping
with open(MAPPING_PATH, 'w', encoding='utf-8') as f:
    json.dump(mapping, f, ensure_ascii=False, indent=2)
print(f"\nUpdated {MAPPING_PATH}")
print("Done.")
