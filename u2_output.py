"""Preserve OCR text when a U2 block has malformed geometry.

Invalid coordinates are removed, never clamped into apparently valid evidence.
The untouched model output remains the canonical transcription in each cache.
"""
import re

BLOCK=re.compile(r'<BLOCK>\s*([a-z_]+)(?:<LEVEL(\d+)>)?\s*\[\s*(-?\d+)\s*,\s*(-?\d+)\s*,\s*(-?\d+)\s*,\s*(-?\d+)\s*\](?:<LEVEL(\d+)>)?\s*<FORK>',re.I)
NON_TEXT={'image','picture','figure','photo','illustration'}


def parse_output(text):
    blocks=[]; warnings=[]
    pages=text.split('<PAGE>')
    if pages and not pages[0].strip(): pages=pages[1:]
    for number,page in enumerate(pages,1):
        matches=list(BLOCK.finditer(page))
        if page.strip() and not matches:
            warnings.append(f'page_{number}:unsupported_block_format')
            blocks.append({'label':'unparsed_text','bbox':None,'content':page.strip(),'page':number})
        for index,match in enumerate(matches):
            box=[int(match.group(j)) for j in range(3,7)]
            valid=all(0<=value<=1000 for value in box) and box[0]<box[2] and box[1]<box[3]
            if not valid: warnings.append(f'page_{number}_block_{index}:invalid_coordinates')
            content=page[match.end():matches[index+1].start() if index+1<len(matches) else len(page)].strip()
            block={'label':match.group(1).lower(),'bbox':box if valid else None,
                   'content':content,'page':number,'level':int(match.group(2) or match.group(7)) if match.group(2) or match.group(7) else None}
            if not valid: block['invalid_bbox']=box
            blocks.append(block)
    return blocks,warnings


def has_text(record):
    for block in record.get('blocks',[]):
        if str(block.get('label','')).lower() in NON_TEXT: continue
        content=re.sub(r'<[^>]*>',' ',str(block.get('content','')))
        content=re.sub(r'\b(?:image|picture|figure|photo|text|table|title|header|footer|aside_text|other)\s*\[[\d\s.,-]+\]',' ',content,flags=re.I)
        if any(character.isalnum() for character in content): return True
    return False
