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

import datetime
import json
import os
import re
import sys
import io
import html
import time
import urllib.request
from collections import defaultdict
from difflib import SequenceMatcher
from pathlib import Path

from meufan_core import KNOWN_LANGS, normalize_srt_ref, extract_lang

if sys.platform == 'win32':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

BASE_DIR = Path(__file__).parent
MAPPING_PATH = BASE_DIR / 'mapping.json'
SUBTITLE_DIR = BASE_DIR / 'subtitles'
DATA_DIR = BASE_DIR / 'data'
PUBLISH_CACHE_PATH = DATA_DIR / 'youtube_publish_cache.json'
PLAYLIST_URL = 'https://www.youtube.com/playlist?list=PLPI_XuP-34e7OFxjz2udmZSKlyuDcAhiu'
PLAYLIST_PAGE_URL = PLAYLIST_URL + '&hl=en&gl=US'

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
        # Try old format (playlistVideoRenderer) first, then new format (lockupViewModel)
        renderers = find_playlist_video_renderers(initial_data)
        use_new_format = False
        if not renderers:
            renderers = find_playlist_lockup_viewmodels(initial_data)
            use_new_format = True
    except Exception as e:
        print(f"ERROR: cannot fetch playlist page: {e}")
        sys.exit(1)

    videos = []
    seen = set()
    for renderer in renderers:
        if use_new_format:
            video_id = extract_lockup_video_id(renderer)
            title = extract_lockup_title(renderer)
            duration = extract_lockup_duration(renderer)
            thumbnail_url = extract_lockup_thumbnail(renderer)
            published_at = ''  # lockupViewModel doesn't include publish date
        else:
            video_id = renderer.get('videoId') or ''
            title = text_from_runs(renderer.get('title')) or renderer.get('title', {}).get('simpleText', '')
            duration = parse_duration_seconds(text_from_runs(renderer.get('lengthText')))
            thumbnail_url = best_thumbnail_url(renderer.get('thumbnail'))
            published_at = find_video_date(renderer)

        if not video_id or video_id in seen:
            continue
        seen.add(video_id)

        title = html.unescape(title).strip()
        if not title or title.lower() in ('private video', 'deleted video'):
            continue

        if not published_at:
            published_at = find_video_date(renderer) if not use_new_format else ''

        videos.append({
            'videoId': video_id,
            'videoUrl': f'https://www.youtube.com/watch?v={video_id}',
            'title': title,
            'duration': duration,
            'thumbnailUrl': thumbnail_url,
            'liveStatus': '',
            'publishedAt': published_at,
        })

    if not videos:
        print("ERROR: no videos found in playlist page")
        sys.exit(1)

    return videos


# ===== New lockupViewModel format (YouTube 2026 redesign) =====

def find_playlist_lockup_viewmodels(obj):
    """Find all lockupViewModel entries for videos in the playlist data.
    The new YouTube format stores videos in:
      tabs[].tabRenderer.content.sectionListRenderer.contents[].itemSectionRenderer.contents[].lockupViewModel
    """
    found = []

    def search(o):
        if isinstance(o, dict):
            # Direct lockupViewModel hit
            if 'lockupViewModel' in o:
                lockup = o['lockupViewModel']
                if isinstance(lockup, dict) and lockup.get('contentType') == 'LOCKUP_CONTENT_TYPE_VIDEO':
                    found.append(lockup)
                    return
            # itemSectionRenderer.contents may contain lockupViewModels
            item_section = o.get('itemSectionRenderer')
            if isinstance(item_section, dict):
                contents = item_section.get('contents')
                if isinstance(contents, list):
                    for item in contents:
                        search(item)
                    return
            # Recurse into dict values
            for value in o.values():
                search(value)
        elif isinstance(o, list):
            for item in o:
                search(item)

    search(obj)
    return found


def extract_lockup_video_id(lockup):
    """Extract video ID from a lockupViewModel."""
    return lockup.get('contentId') or ''


def extract_lockup_title(lockup):
    """Extract title from a lockupViewModel."""
    metadata = lockup.get('metadata', {})
    lockup_meta = metadata.get('lockupMetadataViewModel', {})
    title_obj = lockup_meta.get('title', {})
    return title_obj.get('content', '') if isinstance(title_obj, dict) else str(title_obj or '')


def extract_lockup_duration(lockup):
    """Extract duration in seconds from a lockupViewModel.
    Duration is in: contentImage.thumbnailViewModel.overlays[0].thumbnailBottomOverlayViewModel.badges[0].thumbnailBadgeViewModel.text
    """
    try:
        overlays = lockup.get('contentImage', {}).get('thumbnailViewModel', {}).get('overlays', [])
        for overlay in overlays:
            bottom_overlay = overlay.get('thumbnailBottomOverlayViewModel')
            if not isinstance(bottom_overlay, dict):
                continue
            badges = bottom_overlay.get('badges', [])
            for badge in badges:
                badge_vm = badge.get('thumbnailBadgeViewModel')
                if isinstance(badge_vm, dict) and badge_vm.get('text'):
                    return parse_duration_seconds(badge_vm['text'])
    except Exception:
        pass
    return 0


def extract_lockup_thumbnail(lockup):
    """Extract best thumbnail URL from a lockupViewModel."""
    try:
        sources = lockup.get('contentImage', {}).get('thumbnailViewModel', {}).get('image', {}).get('sources', [])
        if not sources:
            return ''
        best = max(sources, key=lambda t: (t.get('width') or 0) * (t.get('height') or 0))
        return best.get('url') or ''
    except Exception:
        return ''


def load_publish_cache():
    if not PUBLISH_CACHE_PATH.exists():
        return {}
    try:
        with open(PUBLISH_CACHE_PATH, 'r', encoding='utf-8') as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def save_publish_cache(cache):
    DATA_DIR.mkdir(exist_ok=True)
    with open(PUBLISH_CACHE_PATH, 'w', encoding='utf-8') as f:
        json.dump(cache, f, ensure_ascii=False, indent=2)


def fetch_publish_dates(videos, existing_lookup=None):
    """Fetch publish dates for videos by scraping individual watch pages."""
    if existing_lookup is None:
        existing_lookup = {}

    cache = load_publish_cache()
    need_dates = []
    for v in videos:
        vid = v['videoId']
        existing_date = existing_lookup.get(vid, {}).get('publishedAt', '')
        cached_date = cache.get(vid, {}).get('publishedAt', '') if isinstance(cache.get(vid), dict) else ''
        if existing_date:
            v['publishedAt'] = existing_date
        elif v.get('publishedAt'):
            cache[vid] = {'publishedAt': v['publishedAt'], 'fetchedAt': datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0).isoformat(), 'source': 'playlist'}
        elif cached_date:
            v['publishedAt'] = cached_date
        else:
            need_dates.append(v)

    if not need_dates:
        print(f"\n  All publish dates already cached ({len(videos)} videos)")
        save_publish_cache(cache)
        return

    print(f"\n  Fetching publish dates for {len(need_dates)} new videos...")
    fetched = 0
    for i, v in enumerate(need_dates):
        try:
            date_str = fetch_video_publish_date(v['videoId'])
            if date_str:
                v['publishedAt'] = date_str
                cache[v['videoId']] = {'publishedAt': date_str, 'fetchedAt': datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0).isoformat(), 'source': 'watch'}
                fetched += 1
        except Exception as e:
            print(f"    date fetch failed for {v['videoId']}: {e}")

        if (i + 1) % 5 == 0:
            print(f"    {i+1}/{len(need_dates)}...")
        time.sleep(0.5)

    save_publish_cache(cache)
    print(f"  Fetched {fetched}/{len(need_dates)} publish dates")


def fetch_video_publish_date(video_id):
    """Fetch a single video's watch page and extract the publish date."""
    url = f'https://www.youtube.com/watch?v={video_id}&gl=US&hl=en'
    page = fetch_url(url)
    date_str = find_video_date_in_page(page)
    if date_str:
        return parse_youtube_date(date_str)
    return ''


def find_video_date_in_page(page):
    for pattern in (
        r'"publishDate"\s*:\s*"([^"\\]+)"',
        r'"uploadDate"\s*:\s*"([^"\\]+)"',
        r'"datePublished"\s*:\s*"([^"\\]+)"',
    ):
        match = re.search(pattern, page)
        if match:
            parsed = parse_youtube_date(html.unescape(match.group(1)))
            if parsed:
                return parsed
    try:
        return find_video_date(extract_yt_initial_data(page))
    except Exception:
        return ''


def find_video_date(obj):
    """Find publish date fields in YouTube JSON."""
    found = []

    def search(o):
        if isinstance(o, dict):
            microformat = o.get('playerMicroformatRenderer')
            if isinstance(microformat, dict):
                for key in ('publishDate', 'uploadDate', 'datePublished'):
                    parsed = parse_youtube_date(str(microformat.get(key) or ''))
                    if parsed:
                        found.append(parsed)
                        return
            for key in ('publishDate', 'uploadDate', 'datePublished'):
                if key in o:
                    parsed = parse_youtube_date(str(o.get(key) or ''))
                    if parsed:
                        found.append(parsed)
                        return
            renderer = o.get('videoPrimaryInfoRenderer')
            if isinstance(renderer, dict):
                date_text = renderer.get('dateText', {})
                date_value = text_from_runs(date_text)
                parsed = parse_youtube_date(date_value)
                if parsed:
                    found.append(parsed)
                    return
            for v in o.values():
                search(v)
                if found:
                    return
        elif isinstance(o, list):
            for item in o:
                search(item)
                if found:
                    return

    search(obj)
    return found[0] if found else ''


def parse_youtube_date(text):
    """Parse YouTube's dateText.simpleText into YYYY-MM-DD.
    Handles prefixed formats: 'Streamed live on Mar 7, 2026', 'Premiered Dec 25, 2025'
    And plain: 'Dec 25, 2025', '2025. 12. 25.', '25 Dec 2025', '2025年12月25日'
    """
    if not text:
        return ''

    text = html.unescape(str(text)).strip()
    text = re.sub(r'(?i)^(Streamed live on|Premiered|Premieres|Scheduled for|Published on)\s+', '', text)

    # "2025-12-25" / "2025. 12. 25." / "2025年12月25日"
    m = re.match(r'(\d{4})\s*[.\-/年]\s*(\d{1,2})\s*[.\-/月]\s*(\d{1,2})', text)
    if m:
        try:
            return datetime.date(int(m.group(1)), int(m.group(2)), int(m.group(3))).isoformat()
        except (ValueError, OverflowError):
            pass

    month_names = {
        'jan': 1, 'feb': 2, 'mar': 3, 'apr': 4, 'may': 5, 'jun': 6,
        'jul': 7, 'aug': 8, 'sep': 9, 'oct': 10, 'nov': 11, 'dec': 12,
        'january': 1, 'february': 2, 'march': 3, 'april': 4,
        'june': 6, 'july': 7, 'august': 8, 'september': 9,
        'october': 10, 'november': 11, 'december': 12,
    }
    lower = text.lower().strip()
    # "Dec 25, 2025"
    m = re.match(r'([a-z]+)\s+(\d{1,2}),?\s*(\d{4})', lower)
    if m and m.group(1) in month_names:
        try:
            return datetime.date(int(m.group(3)), month_names[m.group(1)], int(m.group(2))).isoformat()
        except (ValueError, OverflowError):
            pass

    # "25 Dec 2025"
    m = re.match(r'(\d{1,2})\s+([a-z]+)\s+(\d{4})', lower)
    if m and m.group(2) in month_names:
        try:
            return datetime.date(int(m.group(3)), month_names[m.group(2)], int(m.group(1))).isoformat()
        except (ValueError, OverflowError):
            pass

    return ''


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
            if find_playlist_video_renderers(candidate) or find_playlist_lockup_viewmodels(candidate):
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
            'youtubeUrl': old.get('youtubeUrl') or pv.get('videoUrl') or old.get('videoUrl') or f'https://www.youtube.com/watch?v={vid}',
            'title': pv['title'],
            'duration': pv.get('duration') or old.get('duration', 0),
            'thumbnailUrl': pv.get('thumbnailUrl') or old.get('thumbnailUrl', ''),
            'liveStatus': pv.get('liveStatus') or old.get('liveStatus', ''),
            'publishedAt': pv.get('publishedAt') or old.get('publishedAt', ''),
            'subtitles': {}
        }
        if old.get('bilibiliUrl'):
            entry['bilibiliUrl'] = old.get('bilibiliUrl')
        if old.get('bilibiliSubtitleOffset') is not None:
            entry['bilibiliSubtitleOffset'] = old.get('bilibiliSubtitleOffset')
        if isinstance(old.get('sources'), dict):
            entry['sources'] = old.get('sources')

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

    # 4.5 Fetch publish dates for new videos (scrapes individual watch pages)
    fetch_publish_dates(playlist, existing)

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
