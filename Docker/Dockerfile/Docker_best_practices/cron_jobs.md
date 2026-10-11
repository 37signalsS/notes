# Cron-задачи в контейнерах

**Актуально для:** Docker 20.10+, cronie 1.7.0+ / debian-cron / busybox crond

## Определения

- **cron:** Демон планировщика задач Unix. Читает crontab-файлы и запускает команды по расписанию. В контейнерах требует явного запуска в foreground-режиме (`cron -f`), иначе контейнер сразу завершится.
- **crontab:** Файл расписания (формат: `мин час день месяц день_недели команда`). Каждая строка — одна задача; файл должен заканчиваться переводом строки, иначе последняя задача не выполнится.
- **CRON_TZ:** Переменная в crontab (cronie, Vixie cron), задающая часовой пояс конкретной задачи независимо от `TZ` контейнера. Поддерживается с давних версий; последняя стабильная — cronie 1.7.2.
- **systemd timer:** Альтернатива cron на хосте: юнит-триггер + юнит-сервис. Преимущество — логирование в journald, зависимости, отсутствие демона cron.
- **CronJob (Kubernetes):** Ресурс K8s, создающий Job по расписанию. Предпочтительный способ регламентных задач в Kubernetes — cron не нужен внутри контейнера.
- **at:** Одноразовый отложенный запуск. В контейнерах практически не применяется (требует демона `atd`).
- **PID 1 проблема:** Контейнер завершается, когда завершается PID 1. Если PID 1 — приложение, cron не запущен; если cron — приложение не запущено. Одновременно нужны два процесса (supervisord, s6-overlay) или разделение на два контейнера.

## Базовые концепции

### Предпосылки

- **Docker Engine 20.10+**.
- Понимание проблемы PID 1: [Init Process (tini)](../init_process_tini.md).
- Знание формата crontab: `*/5 * * * * /script.sh` — каждые 5 минут.

### Проблема cron в контейнерах

Классический cron рассчитан на хост с systemd. В контейнере возникают три проблемы:

1. **Демон не запущен:** Образы приложений не содержат cron. Установка (`apt-get install cron`) + запуск (`cron -f`) — обязанность Dockerfile.
2. **Логирование:** cron по умолчанию пишет в syslog, которого в контейнере нет. Задачи молча падают. Решение — перенаправление вывода в stdout/stderr.
3. **Окружение:** cron-задачи не наследуют `ENV` из Dockerfile и переменные compose — только `SHELL`, `PATH`, `HOME`. Все переменные нужно задавать в crontab или sourcing-скриптом.

### Пять паттернов запуска регламентных задач

| Паттерн | Когда использовать | Инструмент |
| :--- | :--- | :--- |
| **1. cron как PID 1** | Контейнер существует только ради задач (бэкапы, очистка) | `cron -f` / `crond -f` |
| **2. cron + приложение** | Legacy-монолит, тесно связанные процессы | s6-overlay, supervisord |
| **3. Хост cron + `docker exec`** | Разовые задачи администрирования | crontab на хосте |
| **4. Kubernetes CronJob** | Регламентные задачи в K8s | `CronJob` resource |
| **5. systemd timer на хосте** | Очистка Docker, хостовые задачи | systemd timer |

**Правило:** если задача не требует того же окружения, что и приложение — выносите её в отдельный контейнер или на хост. Один контейнер = одна ответственность.

### Формат crontab

```
# ┌───────────── минута (0–59)
# │ ┌───────────── час (0–23)
# │ │ ┌───────────── день месяца (1–31)
# │ │ │ ┌───────────── месяц (1–12)
# │ │ │ │ ┌───────────── день недели (0–6, Вс=0)
# │ │ │ │ │
# */5 * * * * /usr/local/bin/backup.sh >> /proc/1/fd/1 2>&1
```

**Подводные камни:**
- Файл должен заканчиваться пустой строкой — иначе последняя задача игнорируется.
- `%` в команде интерпретируется как перевод строки — экранируйте `\%` (например, в `date +\%Y\%m\%d`).
- Переменные окружения задаются строками `NAME=value` до задач.

### Логирование cron в stdout

Без syslog cron молчит. Два решения:

1. **Перенаправление в задаче:** `... >> /proc/1/fd/1 2>&1` — вывод попадает в stdout PID 1, откуда его собирает `docker logs`.
2. **cronie с `-x`:** флаги отладки (`-x 8` — логирование всех событий) в stderr.

### Переменные окружения и entrypoint-скрипт

cron не наследует `ENV` из Dockerfile и `environment:` compose — он запускает задачи с минимальным окружением: только `SHELL`, `PATH`, `HOME` и то, что задано в crontab. Три способа передать переменные:

**1. Задать в crontab (простой способ):**
```crontab
SHELL=/bin/bash
PATH=/usr/local/bin:/usr/bin:/bin
DB_HOST=db
DB_PORT=5432

0 2 * * * /usr/local/bin/backup.sh >> /proc/1/fd/1 2>&1
```

**2. Entry-point скрипт, который выгружает ENV в crontab перед стартом:**
```dockerfile
# Dockerfile
COPY entrypoint.sh /usr/local/bin/entrypoint.sh
RUN chmod +x /usr/local/bin/entrypoint.sh
ENTRYPOINT ["entrypoint.sh"]
```

```bash
#!/bin/bash
set -e

# Выгружаем ENV в crontab
{
  echo "SHELL=/bin/bash"
  echo "PATH=/usr/local/bin:/usr/bin:/bin"
  env | while IFS='=' read -r key value; do
    echo "${key}=${value}"
  done
  cat /etc/cron.d/app-jobs
} > /tmp/crontab-final

# Устанавливаем финальный crontab
crontab /tmp/crontab-final

# Запускаем cron в foreground
exec cron -f
```

**3. Supercronic** — переменные окружения доступны автоматически, без дополнительной настройки.

### Безопасность

**Non-root:** cron-демон (cronie/debian-cron) традиционно требует root для запуска. Задачи из `/etc/cron.d` с полем `root` выполняются от root. Для снижения привилегий:

- Используйте `cddocker728/cron` или аналогичный образ, где демон запускается от root, но задачи выполняются от non-root пользователя (`worker` по умолчанию, настраивается через `CRON_USER`).
- Или задайте `USER` в Dockerfile и запускайте cron через `crontab -u` от имени этого пользователя (требует настройки доступа к crontab).
- Для Supercronic: `USER` в Dockerfile полностью контролирует привилегии, т.к. supercronic не требует root.

**Минимизация capabilities:** Добавьте `--cap-drop=ALL` и явно добавляйте только необходимые:
```bash
docker run --cap-drop=ALL --cap-add=net_raw my-cron:latest
```

**no-new-privileges:** Предотвращает escalation через setuid/setgid бинари:
```dockerfile
# В Dockerfile не задаётся напрямую, но проверяется через security-opt:
# docker run --security-opt=no-new-privileges my-cron:latest
```

**Идемпотентность задач:** Каждая cron-задача должна быть способна к повторному запуску без негативных последствий:
- Проверяйте, запускалась ли задача ранее (файл-флаг, метка в БД, idempotency key).
- Используйте блокировки (`flock`) при работе с общими ресурсами:
  ```crontab
  0 2 * * * /usr/bin/flock -n /var/lock/backup.lock /usr/local/bin/backup.sh >> /proc/1/fd/1 2>&1
  ```
- Избегайте накопления временных файлов; очищайте в начале задачи.

### Часовые пояса

```dockerfile
ENV TZ=Europe/Moscow
```

```crontab
CRON_TZ=Asia/Tokyo
15 9 * * * /usr/local/bin/tokyo-job.sh >> /proc/1/fd/1 2>&1
```

Подробно: [Управление временной зоной](../../Concepts/docker_timezone_management.md).

## Практические сценарии

### Сценарий 0: Supercronic — альтернатива системному cron для контейнеров

Supercronic — кроссплатформенный запускатель crontab-задач, разработанный конкретно для контейнеров. Устраняет основные неудобства системного cron: не требует syslog, не теряет переменные окружения, выводит логи в stdout/stderr, корректно обрабатывает сигналы.

| Характеристика | Системный cron (cronie/debian-cron) | Supercronic |
| :--- | :--- | :--- |
| Переменные окружения | Не наследуют ENV Dockerfile | Наследуются автоматически |
| Логирование | Требует перенаправления в stdout | Логи в stdout/stderr по умолчанию |
| SIGTERM | Не обрабатывается корректно | Плавное завершение текущих задач |
| Требует root | Да (для запуска демона) | Нет, можно запускать от non-root |
| Управление конфигом | Файл, монтируется или копируется | Файл, можно менять на лету (SIGUSR2) |
| Секундная точность | Нет (минимальный интервал — 1 мин) | Да (через `cronexpr`) |

**Установка в Dockerfile:**

```dockerfile
# syntax=docker/dockerfile:1
FROM alpine:3.22

RUN wget -qO /usr/local/bin/supercronic \
    https://github.com/aptible/supercronic/releases/download/v0.7.2/supercronic-linux-amd64 \
    && chmod +x /usr/local/bin/supercronic

COPY crontab /app/crontab
WORKDIR /app

# Запуск от non-root пользователя
RUN addgroup -S cronuser && adduser -S cronuser -G cronuser
USER cronuser

CMD ["supercronic", "/app/crontab"]
```

**Crontab (без root-поля, без перенаправления):**

```crontab
# Переменные окружения доступны напрямую
*/5 * * * * /app/backup.sh
0 2 * * * /app/cleanup.sh
```

**Особенности:**
- `SIGUSR2` — graceful shutdown + перезагрузка crontab без перезапуска контейнера.
- `SIGQUIT` — graceful shutdown.
- `USER` в crontab игнорируется (задачи запускаются от имени процесса); используйте `USER` в Dockerfile.
- Поддерживает выражения с секундной точностью (через пакет `cronexpr`).

**Когда использовать:** когда нужно избежать сложностей системного cron и не требуется полный контроль над средой выполнения (например, миграция существующих crontab-файлов в контейнер).

---

### Сценарий 1: cron как PID 1 (Debian)

Контейнер для регламентных задач: бэкапы, очистка, отчёты.

```dockerfile
# syntax=docker/dockerfile:1
FROM debian:bookworm-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends cron curl \
    && rm -rf /var/lib/apt/lists/*

# Non-root пользователь для задач (cron daemon запускается от root,
# но задачи из /etc/cron.d с полем `root` выполняются от root;
# для привилегированных задач используйте отдельного non-root
# пользователя через USER в скриптах или через sudo -u)
RUN addgroup --system cronuser && adduser --system --group cronuser

COPY jobs/backup.sh /usr/local/bin/backup.sh
COPY jobs/crontab /etc/cron.d/app-jobs

RUN chmod 0644 /etc/cron.d/app-jobs \
    && chmod +x /usr/local/bin/backup.sh \
    && touch /var/log/cron.log

# HEALTHCHECK: проверяем, что демон cron жив
HEALTHCHECK --interval=60s --timeout=5s --start-period=10s --retries=3 \
    CMD pgrep -x cron > /dev/null || exit 1

# cron -f: foreground-режим, cron становится PID 1
CMD ["cron", "-f"]
```

`jobs/crontab` (обратите внимание на пользователя и финальную пустую строку):

```crontab
SHELL=/bin/bash
PATH=/usr/local/bin:/usr/bin:/bin

# Бэкап каждый день в 02:00, вывод в stdout
0 2 * * * root /usr/local/bin/backup.sh >> /proc/1/fd/1 2>&1

# Очистка каждые 6 часов
0 */6 * * * root /usr/local/bin/cleanup.sh >> /proc/1/fd/1 2>&1

```

**Валидация:**
```bash
docker build -t app-cron:latest .
docker run -d --name cron-test app-cron:latest

# Проверка что cron — PID 1
docker exec cron-test ps -p 1 -o pid,comm
# → PID COMMAND
# → 1   cron

# Проверка расписания
docker exec cron-test cat /etc/cron.d/app-jobs

# Принудительный запуск задачи (для теста)
docker exec cron-test /usr/local/bin/backup.sh
# → Backup completed

docker logs cron-test
# → Backup completed
```

### Сценарий 2: cron + приложение (s6-overlay)

Когда приложение и его регламентные задачи тесно связаны (общий lifecycle, общие файлы). Полный разбор multi-process паттерна: [Multi-process контейнеры](../../Docker_logs/docker_multi_process_logging.md).

```dockerfile
# syntax=docker/dockerfile:1
FROM python:3.14-slim AS base
RUN apt-get update && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

# s6-overlay v3.2.3.2 (2026-07-16)
ADD --from=justwatch/s6-overlay:3.2.3.2 / /

COPY app/ /app/
COPY services/ /etc/s6-overlay/s6-rc.d/

ENTRYPOINT ["/init"]
```

Структура s6-rc сервисов:

```
services/
├── app/
│   ├── type          # → longrun
│   └── run           # → exec python /app/main.py
├── cron/
│   ├── type          # → longrun
│   └── run           # → exec cron -f
└── app/
    └── dependencies.d/
        └── cron      # cron стартует вместе с app
```

**Валидация:**
```bash
docker exec <container> s6-rc -l list
# → app
# → cron
```

### Сценарий 3: Хост cron + docker exec

Для задач администрирования (бэкапы БД, очистка) — cron на хосте, а не в контейнере:

```bash
# /etc/cron.d/docker-backup
0 2 * * * root docker exec db pg_dump -U app appdb | gzip > /backup/appdb-$(date +\%Y\%m\%d).sql.gz

# Очистка неиспользуемых образов (systemd timer предпочтительнее — см. сценарий 5)
0 3 * * * root docker image prune -f >> /var/log/docker-prune.log 2>&1
```

**Плюсы:** не нужен cron в образе; задача живёт независимо от контейнера.
**Минусы:** нет изоляции окружения; требуется доступ к docker.sock.

### Сценарий 4: Kubernetes CronJob

В Kubernetes cron внутри контейнера не нужен — используйте ресурс `CronJob`:

```yaml
apiVersion: batch/v1
kind: CronJob
metadata:
  name: db-backup
spec:
  schedule: "0 2 * * *"
  jobTemplate:
    spec:
      template:
        spec:
          restartPolicy: OnFailure
          containers:
            - name: backup
              image: postgres:17-alpine
              command:
                - /bin/sh
                - -c
                - pg_dump -h $DB_HOST -U app appdb | gzip > /backup/appdb-$(date +%Y%m%d).sql.gz
              env:
                - name: PGPASSWORD
                  valueFrom:
                    secretKeyRef:
                      name: db-secret
                      key: password
              volumeMounts:
                - name: backup
                  mountPath: /backup
          volumes:
            - name: backup
              persistentVolumeClaim:
                claimName: backup-pvc
```

Скелет CronJob в Helm-чарте: [Helm skeleton pattern](../../../Kubernetes/ToolsUtilities/Helm/helm_skeleton_pattern.md).

### Сценарий 5: systemd timer на хосте

Для хостовых задач (очистка Docker) systemd timer предпочтительнее cron — логирование в journald, зависимости от сервисов:

```ini
# /etc/systemd/system/docker-prune.service
[Unit]
Description=Docker prune (resources older than 24h)
After=docker.service
Requires=docker.service

[Service]
Type=oneshot
ExecStart=/usr/bin/docker system prune --filter "until=24h" -f
```

```ini
# /etc/systemd/system/docker-prune.timer
[Unit]
Description=Run docker-prune daily

[Timer]
OnCalendar=daily
Persistent=true

[Install]
WantedBy=timers.target
```

```bash
sudo systemctl enable --now docker-prune.timer
sudo systemctl list-timers
# → NEXT LEFT LAST PASSED UNIT ACTIVATES
# → ...  docker-prune.timer docker-prune.service
```

Подробно: [Очистка и GC-стратегии](../../Docker_fs/cleanup_gc_strategies.md).

### Сценарий 6: Альтернативы cron

| Задача | Альтернатива cron | Обоснование |
| :--- | :--- | :--- |
| Очистка ресурсов Docker | systemd timer / `docker system prune` в CI | Логирование, зависимости |
| Регламентные задачи в K8s | `CronJob` | Нативный ресурс, retry, история |
| Очереди с отложенным выполнением | RabbitMQ delayed plugin, Temporal | Надёжность, retry, visibility |
| Одноразовые задачи | `docker run --rm` из CI | Эфемерность |
| Интервальные проверки | Healthcheck, Prometheus alerting | Специализированный инструмент |

## Типичные ошибки и их решение

### Ошибка 1: Контейнер сразу завершается

**Причина:** cron запущен в daemon-режиме (`cron` без `-f`) — форкается и PID 1 завершается.

```dockerfile
# ПЛОХО: cron форкается, контейнер останавливается
CMD ["cron"]

# ХОРОШО: foreground
CMD ["cron", "-f"]

# Alpine (busybox crond)
CMD ["crond", "-f", "-l", "8"]
```

### Ошибка 2: Задача молча не выполняется

**Причина:** Нет syslog в контейнере; вывод задачи теряется.

```crontab
# Решение: перенаправление в stdout PID 1
*/5 * * * * /usr/local/bin/job.sh >> /proc/1/fd/1 2>&1
```

### Ошибка 3: Последняя задача в crontab не запускается

**Причина:** Файл не заканчивается переводом строки.

```bash
# Проверка
tail -c 1 /etc/cron.d/app-jobs | xxd
# → 0a (должен быть 0a = \n)

# Решение: добавить пустую строку в конце файла
```

### Ошибка 4: Переменные окружения недоступны в задаче

**Причина:** cron не наследует `ENV` Dockerfile и `environment:` compose.

```crontab
# Решение: задать переменные в crontab
SHELL=/bin/bash
PATH=/usr/local/bin:/usr/bin:/bin
DB_HOST=db
DB_PORT=5432

0 2 * * * /usr/local/bin/backup.sh >> /proc/1/fd/1 2>&1
```

### Ошибка 5: Задача выполняется в неправильном часовом поясе

**Причина:** Контейнер работает в UTC.

```dockerfile
ENV TZ=Europe/Moscow
# Для debian: apt-get install -y tzdata
```

Или per-task: `CRON_TZ=Asia/Tokyo` (cronie, Vixie cron).

### Ошибка 6: `%` в команде ломает расписание

**Причина:** В crontab `%` = перевод строки.

```crontab
# ПЛОХО: date +%Y%m%d обрежется на %
# ХОРОШО: экранируйте
0 2 * * * root /backup.sh $(date +\%Y\%m\%d) >> /proc/1/fd/1 2>&1
```

### Ошибка 7: Задача "съедает" ресурсы (OOM, дисковый thrift)

**Причина:** Нет ограничений на память/CPU/диск; задача может упасть в бесконечный цикл или накопить мусор.

```yaml
# docker-compose.yml
services:
  cron:
    image: app-cron:latest
    deploy:
      resources:
        limits:
          cpus: '0.50'
          memory: 256M
        reservations:
          cpus: '0.25'
          memory: 128M
```

```bash
# Или напрямую
docker run --memory=256m --cpus=0.5 app-cron:latest
```

```yaml
# K8s: CronJob с ресурсами
spec:
  jobTemplate:
    spec:
      template:
        spec:
          containers:
            - name: backup
              resources:
                limits:
                  memory: "256Mi"
                  cpu: "500m"
```

### Ошибка 8: Задача запускается дважды (concurrency)

**Причина:** Нет блокировки; при задержке или дублировании расписания задача запускается параллельно.

```crontab
# Решение: flock с таймаутом
0 2 * * * /usr/bin/flock -n /var/lock/backup.lock /usr/local/bin/backup.sh >> /proc/1/fd/1 2>&1
```

**В K8s:** используйте `concurrencyPolicy: Forbid`:
```yaml
spec:
  concurrencyPolicy: Forbid
```

## Лучшие практики

### Сводка рекомендаций

| Практика | Рекомендация | Причина |
| :--- | :--- | :--- |
| **Один контейнер = одна задача** | Отдельный контейнер для cron | Изоляция, независимый lifecycle |
| **Foreground** | `cron -f` / `crond -f` | PID 1 не завершается |
| **Логи** | `>> /proc/1/fd/1 2>&1` | Видимость в `docker logs` |
| **Окружение** | Переменные в crontab или entrypoint-скрипт | cron не наследует ENV |
| **K8s** | `CronJob` вместо cron в контейнере | Нативный ресурс |
| **Хост** | systemd timer вместо cron | journald, зависимости |
| **Файл** | Финальный `\n`, права 0644 | Последняя задача не теряется |
| **Тестирование** | Ручной запуск скрипта + `docker logs` | Отладка без ожидания расписания |
| **Безопасность** | Non-root, `--cap-drop=ALL`, секреты через Docker/K8s | Минимизация привилегий |
| **Идемпотентность** | Проверка запуска, `flock`, очистка временных файлов | Повторный запуск без побочных эффектов |
| **Ресурсы** | `--memory`/`--cpus` в compose, `resources.limits` в K8s | Предотвращение OOM/дискового thrift |
| **Healthcheck** | `pgrep cron` / `supercronic --check` | Обнаружение неработающего демона |
| **Альтернатива** | Supercronic для простых сценариев | Переменные, логи, сигналы "из коробки" |

### Чек-лист перед деплоем

- [ ] cron запущен в foreground (`-f`)
- [ ] Вывод задач перенаправлен в stdout/stderr
- [ ] crontab заканчивается пустой строкой
- [ ] Переменные окружения заданы в crontab или entrypoint
- [ ] Часовой пояс явно установлен (`TZ` / `CRON_TZ`)
- [ ] `%` экранирован как `\%`
- [ ] Задача проверена ручным запуском
- [ ] В K8s — CronJob вместо cron в контейнере
- [ ] Контейнер запускается от non-root пользователя
- [ ] Секреты не хранятся в образе (через `secretKeyRef`/Docker secrets)
- [ ] Задача идемпотентна (повторный запуск безопасен)
- [ ] Используется `flock` при работе с общими ресурсами
- [ ] Настроен healthcheck для обнаружения падения демона
- [ ] Ограничены ресурсы контейнера (`--memory`, `--cpus`)

## Смотрите также

- **[Init Process (tini)](../init_process_tini.md)** — PID 1 и обработка сигналов.
- **[Multi-process контейнеры](../../Docker_logs/docker_multi_process_logging.md)** — s6-overlay, supervisord для cron + app.
- **[Управление временной зоной](../../Concepts/docker_timezone_management.md)** — `TZ`, `CRON_TZ`.
- **[Очистка и GC-стратегии](../../Docker_fs/cleanup_gc_strategies.md)** — systemd timer вместо cron.
- **[Stateful-сервисы](./stateful_services.md)** — бэкапы БД как cron-задача.
- **[Helm skeleton pattern](../../../Kubernetes/ToolsUtilities/Helm/helm_skeleton_pattern.md)** — CronJob в Helm.
