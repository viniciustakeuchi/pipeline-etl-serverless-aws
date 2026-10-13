"""Configuração lida de variáveis de ambiente.

As Lambdas recebem esses valores do Terraform. Sem Pydantic de propósito: o pacote da
extração usa só a biblioteca padrão e o boto3 que já vem no runtime da AWS, então o zip
fica com poucos KB e o cold start é curto.
"""

import os
from dataclasses import dataclass, field
from zoneinfo import ZoneInfo

FUSO = ZoneInfo("America/Sao_Paulo")


def _env(nome: str, padrao: str) -> str:
    return os.environ.get(nome) or padrao


@dataclass(frozen=True)
class Config:
    bucket: str = field(default_factory=lambda: _env("BUCKET_DADOS", "pipeline-etl-local"))
    s3_endpoint: str | None = field(default_factory=lambda: os.environ.get("S3_ENDPOINT_URL"))

    timeout_segundos: float = field(default_factory=lambda: float(_env("TIMEOUT_SEGUNDOS", "20")))
    tentativas: int = field(default_factory=lambda: int(_env("TENTATIVAS", "4")))
    backoff_inicial_segundos: float = field(
        default_factory=lambda: float(_env("BACKOFF_INICIAL_SEGUNDOS", "1"))
    )

    sgs_url_base: str = field(
        default_factory=lambda: _env("SGS_URL_BASE", "https://api.bcb.gov.br/dados/serie")
    )
    tesouro_url_api: str = field(
        default_factory=lambda: _env(
            "TESOURO_URL_API", "https://www.tesourodireto.com.br/o/rentabilidade/resgatar"
        )
    )
    tesouro_url_csv: str = field(
        default_factory=lambda: _env(
            "TESOURO_URL_CSV",
            "https://www.tesourotransparente.gov.br/ckan/dataset/"
            "df56aa42-484a-4a59-8184-7676580c81e3/resource/"
            "796d2059-14e9-44e3-80c9-2d9e30b405c1/download/PrecoTaxaTesouroDireto.csv",
        )
    )

    namespace_metricas: str = field(
        default_factory=lambda: _env("NAMESPACE_METRICAS", "PipelineETL")
    )


def carregar() -> Config:
    return Config()
