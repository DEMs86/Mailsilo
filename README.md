Модификация в части работы с PST файлами:
    - восстановление структуру файлов PST и работы с цитатами в HTML
Адаптация русского языка

## Запуск в Docker (сборка из этого репозитория)

Образ собирается из `Dockerfile` в корне репозитория и запускается через
`docker-compose.yaml`:

```bash
docker compose up -d --build      # пересобрать образ и поднять контейнеры
docker compose logs -f mailsilo   # смотреть логи приложения
```

Сервис `mailsilo` в compose собирается из локального `Dockerfile`
(`build:` + `image: mailsilo:local`), поэтому код в контейнере — это код из
этого репозитория, а не образ с Docker Hub.

Важно: флаг `--build` нужен каждый раз после правок в коде. Без него
`docker compose up -d` переиспользует уже собранный образ, и изменения в
контейнер не попадут.

Проверка, что внутри контейнера свежий код:

```bash
docker exec mailsilo grep -c formatDateTime /app/app/static/js/inbox.js
```

Если нужен готовый образ с Docker Hub, замените в `docker-compose.yaml`
блоки `build:`/`image: mailsilo:local` на `image: cesarf26/mailsilo:latest`.
