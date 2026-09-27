# Практическая настройка Loki в Docker Compose

## Определения

**Loki** — горизонтально масштабируемая система агрегации логов от Grafana Labs, которая индексирует только метаданные (метки), а не полный текст логов. Это позволяет значительно снизить затраты на хранение и обработку данных по сравнению с традиционными полнотекстовыми поисковыми системами. Подробная архитектура: [loki_overview.md](../loki_overview.md).

**Docker Compose** — инструмент для определения и запуска многоконтейнерных Docker-приложений с помощью YAML-файлов. Он обеспечивает оркестрацию локальных сервисов, управление сетями и томами данных в рамках одного проекта. В данном документе используется Compose Specification v2 (плагин к Docker CLI).

**Grafana Alloy** — современный универсальный агент для сбора телеметрии (логов, метрик, трейсов). Построен на базе OpenTelemetry Collector и является официальной заменой Promtail и Grafana Agent. Подробнее см. [Grafana Alloy](../../Grafana/grafana_alloy_overview.md).

**LogQL** — язык запросов, вдохновленный Prometheus (PromQL), используемый для фильтрации и анализа логов в Loki.

**Named Volume** — том Docker, управляемый плагином Compose. Данные в именованных томах сохраняются после удаления контейнеров, что критично для персистентности индексов и кэшей Loki. В отличие от bind mounts, не требуют настройки прав доступа на хосте.

**River** — декларативный язык конфигурации Alloy, использующий блоковую структуру, аналогичную HCL. Каждый блок описывает компонент пайплайна с явными связями `forward_to`/`exports`.

## Основные концепции

Для полноценного сбора логов в Docker с использованием Loki требуется три основных компонента. Информация актуальна на **август 2026 года**.

### Компоненты стека

| Компонент | Назначение | Актуальная версия | Примечание |
| :--- | :--- | :--- | :--- |
| **Loki** | Сервер для приема, хранения и индексации логов | `3.7.5` | Основной бэкенд системы. Версия 3.x включает новый движок запросов и поддержку Bloom-фильтров. |
| **Grafana Alloy** | Универсальный агент для сбора телеметрии | `1.18.1` | **Рекомендуемый агент**. Поддерживает динамическое обнаружение контейнеров через Docker API. |
| **Grafana** | Визуализация и запросы (LogQL) | `13.1.3` | Единый UI для мониторинга. Включает новые инструменты Logs Drilldown. |
| **Promtail** | Агент для сбора логов (Legacy) | — | **Удален** начиная с версии Loki 3.7.3. Поддержка прекращена в пользу Alloy. |

> **Важно:** Использование Promtail в новых проектах не рекомендуется. Alloy предоставляет более гибкую настройку пайплайнов обработки логов и нативную поддержку OpenTelemetry. Подробнее см. [Grafana Alloy](../../Grafana/grafana_alloy_overview.md).

### Архитектура потока данных

```
┌─────────────────────────────────────────────────────────────┐
│              Контейнеры Docker (приложения)                  │
│              STDOUT / STDERR → json-file драйвер            │
└──────────────────────┬──────────────────────────────────────┘
                       │ Docker API / direct tail
                       ▼
┌─────────────────────────────────────────────────────────────┐
│                    Grafana Alloy                            │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────────┐  │
│  │ discovery.   │  │ discovery.   │  │ loki.source.     │  │
│  │ docker       │→│ relabel      │→│ docker / file    │  │
│  │ (метаданные) │  │ (лейблы)     │  │ (чтение логов)   │  │
│  └──────────────┘  └──────────────┘  └────────┬─────────┘  │
│                                                │            │
│  ┌─────────────────────────────────────────────┼────────┐   │
│  │ loki.write (батчинг, буферизация, retry)    │        │   │
│  └─────────────────────────────────────────────┼────────┘   │
└────────────────────────────────────────────────┼────────────┘
                                                 │ HTTP Push
                                                 ▼
┌─────────────────────────────────────────────────────────────┐
│                      Loki                                   │
│  ┌────────────┐  ┌────────────┐  ┌──────────────────────┐  │
│  │ Distributor│→ │ Ingester   │→ │ Storage (filesystem) │  │
│  │ (валидация)│  │ (чанки)     │  │ /loki/chunks         │  │
│  └────────────┘  └────────────┘  └──────────────────────┘  │
│  ┌────────────┐  ┌────────────┐                            │
│  │ Querier    │← │ Compactor  │  Применение retention      │
│  └────────────┘  └────────────┘                            │
└──────────────────────┬──────────────────────────────────────┘
                       │ LogQL API (HTTP)
                       ▼
┌─────────────────────────────────────────────────────────────┐
│                      Grafana UI                             │
│           (визуализация, алертинг, дашборды)                │
└─────────────────────────────────────────────────────────────┘
```

### Режимы сбора логов Alloy

Alloy может собирать логи двумя способами:

1. **Docker API (рекомендуется в конфигурации ниже):** Агент подключается к `/var/run/docker.sock`, получает метаданные контейнеров и поток логов через API. Преимущества: автоматическое обогащение метаданными (образ, имя, лейблы), динамическое обнаружение новых контейнеров. Недостаток: дополнительная нагрузка на Docker daemon при очень высоком объеме логов.
2. **Прямое чтение файлов (Tail):** Агент монтирует `/var/lib/docker/containers/` и читает файлы `*-json.log` напрямую. Преимущества: максимальная производительность, отсутствие нагрузки на Docker API. Используется в production средах с очень высоким throughput. Необходимо самостоятельно управлять позиционными файлами (checkpoints) для надежности.

## Предварительные требования

### Аппаратные требования

| Компонент | Минимум | Рекомендуется |
| :--- | :--- | :--- |
| **CPU** | 2 ядра | 4+ ядра |
| **RAM** | 4 GB | 8+ GB |
| **Диск** | 20 GB (SSD) | 50+ GB (SSD/NVMe) |

Для хранения логов рекомендуется выделять отдельный том или раздел, отличный от системного, чтобы избежать заполнения корневой файловой системы.

### Программные требования

- **Docker Engine:** 24.0+ (с включенным containerd)
- **Docker Compose:** v2.20+ (плагин к Docker CLI)
- **ОС:** Linux (Debian 12+, Ubuntu 22.04+, RHEL 9+), macOS 13+, Windows 11 Pro/Enterprise с WSL2

### Начальное состояние окружения

1. Docker Engine установлен и служба активна:
   ```bash
   systemctl status docker
   # → active (running)
   ```
2. Пользователь добавлен в группу `docker`:
   ```bash
   sudo usermod -aG docker $USER
   ```
   Перелогин требуется для применения прав.
3. Достаточно свободного места в `/var/lib/docker/` для образов и томов
4. Порты `3100` (Loki), `3000` (Grafana), `12345` (Alloy UI) свободны на хосте:
   ```bash
   ss -tlnp | grep -E ':3100|:3000|:12345'
   # → нет вывода
   ```
5. Доступ к Docker Socket:
   ```bash
   ls -la /var/run/docker.sock
   # → srw-rw---- 1 root docker 0 ... /var/run/docker.sock
   ```

## Практические сценарии

### Конфигурация Docker Compose

Ниже приведен современный пример `compose.yml` (Compose Spec) для развертывания стека логирования. Файл предполагается в каталоге `monitoring/`.

```yaml
# monitoring/compose.yml

services:
  loki:
    image: grafana/loki:3.7.5
    container_name: monitoring-loki
    ports:
      - "3100:3100"
    command: -config.file=/etc/loki/local-config.yaml
    volumes:
      - loki_data:/loki
      - ./loki/config.yaml:/etc/loki/local-config.yaml:ro
    restart: always
    networks:
      - monitoring
    healthcheck:
      test: ["CMD", "wget", "-q", "--spider", "http://localhost:3100/ready"]
      interval: 10s
      timeout: 5s
      retries: 3
      start_period: 15s
    deploy:
      resources:
        limits:
          memory: 2G
        reservations:
          memory: 512M
    logging:
      driver: json-file
      options:
        max-size: "10m"
        max-file: "3"

  alloy:
    image: grafana/alloy:v1.18.1
    container_name: monitoring-alloy
    volumes:
      - /var/run/docker.sock:/var/run/docker.sock:ro
      - ./alloy/config.alloy:/etc/alloy/config.alloy:ro
      - alloy_data:/var/lib/alloy
    command: run --storage.path=/var/lib/alloy /etc/alloy/config.alloy
    ports:
      - "12345:12345"
    restart: always
    networks:
      - monitoring
    depends_on:
      loki:
        condition: service_healthy
    healthcheck:
      test: ["CMD", "wget", "-q", "--spider", "http://localhost:12345/health"]
      interval: 10s
      timeout: 5s
      retries: 3
      start_period: 10s
    deploy:
      resources:
        limits:
          memory: 512M
        reservations:
          memory: 128M
    logging:
      driver: json-file
      options:
        max-size: "10m"
        max-file: "3"

  grafana:
    image: grafana/grafana:13.1.3
    container_name: monitoring-grafana
    ports:
      - "3000:3000"
    volumes:
      - grafana_data:/var/lib/grafana
      - ./grafana/provisioning:/etc/grafana/provisioning:ro
    environment:
      - GF_SECURITY_ADMIN_USER=admin
      - GF_SECURITY_ADMIN_PASSWORD=admin
      - GF_SERVER_ROOT_URL=http://localhost:3000
    restart: always
    networks:
      - monitoring
    depends_on:
      loki:
        condition: service_healthy
    healthcheck:
      test: ["CMD", "wget", "-q", "--spider", "http://localhost:3000/api/health"]
      interval: 15s
      timeout: 10s
      retries: 3
      start_period: 30s
    deploy:
      resources:
        limits:
          memory: 512M
        reservations:
          memory: 256M
    logging:
      driver: json-file
      options:
        max-size: "10m"
        max-file: "3"

volumes:
  loki_data:
    name: monitoring-loki
  alloy_data:
    name: monitoring-alloy
  grafana_data:
    name: monitoring-grafana

networks:
  monitoring:
    driver: bridge
    name: monitoring-net
```

#### Пояснения к параметрам Compose

- **depends_on с условием `service_healthy`:** Гарантирует, что Alloy и Grafana запустятся только после того, как Loki пройдет проверку готовности. Это предотвращает ошибки подключения на старте.
- **healthcheck:** Встроенные проверки здоровья для каждого сервиса. Docker Compose отслеживает статус и может перезапустить unhealthy контейнер в зависимости от политики `restart`.
- **deploy.resources:** Ограничение памяти критично для Loki, так как при тяжелых запросах и приемах данных потребление RAM может резко возрасти. Резервирование гарантирует минимальный объем памяти для стабильной работы.
- **logging.driver:** Ограничение размера логов самих контейнеров мониторинга, чтобы они не заполнили диск хоста бесконтрольно.
- **restart: always:** Политика перезапуска. В production вместо `always` рекомендуется `unless-stopped`, чтобы предотвратить автоматический перезапуск после явной остановки для обслуживания.

### Настройка Grafana Alloy

Конфигурация Alloy использует декларативный язык River для описания потоков данных.

```alloy
// monitoring/alloy/config.alloy

// 1. Обнаружение контейнеров через Docker API
discovery.docker "containers" {
  host = "unix:///var/run/docker.sock"
}

// 2. Преобразование и фильтрация меток
discovery.relabel "docker_logs" {
  targets = discovery.docker.containers.targets

  // Извлекаем чистое имя контейнера
  rule {
    source_labels = ["__meta_docker_container_name"]
    regex         = "/(.*)"
    target_label  = "container"
  }

  // Добавляем метку образа
  rule {
    source_labels = ["__meta_docker_container_image"]
    target_label  = "image"
  }

  // Исключаем логи самой Grafana и Alloy, чтобы избежать циклической нагрузки (опционально)
  rule {
    source_labels = ["container"]
    regex         = "monitoring-(grafana|alloy)"
    action        = "drop"
  }
}

// 3. Сбор логов через Docker API и передача в приемник
loki.source.docker "local_docker" {
  host       = "unix:///var/run/docker.sock"
  targets    = discovery.relabel.docker_logs.output
  forward_to = [loki.write.local_loki.receiver]
}

// 4. Отправка данных в Loki API с настройкой батчинга
loki.write "local_loki" {
  endpoint {
    url = "http://loki:3100/loki/api/v1/push"
    // Настройка батчинга для оптимизации производительности
    batch_size = 1048576 // 1MB
    batch_wait = "1s"
  }
}
```

#### Пояснения к конфигурации Alloy

- **discovery.docker:** Подключается к Docker Socket и получает поток событий о контейнерах (создание, старт, остановка). Для каждого контейнера генерируется набор мета-лейблов (`__meta_docker_*`), которые используются на этапе relabeling.
- **discovery.relabel:** Механизм трансформации меток, аналогичный Prometheus `relabel_configs`. Позволяет переименовывать, добавлять, фильтровать и удалять метки перед отправкой в Loki. Правила применяются последовательно в порядке объявления.
- **loki.source.docker:** Компонент сбора логов через Docker API. В отличие от `loki.source.file`, он автоматически отслеживает новые контейнеры и извлекает логи через API `/containers/{id}/logs`. Не требует монтирования `/var/lib/docker/containers/`.
- **loki.write:** Компонент отправки данных в Loki. Выполняет батчинг (объединение нескольких записей в один HTTP-запрос), буферизацию на диске и автоматические повторные попытки при недоступности приемника. Параметры `batch_size` и `batch_wait` балансируют между задержкой доставки и нагрузкой на сеть/CPU.

#### Альтернатива: Прямое чтение файлов

Для production сред с очень высоким объемом логов (более 1 ГБ/мин) рекомендуется использовать прямое чтение файлов вместо Docker API, чтобы снизить нагрузку на Docker daemon:

```alloy
// monitoring/alloy/config.alloy (альтернативный вариант с прямым чтением)

loki.source.file "docker_logs" {
  targets = discovery.relabel.docker_logs.output
  forward_to = [loki.write.local_loki.receiver]

  // Читаем файлы напрямую с хоста
  // Требует монтирования /var/lib/docker/containers в compose.yml
  // и настройки discovery.file или кастомного relabeling
}
```

Для этого варианта в `compose.yml` необходимо добавить монтирование:
```yaml
services:
  alloy:
    volumes:
      - /var/lib/docker/containers:/var/lib/docker/containers:ro
```

### Конфигурация Loki (Storage и Retention)

```yaml
# monitoring/loki/config.yaml

auth_enabled: false

server:
  http_listen_port: 3100

common:
  instance_addr: 127.0.0.1
  path_prefix: /loki
  storage:
    filesystem:
      chunks_directory: /loki/chunks
      rules_directory: /loki/rules
  replication_factor: 1
  ring:
    kvstore:
      store: inmemory

schema_config:
  configs:
    - from: 2024-01-01
      store: tsdb
      object_store: filesystem
      schema: v13
      index:
        prefix: index_
        period: 24h

limits_config:
  retention_period: 30d # Хранить логи 30 дней
  ingestion_rate_mb: 10
  ingestion_burst_size_mb: 20
  max_query_series: 5000
  reject_old_samples: true
  reject_old_samples_max_age: 168h

compactor:
  working_directory: /loki/retention
  compaction_interval: 10m
  retention_enabled: true
  retention_delete_delay: 2h
  retention_delete_worker_count: 150
```

#### Пояснения к конфигурации Loki

- **auth_enabled: false:** Отключает мультиарендность. В Docker Compose окружении безопасность обеспечивается изоляцией сети. Для внешнего доступа (за пределами Docker bridge) необходимо включить `auth_enabled: true` и использовать Gateway (Nginx/Ingress) с передачей заголовка `X-Scope-OrgID`.
- **replication_factor: 1:** В Single Binary режиме репликация не требуется. Для кластерных развертываний (Simple Scalable, Distributed) устанавливается значение 3.
- **schema_config:** Определяет формат хранения данных.
  - `store: tsdb` — движок хранения индексов (Time Series Database, встроенный в Loki 3.x).
  - `object_store: filesystem` — хранилище чанков (локальная файловая система). Для production рекомендуется S3, GCS или Azure Blob.
  - `schema: v13` — актуальная версия схемы на 2026 год, поддерживающая structured metadata и Bloom-фильтры.
  - `period: 24h` — период ротации индексных файлов. Меньший период ускоряет сжатие и удаление, но увеличивает количество маленьких файлов.
- **limits_config:** Лимиты приема и запросов.
  - `retention_period: 30d` — глобальный срок хранения логов. Компактор автоматически удаляет данные старше этого порога.
  - `ingestion_rate_mb: 10` — максимальная скорость приема логов на один инжестер (MB/сек). При превышении Loki возвращает 429.
  - `ingestion_burst_size_mb: 20` — размер burst-буфера для краткосрочных пиков нагрузки.
  - `max_query_series: 5000` — защита от слишком широких запросов, которые могут "завесить" инстанс.
  - `reject_old_samples: true` — отбрасывание логов с timestamp старше `reject_old_samples_max_age`. Защищает от перезаписи исторических данных при пересылке старых логов.
- **compactor:** Фоновая задача, объединяющая чанки и применяющая retention.
  - `retention_delete_worker_count: 150` — количество параллельных воркеров для удаления. Увеличивайте при объемах > 1 ТБ/день.

### Развертывание и валидация

#### Шаг 1: Подготовка каталогов

```bash
mkdir -p monitoring/loki monitoring/alloy monitoring/grafana/provisioning
```

#### Шаг 2: Запись конфигурационных файлов

Создайте файлы `monitoring/compose.yml`, `monitoring/loki/config.yaml`, `monitoring/alloy/config.alloy` согласно примерам выше.

#### Шаг 3: Запуск стека

```bash
cd monitoring
docker compose up -d
# → [+] Running 3/3
#  ⠿ Network monitoring-net    Created
#  ⠿ Volume "monitoring-loki"  Created
#  ⠿ Volume "monitoring-alloy" Created
#  ⠿ Volume "monitoring-grafana" Created
#  ⠿ Container monitoring-loki    Started
#  ⠿ Container monitoring-alloy   Started
#  ⠿ Container monitoring-grafana Started
```

#### Шаг 4: Проверка статуса сервисов

```bash
docker compose ps
# → NAME                    SERVICE       STATUS              PORTS
#  monitoring-alloy         alloy         running (healthy)    0.0.0.0:12345->12345/tcp
#  monitoring-grafana       grafana       running (healthy)    0.0.0.0:3000->3000/tcp
#  monitoring-loki          loki          running (healthy)    0.0.0.0:3100->3100/tcp
```

#### Шаг 5: Валидация доставки логов

```bash
# Проверка готовности Loki
curl -s http://localhost:3100/ready
# → ready

# Проверка метрик Loki (количество принятых строк)
curl -s "http://localhost:3100/metrics" | grep "loki_ingester_streams_created_total"
# → loki_ingester_streams_created_total 5

# Просмотр логов самого Alloy (для диагностики)
docker logs monitoring-alloy 2>&1 | tail -20
# → ts=2026-09-14T... caller=runner.go:... msg="compiling config file" ... level=info
# → ts=2026-09-14T... caller=storage.go:... msg="running with storage.path=/var/lib/alloy" ... level=info

# Проверка метрик Alloy
curl -s http://localhost:12345/metrics | grep "alloy_build_info"
# → alloy_build_info{version="1.18.1",...} 1
```

#### Шаг 6: Проверка в Grafana

1. Откройте `http://localhost:3000` и войдите с `admin`/`admin`.
2. Перейдите в **Connections → Data sources → Add data source → Loki**.
3. В поле **URL** укажите `http://loki:3100` (имя сервиса внутри Docker сети).
4. Нажмите **Save & test**. Ожидаемый результат: `Data source is working`.
5. Перейдите в **Explore**, выберите источник Loki и выполните запрос:
   ```logql
   {container=~".+"}
   ```
   Должны отобразиться логи всех работающих контейнеров.

### Жизненный цикл и обслуживание

#### Обновление образов

```bash
# Проверка актуальных версий
docker compose pull

# Перезапуск с новыми образами (zero-downtime для loki и alloy)
docker compose up -d --force-recreate --wait

# Проверка статуса после обновления
docker compose ps
docker compose logs --tail=20 loki
```

#### Резервное копирование

Данные Loki хранятся в именованном томе `monitoring-loki`. Для бэкапа:

```bash
# Остановка Loki (гарантирует консистентность данных)
docker compose stop loki

# Создание архива тома
docker run --rm \
  -v monitoring-loki:/data:ro \
  -v $(pwd)/backups:/backup \
  alpine tar czf /backup/loki-backup-$(date +%Y%m%d).tar.gz -C /data .

# Запуск Loki
docker compose start loki
```

Данные Grafana (дашборды, пользователи) хранятся в томе `monitoring-grafana`. Данные Alloy (WAL, позиционные файлы) — в `monitoring-alloy`.

#### Масштабирование

В Single Binary режиме (Docker Compose) горизонтальное масштабирование Loki не поддерживается. Для масштабирования необходимо перейти на режим **Simple Scalable** или **Distributed** в Kubernetes (см. [loki_installation.md](../loki_stack_setup/loki_installation.md)).

Можно увеличить ресурсы контейнера без пересоздания:

```bash
docker compose up -d --scale loki=1
# Ресурсы меняются через редактирование compose.yml и последующий recreate
```

#### Очистка окружения

```bash
# Остановка и удаление контейнеров, сетей (томы сохраняются)
docker compose down

# Полная очистка с удалением томов (ВНИМАНИЕ: удаляет все данные)
docker compose down -v
```

### Безопасность и ограничение доступа

#### 1. Ресурсные лимиты

Всегда ограничивайте потребление памяти для Loki, так как при тяжелых запросах потребление RAM может резко возрасти.

```yaml
deploy:
  resources:
    limits:
      memory: 2G
    reservations:
      memory: 512M
```

#### 2. Сетевая изоляция

Все сервисы объединены в выделенную bridge-сеть `monitoring-net`. Grafana пробрасывается на порт `3000` хоста, остальные сервисы остаются изолированными внутри сети. Доступ к Loki (3100) и Alloy (12345) извне Docker по умолчанию отсутствует.

Для доступа к Loki извне Docker используйте Reverse Proxy (Nginx/Traefik) с базовой аутентификацией или настроить `auth_enabled: true` в Loki.

#### 3. Базовый аутентификация в Alloy

```alloy
loki.write "local_loki" {
  endpoint {
    url = "http://loki:3100/loki/api/v1/push"
    basic_auth {
      username = "loki_user"
      password = "secret_password"
    }
  }
}
```

#### 4. Non-root пользователь

Для повышения безопасности можно запускать Alloy от имени не-root пользователя. В официальном образе Grafana Alloy пользователь `alloy` (UID 10001) уже создан. Доступ к Docker Socket:

```bash
# На хосте (Linux)
sudo setfacl -m u:10001:r /var/run/docker.sock
```

#### 5. Защита портов хоста

```bash
# Ограничение доступа к портам мониторинга только локальным интерфейсом
# В compose.yml измените проброс портов:
# ports:
#   - "127.0.0.1:3000:3000"
#   - "127.0.0.1:12345:12345"
```

### Поиск и устранение неисправностей

| Проблема | Возможная причина | Решение |
| :--- | :--- | :--- |
| **Alloy не видит контейнеры** | Нет доступа к `docker.sock` | Проверьте монтирование сокета и права доступа: `ls -la /var/run/docker.sock`. На Linux может потребоваться `sudo setfacl -m u:10001:r /var/run/docker.sock` |
| **Ошибка 429 (Too Many Requests)** | Превышены лимиты Loki | Увеличьте `ingestion_rate_mb` и `ingestion_burst_size_mb` в `limits_config` конфигурации Loki |
| **Логи отображаются с задержкой** | Большой `batch_wait` в Alloy | Уменьшите интервал отправки в конфигурации `loki.write` (например, до `"500ms"`). Учтите, что слишком маленькие значения увеличивают нагрузку на сеть |
| **Пустые результаты Explore** | Неверный селектор меток | Проверьте метки через Alloy UI (порт 12345) в разделе `discovery.relabel`. Убедитесь, что имена контейнеров корректно извлекаются |
| **Контейнер Loki в состоянии restarting** | Недостаточно памяти или ошибка в конфигурации | Проверьте логи: `docker logs monitoring-loki`. Убедитесь, что путь `/loki` доступен для записи и том смонтирован корректно |
| **Grafana не видит источник Loki** | Неверный URL источника или DNS | Внутри Docker сети используйте `http://loki:3100`, а не `localhost` или IP-адрес. Проверьте: `docker exec monitoring-grafana ping -c 1 loki` |
| **Высокое потребление RAM у Loki** | Отсутствуют лимиты или слишком большой `max_query_series` | Установите `deploy.resources.limits.memory`. Уменьшите `max_query_series`. Используйте Bloom-фильтры для ускорения запросов |
| **Потеря логов при перезагрузке Alloy** | Позиционные файлы не персистентны | Убедитесь, что том `alloy_data` смонтирован и не удаляется при `docker compose down` (используйте `docker compose down` без `-v`) |

#### Диагностические команды

```bash
# Статус контейнеров и healthcheck
docker compose ps
docker inspect --format='{{.State.Health.Status}}' monitoring-loki

# Логи конкретного сервиса
docker compose logs --tail=100 loki
docker compose logs --tail=100 alloy

# Проверка сетевого взаимодействия между контейнерами
docker exec monitoring-grafana ping -c 3 loki
docker exec monitoring-alloy ping -c 3 loki

# Проверка монтирования томов
docker inspect monitoring-loki | jq '.[0].Mounts'

# Использование ресурсов в реальном времени
docker stats monitoring-loki monitoring-alloy monitoring-grafana
# → CONTAINER           CPU %     MEM USAGE / LIMIT
#  monitoring-loki      2.5%      512MiB / 2GiB
#  monitoring-alloy     0.1%      64MiB / 512MiB
#  monitoring-grafana   1.0%      256MiB / 512MiB
```

## Дополнительная информация

* **Обзор архитектуры:** [loki_overview.md](../loki_overview.md) — детальное описание компонентов и потоков данных.
* **Развертывание в Kubernetes:** [loki_installation.md](../loki_stack_setup/loki_installation.md) — переход от Docker Compose к Helm-чартам.
* **Подробно об Alloy:** [Grafana Alloy](../../Grafana/grafana_alloy_overview.md) — возможности и компоненты нового агента.
* **Агентный сбор логов в Docker:** [docker_agent_based_logging.md](../../Docker/Docker_logs/docker_agent_based_logging.md) — сравнение подходов и тонкая настройка пайплайнов.
* **Официальная документация:** [Grafana Loki Docs](https://grafana.com/docs/loki/latest/) — справочник по всем параметрам конфигурации.
