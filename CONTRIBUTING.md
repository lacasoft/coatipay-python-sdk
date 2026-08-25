# Contribuir

Gracias por querer aportar. Escribe en **español o inglés**, lo que te resulte
natural — ambos idiomas son bienvenidos en issues y pull requests.

## Poner en marcha

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
pytest -q
```

Requiere Python **3.11 o superior**.

El paquete se publica como `coatipay-sdk`, pero el módulo importable es
`coatipay`:

```python
from coatipay import CoatiPay
```

Esa diferencia está declarada de forma explícita en `pyproject.toml`
(`[tool.hatch.build.targets.wheel]`); si renombras algo, actualízala o el
paquete dejará de construirse.

## Antes de abrir el PR

```bash
pytest -q
```

Si arreglas un fallo, añade el test que lo reproduce. Si cambias la API pública,
dilo en la descripción del PR: hay integraciones en producción que dependen de
ella.

## Seguridad

¿Encontraste una vulnerabilidad? **No abras un issue.** Escribe a
**security@coatipay.com** — ver [SECURITY.md](SECURITY.md).
