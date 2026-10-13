"""Logs em JSON e métricas no CloudWatch via Embedded Metric Format (EMF).

Com EMF a métrica vai dentro de uma linha de log e o CloudWatch a extrai sozinho: não há
chamada a `PutMetricData`, nem permissão extra no IAM, nem latência na Lambda.
"""

import json
import logging
import sys
import time
from typing import Any

_CAMPOS_PADRAO = set(vars(logging.makeLogRecord({})))


class FormatoJSON(logging.Formatter):
    def format(self, registro: logging.LogRecord) -> str:
        dados: dict[str, Any] = {
            "nivel": registro.levelname,
            "evento": registro.getMessage(),
            "logger": registro.name,
        }
        dados.update({k: v for k, v in vars(registro).items() if k not in _CAMPOS_PADRAO})
        if registro.exc_info:
            dados["excecao"] = self.formatException(registro.exc_info)
        return json.dumps(dados, ensure_ascii=False, default=str)


def configurar_logs(nivel: str = "INFO") -> None:
    """Na Lambda o logger raiz já tem um handler; trocamos só o formato."""
    raiz = logging.getLogger()
    if not raiz.handlers:
        raiz.addHandler(logging.StreamHandler(sys.stdout))
    for handler in raiz.handlers:
        handler.setFormatter(FormatoJSON())
    raiz.setLevel(nivel)


def emitir_metricas(
    namespace: str,
    dimensoes: dict[str, str],
    metricas: dict[str, tuple[float, str]],
    saida: Any = None,
) -> dict[str, Any]:
    """Escreve uma linha EMF. `metricas` é {nome: (valor, unidade)}."""
    documento: dict[str, Any] = {
        "_aws": {
            "Timestamp": int(time.time() * 1000),
            "CloudWatchMetrics": [
                {
                    "Namespace": namespace,
                    "Dimensions": [list(dimensoes)],
                    "Metrics": [{"Name": n, "Unit": u} for n, (_, u) in metricas.items()],
                }
            ],
        },
        **dimensoes,
        **{n: v for n, (v, _) in metricas.items()},
    }
    print(json.dumps(documento), file=saida or sys.stdout, flush=True)
    return documento
