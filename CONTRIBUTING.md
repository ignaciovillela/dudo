# Contribuir a Dudo

¡Gracias por el interés! Cualquier ayuda es bienvenida: reglas, bots, traducciones, accesibilidad, bugs.

## Cómo empezar

```bash
docker compose up --build        # app + Postgres en http://localhost:8000
# o, sin Docker:
pip install -r requirements.txt -r requirements-dev.txt
python -m pytest
```

## Flujo

1. Haz un fork y crea una rama (`fix/...` o `feat/...`).
2. Si cambias reglas o lógica, añade o ajusta tests en `tests/` y mantén [REGLAS.md](REGLAS.md) al día.
3. Si cambias el contenido de las guías, edita los fragmentos de `scripts/seo_pages/` y ejecuta
   `python scripts/seo_pages/build.py` (regenera `static/pages/` y el sitemap).
4. Registra los cambios importantes en [CHANGELOG.md](CHANGELOG.md).
5. Abre un Pull Request describiendo qué cambia y por qué.

Ideas pendientes en [BACKLOG.md](BACKLOG.md).
