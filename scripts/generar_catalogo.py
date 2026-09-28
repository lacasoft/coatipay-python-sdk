"""
Genera `coatipay/_catalogo.py`: la categoría de cada código de error de la API,
a partir de los vectores compartidos (`tests/vectors/errores.json`), que el CI
compara con los de la última versión publicada de @lacasoft/coatipay-protocol.

No se edita a mano: los tests de vectores fallan si un código del catálogo no
está aquí, o si su clase no es la que dicen los vectores.

Uso: python scripts/generar_catalogo.py
"""
from __future__ import annotations

import json
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
ORIGEN = RAIZ / "tests" / "vectors" / "errores.json"
DESTINO = RAIZ / "coatipay" / "_catalogo.py"


def main() -> None:
    codigos = json.loads(ORIGEN.read_text(encoding="utf-8"))["codigos"]
    lineas = [
        '"""',
        "Categoría de cada código de error de la API de CoatiPay.",
        "",
        "GENERADO por scripts/generar_catalogo.py desde los vectores compartidos",
        "(tests/vectors/errores.json). No editar a mano.",
        '"""',
        "",
        "CATEGORIAS: dict[str, str] = {",
    ]
    for codigo in sorted(codigos):
        lineas.append(f'    "{codigo}": "{codigos[codigo]["category"]}",')
    lineas.append("}")
    DESTINO.write_text("\n".join(lineas) + "\n", encoding="utf-8")
    print(f"✓ {DESTINO.relative_to(RAIZ)}: {len(codigos)} códigos")


if __name__ == "__main__":
    main()
