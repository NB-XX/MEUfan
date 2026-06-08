#!/usr/bin/env python3
"""Move unreferenced SRT files to data/orphaned_subtitles/ instead of deleting them."""

import datetime
import json
import shutil
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[1]
MAPPING_PATH = BASE_DIR / 'mapping.json'
SUBTITLE_DIR = BASE_DIR / 'subtitles'
ARCHIVE_ROOT = BASE_DIR / 'data' / 'orphaned_subtitles'


def rel(path):
    return str(path.relative_to(BASE_DIR)).replace('\\', '/')


def main():
    data = json.loads(MAPPING_PATH.read_text(encoding='utf-8'))
    refs = {
        ref
        for video in data.get('videos', [])
        for ref in (video.get('subtitles') or {}).values()
        if isinstance(ref, str)
    }
    srt_files = sorted(SUBTITLE_DIR.glob('*.srt'))
    orphaned = [path for path in srt_files if rel(path) not in refs]

    if not orphaned:
        print('No orphaned SRT files.')
        return 0

    stamp = datetime.datetime.now().strftime('%Y%m%d-%H%M%S')
    archive_dir = ARCHIVE_ROOT / stamp
    archive_dir.mkdir(parents=True, exist_ok=True)

    manifest = []
    for path in orphaned:
        target = archive_dir / path.name
        counter = 1
        while target.exists():
            target = archive_dir / f'{path.stem}_{counter}{path.suffix}'
            counter += 1
        shutil.move(str(path), str(target))
        manifest.append({'from': rel(path), 'to': rel(target), 'bytes': target.stat().st_size})
        print(f'archived {rel(path)} -> {rel(target)}')

    (archive_dir / 'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f'Archived {len(manifest)} file(s).')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
