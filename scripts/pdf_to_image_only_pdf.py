from __future__ import annotations

import argparse
from pathlib import Path

import fitz


def _default_output_path(input_path: Path) -> Path:
    return input_path.with_name(f"{input_path.stem}_image_only.pdf")


def _render_page_to_jpeg_bytes(page: fitz.Page, dpi: int, jpeg_quality: int) -> bytes:
    scale = dpi / 72.0
    matrix = fitz.Matrix(scale, scale)
    pix = page.get_pixmap(matrix=matrix, alpha=False)
    return pix.tobytes("jpg", jpg_quality=jpeg_quality)


def convert_pdf_to_image_only_pdf(
    input_path: Path,
    output_path: Path,
    dpi: int,
    jpeg_quality: int,
) -> None:
    """Convert a PDF into a new PDF made only of page images."""
    if not input_path.exists():
        raise FileNotFoundError(f"Input PDF not found: {input_path}")

    if input_path.suffix.lower() != ".pdf":
        raise ValueError(f"Input must be a .pdf file: {input_path}")

    if dpi < 72:
        raise ValueError("DPI must be >= 72.")

    if not 1 <= jpeg_quality <= 100:
        raise ValueError("JPEG quality must be between 1 and 100.")

    source_doc = fitz.open(input_path)
    if source_doc.page_count == 0:
        source_doc.close()
        raise ValueError(f"Input PDF has no pages: {input_path}")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    image_only_doc = fitz.open()

    try:
        for page in source_doc:
            jpg_bytes = _render_page_to_jpeg_bytes(page, dpi=dpi, jpeg_quality=jpeg_quality)
            image_rect = page.rect
            image_page = image_only_doc.new_page(width=image_rect.width, height=image_rect.height)
            image_page.insert_image(image_page.rect, stream=jpg_bytes)

        image_only_doc.save(output_path, deflate=True, garbage=4)
    finally:
        source_doc.close()
        image_only_doc.close()


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Convert a text PDF into an image-only PDF (no embedded selectable text) "
            "for OCR testing."
        )
    )
    parser.add_argument("--input", required=True, help="Path to input PDF.")
    parser.add_argument(
        "--output",
        default=None,
        help="Path to output PDF. Defaults to <input_stem>_image_only.pdf.",
    )
    parser.add_argument(
        "--dpi",
        type=int,
        default=300,
        help="Rasterization DPI for page rendering (default: 300).",
    )
    parser.add_argument(
        "--jpeg-quality",
        type=int,
        default=90,
        help="JPEG quality for rasterized page images, 1-100 (default: 90).",
    )

    args = parser.parse_args()
    input_path = Path(args.input).expanduser().resolve()
    output_path = (
        Path(args.output).expanduser().resolve()
        if args.output is not None
        else _default_output_path(input_path)
    )

    convert_pdf_to_image_only_pdf(
        input_path=input_path,
        output_path=output_path,
        dpi=args.dpi,
        jpeg_quality=args.jpeg_quality,
    )
    print(f"Created image-only PDF: {output_path}")


if __name__ == "__main__":
    main()
