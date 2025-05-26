import fitz  # PyMuPDF
import os
import sys

def extract_images(pdf_path, output_dir):
    os.makedirs(output_dir, exist_ok=True)
    doc = fitz.open(pdf_path)
    image_count = 0

    for page_number in range(len(doc)):
        page = doc[page_number]
        image_list = page.get_images(full=True)
        
        for img_index, img in enumerate(image_list):
            xref = img[0]
            base_image = doc.extract_image(xref)
            image_bytes = base_image["image"]
            image_ext = base_image["ext"]
            image_filename = f"page{page_number+1}_img{img_index+1}.{image_ext}"
            output_path = os.path.join(output_dir, image_filename)
            
            with open(output_path, "wb") as f:
                f.write(image_bytes)
            image_count += 1
            print(f"Saved: {output_path}")

    print(f"✅ Done. Extracted {image_count} images to: {output_dir}")

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python extract_images_from_pdf.py <input.pdf> [output_dir]")
        sys.exit(1)

    pdf_path = sys.argv[1]
    output_dir = sys.argv[2] if len(sys.argv) > 2 else os.path.splitext(pdf_path)[0] + "_images"

    extract_images(pdf_path, output_dir)
