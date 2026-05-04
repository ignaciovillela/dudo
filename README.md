# Dudo

Juego de dados multijugador en tiempo real, jugable desde el navegador. Basado en el clásico juego de los cachos (Dudo).

## Stack

- **Backend:** FastAPI + WebSockets
- **Frontend:** HTML/CSS/JS estático servido por FastAPI

## Instalación

```bash
pip install -r requirements.txt
```

## Ejecución

```bash
uvicorn main:app --reload
```

Luego abre `http://localhost:8000` en el navegador.

## Cómo jugar

Cada jugador se une a una sala compartida. El objetivo es ser el último con dados. Las reglas completas están en [REGLAS.md](REGLAS.md).

Acciones disponibles por turno: **Apostar**, **Pasar**, **Dudar** o **Calzar**.

## Generar OG cover PNG

El archivo `static/og-cover.png` se puede regenerar desde `static/og-cover.svg` con `@resvg/resvg-js`.

```bash
npm install
npm run og:cover
```

