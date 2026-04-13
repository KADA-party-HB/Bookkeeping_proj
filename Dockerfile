FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential libpq-dev \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt ./
RUN pip install --upgrade pip \
    && pip install -r requirements.txt \
    && pip install gunicorn

COPY . .

RUN chmod +x docker/entrypoint.sh

EXPOSE 9342

ENTRYPOINT ["./docker/entrypoint.sh"]
CMD ["gunicorn", "--bind", "0.0.0.0:9342", "--workers", "2", "--threads", "4", "--timeout", "120", "wsgi:app"]
