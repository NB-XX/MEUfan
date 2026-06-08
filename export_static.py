#!/usr/bin/env python3
"""Export the public MEUfan search app as static files for Cloudflare Pages."""

import datetime
import json
import shutil
from pathlib import Path

BASE_DIR = Path(__file__).parent.resolve()
DIST_DIR = BASE_DIR / 'dist'
ASSET_FILES = ('index.css', 'index.js')
MAPPING_PATH = BASE_DIR / 'mapping.json'
SUBTITLE_DIR = BASE_DIR / 'subtitles'
GLOSSARY_PATH = BASE_DIR / 'data' / 'glossary.json'


def read_json(path, default):
    if not path.exists():
        return default
    with path.open('r', encoding='utf-8') as f:
        return json.load(f)


def write_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write('\n')


def copy_file(src, dst):
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)


def clean_dist():
    dist = DIST_DIR.resolve()
    if dist == BASE_DIR or BASE_DIR not in dist.parents:
        raise RuntimeError(f'Unsafe dist path: {dist}')
    if dist.exists():
        shutil.rmtree(dist)
    dist.mkdir(parents=True)


def collect_subtitle_refs(mapping):
    refs = set()
    for video in mapping.get('videos', []):
        subtitles = video.get('subtitles') or {}
        if not isinstance(subtitles, dict):
            continue
        for ref in subtitles.values():
            if isinstance(ref, str) and ref:
                refs.add(ref.replace('\\', '/'))
    return sorted(refs)


def validate_subtitle_ref(ref):
    if not ref.startswith('subtitles/') or not ref.lower().endswith('.srt'):
        raise RuntimeError(f'Invalid subtitle reference in mapping.json: {ref}')
    path = (BASE_DIR / ref).resolve()
    if not path.exists():
        raise RuntimeError(f'Missing subtitle referenced by mapping.json: {ref}')
    subtitles_base = SUBTITLE_DIR.resolve()
    if path != subtitles_base and subtitles_base not in path.parents:
        raise RuntimeError(f'Subtitle reference escapes subtitles/: {ref}')
    return path


def write_headers():
    headers = """# Cloudflare Pages headers for the public static app
/*
  X-Content-Type-Options: nosniff
  Referrer-Policy: strict-origin-when-cross-origin

/mapping.json
  Cache-Control: public, max-age=0, must-revalidate

/data/manifest.json
  Cache-Control: public, max-age=0, must-revalidate

/data/glossary.json
  Cache-Control: public, max-age=0, must-revalidate

/assets/*
  Cache-Control: public, max-age=0, must-revalidate

/subtitles/*
  Cache-Control: public, max-age=0, must-revalidate
"""
    (DIST_DIR / '_headers').write_text(headers, encoding='utf-8')


def main():
    if not MAPPING_PATH.exists():
        raise RuntimeError('mapping.json not found')

    mapping = read_json(MAPPING_PATH, {'videos': []})
    glossary = read_json(GLOSSARY_PATH, {'terms': []})
    subtitle_refs = collect_subtitle_refs(mapping)

    clean_dist()

    copy_file(BASE_DIR / 'index.html', DIST_DIR / 'index.html')
    for name in ASSET_FILES:
        copy_file(BASE_DIR / 'assets' / name, DIST_DIR / 'assets' / name)
    copy_file(MAPPING_PATH, DIST_DIR / 'mapping.json')

    for ref in subtitle_refs:
        copy_file(validate_subtitle_ref(ref), DIST_DIR / ref)

    generated_at = datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0).isoformat()
    manifest = {
        'schemaVersion': 1,
        'generatedAt': generated_at,
        'videos': mapping.get('videos', []),
        'glossary': glossary,
        'subtitleFiles': subtitle_refs,
        'counts': {
            'videos': len(mapping.get('videos', [])),
            'subtitleFiles': len(subtitle_refs),
        },
    }
    write_json(DIST_DIR / 'data' / 'manifest.json', manifest)
    write_json(DIST_DIR / 'data' / 'glossary.json', glossary)
    write_headers()

    print(f'Exported {len(mapping.get("videos", []))} videos and {len(subtitle_refs)} subtitles to {DIST_DIR}')
    print('Public files only: admin.html, server.py, and local data/admin_* files were not exported.')


if __name__ == '__main__':
    main()
