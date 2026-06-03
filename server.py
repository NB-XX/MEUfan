#!/usr/bin/env python3
"""
MEUfan management server.
Serves static files + API for SRT upload, mapping CRUD, and playlist sync.
Usage: python server.py [--port 8080]
"""

import json
import os
import re
import sys
import io
import shutil
import subprocess
import urllib.parse
from pathlib import Path
from http.server import HTTPServer, SimpleHTTPRequestHandler

if sys.platform == 'win32':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

BASE_DIR = Path(__file__).parent
MAPPING_PATH = BASE_DIR / 'mapping.json'
SUBTITLE_DIR = BASE_DIR / 'subtitles'
DATA_DIR = BASE_DIR / 'data'
KNOWN_LANGS = ['ko', 'en', 'ja', 'zh']
LANG_LABELS = {'ko': '한국어', 'en': 'English', 'ja': '日本語', 'zh': '中文'}
SUBTITLE_PREFIX = 'subtitles/'
LANG_ALIASES = {
    'ko': ['ko', 'kor', 'kr', 'korean'],
    'en': ['en', 'eng', 'english'],
    'ja': ['ja', 'jp', 'jpn', 'japanese'],
    'zh': ['zh', 'zh-cn', 'zh-tw', 'zh-hans', 'zh-hant', 'cn', 'chinese'],
}


def ensure_dirs():
    SUBTITLE_DIR.mkdir(exist_ok=True)
    DATA_DIR.mkdir(exist_ok=True)


def normalize_srt_ref(filename):
    """Return the mapping path used by the frontend for an SRT file."""
    if not filename:
        return filename
    filename = filename.replace('\\', '/')
    if filename.startswith(SUBTITLE_PREFIX):
        return filename
    return SUBTITLE_PREFIX + os.path.basename(filename)


def srt_disk_path(filename):
    """Resolve an SRT mapping value to an on-disk path."""
    filename = (filename or '').replace('\\', '/')
    if filename.startswith(SUBTITLE_PREFIX):
        return BASE_DIR / filename
    return SUBTITLE_DIR / os.path.basename(filename)


def detect_lang_from_filename(filename):
    name = os.path.basename(filename).lower()
    stem = re.sub(r'\.srt$', '', name)
    tokens = [token for token in re.split(r'[^a-z0-9]+', stem) if token]
    compact = stem.replace('_', '-')
    for lang, aliases in LANG_ALIASES.items():
        for alias in aliases:
            alias_tokens = [token for token in re.split(r'[^a-z0-9]+', alias) if token]
            if alias in tokens or compact.endswith('-' + alias) or compact.endswith('.' + alias):
                return lang
            if alias_tokens and len(alias_tokens) > 1:
                for i in range(0, len(tokens) - len(alias_tokens) + 1):
                    if tokens[i:i + len(alias_tokens)] == alias_tokens:
                        return lang
    return None


def strip_lang_suffix(filename):
    """Remove known language suffixes from an SRT filename for title matching."""
    stem = os.path.basename(filename)
    stem = re.sub(r'\.srt$', '', stem, flags=re.IGNORECASE)
    stem = re.sub(r'\.srt([._-])', r'\1', stem, flags=re.IGNORECASE)
    for aliases in LANG_ALIASES.values():
        for alias in sorted(aliases, key=len, reverse=True):
            pattern = r'([._-])' + re.escape(alias) + r'([._-](translation|translated|subtitle|subtitles))?$'
            stem = re.sub(pattern, '', stem, flags=re.IGNORECASE)
    return stem


def detect_language(text):
    """Detect language from subtitle text content.
    Counts characters in each script, returns the dominant language code.
    """
    hangul = len(re.findall(r'[\uac00-\ud7af\u1100-\u11ff\u3130-\u318f]', text))
    hiragana = len(re.findall(r'[\u3040-\u309f]', text))
    katakana = len(re.findall(r'[\u30a0-\u30ff]', text))
    cjk = len(re.findall(r'[\u4e00-\u9fff]', text))
    latin = len(re.findall(r'[a-zA-Z]', text))

    kana = hiragana + katakana

    # Japanese: has kana (distinctive feature)
    if kana > 5:
        return 'ja'
    # Korean: has Hangul (distinctive feature)
    if hangul > 5:
        return 'ko'
    # Chinese: has CJK but no kana/hangul
    if cjk > 5:
        return 'zh'
    # Default: English
    return 'en'

PORT = 8080
for i, arg in enumerate(sys.argv):
    if arg == '--port' and i + 1 < len(sys.argv):
        PORT = int(sys.argv[i + 1])


def parse_multipart(body, boundary):
    """Parse multipart/form-data. Returns {fieldname: (filename, bytes)}."""
    if isinstance(body, str):
        body = body.encode('utf-8')
    if isinstance(boundary, str):
        boundary = boundary.encode('utf-8')

    parts = {}
    boundary_full = b'--' + boundary
    sections = body.split(boundary_full)

    for section in sections:
        if not section.strip() or section.strip() == b'--':
            continue
        # Split headers from body
        if b'\r\n\r\n' in section:
            header_part, content = section.split(b'\r\n\r\n', 1)
        elif b'\n\n' in section:
            header_part, content = section.split(b'\n\n', 1)
        else:
            continue

        # Remove trailing \r\n and boundary markers
        content = content.rstrip(b'\r\n')
        if content.endswith(b'--'):
            content = content[:-2]

        # Parse Content-Disposition header
        headers = header_part.decode('utf-8', errors='replace')
        name_match = re.search(r'name="([^"]+)"', headers)
        filename_match = re.search(r'filename="([^"]+)"', headers)

        if name_match:
            name = name_match.group(1)
            filename = filename_match.group(1) if filename_match else None
            parts[name] = (filename, content)

    return parts


def load_mapping():
    """Load mapping.json."""
    if not MAPPING_PATH.exists():
        return {'videos': []}
    with open(MAPPING_PATH, 'r', encoding='utf-8') as f:
        return json.load(f)


def save_mapping(data):
    """Save mapping.json."""
    with open(MAPPING_PATH, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def sanitize_filename(name):
    """Sanitize filename, preserving Korean/Chinese/Japanese characters."""
    # Remove path separators and null bytes
    name = name.replace('/', '_').replace('\\', '_').replace('\x00', '')
    # Strip leading/trailing whitespace and dots
    name = name.strip(' .')
    if not name:
        name = 'untitled.srt'
    return name


class APIHandler(SimpleHTTPRequestHandler):
    """HTTP handler serving static files + JSON API."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(BASE_DIR), **kwargs)

    def log_message(self, format, *args):
        # Quieter logging
        if '/api/' in str(args[0]) or 'admin' in str(args[0]):
            print(f"  {args[0]}")
        # Suppress static file logs unless verbose
        # sys.stderr.write(f"  {format % args}\n")

    def end_headers(self):
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, DELETE, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
        super().end_headers()

    def do_OPTIONS(self):
        self.send_response(200)
        self.end_headers()

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path

        if path == '/api/mapping':
            self.send_json(load_mapping())
        elif path == '/api/languages':
            self.send_json({'languages': KNOWN_LANGS, 'labels': LANG_LABELS})
        elif path == '/api/scan':
            # Scan for SRT files and report unmatched
            self.handle_scan()
        elif path == '/admin' or path == '/admin/':
            # Serve admin.html
            self.path = '/admin.html'
            super().do_GET()
        else:
            super().do_GET()

    def do_POST(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path

        if path == '/api/upload':
            self.handle_upload()
        elif path == '/api/upload-batch':
            self.handle_batch_upload()
        elif path == '/api/assign-batch':
            self.handle_batch_assign()
        elif path == '/api/assign':
            self.handle_assign()
        elif path == '/api/mapping':
            self.handle_save_mapping()
        elif path == '/api/sync':
            self.handle_sync()
        else:
            self.send_json({'error': 'Not found'}, 404)

    def do_DELETE(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path

        if path == '/api/srt':
            self.handle_delete_srt()
        else:
            self.send_json({'error': 'Not found'}, 404)

    # ===== API Handlers =====

    def handle_upload(self):
        """Upload an SRT file."""
        content_type = self.headers.get('Content-Type', '')
        if 'multipart/form-data' not in content_type:
            self.send_json({'error': 'Expected multipart/form-data'}, 400)
            return

        boundary = content_type.split('boundary=')[1].strip()
        content_length = int(self.headers.get('Content-Length', 0))
        body = self.rfile.read(content_length)
        parts = parse_multipart(body, boundary)

        file_part = parts.get('file') or parts.get('srt')
        if not file_part or not file_part[0]:
            self.send_json({'error': 'No file uploaded'}, 400)
            return

        filename, data = file_part
        filename = sanitize_filename(filename)

        # Ensure .srt extension
        if not filename.lower().endswith('.srt'):
            filename += '.srt'

        ensure_dirs()
        # Save to disk
        dest_path = SUBTITLE_DIR / filename
        with open(dest_path, 'wb') as f:
            f.write(data)

        # Detect language from filename
        detected_lang = detect_lang_from_filename(filename) or 'ko'

        # Count subtitles
        sub_count = 0
        try:
            text = data.decode('utf-8')
            detected_lang = detect_lang_from_filename(filename) or detect_language(text)
            sub_count = len(re.findall(r'\n\s*\n', text.strip())) + 1
        except:
            pass

        print(f"  Uploaded: {filename} ({len(data)} bytes, ~{sub_count} subs, lang={detected_lang})")

        self.send_json({
            'ok': True,
            'filename': normalize_srt_ref(filename),
            'detectedLang': detected_lang,
            'size': len(data),
            'subtitleCount': sub_count
        })

    def handle_batch_upload(self):
        """Upload multiple SRT files, auto-detect language from content,
        and suggest video matches by filename similarity (70% threshold)."""
        content_type = self.headers.get('Content-Type', '')
        if 'multipart/form-data' not in content_type:
            self.send_json({'error': 'Expected multipart/form-data'}, 400)
            return

        boundary = content_type.split('boundary=')[1].strip()
        content_length = int(self.headers.get('Content-Length', 0))
        body = self.rfile.read(content_length)
        parts = parse_multipart(body, boundary)

        from difflib import SequenceMatcher

        mapping = load_mapping()
        results = []
        skipped = 0
        total_sub_count = 0

        for name, (filename, data) in parts.items():
            if not filename or not data:
                continue

            filename = sanitize_filename(filename)
            if not filename.lower().endswith('.srt'):
                filename += '.srt'

            ensure_dirs()
            # Save file
            dest_path = SUBTITLE_DIR / filename
            # If exists, add number suffix
            if dest_path.exists():
                base = filename[:-4]
                ext = '.srt'
                counter = 2
                while dest_path.exists():
                    filename = f"{base}_{counter}{ext}"
                    dest_path = SUBTITLE_DIR / filename
                    counter += 1

            with open(dest_path, 'wb') as f:
                f.write(data)

            # Detect language from text content
            try:
                text = data.decode('utf-8')
            except:
                text = data.decode('utf-8', errors='replace')

            detected_lang = detect_lang_from_filename(filename) or detect_language(text)
            sub_count = len(re.findall(r'\n\s*\n', text.strip())) + 1
            total_sub_count += sub_count

            # Match to video by filename similarity (70% threshold)
            # Strip language suffix and .srt for matching
            match_stem = strip_lang_suffix(filename)

            best_score, best_video = 0, None
            for v in mapping.get('videos', []):
                def clean(t):
                    t = re.sub(r'^\d+\s*[-–—]\s*', '', t.strip())
                    t = t.replace('｜', '|')
                    return re.sub(r'\s+', ' ', t).strip()
                score = SequenceMatcher(None,
                    clean(match_stem).lower(),
                    clean(v['title']).lower()
                ).ratio()
                if score > best_score:
                    best_score, best_video = score, v

            results.append({
                'filename': normalize_srt_ref(filename),
                'detectedLang': detected_lang,
                'subtitleCount': sub_count,
                'size': len(data),
                'suggestedVideoId': best_video['videoId'] if best_video and best_score >= 0.7 else None,
                'suggestedTitle': best_video['title'] if best_video and best_score >= 0.7 else None,
                'matchScore': round(best_score, 3) if best_video else 0,
            })

            print(f"  Batch uploaded: {filename} (lang={detected_lang}, subs={sub_count}, match={best_score:.2f})")

        print(f"  Batch: {len(results)} files, {total_sub_count} total subs, {skipped} skipped")

        self.send_json({'ok': True, 'files': results})

    def handle_batch_assign(self):
        """Assign multiple SRT files to videos at once."""
        content_length = int(self.headers.get('Content-Length', 0))
        body = self.rfile.read(content_length)
        try:
            req = json.loads(body)
        except json.JSONDecodeError:
            self.send_json({'error': 'Invalid JSON'}, 400)
            return

        assignments = req.get('assignments', [])
        mapping = load_mapping()
        updated = 0

        for a in assignments:
            video_id = a.get('videoId')
            lang = a.get('lang')
            filename = a.get('filename')
            if not video_id or not lang or not filename:
                continue
            filename = normalize_srt_ref(filename)
            for v in mapping.get('videos', []):
                if v['videoId'] == video_id:
                    if 'subtitles' not in v:
                        v['subtitles'] = {}
                    v['subtitles'][lang] = filename
                    updated += 1
                    break

        save_mapping(mapping)
        print(f"  Batch assigned: {updated} files")
        self.send_json({'ok': True, 'assigned': updated})

    def handle_assign(self):
        """Assign an SRT file to a video+language."""
        content_length = int(self.headers.get('Content-Length', 0))
        body = self.rfile.read(content_length)
        try:
            req = json.loads(body)
        except json.JSONDecodeError:
            self.send_json({'error': 'Invalid JSON'}, 400)
            return

        video_id = req.get('videoId')
        lang = req.get('lang')
        filename = req.get('filename')
        remove = req.get('remove', False)

        if not video_id or not lang:
            self.send_json({'error': 'videoId and lang required'}, 400)
            return

        mapping = load_mapping()
        found = False

        for v in mapping.get('videos', []):
            if v['videoId'] == video_id:
                found = True
                if remove:
                    old_file = v.get('subtitles', {}).pop(lang, None)
                    print(f"  Unassigned: [{lang}] {old_file} from {video_id}")
                else:
                    if 'subtitles' not in v:
                        v['subtitles'] = {}
                    filename = normalize_srt_ref(filename)
                    old = v['subtitles'].get(lang)
                    v['subtitles'][lang] = filename
                    print(f"  Assigned: [{lang}] {filename} -> {video_id}" + (f" (was: {old})" if old else ""))
                break

        if not found:
            self.send_json({'error': f'Video not found: {video_id}'}, 404)
            return

        save_mapping(mapping)
        self.send_json({'ok': True})

    def handle_save_mapping(self):
        """Save entire mapping.json."""
        content_length = int(self.headers.get('Content-Length', 0))
        body = self.rfile.read(content_length)
        try:
            mapping = json.loads(body)
        except json.JSONDecodeError:
            self.send_json({'error': 'Invalid JSON'}, 400)
            return

        save_mapping(mapping)
        print(f"  Saved mapping.json ({len(mapping.get('videos', []))} videos)")
        self.send_json({'ok': True})

    def handle_delete_srt(self):
        """Delete an SRT file from disk and optionally from mapping."""
        qs = urllib.parse.urlparse(self.path).query
        params = urllib.parse.parse_qs(qs)
        filename = params.get('file', [None])[0]
        remove_mapping = params.get('removeMapping', ['1'])[0] == '1'

        if not filename:
            self.send_json({'error': 'file parameter required'}, 400)
            return

        filename = normalize_srt_ref(filename)
        filepath = srt_disk_path(filename)

        if not filepath.exists():
            self.send_json({'error': 'File not found'}, 404)
            return

        # Remove from mapping
        if remove_mapping:
            mapping = load_mapping()
            for v in mapping.get('videos', []):
                subs = v.get('subtitles', {})
                to_remove = [lang for lang, fn in subs.items() if normalize_srt_ref(fn) == filename]
                for lang in to_remove:
                    del subs[lang]
            save_mapping(mapping)

        # Delete file
        filepath.unlink()
        print(f"  Deleted: {filename}")
        self.send_json({'ok': True, 'filename': filename})

    def handle_scan(self):
        """Scan for SRT files and report matching suggestions."""
        from difflib import SequenceMatcher

        ensure_dirs()
        # Discover all SRTs
        srt_files = {}
        for f in sorted(SUBTITLE_DIR.glob('*.srt')):
            name = normalize_srt_ref(f.name)
            # Detect language
            lang = detect_lang_from_filename(name)
            # Count lines
            try:
                text = f.read_text(encoding='utf-8')
                if not lang:
                    lang = detect_language(text)
                count = len(re.findall(r'\n\s*\n', text.strip())) + 1
            except:
                lang = lang or 'ko'
                count = 0
            srt_files[name] = {'lang': lang, 'subs': count}

        # Get current mapping assignments
        mapping = load_mapping()
        assigned = set()
        for v in mapping.get('videos', []):
            for fn in v.get('subtitles', {}).values():
                assigned.add(normalize_srt_ref(fn))

        # Find unassigned SRTs
        unassigned = {name: info for name, info in srt_files.items() if name not in assigned}

        # Suggest matches for unassigned SRTs
        suggestions = []
        for name, info in unassigned.items():
            # Clean title for matching
            stem = strip_lang_suffix(name)

            # Find best match
            best_score, best_video = 0, None
            for v in mapping.get('videos', []):
                score = SequenceMatcher(None, stem.lower(), v['title'].lower()).ratio()
                if score > best_score:
                    best_score, best_video = score, v

            if best_video and best_score > 0.4:
                suggestions.append({
                    'filename': name,
                    'lang': info['lang'],
                    'subs': info['subs'],
                    'suggestedVideoId': best_video['videoId'],
                    'suggestedTitle': best_video['title'],
                    'score': round(best_score, 3)
                })

        self.send_json({
            'totalSrtFiles': len(srt_files),
            'assignedCount': len(assigned),
            'unassigned': list(unassigned.keys()),
            'suggestions': suggestions
        })

    def handle_sync(self):
        """Run sync_playlist.py."""
        try:
            result = subprocess.run(
                [sys.executable, str(BASE_DIR / 'sync_playlist.py')],
                capture_output=True, text=True, timeout=60, cwd=str(BASE_DIR)
            )
            self.send_json({
                'ok': result.returncode == 0,
                'output': result.stdout[-2000:] if result.stdout else '',
                'error': result.stderr[-1000:] if result.stderr else '',
                'exitCode': result.returncode
            })
        except subprocess.TimeoutExpired:
            self.send_json({'ok': False, 'error': 'Sync timed out'}, 500)
        except Exception as e:
            self.send_json({'ok': False, 'error': str(e)}, 500)

    # ===== Helpers =====

    def send_json(self, data, code=200):
        self.send_response(code)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.end_headers()
        self.wfile.write(json.dumps(data, ensure_ascii=False, indent=2).encode('utf-8'))


if __name__ == '__main__':
    print(f'MEUfan server starting on http://localhost:{PORT}')
    print(f'  App:   http://localhost:{PORT}/')
    print(f'  Admin: http://localhost:{PORT}/admin')
    print(f'  API:   http://localhost:{PORT}/api/mapping')
    print(f'  Press Ctrl+C to stop')

    server = HTTPServer(('0.0.0.0', PORT), APIHandler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print('\nServer stopped')
        server.server_close()
