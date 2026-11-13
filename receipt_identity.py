"""Conservative merchant identity comparison, never an OCR correction.

Preserve Unicode letters and digits so different non-Latin names cannot
collapse to the same empty ASCII key. Only typography is normalized.
"""
import unicodedata


def merchant_key(value):
    if not isinstance(value, str):
        return None
    text = unicodedata.normalize('NFC', value).casefold().replace('&', 'and')
    key = ''.join(char for char in text if char.isalnum() or unicodedata.category(char).startswith('M'))
    return key if any(char.isalnum() for char in key) else None
