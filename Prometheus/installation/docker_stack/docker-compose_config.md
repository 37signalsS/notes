# Конфигурация Docker Compose для стека мониторинга

## Определения

**Docker Compose для мониторинга** — это декларативный способ описания инфраструктуры наблюдения (Prometheus, Grafana, Alertmanager и экспортеры) в виде единого стека. Использование Compose обеспечивает повторяемость развёртывания, изоляцию компонентов и простоту управления жизненным циклом (запуск, обновление, масштабирование).

> **См. также:** [Обзор Docker Stack](./overview.md), [Docker Compose basics](../../../Docker/Docker_compose/docker_compose_file_example.md).

## Основные концепции

### Архитектура и сетевое взаимодействие

Все компоненты стека объединяются в выделенную bridge-сеть. Это обеспечивает изоляцию от других контейнеров на хосте и позволяет использовать встроенный DNS Docker для обращения к сервисам по их именам (например, `prometheus:9090`).

### Персистентность и тома

Для надежного хранения данных используются именованные тома (Named Volumes), которые сохраняют состояние TSDB Prometheus и базу данных Grafana даже после удаления контейнеров. Конфигурационные файлы монтируются через Bind Mounts в режиме `read-only`.

### Актуальные версии образов (Август 2026)

| Компонент | Образ | Версия | Примечание |
|---|---|---|---|
| **Prometheus** | `prom/prometheus` | v3.13.1 | Поддержка OTLP и Auto-tuning |
| **Grafana** | `grafana/grafana` | v13.1.1 | Современный UI и Alloy-интеграция |
| **Alertmanager** | `prom/alertmanager` | v0.33.1 | API v2, расширенная маршрутизация |
| **Node Exporter** | `prom/node-exporter` | v1.12.1 | Метрики хоста (Linux/UNIX) |
| **cAdvisor** | `ghcr.io/google/cadvisor` | v0.60.5 | Метрики ресурсов контейнеров |

### Структура файла Compose

`compose.yml` — декларативный YAML-файл, описывающий сервисы, сети, тома и конфиги стека. Вместе с необязательным `compose.override.yml` он формирует итоговую конфигурацию. Для крупных стеков Compose v2.20+ поддерживает директиву `include` для разделения конфигурации на логические части:

```yaml
# compose.yml
include:
  - path: ./compose.prometheus.yml
  - path: ./compose.grafana.yml
  - path: ./compose.alertmanager.yml
```

Файл `.env` в той же директории автоматически подставляется при запуске `docker compose`. Переменные из `.env` доступны в `compose.yml` через интерполяцию `${VAR:-default}`.

### Зависимости между сервисами и порядок запуска

Docker Compose запускает сервисы параллельно. Для управления порядком используется `depends_on` с условием `service_healthy`. Это гарантирует, что Prometheus стартует только после готовности Node Exporter и Alertmanager. Важно: `depends_on` без `condition` проверяет только факт создания контейнера, а не его работоспособность.

Для сложных сценариев инициализации используйте вспомогательные скрипты-ожидания (`wait-for-it.sh`, `dockerize`) или проверки readiness внутри приложения.

### Сети, DNS и разрешение имён

По умолчанию Compose создаёт bridge-сеть с именем проекта. Сервисы доступны друг другу по DNS-именам, объявленным в `container_name` или автоматически сгенерированным именем `<project>_<service>_1`.

| Адрес | Назначение |
|---|---|
| `prometheus:9090` | Обращение к сервису Prometheus из другого контейнера |
| `localhost:9090` | Всегда указывает на сам контейнер; не используется для обращения к другим сервисам Compose |
| `host.docker.internal` | Хост-машина; требует `extra_hosts` или `network_mode: host` |
| `<service>:<port>` | Стандартное обращение к любому сервису в сети |

Docker кэширует DNS-записи на время TTL (по умолчанию 60 секунд). При изменении состава сервисов кэш может содержать устаревшие адреса. Используйте `docker compose up -d --force-recreate` или дождитесь истечения TTL.

### Тома, bind mounts и опции монтирования

| Тип монтирования | Использование | Особенности |
|---|---|---|
| Named Volume | Данные TSDB, БД Grafana, Alertmanager state | Управляются Docker, сохраняются после `down` без `-v` |
| Bind Mount | Конфигурационные файлы, provisioning | Прямое отображение хостовой директории |
| tmpfs | Временные данные, WAL буферы | Хранится в памяти, не персистит после остановки |

Опции монтирования:
- `:ro` — read-only; запрещает запись в контейнер
- `:rw` — read-write; значение по умолчанию
- `:z` / `:Z` — автоматическая пометка для SELinux (shared/private)
- `:nocopy` — отключает копирование данных из тома при первом монтировании
- `:bind` / `:volume` — явное указание типа монтирования

### Переменные окружения, .env и секреты

Compose автоматически загружает `.env` из корня проекта. Переменные подставляются в `environment:` через интерполяцию `${VAR}` или `${VAR:-default}`.

Для секретных данных (пароли, токены) используйте:
- Docker Secrets (Swarm mode): монтируются в `/run/secrets/<name>` как файлы
- Внешние файлы через bind mounts с правами `:ro`
- Внешние менеджеры секретов (Vault, Doppler) с агентом на хосте

Никогда не коммитьте `.env` с production-секретами в репозиторий.

### Ресурсы, лимиты и restart-политики

```yaml
deploy:
  resources:
    limits:
      cpus: '1.5'
      memory: 2G
    reservations:
      cpus: '0.5'
      memory: 512M
restart: unless-stopped
```

Политики перезапуска:
- `no` — не перезапускать (по умолчанию)
- `always` — всегда перезапускать
- `on-failure` — при ненулевом коде завершения
- `unless-stopped` — перезапускать, кроме ручной остановки

`stop_grace_period` задаёт время ожидания graceful shutdown перед SIGKILL. Для Prometheus рекомендуется 30–60 секунд для завершения WAL write-ahead.

### Безопасность контейнеров

Минимизация поверхности атаки достигается несколькими механизмами:

| Директива | Назначение |
|---|---|
| `user: "65534:65534"` | Запуск от непривилегированного пользователя |
| `read_only: true` | Запрет записи в корневую ФС контейнера |
| `tmpfs: ["/tmp:noexec,nosuid,size=1g"]` | Временные данные в памяти; `noexec` блокирует выполнение |
| `cap_drop: [ALL]` | Отзыв всех Linux capabilities |
| `cap_add: [NET_BIND_SERVICE]` | Выборочное добавление только необходимых прав |
| `security_opt: [no-new-privileges:true]` | Запрет повышения привилегий |
| `security_opt: [seccomp:default]` | Стандартный профиль seccomp; для специализированных контейнеров может потребоваться кастомный |
| `privileged: false` | Отключение привилегированного режима |
| `pid: host` | Общий namespace PID с хостом; требуется для node-exporter |

### Управление логами

Без ограничений логи Docker могут заполнить всё дисковое пространство. Конфигурация логирования задаётся на уровне сервиса или глобально через `logging:`:

```yaml
services:
  prometheus:
    logging:
      driver: json-file
      options:
        max-size: "10m"
        max-file: "3"
        compress: "false"
```

Доступные драйверы: `json-file` (по умолчанию), `local`, `syslog`, `journald`, `fluentd`, `gelf`, `awslogs`, `splunk`. Для production рекомендуется `json-file` или `local` с ограничением размера и количества файлов.

## Практические сценарии

### Эталонный `compose.yml` (Production Ready)

```yaml
services:
  prometheus:
    image: prom/prometheus:v3.13.1
    container_name: monitoring-prometheus
    restart: unless-stopped
    user: "65534:65534"
    security_opt:
      - no-new-privileges:true
      - seccomp:default
    cap_drop:
      - ALL
    read_only: true
    tmpfs:
      - /tmp:noexec,nosuid,size=1g
    command:
      - '--config.file=/etc/prometheus/prometheus.yml'
      - '--storage.tsdb.path=/prometheus'
      - '--storage.tsdb.retention.time=${PROMETHEUS_RETENTION:-30d}'
      - '--web.enable-lifecycle'
      - '--web.enable-otlp-receiver'
      - '--auto-gomemlimit'
      - '--auto-gomaxprocs'
    volumes:
      - ./prometheus/prometheus.yml:/etc/prometheus/prometheus.yml:ro
      - ./prometheus/web-config.yml:/etc/prometheus/web-config.yml:ro
      - prometheus_data:/prometheus
    ports:
      - "127.0.0.1:9090:9090"
    healthcheck:
      test: ["CMD", "wget", "--no-verbose", "--tries=1", "--spider", "http://localhost:9090/-/healthy"]
      interval: 30s
      timeout: 5s
      retries: 3
      start_period: 60s
    logging: &default-logging
      driver: json-file
      options:
        max-size: "10m"
        max-file: "3"
    deploy:
      resources:
        limits:
          cpus: '1.5'
          memory: 2G
        reservations:
          cpus: '0.5'
          memory: 512M
    networks:
      - monitoring-net
    depends_on:
      node-exporter:
        condition: service_healthy

  alertmanager:
    image: prom/alertmanager:v0.33.1
    container_name: monitoring-alertmanager
    restart: unless-stopped
    user: "65534:65534"
    security_opt:
      - no-new-privileges:true
    cap_drop:
      - ALL
    read_only: true
    tmpfs:
      - /tmp:noexec,nosuid,size=512m
    command:
      - '--config.file=/etc/alertmanager/config.yml'
      - '--storage.path=/alertmanager'
      - '--cluster.listen-address=0.0.0.0:9094'
    volumes:
      - ./alertmanager/config.yml:/etc/alertmanager/config.yml:ro
      - alertmanager_data:/alertmanager
    ports:
      - "127.0.0.1:9093:9093"
      - "127.0.0.1:9094:9094"
    healthcheck:
      test: ["CMD", "wget", "--no-verbose", "--tries=1", "--spider", "http://localhost:9093/-/healthy"]
      interval: 30s
      timeout: 5s
      retries: 3
      start_period: 30s
    logging: *default-logging
    deploy:
      resources:
        limits:
          cpus: '0.5'
          memory: 512M
    networks:
      - monitoring-net

  node-exporter:
    image: prom/node-exporter:v1.12.1
    container_name: monitoring-node-exporter
    restart: unless-stopped
    pid: host
    security_opt:
      - no-new-privileges:true
    volumes:
      - /proc:/host/proc:ro
      - /sys:/host/sys:ro
      - /:/rootfs:ro
    command:
      - '--path.procfs=/host/proc'
      - '--path.sysfs=/host/sys'
      - '--path.rootfs=/rootfs'
    healthcheck:
      test: ["CMD", "wget", "--no-verbose", "--tries=1", "--spider", "http://localhost:9100/metrics"]
      interval: 30s
      timeout: 5s
      retries: 2
    logging: *default-logging
    deploy:
      resources:
        limits:
          cpus: '0.25'
          memory: 256M
    networks:
      - monitoring-net

  cadvisor:
    image: ghcr.io/google/cadvisor:v0.60.5
    container_name: monitoring-cadvisor
    restart: unless-stopped
    security_opt:
      - no-new-privileges:true
    devices:
      - /dev/kmsg
    volumes:
      - /:/rootfs:ro
      - /var/run:/var/run:ro
      - /sys:/sys:ro
      - /var/lib/docker/:/var/lib/docker:ro
      - /dev/disk/:/dev/disk:ro
    healthcheck:
      test: ["CMD", "wget", "--no-verbose", "--tries=1", "--spider", "http://localhost:8080/healthz"]
      interval: 30s
      timeout: 5s
      retries: 2
    logging: *default-logging
    deploy:
      resources:
        limits:
          cpus: '0.5'
          memory: 512M
    networks:
      - monitoring-net

  grafana:
    image: grafana/grafana:13.1.1
    container_name: monitoring-grafana
    restart: unless-stopped
    user: "472:472"
    environment:
      - GF_SECURITY_ADMIN_PASSWORD=${GRAFANA_PASS:-admin}
      - GF_USERS_ALLOW_SIGN_UP=false
      - GF_SERVER_ROOT_URL=http://localhost:3000
    volumes:
      - grafana_data:/var/lib/grafana
      - ./grafana/provisioning:/etc/grafana/provisioning:ro
    ports:
      - "127.0.0.1:3000:3000"
    depends_on:
      prometheus:
        condition: service_healthy
    healthcheck:
      test: ["CMD", "wget", "--no-verbose", "--tries=1", "--spider", "http://localhost:3000/api/health"]
      interval: 30s
      timeout: 5s
      retries: 3
      start_period: 30s
    logging: *default-logging
    deploy:
      resources:
        limits:
          cpus: '0.5'
          memory: 512M
    networks:
      - monitoring-net

volumes:
  prometheus_data:
    driver: local
  alertmanager_data:
    driver: local
  grafana_data:
    driver: local

networks:
  monitoring-net:
    driver: bridge
    ipam:
      config:
        - subnet: 172.28.0.0/16
```

### Пояснения к параметрам конфигурации

- `user: "65534:65534"` — запуск от непривилегированного пользователя (встроенный в образ Prometheus и Alertmanager). Grafana использует UID 472.
- `read_only: true` + `tmpfs` — запрет записи в корневую ФС контейнера; WAL и временные файлы размещаются в tmpfs.
- `cap_drop: [ALL]` — отзыв всех Linux capabilities; повышение привилегий заблокировано.
- `security_opt.no-new-privileges:true` — запрет на повышение привилегий через setuid/setgid.
- `security_opt.seccomp:default` — стандартный профиль seccomp, блокирующий опасные syscall.
- `depends_on.condition: service_healthy` — ожидание готовности зависимых сервисов перед стартом Prometheus (требует healthcheck в зависимых сервисах).
- `127.0.0.1` в `ports` — привязка только к localhost; доступ извне требует reverse proxy или изменения привязки.
- `start_period` — grace period для медленных стартов; healthcheck не учитывается до истечения периода.

### Управление переменными окружения (.env)

Создайте файл `.env` в корне проекта для разделения конфигурации от кода:

```bash
# .env
GRAFANA_PASS=StrongPassword123
PROMETHEUS_RETENTION=30d
ALERTMANAGER_SMTP_HOST=smtp.example.com
ALERTMANAGER_SMTP_PORT=587
ALERTMANAGER_SMTP_USER=alerts@example.com
ALERTMANAGER_SMTP_PASS=SMTP_Password
```

Переменные подставляются в `compose.yml` через `${VAR}` или `${VAR:-default}`. Docker Compose автоматически загружает `.env` при запуске. Для проверки используйте `docker compose config`.

### Локальные переопределения (compose.override.yml)

Файл `compose.override.yml` автоматически применяется при запуске `docker compose up` и предназначен для локальных настроек, которые не должны попадать в репозиторий:

```yaml
# compose.override.yml
services:
  prometheus:
    ports:
      - "127.0.0.1:9090:9090"  # только локальный доступ
    volumes:
      - ./prometheus/debug:/etc/prometheus:ro  # локальная отладочная конфигурация
  grafana:
    ports:
      - "127.0.0.1:3000:3000"
```

Для production-среды используйте `docker compose -f compose.yml -f compose.prod.yml up -d`.

### Множественные файлы Compose

Шаблон для разных окружений:

```bash
# Development
docker compose -f compose.yml -f compose.override.yml up -d

# Production
docker compose -f compose.yml -f compose.prod.yml up -d
```

### Масштабирование сервисов

Для горизонтального масштабирования укажите `deploy.replicas` (Swarm mode) или используйте `docker compose up --scale`:

```bash
# Масштабирование Grafana до 2 реплик (если настроен кластер)
docker compose up -d --scale grafana=2
```

Для Alertmanager HA-кластера используйте `mode: global` в Swarm или несколько реплик с gossip-протоколом.

### Обновление и откат стека

Пошаговая процедура обновления без простоя:

```bash
# 1. Проверка конфигурации перед обновлением
docker compose config

# 2. Обновление образа
docker compose pull

# 3. Пересоздание сервисов с проверкой
docker compose up -d --no-deps --force-recreate prometheus

# 4. Проверка работоспособности
curl -s -o /dev/null -w "%{http_code}" http://localhost:9090/-/healthy
docker compose ps

# 5. Очистка старых образов
docker image prune -f
```

Откат к предыдущей версии:

```bash
# Откат образа Prometheus
docker compose pull prometheus:v3.12.0
docker compose up -d --no-deps prometheus

# Если данные несовместимы, создайте новый том и восстановите снапшот
docker compose down prometheus
docker volume rm monitoring_prometheus_data
docker compose up -d prometheus
```

### Резервное копирование и восстановление

Резервное копирование томов:

```bash
# Создание снапшота Prometheus
docker compose stop prometheus
docker run --rm -v monitoring_prometheus_data:/data -v $(pwd):/backup alpine tar czf /backup/prometheus_backup.tar.gz -C /data ./
docker compose start prometheus

# Создание снапшота Grafana
docker compose stop grafana
docker run --rm -v monitoring_grafana_data:/data -v $(pwd):/backup alpine tar czf /backup/grafana_backup.tar.gz -C /data ./
docker compose start grafana
```

Восстановление:

```bash
# Остановка сервиса
docker compose stop prometheus

# Удаление текущих данных
docker volume rm monitoring_prometheus_data
docker volume create monitoring_prometheus_data

# Восстановление из снапшота
docker run --rm -v monitoring_prometheus_data:/data -v $(pwd):/backup alpine tar xzf /backup/prometheus_backup.tar.gz -C /data
docker compose up -d prometheus
```

### Мониторинг состояния стека

Endpoint'ы для проверки работоспособности:

| Сервис | Endpoint | Ожидаемый ответ |
|---|---|---|
| Prometheus | `http://localhost:9090/-/healthy` | `Prometheus Server is Healthy.` |
| Alertmanager | `http://localhost:9093/-/healthy` | `OK` |
| Grafana | `http://localhost:3000/api/health` | `{"database":"ok"}` |

Проверка через curl:

```bash
# Быстрая проверка всех сервисов
for port in 9090 9093 3000; do
  echo -n "Port $port: "
  curl -s -o /dev/null -w "%{http_code}" http://localhost:$port/ 2>/dev/null || echo "UNREACHABLE"
  echo
done
```

## Ключевые аспекты настройки

### Безопасность и изоляция

1.  **User ID (UID):** Grafana запускается с `user: "472:472"`. Это требует настройки прав на хосте при использовании bind mounts: `chown -R 472:472 ./grafana/data`.
2.  **Read-Only Root FS:** Рекомендуется монтировать конфигурационные файлы как `:ro`. Для Prometheus и Alertmanager это предотвращает случайное изменение настроек изнутри контейнера.
3.  **Привилегии:** `node-exporter` и `cadvisor` требуют глубокого доступа к ОС хоста. Используйте их только в доверенных средах.

### Оптимизация Prometheus v3

*   **`--auto-gomemlimit`**: Обязателен при установке `deploy.resources.limits.memory`. Позволяет Go Runtime лучше управлять GC и избегать OOM.
*   **`--web.enable-lifecycle`**: Позволяет применять изменения в `prometheus.yml` через `curl -X POST /-/reload` без перезагрузки контейнера.

### Два режима security hardening

#### Режим A: Базовый (bind mounts + логирование)

Подходит для сред, где привилегированный доступ к хосту невозможен или нежелателен. Ограничивается `read_only` для конфигов, `tmpfs` для временных данных, `cap_drop` и `security_opt`.

#### Режим B: Расширенный (Docker Socket + Docker SD)

Для dynamic service discovery требуется доступ к Docker Socket. Это расширяет атакующую поверхность, но даёт автоматическое обнаружение контейнеров.

```yaml
services:
  prometheus:
    volumes:
      - /var/run/docker.sock:/var/run/docker.sock:ro
    security_opt:
      - no-new-privileges:true
      - seccomp:default
    cap_drop:
      - ALL
```

**Важно:** При доступе к Docker Socket компрометация Prometheus даёт злоумышленнику контроль над контейнерами хоста. Ограничьте доступ через сетевые политики и аутентификацию.

### Логирование

Секция `logging` задаётся на уровне сервиса или глобально через якорь:

```yaml
services:
  prometheus:
    logging: &default-logging
      driver: json-file
      options:
        max-size: "10m"
        max-file: "3"

  alertmanager:
    logging: *default-logging
```

Доступные драйверы: `json-file` (по умолчанию), `local`, `syslog`, `journald`, `fluentd`, `gelf`, `awslogs`, `splunk`. Для production рекомендуется `json-file` или `local` с ограничением размера и количества файлов.

## Рекомендации по эксплуатации

### Переменные окружения (.env)

Создайте файл `.env` в корне проекта для разделения конфигурации от кода:

```bash
# .env
GRAFANA_PASS=StrongPassword123
PROMETHEUS_RETENTION=30d
ALERTMANAGER_SMTP_HOST=smtp.example.com
ALERTMANAGER_SMTP_PORT=587
ALERTMANAGER_SMTP_USER=alerts@example.com
ALERTMANAGER_SMTP_PASS=SMTP_Password
```

Переменные подставляются в `compose.yml` через `${VAR}` или `${VAR:-default}`. Docker Compose автоматически загружает `.env` при запуске. Для проверки используйте `docker compose config`.

### Локальные переопределения (compose.override.yml)

Файл `compose.override.yml` автоматически применяется при запуске `docker compose up` и предназначен для локальных настроек:

```yaml
# compose.override.yml
services:
  prometheus:
    ports:
      - "127.0.0.1:9090:9090"
    volumes:
      - ./prometheus/debug:/etc/prometheus:ro
  grafana:
    ports:
      - "127.0.0.1:3000:3000"
```

Для production используйте явный указание файлов: `docker compose -f compose.yml -f compose.prod.yml up -d`.

### Управление секретами (Docker secrets)

Для production-сред используйте Docker secrets вместо `.env`. В Swarm mode:

```yaml
# compose.yml
services:
  grafana:
    secrets:
      - grafana_pass
    environment:
      - GF_SECURITY_ADMIN_PASSWORD_FILE=/run/secrets/grafana_pass

secrets:
  grafana_pass:
    file: ./secrets/grafana_pass.txt
```

В standalone Compose секреты можно эмулировать через `volumes` с `:ro`:

```yaml
services:
  grafana:
    volumes:
      - ./secrets/grafana_pass:/run/secrets/grafana_pass:ro
```

### Обновление и откат стека

Пошаговая процедура обновления:

```bash
# 1. Проверка конфигурации перед обновлением
docker compose config

# 2. Обновление образов
docker compose pull

# 3. Пересоздание сервисов
docker compose up -d --no-deps --force-recreate prometheus

# 4. Проверка работоспособности
curl -s -o /dev/null -w "%{http_code}" http://localhost:9090/-/healthy
docker compose ps

# 5. Очистка старых образов
docker image prune -f
```

Откат к предыдущей версии:

```bash
# Откат образа Prometheus
docker compose pull prometheus:v3.12.0
docker compose up -d --no-deps prometheus

# Если данные несовместимы
docker compose down prometheus
docker volume rm monitoring_prometheus_data
docker compose up -d prometheus
```

### Резервное копирование и восстановление

Создание снапшотов:

```bash
# Снапшот Prometheus
docker compose stop prometheus
docker run --rm -v monitoring_prometheus_data:/data -v $(pwd):/backup alpine tar czf /backup/prometheus_backup.tar.gz -C /data ./
docker compose start prometheus

# Снапшот Grafana
docker compose stop grafana
docker run --rm -v monitoring_grafana_data:/data -v $(pwd):/backup alpine tar czf /backup/grafana_backup.tar.gz -C /data ./
docker compose start grafana
```

Восстановление:

```bash
# Остановка сервиса
docker compose stop prometheus

# Удаление текущих данных
docker volume rm monitoring_prometheus_data
docker volume create monitoring_prometheus_data

# Восстановление из снапшота
docker run --rm -v monitoring_prometheus_data:/data -v $(pwd):/backup alpine tar xzf /backup/prometheus_backup.tar.gz -C /data
docker compose up -d prometheus
```

## Дополнительная информация

### Связанные темы

* [Обзор Docker Stack](./overview.md) — общая концепция и структура проекта.
* [Конфигурация Prometheus](./prometheus_config.md) — настройка сбора данных и алертинга.
* [Node Exporter](../../Exporters/node_exporter.md) — подробный разбор системных метрик.
* [cAdvisor](../../Exporters/cadvisor.md) — детализация мониторинга контейнеров.
* [Docker Compose basics](../../../Docker/Docker_compose/docker_compose_file_example.md) — общий синтаксис Compose.
* [Мониторинг Docker Engine](../../../Docker/Docker_metrics/docker_prometheus_integration.md) — интеграция с демоном Docker.

### Устранение неполадок

| Проблема | Причина | Решение |
|---|---|---|
| **Prometheus OOM** | Нет лимитов или `--auto-gomemlimit` | Добавьте лимиты в `deploy` и флаг запуска. |
| **cAdvisor 0 metrics** | Нет доступа к `docker.sock` | Проверьте монтирование `/var/run:/var/run:ro`. |
| **Grafana Login Fail** | Неверный пароль в `.env` | Проверьте переменную `GF_SECURITY_ADMIN_PASSWORD`. |
| **Permission denied на данных** | Несоответствие прав UID | Выполните `chown -R 65534:65534 ./prometheus_data`. |
| **Port already in use** | Порт занят на хосте | Измените привязку порта в `ports:` или освободите порт. |
| **Healthcheck не проходит** | Неверный URL или таймаут | Проверьте endpoint вручную: `curl http://localhost:9090/-/healthy`. |
| **DNS resolution fail** | Сервис в другой сети | Добавьте Prometheus в сеть через `networks:`. |
| **Hot reload не работает** | Флаг `--web.enable-lifecycle` отсутствует | Добавьте флаг в `command:` и перезапустите контейнер. |
| **Read-only контейнер падает** | Нет `tmpfs` для `/tmp` | Добавьте `tmpfs: ["/tmp:noexec,nosuid"]` в сервис. |
| **Retention не применяется** | Параметр задан в `prometheus.yml`, а не в CLI | Переместите `--storage.tsdb.retention.time` в `command:` compose-сервиса. |
| **Config reload failed** | Ошибка в `prometheus.yml` или правах | `docker logs prometheus 2>&1 | grep -i reload`; проверьте YAML и права. |
| **Targets в DOWN** | Ошибка DNS, неверный порт, фаервол | `docker exec prometheus nslookup node-exporter`; проверьте сеть. |
| **Scrape timeout** | Большая кардинальность, медленный экспортер | Увеличьте `scrape_timeout`, оптимизируйте экспортер. |
| **Sample limit exceeded** | Превышен `sample_limit` в job | Увеличьте `sample_limit` или добавьте `metric_relabel_configs`. |
| **Secret leaked in /-/config** | Секреты указаны в `prometheus.yml` | Перенесите секреты в `credentialsFile` или env vars. |

### Проверка состояния стека

Endpoint'ы для проверки работоспособности:

| Сервис | Endpoint | Ожидаемый ответ |
|---|---|---|
| Prometheus | `http://localhost:9090/-/healthy` | `Prometheus Server is Healthy.` |
| Alertmanager | `http://localhost:9093/-/healthy` | `OK` |
| Grafana | `http://localhost:3000/api/health` | `{"database":"ok"}` |

Проверка через curl:

```bash
# Быстрая проверка всех сервисов
for port in 9090 9093 3000; do
  echo -n "Port $port: "
  curl -s -o /dev/null -w "%{http_code}" http://localhost:$port/ 2>/dev/null || echo "UNREACHABLE"
  echo
done
```
