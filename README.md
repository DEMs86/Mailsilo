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

## Импорт выгрузки Yandex Mail (`yandex-mail-export`)

Дамп из [leksuss/yandex-mail-export](https://github.com/leksuss/yandex-mail-export)
(`manifest.jsonl` + `<Папка>/<mid>.eml`) импортируется отдельным режимом,
который, в отличие от обычного импорта EML, сохраняет **папки, флаги
прочитанности и даты** и складывает всё в **один** аккаунт-архив, а не в
папку `Imported` и не в аккаунт на каждого отправителя.

Через HTTP (файл `.zip` с дампом, обрабатывается в фоне):

```bash
curl -X POST http://localhost:8765/api/import/yandex-dump \
  -H "Authorization: Bearer $TOKEN" \
  -F "file=@yandex-dump.zip" \
  -F "account_email=AkulovDmE@yandex.ru"
# -> {"task_id": "..."}
curl -H "Authorization: Bearer $TOKEN" http://localhost:8765/api/import/status/<task_id>
```

Внутри контейнера, если дамп уже лежит на сервере:

```bash
docker exec -it mailsilo python scripts/import_yandex_dump.py \
    /app/data/yandex-dump --email AkulovDmE@yandex.ru
```

Поведение:

- `--email` / `account_email` — аккаунт с таким адресом находится или
  создаётся с `is_imported=true` и `enabled=false` (фоновый IMAP-фетчер его
  не трогает). Явный `account_id` имеет приоритет.
- Папка берётся из `manifest.jsonl` (имя как в Яндексе, например
  `Отправленные`), `unread=true` превращается в `is_read=false`.
- Если в письме нет заголовка `Date`, дата берётся из `manifest.timestamp`
  (поддерживаются секунды и миллисекунды).
- Повторный запуск безопасен: дубликаты определяются по
  `message_id + account_id + folder`.
- ZIP распаковывается во временный каталог; поддерживается архив как с
  `manifest.jsonl` в корне, так и с дампом внутри одной вложенной папки.

Обычный `POST /api/import/eml` тоже принимает необязательные поля `folder`,
`is_read` и `account_email` — по умолчанию поведение прежнее (`Imported`,
непрочитанное), поэтому веб-интерфейс не меняется.

Тесты импортёра (SQLite, без Postgres и без сервера):

```bash
python scripts/test_yandex_import.py
python scripts/test_import_endpoint.py
```

