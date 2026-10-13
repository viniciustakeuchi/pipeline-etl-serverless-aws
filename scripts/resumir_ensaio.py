"""Resume a saída do `docker compose up` em poucas linhas (usado no workflow de ensaio).

python scripts/resumir_ensaio.py ensaio.log
"""

import json
import re
import sys
from pathlib import Path
from typing import Any

PREFIXO = re.compile(r"^pipeline-\d+\s+\| ?")


def documentos(texto: str) -> list[Any]:
    """Todos os JSON impressos pelo pipeline, na ordem (linhas EMF incluídas)."""
    decodificador = json.JSONDecoder()
    achados: list[Any] = []
    posicao = 0
    while (inicio := re.compile(r"^[\[{]", re.M).search(texto, posicao)) is not None:
        try:
            valor, fim = decodificador.raw_decode(texto, inicio.start())
        except json.JSONDecodeError:
            posicao = inicio.end()
            continue
        achados.append(valor)
        posicao = fim
    return achados


def main() -> None:
    linhas = Path(sys.argv[1]).read_text(encoding="utf-8").splitlines()
    texto = "\n".join(PREFIXO.sub("", ln) for ln in linhas if PREFIXO.match(ln))
    for doc in documentos(texto):
        if isinstance(doc, dict) and "fontes" in doc:
            print(f"data_coleta {doc['data_coleta']}")
            for f in doc["fontes"]:
                print(
                    f"  {f['fonte']:<11} {f['status']:<9} {f['duracao_ms']:>6} ms "
                    f"{f['bytes']:>7} bytes  via {f['estrategia']}  tentativas {f['tentativas']}"
                )
            for a in doc["transformacao"]["arquivos"]:
                print(
                    f"  -> {a['destino']}: {a['registros']} registros, {a['rejeitados']} rejeitados"
                )
        elif isinstance(doc, list) and doc and "cdi_anual" in doc[0]:
            print(f"premissas {json.dumps(doc[0], ensure_ascii=False)}")
        elif isinstance(doc, list) and doc and "titulo" in doc[0]:
            print(f"curva_tesouro {len(doc)} títulos, origem {sorted({d['origem'] for d in doc})}")


if __name__ == "__main__":
    main()
