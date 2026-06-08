#!/usr/bin/env python3
"""
MEUfan management server.
Serves static files + API for SRT upload, mapping CRUD, and playlist sync.
Usage: python server.py [--port 8080]
"""

import base64
import datetime
import hashlib
import hmac
import io
import json
import os
import re
import secrets
import subprocess
import sys
import urllib.parse
from http import cookies
from http.server import HTTPServer, SimpleHTTPRequestHandler
from pathlib import Path

if sys.platform == 'win32':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

BASE_DIR = Path(__file__).parent
MAPPING_PATH = BASE_DIR / 'mapping.json'
SUBTITLE_DIR = BASE_DIR / 'subtitles'
DATA_DIR = BASE_DIR / 'data'
GLOSSARY_PATH = DATA_DIR / 'glossary.json'
ADMIN_CONFIG_PATH = DATA_DIR / 'admin_config.json'
ADMIN_SESSIONS_PATH = DATA_DIR / 'admin_sessions.json'
ADMIN_ACCESS_LOG = DATA_DIR / 'admin_access.log.jsonl'
ADMIN_ACTION_LOG = DATA_DIR / 'admin_actions.log.jsonl'
KNOWN_LANGS = ['ko', 'en', 'ja', 'zh']
LANG_LABELS = {'ko': '한국어', 'en': 'English', 'ja': '日本語', 'zh': '中文'}
SUBTITLE_PREFIX = 'subtitles/'
LANG_ALIASES = {
    'ko': ['ko', 'kor', 'kr', 'korean'],
    'en': ['en', 'eng', 'english'],
    'ja': ['ja', 'jp', 'jpn', 'japanese'],
    'zh': ['zh', 'zh-cn', 'zh-tw', 'zh-hans', 'zh-hant', 'cn', 'chinese'],
}
DEFAULT_GLOSSARY = {
    'terms': [
        {'id': 'zhan', 'label': 'Z-Han', 'aliases': {'ko': ['지한'], 'en': ['Z-Han', 'Z Han', 'ZHan'], 'ja': [], 'zh': ['智涵']}},
        {'id': 'ivi', 'label': 'Ivi', 'aliases': {'ko': ['이비'], 'en': ['Ivi'], 'ja': [], 'zh': ['依璧']}},
        {'id': 'sua', 'label': 'Sua', 'aliases': {'ko': ['수아'], 'en': ['Sua'], 'ja': [], 'zh': ['苏娅']}},
        {'id': 'ritz', 'label': 'Ritz', 'aliases': {'ko': ['리츠'], 'en': ['Ritz'], 'ja': [], 'zh': ['瑞慈']}},
        {'id': 'chouen', 'label': 'Chouen', 'aliases': {'ko': ['초은'], 'en': ['Chouen'], 'ja': [], 'zh': ['初恩']}},
    ]
}

PORT = 8080
for i, arg in enumerate(sys.argv):
    if arg == '--port' and i + 1 < len(sys.argv):
        PORT = int(sys.argv[i + 1])


def now_iso():
    return datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0).isoformat()


def ensure_dirs():
    SUBTITLE_DIR.mkdir(exist_ok=True)
    DATA_DIR.mkdir(exist_ok=True)


def read_json(path, default):
    if not path.exists():
        return default
    try:
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return default


def write_json(path, data):
    ensure_dirs()
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def append_log(path, data):
    ensure_dirs()
    data = dict(data)
    data.setdefault('ts', now_iso())
    with open(path, 'a', encoding='utf-8') as f:
        f.write(json.dumps(data, ensure_ascii=False, separators=(',', ':')) + '\n')


def normalize_srt_ref(filename):
    if not filename:
        return filename
    filename = filename.replace('\\', '/')
    if filename.startswith(SUBTITLE_PREFIX):
        return filename
    return SUBTITLE_PREFIX + os.path.basename(filename)


def safe_subtitle_path(filename, must_exist=False):
    ref = normalize_srt_ref(filename)
    if not ref or not ref.startswith(SUBTITLE_PREFIX) or not ref.lower().endswith('.srt'):
        raise ValueError('Invalid subtitle path')
    rel = ref[len(SUBTITLE_PREFIX):]
    if rel.startswith('/') or '..' in Path(rel).parts:
        raise ValueError('Invalid subtitle path')
    path = (SUBTITLE_DIR / rel).resolve()
    base = SUBTITLE_DIR.resolve()
    if path != base and base not in path.parents:
        raise ValueError('Invalid subtitle path')
    if must_exist and not path.exists():
        raise FileNotFoundError(ref)
    return ref, path


def srt_disk_path(filename):
    return safe_subtitle_path(filename)[1]


def detect_lang_from_filename(filename):
    name = os.path.basename(filename).lower()
    prefixed = re.match(r'^\[([a-z]{2}(?:-[a-z]{2,4})?)[-_][a-z0-9_-]+\]', name)
    if prefixed:
        token = prefixed.group(1)
        for lang, aliases in LANG_ALIASES.items():
            if token in aliases:
                return lang
    stem = re.sub(r'\.srt$', '', name)
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


def strip_lang_suffix(filename):
    stem = os.path.basename(filename)
    stem = re.sub(r'\.srt$', '', stem, flags=re.IGNORECASE)
    stem = re.sub(r'^\[[a-z]{2}(?:-[a-z]{2,4})?-[a-zA-Z0-9_-]+\]\s*', '', stem)
    stem = re.sub(r'\.srt([._-])', r'\1', stem, flags=re.IGNORECASE)
    for aliases in LANG_ALIASES.values():
        for alias in sorted(aliases, key=len, reverse=True):
            stem = re.sub(r'([._-])' + re.escape(alias) + r'([._-](translation|translated|subtitle|subtitles))?$', '', stem, flags=re.IGNORECASE)
    return stem


def detect_language(text):
    hangul = len(re.findall(r'[가-힯ᄀ-ᇿ㄰-㆏]', text))
    hiragana = len(re.findall(r'[぀-ゟ]', text))
    katakana = len(re.findall(r'[゠-ヿ]', text))
    cjk = len(re.findall(r'[一-鿿]', text))
    if hiragana + katakana > 5:
        return 'ja'
    if hangul > 5:
        return 'ko'
    if cjk > 5:
        return 'zh'
    return 'en'


def parse_multipart(body, boundary):
    if isinstance(body, str):
        body = body.encode('utf-8')
    if isinstance(boundary, str):
        boundary = boundary.encode('utf-8')
    parts = {}
    for section in body.split(b'--' + boundary):
        if not section.strip() or section.strip() == b'--':
            continue
        if b'\r\n\r\n' in section:
            header_part, content = section.split(b'\r\n\r\n', 1)
        elif b'\n\n' in section:
            header_part, content = section.split(b'\n\n', 1)
        else:
            continue
        content = content.rstrip(b'\r\n')
        if content.endswith(b'--'):
            content = content[:-2]
        headers = header_part.decode('utf-8', errors='replace')
        name_match = re.search(r'name="([^"]+)"', headers)
        filename_match = re.search(r'filename="([^"]*)"', headers)
        if name_match:
            parts[name_match.group(1)] = (filename_match.group(1) if filename_match else None, content)
    return parts


def part_text(parts, name, default=''):
    value = parts.get(name)
    if not value:
        return default
    return value[1].decode('utf-8', errors='replace')


def load_mapping():
    return read_json(MAPPING_PATH, {'videos': []})


def save_mapping(data):
    write_json(MAPPING_PATH, data)


def sanitize_filename(name):
    name = name.replace('/', '_').replace('\\', '_').replace('\x00', '').strip(' .')
    return name or 'untitled.srt'


def sanitize_title(name):
    name = re.sub(r'[/\\:*?"<>|]', '_', name)
    name = re.sub(r'[\x00-\x1f]', '', name)
    name = re.sub(r'\s+', ' ', name).strip()
    return (name[:120].rstrip() or 'untitled')


def make_srt_filename(lang, video_id, title):
    return f'[{lang}-{video_id}] {sanitize_title(title)}.srt'


def unique_subtitle_ref(ref, old_path=None):
    ref, path = safe_subtitle_path(ref)
    if old_path and path.resolve() == old_path.resolve():
        return ref, path
    if not path.exists():
        return ref, path
    stem = ref[:-4]
    counter = 1
    while True:
        candidate = f'{stem}_{counter}.srt'
        _, candidate_path = safe_subtitle_path(candidate)
        if not candidate_path.exists() or (old_path and candidate_path.resolve() == old_path.resolve()):
            return candidate, candidate_path
        counter += 1


def rename_srt_file(old_rel_path, new_rel_path):
    old_ref, old_path = safe_subtitle_path(old_rel_path, must_exist=True)
    new_ref, new_path = unique_subtitle_ref(new_rel_path, old_path)
    if old_path.resolve() != new_path.resolve():
        new_path.parent.mkdir(parents=True, exist_ok=True)
        old_path.rename(new_path)
    return new_ref


def count_subtitles(text):
    text = text.strip()
    if not text:
        return 0
    return len(re.split(r'\n\s*\n', text))


def parse_srt(text):
    cues = []
    for block in re.split(r'\n\s*\n', text.strip()):
        lines = block.strip().splitlines()
        if len(lines) < 2:
            continue
        time_line = lines[1] if re.match(r'^\d+\s*$', lines[0]) else lines[0]
        text_start = 2 if time_line == (lines[1] if len(lines) > 1 else '') else 1
        m = re.match(r'(\d{2}):(\d{2}):(\d{2})[,.](\d{3})\s*-->\s*(\d{2}):(\d{2}):(\d{2})[,.](\d{3})', time_line)
        if not m:
            continue
        vals = [int(x) for x in m.groups()]
        start = vals[0] * 3600 + vals[1] * 60 + vals[2] + vals[3] / 1000
        end = vals[4] * 3600 + vals[5] * 60 + vals[6] + vals[7] / 1000
        cues.append({'start': round(start, 3), 'end': round(end, 3), 'text': '\n'.join(lines[text_start:]).strip()})
    return cues


def srt_time(seconds):
    ms = int(round(float(seconds) * 1000))
    h, rem = divmod(ms, 3600000)
    m, rem = divmod(rem, 60000)
    s, ms = divmod(rem, 1000)
    return f'{h:02d}:{m:02d}:{s:02d},{ms:03d}'


def format_srt(cues):
    blocks = []
    for i, cue in enumerate(cues, 1):
        blocks.append(f'{i}\n{srt_time(cue["start"])} --> {srt_time(cue["end"])}\n{cue["text"].strip()}')
    return '\n\n'.join(blocks) + '\n'


def default_glossary():
    return json.loads(json.dumps(DEFAULT_GLOSSARY, ensure_ascii=False))


def load_glossary():
    ensure_dirs()
    if not GLOSSARY_PATH.exists():
        save_glossary(default_glossary())
    data = read_json(GLOSSARY_PATH, default_glossary())
    return validate_glossary(data)


def validate_glossary(data):
    terms = data.get('terms') if isinstance(data, dict) else []
    cleaned = []
    for term in terms if isinstance(terms, list) else []:
        aliases = term.get('aliases', {}) if isinstance(term, dict) else {}
        cleaned_aliases = {}
        for lang in KNOWN_LANGS:
            values = aliases.get(lang, []) if isinstance(aliases, dict) else []
            if isinstance(values, str):
                values = [values]
            cleaned_aliases[lang] = [str(v).strip() for v in values if str(v).strip()]
        label = str(term.get('label') or term.get('id') or '').strip()
        tid = re.sub(r'[^a-z0-9_-]+', '-', str(term.get('id') or label).lower()).strip('-') or f'term-{len(cleaned)+1}'
        if label or any(cleaned_aliases.values()):
            cleaned.append({'id': tid, 'label': label or tid, 'aliases': cleaned_aliases})
    return {'terms': cleaned}


def save_glossary(data):
    write_json(GLOSSARY_PATH, validate_glossary(data))


def hash_password(password, salt=None, iterations=260000):
    salt = salt or secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac('sha256', password.encode('utf-8'), salt.encode('utf-8'), iterations)
    return f'pbkdf2_sha256${iterations}${salt}${base64.b64encode(digest).decode("ascii")}'


def verify_password(password, stored):
    try:
        algo, iterations, salt, expected = stored.split('$', 3)
        if algo != 'pbkdf2_sha256':
            return False
        digest = hashlib.pbkdf2_hmac('sha256', password.encode('utf-8'), salt.encode('utf-8'), int(iterations))
        return hmac.compare_digest(base64.b64encode(digest).decode('ascii'), expected)
    except Exception:
        return False


def parse_admin_credentials(value):
    admins = []
    for item in (value or '').split(','):
        if ':' in item:
            alias, password = item.split(':', 1)
            alias = alias.strip()
            if alias and password:
                admins.append({'alias': alias, 'password': password})
    return admins


def admin_password_matches(password, admin):
    if admin.get('password') is not None:
        return hmac.compare_digest(password, str(admin.get('password')))
    return verify_password(password, admin.get('passwordHash', ''))


def public_admin(admin):
    return {'alias': admin.get('alias'), 'passwordHash': admin.get('passwordHash', ''), 'password': admin.get('password', '')}


def load_admin_config():
    config = read_json(ADMIN_CONFIG_PATH, {'admins': [], 'sessionHours': 24})
    env_passwords = os.environ.get('MEUFAN_ADMIN_PASSWORDS') or os.environ.get('ADMIN_PASSWORDS') or os.environ.get('ADMIN_CREDENTIALS') or ''
    if env_passwords:
        config['admins'] = parse_admin_credentials(env_passwords)
    config.setdefault('admins', [])
    config.setdefault('sessionHours', 24)
    return config


def load_sessions():
    return read_json(ADMIN_SESSIONS_PATH, {})


def save_sessions(data):
    write_json(ADMIN_SESSIONS_PATH, data)


def token_hash(token):
    return hashlib.sha256(token.encode('utf-8')).hexdigest()


LOGIN_PAGE = '''<!DOCTYPE html><html><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>MEU Admin Login</title><style>body{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;background:#fdf6f8;color:#4a3f4a;display:flex;align-items:center;justify-content:center;min-height:100vh;margin:0}.card{background:#fff;border:1px solid #f0dce3;border-radius:20px;padding:28px;box-shadow:0 4px 16px rgba(180,150,160,.12);width:min(92vw,360px)}h1{font-size:20px;color:#f0a0b4;margin:0 0 18px}input,button{width:100%;box-sizing:border-box;border-radius:999px;padding:11px 14px;font-size:14px;margin-top:10px}input{border:1px solid #f0dce3;background:#faf5f8;color:#4a3f4a}button{border:0;background:#f0a0b4;color:white;font-weight:700;cursor:pointer}.msg{font-size:12px;color:#c77;margin-top:12px;min-height:18px}</style></head><body><form class="card" id="f"><h1>MEU Admin Login</h1><input id="alias" placeholder="Alias" autocomplete="username"><input id="password" type="password" placeholder="Password" autocomplete="current-password"><button>Login</button><div class="msg" id="msg"></div></form><script>document.getElementById('f').addEventListener('submit',async e=>{e.preventDefault();msg.textContent='';try{let r=await fetch('/api/admin/login',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({alias:alias.value,password:password.value})});let j=await r.json();if(!r.ok||!j.ok)throw new Error(j.error||'Login failed');location.href='/admin';}catch(err){msg.textContent=err.message}})</script></body></html>'''


class APIHandler(SimpleHTTPRequestHandler):
    """HTTP handler serving static files + JSON API."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(BASE_DIR), **kwargs)

    def log_message(self, format, *args):
        if '/api/' in str(args[0]) or 'admin' in str(args[0]):
            print(f"  {args[0]}")

    def end_headers(self):
        self.send_header('Access-Control-Allow-Origin', self.headers.get('Origin', '*'))
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, DELETE, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
        self.send_header('Access-Control-Allow-Credentials', 'true')
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
        elif path == '/api/glossary':
            self.send_json(load_glossary())
        elif path == '/api/admin/session':
            self.handle_admin_session()
        elif path == '/api/scan':
            if not self.require_admin():
                return
            self.handle_scan()
        elif path in ('/admin', '/admin/', '/admin.html'):
            if not self.current_admin():
                append_log(ADMIN_ACCESS_LOG, {'event': 'admin_login_page', 'ip': self.client_address[0], 'ua': self.headers.get('User-Agent', '')})
                self.send_html(LOGIN_PAGE)
                return
            self.path = '/admin.html'
            super().do_GET()
        else:
            super().do_GET()

    def do_POST(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        public = {'/api/admin/login', '/api/admin/logout'}
        if path == '/api/admin/login':
            self.handle_admin_login()
            return
        if path == '/api/admin/logout':
            self.handle_admin_logout()
            return
        if path not in public and path in {
            '/api/upload', '/api/upload-batch', '/api/assign-batch', '/api/assign', '/api/mapping',
            '/api/sync', '/api/glossary', '/api/subtitles/standardize', '/api/subtitle/save'
        } and not self.require_admin():
            return
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
        elif path == '/api/glossary':
            self.handle_save_glossary()
        elif path == '/api/subtitles/standardize':
            self.handle_standardize_subtitles()
        elif path == '/api/subtitle/save':
            self.handle_save_subtitle_cue()
        elif path == '/api/srt/cleanup-batch':
            self.handle_cleanup_batch()
        else:
            self.send_json({'error': 'Not found'}, 404)

    def do_DELETE(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        if path == '/api/srt':
            if not self.require_admin():
                return
            self.handle_delete_srt()
        else:
            self.send_json({'error': 'Not found'}, 404)

    def read_json_body(self):
        content_length = int(self.headers.get('Content-Length', 0))
        body = self.rfile.read(content_length)
        return json.loads(body or b'{}')

    def current_admin(self):
        cookie_header = self.headers.get('Cookie', '')
        jar = cookies.SimpleCookie()
        try:
            jar.load(cookie_header)
        except cookies.CookieError:
            return None
        morsel = jar.get('meufan_admin_session')
        if not morsel:
            return None
        sessions = load_sessions()
        key = token_hash(morsel.value)
        session = sessions.get(key)
        if not session:
            return None
        expires = datetime.datetime.fromisoformat(session.get('expiresAt'))
        if expires < datetime.datetime.now(datetime.timezone.utc):
            sessions.pop(key, None)
            save_sessions(sessions)
            return None
        session['lastSeenAt'] = now_iso()
        sessions[key] = session
        save_sessions(sessions)
        return session.get('alias')

    def require_admin(self):
        alias = self.current_admin()
        if alias:
            return True
        self.send_json({'error': 'Admin login required'}, 401)
        return False

    def set_session_cookie(self, token, max_age):
        cookie = cookies.SimpleCookie()
        cookie['meufan_admin_session'] = token
        cookie['meufan_admin_session']['path'] = '/'
        cookie['meufan_admin_session']['httponly'] = True
        cookie['meufan_admin_session']['samesite'] = 'Lax'
        cookie['meufan_admin_session']['max-age'] = str(max_age)
        self.send_header('Set-Cookie', cookie.output(header=''))

    def clear_session_cookie(self):
        self.send_header('Set-Cookie', 'meufan_admin_session=; Path=/; Max-Age=0; HttpOnly; SameSite=Lax')

    def handle_admin_login(self):
        try:
            req = self.read_json_body()
        except json.JSONDecodeError:
            self.send_json({'error': 'Invalid JSON'}, 400)
            return
        alias = str(req.get('alias', '')).strip()
        password = str(req.get('password', ''))
        config = load_admin_config()
        admin = next((a for a in config.get('admins', []) if a.get('alias') == alias), None)
        if not admin or not admin_password_matches(password, admin):
            append_log(ADMIN_ACCESS_LOG, {'event': 'login_failed', 'alias': alias, 'ip': self.client_address[0], 'ua': self.headers.get('User-Agent', '')})
            self.send_json({'error': 'Invalid alias or password'}, 401)
            return
        token = secrets.token_urlsafe(32)
        hours = float(config.get('sessionHours') or 24)
        expires = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(hours=hours)
        sessions = load_sessions()
        sessions[token_hash(token)] = {'alias': alias, 'createdAt': now_iso(), 'lastSeenAt': now_iso(), 'expiresAt': expires.replace(microsecond=0).isoformat()}
        save_sessions(sessions)
        append_log(ADMIN_ACCESS_LOG, {'event': 'login_success', 'alias': alias, 'ip': self.client_address[0], 'ua': self.headers.get('User-Agent', '')})
        self.send_response(200)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.set_session_cookie(token, int(hours * 3600))
        self.end_headers()
        self.wfile.write(json.dumps({'ok': True, 'alias': alias}, ensure_ascii=False).encode('utf-8'))

    def handle_admin_logout(self):
        alias = self.current_admin()
        cookie_header = self.headers.get('Cookie', '')
        jar = cookies.SimpleCookie()
        try:
            jar.load(cookie_header)
            morsel = jar.get('meufan_admin_session')
            if morsel:
                sessions = load_sessions()
                sessions.pop(token_hash(morsel.value), None)
                save_sessions(sessions)
        except cookies.CookieError:
            pass
        if alias:
            append_log(ADMIN_ACCESS_LOG, {'event': 'logout', 'alias': alias, 'ip': self.client_address[0]})
        self.send_response(200)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.clear_session_cookie()
        self.end_headers()
        self.wfile.write(b'{"ok": true}')

    def handle_admin_session(self):
        alias = self.current_admin()
        self.send_json({'ok': True, 'admin': bool(alias), 'alias': alias})

    def log_action(self, action, **extra):
        alias = self.current_admin()
        append_log(ADMIN_ACTION_LOG, {'alias': alias, 'action': action, 'ip': self.client_address[0], **extra})

    def handle_upload(self):
        content_type = self.headers.get('Content-Type', '')
        if 'multipart/form-data' not in content_type or 'boundary=' not in content_type:
            self.send_json({'error': 'Expected multipart/form-data'}, 400)
            return
        boundary = content_type.split('boundary=', 1)[1].strip()
        body = self.rfile.read(int(self.headers.get('Content-Length', 0)))
        parts = parse_multipart(body, boundary)
        file_part = parts.get('file') or parts.get('srt')
        if not file_part or not file_part[0]:
            self.send_json({'error': 'No file uploaded'}, 400)
            return
        filename, data = file_part
        filename = sanitize_filename(filename)
        if not filename.lower().endswith('.srt'):
            filename += '.srt'
        video_id = part_text(parts, 'videoId').strip()
        requested_lang = part_text(parts, 'lang').strip()
        lang = requested_lang if requested_lang in KNOWN_LANGS else (detect_lang_from_filename(filename) or 'ko')
        overwrite = part_text(parts, 'overwrite').strip().lower() in ('1', 'true', 'yes')
        mapping = load_mapping()
        video = next((v for v in mapping.get('videos', []) if v.get('videoId') == video_id), None) if video_id else None
        old_ref = video.get('subtitles', {}).get(lang) if video and lang in KNOWN_LANGS else None
        if old_ref and not overwrite:
            self.send_json({'error': 'Subtitle already exists', 'requiresOverwrite': True, 'videoId': video_id, 'lang': lang, 'existingFile': old_ref}, 409)
            return
        if video and lang in KNOWN_LANGS:
            rel = SUBTITLE_PREFIX + make_srt_filename(lang, video_id, video.get('title', video_id))
            if old_ref and overwrite:
                rel, dest_path = safe_subtitle_path(old_ref)
            else:
                rel, dest_path = unique_subtitle_ref(rel)
        else:
            rel, dest_path = unique_subtitle_ref(SUBTITLE_PREFIX + filename)
        ensure_dirs()
        dest_path.write_bytes(data)
        try:
            text = data.decode('utf-8')
        except UnicodeDecodeError:
            text = data.decode('utf-8', errors='replace')
        detected_lang = detect_lang_from_filename(rel) or detect_language(text)
        if video and lang in KNOWN_LANGS:
            video.setdefault('subtitles', {})[lang] = rel
            save_mapping(mapping)
        self.log_action('upload_srt', file=rel, videoId=video_id, lang=lang)
        self.send_json({'ok': True, 'filename': rel, 'detectedLang': detected_lang, 'size': len(data), 'subtitleCount': count_subtitles(text), 'assigned': bool(video)})

    def handle_batch_upload(self):
        content_type = self.headers.get('Content-Type', '')
        if 'multipart/form-data' not in content_type or 'boundary=' not in content_type:
            self.send_json({'error': 'Expected multipart/form-data'}, 400)
            return
        boundary = content_type.split('boundary=', 1)[1].strip()
        body = self.rfile.read(int(self.headers.get('Content-Length', 0)))
        parts = parse_multipart(body, boundary)
        from difflib import SequenceMatcher
        mapping = load_mapping()
        results = []
        total_sub_count = 0
        for name, (filename, data) in parts.items():
            if not filename or not data:
                continue
            filename = sanitize_filename(filename)
            if not filename.lower().endswith('.srt'):
                filename += '.srt'
            rel, dest_path = unique_subtitle_ref(SUBTITLE_PREFIX + filename)
            dest_path.write_bytes(data)
            text = data.decode('utf-8', errors='replace')
            detected_lang = detect_lang_from_filename(filename) or detect_language(text)
            sub_count = count_subtitles(text)
            total_sub_count += sub_count
            match_stem = strip_lang_suffix(filename)
            best_score, best_video = 0, None
            for v in mapping.get('videos', []):
                def clean(t):
                    t = re.sub(r'^\d+\s*[-–—]\s*', '', t.strip()).replace('｜', '|')
                    return re.sub(r'\s+', ' ', t).strip()
                score = SequenceMatcher(None, clean(match_stem).lower(), clean(v['title']).lower()).ratio()
                if score > best_score:
                    best_score, best_video = score, v
            results.append({'filename': rel, 'detectedLang': detected_lang, 'subtitleCount': sub_count, 'size': len(data), 'suggestedVideoId': best_video['videoId'] if best_video and best_score >= 0.7 else None, 'suggestedTitle': best_video['title'] if best_video and best_score >= 0.7 else None, 'matchScore': round(best_score, 3) if best_video else 0})
        self.log_action('batch_upload_srt', files=len(results), subtitles=total_sub_count)
        self.send_json({'ok': True, 'files': results})

    def assign_file(self, mapping, video_id, lang, filename):
        filename = normalize_srt_ref(filename)
        for v in mapping.get('videos', []):
            if v.get('videoId') == video_id:
                new_rel = SUBTITLE_PREFIX + make_srt_filename(lang, video_id, v.get('title', video_id))
                new_rel = rename_srt_file(filename, new_rel)
                v.setdefault('subtitles', {})[lang] = new_rel
                return new_rel
        raise ValueError(f'Video not found: {video_id}')

    def handle_batch_assign(self):
        try:
            req = self.read_json_body()
        except json.JSONDecodeError:
            self.send_json({'error': 'Invalid JSON'}, 400)
            return
        mapping = load_mapping()
        updated = 0
        failed = []
        for a in req.get('assignments', []):
            try:
                if not a.get('videoId') or not a.get('lang') or not a.get('filename'):
                    continue
                self.assign_file(mapping, a['videoId'], a['lang'], a['filename'])
                updated += 1
            except Exception as e:
                failed.append({'filename': a.get('filename'), 'error': str(e)})
        save_mapping(mapping)
        self.log_action('assign_batch', assigned=updated, failed=len(failed))
        self.send_json({'ok': True, 'assigned': updated, 'failed': failed})

    def handle_assign(self):
        try:
            req = self.read_json_body()
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
        for v in mapping.get('videos', []):
            if v.get('videoId') == video_id:
                if remove:
                    old_file = v.get('subtitles', {}).pop(lang, None)
                    if old_file:
                        try:
                            _, filepath = safe_subtitle_path(old_file, must_exist=True)
                            filepath.unlink()
                        except Exception:
                            pass
                    save_mapping(mapping)
                    self.log_action('unassign_srt', videoId=video_id, lang=lang, file=old_file)
                    self.send_json({'ok': True, 'filename': None})
                    return
                try:
                    new_rel = self.assign_file(mapping, video_id, lang, filename)
                except Exception as e:
                    self.send_json({'error': str(e)}, 400)
                    return
                save_mapping(mapping)
                self.log_action('assign_srt', videoId=video_id, lang=lang, file=new_rel)
                self.send_json({'ok': True, 'filename': new_rel})
                return
        self.send_json({'error': f'Video not found: {video_id}'}, 404)

    def handle_save_mapping(self):
        try:
            mapping = self.read_json_body()
        except json.JSONDecodeError:
            self.send_json({'error': 'Invalid JSON'}, 400)
            return
        save_mapping(mapping)
        self.log_action('save_mapping', videos=len(mapping.get('videos', [])))
        self.send_json({'ok': True})

    def handle_delete_srt(self):
        params = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
        filename = params.get('file', [None])[0]
        remove_mapping = params.get('removeMapping', ['1'])[0] == '1'
        if not filename:
            self.send_json({'error': 'file parameter required'}, 400)
            return
        try:
            filename, filepath = safe_subtitle_path(filename, must_exist=True)
        except Exception as e:
            self.send_json({'error': str(e)}, 404)
            return
        if remove_mapping:
            mapping = load_mapping()
            for v in mapping.get('videos', []):
                subs = v.get('subtitles', {})
                for lang in [lang for lang, fn in subs.items() if normalize_srt_ref(fn) == filename]:
                    del subs[lang]
            save_mapping(mapping)
        filepath.unlink()
        self.log_action('delete_srt', file=filename)
        self.send_json({'ok': True, 'filename': filename})

    def handle_cleanup_batch(self):
        try:
            req = self.read_json_body()
        except json.JSONDecodeError:
            self.send_json({'error': 'Invalid JSON'}, 400)
            return
        files = req.get('files', [])
        if not isinstance(files, list):
            self.send_json({'error': 'files must be a list'}, 400)
            return
        deleted = []
        failed = []
        for filename in files:
            try:
                _, filepath = safe_subtitle_path(filename, must_exist=True)
                filepath.unlink()
                deleted.append(filename)
            except Exception as e:
                failed.append({'filename': filename, 'error': str(e)})
        self.log_action('cleanup_batch', deleted=len(deleted), failed=len(failed))
        self.send_json({'ok': True, 'deleted': deleted, 'failed': failed})

    def handle_scan(self):
        from difflib import SequenceMatcher
        ensure_dirs()
        srt_files = {}
        for f in sorted(SUBTITLE_DIR.glob('*.srt')):
            name = normalize_srt_ref(f.name)
            try:
                text = f.read_text(encoding='utf-8')
                lang = detect_lang_from_filename(name) or detect_language(text)
                count = count_subtitles(text)
            except Exception:
                lang, count = detect_lang_from_filename(name) or 'ko', 0
            srt_files[name] = {'lang': lang, 'subs': count}
        mapping = load_mapping()
        assigned = {normalize_srt_ref(fn) for v in mapping.get('videos', []) for fn in v.get('subtitles', {}).values()}
        unassigned = {name: info for name, info in srt_files.items() if name not in assigned}
        suggestions = []
        for name, info in unassigned.items():
            stem = strip_lang_suffix(name)
            best_score, best_video = 0, None
            for v in mapping.get('videos', []):
                score = SequenceMatcher(None, stem.lower(), v['title'].lower()).ratio()
                if score > best_score:
                    best_score, best_video = score, v
            if best_video and best_score > 0.4:
                suggestions.append({'filename': name, 'lang': info['lang'], 'subs': info['subs'], 'suggestedVideoId': best_video['videoId'], 'suggestedTitle': best_video['title'], 'score': round(best_score, 3)})
        self.send_json({'totalSrtFiles': len(srt_files), 'assignedCount': len(assigned), 'unassigned': list(unassigned.keys()), 'suggestions': suggestions})

    def handle_sync(self):
        try:
            env = os.environ.copy()
            env['PYTHONIOENCODING'] = 'utf-8'
            result = subprocess.run([sys.executable, str(BASE_DIR / 'sync_playlist.py')], capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=180, cwd=str(BASE_DIR), env=env)
            mapping = load_mapping()
            total = len(mapping.get('videos', []))
            published = sum(1 for v in mapping.get('videos', []) if v.get('publishedAt'))
            self.log_action('sync_youtube', ok=result.returncode == 0, total=total, publishedAt=published)
            self.send_json({'ok': result.returncode == 0, 'totalVideos': total, 'publishedAtPopulated': published, 'publishedAtMissing': total - published, 'output': result.stdout[-4000:] if result.stdout else '', 'error': result.stderr[-1000:] if result.stderr else '', 'exitCode': result.returncode})
        except subprocess.TimeoutExpired:
            self.send_json({'ok': False, 'error': 'Sync timed out'}, 500)
        except Exception as e:
            self.send_json({'ok': False, 'error': str(e)}, 500)

    def handle_save_glossary(self):
        try:
            data = self.read_json_body()
        except json.JSONDecodeError:
            self.send_json({'error': 'Invalid JSON'}, 400)
            return
        save_glossary(data)
        self.log_action('save_glossary', terms=len(validate_glossary(data).get('terms', [])))
        self.send_json({'ok': True, 'glossary': load_glossary()})

    def handle_standardize_subtitles(self):
        mapping = load_mapping()
        renamed, skipped, errors = 0, 0, []
        for v in mapping.get('videos', []):
            video_id = v.get('videoId')
            title = v.get('title') or video_id
            subs = v.get('subtitles', {})
            for lang, filename in list(subs.items()):
                try:
                    target = SUBTITLE_PREFIX + make_srt_filename(lang, video_id, title)
                    new_ref = rename_srt_file(filename, target)
                    if normalize_srt_ref(filename) == new_ref:
                        skipped += 1
                    else:
                        renamed += 1
                    subs[lang] = new_ref
                except Exception as e:
                    errors.append({'videoId': video_id, 'lang': lang, 'file': filename, 'error': str(e)})
        save_mapping(mapping)
        self.log_action('standardize_subtitles', renamed=renamed, skipped=skipped, errors=len(errors))
        self.send_json({'ok': len(errors) == 0, 'renamed': renamed, 'skipped': skipped, 'errors': errors})

    def handle_save_subtitle_cue(self):
        try:
            req = self.read_json_body()
        except json.JSONDecodeError:
            self.send_json({'error': 'Invalid JSON'}, 400)
            return
        video_id, lang = req.get('videoId'), req.get('lang')
        try:
            idx = int(req.get('index'))
            start = float(req.get('start'))
            end = float(req.get('end'))
        except (TypeError, ValueError):
            self.send_json({'error': 'Invalid index/start/end'}, 400)
            return
        text = str(req.get('text', '')).strip()
        if idx < 0 or start < 0 or end <= start or len(text) > 5000:
            self.send_json({'error': 'Invalid subtitle cue'}, 400)
            return
        mapping = load_mapping()
        video = next((v for v in mapping.get('videos', []) if v.get('videoId') == video_id), None)
        if not video or lang not in video.get('subtitles', {}):
            self.send_json({'error': 'Subtitle not found'}, 404)
            return
        try:
            ref, path = safe_subtitle_path(video['subtitles'][lang], must_exist=True)
            cues = parse_srt(path.read_text(encoding='utf-8'))
        except Exception as e:
            self.send_json({'error': str(e)}, 400)
            return
        if idx >= len(cues):
            self.send_json({'error': 'Subtitle index out of range'}, 400)
            return
        cues[idx] = {'start': round(start, 3), 'end': round(end, 3), 'text': text}
        path.write_text(format_srt(cues), encoding='utf-8')
        self.log_action('save_subtitle_cue', videoId=video_id, lang=lang, index=idx, file=ref)
        self.send_json({'ok': True, 'cue': cues[idx], 'subtitles': cues})

    def send_html(self, html, code=200):
        self.send_response(code)
        self.send_header('Content-Type', 'text/html; charset=utf-8')
        self.end_headers()
        self.wfile.write(html.encode('utf-8'))

    def send_json(self, data, code=200):
        self.send_response(code)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.end_headers()
        self.wfile.write(json.dumps(data, ensure_ascii=False, indent=2).encode('utf-8'))


if __name__ == '__main__':
    ensure_dirs()
    if not ADMIN_CONFIG_PATH.exists() and not os.environ.get('MEUFAN_ADMIN_PASSWORDS'):
        print('Admin auth is not configured. For local/dev, create data/admin_config.json with {"admins":[{"alias":"owner","password":"..."}]}; for deploy, set MEUFAN_ADMIN_PASSWORDS=owner:password,helper:password.')
    print(f'MEUfan server starting on http://localhost:{PORT}')
    print(f'  App:   http://localhost:{PORT}/')
    print(f'  Admin: http://localhost:{PORT}/admin')
    print(f'  API:   http://localhost:{PORT}/api/mapping')
    print('  Press Ctrl+C to stop')
    server = HTTPServer(('0.0.0.0', PORT), APIHandler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print('\nServer stopped')
        server.server_close()
