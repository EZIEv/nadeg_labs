# syntax=docker/dockerfile:1
FROM python:3.14-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

COPY requirements.runtime.lock ./
RUN python -m pip install --no-cache-dir -r requirements.runtime.lock \
    && python -m pip check \
    && groupadd --gid 10001 nadeg \
    && useradd --uid 10001 --gid nadeg --no-create-home --shell /usr/sbin/nologin nadeg

COPY --chown=10001:10001 nadeg ./nadeg

USER 10001:10001
EXPOSE 8000

HEALTHCHECK --interval=20s --timeout=5s --start-period=15s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=3).read()"]

CMD ["python", "-m", "uvicorn", "nadeg.main:app", "--host", "0.0.0.0", "--port", "8000", "--no-proxy-headers"]
