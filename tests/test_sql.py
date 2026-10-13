"""As consultas rodam no DuckDB nos testes e no Athena (Trino) em produção.

O DuckDB já é exercitado em test_local.py. Aqui conferimos que o mesmo texto também é SQL
válido no dialeto do Athena e que só lê as tabelas que o Terraform cria.
"""

from pathlib import Path

import pytest
import sqlglot
from sqlglot import exp

PASTA_SQL = Path(__file__).resolve().parent.parent / "sql"
TABELAS_DO_GLUE = {"indicadores", "tesouro"}
CONSULTAS = sorted(PASTA_SQL.glob("*.sql"))


def test_existem_consultas() -> None:
    assert {c.stem for c in CONSULTAS} == {"curva_tesouro", "premissas", "ultimos_indicadores"}


@pytest.mark.parametrize("arquivo", CONSULTAS, ids=lambda c: c.stem)
def test_consulta_e_valida_no_dialeto_do_athena(arquivo: Path) -> None:
    arvore = sqlglot.parse_one(arquivo.read_text(), read="trino")
    ctes = {cte.alias for cte in arvore.find_all(exp.CTE)}
    tabelas = {t.name for t in arvore.find_all(exp.Table)} - ctes
    assert tabelas <= TABELAS_DO_GLUE
