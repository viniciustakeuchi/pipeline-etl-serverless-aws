"""Roda o pipeline fora da AWS, contra um S3 local (moto server) ou qualquer S3 compatível.

    python -m etl.local executar [--data 2026-10-13] [--fontes cdi,ipca]
    python -m etl.local consultar [premissas|ultimos_indicadores|curva_tesouro]

`executar` chama os mesmos handlers das Lambdas, simulando a notificação do S3 que liga a
extração à transformação. `consultar` roda no DuckDB os mesmos arquivos SQL que o
Terraform publica como consultas salvas no Athena.
"""

import argparse
import json
import sys
import tempfile
from pathlib import Path
from typing import Any

from etl import extracao, transformacao
from etl.camadas import PREFIXO_PROCESSADO
from etl.config import Config, carregar
from etl.observabilidade import configurar_logs
from etl.s3 import S3Client, cliente

PASTA_SQL = Path(__file__).resolve().parent.parent / "sql"
CONSULTAS = sorted(p.stem for p in PASTA_SQL.glob("*.sql"))


def garantir_bucket(s3: S3Client, bucket: str) -> None:
    if bucket not in {b["Name"] for b in s3.list_buckets().get("Buckets", [])}:
        regiao = s3.meta.region_name
        if regiao == "us-east-1":
            s3.create_bucket(Bucket=bucket)
        else:
            s3.create_bucket(
                Bucket=bucket,
                CreateBucketConfiguration={"LocationConstraint": regiao},  # type: ignore[typeddict-item]
            )


def evento_s3(bucket: str, chaves: list[str]) -> dict[str, Any]:
    """O formato que o S3 entrega à Lambda (só os campos que o handler lê)."""
    return {
        "Records": [
            {"eventSource": "aws:s3", "s3": {"bucket": {"name": bucket}, "object": {"key": c}}}
            for c in chaves
        ]
    }


def executar(
    cfg: Config, s3: S3Client, data: str | None, fontes: list[str] | None
) -> dict[str, Any]:
    garantir_bucket(s3, cfg.bucket)
    evento: dict[str, Any] = {}
    if data:
        evento["data_coleta"] = data
    if fontes:
        evento["fontes"] = fontes
    resumo = extracao.executar(evento, cfg, s3, execucao="local")
    chaves = [f["chave"] for f in resumo["fontes"] if f["chave"]]
    resumo["transformacao"] = transformacao.executar(evento_s3(cfg.bucket, chaves), cfg, s3)
    return resumo


def baixar_processados(s3: S3Client, bucket: str, destino: Path) -> int:
    paginas = s3.get_paginator("list_objects_v2").paginate(
        Bucket=bucket, Prefix=f"{PREFIXO_PROCESSADO}/"
    )
    total = 0
    for pagina in paginas:
        for objeto in pagina.get("Contents", []):
            arquivo = destino / objeto["Key"]
            arquivo.parent.mkdir(parents=True, exist_ok=True)
            s3.download_file(bucket, objeto["Key"], str(arquivo))
            total += 1
    return total


def consultar(cfg: Config, s3: S3Client, consulta: str) -> list[dict[str, Any]]:
    import duckdb

    with tempfile.TemporaryDirectory() as pasta:
        raiz = Path(pasta)
        baixar_processados(s3, cfg.bucket, raiz)
        conexao = duckdb.connect()
        for tabela in ("indicadores", "tesouro"):
            arquivos = sorted((raiz / PREFIXO_PROCESSADO / tabela).rglob("*.parquet"))
            if arquivos:
                lista = ", ".join(f"'{a}'" for a in arquivos)
                conexao.execute(
                    f"CREATE VIEW {tabela} AS SELECT * FROM "
                    f"read_parquet([{lista}], hive_partitioning = true)"
                )
        cursor = conexao.execute((PASTA_SQL / f"{consulta}.sql").read_text())
        colunas = [c[0] for c in cursor.description]
        return [dict(zip(colunas, linha, strict=True)) for linha in cursor.fetchall()]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m etl.local", description=__doc__)
    comandos = parser.add_subparsers(dest="comando", required=True)
    p_exec = comandos.add_parser("executar", help="extrai e transforma, como as Lambdas")
    p_exec.add_argument("--data", help="data da coleta (AAAA-MM-DD); padrão: hoje")
    p_exec.add_argument("--fontes", help="lista separada por vírgula; padrão: todas")
    p_cons = comandos.add_parser("consultar", help="roda uma consulta SQL no DuckDB")
    p_cons.add_argument("consulta", nargs="?", default="premissas", choices=CONSULTAS)
    args = parser.parse_args(argv)

    configurar_logs("WARNING")
    cfg = carregar()
    s3 = cliente(cfg)
    if args.comando == "executar":
        fontes = args.fontes.split(",") if args.fontes else None
        saida: Any = executar(cfg, s3, args.data, fontes)
    else:
        saida = consultar(cfg, s3, args.consulta)
    print(json.dumps(saida, indent=2, ensure_ascii=False, default=str))
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
