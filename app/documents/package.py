"""Fresh PDF package construction for allowlisted application documents."""

from __future__ import annotations

import io

from pypdf import PdfReader, PdfWriter


class PdfPackageError(RuntimeError):
    """The selected document set cannot form a safe package."""


def build_pdf_package(sources: tuple[bytes, ...]) -> bytes:
    if not sources:
        raise PdfPackageError("The application document package is unavailable.")
    writer = PdfWriter()
    try:
        for source in sources:
            reader = PdfReader(io.BytesIO(source), strict=True)
            if reader.is_encrypted or not reader.pages:
                raise PdfPackageError("The application document package is unavailable.")
            for page in reader.pages:
                rebuilt = writer.add_page(page)
                for key in ("/A", "/AA", "/Annots", "/Metadata"):
                    rebuilt.pop(key, None)
        writer.add_metadata(
            {
                "/Title": "EHF application document package",
                "/Author": "Ernst Hadorn Foundation",
                "/Subject": "Approved applicant-visible submitted documents",
                "/Creator": "EHF Fellowships",
            }
        )
        output = io.BytesIO()
        writer.write(output)
        return output.getvalue()
    except PdfPackageError:
        raise
    except Exception:
        raise PdfPackageError("The application document package is unavailable.") from None
