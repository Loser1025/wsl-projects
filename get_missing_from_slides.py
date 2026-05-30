#!/usr/bin/env python3
import json
import sys
from google.oauth2 import service_account
from googleapiclient.discovery import build

# Configuration
SERVICE_ACCOUNT_FILE = '/home/loser/wsl-projects/ageless-impulse-488713-m6-03014b3cddad.json'
PRESENTATION_ID = '1YIfc0YPCiqFFzInkfuhipkh8rC8X66i5VPpqIJS9HOE'  # extracted from URL
SCOPES = ['https://www.googleapis.com/auth/presentations.readonly']
MEMBER_LIST_FILE = '/home/loser/wsl-projects/メンリスト'
OUTPUT_FILE = '/home/loser/wsl-projects/メンリストにいない人分'

def main():
    # Load member list
    try:
        with open(MEMBER_LIST_FILE, 'r', encoding='utf-8') as f:
            member_names = set(line.strip() for line in f if line.strip())
    except FileNotFoundError:
        print(f'Member list file not found: {MEMBER_LIST_FILE}', file=sys.stderr)
        sys.exit(1)

    # Authenticate using service account
    credentials = service_account.Credentials.from_service_account_file(
        SERVICE_ACCOUNT_FILE, scopes=SCOPES)
    service = build('slides', 'v1', credentials=credentials)

    # Get presentation
    try:
        presentation = service.presentations().get(presentationId=PRESENTATION_ID).execute()
    except Exception as e:
        print(f'Failed to fetch presentation: {e}', file=sys.stderr)
        sys.exit(1)

    # Extract all text from slides
    slide_texts = []
    for slide in presentation.get('slides', []):
        for element in slide.get('pageElements', []):
            if 'shape' in element:
                shape = element['shape']
                if 'text' in shape:
                    text_elements = shape['text'].get('textElements', [])
                    for elem in text_elements:
                        if 'textRun' in elem:
                            content = elem['textRun'].get('content', '')
                            slide_texts.append(content)

    # Combine and split into lines/words
    full_text = ''.join(slide_texts)
    # Normalize newlines and split by whitespace
    # Replace various newline characters
    import re
    lines = re.split(r'[\r\n]+', full_text)
    # Further split by spaces if needed, but names may contain spaces? Japanese names usually no space.
    # We'll strip each line and treat as candidate name if not empty.
    slide_names = set()
    for line in lines:
        stripped = line.strip()
        if stripped:
            slide_names.add(stripped)

    # Compute difference: names in slide but not in member list
    missing = slide_names - member_names

    # Output result
    with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
        for name in sorted(missing):
            f.write(name + '\n')

    print(f'Found {len(missing)} names not in member list. Output written to {OUTPUT_FILE}')
    if missing:
        print('Missing names:', ', '.join(sorted(missing)))

if __name__ == '__main__':
    main()