"""Onde cada arquivo mora no S3.

    raw/fonte=cdi/data_coleta=2026-10-13/cdi.json.gz
    processed/indicadores/serie=cdi/data_coleta=2026-10-13/cdi.parquet
    processed/tesouro/data_coleta=2026-10-13/tesouro.parquet

As chaves são determinísticas (uma por fonte e dia): rodar de novo no mesmo dia sobrescreve
o arquivo em vez de duplicar linhas. O versionamento do bucket guarda as versões anteriores
do bruto, então nada se perde.
"""

import re
from dataclasses import dataclass
from datetime import date
from typing import Literal

PREFIXO_RAW = "raw"
PREFIXO_PROCESSADO = "processed"

Formato = Literal["json", "csv"]

_RAW = re.compile(
    rf"^{PREFIXO_RAW}/fonte=(?P<fonte>[a-z_]+)/data_coleta=(?P<data>\d{{4}}-\d{{2}}-\d{{2}})/"
    r"(?P=fonte)\.(?P<formato>json|csv)\.gz$"
)


class ChaveInvalida(ValueError):
    pass


@dataclass(frozen=True)
class ChaveRaw:
    fonte: str
    data_coleta: date
    formato: Formato

    @property
    def chave(self) -> str:
        return (
            f"{PREFIXO_RAW}/fonte={self.fonte}/data_coleta={self.data_coleta.isoformat()}/"
            f"{self.fonte}.{self.formato}.gz"
        )

    @classmethod
    def de_texto(cls, chave: str) -> "ChaveRaw":
        encontrada = _RAW.match(chave)
        if not encontrada:
            raise ChaveInvalida(f"Chave fora do padrão da camada raw: {chave}")
        formato: Formato = "json" if encontrada["formato"] == "json" else "csv"
        return cls(encontrada["fonte"], date.fromisoformat(encontrada["data"]), formato)


def chave_processada(tabela: str, fonte: str, data_coleta: date) -> str:
    dia = data_coleta.isoformat()
    if tabela == "indicadores":
        return f"{PREFIXO_PROCESSADO}/indicadores/serie={fonte}/data_coleta={dia}/{fonte}.parquet"
    if tabela == "tesouro":
        return f"{PREFIXO_PROCESSADO}/tesouro/data_coleta={dia}/{fonte}.parquet"
    raise ValueError(f"Tabela desconhecida: {tabela}")
