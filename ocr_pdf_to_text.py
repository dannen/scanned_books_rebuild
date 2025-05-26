import fitz  # PyMuPDF
import pytesseract
from PIL import Image
import io
import sys
import os

def ocr_pdf(input_pdf_path, output_text_path):
    doc = fitz.open(input_pdf_path)
    ocr_text = []

    print(f"Processing {len(doc)} pages from '{input_pdf_path}'...")

    for i in range(len(doc)):
        print(f"OCR page {i+1}/{len(doc)}")
        page = doc.load_page(i)
        pix = page.get_pixmap(dpi=300)
        img = Image.open(io.BytesIO(pix.tobytes("png")))
        text = pytesseract.image_to_string(img)
        ocr_text.append(text)

    with open(output_text_path, "w", encoding="utf-8") as f:
        f.write("\n\n".join(ocr_text))

    print(f"OCR completed. Output saved to '{output_text_path}'")

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python ocr_pdf_to_text.py <input.pdf> [output.txt]")
        sys.exit(1)

    input_file = sys.argv[1]
    output_file = sys.argv[2] if len(sys.argv) > 2 else os.path.splitext(input_file)[0] + "_ocr.txt"

    ocr_pdf(input_file, output_file)
