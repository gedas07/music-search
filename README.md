# music-search — versión propia de gedas07

Bot de Telegram para buscar música, descargar canciones y álbumes e importar playlists.

> **Nota:** fork/copia independiente de `javikobcn/music-search`. Esta versión se construye
> y publica **con tu propia imagen de Docker** (`ghcr.io/gedas07/music-search`),
> de modo que el código que ejecutas es exactamente el que hay en este repositorio.

## Arranque rápido

```bash
cp .env.example .env    # rellena tus credenciales
docker compose up -d --build   # construye TU imagen localmente y arranca
```

Una vez que la acción de GitHub publique tu imagen, puedes arrancar solo con
`docker compose up -d` (se descargará `ghcr.io/gedas07/music-search:latest`).

## Servicios

- `music-search` — API FastAPI que habla con tu instancia de `slskd` (puerto host 8086).
- `telegram-bot` — bot de Telegram que consume la API interna.

## Configuración

Rellena `.env` siguiendo `.env.example`:

- `SLSKD_URL`, `SLSKD_USERNAME`, `SLSKD_PASSWORD` — tu instancia de slskd
- `TELEGRAM_BOT_TOKEN`, `TELEGRAM_ALLOWED_USER_ID` — bot de Telegram
- `SLSKD_WEBHOOK_TOKEN` — token del webhook
- `YOUTUBE_API_KEY` — para importar playlists de YouTube
- `TZ` — zona horaria

Ajusta los volúmenes de `docker-compose.yml` (`/PATH/TO/...`) a tus rutas reales.

## Guía de uso

[Chuleta del bot de Telegram](https://gedas07.github.io/music-search/)

## Tests

```bash
python -m unittest discover -s tests -v
```
