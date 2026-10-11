# Настройка лог-драйвера Grafana Loki для Docker

**Актуально для:** Docker Engine 29.x, Loki Docker Driver 3.7.x

## Определения

**Драйвер логирования Loki (Loki Docker Driver)** — это плагин для Docker Engine, разработанный Grafana Labs. Он позволяет отправлять логи напрямую из контейнеров в [Grafana Loki](../../Loki/loki_overview.md), минуя необходимость развертывания промежуточных агентов (например, Alloy или Promtail) на каждом хосте.

## Предпосылки

- **Docker Engine** версии 29.x (актуальная стабильная версия на 2026 год) или выше (минимальная поддерживаемая версия — 20.10 для Dual Logging и стабильной работы плагинов)
- **Docker CLI** с правами root или членство в группе `docker` для установки плагинов и редактирования `/etc/docker/daemon.json`
- **Доступ к реестру Docker Hub** для загрузки образа плагина
- **Доступ к серверу Loki** по сети (HTTP/HTTPS) из каждого Docker-хоста
- **Открытый порт** (по умолчанию `3100`) на сервере Loki и доступ к нему из сети хостов (Firewall/Security Groups)

**Проверка версии Docker:**
```bash
docker version --format '{{.Server.Version}}'
# → 29.x.x (актуальная стабильная версия на 2026 год)
```

## Базовые концепции

### Архитектура и механизм работы

Данное решение реализует модель прямой отправки логов (Push-модель) на уровне рантайма контейнеров.

**Схема потока данных:**
`Приложение → STDOUT/STDERR → Docker Engine → loki-docker-driver → HTTP/HTTPS → Loki`

**Ключевые особенности:**
*   **Простота внедрения**: Не требует управления жизненным циклом дополнительных контейнеров-агентов.
*   **Поддержка Dual Logging**: В отличие от драйверов `syslog` или `gelf` (в старых версиях), Loki-драйвер поддерживает чтение логов через стандартную команду `docker logs` при сохранении локальной копии (механизм Dual Logging). Подробнее: **[Управление ротацией логов Docker](./docker_log_rotation.md)**.
*   **Режимы работы**:
    *   **Blocking (по умолчанию)**: Гарантирует доставку, но при недоступности Loki или сетевых проблемах приложение может "зависнуть" при попытке записи в лог.
    *   **Non-blocking**: Рекомендуется для production. Логи буферизируются в кольцевом буфере в оперативной памяти хоста; при переполнении буфера старые записи отбрасываются (принцип FIFO), обеспечивая стабильность приложения ценой частичной потери логов.

**Важно о Dual Logging:** Механизм Dual Logging по умолчанию активен с Docker 20.10+. Loki-драйвер поддерживает его, что означает: даже при использовании удалённого драйвера команда `docker logs <container>` продолжает работать, читая локальную кэширующую копию логов. Локальный кэш автоматически ротируется и не занимает много места на диске.

### Управление версиями плагина

Плагин Loki Docker Driver поставляется в виде Docker Plugin (не контейнера). Версия плагина может не совпадать с версией самого Loki. Рекомендуется:

1.  Использовать **фиксированные теги** (например, `3.7.8`), а не `latest`, для предсказуемости.
2.  Проверять доступные версии на [Docker Hub](https://hub.docker.com/r/grafana/loki-docker-driver/tags) или в [GitHub Releases](https://github.com/grafana/loki-docker-driver/releases).
3.  При обновлении: сначала отключить плагин на всех хостах, затем обновить, затем включить обратно (rolling update).

## Практические сценарии

### Шаг 1: Установка плагина

Плагин устанавливается как расширение Docker Engine на каждом хосте.

```bash
# Установка плагина с псевдонимом 'loki'
docker plugin install grafana/loki-docker-driver:3.7.8 --alias loki --grant-all-permissions
```
*   `grafana/loki-docker-driver:3.7.8`: Рекомендуется использовать фиксированную версию.
*   `--alias loki`: Позволяет обращаться к драйверу по короткому имени в конфигурациях.
*   `--grant-all-permissions`: Предоставляет плагину все необходимые разрешения (сетевой доступ, доступ к сокетам).

**Проверка статуса:**
```bash
docker plugin ls
# → ID            NAME          DESCRIPTION           ENABLED
# → <id>          loki:latest   Loki Logging Driver   true
```

**Проверка конфигурации плагина:**
```bash
docker plugin inspect loki --format '{{.Settings.Env}}'
# → [LOKI_URL=...]
```

**Отключение и удаление (при необходимости):**
```bash
docker plugin disable loki
docker plugin rm loki
```

### Шаг 2: Глобальная конфигурация (`daemon.json`)

Обеспечивает автоматическую отправку логов всех новых контейнеров в централизованную систему.

**Файл `/etc/docker/daemon.json`:**
```json
{
  "log-driver": "loki",
  "log-opts": {
    "loki-url": "http://loki.example.com:3100/loki/api/v1/push",
    "loki-batch-size": "400000",
    "loki-batch-wait": "1s",
    "loki-retries": "3",
    "loki-max-backoff": "5m",
    "loki-min-backoff": "500ms",
    "mode": "non-blocking",
    "max-buffer-size": "10m",
    "loki-external-labels": "env=prod,cluster=main",
    "loki-timeout": "10s"
  }
}
```
*   **Безопасность**: Если Loki требует аутентификации, используйте формат `http://user:password@loki.example.com:3100/...` или параметры `loki-auth-basic-*`.
*   **Буфер**: `max-buffer-size: 10m` — рекомендуется для production. При недоступности Loki логи будут буферизироваться в памяти до 10 МБ, после чего старые записи начнут отбрасываться.

**Применение настроек:**
```bash
sudo systemctl restart docker
```
**Важно:** Изменения коснутся только **новых** контейнеров. Существующие контейнеры нужно пересоздать:
```bash
docker-compose up -d --force-recreate
```

**Валидация после применения:**
```bash
docker info --format '{{.LoggingDriver}}'
# → loki

docker info --format '{{.LogOpts}}'
# → map[loki-url:http://loki.example.com:3100/loki/api/v1/push ...]
```

### Шаг 3: Настройка через Docker Compose

Позволяет гибко управлять метками и параметрами для конкретных сервисов.

```yaml
services:
  web-app:
    image: nginx:1.30
    logging:
      driver: "loki"
      options:
        loki-url: "https://loki.example.com/loki/api/v1/push"
        loki-external-labels: "project=ecommerce,service={{.Name}}"
        loki-retries: "5"
        mode: "non-blocking"
        loki-tls-ca-file: "/etc/docker/certs/ca.crt"
```

**YAML-якорь для DRY-конфигурации (рекомендуется для проектов с несколькими сервисами):**
```yaml
x-loki-logging: &loki-logging
  driver: "loki"
  options:
    loki-url: "http://loki:3100/loki/api/v1/push"
    loki-external-labels: "project=myapp,env=prod,service={{.Name}}"
    loki-retries: "3"
    loki-max-backoff: "5m"
    mode: "non-blocking"
    max-buffer-size: "8m"

services:
  api:
    image: my-api:latest
    logging: *loki-logging

  worker:
    image: my-worker:latest
    logging: *loki-logging
```

**Валидация для конкретного контейнера:**
```bash
docker inspect --format '{{.HostConfig.LogConfig}}' web-app
# → {loki map[loki-url:https://loki.example.com/loki/api/v1/push ...]}
```

### Шаг 4: Проверка и чтение логов

**1. Проверка в Grafana Explore:**
*   Выберите источник данных **Loki**.
*   Запрос: `{container_name="web-app"}` или `{project="ecommerce"}`.

**2. Использование CLI:**
Благодаря Dual Logging, локальный доступ сохраняется:
```bash
docker logs -f web-app
docker logs --tail 100 web-app
docker logs --since 1h web-app
```

**3. Проверка отправки через системный лог Docker:**
```bash
journalctl -u docker --since "10 minutes ago" | grep -i loki
# → [plugin] loki-drivers.go:... loki: push to Loki completed
```

**4. Проверка доступности Loki API:**
```bash
curl -s http://loki.example.com:3100/ready
# → ready

curl -s http://loki.example.com:3100/loki/api/v1/labels | jq .
# → {"status":"success","data":["__name__","container_name","project"]}
```

### Шаг 5: Аутентификация и TLS

**Basic Auth:**
```json
{
  "log-driver": "loki",
  "log-opts": {
    "loki-url": "http://loki.example.com:3100/loki/api/v1/push",
    "loki-auth-basic-user": "loki-user",
    "loki-auth-basic-password": "secure-password-here"
  }
}
```

**TLS с собственным CA-сертификатом:**
```json
{
  "log-driver": "loki",
  "log-opts": {
    "loki-url": "https://loki.example.com:3100/loki/api/v1/push",
    "loki-tls-ca-file": "/etc/docker/certs/loki-ca.crt",
    "loki-tls-insecure-skip-verify": "false"
  }
}
```

**TLS без проверки сертификата (только для dev/test):**
```json
{
  "log-opts": {
    "loki-url": "https://loki.example.com:3100/loki/api/v1/push",
    "loki-tls-insecure-skip-verify": "true"
  }
}
```

## Pipeline stages и обработка логов

Параметры `loki-pipeline-stages` и `loki-pipeline-stage-file` позволяют обрабатывать логи на уровне драйвера перед отправкой в Loki: парсить строки, извлекать метки, маскировать чувствительные данные.

**Важно:** `loki-pipeline-stage-file` и `loki-pipeline-stages` взаимно исключают друг друга. Используйте только один из вариантов.

### Inline pipeline stages (`loki-pipeline-stages`)

Конфигурация передаётся как строка в формате YAML. Удобно для простых правил.

```json
{
  "log-driver": "loki",
  "log-opts": {
    "loki-url": "http://loki:3100/loki/api/v1/push",
    "loki-pipeline-stages": "- regex:\n    expression: '(level|lvl|severity)=(?P<level>\\w+)'\n- labels:\n    level:"
  }
}
```

### Pipeline stages через файл (`loki-pipeline-stage-file`)

Для сложных конфигураций используйте отдельный YAML-файл, смонтированный в корневую ФС драйвера.

```yaml
# /etc/loki/pipeline.yaml
- regex:
    expression: '(level|lvl|severity)=(?P<level>\\w+)'
- labels:
    level:
- timestamp:
    source: timestamp
    format: RFC3339
```

```json
{
  "log-driver": "loki",
  "log-opts": {
    "loki-url": "http://loki:3100/loki/api/v1/push",
    "loki-pipeline-stage-file": "/etc/loki/pipeline.yaml"
  }
}
```

**Доступные stage:** `regex`, `json`, `logfmt`, `labels`, `timestamp`, `match`, `outly`, `cri`, `docker`, `replace`, `template`, `metrics`. Полный список: [Pipeline stages in Loki](https://grafana.com/docs/loki/latest/send-data/docker-driver/configuration/#pipeline-stages).

## Relabeling меток контейнера

Параметр `loki-relabel-config` позволяет переименовывать или удалять метки, автоматически добавляемые драйвером (`compose_project`, `compose_service`, `swarm_stack`, `swarm_service`, `host`), без изменения конфигурации приложения.

```json
{
  "log-driver": "loki",
  "log-opts": {
    "loki-url": "http://loki:3100/loki/api/v1/push",
    "loki-relabel-config": "- action: labelmap\n  regex: swarm_stack\n  replacement: namespace\n- action: labelmap\n  regex: swarm_(service)\n  replacement: $1\n- action: drop\n  regex: swarm_node"
  }
}
```

**Поддерживаемые действия:** `replace`, `keep`, `drop`, `hashmod`, `labelmap`, `labeldrop`, `labelkeep`. Синтаксис соответствует [Prometheus relabeling config](https://prometheus.com/docs/prometheus/latest/configuration/configuration/#relabel_config).

**Важно:** Relabeling применяется один раз при старте контейнера, к метаданным контейнера. Для обработки содержимого строк лога используйте pipeline stages.

## Управление локальными JSON-логами

Драйвер Loki создаёт локальные JSON-файлы логов (как `json-file` драйвер), чтобы команда `docker logs` продолжала работать. Параметры `no-file`, `keep-file`, `max-size`, `max-file` управляют этим поведением.

```json
{
  "log-driver": "loki",
  "log-opts": {
    "loki-url": "http://loki:3100/loki/api/v1/push",
    "no-file": "false",
    "keep-file": "false",
    "max-size": "10m",
    "max-file": "3"
  }
}
```

| Режим | `no-file` | `keep-file` | JSON-файл создаётся? | Удаляется при остановке? | `docker logs` работает? |
| :--- | :--- | :--- | :--- | :--- | :--- |
| Стандартный | `false` | `false` | Да | Да | Да |
| Сохранять логи | `false` | `true` | Да | Нет | Да |
| Без локальных файлов | `true` | — | Нет | — | Нет |

**Рекомендации:**
- **Production с аудитом**: `no-file=false`, `keep-file=true`, `max-size=10m`, `max-file=3` — логи сохраняются после остановки контейнера.
- **Высокая плотность**: `no-file=true` — отключает создание файлов, экономя диск, но `docker logs` не работает.
- **Debug**: `no-file=false`, `max-size=50m`, `max-file=5` — увеличивает локальный буфер для отладки.

## Обновление плагина

Плагины Docker требуют rolling update: отключение → обновление → включение.

```bash
# 1. Отключить плагин (принудительно, если есть активные контейнеры)
docker plugin disable loki --force

# 2. Обновить (указать нужную архитектуру)
docker plugin upgrade loki grafana/loki-docker-driver:3.7.8-amd64 --grant-all-permissions

# 3. Включить обратно
docker plugin enable loki

# 4. Перезапустить Docker
sudo systemctl restart docker
```

**Валидация после обновления:**
```bash
docker plugin ls
# → ID            NAME          DESCRIPTION           ENABLED
# → <id>          loki:latest   Loki Logging Driver   true

docker info --format '{{.LoggingDriver}}'
# → loki
```

## Дополнительная информация

### Полная таблица параметров `log-opts`

| Параметр | Описание | Значение по умолчанию | Пример |
| :--- | :--- | :--- | :--- |
| `loki-url` | Эндпоинт Loki для отправки логов. **Обязателен.** | — | `http://loki:3100/loki/api/v1/push` |
| `loki-external-labels` | Пользовательские метки. Поддерживают шаблоны Go (`{{.Name}}`, `{{.ImageName}}`, `{{.ID}}`). Разделитель меток: запятая. Если задано, заменяет значение по умолчанию `container_name={{.Name}}`. | `container_name={{.Name}}` | `"env=prod,service={{.Name}}"` |
| `loki-batch-size` | Максимальный размер пакета (в байтах) перед отправкой в Loki. | `1048576` (~1 МБ) | `"400000"` |
| `loki-batch-wait` | Максимальное время ожидания перед отправкой неполного пакета. | `1s` | `"1s"`, `"500ms"` |
| `loki-retries` | Количество попыток повторной отправки при ошибке. `0` означает бесконечные повторы. | `10` | `"3"`, `"5"` |
| `loki-max-backoff` | Максимальный интервал между повторными попытками (exponential backoff). | `5m` | `"10s"`, `"30s"` |
| `loki-min-backoff` | Минимальный интервал между повторными попытками. | `500ms` | `"1s"` |
| `loki-timeout` | Таймаут HTTP-запроса к Loki. | `10s` | `"15s"` |
| `loki-auth-basic-user` | Имя пользователя для Basic Auth. | пусто | `"admin"` |
| `loki-auth-basic-password` | Пароль для Basic Auth. | пусто | `"secret"` |
| `loki-tls-ca-file` | Путь к CA-сертификату для HTTPS. | пусто | `"/etc/docker/certs/ca.crt"` |
| `loki-tls-insecure-skip-verify` | Отключение проверки сертификата TLS. **Не используйте в production.** | `false` | `"true"` |
| `mode` | Режим буферизации: `blocking` или `non-blocking`. | `blocking` | `"non-blocking"` |
| `max-buffer-size` | Размер кольцевого буфера в памяти (в non-blocking режиме). | `1m` | `"10m"`, `"16m"` |
| `loki-pipeline-stage-file` | Путь к файлу с конфигурацией pipeline stages. Несовместимо с `loki-pipeline-stages`. | пусто | `"/etc/loki/pipeline.yaml"` |
| `loki-pipeline-stages` | Конфигурация pipeline stages в виде строки (YAML). Позволяет парсить логи и извлекать метки. | пусто | `"- regex:\\n    expression: 'level=(?P<level>\\\\w+)'\\n- labels:\\n    level:"` |
| `loki-relabel-config` | Конфигурация Prometheus relabeling в виде строки (YAML) для переименования лейблов контейнера. | пусто | `"- action: labelmap\\n    regex: swarm_stack\\n    replacement: namespace"` |
| `loki-tenant-id` | Идентификатор тенанта для multi-tenant режима Loki (HTTP-заголовок `X-Scope-OrgID`). | пусто | `"team-frontend"` |
| `loki-tls-cert-file` | Путь к клиентскому сертификату для mTLS. | пусто | `"/etc/docker/certs/client.crt"` |
| `loki-tls-key-file` | Путь к приватному ключу клиентского сертификата. | пусто | `"/etc/docker/certs/client.key"` |
| `loki-tls-server-name` | Имя сервера для валидации сертификата (SNI). | пусто | `"loki.example.com"` |
| `loki-proxy-url` | URL прокси для подключения к Loki. | пусто | `"http://proxy.internal:8080"` |
| `no-file` | Отключение создания локальных JSON-файлов логов. `true` отключает `docker logs` для контейнера. | `false` | `"true"` |
| `keep-file` | Сохранять JSON-файл логов после остановки контейнера. Не действует при `no-file=true`. | `false` | `"true"` |
| `max-size` | Максимальный размер лог-файла перед ротацией (требует `max-file`). Единицы: `k`, `m`, `g`. | `-1` (неограниченно) | `"10m"` |
| `max-file` | Максимальное количество ротированных лог-файлов. Старые файлы удаляются. Действует только при `max-size`. | `1` | `"3"` |
| `labels` | Список ключей лейблов контейнера, которые нужно включить в сообщение лога. | пусто | `"com.docker.compose.service,com.docker.compose.project"` |
| `env` | Список ключей переменных окружения, которые нужно включить в сообщение лога. | пусто | `"APP_VERSION,ENV"` |
| `env-regex` | Регулярное выражение для выбора переменных окружения (приоритет над `env` при коллизии). | пусто | `"APP_.*"` |

**Важно:** Все значения в `daemon.json` должны быть строками (в кавычках), включая числовые и булевы. Булевы значения принимают: `"1"`, `"t"`, `"T"`, `"true"`, `"TRUE"`, `"True"` (истина) и `"0"`, `"f"`, `"F"`, `"false"`, `"FALSE"`, `"False"` (ложь).

### Типичные ошибки и решения

| Ошибка / Симптом | Возможная причина | Решение |
| :--- | :--- | :--- |
| **`Cannot connect to the Docker daemon`** | Docker daemon не запущен или нет прав. | `sudo systemctl start docker` или добавьте пользователя в группу `docker`. |
| **`plugin "loki" not found`** | Плагин не установлен или отключён. | `docker plugin ls` — проверьте статус. При необходимости установите (Шаг 1). |
| **`Error: No such plugin: loki`** | Попытка использовать драйвер `loki` до установки плагина. | Установите плагин (Шаг 1) перед настройкой `daemon.json`. |
| **Логи не доходят до Loki, нет ошибок в Docker** | Плагин работает в silent-режиме. | Проверьте `journalctl -u docker | grep loki`. Частые причины: неверный URL, файрвол блокирует порт 3100, ошибки аутентификации. |
| **`Entry timestamp too old` / `too far behind` / `too new`** | Часы источника и сервера Loki рассинхронизированы. Пороги (default): `too old` — запись старше `reject_old_samples_max_age` (168h / 7 суток); `too far behind` — старше `max_chunk_age/2` (~1ч) относительно последней записи в потоке; `too new` — метка в будущем дальше `creation_grace_period` (10 мин). | Настройте NTP (Chrony/systemd-timesyncd) на **всех** узлах; для отложенной доставки поднимите `reject_old_samples_max_age` (см. [container_time_sync.md](../Docker_troubleshooting/container_time_sync.md), Сценарий 6). |
| **Контейнер "зависает" при записи логов** | Режим `blocking` при недоступном Loki. | Переключите на `non-blocking`: `"mode": "non-blocking", "max-buffer-size": "10m"`. |
| **Логи обрезаются / теряются** | Размер буфера слишком мал, Loki недоступен слишком долго. | Увеличьте `max-buffer-size` или перейдите на агентный сбор (**[docker_agent_based_logging.md](./docker_agent_based_logging.md)**) с буферизацией на диске. |
| **`http: server gave HTTP response to HTTPS client`** | Loki доступен по HTTP, а URL указан с HTTPS (или наоборот). | Проверьте протокол в `loki-url`. Для dev: `http://`, для prod с TLS: `https://`. |
| **Ошибка 401 Unauthorized** | Неверные учётные данные Basic Auth. | Проверьте `loki-auth-basic-user` и `loki-auth-basic-password`. Убедитесь, что пользователь существует в конфигурации Loki. |
| **Ошибка 429 Too Many Requests** | Loki отклоняет из-за превышения лимитов ingestion rate. | Увеличьте `ingestion_rate_mb` и `ingestion_burst_size_mb` в конфигурации Loki (параметры `limits_config`). |
| **`docker logs` не работает** | Включён `no-file=true` или локальный JSON-файл удалён (`keep-file=false`). | Пересоздайте контейнер с `no-file=false` и/или `keep-file=true`. |
| **Ошибка синтаксиса pipeline stages** | Неверный YAML в `loki-pipeline-stages` или `loki-pipeline-stage-file`. | Проверьте отступы и кавычки. Логи драйвера: `journalctl -u docker | grep -i pipeline`. |
| **Метки не применяются** | `loki-external-labels` переопределяет дефолтные метки, включая `container_name`. | Добавьте `container_name={{.Name}}` явно в `loki-external-labels`. |

### Производительность и оптимизация

**Рекомендуемые профили:**

| Сценарий | `mode` | `max-buffer-size` | `loki-batch-size` | `loki-retries` | `loki-timeout` |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **Разработка** | `blocking` | `4m` | `200000` | `1` | `10s` |
| **Продакшн (умеренный)** | `non-blocking` | `8m` | `400000` | `3` | `10s` |
| **Продакшн (высокий трафик)** | `non-blocking` | `16m` | `1000000` | `5` | `15s` |
| **Критичные сервисы (аудит)** | `blocking` | `16m` | `500000` | `5` | `30s` |

**Влияние на производительность:**
*   **Blocking-режим**: Добавляет задержку ~1-10 мс на каждую запись лога (зависит от сети до Loki). При недоступном Loki приложение блокируется полностью.
*   **Non-blocking-режим**: Добавляет минимальную задержку (~0.1 мс). Потребление RAM: `max-buffer-size` * количество контейнеров с Loki-драйвером.

### Ограничения и известные проблемы

1.  **Docker Plugin Manager**: Плагины управляются через `docker plugin` API. Их нельзя обновить без отключения — required rolling update.
2.  **Multi-tenancy**: Параметр `loki-tenant-id` задаётся глобально или per-контейнер. Невозможно динамически менять tenant для уже запущенного контейнера.
3.  **Шаблоны Go в `loki-external-labels`**: Поддерживаются только `{{.Name}}`, `{{.ImageName}}`, `{{.ID}}`. Другие шаблоны (например, `{{.Env}}`) не поддерживаются драйвером — используйте статичные метки.
4.  **Размер строк**: Loki по умолчанию ограничивает размер строки лога (~256 КБ в Loki 3.x). Очень длинные строки (например, stack traces) могут быть отброшены. Настройте `max_line_size` в конфигурации Loki.
5.  **Драйвер фиксируется при создании контейнера**: Невозможно изменить `log-driver` или `log-opts` для уже запущенного контейнера. Требуется пересоздание.
6.  **Non-blocking и потеря данных**: При переполнении буфера (если Loki недоступен слишком долго) логи **отбрасываются без уведомления**. Для аудит-требований используйте `blocking` режим или агентный сбор с буферизацией на диске.
7.  **Docker Desktop (macOS/Windows)**: Плагины работают через виртуальную машину. Настройки `daemon.json` хоста не применяются напрямую. Используйте UI Docker Desktop (Settings - Docker Engine) или `~/.docker/daemon.json`.
8.  **Булевы значения**: В `daemon.json` все значения — строки. Для `true`/`false` используйте только `"true"`/`"false"` (или другие accepted values: `"1"`, `"t"`, `"T"`, `"TRUE"`, `"True"`, `"0"`, `"f"`, `"F"`, `"FALSE"`, `"False"`).
9.  **`no-file=true` отключает `docker logs`**: При отключении локальных JSON-файлов команда `docker logs` перестаёт работать для контейнера. Для восстановления нужно пересоздать контейнер с `no-file=false`.
10. **Pipeline stages и производительность**: Сложные pipeline stages (regex, json parsing) добавляют задержку на каждую строку лога. Для высоконагруженных систем (10k+ логов/сек) тестируйте конфигурацию под нагрузкой.
11. **`loki-batch-size` в байтах**: Параметр указывает размер в байтах, а не в записях. Значение `400` (как в устаревших примерах) означает всего 400 байт — это слишком мало для production. Используйте `400000` (400 КБ) или `1048576` (1 МБ).

### Лучшие практики

1.  **Всегда используйте `non-blocking`** для production — это гарантирует стабильность приложений даже при проблемах с Loki.
2.  **Настройте `max-buffer-size`**: `8m`-`16m` для production, `4m` для dev/test.
3.  **Используйте фиксированные версии плагина** (например, `3.7.8`), а не `latest`.
4.  **Настройте `loki-retries`**: минимум `3` для production, чтобы компенсировать кратковременные сетевые сбои.
5.  **Используйте YAML-якоря** в Compose для дублирования конфигурации логирования.
6.  **Настройте аутентификацию** для production: Basic Auth или TLS с `loki-tls-ca-file`.
7.  **Мониторьте размер логов**: регулярно проверяйте рост логов через `docker system df -v` и настраивайте ротацию для локального кэша Dual Logging. Подробнее: **[Управление ротацией логов Docker](./docker_log_rotation.md)**.
8.  **Для критичных аудит-систем** используйте агентный сбор (**[docker_agent_based_logging.md](./docker_agent_based_logging.md)**) с буферизацией на диске вместо драйвера Loki.
9.  **Используйте pipeline stages** для извлечения меток и обогащения логов на стороне драйвера, если вам не нужна полная пайплайн-гибкость Alloy.
10. **Настройте `no-file` и `max-size`** для управления локальными JSON-логами: `no-file=false`, `max-size=10m`, `max-file=3` для production; `no-file=true` только если `docker logs` не требуется.
11. **Не используйте `loki-batch-size` ниже 100000** (100 КБ) — слишком малые пакеты увеличивают нагрузку на Loki и сеть.
12. **Тестируйте обновления плагина** в staging перед rolling update в production: отключение плагина прерывает отправку логов для активных контейнеров.

### Сравнение с агентным подходом

| Критерий | Loki Docker Driver | Alloy / Promtail (Агент) |
| :--- | :--- | :--- |
| **Сложность** | Низкая (один плагин). | Средняя (нужен конфиг агента). |
| **Производительность** | Высокая (нет лишнего копирования). | Средняя (чтение файлов с диска). |
| **Гибкость (Pipelines)** | Ограниченная (pipeline stages, relabeling). | Максимальная (парсинг JSON, маскирование, преобразования). |
| **Надежность** | Зависит от Docker Engine. | Высокая (буферизация на диске). |
| **Сохранность логов** | Non-blocking: потеря при переполнении RAM. | Высокая: буфер на диске переживает перезагрузки. |
| **Multiline** | Не поддерживается на уровне драйвера. | Полная поддержка (склейка stack traces). |

**Рекомендация:** Используйте драйвер для простых инфраструктур и быстрой отладки. Для сложных enterprise-решений с необходимостью глубокой обработки логов (парсинг логов приложений, маскирование PII) переходите на **[агентный сбор](./docker_agent_based_logging.md)**.

### Ссылки на смежные темы

*   **[Обзор системы логирования в Docker](./docker_logging_drivers_overview.md)**
*   **[Grafana Loki: обзор системы](../../Loki/loki_overview.md)**
*   **[Настройка Loki Stack через Docker Compose](../../Loki/Docker_Compose/loki_docker_compose_setup.md)**
*   **[Централизованное логирование Docker: Лог-драйверы](./docker_centralized_logging.md)**
*   **[Команда docker logs: справочник](./docker_logs_cli.md)** — Dual Logging и локальный кэш драйвера Loki.
