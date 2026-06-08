#!/usr/bin/env python3
"""Validate MEUfan project data and source files."""

import json
import py_compile
import subprocess
import sys
from pathlib import Path

BASE_DIR = Path(__file__).parent
MAPPING_PATH = BASE_DIR / 'mapping.json'
SUBTITLE_DIR = BASE_DIR / 'subtitles'


def rel(path):
    return str(path.relative_to(BASE_DIR)).replace('\\', '/')


def load_mapping():
    with MAPPING_PATH.open('r', encoding='utf-8') as f:
        return json.load(f)


def check_mapping():
    errors = []
    warnings = []
    data = load_mapping()
    videos = data.get('videos', [])
    refs = set()
    lang_counts = {}

    if not isinstance(videos, list):
        errors.append('mapping.json: "videos" must be a list')
        return errors, warnings

    seen_video_ids = set()
    for idx, video in enumerate(videos):
        video_id = video.get('videoId')
        if not video_id:
            errors.append(f'mapping.json: videos[{idx}] has no videoId')
            continue
        if video_id in seen_video_ids:
            errors.append(f'mapping.json: duplicate videoId {video_id}')
        seen_video_ids.add(video_id)

        subtitles = video.get('subtitles') or {}
        if not isinstance(subtitles, dict):
            errors.append(f'mapping.json: {video_id} subtitles must be an object')
            continue
        for lang, ref in subtitles.items():
            if not isinstance(ref, str) or not ref:
                errors.append(f'mapping.json: {video_id}/{lang} has invalid subtitle ref')
                continue
            refs.add(ref)
            lang_counts[lang] = lang_counts.get(lang, 0) + 1
            if not ref.startswith('subtitles/'):
                warnings.append(f'mapping.json: {video_id}/{lang} ref should start with subtitles/: {ref}')
            if not (BASE_DIR / ref).exists():
                errors.append(f'mapping.json: missing subtitle for {video_id}/{lang}: {ref}')

    srt_files = {rel(p) for p in SUBTITLE_DIR.glob('*.srt')} if SUBTITLE_DIR.exists() else set()
    unreferenced = sorted(srt_files - refs)
    for ref in unreferenced:
        warnings.append(f'unreferenced subtitle file: {ref}')

    print(f'videos: {len(videos)}')
    print(f'subtitle refs: {sum(lang_counts.values())}')
    print('languages:', ', '.join(f'{k}={v}' for k, v in sorted(lang_counts.items())) or '-')
    print(f'srt files: {len(srt_files)}')
    print(f'unreferenced srt files: {len(unreferenced)}')
    return errors, warnings


def check_python():
    errors = []
    for name in ['meufan_core.py', 'server.py', 'sync_playlist.py', 'build_data.py', 'rename_srts.py', 'check_project.py', 'archive_orphaned_srts.py', 'export_static.py']:
        path = BASE_DIR / name
        if not path.exists():
            continue
        try:
            py_compile.compile(str(path), doraise=True)
        except py_compile.PyCompileError as e:
            errors.append(f'{name}: {e.msg}')
    return errors


def check_frontend_js():
    errors = []
    node = 'node'
    script = r"""
const fs = require('fs');
for (const f of ['index.html', 'admin.html']) {
  const html = fs.readFileSync(f, 'utf8');
  const scripts = [...html.matchAll(/<script>([\s\S]*?)<\/script>/g)];
  for (let i = 0; i < scripts.length; i++) {
    new Function(scripts[i][1]);
  }
}
for (const f of ['assets/index.js', 'assets/admin.js']) {
  new Function(fs.readFileSync(f, 'utf8'));
}
"""
    try:
        result = subprocess.run(
            [node, '-e', script],
            cwd=str(BASE_DIR),
            capture_output=True,
            text=True,
            encoding='utf-8',
            errors='replace',
            timeout=10,
        )
    except FileNotFoundError:
        return ['node is not installed; cannot validate inline JavaScript']
    except subprocess.TimeoutExpired:
        return ['JavaScript validation timed out']
    if result.returncode != 0:
        errors.append((result.stderr or result.stdout or 'JavaScript validation failed').strip())
    return errors


def check_sensitive_paths():
    warnings = []
    for path in ['data/admin_config.json', 'data/admin_sessions.json', '.git/config']:
        if (BASE_DIR / path).exists():
            warnings.append(f'sensitive local file exists; server must not expose it: {path}')
    return warnings


def main():
    errors = []
    warnings = []

    try:
        e, w = check_mapping()
        errors.extend(e)
        warnings.extend(w)
    except Exception as e:
        errors.append(f'mapping check failed: {e}')

    errors.extend(check_python())
    errors.extend(check_frontend_js())
    warnings.extend(check_sensitive_paths())

    if warnings:
        print('\nWarnings:')
        for item in warnings:
            print('  - ' + item)
    if errors:
        print('\nErrors:')
        for item in errors:
            print('  - ' + item)
        return 1
    print('\nOK')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
