import fitz
import cv2
import numpy as np
from PIL import Image
import io
import os
import sys

def extract_illustrations(pdf_path, output_dir):
    os.makedirs(output_dir, exist_ok=True)
    doc = fitz.open(pdf_path)
    count = 0

    for page_index in range(len(doc)):
        page = doc.load_page(page_index)
        pix = page.get_pixmap(dpi=300)
        img = Image.open(io.BytesIO(pix.tobytes("png"))).convert("L")
        open_cv_image = np.array(img)

        # Threshold to isolate drawings
        _, thresh = cv2.threshold(open_cv_image, 200, 255, cv2.THRESH_BINARY_INV)

        # Find contours
        contours, _ = cv2.findContours(thresh, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

        for i, cnt in enumerate(contours):
            x, y, w, h = cv2.boundingRect(cnt)
            if w > 100 and h > 100:  # Skip small artifacts
                cropped = img.crop((x, y, x + w, y + h))
                filename = f"page{page_index+1}_img{i+1}.png"
                cropped.save(os.path.join(output_dir, filename))
                count += 1
                print(f"Saved: {filename}")

    print(f"✅ Done. {count} cropped images saved to {output_dir}")

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python detect_and_crop_illustrations.py <input.pdf> [output_dir]")
        sys.exit(1)

    pdf_path = sys.argv[1]
    output_dir = sys.argv[2] if len(sys.argv) > 2 else os.path.splitext(pdf_path)[0] + "_cropped_images"

    extract_illustrations(pdf_path, output_dir)
