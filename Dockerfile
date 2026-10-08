FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# Las dependencias se copian aparte para aprovechar la caché de capas:
# solo se reinstalan cuando cambian los requirements.
COPY requirements/ requirements/
RUN pip install --upgrade pip && pip install -r requirements/local.txt

COPY . .

EXPOSE 8000

CMD ["python", "manage.py", "runserver", "0.0.0.0:8000"]
