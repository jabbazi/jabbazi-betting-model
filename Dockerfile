FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app
COPY pyproject.toml README.md ./
COPY src ./src
COPY tools ./tools
RUN python -m pip install --upgrade pip && python -m pip install '.[discord]'

RUN useradd --create-home --uid 10001 jabazi && mkdir -p /data && chown jabazi:jabazi /data
USER jabazi

VOLUME ["/data"]
EXPOSE 8000
CMD ["python", "-m", "jabazi.runtime", "api"]
