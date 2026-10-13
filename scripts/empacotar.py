"""Gera os dois pacotes que o Terraform publica na AWS.

    build/funcao.zip         código das duas Lambdas (pacote etl/, só biblioteca padrão)
    build/layer-pyarrow.zip  layer com pyarrow para a transformação (Linux arm64)

Os zips são determinísticos (datas e ordem fixas): sem mudança no código, o hash não muda e
o Terraform não republica a Lambda.

    python scripts/empacotar.py [--sem-layer]
"""

import argparse
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
BUILD = RAIZ / "build"
PYARROW = "pyarrow==21.0.0"
# O runtime python3.12 roda no Amazon Linux 2023 (glibc 2.34): aceita wheels manylinux_2_28.
PLATAFORMAS = ("manylinux_2_28_{arq}", "manylinux2014_{arq}")
ARQUITETURAS = {"arm64": "aarch64", "x86_64": "x86_64"}
PYTHON_LAMBDA = "3.12"
DATA_FIXA = (2024, 1, 1, 0, 0, 0)
FORA_DA_FUNCAO = {"local.py"}
FORA_DA_LAYER = ("tests", "include", "__pycache__")


def _zipar(origem: Path, destino: Path, prefixo: str, arquivos: list[Path]) -> None:
    destino.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(destino, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as zip_:
        for arquivo in sorted(arquivos):
            info = zipfile.ZipInfo(f"{prefixo}{arquivo.relative_to(origem).as_posix()}", DATA_FIXA)
            info.external_attr = 0o644 << 16
            info.compress_type = zipfile.ZIP_DEFLATED
            zip_.writestr(info, arquivo.read_bytes())


def empacotar_funcao() -> Path:
    pacote = RAIZ / "etl"
    arquivos = [
        a
        for a in pacote.rglob("*.py")
        if a.name not in FORA_DA_FUNCAO and "__pycache__" not in a.parts
    ]
    destino = BUILD / "funcao.zip"
    _zipar(pacote, destino, "etl/", arquivos)
    return destino


def empacotar_layer(arquitetura: str) -> Path:
    with tempfile.TemporaryDirectory() as pasta:
        alvo = Path(pasta) / "python"
        subprocess.run(  # noqa: S603
            [
                sys.executable,
                "-m",
                "pip",
                "install",
                PYARROW,
                "--target",
                str(alvo),
                *(
                    arg
                    for p in PLATAFORMAS
                    for arg in ("--platform", p.format(arq=ARQUITETURAS[arquitetura]))
                ),
                "--python-version",
                PYTHON_LAMBDA,
                "--implementation",
                "cp",
                "--only-binary=:all:",
                "--no-deps",
                "--quiet",
                "--disable-pip-version-check",
            ],
            check=True,
        )
        # Testes e headers C++ não são usados em produção e pesam ~12 MB.
        for caminho in list(alvo.rglob("*")):
            if caminho.is_dir() and caminho.name in FORA_DA_LAYER and caminho.exists():
                shutil.rmtree(caminho)
        arquivos = [a for a in alvo.rglob("*") if a.is_file()]
        destino = BUILD / "layer-pyarrow.zip"
        _zipar(alvo.parent, destino, "", arquivos)
    return destino


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sem-layer", action="store_true", help="gera só o zip da função")
    parser.add_argument(
        "--arquitetura",
        choices=sorted(ARQUITETURAS),
        default="arm64",
        help="arm64 em produção (Graviton); x86_64 para testar na imagem da Lambda local",
    )
    args = parser.parse_args()
    gerados = [empacotar_funcao()]
    if not args.sem_layer:
        gerados.append(empacotar_layer(args.arquitetura))
    for zip_ in gerados:
        print(f"{zip_.relative_to(RAIZ)}: {zip_.stat().st_size / 1_048_576:.1f} MB")


if __name__ == "__main__":
    main()
