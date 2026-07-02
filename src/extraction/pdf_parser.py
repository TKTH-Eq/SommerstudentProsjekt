# src/extraction/pdf_parser.py

import fitz

def extract_text(pdf_path):
    pdf = fitz.open(pdf_path)

    text = ""

    for page in pdf:
        text += page.get_text()

    return text