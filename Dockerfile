# Imagem para rodar o pipeline fora da AWS (docker compose up, contra um S3 local).
# Na AWS o código roda como zip nas Lambdas; esta imagem usa o mesmo pacote etl/.
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

RUN useradd --create-home --uid 1000 pipeline
WORKDIR /app

COPY pyproject.toml ./
COPY etl ./etl
COPY sql ./sql
RUN pip install ".[local]"

USER pipeline
ENTRYPOINT ["python", "-m", "etl.local"]
CMD ["--help"]
