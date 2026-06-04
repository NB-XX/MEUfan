#!/usr/bin/env python3
"""
Sync YouTube playlist data to mapping.json.
Fetches latest playlist, discovers local SRT files, auto-matches by title similarity,
merges with existing mapping.json (preserving manual edits), and writes updated file.

Usage:
  python sync_playlist.py              # Full sync
  python sync_playlist.py --dry-run    # Preview changes only
  python sync_playlist.py --no-match   # Skip SRT auto-matching
"""

import json
import os
import re
import sys
import io
import html
import urllib.request
from collections import defaultdict
from difflib import SequenceMatcher
from pathlib import Path

if sys.platform == 'win32':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

BASE_DIR = Path(__file__).parent
MAPPING_PATH = BASE_DIR / 'mapping.json'
SUBTITLE_DIR = BASE_DIR / 'subtitles'
PLAYLIST_URL = 'https://www.youtube.com/playlist?list=PLPI_XuP-34e7OFxjz2udmZSKlyuDcAhiu'
PLAYLIST_PAGE_URL = PLAYLIST_URL + '&hl=en&gl=US'

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


# ===== SRT Discovery (shared with build_data.py) =====

def extract_lang(filename):
    """Extract (base_stem, lang_code) from an SRT filename."""
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
            if alias in tokens or compact.endswith('-' + alias) or compact.endswith('.' + alias):
                return re.sub(r'([._-])' + re.escape(alias) + r'([._-](translation|translated|subtitle|subtitles))?$', '', name, flags=re.IGNORECASE), lang
            if alias_tokens and len(alias_tokens) > 1:
                for i in range(0, len(tokens) - len(alias_tokens) + 1):
                    if tokens[i:i + len(alias_tokens)] == alias_tokens:
                        return re.sub(r'([._-])' + re.escape(alias) + r'([._-](translation|translated|subtitle|subtitles))?$', '', name, flags=re.IGNORECASE), lang
    return name, DEFAULT_LANG


def discover_srt_groups(base_dir):
    """Discover all SRT files, grouped by base_stem."""
    groups = defaultdict(dict)
    for srt_path in sorted(base_dir.glob('*.srt')):
        base_stem, lang = extract_lang(srt_path.name)
        groups[base_stem][lang] = normalize_srt_ref(srt_path.name)
    return dict(groups)


# ===== Title Matching (shared with build_data.py) =====

def clean_title(title):
    """Extract a clean comparable version of a title."""
    t = title.strip()
    t = re.sub(r'^\d+\s*[-–—]\s*', '', t)
    for lang in KNOWN_LANGS:
        if t.lower().endswith('.' + lang):
            t = t[:-len('.' + lang)]
            break
    t = t.replace('｜', '|')
    t = re.sub(r'\.srt$', '', t, flags=re.IGNORECASE)
    t = re.sub(r'\s+', ' ', t).strip()
    return t


def similarity(a, b):
    """Compute string similarity between 0 and 1."""
    return SequenceMatcher(None, a.lower(), b.lower()).ratio()


def match_srt_to_videos(playlist_videos, srt_groups, threshold=0.55):
    """Match SRT groups to playlist videos by title similarity.
    Returns: { playlist_index: base_stem }
    """
    # Build pairs of (score, playlist_idx, srt_stem)
    pairs = []
    srt_stems = list(srt_groups.keys())
    for pi, pv in enumerate(playlist_videos):
        clean_pv = clean_title(pv['title'])
        for si, stem in enumerate(srt_stems):
            score = similarity(clean_pv, clean_title(stem))
            pairs.append((score, pi, si))

    pairs.sort(key=lambda x: x[0], reverse=True)

    used_pl = set()
    used_srt = set()
    matches = {}

    for score, pi, si in pairs:
        if pi not in used_pl and si not in used_srt and score > threshold:
            used_pl.add(pi)
            used_srt.add(si)
            matches[pi] = srt_stems[si]

    # Report
    for pi, pv in enumerate(playlist_videos):
        if pi in matches:
            stem = matches[pi]
            langs = '/'.join(srt_groups[stem].keys())
            print(f"  OK [{similarity(clean_title(pv['title']), clean_title(stem)):.2f}] {pv['title'][:60]}...")
            print(f"        -> [{langs}] {stem[:60]}...")
        else:
            # Find best unmatched score for info
            best = max((similarity(clean_title(pv['title']), clean_title(s)) for s in srt_stems), default=0)
            if best > 0.3:
                print(f"  -- [{best:.2f}] No match: {pv['title'][:60]}...")
            else:
                print(f"  -- No SRT: {pv['title'][:60]}...")

    # Report unmatched SRTs
    unmatched = [s for i, s in enumerate(srt_stems) if i not in used_srt]
    if unmatched:
        print(f"\n  Unmatched SRT groups ({len(unmatched)}):")
        for u in unmatched:
            langs = '/'.join(srt_groups[u].keys())
            print(f"    - [{langs}] {u[:60]}")

    return matches


# ===== YouTube Playlist Fetch (stdlib, no yt-dlp) =====

def fetch_playlist():
    """Fetch playlist data from YouTube's public playlist page."""
    print(f"Fetching playlist page: {PLAYLIST_URL}")
    try:
        page = fetch_url(PLAYLIST_PAGE_URL)
        initial_data = extract_yt_initial_data(page)
        renderers = find_playlist_video_renderers(initial_data)
    except Exception as e:
        print(f"ERROR: cannot fetch playlist page: {e}")
        sys.exit(1)

    videos = []
    seen = set()
    for renderer in renderers:
        video_id = renderer.get('videoId') or ''
        if not video_id or video_id in seen:
            continue
        seen.add(video_id)

        title = text_from_runs(renderer.get('title')) or renderer.get('title', {}).get('simpleText', '')
        title = html.unescape(title).strip()
        if not title or title.lower() in ('private video', 'deleted video'):
            continue

        videos.append({
            'videoId': video_id,
            'videoUrl': f'https://www.youtube.com/watch?v={video_id}',
            'title': title,
            'duration': parse_duration_seconds(text_from_runs(renderer.get('lengthText'))),
            'thumbnailUrl': best_thumbnail_url(renderer.get('thumbnail')),
            'liveStatus': '',
        })

    if not videos:
        print("ERROR: no videos found in playlist page")
        sys.exit(1)

    return videos


def fetch_url(url):
    request = urllib.request.Request(
        url,
        headers={
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
                          '(KHTML, like Gecko) Chrome/125.0 Safari/537.36',
            'Accept-Language': 'en-US,en;q=0.9',
        },
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        return response.read().decode('utf-8', errors='replace')


def extract_yt_initial_data(page):
    marker = 'ytInitialData'
    marker_pos = page.find(marker)
    fallback = None
    while marker_pos >= 0:
        assign_pos = page.find('=', marker_pos)
        if assign_pos < 0:
            break
        start = page.find('{', assign_pos)
        if start < 0:
            break
        try:
            end = find_json_object_end(page, start)
            candidate = json.loads(page[start:end])
            if fallback is None:
                fallback = candidate
            if find_playlist_video_renderers(candidate):
                return candidate
        except (ValueError, json.JSONDecodeError):
            pass
        marker_pos = page.find(marker, marker_pos + len(marker))
    if fallback is not None:
        return fallback
    raise ValueError('ytInitialData not found')


def find_json_object_end(text, start):
    depth = 0
    in_string = False
    escape = False
    for i in range(start, len(text)):
        ch = text[i]
        if in_string:
            if escape:
                escape = False
            elif ch == '\\':
                escape = True
            elif ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
        elif ch == '{':
            depth += 1
        elif ch == '}':
            depth -= 1
            if depth == 0:
                return i + 1
    raise ValueError('unterminated JSON object')


def find_playlist_video_renderers(obj):
    found = []
    if isinstance(obj, dict):
        renderer = obj.get('playlistVideoRenderer')
        if isinstance(renderer, dict):
            found.append(renderer)
        for value in obj.values():
            found.extend(find_playlist_video_renderers(value))
    elif isinstance(obj, list):
        for item in obj:
            found.extend(find_playlist_video_renderers(item))
    return found


def text_from_runs(value):
    if not isinstance(value, dict):
        return ''
    if 'simpleText' in value:
        return str(value.get('simpleText') or '')
    runs = value.get('runs') or []
    return ''.join(str(run.get('text') or '') for run in runs if isinstance(run, dict))


def best_thumbnail_url(thumbnail):
    thumbs = []
    if isinstance(thumbnail, dict):
        thumbs = thumbnail.get('thumbnails') or []
    if not thumbs:
        return ''
    best = max(thumbs, key=lambda t: (t.get('width') or 0) * (t.get('height') or 0))
    return best.get('url') or ''


def parse_duration_seconds(text):
    text = (text or '').strip()
    if not text:
        return 0
    parts = text.split(':')
    if not all(part.isdigit() for part in parts):
        return 0
    seconds = 0
    for part in parts:
        seconds = seconds * 60 + int(part)
    return seconds


# ===== Merge Logic =====

def load_existing_mapping():
    """Load existing mapping.json if it exists."""
    if not MAPPING_PATH.exists():
        return {}
    with open(MAPPING_PATH, 'r', encoding='utf-8') as f:
        data = json.load(f)
    # Build lookup by videoId
    lookup = {}
    for v in data.get('videos', []):
        lookup[v['videoId']] = v
    return lookup


def merge(existing, playlist, srt_matches, srt_groups):
    """Merge playlist data with existing mapping and SRT matches.
    Preserves manually-added subtitle entries in existing mapping.
    """
    result = []

    for pi, pv in enumerate(playlist):
        vid = pv['videoId']
        old = existing.get(vid, {})

        # Start with playlist data
        entry = {
            'videoId': vid,
            'videoUrl': pv.get('videoUrl') or old.get('videoUrl') or f'https://www.youtube.com/watch?v={vid}',
            'title': pv['title'],
            'duration': pv.get('duration') or old.get('duration', 0),
            'thumbnailUrl': pv.get('thumbnailUrl') or old.get('thumbnailUrl', ''),
            'liveStatus': pv.get('liveStatus') or old.get('liveStatus', ''),
            'subtitles': {}
        }

        # Preserve existing subtitle mappings (manual edits)
        if 'subtitles' in old and isinstance(old['subtitles'], dict):
            entry['subtitles'] = {lang: normalize_srt_ref(filename) for lang, filename in old['subtitles'].items()}
        elif 'srtFile' in old and old['srtFile']:
            # Legacy format
            entry['subtitles']['ko'] = normalize_srt_ref(old['srtFile'])

        # Add newly auto-matched SRTs (only if not already present)
        if pi in srt_matches:
            stem = srt_matches[pi]
            for lang, filename in srt_groups.get(stem, {}).items():
                if lang not in entry['subtitles']:
                    entry['subtitles'][lang] = filename

        result.append(entry)

    return result


# ===== Main =====

def main():
    dry_run = '--dry-run' in sys.argv
    no_match = '--no-match' in sys.argv

    # 1. Fetch playlist
    playlist = fetch_playlist()
    print(f"  Got {len(playlist)} videos from playlist")

    # 2. Discover local SRT files
    srt_groups = discover_srt_groups(SUBTITLE_DIR)
    total_files = sum(len(v) for v in srt_groups.values())
    print(f"\nLocal SRT files: {len(srt_groups)} groups ({total_files} files)")
    for stem, langs in srt_groups.items():
        lang_str = '/'.join(langs.keys())
        print(f"  [{lang_str}] {stem[:70]}...")

    # 3. Match SRTs to playlist
    if not no_match:
        print(f"\nMatching SRTs to playlist...")
        srt_matches = match_srt_to_videos(playlist, srt_groups)
        print(f"  Matched {len(srt_matches)} videos")
    else:
        print(f"\nSkipping SRT matching (--no-match)")
        srt_matches = {}

    # 4. Load existing mapping
    existing = load_existing_mapping()
    print(f"\nExisting mapping: {len(existing)} entries")

    # 5. Merge
    merged = merge(existing, playlist, srt_matches, srt_groups)

    # 6. Stats
    new_count = sum(1 for v in merged if v['videoId'] not in existing)
    updated_count = sum(1 for v in merged if v['videoId'] in existing)
    subtitle_videos = sum(1 for v in merged if len(v['subtitles']) > 0)
    total_subs = sum(len(v['subtitles']) for v in merged)

    print(f"\n{'='*50}")
    print(f"  Total:      {len(merged)} videos")
    print(f"  New:        {new_count}")
    print(f"  Updated:    {updated_count}")
    print(f"  With subs:  {subtitle_videos}")
    print(f"  SRT refs:   {total_subs}")

    # 7. Write
    output = {'videos': merged}
    if dry_run:
        print(f"\n  DRY RUN -- mapping.json NOT written")
        # Show sample entry
        if merged:
            print(f"\n  Sample entry:")
            sample = merged[min(5, len(merged)-1)]
            print(f"    {json.dumps(sample, ensure_ascii=False, indent=4)[:300]}")
    else:
        with open(MAPPING_PATH, 'w', encoding='utf-8') as f:
            json.dump(output, f, ensure_ascii=False, indent=2)
        print(f"\n  ✓ Written {MAPPING_PATH}")
        print(f"  Refresh the browser (or click 🔄) to load updated data")


if __name__ == '__main__':
    main()
