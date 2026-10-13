"""Teste de fumaça depois do deploy: roda a extração de verdade e consulta o Athena.

    python scripts/verificar_deploy.py --funcao pipeline-etl-extracao \
        --workgroup pipeline-etl --banco pipeline_etl_dados
"""

import argparse
import json
import time
from pathlib import Path
from typing import Any

import boto3

PASTA_SQL = Path(__file__).resolve().parent.parent / "sql"


def esperar_consulta(athena: Any, execucao: str) -> str:
    for _ in range(60):
        estado = athena.get_query_execution(QueryExecutionId=execucao)
        situacao: str = estado["QueryExecution"]["Status"]["State"]
        if situacao in {"SUCCEEDED", "FAILED", "CANCELLED"}:
            if situacao != "SUCCEEDED":
                motivo = estado["QueryExecution"]["Status"].get("StateChangeReason")
                raise SystemExit(f"Consulta {situacao}: {motivo}")
            return situacao
        time.sleep(2)
    raise SystemExit("Consulta não terminou em 2 minutos")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--funcao", required=True)
    parser.add_argument("--workgroup", required=True)
    parser.add_argument("--banco", required=True)
    parser.add_argument("--espera", type=int, default=30, help="segundos para a transformação")
    args = parser.parse_args()

    resposta = boto3.client("lambda").invoke(FunctionName=args.funcao, Payload=b"{}")
    resumo = json.loads(resposta["Payload"].read())
    print(json.dumps(resumo, indent=2, ensure_ascii=False))
    if resposta.get("FunctionError"):
        raise SystemExit("A extração falhou")

    time.sleep(args.espera)  # a transformação roda pelo evento do S3, de forma assíncrona

    athena = boto3.client("athena")
    execucao = athena.start_query_execution(
        QueryString=(PASTA_SQL / "premissas.sql").read_text(),
        QueryExecutionContext={"Database": args.banco},
        WorkGroup=args.workgroup,
    )["QueryExecutionId"]
    esperar_consulta(athena, execucao)
    linhas = athena.get_query_results(QueryExecutionId=execucao)["ResultSet"]["Rows"]
    cabecalho = [c.get("VarCharValue") for c in linhas[0]["Data"]]
    for linha in linhas[1:]:
        print(dict(zip(cabecalho, (c.get("VarCharValue") for c in linha["Data"]), strict=True)))


if __name__ == "__main__":
    main()
