"""Inventory an authorized local ZIP without trusting archive paths or modifying originals.

Outputs contain private data and belong under ignored data/ or private/ directories.
This performs no OCR, assigns no merchant labels and makes no train/test claims.
"""
import argparse
import hashlib
import io
import json
import sys
from collections import Counter
from pathlib import Path
from zipfile import ZipFile

from PIL import Image, ImageOps, ImageDraw


def inventory(archive, destination):
    destination = Path(destination)
    destination.mkdir(parents=True, exist_ok=True)
    originals = destination / 'images'
    originals.mkdir(exist_ok=True)
    records, rejected = [], []
    with ZipFile(archive) as source:
        entries = sorted((i for i in source.infolist() if not i.is_dir()
                          and '__MACOSX/' not in i.filename
                          and not Path(i.filename).name.startswith('.')), key=lambda i: i.filename)
        for i, member in enumerate(entries, 1):
            if member.file_size > 50_000_000:
                rejected.append({'archive_name': member.filename, 'reason': 'size_limit'})
                continue
            content = source.read(member)
            digest = hashlib.sha256(content).hexdigest()
            try:
                with Image.open(io.BytesIO(content)) as image:
                    image.load()
                    fmt = image.format
                    image = ImageOps.exif_transpose(image).convert('RGB')
                    size = image.size
                    pixels = hashlib.sha256(str(size).encode() + image.tobytes()).hexdigest()
                    small = image.convert('L').resize((9, 8))
                    p = list(small.getdata())
                    dhash = sum((p[y*9+x] > p[y*9+x+1]) << (y*8+x) for y in range(8) for x in range(8))
                if fmt not in ('JPEG', 'PNG', 'WEBP', 'TIFF'):
                    raise ValueError('unsupported image format')
            except Exception as exc:
                rejected.append({'archive_name': member.filename, 'reason': str(exc)})
                continue
            rid = f'real{i:03d}'
            extension = {'JPEG': '.jpg', 'PNG': '.png', 'WEBP': '.webp', 'TIFF': '.tiff'}[fmt]
            target = originals / (rid + extension)
            if target.exists() and hashlib.sha256(target.read_bytes()).hexdigest() != digest:
                raise ValueError(f'Refusing to overwrite changed image: {target}')
            if not target.exists():
                target.write_bytes(content)
            records.append({'id': rid, 'archive_name': member.filename,
                            'local_path': str(target), 'sha256': digest, 'pixel_sha256': pixels,
                            'dhash': f'{dhash:016x}', 'width': size[0], 'height': size[1],
                            'bytes': len(content), 'format': fmt})
    pairs = []
    for i, a in enumerate(records):
        for b in records[i+1:]:
            distance = (int(a['dhash'], 16) ^ int(b['dhash'], 16)).bit_count()
            if distance <= 5:
                pairs.append({'ids': [a['id'], b['id']], 'distance': distance,
                              'exact_pixels': a['pixel_sha256'] == b['pixel_sha256']})
    counts = Counter(r['pixel_sha256'] for r in records)
    result = {'archive_sha256': hashlib.sha256(Path(archive).read_bytes()).hexdigest(),
              'count': len(records), 'unique_pixels': len(counts),
              'duplicate_images': sum(n-1 for n in counts.values()),
              'near_duplicate_candidates': pairs, 'rejected': rejected, 'images': records,
              'split_status': 'unassigned; group by merchant/template before freezing holdout'}
    (destination/'inventory.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
    # Contact sheets are private review aids, not transformed OCR inputs.
    sheets = destination/'contact-sheets'
    sheets.mkdir(exist_ok=True)
    for offset in range(0, len(records), 24):
        canvas = Image.new('RGB', (1440, 1500), '#eeeae2')
        draw = ImageDraw.Draw(canvas)
        for index, record in enumerate(records[offset:offset+24]):
            x, y = index % 6 * 240, index // 6 * 375
            with Image.open(record['local_path']) as original:
                thumb = ImageOps.exif_transpose(original).convert('RGB')
                thumb.thumbnail((226, 338))
                canvas.paste(thumb, (x+(240-thumb.width)//2, y+25))
            draw.text((x+8, y+5), record['id'], fill='black')
        canvas.save(sheets/f'{offset//24+1:02d}.jpg', quality=85)
    return {key: result[key] for key in ('count','unique_pixels','duplicate_images','rejected')}


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('archive', type=Path)
    p.add_argument('--out', type=Path, default=Path('data/real-receipts'))
    args = p.parse_args()
    print(json.dumps(inventory(args.archive, args.out)))
