FROM python:3.12-slim
RUN apt-get update && apt-get install -y --no-install-recommends \
      tesseract-ocr tesseract-ocr-eng tesseract-ocr-hin tesseract-ocr-kan \
      fonts-noto-core libgl1 libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /repo/backend
COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY backend/ /repo/backend/
COPY data/ /repo/data/
COPY prompts/ /repo/prompts/
COPY ml/ /repo/ml/
ENV PYTHONUNBUFFERED=1 NYAYA_KANNADA_FONT=/usr/share/fonts/truetype/noto/NotoSansKannada-Regular.ttf
EXPOSE 8000
CMD ["sh", "-c", "alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port 8000"]
