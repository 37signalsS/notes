# Диагностика и устранение неполадок Grafana

Практическое руководство по диагностике self-hosted Grafana. Версии: 13.x актуальная, 12.x LTS, 11.x — EOL (июнь 2026). Облачные и ИИ-функции не рассматриваются.

## Определения

- **grafana-server** — основной процесс Grafana (бинарник/сервис); все логи и флаги относятся к нему.
- **/api/health** — лёгкий эндпоинт проверки живости: возвращает версию, статус и состояние БД.
- **/metrics** — эндпоинт Prometheus-метрик самой Grafana (процесс, HTTP, запросы, миграции).
- **/debug/pprof** — профайлер Go (CPU/heap/goroutine) для глубокой диагностики (включается отдельно).
- **Миграционный лок (migration lock)** — таблица `migration_log`/`dashboard_version`; зависшая миграция блокирует старт.
- **GF_* (переменные окружения)** — способ переопределения любого ключа `grafana.ini` (`GF_<SECTION>_<KEY>`).

## Базовые концепции

Диагностика Grafana идёт от внешнего к внутреннему:

1. **Живость** — `GET /api/health` (HTTP 200 + `status:"ok"`). Если не отвечает — процесс не запущен или не слушает порт.
2. **Логи** — первичный источник правды. Уровни: `debug` (подробно), `info` (штатно), `warn`/`error` (проблемы). В проде `info`; для разбора — временно `debug`.
3. **БД** — большинство «не стартует» связано с доступом к БД или незавершённой миграцией схемы.
4. **Прокси/сеть** — 502/редиректы/ломаные cookie обычно от некорректного `root_url` или отсутствия `X-Forwarded-*`.
5. **Метрики и профиль** — для регрессий производительности и утечек памяти (см. связанные темы по тюнингу).

Логи по умолчанию — в syslog (systemd: `journalctl -u grafana-server`) или в файл (`log/file` при `logger.mode = file`). В Docker — `docker compose logs grafana`.

## Практические сценарии

### Предварительные требования

- Доступ к хосту/контейнеру Grafana и к БД.
- Права чтения логов (`journalctl` или файл `grafana.log`).
- Для глубокой диагностики — возможность включить `debug` и профайлер временно.

### Сценарий 1. Проверка живости и версии

```bash
curl -s http://localhost:3000/api/health
# → {"commit":"...","database":"ok","version":"13.1.0","status":"ok"}
```

Если `database":"failed"` — проблема с БД (доступ/миграция). Если соединение отклонено — процесс не слушает порт.

### Сценарий 2. Чтение логов и повышение уровня

```bash
# systemd
journalctl -u grafana-server -n 100 --no-pager

# Docker
docker compose logs grafana --tail 100

# Временно включить debug (через env при запуске)
GF_LOG_LEVEL=debug grafana-server
```

Проверка: в логах ищем `level=error`, `migration`, `failed to connect`, `plugin`.

### Сценарий 3. Диагностика проблем с БД и миграцией

```bash
# Проверить доступ к БД напрямую (параметры из [database])
mysql -u grafana -p -h 127.0.0.1 -e "SHOW DATABASES;"   # для MySQL
pg_isready -h 127.0.0.1 -U grafana                       # для PostgreSQL

# Поиск зависшей миграции в логах
journalctl -u grafana-server --no-pager | grep -i "migration"
# → "migrations completed" — ок; "failed to migrate" / зависание — проблема
```

Типичное решение: восстановить БД из бэкапа нужной версии (миграция необратима вперёд) — см. связанные темы.

### Сценарий 4. Проверка метрик и профиля

```bash
# Метрики (Prometheus-формат)
curl -s http://localhost:3000/metrics | grep -E "grafana_(http|db|server)" | head
# → grafana_http_request_duration_seconds_count и пр.

# Профиль памяти (включить [profiling] enabled=true временно)
curl -s http://localhost:3000/debug/pprof/heap -o heap.prof
go tool pprof heap.prof
```

### Сценарий 5. Диагностика за прокси (502 / редиректы)

```bash
# Проверить, что Grafana слушает локально
ss -ltnp | grep 3000
# → LISTEN 127.0.0.1:3000 (если http_addr=127.0.0.1)

# Проверить X-Forwarded-Proto на прокси (см. hardening) — иначе cookie не Secure
curl -sI https://grafana.example.internal/api/health | grep -i "strict-transport-security\|set-cookie"
```

### Сценарий 6. Сброс пароля Grafana Admin

```bash
# Когда нет доступа, но есть доступ к хосту
grafana-cli admin reset-admin-password <new-strong-password>
# → Admin password changed successfully
```

### Сценарий 7. Проверка плагинов

```bash
grafana-cli plugins ls
# → список с версиями; ищем несовместимые/ошибочные
docker compose logs grafana | grep -i "plugin"
# → "plugin <id> is not compatible" означает обновить/удалить плагин
```

## Дополнительная информация

### Рекомендации по эксплуатации

- Ведите метрики `/metrics` самой Grafana во внешний мониторинг — это раннее предупреждение регрессий.
- Перед глубокой диагностикой поднимайте `GF_LOG_LEVEL=debug` только временно.
- Профайлер держите выключенным в публичном контуре (`/debug/pprof` раскрывает внутреннее состояние).
- Фиксируйте версию Grafana рядом с инцидентом (`/api/health`).
- При «не стартует» первым делом проверяйте БД и права плагинов, не меняя схему БД вручную.

### Типичные ошибки и их решение

| Симптом | Причина | Решение |
| --- | --- | --- |
| `curl /api/health` → connection refused | Процесс не запущен / не тот порт | `systemctl status grafana-server`; проверить `http_port` |
| `database":"failed"` в /api/health | Нет доступа к БД | Проверить `[database]`, сетевой доступ, учётные данные |
| `migration failed` при старте | БД новее версии Grafana / повреждена | Восстановить БД из бэкапа нужной версии |
| 502 Bad Gateway за nginx | Grafana не слушает / упала | `ss -ltnp` на 3000, логи Grafana |
| Вечный редирект / cookie не ставится | `root_url` http или нет `X-Forwarded-Proto` | `root_url=https://...`, проксировать `X-Forwarded-Proto` |
| `plugin not compatible` | Плагин несовместим с версией | `grafana-cli plugins update/remove <id>` |
| Панель пустая, в логах `context deadline exceeded` | Таймаут источника | Увеличить `timeout`, оптимизировать запрос |
| Не могу войти, забыл пароль Admin | — | `grafana-cli admin reset-admin-password` |
| Утечка памяти / OOM | Рендеринг в том же процессе | Вынести `grafana-image-renderer` отдельно |

### Ограничения и особые случаи

- Миграция БД необратима; не правьте таблицы миграций вручную — только восстановление из бэкапа.
- `debug`-логи могут содержать чувствительные параметры запросов — очищайте перед передачей третьим лицам.
- Профайлер доступен без аутентификации локально — защищайте сеть/прокси.
- В Helm/Docker пути логов и конфигов отличаются от systemd; используйте `docker compose logs` / `kubectl logs`.

### Очистка и откат изменений

- После диагностики верните `GF_LOG_LEVEL=info` и `[profiling] enabled = false`.
- Удалите снятые профили (`cpu.prof`, `heap.prof`) — они могут быть большими.
- При временном изменении `root_url`/`grafana.ini` сохраняйте оригинал и возвращайте после проверки.

### Актуальность и статус

Эндпоинты `/api/health`, `/metrics` и утилита `grafana-cli` стабильны на 11.x/12.x/13.x. Профайлер — стандартный для Go-сервисов Grafana.

### Связанные темы

- [Производительность и тюнинг](grafana_performance_tuning.md)
- [Резервное копирование и восстановление](grafana_backup_restore.md)
- [Безопасность и жёсткая настройка](grafana_security_hardening.md)
