"""Invoca as funções dentro da imagem oficial do runtime da Lambda (com o emulador RIE).

Usado no CI: o zip da função e a layer gerados por scripts/empacotar.py são montados em
/var/task e /opt, exatamente como a Lambda faz. Pega erros que os testes unitários não
pegam: import faltando no zip, layer incompatível com o runtime, handler com nome errado.

    python scripts/testar_runtime_lambda.py --s3 http://localhost:5000 --rie http://localhost:9000
"""

import argparse
import gzip
import json
import urllib.request
from pathlib import Path
from typing import Any

import boto3
import pyarrow as pa
import pyarrow.parquet as pq

RAIZ = Path(__file__).resolve().parent.parent
BUCKET = "pipeline-etl-runtime"
CHAVE_RAW = "raw/fonte=tesouro/data_coleta=2026-10-13/tesouro.json.gz"
CHAVE_PROCESSADA = "processed/tesouro/data_coleta=2026-10-13/tesouro.parquet"


def invocar(rie: str, evento: dict[str, Any]) -> dict[str, Any]:
    pedido = urllib.request.Request(
        f"{rie}/2015-03-31/functions/function/invocations",
        data=json.dumps(evento).encode(),
        method="POST",
    )
    with urllib.request.urlopen(pedido, timeout=60) as resposta:
        resultado: dict[str, Any] = json.loads(resposta.read())
    return resultado


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--s3", required=True)
    parser.add_argument("--rie", required=True, help="RIE com o handler da transformação")
    parser.add_argument("--rie-extracao", help="RIE com o handler da extração (opcional)")
    args = parser.parse_args()

    s3 = boto3.client("s3", endpoint_url=args.s3, region_name="us-east-1")
    s3.create_bucket(Bucket=BUCKET)
    fixture = RAIZ / "tests" / "fixtures" / "tesouro_rentabilidade.json"
    s3.put_object(Bucket=BUCKET, Key=CHAVE_RAW, Body=gzip.compress(fixture.read_bytes()))

    evento = {"Records": [{"s3": {"bucket": {"name": BUCKET}, "object": {"key": CHAVE_RAW}}}]}
    resposta = invocar(args.rie, evento)
    print(json.dumps(resposta, indent=2, ensure_ascii=False))
    assert "errorType" not in resposta, resposta

    corpo = s3.get_object(Bucket=BUCKET, Key=CHAVE_PROCESSADA)["Body"].read()
    tabela = pq.read_table(pa.BufferReader(corpo))
    assert tabela.num_rows == 9, tabela.num_rows
    print(f"OK: {CHAVE_PROCESSADA} com {tabela.num_rows} linhas, gerado dentro do runtime")

    # A extração precisa de internet; aqui basta provar que o handler carrega no runtime.
    if args.rie_extracao:
        resposta = invocar(args.rie_extracao, {"fontes": ["inexistente"]})
        assert resposta.get("errorType") == "ValueError", resposta
        print("OK: handler da extração carregou no runtime e validou o evento")


if __name__ == "__main__":
    main()
