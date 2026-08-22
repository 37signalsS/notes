# Централизованное логирование Docker: Лог-драйверы

## Определения

**Лог-драйвер (Logging Driver)** — это встроенный в Docker Engine механизм, который перехватывает потоки `STDOUT` и `STDERR` контейнера и перенаправляет их в указанное место назначения: локальный файл, системный журнал (Journald, Syslog) или сетевой эндпоинт (Loki, GELF, Fluentd).

**Централизованное логирование** — архитектурный паттерн, при котором логи со всех узлов инфраструктуры собираются в единое хранилище для обеспечения наблюдаемости (Observability), упрощения отладки и проведения аудита безопасности.

**Драйвер прямой отправки (Direct Push Driver)** — класс лог-драйверов (`loki`, `gelf`, `fluentd`, `awslogs`, `splunk`, `syslog`), которые самостоятельно транслируют логи по сети из Docker Engine в целевое хранилище без промежуточных агентов.

## Предпосылки

- **Docker Engine** версии 20.10 или выше (для Dual Logging и стабильной работы сетевых драйверов)
- **Docker CLI** с правами root или членство в группе `docker` для редактирования `/etc/docker/daemon.json`
- **Доступ по сети** к целевому сервису (Loki, Graylog, Fluentd, CloudWatch и т.д.) из каждого Docker-хоста
- **Открытый порт** на целевом сервисе (по умолчанию: `3100` для Loki, `12201` для GELF, `24224` для Fluentd, `514` для Syslog, `8088` для Splunk HEC)
- **Учётные данные** (при необходимости): IAM-политики для AWS CloudWatch, токен для Splunk, сертификаты TLS для защищённых соединений

**Проверка текущего лог-драйвера:**
```bash
docker info --format '{{.LoggingDriver}}'
# → json-file (по умолчанию)
```

**Просмотр драйвера конкретного контейнера:**
```bash
docker inspect --format '{{.HostConfig.LoggingConfig.Type}}' <container_name>
# → json-file
```

## Базовые концепции

При использовании лог-драйверов Docker Engine берет на себя роль транспортного агента. Это избавляет от необходимости запускать сторонние процессы для сбора логов, но перекладывает нагрузку по сетевой передаче на Docker daemon.

**Схема работы:**
`Приложение → STDOUT/STDERR → Docker Engine (Log Driver) → Сеть/Сокет → Приемник (Loki, Graylog, Splunk)`

**Ключевые особенности лог-драйверов:**
*   **Простота настройки**: Не требуют управления жизненным циклом дополнительных контейнеров.
*   **Минимальные ресурсы**: Docker Engine выполняет отправку в рамках одного процесса.
*   **Ограничение**: Функции обработки (парсинг, фильтрация, маскирование) минимальны или отсутствуют.
*   **Риск блокировки**: В `blocking` режиме сетевой сбой может заморозить контейнер.

### Режим работы: Blocking vs Non-blocking

По умолчанию большинство сетевых драйверов работают в **блокирующем (blocking)** режиме.

*   **Blocking (по умолчанию)**: Docker ждет подтверждения от приемника о получении лога. Если сеть нестабильна или приемник перегружен, Docker daemon приостанавливает (freezes) контейнер, чтобы не потерять данные. Это может привести к каскадным сбоям приложения.
*   **Non-blocking**: Docker пишет логи в промежуточный кольцевой буфер в оперативной памяти хоста.
    *   **Механизм**: Если буфер заполняется (например, при обрыве связи с Loki), новые входящие логи начинают вытеснять самые старые записи в буфере (принцип FIFO).
    *   **Преимущество**: Стабильность приложения гарантирована, даже если система логирования полностью недоступна.
    *   **Цена**: Возможна частичная потеря логов при переполнении буфера.

**Сравнение режимов:**

| Параметр | Blocking | Non-blocking |
| :--- | :--- | :--- |
| **Гарантия доставки** | Высокая (ожидание ACK) | Низкая (потери при переполнении) |
| **Стабильность приложения** | Риск фризов при сбоях сети | Гарантирована |
| **Потребление RAM** | Минимальное | `max-buffer-size` * кол-во контейнеров |
| **Рекомендация** | Критичные логи (аудит, безопасность) | Production по умолчанию |

### Механизм Dual Logging

Начиная с Docker 20.10, сетевые драйверы по умолчанию работают в режиме **Dual Logging**. Это решает проблему "слепой зоны", когда при использовании удаленного драйвера команда `docker logs` переставала работать.
*   **Суть**: Логи пишутся параллельно во внешний драйвер и в локальный бинарный кэш (драйвер `local`).
*   **Контроль**: Локальный кэш автоматически ротируется и не занимает много места.
*   **Важно**: Dual Logging поддерживается не всеми драйверами. Драйверы `gelf` и `syslog` в старых версиях Docker не поддерживали Dual Logging. В Docker 20.10+ это исправлено для большинства драйверов.
*   **Подробнее**: **[Управление ротацией логов Docker](./docker_log_rotation.md)**.

### Шаблонизация тегов (Tag Template)

Большинство сетевых драйверов поддерживают параметр `tag` для маршрутизации и идентификации логов. Docker использует шаблоны Go для динамической подстановки метаданных контейнера:

| Шаблон | Описание | Пример вывода |
| :--- | :--- | :--- |
| `{{.ID}}` | Короткий ID контейнера (12 символов) | `a1b2c3d4e5f6` |
| `{{.Name}}` | Полное имя контейнера (с `/` в начале) | `/my-app` |
| `{{.ImageID}}` | ID образа | `sha256:9d818...` |
| `{{.ImageName}}` | Имя образа | `nginx:latest` |
| `{{.FullID}}` | Полный SHA256 ID контейнера | `sha256:a1b2c3...` |

**Пример:** `tag="docker.{{.Name}}/{{.ID}}"` → `docker.//my-app/a1b2c3d4e5f6`

## Практические сценарии

### Сценарий 0: Глобальная настройка стабильности (`daemon.json`)

Для продакшена рекомендуется всегда использовать неблокирующий режим с адекватным размером буфера. Это применяется ко **всем** лог-драйверам.

**Пример в `/etc/docker/daemon.json`:**
```json
{
  "log-driver": "json-file",
  "log-opts": {
    "mode": "non-blocking",
    "max-buffer-size": "4m"
  }
}
```
*   `max-buffer-size`: 4 МБ буфера обычно достаточно для компенсации кратковременных сетевых задержек без риска исчерпания RAM. Для высоконагруженных систем рекомендуется `8m`-`16m`.

**Применение:**
```bash
sudo systemctl restart docker
# → Важно: изменения коснутся только НОВЫХ контейнеров
# Существующие контейнеры нужно пересоздать:
docker-compose up -d --force-recreate
```

**Валидация:**
```bash
docker info --format '{{.LoggingDriver}}'
# → json-file

# Проверка non-blocking для конкретного контейнера
docker inspect --format '{{.HostConfig.LogConfig.Config}}' <container>
```

### Сценарий 1: Драйвер Journald (Интеграция с ОС)

Предпочтителен для систем на базе systemd, так как позволяет использовать `journalctl` для анализа инфраструктуры.

**Параметры запуска:**
```bash
docker run -d \
  --log-driver=journald \
  --log-opt tag="{{.Name}}/{{.ID}}" \
  nginx
```

**Настройка в Docker Compose:**
```yaml
services:
  app:
    image: my-app:latest
    logging:
      driver: journald
      options:
        tag: "docker/{{.Name}}"
```

**Важно (Тюнинг rsyslog/journald):**
Если на хосте стоит `rsyslog`, он может дублировать логи контейнеров в `/var/log/syslog`. Чтобы этого избежать, настройте фильтрацию или отключите `ForwardToSyslog=yes` в `/etc/systemd/journald.conf`. Подробнее: **[rsyslog: Фильтрация и пересылка](../../Linux/SystemAdministration/Logging/rsyslog.md)**.

**Валидация:**
```bash
# Просмотр логов контейнера через journald
journalctl CONTAINER_NAME=<container_name> -n 50

# Фильтрация по приоритету
journalctl CONTAINER_NAME=<container_name> -p err
```

**Ограничения:**
*   Драйвер `journald` **не поддерживает** Dual Logging — команда `docker logs` не работает при его использовании.
*   Невозможно использовать теги для маршрутизации — логи попадают в общий поток journald.
*   Формат логов — текстовый, без структурированных метаданных Docker.

### Сценарий 2: Драйвер GELF (Graylog / Logstash)

Протокол GELF позволяет передавать структурированные данные и поддерживает сжатие.

**Конфигурация в Docker Compose:**
```yaml
services:
  api:
    image: my-api:latest
    logging:
      driver: gelf
      options:
        gelf-address: "udp://graylog-server:12201"
        gelf-compression-type: "gzip"
        gelf-compression-level: "2"
        tag: "api-prod"
```

**Доступные параметры:**

| Параметр | Описание | Значения |
| :--- | :--- | :--- |
| `gelf-address` | Адрес сервера Graylog (`udp://` или `tcp://`) | `udp://host:12201` |
| `gelf-compression-type` | Тип сжатия | `gzip`, `zlib`, `none` |
| `gelf-compression-level` | Уровень сжатия (0-9) | `2` (по умолчанию) |
| `tag` | Маркер лога (шаблон Go) | `api-prod` |

*   `gelf-address`: Поддерживает `udp` и `tcp`. UDP рекомендуется для минимизации задержек. TCP обеспечивает надёжную доставку, но добавляет латентность.
*   **Dual Logging**: Драйвер GELF поддерживает Dual Logging начиная с Docker 20.10+. Команда `docker logs` работает.

**Валидация:**
```bash
# Проверка доступности Graylog
nc -zuv graylog-server 12201

# Просмотр логов (Dual Logging)
docker logs <container_name> --tail 50
```

**Типичные ошибки:**
| Ошибка | Причина | Решение |
| :--- | :--- | :--- |
| `dial udp: lookup graylog-server: no such host` | DNS не резолвится | Проверьте `/etc/hosts` или DNS-сервер |
| `connection refused` | Graylog не запущен или порт закрыт | `nc -zuv host 12201`, проверьте firewall |
| `no buffer space available` | Переполнение в non-blocking режиме | Увеличьте `max-buffer-size` |

### Сценарий 3: Драйвер Fluentd (Маршрутизация логов)

Используется, когда Docker должен отправить логи в сложную цепочку обработки.

**Конфигурация Docker:**
```bash
docker run -d \
  --log-driver=fluentd \
  --log-opt fluentd-address=localhost:24224 \
  --log-opt fluentd-async-connect=true \
  --log-opt tag="docker.{{.Name}}" \
  my-app
```

**Настройка в Docker Compose:**
```yaml
services:
  app:
    image: my-app:latest
    logging:
      driver: fluentd
      options:
        fluentd-address: "localhost:24224"
        fluentd-async-connect: "true"
        tag: "docker.{{.Name}}"
```

**Пример `fluent.conf` (Прием и склейка Multiline):**
```conf
<source>
  @type forward
  port 24224
  bind 0.0.0.0
</source>

# Склеивание Java Stack Traces
<filter docker.**>
  @type concat
  key log
  multiline_start_regexp /^\d{4}-\d{2}-\d{2}/
  flush_interval 3s
</filter>

<match docker.**>
  @type stdout
</match>
```

**Важные параметры:**
*   `fluentd-async-connect=true`: Асинхронное подключение. Рекомендуется для production — предотвращает блокировку контейнера при недоступности Fluentd.
*   `fluentd-buffer-limit`: Лимит буфера в памяти (по умолчанию 8 МБ).

**Валидация:**
```bash
# Проверка доступности Fluentd
nc -zv localhost 24224

# Просмотр логов (Dual Logging)
docker logs <container_name> --tail 50
```

**Сравнение с агентным Fluentd:**

| Параметр | Fluentd-драйвер | Fluentd-агент |
| :--- | :--- | :--- |
| **Архитектура** | Docker → сеть → Fluentd | Docker → файл → агент → сеть |
| **Multiline** | Требует настройки на стороне Fluentd | Встроенные паттерны |
| **Фильтрация** | Ограничена | Полная (плагины Ruby) |
| **Отказоустойчивость** | Низкая (буфер RAM) | Высокая (буфер диск) |
| **Подробнее** | Этот раздел | **[Агентный сбор логов](./docker_agent_based_logging.md)** |

### Сценарий 4: Драйвер AWS Logs (Cloud Native)

Используется для прямой отправки логов в CloudWatch при запуске в AWS (EC2, Fargate).

**Параметры:**
```bash
docker run -d \
  --log-driver=awslogs \
  --log-opt awslogs-region=us-east-1 \
  --log-opt awslogs-group=my-app-logs \
  --log-opt awslogs-stream=web-server-01 \
  --log-opt awslogs-create-group=true \
  nginx
```

**Доступные параметры:**

| Параметр | Описание | Значение по умолчанию |
| :--- | :--- | :--- |
| `awslogs-region` | Регион AWS | Регион инстанса |
| `awslogs-group` | Имя Log Group | Обязательный |
| `awslogs-stream` | Имя Log Stream | Обязательный |
| `awslogs-create-group` | Автосоздание Log Group | `false` |
| `awslogs-datetime-format` | Формат времени | Формат strftime |
| `awslogs-multiline-pattern` | Regex для multiline | Пусто |

*   Требует настроенных IAM-прав (Policy `logs:CreateLogStream`, `logs:PutLogEvents`) на уровне инстанса или через IAM Role.
*   **Dual Logging**: Драйвер awslogs поддерживает Dual Logging начиная с Docker 20.10+.

**Валидация:**
```bash
# Проверка IAM-прав
aws logs describe-log-groups --log-group-name-prefix my-app-logs

# Просмотр логов в CloudWatch
aws logs get-log-events \
  --log-group-name my-app-logs \
  --log-stream-name web-server-01 \
  --start-time $(date -d '1 hour ago' +%s000)

# Просмотр логов локально (Dual Logging)
docker logs <container_name> --tail 50
```

**Типичные ошибки:**
| Ошибка | Причина | Решение |
| :--- | :--- | :--- |
| `AccessDeniedException` | Нет IAM-политики `logs:PutLogEvents` | Добавьте политику в IAM Role инстанса |
| `ResourceNotFoundException` | Log Group не существует | Установите `awslogs-create-group=true` |
| `InvalidParameterException` | Неверный формат `datetime-format` | Проверьте формат strftime |

### Сценарий 5: Драйвер Splunk

Для интеграции с корпоративной SIEM Splunk через HTTP Event Collector (HEC).

**Параметры:**
```bash
docker run -d \
  --log-driver=splunk \
  --log-opt splunk-url=https://splunk.example.com:8088 \
  --log-opt splunk-token=12345-abcde \
  --log-opt splunk-insecureskipverify=true \
  --log-opt splunk-format=json \
  nginx
```

**Настройка в Docker Compose:**
```yaml
services:
  app:
    image: my-app:latest
    logging:
      driver: splunk
      options:
        splunk-url: "https://splunk.example.com:8088"
        splunk-token: "12345-abcde"
        splunk-insecureskipverify: "true"
        splunk-format: "json"
        tag: "docker.{{.Name}}"
```

**Доступные параметры:**

| Параметр | Описание | Значение по умолчанию |
| :--- | :--- | :--- |
| `splunk-url` | URL сервера Splunk HEC | Обязательный |
| `splunk-token` | Токен HEC | Обязательный |
| `splunk-format` | Формат данных | `json` |
| `splunk-insecureskipverify` | Отключить проверку SSL | `false` |
| `splunk-source` | Источник событий | Имя хоста |
| `splunk-sourcetype` | Тип источника | `docker` |
| `splunk-index` | Индекс для записи | Индекс по умолчанию |

*   **Dual Logging**: Драйвер Splunk поддерживает Dual Logging начиная с Docker 20.10+.
*   **Безопасность**: В production используйте `splunk-insecureskipverify=false` с корневым сертификатом.

**Валидация:**
```bash
# Проверка доступности Splunk HEC
curl -k -H "Authorization: Splunk 12345-abcde" https://splunk.example.com:8088/services/collector/health

# Просмотр логов (Dual Logging)
docker logs <container_name> --tail 50
```

### Сценарий 6: Драйвер Syslog

Отправка логов в стандартный syslog-сервер (rsyslog, syslog-ng).

**Параметры:**
```bash
docker run -d \
  --log-driver=syslog \
  --log-opt syslog-address=tcp://syslog-server:514 \
  --log-opt syslog-facility=daemon \
  --log-opt tag="docker/{{.Name}}" \
  nginx
```

**Доступные параметры:**

| Параметр | Описание | Значения |
| :--- | :--- | :--- |
| `syslog-address` | Адрес сервера (`tcp://` или `udp://`) | `tcp://host:514` |
| `syslog-facility` | Код facility | `daemon`, `local0`-`local7` |
| `syslog-tls-ca-cert` | Путь к CA-сертификату (для TLS) | Путь к файлу |
| `syslog-tls-cert` | Путь к клиентскому сертификату | Путь к файлу |
| `syslog-tls-key` | Путь к приватному ключу | Путь к файлу |
| `tag` | Маркер лога | Шаблон Go |

*   **Dual Logging**: Драйвер syslog поддерживает Dual Logging начиная с Docker 20.10+.
*   **Безопасность**: В production используйте TCP + TLS для шифрования логов в транспорте.

**Валидация:**
```bash
# Просмотр логов на syslog-сервере (rsyslog)
tail -f /var/log/syslog | grep "docker"

# Или через journalctl на syslog-сервере
journalctl -u rsyslog -f | grep "docker"

# Просмотр логов локально (Dual Logging)
docker logs <container_name> --tail 50
```

**Сравнение драйверов Syslog и Journald:**

| Параметр | Syslog | Journald |
| :--- | :--- | :--- |
| **Протокол** | TCP/UDP (RFC 5424) | Локальный сокет |
| **Структура** | Текстовый формат | Бинарный формат |
| **Dual Logging** | Да (Docker 20.10+) | Нет |
| **Фильтрация** | Через rsyslog/syslog-ng | Через journalctl |
| **Пересылка** | Нативная (remote syslog) | Требует ForwardToSyslog |
| **Использование** | Legacy-системы, энтерпайз | systemd-дистрибутивы |

### Сценарий 7: Изменение драйвера для конкретного контейнера

Драйвер можно задать не только глобально, но и для отдельного контейнера через `--log-driver` или секцию `logging` в Docker Compose.

**Docker CLI:**
```bash
docker run -d \
  --log-driver=json-file \
  --log-opt max-size=10m \
  --log-opt max-file=5 \
  --name my-app \
  my-image:latest
```

**Docker Compose:**
```yaml
services:
  app:
    image: my-app:latest
    logging:
      driver: json-file
      options:
        max-size: "10m"
        max-file: "5"
        compress: "true"
```

**Важно:** Драйвер фиксируется при создании контейнера. Невозможно изменить `log-driver` или `log-opts` для уже запущенного контейнера. Требуется пересоздание.

### Сценарий 8: Полный стек с Loki (драйвер + Grafana)

Комбинация Loki-драйвера для сбора с Grafana для визуализации.

**`docker-compose.yml`:**
```yaml
services:
  loki:
    image: grafana/loki:3.4.2
    ports:
      - "3100:3100"
    volumes:
      - ./loki-config.yml:/etc/loki/local-config.yaml
    command: -config.file=/etc/loki/local-config.yaml

  grafana:
    image: grafana/grafana:11.5.0
    ports:
      - "3000:3000"
    environment:
      - GF_SECURITY_ADMIN_PASSWORD=admin
    depends_on:
      - loki

  app:
    image: nginx:latest
    logging:
      driver: loki
      options:
        loki-url: "http://loki:3100/loki/api/v1/push"
        loki-batch-size: "400"
        mode: "non-blocking"
        max-buffer-size: "8m"
```

**Валидация:**
```bash
# Проверка Loki
curl -s http://localhost:3100/ready
# → ready

# Проверка Grafana
curl -s http://localhost:3000/api/health
# → {"database":"ok"}

# Проверка наличия логов в Loki
curl -s "http://localhost:3100/loki/api/v1/query?query={job=\"docker\"}" | python3 -m json.tool | head -20
```

Подробнее: **[Настройка лог-драйвера Grafana Loki](./loki_logging_driver_setup.md)**.

## Дополнительная информация

### Сравнение всех лог-драйверов Docker

| Драйвер | Протокол | Dual Logging | Non-blocking | Сжатие | Multiline | Фильтрация |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **json-file** | Файл (диск) | Да | Да | Да | Нет | Нет |
| **local** | Файл (диск) | Да | Да | Да (встроено) | Нет | Нет |
| **journald** | Сокет systemd | **Нет** | Да | Нет | Нет | Нет |
| **syslog** | TCP/UDP | Да (20.10+) | Да | Нет | Нет | Нет |
| **gelf** | TCP/UDP | Да (20.10+) | Да | gzip/zlib | Нет | Нет |
| **fluentd** | TCP/Unix socket | Да | Да | Нет | Нет (требует настройки) | Нет |
| **awslogs** | HTTPS (CloudWatch) | Да (20.10+) | Да | Нет | Да | Нет |
| **splunk** | HTTPS (HEC) | Да (20.10+) | Да | Нет | Да | Нет |
| **loki** | HTTP/HTTPS | Да | Да | Нет | Да | Минимальная |

### Выбор метода: Драйвер или Агент?

| Параметр | Лог-драйверы | Агенты (Vector/Alloy) |
| :--- | :--- | :--- |
| **Отказоустойчивость** | Низкая (буфер только в RAM). | Высокая (буфер на диске). |
| **Трансформация** | Почти отсутствует. | Полноценный ETL (парсинг, маскирование). |
| **Нагрузка** | На Docker Engine. | На отдельный процесс (агент). |
| **Простота** | Настройка одной строкой. | Требует конфигурации агента. |
| **Multiline** | Ограничена (awslogs, splunk). | Полная поддержка (regex-паттерны). |
| **Фильтрация** | Отсутствует. | Полная (по контейнерам, лейблам, содержимому). |
| **Доп. ресурсы** | Минимальные. | 20-500 МБ RAM на агента. |

**Рекомендация:** Используйте лог-драйверы для быстрой интеграции в облачных средах (AWS/GCP) или при малых нагрузках. Для высоконагруженных систем с требованиями к сохранности данных (compliance) переходите на **[Агентный сбор логов Docker](./docker_agent_based_logging.md)**.

### Лучшие практики

1.  **Всегда используйте `non-blocking`** для production — это гарантирует стабильность приложений даже при проблемах с сетью или хранилищем.
2.  **Настройте `max-buffer-size`**: `4m` для dev/test, `8m`-`16m` для production. Потребление RAM: `max-buffer-size` * количество контейнеров с сетевым драйвером.
3.  **Настройте локальную ротацию** даже при использовании сетевого драйвера — Dual Logging пишет локальную копию. Подробнее: **[Управление ротацией логов Docker](./docker_log_rotation.md)**.
4.  **Используйте шаблоны тегов** (`tag="docker/{{.Name}}"`) для маршрутизации и идентификации логов в целевой системе.
5.  **Для критичных логов** (аудит, безопасность) используйте `blocking` режим или агентную сборку с disk-backed буфером.
6.  **Версионируйте `daemon.json`** в Git для воспроизводимости настроек.
7.  **Для TLS-соединений** используйте параметры `tls-ca-cert`, `tls-cert`, `tls-key` (поддерживается не всеми драйверами).

### Ограничения и известные проблемы

1.  **Драйвер фиксируется при создании контейнера**: Невозможно изменить `log-driver` или `log-opts` для уже запущенного контейнера. Требуется пересоздание.
2.  **`journald` не поддерживает Dual Logging**: Команда `docker logs` не работает при использовании этого драйвера.
3.  **Потеря логов в non-blocking режиме**: При переполнении буфера старые записи отбрасываются без уведомления. Для критичных логов используйте `blocking` или агентный сбор.
4.  **Нагрузка на Docker daemon**: Сетевые драйверы выполняют передачу данных в рамках Docker Engine. При высоком трафике это может увеличить потребление CPU.
5.  **Ограничение Multiline**: Не все драйверы поддерживают склейку многострочных логов. Для сложных паттернов (Java stack traces) рекомендуется агентный сбор.
6.  **Дублирование при ForwardToSyslog**: Если на хосте настроен `rsyslog` и активен `ForwardToSyslog=yes` в `journald.conf`, логи контейнеров могут дублироваться в `/var/log/syslog`.
7.  **`max-buffer-size` — общий для всех контейнеров**: Невозможно задать разный размер буфера для разных драйверов в пределах одного `daemon.json`. Используйте per-container настройку через Docker Compose.

### Типичные ошибки и решения

| Ошибка / Симптом | Возможная причина | Решение |
| :--- | :--- | :--- |
| **Контейнер "зависает" при записи логов** | Режим `blocking` при недоступном приемнике. | Переключите на `non-blocking`: `"mode": "non-blocking", "max-buffer-size": "10m"`. |
| **Логи обрезаются / теряются** | Размер буфера слишком мал, приемник недоступен太久. | Увеличьте `max-buffer-size` или перейдите на агентный сбор с disk-backed буфером. |
| **`docker logs` не работает** | Используется драйвер без Dual Logging (старый syslog/gelf). | Обновите Docker до 20.10+ или переключите на `json-file`/`local`. |
| **`permission denied` при чтении логов** | Драйвер не поддерживает чтение через `docker logs`. | Проверьте Dual Logging для вашего драйвера. |
| **Дублирование логов в `/var/log/syslog`** | Активен `ForwardToSyslog=yes` в journald.conf. | Отключите: `ForwardToSyslog=no` в `/etc/systemd/journald.conf`. |
| **`no buffer space available`** | Non-blocking буфер переполнен. | Увеличьте `max-buffer-size` или стабилизируйте приемник. |
| **`connection refused` на целевом порту** | Целевой сервис не запущен или порт закрыт. | Проверьте `nc -zv host port` и настройки firewall. |
| **`AccessDeniedException` (AWS)** | Нет IAM-политики для CloudWatch. | Добавьте `logs:CreateLogStream`, `logs:PutLogEvents` в IAM Role. |
| **Высокий CPU на Docker daemon** | Много контейнеров с сетевым драйвером в blocking режиме. | Переключите на `non-blocking` или используйте агентный сбор. |

### Безопасность

- **TLS для удалённых хранилищ**: Используйте HTTPS при отправке логов по сети. Драйверы `syslog`, `splunk` поддерживают TLS-соединения.
- **Токены и секреты**: Не храните токены (Splunk HEC, AWS Credentials) в `daemon.json` в открытом виде. Используйте IAM Roles (AWS) или Docker Secrets.
- **Сетевая изоляция**: Разместите приемники логов в отдельной VLAN или используйте Security Groups для ограничения доступа.
- **Аудит доступа**: Мониторьте, кто изменяет `daemon.json` — это файл глобальных настроек Docker.

### Производительность и масштабирование

| Параметр | Рекомендация |
| :--- | :--- |
| **Режим буфера** | `non-blocking` для production. |
| **Размер буфера** | `4m` (dev), `8m` (prod), `16m` (высокий трафик). |
| **Потребление RAM** | `max-buffer-size` * количество контейнеров с сетевым драйвером. |
| **Количество контейнеров** | Не рекомендуется >200 контейнеров с сетевым драйвером на одном хосте (нагрузка на Docker daemon). |
| **Batch timeout** | Зависит от драйвера: Fluentd (`fluentd-request-timeout`), Loki (`loki-timeout`). |

**Рекомендация по масштабированию**: При >200 контейнеров на хост или требовании fault-tolerance переходите на **[Агентный сбор логов Docker](./docker_agent_based_logging.md)**.

### Ссылки на смежные темы

*   **[Обзор системы логирования в Docker](./docker_logging_drivers_overview.md)** — база и сравнение методов.
*   **[Настройка лог-драйвера Grafana Loki для Docker](./loki_logging_driver_setup.md)** — детальный разбор драйвера Loki.
*   **[Агентный сбор логов Docker](./docker_agent_based_logging.md)** — альтернативный, более надежный подход.
*   **[Управление ротацией логов Docker](./docker_log_rotation.md)** — защита диска от переполнения.
*   **[rsyslog: Фильтрация и пересылка](../../Linux/SystemAdministration/Logging/rsyslog.md)** — настройка приемника для драйвера syslog.

**Глубокое изучение:**
- **[Audit Logging](../../Security/audit_and_compliance_overview.md)** — аудит для compliance. В Docker: `auditd` для мониторинга `/var/run/docker.sock`, логирование `docker events` в централизованное хранилище, трекинг изменений `daemon.json`.
- **[Structured Logging](../../Concepts/Observability_and_Monitoring/logs_deep_dive.md)** — Correlation IDs. В Docker: `log-driver` может добавлять labels/env через `--log-opt tag`, но для correlation ID приложение должно генерировать `request_id` на stdout.
