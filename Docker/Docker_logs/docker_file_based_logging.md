# Файловые логи приложений в Docker

**Актуально для:** Docker Engine 29.x, Docker Compose v2.x

## Определения

**Файловые логи в контейнере** — ситуация, когда приложение записывает логи в файл внутри файловой системы контейнера (например, `/var/log/app.log`), а не в `stdout`/`stderr`. Лог-драйверы Docker перехватывают **только** стандартные потоки: файлы невидимы для `docker logs`, для лог-драйверов и для агентов, читающих `/var/lib/docker/containers/`.

**Symlink-to-stdout паттерн** — создание символической ссылки с пути лога приложения на `/dev/stdout` (или `/proc/self/fd/1`): приложение пишет «в файл», а данные попадают в стандартный поток и перехватываются Docker. Стандартный подход в официальных образах (nginx, httpd).

**Log-streaming sidecar** — отдельный контейнер в том же Compose-стеке, монтирующий общий volume с приложением и выполняющий `tail -F` файла лога, перенаправляя вывод в свой `stdout`. Делает файловые логи доступными для Docker-инфраструктуры логирования.

**Host volume + logrotate** — монтирование хостовой директории в контейнер и ротация логов средствами хоста (`logrotate`). Подходит для legacy-приложений, требующих реальных файлов.

## Предпосылки

- **Приложение, пишущее в файл** (legacy, Java-приложения с RollingFileAppender, nginx с `access_log /var/log/nginx/access.log`, базы данных)
- **Docker Compose** (для sidecar-паттерна) или доступ к хосту (для volume+logrotate)
- Понимание, что **`docker logs` не покажет файловые логи** — это не баг, а архитектурное ограничение лог-драйверов

**Быстрая диагностика «пустых» логов:**
```bash
# docker logs пуст, хотя приложение работает?
docker logs <container>
# → (пусто)

# Проверьте, пишет ли приложение в файл внутри контейнера
docker exec <container> sh -c 'ls -la /var/log/ && tail -5 /var/log/*.log 2>/dev/null'

# Проверьте, куда пишет конфиг приложения
docker exec <container> sh -c 'grep -r "log" /etc/nginx/nginx.conf | grep -v "^#"'
```

## Базовые концепции

### Почему файлы невидимы для Docker

Лог-драйвер Docker подключается к файловым дескрипторам `1` (stdout) и `2` (stderr) процесса PID 1 (и его потомков, унаследовавших дескрипторы). Всё, что приложение записывает в файл на диске, обходит этот механизм полностью:

```
Приложение → stdout/stderr → Docker Engine → лог-драйвер → хранилище   (видно Docker)
Приложение → /var/log/app.log → файл в container layer                 (НЕ видно Docker)
```

**Последствия:**
- `docker logs` пуст
- Логи теряются при удалении контейнера (container layer удаляется)
- Нет ротации, нет централизованного сбора
- При пересоздании контейнера (`docker compose up --force-recreate`) история логов исчезает — если логи пишутся в container layer; named volume и bind-mount сохраняются (см. «Где физически живут файловые логи»)

### Паттерн 1: Symlink на /dev/stdout (рекомендуемый)

Приложение пишет в «файл», который на самом деле — стандартный поток:

```dockerfile
# Dockerfile
RUN mkdir -p /var/log/app && ln -sf /dev/stdout /var/log/app/app.log
# Приложение пишет в /var/log/app/app.log → данные идут в stdout → Docker лог-драйвер
```

**Ограничения:**
- Работает для одного файла лога; для нескольких — несколько ссылок
- Приложение должно открывать файл заново при ротации (или не ротировать вовсе — ротацию делает Docker)
- Не подходит для приложений, проверяющих тип файла (stat не вернёт обычный файл)
- Для multi-process контейнеров используйте s6-overlay (см. [Multi-Process паттерн](./docker_multi_process_logging.md))

**Пример nginx (официальный образ использует этот паттерн):**
```dockerfile
RUN ln -sf /dev/stdout /var/log/nginx/access.log \
 && ln -sf /dev/stderr /var/log/nginx/error.log
```

**Когда доступен конфиг приложения — перенастройте фреймворк** (надёжнее symlink: приложение само управляет форматом и буферизацией, нет риска `stat()`-проверок):

```xml
<!-- logback.xml: Java-приложение пишет в stdout вместо RollingFileAppender -->
<appender name="CONSOLE" class="ch.qos.logback.core.ConsoleAppender">
    <encoder>
        <pattern>%d{ISO8601} [%thread] %-5level %logger{36} - %msg%n</pattern>
    </encoder>
</appender>
<root level="INFO">
    <appender-ref ref="CONSOLE"/>
</root>
```

```xml
<!-- log4j2.xml: аналогично, Console-appender вместо RollingFile -->
<Console name="Console" target="SYSTEM_OUT">
    <PatternLayout pattern="%d{ISO8601} [%t] %-5level %logger{36} - %msg%n"/>
</Console>
```

```nginx
# nginx.conf (собственный образ, не официальный)
access_log /dev/stdout main;
error_log /dev/stderr warn;
```

JSON-формат для Java (LogstashEncoder) — см. [Structured Logging](../../Linux/SystemAdministration/Logging/structured_logging.md); конфигурация nginx — см. [Nginx: best practices](../Dockerfile/Docker_best_practices/web_servers.md).

### Паттерн 2: Log-streaming sidecar (Docker Compose)

Два сервиса делят volume; sidecar читает файл и пишет в свой stdout:

```yaml
services:
  app:
    image: legacy-app:1.0
    volumes:
      - app-logs:/var/log/app
    # приложение пишет /var/log/app/app.log

  log-streamer:
    image: alpine:3.24
    # Ожидание создания файла: depends_on ждёт только запуск контейнера,
    # но не создание лог-файла приложением
    command: sh -c 'while [ ! -f /var/log/app/app.log ]; do sleep 1; done; exec tail -F /var/log/app/app.log'
    volumes:
      - app-logs:/var/log/app:ro
    depends_on:
      - app
    logging:
      driver: json-file
      options:
        max-size: "10m"
        max-file: "5"

volumes:
  app-logs:
```

**Механизм:** `tail -F` (большая F — отслеживает ротацию по имени файла) читает новые записи и пишет в stdout sidecar'а, откуда их перехватывает лог-драйвер. Логи sidecar'а доступны через `docker compose logs log-streamer`.

**Нюансы:**
- `tail -F` (большая F) вместо `tail -f`: при ротации приложением файла tail переоткрывает новый файл
- `depends_on` **не ждёт появления файла лога** — sidecar может стартовать раньше приложения; цикл `while [ ! -f ... ]` решает это (BusyBox `tail` в Alpine не поддерживает `--retry`)
- `exec` перед `tail` — shell заменяется процессом tail, и `SIGTERM` при `docker compose stop` доходит до tail, а не теряется в shell
- `tail -F` отслеживает файлы, существовавшие на момент старта; файлы с новыми именами, появившиеся позже (ротация по шаблону имени), не подхватываются — перезапустите sidecar или используйте фиксированное имя файла
- Двойная ротация: если приложение ротирует файл, а Docker ротирует лог sidecar'а — настройте ротацию только на одной стороне
- Задержка: tail опрашивает файл (обычно 1с) — логи приходят с задержкой

### Паттерн 3: Host volume + logrotate

Для legacy-приложений, которым нужны реальные файлы на диске:

```yaml
services:
  app:
    image: legacy-app:1.0
    volumes:
      - /srv/legacy-app/logs:/var/log/app
```

```conf
# /etc/logrotate.d/legacy-app (на ХОСТЕ)
/srv/legacy-app/logs/*.log {
    daily
    rotate 14
    compress
    delaycompress
    missingok
    notifempty
    copytruncate
}
```

**`copytruncate`** обязателен, если приложение не переоткрывает файлы по сигналу (SIGHUP): файл копируется, а оригинал обрезается на месте — приложение продолжает писать в тот же inode. Если приложение поддерживает сигнал (nginx, postgresql), предпочтительнее `postrotate` + сигнал — нулевые потери (см. [logrotate](../../Linux/SystemAdministration/Logging/logrotate.md)).

### Где физически живут файловые логи

| Тип хранилища | Путь на хосте | Доступ агентам | Живёт при `docker compose down` |
| :--- | :--- | :--- | :--- |
| **Named volume** | `/var/lib/docker/volumes/<name>/_data` | Через `docker volume inspect` (путь opaque) | Да — удаляется только с `-v` |
| **Bind mount** | Явный путь (`/srv/legacy-app/logs`) | Прямой | Да |
| **Container layer** (без volume) | Внутри writable layer контейнера | Только `docker exec` / `docker cp` | Нет — удаляется с контейнером |

```bash
# Где смонтирован named volume
docker volume inspect app-logs --format '{{.Mountpoint}}'
# → /var/lib/docker/volumes/app-logs/_data

# Размер writable layer контейнера (сюда растут логи без volume)
docker ps -s --format 'table {{.Names}}\t{{.Size}}'
```

**Критично для SRE:** `docker compose up -d --force-recreate` **сохраняет** named volumes (теряется только container layer), а `docker compose down -v` **удаляет** named volumes вместе со всеми логами. Для сохранения истории — `down` без `-v` или бэкап (Сценарий 3).

### Паттерн 4: Чтение через Docker API (агенты)

Агенты (Alloy, Vector, Fluent Bit) могут читать логи контейнеров через Docker API (`/containers/{id}/logs`) — но **только stdout/stderr**, не файлы внутри контейнера. Для файловых логов агент должен монтировать volume или работать как sidecar.

### Сравнение паттернов

| Паттерн | Надёжность | Сложность | Ротация | Централизованный сбор | Когда использовать |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **Symlink /dev/stdout** | Высокая | Минимальная | Docker (драйвер) | Полный | Новые образы; однофайловые логи |
| **Sidecar tail** | Средняя (задержка ~1с) | Средняя | Двойная — настраивать аккуратно | Полный | Чужие/legacy-образы без возможности правки |
| **Host volume + logrotate** | Высокая | Средняя | logrotate (хост) | Через агент на хосте | Требование реальных файлов, compliance |
| **s6-overlay** (multi-process) | Высокая | Средняя | s6-log / Docker | Полный | Multi-process контейнеры |

## Практические сценарии

### Сценарий 1: Перевод legacy-приложения на stdout (symlink)

```dockerfile
FROM eclipse-temurin:17-jre

# Приложение пишет в /var/log/app/application.log
RUN mkdir -p /var/log/app && ln -sf /dev/stdout /var/log/app/application.log

COPY app.jar /app.jar
CMD ["java", "-jar", "/app.jar"]
```

> Образ `openjdk` официально deprecated с 2022 и не обновляется — используйте `eclipse-temurin` (см. [Java best practices](../Dockerfile/Docker_best_practices/java.md)).

**Валидация:**
```bash
docker build -t app-stdout .
docker run -d --name app app-stdout
docker logs app
# → логи приложения в stdout

# Проверка, что ссылка работает
docker exec app ls -la /var/log/app/
# → application.log -> /dev/stdout
```

### Сценарий 2: Sidecar для образа, который нельзя менять

```yaml
# docker-compose.yml
services:
  db:
    image: postgres:17
    volumes:
      - pg-logs:/var/log/postgresql
    # PostgreSQL по умолчанию пишет в stderr → Docker перехватывает (рекомендуется).
    # Файловые логи нужны только по требованию (compliance) — тогда:
    # command: postgres -c logging_collector=on \
    #   -c log_directory=/var/log/postgresql -c log_filename=postgresql-%Y-%m-%d.log

  # Пример sidecar для приложения с файловыми логами:
  legacy:
    image: legacy-app:1.0
    volumes:
      - legacy-logs:/var/log/legacy

  legacy-log-streamer:
    image: alpine:3.24
    command: sh -c 'while ! ls /var/log/legacy/*.log >/dev/null 2>&1; do sleep 1; done; exec tail -F /var/log/legacy/*.log'
    volumes:
      - legacy-logs:/var/log/legacy:ro
    depends_on:
      - legacy

volumes:
  pg-logs:
  legacy-logs:
```

**Валидация:**
```bash
docker compose up -d
docker compose logs --tail 20 legacy-log-streamer
# → логи legacy-приложения

# Без префиксов сервисов (чистый поток для пайплайнов)
docker compose logs --no-log-prefix legacy-log-streamer
```

### Сценарий 3: Архивация логов перед пересозданием контейнера

```bash
# Дамп логов контейнера (stdout-логи)
docker logs --timestamps <container> > /backup/logs-$(date +%Y%m%d).log

# Извлечение файловых логов из container layer (контейнер жив или остановлен)
docker cp <container>:/var/log/app ./logs-backup-$(date +%Y%m%d)

# Дамп файловых логов из bind-mount на хосте
tar -czf /backup/app-logs-$(date +%Y%m%d).tar.gz /srv/legacy-app/logs/

# Только после этого — пересоздание
docker compose up -d --force-recreate
```

**Что сохраняется, а что теряется:**
- `--force-recreate` — named volumes и bind-mounts сохраняются, теряется только container layer (логи без volume)
- `docker compose down` — volumes сохраняются
- `docker compose down -v` — named volumes **удаляются** вместе с логами

### Сценарий 4: Мониторинг файловых логов в контейнере

```bash
# Размер файловых логов внутри контейнера
docker exec <container> du -sh /var/log/

# Размер writable layer контейнера (логи без volume растут здесь)
docker ps -s --format 'table {{.Names}}\t{{.Size}}'

# Алерт на рост (в скрипте/CI)
size=$(docker exec <container> du -s /var/log/ | awk '{print $1}')
[ "$size" -gt 1048576 ] && echo "WARNING: логи > 1GB в контейнере"
```

## Дополнительная информация

### Troubleshooting

| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| `docker logs` пуст | Приложение пишет в файл, а не stdout | Symlink-паттерн или sidecar (см. выше) |
| Sidecar не видит новых записей | `tail -f` не переоткрывает файл после ротации | Используйте `tail -F` (по имени файла) |
| Дублирование логов в sidecar | Приложение ротирует файл + tail перечитывает | `tail -F` + `copytruncate`-совместимая ротация; или ротация только в Docker |
| Логи теряются при `docker compose up --force-recreate` | Container layer удаляется вместе с контейнером | Дамп перед пересозданием (Сценарий 3); host volume |
| `permission denied` в sidecar | Файл создан root'ом, sidecar читает как другой пользователь | Единый USER в образах или `:ro`-том с корректными правами |
| symlink не работает | Приложение проверяет тип файла (stat) или открывает с O_CREAT на ссылке | Проверьте поведение приложения; fallback — sidecar |
| Лог-файл растёт внутри контейнера | Нет ротации (приложение не ротирует, Docker не видит файл) | Symlink (ротация Docker) или host volume + logrotate |
| Named volume пуст после `docker compose down -v` | Флаг `-v` удаляет named volumes вместе с данными | `down` без `-v`; бэкап тома перед удалением |
| Sidecar стартует, но не видит логов | `depends_on` ждёт запуск контейнера, а не создание файла | Цикл ожидания файла в команде sidecar (см. Паттерн 2) |
| `tail -F /var/log/app/*.log` падает сразу после старта | Glob не раскрывается, если файлов ещё нет | Проверка `ls` перед tail (см. Паттерн 2) |

### Best Practices

1. **По умолчанию — stdout/stderr**: новый образ всегда пишет логи в стандартные потоки; файлы — только по требованию.
2. **Symlink /dev/stdout** — первый выбор для однофайловых логов в собственных образах.
3. **Sidecar — для чужих образов**, которые нельзя пересобрать.
4. **Host volume + logrotate** — когда compliance требует реальных файлов с ротацией на хосте.
5. **Не смешивайте ротации**: если Docker ротирует stdout-логи, приложение не должно ротировать тот же поток (и наоборот).
6. **Архивируйте перед пересозданием** — `docker rm` уничтожает и stdout-логи, и container layer с файлами.
7. **Для multi-process контейнеров** — s6-overlay с s6-log (см. [Multi-Process паттерн](./docker_multi_process_logging.md)).
8. **Если доступен конфиг приложения — перенастройте фреймворк** (logback/log4j2 → ConsoleAppender, nginx → `access_log /dev/stdout`): это надёжнее symlink, приложение само управляет форматом и буферизацией.

### Ограничения

1. **Docker API не читает файлы внутри контейнера** — только stdout/stderr; для файлов нужен volume или sidecar.
2. **Sidecar добавляет задержку** (~1с) и дополнительный контейнер в стеке.
3. **Symlink ломает приложения**, которые делают `stat()`/`fseek()` на лог-файле или ожидают регулярный файл.
4. **Docker named volume** не виден хостовым агентам напрямую — для агентного сбора используйте bind-mount (host volume).
5. **BusyBox `tail` (Alpine) не поддерживает `--retry`** — для ожидания появления файла используйте цикл `while [ ! -f ... ]` (см. Паттерн 2).

### Ссылки на смежные темы

* **[Команда docker logs: справочник](./docker_logs_cli.md)** — чтение stdout/stderr логов.
* **[Обзор системы логирования](./docker_logging_drivers_overview.md)** — почему драйверы видят только stdout/stderr.
* **[Multi-Process паттерн](./docker_multi_process_logging.md)** — s6-overlay и сбор логов нескольких процессов.
* **[Агентный сбор логов](./docker_agent_based_logging.md)** — Alloy, Vector, Fluent Bit и чтение через Docker API.
* **[logrotate: ротация и сжатие](../../Linux/SystemAdministration/Logging/logrotate.md)** — `copytruncate` vs сигналы.
* **[Управление ротацией логов Docker](./docker_log_rotation.md)** — ротация stdout-логов драйвером.
* **[Structured Logging](../../Linux/SystemAdministration/Logging/structured_logging.md)** — JSON-формат для Java (logback LogstashEncoder).
* **[Nginx: best practices](../Dockerfile/Docker_best_practices/web_servers.md)** — `access_log /dev/stdout` в конфигурации nginx.
* **[Java best practices](../Dockerfile/Docker_best_practices/java.md)** — базовые образы (`eclipse-temurin` вместо deprecated `openjdk`).
