# Pinned by tag and digest (multi-platform index): a moved tag never changes what is built
FROM python:3.13.18-slim@sha256:e48f59cdba69a3cbd9ed2cf0f348d90d45a8d350d98134cf1070bc106ee9ed90

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 MOONIE_REDIRECT_DB=/data/redirect.db
WORKDIR /app
COPY requirements.txt .
# Every package, transitive ones included, is pinned in requirements.txt
RUN pip install --no-cache-dir --no-deps -r requirements.txt
COPY app.py .
COPY templates templates
COPY static static

# 10001 owns /data, so a new named volume mounted there starts owned by it, and reads the secret files (mode 0400)
RUN useradd --system --uid 10001 --no-create-home --shell /usr/sbin/nologin moonie \
    && install -d -o 10001 -g 10001 -m 0700 /data
USER 10001
EXPOSE 8080
# The same port as the app: MOONIE_HTTP_PORT, 8080 by default
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s \
    CMD ["python", "-c", "import os, urllib.request; urllib.request.urlopen('http://127.0.0.1:%s/health' % os.environ.get('MOONIE_HTTP_PORT', '8080'), timeout=4)"]
CMD ["python", "app.py"]
