"""PDFs de prueba: portadas con texto digital, escaneos (solo imagen), archivos cifrados y dañados."""

import io

from django.core.files.uploadedfile import SimpleUploadedFile
from PIL import Image, ImageDraw, ImageFont
from pypdf import PdfReader, PdfWriter
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas

from apps.batches.services import batch
from apps.courses.tests.factories import EnrollmentFactory


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


def scan_pdf(*pages):
    """Un PDF que son solo imágenes, como un escaneo: cada argumento es la lista de líneas que se ven en una página."""
    font = ImageFont.load_default(size=34)
    images = []
    for lines in pages:
        image = Image.new('RGB', (1275, 1650), 'white')
        draw = ImageDraw.Draw(image)
        for number, line in enumerate(lines):
            draw.text((100, 120 + number * 70), line, fill='black', font=font)
        images.append(image)
    buffer = io.BytesIO()
    images[0].save(buffer, 'PDF', save_all=True, append_images=images[1:], resolution=150)
    return buffer.getvalue()


def mixed_pdf(cover_lines, *scanned_pages):
    """Una portada con texto digital seguida del trabajo escaneado."""
    writer = PdfWriter()
    writer.append(PdfReader(io.BytesIO(make_pdf(list(cover_lines)))))
    writer.append(PdfReader(io.BytesIO(scan_pdf(*scanned_pages))))
    buffer = io.BytesIO()
    writer.write(buffer)
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


def inscribir(course, numero, nombre='Ana', apellido='Pérez'):
    return EnrollmentFactory(
        course=course, student__user=None, student__first_name=nombre, student__last_name=apellido,
        student__student_number=numero,
    ).student


def subir(tarea, *archivos, cover_pages=1, user=None):
    return batch.upload(tarea, list(archivos), cover_pages=cover_pages, user=user)


def pdf_de(numero, apellido='Pérez', nombre='archivo.pdf'):
    return cover_upload(nombre, f'Nombre: Ana {apellido}', f'Matrícula: {numero}', 'Grupo 3B')
