FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app
COPY pyproject.toml README.md ./
COPY src ./src
RUN python -m pip install --upgrade pip && python -m pip install .

RUN useradd --create-home --uid 10001 jabazi && mkdir -p /data && chown jabazi:jabazi /data
USER jabazi

VOLUME ["/data"]
EXPOSE 8000
CMD ["uvicorn", "jabazi.api:app", "--host", "0.0.0.0", "--port", "8000"]
