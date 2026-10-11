# Команда docker logs: Справочник

**Актуально для:** Docker Engine 29.x (флаги стабильны с API 1.35; `--until` — с API 1.35)

## Определения

**`docker logs`** — команда Docker CLI (`docker container logs [OPTIONS] CONTAINER`), пакетно извлекающая логи контейнера. Работает с логами, уже записанными лог-драйвером: для `json-file`, `local` и `journald` — нативно, для остальных драйверов — через локальный кэш Dual Logging (Docker 20.10+).

**Multiplexed stream (stdcopy)** — формат, в котором Docker API отдаёт логи контейнера без TTY: каждый чанк логов оборачивается в 8-байтовый заголовок (1 байт — тип потока `0` = stdout / `1` = stderr, 4 байта — длина payload, 3 байта — резерв). CLI демультиплексирует поток перед выводом. Для контейнеров с TTY (`tty: true`) поток отдаётся «сырым» — без заголовков, stdout и stderr не различаются.

**Log retention контейнера** — логи контейнера хранятся на хосте всё время существования контейнера (включая остановленные) и удаляются только вместе с контейнером (`docker rm`). В отличие от Kubernetes, в Docker нет флага `--previous`: логи упавшего и перезапущенного контейнера доступны, пока контейнер не удалён.

**Log forging** — подмена/добавление фальшивых записей в лог через внедрение управляющих символов (CRLF). Отдельная тема — см. [Log Injection и безопасность логов](./docker_log_injection_security.md).

## Предпосылки

- **Docker Engine** 20.10+ (для чтения логов при сетевых драйверах через Dual Logging)
- **Docker CLI** с доступом к Docker daemon (root или группа `docker`)
- **Контейнер с настроенным лог-драйвером**, поддерживающим чтение (`json-file`, `local`, `journald` — нативно; остальные — через Dual Logging)

**Быстрая диагностика:**
```bash
# Драйвер контейнера (определяет, откуда читаются логи)
docker inspect --format '{{.HostConfig.LoggingConfig.Type}}' <container>
# → json-file

# Есть ли TTY (влияет на формат потока и разделение stdout/stderr)
docker inspect --format '{{.Config.Tty}}' <container>
# → false

# Путь к лог-файлу (json-file)
docker inspect --format '{{.LogPath}}' <container>
# → /var/lib/docker/containers/<id>/<id>-json.log
```

## Базовые концепции

### Полный список флагов `docker logs`

| Флаг | Короткий | По умолчанию | Описание |
| :--- | :--- | :--- | :--- |
| `--details` | — | `false` | Показывает дополнительные атрибуты: переменные окружения и labels, переданные через `--log-opt` (опции `labels`, `env` драйвера `json-file`) |
| `--follow` | `-f` | `false` | Стримить новые записи после выдачи всех существующих (аналог `tail -f`) |
| `--since` | — | — | Логи после указанного момента: RFC3339 (`2013-01-02T13:23:37Z`), UNIX-timestamp, Go-duration (`42m`, `1h30s`, `3h`) |
| `--tail` | `-n` | `all` | Число строк с конца. Отрицательное или нечисловое значение трактуется как `all` |
| `--timestamps` | `-t` | `false` | Добавлять RFC3339Nano-метку (`2014-09-16T06:17:46.000000000Z`) к каждой записи |
| `--until` | — | — | Логи до указанного момента (API 1.35+). Форматы как у `--since`; относительная длительность отсчитывается от текущего момента клиента |

**Форматы времени (`--since`/`--until`):** RFC3339Nano, RFC3339, `2006-01-02T15:04:05`, `2006-01-02T15:04:05.999999999`, `2006-01-02T07:00`, `2006-01-02`, UNIX-секунды[.наносекунды], Go-duration (`10m`, `1h30m`). Без суффикса `Z` или смещения используется локальная таймзона клиента.

**Важно:** `--since`/`--until` с относительными длительностями вычисляются относительно часов **клиентской машины**, а не хоста Docker. При рассинхронизации часов (см. [Chrony — NTP](../../Linux/Networking/Services/chrony_ntp.md)) выборка по времени будет смещена.

### Как работает `docker logs` под капотом

1. CLI вызывает Docker API: `GET /containers/{id}/logs?follow=true&stdout=true&stderr=true&since=...&until=...&timestamps=...&tail=...&details=...`.
2. Демон читает лог-файл (json-file/local) или journald и отдаёт поток.
3. Для контейнеров без TTY поток мультиплексирован (stdcopy, 8-байтовый заголовок на чанк); CLI разделяет stdout/stderr обратно.
4. При `--follow` соединение остаётся открытым; демон транслирует новые записи по мере записи в файл.

**Логи остановленных контейнеров:** `docker logs` работает для остановленных контейнеров — файл сохраняется до удаления контейнера. `docker rm` удаляет и логи. Для контейнеров, пересозданных Compose (`--force-recreate`), логи старого контейнера теряются — архивируйте файл перед пересозданием, если история нужна.

### Отличие от `kubectl logs --previous`

| Аспект | Docker | Kubernetes |
| :--- | :--- | :--- |
| Логи упавшего контейнера | Доступны, пока контейнер не удалён | Удаляются при перезапуске контейнера |
| Флаг `--previous` | **Не существует** | `kubectl logs -p` — логи предыдущей инстанции |
| Рекомендация | Не удаляйте контейнер до анализа (`docker ps -a`) | Используйте `--previous` |

## Практические сценарии

### Сценарий 1: Диагностика инцидента по времени

```bash
# Логи за последний час с метками времени
docker logs --since 1h --timestamps <container>

# Точное окно (RFC3339)
docker logs --since 2026-10-04T14:00:00Z --until 2026-10-04T15:00:00Z <container>

# Последние 200 строк ошибок
docker logs --tail 200 <container> 2>&1 | grep -i error

# Следить за логами, начиная с текущего момента
docker logs -f --since 0s <container>
```

### Сценарий 2: Метаданные контейнера в логах (`--details`)

```bash
# Запуск с пробросом labels/env в записи лога
docker run -d --name tagged \
  --log-driver=json-file \
  --log-opt labels=service,env \
  --log-opt env=APP_VERSION \
  --label service=api \
  --label env=prod \
  -e APP_VERSION=1.2.3 \
  alpine sh -c 'echo "started"; sleep 60'

# Чтение с атрибутами
docker logs --details tagged
# → {"log":"started\n","stream":"stdout","time":"...","attrs":{"service":"api","env":"prod","APP_VERSION":"1.2.3"}}
```

### Сценарий 3: Экспорт логов в файл

```bash
# Полный дамп логов контейнера (до удаления контейнера)
docker logs --timestamps <container> > /tmp/container-logs-$(date +%Y%m%d).log

# Только stderr
docker logs <container> 2>/tmp/stderr.log 1>/dev/null
```

### Сценарий 4: `docker compose logs` и `docker service logs`

```bash
# Compose: логи всех сервисов проекта
docker compose logs --tail 50 --timestamps

# Compose: один сервис, следить, без префикса сервиса
docker compose logs -f --no-log-prefix web

# Compose: окно времени (--until есть в compose logs, как в docker logs)
docker compose logs --since 10m --until 5m web

# Swarm: логи сервиса (только json-file или journald драйвер!)
# Выполняется на менеджере Swarm (cluster management command)
docker service logs --tail 100 --since 30m my_service

# Swarm: логи конкретной задачи, без обрезки строк
docker service logs --no-trunc --raw <task_id>

# Swarm: чистый вывод без ID задач и без маппинга ID→имя (удобно для grep)
docker service logs --no-task-ids --no-resolve --tail 100 my_service

# Swarm: метаданные (labels/env из --log-opt), API 1.30+
docker service logs --details my_service
```

**Ограничение Swarm:** `docker service logs` функционален **только** для сервисов с драйверами `json-file` или `journald`. Сетевые драйверы (gelf, fluentd, splunk, loki) не поддерживаются — используйте централизованное хранилище или агентный сбор. Флаги `--raw` и `--details` требуют API 1.30+.

### Сценарий 5: Контейнер с TTY

```bash
# Запуск с TTY (интерактивные приложения)
docker run -it --name tty-app alpine sh

# Логи: поток «сырой», stdout/stderr не разделяются,
# управляющие последовательности терминала попадают в лог как есть
docker logs tty-app
```

**Практическое следствие:** в TTY-контейнерах ANSI-escape-последовательности (цвета, очистка экрана) попадают в лог-файл — при анализе в терминале это может мешать чтению (см. [Log Injection](./docker_log_injection_security.md)).

## Дополнительная информация

### Troubleshooting

| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| `docker logs` пуст | Контейнер запущен с `none` драйвером; или приложение пишет в файл, а не stdout | Проверьте драйвер: `docker inspect --format '{{.HostConfig.LoggingConfig.Type}}'`; для файловых логов — [файловые логи](./docker_file_based_logging.md) |
| `docker logs` не работает с сетевым драйвером | Docker < 20.10 без Dual Logging | Обновите Docker или используйте хранилище/агент |
| `docker logs -f` «зависает» | Известный баг moby#39235 (фикс — PR #39969, 2019): при ротации с `max-file=1` писатель закрывает файл и открывает с `O_TRUNC`, событие не приходит в inotify (consumer ждёт `write`/`rename`/`remove`) | Обновите Docker; на уязвимых версиях — `max-file >= 2` или драйвер `local` |
| Логи обрываются на NUL-байте | Баг moby#53631 (2026, open): `docker logs` молча обрезает вывод на NUL-байте в json-file (exit 0, без ошибок). `--since` читает файл от начала — при повреждении в середине вернёт 0 строк для любой метки времени; `--tail` работает, только если окно начинается после повреждения | Диагностика: `tr -cd '\000' < "$(docker inspect --format '{{.LogPath}}' <container>)" \| wc -c` (0 = файл цел); сравните последнюю строку файла (`grep -avP '\x00' <LogPath> \| tail -1`) с `docker logs`; причина — повреждение файла (unclean shutdown, ext4 delayed allocation), диагностируйте диск |
| `docker logs -f` обрывается после ротации logrotate | Внешний `truncate`/`copytruncate` (moby#45728, known and expected, tracked in moby#36853): демон не поддерживает усечение лога извне — reader «зависает» на усечённом файле | Не используйте `copytruncate` на `*-json.log`; ротацию выполняет сам драйвер (`max-size`/`max-file`) — см. [Ротацию логов](./docker_log_rotation.md) |
| `--since` выбирает не тот диапазон | Часы клиента рассинхронизированы с хостом; относительные duration считаются по часам клиента | Синхронизируйте NTP на клиенте и хосте ([Chrony](../../Linux/Networking/Services/chrony_ntp.md)); используйте абсолютные RFC3339-метки |
| `docker service logs` пуст | Сервис использует сетевой драйвер (gelf/fluentd/splunk/loki) | `docker service logs` работает только с `json-file`/`journald`; логи — в хранилище |

### Best Practices

1. **Всегда используйте `--timestamps`** при диагностике инцидентов — метки из записи приложения и метки Docker могут различаться.
2. **Не удаляйте контейнер до анализа** — `docker rm` уничтожает логи; сначала сделайте дамп (`docker logs > file`).
3. **`--since`/`--until` с абсолютными метками** в скриптах автоматизации — относительные длительности зависят от часов клиента.
4. **Для Swarm-кластеров** держите `json-file`/`journald` на сервисах, где нужен `docker service logs`, либо полагайтесь на централизованное хранилище.
5. **`--details`** полезен в audit-сценариях: labels/env записываются в каждую строку лога.
6. **Проверяйте целостность лог-файла после краха хоста** — NUL-байты в json-file (moby#53631) обрывают чтение молча: `tr -cd '\000' < <LogPath> | wc -c` и сравнение последней строки файла с выводом `docker logs`. Расхождение — сигнал повреждения, логи читайте из файла напрямую.

### Ограничения

1. **Нет `--previous`** — в Docker логи живут пока жив контейнер; концепция «предыдущей инстанции» из Kubernetes неприменима.
2. **TTY-контейнеры** — stdout/stderr не разделяются, управляющие последовательности попадают в лог.
3. **`--tail` с отрицательным/нечисловым значением** трактуется как `all` — не используйте для «всего кроме N строк».
4. **Производительность `--follow`** при очень частой ротации — исторический баг (moby#39235), исправлен в 2019; на старых версиях возможны пропуски.
5. **Внешний truncate не поддерживается** — `copytruncate` из logrotate на `*-json.log` ломает `docker logs -f` (moby#45728, «known and expected», отслеживается в moby#36853); ротация — только через `max-size`/`max-file` драйвера.
6. **`--since` читает файл от начала** — при повреждении json-file в середине (NUL-байты, moby#53631) выборка по времени вернёт пустой результат, даже если свежие записи на диске целы.

### Ссылки на смежные темы

* **[Обзор системы логирования в Docker](./docker_logging_drivers_overview.md)** — лог-драйверы, Dual Logging, режимы доставки.
* **[Управление ротацией логов](./docker_log_rotation.md)** — `max-size`/`max-file`, механизм ротации.
* **[Файловые логи приложений](./docker_file_based_logging.md)** — что делать, если приложение пишет не в stdout.
* **[Log Injection и безопасность логов](./docker_log_injection_security.md)** — CRLF/ANSI-инъекции в логах.
* **[Агентный сбор логов](./docker_agent_based_logging.md)** — Alloy, Vector, Fluent Bit, Filebeat.
* **[Chrony — NTP](../../Linux/Networking/Services/chrony_ntp.md)** — синхронизация часов для корректных временных меток.
* **[Docker daemon.json — полный референс](../docker_daemon_config.md)** — глобальная настройка лог-драйвера.
