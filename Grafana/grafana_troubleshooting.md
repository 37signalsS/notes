# Диагностика и устранение неполадок Grafana

Практическое руководство по диагностике self-hosted Grafana. Версии: 13.x актуальная, 12.x LTS, 11.x — EOL (июнь 2026). Облачные и ИИ-функции не рассматриваются.

## Определения

- **Grafana server** — процесс Grafana (подкоманда `grafana server`); в systemd служба называется `grafana-server`.
- **`GET /api/health`** — эндпоинт живости без аутентификации; возвращает версию, коммит и состояние БД.
- **`GET /metrics`** — метрики в формате Prometheus (процесс, Go-рантайм, HTTP-запросы Grafana).
- **`/debug/pprof`** — профилировщик Go (CPU/heap/goroutine/block/mutex); по умолчанию слушает **отдельный порт** `6060`, а не порт Grafana.
- **Миграция схемы** — изменение структуры таблиц БД при старте новой версии; выполняется один раз и необратима вперёд.
- **`GF_*` (переменные окружения)** — способ переопределить любой ключ `grafana.ini` как `GF_<SECTION>_<KEY>` (точки и дефисы заменяются на `_`).
- **SNE (Single Node Evaluation)** — механизм единичного вычисления алертов в HA, чтобы правило не срабатывало на каждом узле.

## Базовые концепции

Диагностика идёт от внешнего к внутреннему:

1. **Живость** — `GET /api/health`. Если эндпоинт не отвечает, процесс не запущен или не слушает порт; если отвечает `"database":"failed"` — проблема с БД.
2. **Логи** — первичный источник правды. Смотрим `level=error`/`level=warn`, а также логгеры `migrator`, `sqlstore`, `plugin`, `tsdb`, `dataproxy`, `rendering`.
3. **БД и миграции** — большинство «не стартует» связано с доступом к БД или незавершённой/заблокированной миграцией.
4. **Прокси и сеть** — 502, вечные редиректы и «не ставится cookie» обычно следствие неверного `root_url` или отсутствующего `X-Forwarded-Proto`.
5. **Метрики и профиль** — для регрессий производительности, утечек памяти и зависаний.

### Подсистема логирования

Логи настраиваются секцией `[log]`:

- `mode` — `console`, `file`, `syslog`; можно комбинировать через пробел. По умолчанию `console file`. В systemd вывод `console` попадает в журнал (`journalctl -u grafana-server`).
- `level` — `debug`, `info`, `warn`, `error` (`critical` — алиас `error`). По умолчанию `info`.
- `filters` — уровень для отдельных логгеров, например `filters = sqlstore:debug,plugins:info`.

Печать в файл регулируется в `[log.file]`: ротация включена (`log_rotate = true`), `max_days = 7` (хранить дней), `max_size_shift = 28` (≈256 МБ на файл), `daily_rotate = true`. Путь задаётся в `[paths] logs` (по умолчанию `/var/log/grafana`).

## Практические сценарии

### Предварительные требования

- Доступ к хосту/контейнеру Grafana и к БД.
- Права чтения логов (`journalctl`, файл `grafana.log` или `docker compose logs`).
- Для глубокой диагностики — возможность временно поднять уровень логов и включить профилировщик.
- Утилита `jq` для разбора JSON-ответов API (в примерах ниже).

### Сценарий 1. Проверка живости и версии

```bash
curl -s http://localhost:3000/api/health | jq
# → {"commit":"...","database":"ok","version":"13.2.3"}

# Версия сервера и CLI
grafana server -v
grafana cli --version
```

Поля ответа: `database` = `ok` или `failed`, `version`, `commit`. Отдельного поля `status` в ответе нет — признак исправности это HTTP 200 и `"database":"ok"`. Если соединение отклонено — процесс не слушает порт (`http_addr`/`http_port`); если `database":"failed"` — см. Сценарий 3.

### Сценарий 2. Чтение логов и повышение уровня

```bash
# systemd
journalctl -u grafana-server -n 100 --no-pager

# Docker
docker compose logs grafana --tail 100

# Временно включить debug только для нужных логгеров
GF_LOG_LEVEL=debug GF_LOG_FILTERS=sqlstore:debug grafana server
```

Повышайте уровень точечно (`filters`), а не глобально: полный `debug` на нагруженном инстансе даёт большой объём и шум. Ищите в логах `level=error`, `migrat`, `failed to connect`, `plugin`, `context deadline exceeded`.

### Сценарий 3. Диагностика БД и миграций

```bash
# Проверить доступ к БД напрямую (параметры из [database])
mysql -u grafana -p -h 127.0.0.1 -e "SHOW DATABASES;"    # MySQL
pg_isready -h 127.0.0.1 -U grafana                        # PostgreSQL

# Ход миграции в логах
journalctl -u grafana-server --no-pager | grep -i "migrat"
# → "migrations completed" — ок; "failed to migrate" / зависание — проблема
```

Ключевые настройки `[database]`: `migration_locking` (блокировка БД на время миграции, по умолчанию `true`) и `locking_attempt_timeout_sec` (таймаут ожидания блокировки, `0` — без ограничения). Миграция необратима вперёд: единственный корректный откат — восстановление БД из бэкапа совместимой версии (см. [Резервное копирование и восстановление](grafana_backup_restore.md)). Не редактируйте таблицы миграций вручную.

Для SQLite при блокировках на записи доступны `[database] query_retries` (повторы запроса, по умолчанию `0`) и `transaction_retries` (повторы транзакции, по умолчанию `5`). Постоянное решение под нагрузкой — миграция на PostgreSQL (см. [Обновление и миграция](grafana_upgrade_migration.md)).

### Сценарий 4. Метрики

```bash
curl -s http://localhost:3000/metrics | grep -E "grafana_http_request_duration|process_resident_memory_bytes|go_goroutines"
# → метрики HTTP-запросов, памяти процесса и числа горутин
```

Секция `[metrics]`: `enabled` (по умолчанию `true`), `interval_seconds` (интервал записи во внешний TSDB, по умолчанию `10`). Эндпоинт можно закрыть Basic Auth, задав `basic_auth_username` и `basic_auth_password`. Заведите скрейпинг `/metrics` в Prometheus — это лучший способ заметить регрессию до жалоб пользователей (см. [Производительность и тюнинг](grafana_performance_tuning.md)).

### Сценарий 4a. Профилирование (CPU, память, зависания)

Профилировщик слушает **отдельный порт** (по умолчанию `localhost:6060`) и включается при запуске сервера:

```bash
# Запуск с профилировщиком (только временно!)
grafana server -profile -profile-addr=0.0.0.0 -profile-port=6060

# Эквивалент через переменные окружения
GF_DIAGNOSTICS_PROFILING_ENABLED=true GF_DIAGNOSTICS_PROFILING_ADDR=0.0.0.0 \
  GF_DIAGNOSTICS_PROFILING_PORT=6060 grafana server

# Снять heap-профиль (для утечек снимают два с интервалом и сравнивают)
curl -s http://localhost:6060/debug/pprof/heap -o heap1.prof
sleep 30
curl -s http://localhost:6060/debug/pprof/heap -o heap2.prof
go tool pprof -http=localhost:8081 --base heap1.prof heap2.prof

# CPU-профиль за 30 секунд
curl -s "http://localhost:6060/debug/pprof/profile?seconds=30" -o cpu.prof
go tool pprof cpu.prof
```

Флаги: `-profile-addr` (по умолчанию `localhost`), `-profile-port` (по умолчанию `6060`), `-profile-block-rate` (доля событий блокировок, по умолчанию `1`), `-profile-mutex-rate` (доля конкуренции мьютексов, по умолчанию `0`). Эквивалентные переменные: `GF_DIAGNOSTICS_PROFILING_ENABLED/ADDR/PORT/BLOCK_RATE/MUTEX_RATE`. Для непрерывного профилирования (Pyroscope) предусмотрены дельта-эндпоинты `/debug/pprof/delta_heap`, `/debug/pprof/delta_block`, `/debug/pprof/delta_mutex`.

### Сценарий 4b. Трассировка

```bash
# Низкоуровневый трассировщик рантайма Go
grafana server -tracing -tracing-file=/tmp/trace.out
# эквивалент: GF_DIAGNOSTICS_TRACING_ENABLED=true GF_DIAGNOSTICS_TRACING_FILE=/tmp/trace.out
go tool trace /tmp/trace.out
```

Этот режим пишет низкоуровневую трассировку рантайма Go. Чтобы получить OTLP-трейсы (те же спаны, что уходят в Jaeger/OTLP), можно писать их в файл без коллектора — секция `[tracing.opentelemetry.file] path = /var/lib/grafana/traces/capture.json`; экспортёр включается только если не заданы `tracing.opentelemetry.jaeger`/`tracing.opentelemetry.otlp`. Просмотр — в Explore через источник Tempo («Import trace»).

### Сценарий 5. Диагностика за обратным прокси (502 / редиректы)

```bash
# Grafana слушает локально?
ss -ltnp | grep 3000
# → LISTEN 127.0.0.1:3000 (если http_addr=127.0.0.1)

# Заголовки от прокси (HSTS / Secure-cookie)
curl -sI https://grafana.example.internal/api/health | grep -i "strict-transport-security\|set-cookie"
```

Типовые причины: `root_url` указывает на `http://` или на внутренний адрес; прокси не передаёт `X-Forwarded-Proto $scheme` (тогда cookie не помечается `Secure` и возможен вечный редирект); Grafana за подпутём без `serve_from_sub_path = true`. Настройка прокси и TLS — в [Безопасность и жёсткая настройка](grafana_security_hardening.md).

### Сценарий 6. Сброс пароля Grafana Admin

```bash
# Базовый случай
grafana cli admin reset-admin-password '<new password>'

# Внешняя БД или нестандартные пути: обязательно указать homepath и config,
# иначе CLI возьмёт дефолтную SQLite и сбросит пароль не в той БД
grafana cli --homepath /usr/share/grafana --config /etc/grafana/grafana.ini \
  admin reset-admin-password '<new password>'
```

Если админ-пользователь не найден (изменён ID), команда выводит список админов с их ID — повторите с флагом `--user-id <id>`.

### Сценарий 7. Плагины

```bash
grafana cli plugins ls                 # установленные и версии
grafana cli plugins list-remote        # доступные в репозитории
grafana cli plugins update <id>        # обновить один
grafana cli plugins update-all         # обновить все
grafana cli plugins remove <id>        # удалить

docker compose logs grafana | grep -i plugin
```

Причины проблем с плагинами: несовместимость с версией Grafana, архитектура (плагин собран только под amd64, а хост — arm64), отсутствие подписи при `allow_loading_unsigned_plugins = false`. При загрузке стартует backend-процесс плагина — его ошибки видны в логах с `logger=plugin.<id>`. Подробнее — [Плагины](grafana_plugins.md).

### Сценарий 8. Источники данных и таймауты панелей

```bash
# Точечная проверка источника
curl -s "$GRAFANA_URL/api/datasources/uid/<uid>/health" \
  -H "Authorization: Bearer <service-account-token>" | jq
# → {"status":"OK"} или текст ошибки соединения
```

Таймаут проксирования задаётся в `[dataproxy] timeout` (по умолчанию `30` секунд) и применяется к запросам источников. Симптом «панель пустая, `context deadline exceeded`» — тяжёлый запрос не укладывается в таймаут: оптимизируйте запрос на стороне источника или увеличьте `timeout`. Диагностика источников и прокси — в [Источники данных](grafana_datasources.md).

### Сценарий 9. Быстрый сбор диагностики

Минимальный набор для разбора инцидента или тикета:

```bash
grafana server -v                                   # версия
curl -s http://localhost:3000/api/health | jq       # живость + БД
journalctl -u grafana-server -n 500 --no-pager      # логи (или docker compose logs)
grafana cli plugins ls                              # установленные плагины
```

В Docker дополнительно снимайте `docker compose config` (итоговый конфиг с подстановками) и `docker inspect <container>` (лимиты, тома, env).

## Дополнительная информация

### Рекомендации по эксплуатации

- Скрейпите `/metrics` внешним Prometheus — это даёт регрессии памяти и латентности до жалоб пользователей.
- Повышайте уровень логов точечно через `filters` и возвращайте `info` сразу после разбора.
- Держите профилировщик выключенным в публичном контуре: он без аутентификации раскрывает внутреннюю статистику. Включайте на время, привязывайте к localhost или закрывайте сетью/прокси.
- Логируйте SQL только временно (`[database] log_queries = true`) — это заметно нагружает систему.
- Фиксируйте версию Grafana рядом с дампом (`grafana server -v` или `/api/health`).
- Для разбора HA-проблем всегда проверяйте идентичность `secret_key` на узлах и синхронизацию времени (NTP/Chrony): дрейф > 500 мс вызывает дребезг алертов.

### Типичные ошибки и их решение

| Проблема | Возможная причина | Решение |
| :--- | :--- | :--- |
| `/api/health` не отвечает (connection refused) | Процесс не запущен или не тот порт | `systemctl status grafana-server`; проверить `http_addr`/`http_port` |
| `"database":"failed"` в `/api/health` | Нет доступа к БД или сорвана миграция | Проверьте доступ к БД напрямую, логи `migrator`/`sqlstore` |
| Процесс не стартует, в логах `bind: address already in use` | Порт 3000 занят | `ss -ltnp \| grep 3000`, сменить `http_port` или освободить порт |
| `failed to migrate` при старте | Миграция не завершилась или БД несовместима | Восстановить БД из бэкапа нужной версии; не править таблицы вручную |
| `database is locked` в логах | SQLite не выдерживает конкурентную запись (Unified Alerting) | Перейти на PostgreSQL — см. [Обновление и миграция](grafana_upgrade_migration.md#сценарий-7-миграция-sqlite--postgresql-docker-compose) |
| 502 от прокси | Grafana ещё стартует или упала | `ss -ltnp` на 3000, логи Grafana; увеличить `start_period` healthcheck |
| Вечный редирект / cookie не ставится | `root_url` неверен или нет `X-Forwarded-Proto` | `root_url` с внешним `https://...`, проксировать `X-Forwarded-Proto $scheme` |
| Плагин не загружается | Несовместимость версии/архитектуры, нет подписи | `grafana cli plugins update/remove`; проверить архитектуру и `allow_loading_unsigned_plugins` |
| Панель пустая, `context deadline exceeded` | Таймаут источника | Увеличить `[dataproxy] timeout`, оптимизировать запрос |
| Забыт пароль Admin | — | `grafana cli admin reset-admin-password` (см. Сценарий 6) |
| Рост памяти / OOM | Рендеринг изображений в том же процессе | Вынести `grafana-image-renderer` в отдельный сервис — см. [Рендеринг изображений](grafana_image_rendering.md) |
| Алерты «дребезжат» в HA | Оцениваются на всех узлах или дрейф времени | Включить SNE (`ha_single_node_evaluation`), использовать NTP — см. [Высокая доступность](high_availability.md) |
| Профайлер недоступен | Не включён при запуске | Запускать с `-profile`; слушает отдельный порт `6060` |

### Коды HTTP-ответов

| Код | Значение при диагностике Grafana |
| :--- | :--- |
| 200 | Успех; для `/api/health` — приложение и БД живы |
| 302 | Редирект на логин или на `root_url` (при `enforce_domain`/подпути) |
| 401 | Не пройдена аутентификация (просрочен токен, неверный service account) |
| 403 | Аутентификация пройдена, но нет прав (RBAC) |
| 404 | Неверный путь: подпуть без `serve_from_sub_path` или устаревший эндпоинт |
| 502/504 | Прокси не получил (вовремя) ответ от Grafana |

### Ограничения и особые случаи

- Миграция схемы необратима вперёд; не редактируйте таблицы миграций вручную — только восстановление из бэкапа.
- `debug`-логи могут содержать чувствительные данные запросов (в т.ч. значения переменных) — очищайте перед передачей третьим лицам.
- Профилировщик и `/metrics` без защиты раскрывают внутреннее состояние и статистику; `/metrics` закрывается через `[metrics] basic_auth_*`, профилировщик — сетью/прокси.
- В Helm/Docker пути логов и конфигов отличаются от systemd: используйте `docker compose logs` / `kubectl logs` и env `GF_*` вместо правки файла.
- Синхронизация времени между узлами критична только для HA и алертинга; на одиночном узле обычно не влияет.

### Очистка и откат изменений

- После диагностики верните `[log] level = info` (уберите `GF_LOG_LEVEL`/`GF_LOG_FILTERS`) и отключите профилировщик (перезапуск без `-profile`).
- Удалите снятые профили (`cpu.prof`, `heap1.prof`, `heap2.prof`) — они могут занимать сотни мегабайт.
- Временные изменения `root_url`/`grafana.ini` сохраняйте с копией оригинала и возвращайте после проверки.
- Отключите `[database] log_queries` и `[metrics] basic_auth_*`, если они больше не нужны.

### Актуальность и статус

Эндпоинты `/api/health` и `/metrics` и утилиты `grafana cli`/`grafana server` стабильны на 11.x/12.x/13.x. В Grafana 13.0 старые обёртки `grafana-cli` и `grafana-server` (как отдельные бинарники) удалены — используйте `grafana cli` и `grafana server`; служба systemd при этом по-прежнему называется `grafana-server`. Начиная с Grafana 13 маршруты `/api` постепенно вытесняются новым `/apis`; legacy-маршруты продолжают работать. Профилирование и трассировка включаются при запуске сервера (`-profile`, `-tracing`) или переменными `GF_DIAGNOSTICS_*`, а не ключом `[profiling]`.

### Связанные темы

- [Производительность и тюнинг](grafana_performance_tuning.md)
- [Резервное копирование и восстановление](grafana_backup_restore.md)
- [Обновление и миграция](grafana_upgrade_migration.md)
- [Безопасность и жёсткая настройка](grafana_security_hardening.md)
- [Плагины](grafana_plugins.md)
- [Источники данных](grafana_datasources.md)
- [Рендеринг изображений](grafana_image_rendering.md)
- [Высокая доступность](high_availability.md)
