#!/usr/bin/env python3
"""Mirror the public Google Docs CV to a GitHub Pages PDF.

Run by .github/workflows/update-cv.yml. Does not require a personal
access token: GitHub Actions uses the repository's GITHUB_TOKEN to commit.
"""
from __future__ import annotations

import argparse
from io import BytesIO
from pathlib import Path
import sys
import time

import fitz
from pypdf import PdfReader, PdfWriter
import requests

DOC_ID = '16_NuvWWbNeWrBwwGzl6Yj0iOpQr2VLSaCWu7hb9FeZY'
OUTPUT = Path('cv.pdf')


def fetch_pdf() -> bytes:
    url = f'https://docs.google.com/document/d/{DOC_ID}/export'
    session = requests.Session()
    last_error = None
    for attempt in range(3):
        try:
            response = session.get(
                url,
                params={'format': 'pdf', 'tab': 't.0'},
                headers={'User-Agent': 'Mozilla/5.0 (compatible; Academic-CV-Sync/1.0)'},
                timeout=45,
                allow_redirects=True,
            )
            response.raise_for_status()
            data = response.content
            if not data.startswith(b'%PDF-'):
                raise RuntimeError(
                    'Google did not return a PDF. Please ensure the Google Doc is '
                    'shared as Anyone with the link / Viewer and PDF export is allowed. '
                    f'Content-Type: {response.headers.get("Content-Type", "unknown")}'
                )
            return data
        except (requests.RequestException, RuntimeError) as exc:
            last_error = exc
            if attempt < 2:
                time.sleep(2 * (attempt + 1))
    raise RuntimeError(f'Unable to export the Google Doc: {last_error}')


def remove_title_page_if_present(pdf_data: bytes) -> bytes:
    reader = PdfReader(BytesIO(pdf_data))
    if not reader.pages:
        raise RuntimeError('Exported PDF has no pages.')
    first_page_text = (reader.pages[0].extract_text() or '').strip()
    # The source document currently exports a cover-only tab as its first page.
    # Remove it only if clearly a very short cover; never blindly drop CV content.
    cover_only = len(reader.pages) > 1 and len(first_page_text) < 65
    if not cover_only:
        return pdf_data
    print(f'Skipping title-only first page ({first_page_text!r}).')
    writer = PdfWriter()
    for page in reader.pages[1:]:
        writer.add_page(page)
    output = BytesIO()
    writer.write(output)
    return output.getvalue()


def visually_equal(a: bytes, b: bytes) -> bool:
    """Ignore export timestamps but detect actual CV content/layout changes."""
    try:
        with fitz.open(stream=a, filetype='pdf') as pdf_a, fitz.open(stream=b, filetype='pdf') as pdf_b:
            if len(pdf_a) != len(pdf_b):
                return False
            for page_a, page_b in zip(pdf_a, pdf_b):
                thumb_a = page_a.get_pixmap(matrix=fitz.Matrix(.7, .7), alpha=False)
                thumb_b = page_b.get_pixmap(matrix=fitz.Matrix(.7, .7), alpha=False)
                if (thumb_a.width, thumb_a.height, thumb_a.samples) != (thumb_b.width, thumb_b.height, thumb_b.samples):
                    return False
        return True
    except Exception as exc:
        print(f'Cannot compare renders ({exc}); updating PDF as a precaution.', file=sys.stderr)
        return False


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('--source-pdf', type=Path, help='Use local exported PDF for testing.')
    parser.add_argument('--output', type=Path, default=OUTPUT)
    args = parser.parse_args()
    data = args.source_pdf.read_bytes() if args.source_pdf else fetch_pdf()
    data = remove_title_page_if_present(data)
    try:
        new_document = fitz.open(stream=data, filetype='pdf')
        pages = len(new_document)
        new_document.close()
    except Exception as exc:
        raise RuntimeError(f'Invalid PDF returned: {exc}') from exc
    if pages < 1:
        raise RuntimeError('PDF had zero usable pages.')
    if args.output.exists() and visually_equal(args.output.read_bytes(), data):
        print(f'CV PDF is already up to date ({pages} pages).')
        return
    args.output.write_bytes(data)
    print(f'Updated {args.output} ({pages} pages).')


if __name__ == '__main__':
    main()
