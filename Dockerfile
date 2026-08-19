FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_ROOT_USER_ACTION=ignore

WORKDIR /app
RUN apt-get update \
    && DEBIAN_FRONTEND=noninteractive apt-get install --yes --no-install-recommends git \
    && rm -rf /var/lib/apt/lists/*
COPY pyproject.toml README.md MANIFEST.in LICENSE /app/
COPY src /app/src
RUN pip install --no-cache-dir .

RUN useradd --create-home --uid 10001 codeintel \
    && mkdir -p /state \
    && chown codeintel:codeintel /state
USER codeintel

EXPOSE 8765
ENTRYPOINT ["anaxigraph"]
CMD ["serve", "--host", "0.0.0.0", "--port", "8765"]
