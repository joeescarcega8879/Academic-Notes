"""Foto de perfil: se valida de verdad como imagen y se guarda siempre como un JPEG cuadrado y ligero.

Lo que sube el usuario nunca se guarda tal cual: se reconstruye la imagen píxel por píxel. Así se
descartan metadatos (ubicación GPS del teléfono), contenido incrustado y formatos raros, y la foto
pesa unos 30–60 KB en vez de varios megas.
"""

from io import BytesIO

from django.core.exceptions import ValidationError
from django.core.files.base import ContentFile
from PIL import Image, ImageOps, UnidentifiedImageError

MAX_AVATAR_BYTES = 5 * 1024 * 1024
MAX_AVATAR_PIXELS = 25_000_000  # una foto de 5000 × 5000; más allá es un archivo hecho para agotar la memoria
AVATAR_SIDE = 512
ALLOWED_FORMATS = ('JPEG', 'PNG', 'WEBP')


def process_avatar(upload):
    """Devuelve la foto lista para guardar (``ContentFile`` JPEG de 512 px como máximo) o lanza ``ValidationError``."""
    if upload.size > MAX_AVATAR_BYTES:
        raise ValidationError('La foto pesa más de 5 MB.', code='size')
    try:
        image = Image.open(upload)
        if image.format not in ALLOWED_FORMATS:
            raise ValidationError('Sube una foto en formato JPG, PNG o WebP.', code='format')
        if image.width * image.height > MAX_AVATAR_PIXELS:
            raise ValidationError('La foto es demasiado grande: reduce su tamaño y vuelve a intentarlo.', code='pixels')
        image = ImageOps.exif_transpose(image)  # respeta la orientación con que se tomó (celulares)
        image.load()
    except ValidationError:
        raise
    except (UnidentifiedImageError, Image.DecompressionBombError, OSError, ValueError, SyntaxError):
        raise ValidationError('No se pudo leer la imagen. Prueba con otra foto en JPG, PNG o WebP.', code='invalid') from None

    if image.mode in ('RGBA', 'LA', 'P'):
        image = image.convert('RGBA')
        fondo = Image.new('RGB', image.size, (255, 255, 255))  # el JPEG no tiene transparencia
        fondo.paste(image, mask=image.getchannel('A'))
        image = fondo
    else:
        image = image.convert('RGB')

    # Recorte cuadrado desde el centro; solo se reduce, nunca se amplía.
    lado = min(image.size)
    izquierda, arriba = (image.width - lado) // 2, (image.height - lado) // 2
    image = image.crop((izquierda, arriba, izquierda + lado, arriba + lado))
    if lado > AVATAR_SIDE:
        image = image.resize((AVATAR_SIDE, AVATAR_SIDE), Image.Resampling.LANCZOS)

    salida = BytesIO()
    image.save(salida, format='JPEG', quality=88, optimize=True)
    return ContentFile(salida.getvalue(), name='avatar.jpg')
