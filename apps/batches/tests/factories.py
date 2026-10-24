"""PDFs de prueba: portadas con texto digital, escaneos sin texto, archivos cifrados y dañados."""

import io

from django.core.files.uploadedfile import SimpleUploadedFile
from pypdf import PdfWriter
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas


def make_pdf(cover_lines=(), pages=1, *, body='Desarrollo del trabajo.'):
    """Bytes de un PDF: la primera página trae ``cover_lines`` (la portada) y las demás un texto cualquiera."""
    buffer = io.BytesIO()
    pdf = canvas.Canvas(buffer, pagesize=letter)
    for number in range(pages):
        y = 740
        for line in (cover_lines if number == 0 else [body]):
            pdf.drawString(72, y, line)
            y -= 18
        pdf.showPage()
    pdf.save()
    return buffer.getvalue()


def blank_pdf(pages=1):
    """Un PDF sin texto, como un escaneo (la portada es una imagen)."""
    writer = PdfWriter()
    for _ in range(pages):
        writer.add_blank_page(width=612, height=792)
    buffer = io.BytesIO()
    writer.write(buffer)
    return buffer.getvalue()


def encrypted_pdf(password='secreto'):
    writer = PdfWriter(clone_from=io.BytesIO(make_pdf(['Matrícula: 20240001'])))
    writer.encrypt(user_password=password, owner_password=password)
    buffer = io.BytesIO()
    writer.write(buffer)
    return buffer.getvalue()


def upload(name, content, content_type='application/pdf'):
    return SimpleUploadedFile(name, content, content_type=content_type)


def cover_upload(name, *lines, pages=1):
    """Un PDF subido cuya portada trae ``lines``."""
    return upload(name, make_pdf(list(lines), pages=pages))
