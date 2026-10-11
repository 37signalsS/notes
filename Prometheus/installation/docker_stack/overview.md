# Обзор Docker Stack — установка стека мониторинга

## Определения

**Стек мониторинга (Monitoring Stack)** — это логическая группа взаимосвязанных сервисов (Prometheus, Grafana, Alertmanager и экспортеры), работающих совместно для обеспечения полной наблюдаемости системы.

**Docker Compose** — основной инструмент оркестрации для развёртывания стека мониторинга на одном хосте. Позволяет декларативно описать всю инфраструктуру в одном YAML-файле.

**Docker Stack (в контексте мониторинга)** — часто используемый термин для обозначения набора сервисов мониторинга. Важно отличать его от *Docker Swarm Stack*, который используется для оркестрации в кластере. Данное руководство сфокусировано на **Docker Compose**.

> **См. также:** [Конфигурация Docker Compose](./docker-compose_config.md) — полный YAML-файл, описания сервисов, healthchecks, security.

## Основные концепции

### Компоненты стека

| Компонент | Роль в стеке | Конфигурация |
|---|---|---|
| **Prometheus** | Сбор и хранение метрик (TSDB), вычисление правил алертинга | [prometheus_config.md](./prometheus_config.md) |
| **Grafana** | Визуализация, дашборды, единый UI для всех источников данных | [Grafana docker_compose_setup](../../../Grafana/Installation/docker_compose_setup.md) |
| **Alertmanager** | Дедупликация, группировка, маршрутизация оповещений | [docker_compose_alertmanager_config.md](./docker_compose_alertmanager_config.md) |
| **Node Exporter** | Экспорт метрик хоста: CPU, память, диск, сеть | Встроен в [docker-compose_config.md](./docker-compose_config.md) |
| **cAdvisor** | Экспорт детальных метрик Docker-контейнеров (ресурсы, I/O) | [cAdvisor SSoT](../../Exporters/cadvisor.md) |
| **Grafana Alloy** | (Опционально) Современный универсальный агент, заменяющий экспортеры | [Grafana Alloy overview](../../../Grafana/Installation/docker_compose_setup.md) |

### Хранение данных и персистентность

Для обеспечения сохранности данных при перезапуске контейнеров используются **Docker Volumes**:
*   **Named Volumes (Именованные тома):** Рекомендуются для баз данных (Prometheus TSDB, Grafana DB). Управляются Docker, обеспечивают высокую производительность.
*   **Bind Mounts (Привязки директорий):** Используются для конфигурационных файлов (`prometheus.yml`, `config.yml`). Позволяют легко редактировать конфиги на хосте без входа в контейнер.

**Драйверы томов:**
*   **`local`** — драйвер по умолчанию, хранит данные на локальном диске хоста. Рекомендуется для production.
*   **`tmpfs`** — хранит данные в оперативной памяти. Подходит для временных данных, не требующих персистентности.
*   **NFS/блочные устройства** — используются для распределённых хранилищ или общего доступа к данным между хостами.

**Важно:** Для production-среды избегайте `tmpfs` для Prometheus TSDB и Grafana DB — при перезапуске хоста все данные будут потеряны.

### Сетевое взаимодействие

#### Режимы сетей Docker Compose

В Docker Compose по умолчанию создаётся изолированная сеть с драйвером **bridge**:
*   **`bridge`** — изолированная сеть на уровне хоста. Сервисы видят друг друга по DNS-именам. Внешний доступ через проброшенные порты (`ports`). Рекомендуется для production.
*   **`host`** — контейнер использует сетевой стек хоста напрямую. Отсутствует изоляция сети, повышается производительность (нет NAT). Подходит для сценариев, где требуется максимальная производительность сети.
*   **`none`** — полная изоляция сети. Контейнер не имеет сетевых интерфейсов. Используется для фоновых задач, не требующих сетевого доступа.

**Service Discovery:** Внутри bridge-сети сервисы обращаются друг к другу по именам, объявленным в `compose.yml` (например, `http://prometheus:9090`). Docker встроенный DNS автоматически разрешает имена сервисов в IP-адреса контейнеров.

**Изоляция:** Стек защищён от внешнего мира; наружу пробрасываются только необходимые порты (Grafana — 3000, Prometheus — 9090, Alertmanager — 9093).

### Жизненный цикл сервисов

#### Политики перезапуска (restart policies)

| Политика | Поведение | Применение |
|---|---|---|
| **`no`** | Не перезапускать автоматически | Только для отладочных контейнеров |
| **`on-failure`** | Перезапускать только при ненулевом коде завершения | Для рабочих процессов с чётким статусом выхода |
| **`always`** | Всегда перезапускать, кроме явной остановки | Для критичных сервисов |
| **`unless-stopped`** | Перезапускать, кроме явной остановки (`docker stop`) | **Рекомендуется для production** |

#### Зависимости и healthchecks

Директива `depends_on` с условием `service_healthy` гарантирует, что сервис-зависимость (например, Grafana) запустится только после того, как целевой сервис (Prometheus) пройдёт healthcheck:

```yaml
depends_on:
  prometheus:
    condition: service_healthy
```

**Важно:** `depends_on` без `condition` только контролирует порядок запуска, а не готовность сервиса. Для production используйте `condition: service_healthy`.

### Управление логами

Docker поддерживает несколько драйверов логирования. Для стека мониторинга критически важно предотвратить переполнение диска логами.

| Драйвер | Тип | Хранение | Ротация | Применение |
|---|---|---|---|---|
| **`json-file`** | Локальный | `/var/lib/docker/containers/<id>/<id>-json.log` | Ручная (`max-size`, `max-file`) | Стандартный, совместим со всеми инструментами |
| **`local`** | Локальный | Бинарный protobuf-кэш | Автоматическая (100 МБ / 5 файлов) | **Рекомендуется** с Docker 20.10+ |
| **`none`** | — | Отключён | — | Только для одноразовых задач |
| **`fluentd` / `loki`** | Сетевой | Удалённый сервер | На стороне агента | Централизованный сбор логов |

**Рекомендация:** Используйте драйвер `local` или `json-file` с явной ротацией (`max-size: 10m`, `max-file: 3`). Для централизованного сбора логов применяйте сетевые драйверы или sidecar-агенты (Grafana Alloy, Vector).

### Ресурсы и изоляция

#### cgroups и лимиты памяти

Docker использует контрольные группы (cgroups) для ограничения ресурсов контейнеров. Важно учитывать версию cgroups на хосте:

*   **cgroups v1:** Лимиты задаются через `docker run --memory`, `--cpus`. Параметр `memory.memsw.limit_in_bytes` контролирует swap.
*   **cgroups v2:** Объединённая иерархия, более точный контроль. Лимиты задаются через `deploy.resources.limits` в Compose. Параметр `memory.max` задаёт жёсткий лимит, `memory.high` — мягкий.

Для Prometheus v3 (на базе Go Runtime) обязательно используйте флаг `--auto-gomemlimit`, который позволяет Go автоматически подстраивать лимиты GC под лимиты контейнера и избегать OOM Killer.

#### CPU и I/O

*   **CPU:** Ограничивайте через `deploy.resources.limits.cpus` (например, `"2"` для 2 ядер). Для тонкой настройки используйте `cpuset` (привязка к конкретным ядрам).
*   **I/O:** Ограничивайте через `blkio-weight` (приоритет) или `device-read-bps` / `device-write-bps` (пропускная способность). Для cgroups v2 используйте `io.max`.

### Часовые пояса и локали

По умолчанию контейнеры используют UTC. Для согласования временных меток в логах и метриках с локальным временем хоста:

```yaml
services:
  prometheus:
    environment:
      - TZ=Europe/Moscow
    volumes:
      - /etc/localtime:/etc/localtime:ro
```

**Важно:** Монтирование `/etc/localtime` в режиме `ro` синхронизирует время без изменения конфигурации контейнера. Для всех сервисов стека рекомендуется использовать единый часовой пояс, чтобы временные метки в Grafana, Alertmanager и Prometheus были согласованы.

### Структура проекта

```text
monitoring/
├── compose.yml           # Основной файл конфигурации
├── compose.override.yml  # Локальные переопределения (не коммитить в Git)
├── .env                  # Переменные окружения и секреты
├── prometheus/
│   ├── prometheus.yml    # Основной конфиг Prometheus
│   └── rules.yml         # Правила алертинга
├── alertmanager/
│   └── config.yml        # Настройки уведомлений
└── grafana/              # Настройки визуализации (provisioning)
    └── provisioning/
        ├── datasources/
        └── dashboards/
```

**Модульность:** Для крупных стеков используйте `include` (Compose v2.20+) для разделения конфигурации на логические части:

```yaml
# compose.yml
include:
  - path: ./compose.prometheus.yml
  - path: ./compose.grafana.yml
  - path: ./compose.alertmanager.yml
```

### Пошаговая настройка

Процесс разбит на независимые шаги:

| Шаг | Файл | Содержание |
|---|---|---|
| **1** | [docker-compose_config.md](./docker-compose_config.md) | YAML-файл стека: сервисы, тома, сети, лимиты ресурсов |
| **2** | [prometheus_config.md](./prometheus_config.md) | `prometheus.yml`: scrape-цели, rule_files, alerting-секция |
| **3** | [docker_compose_alertmanager_config.md](./docker_compose_alertmanager_config.md) | `config.yml` Alertmanager: маршруты, получатели (Slack, Email) |
| **4** | — | Запуск и проверка: `docker compose up -d`, health-эндопоинты |
| **5** | [remote_hosts_monitoring.md](./remote_hosts_monitoring.md) | Мониторинг внешних серверов через Node Exporter |

### Сравнение с альтернативами

| Подход | Когда использовать | Плюсы | Минусы |
|---|---|---|---|
| **Docker Compose** | Локальная среда, demo, small-scale production | Простота, скорость развёртывания | Нет встроенного HA |
| **Kubernetes (Helm)** | Enterprise, масштабируемые системы | HA, Auto-scaling, GitOps | Высокая сложность управления |
| **Grafana Alloy Stack** | Современный стандарт (2026+) | Единый агент для метрик, логов и трейсов | Требует изучения Alloy конфигурации |

## Практические сценарии

### Быстрый старт

```bash
# Создание структуры каталогов
mkdir -p monitoring/{prometheus,alertmanager,grafana}
cd monitoring

# Запуск стека
docker compose up -d

# Проверка статусов и логов
docker compose ps
docker compose logs -f prometheus
```

### Безопасность и лимиты

1.  **Секреты:** Используйте `.env` файл для хранения паролей Grafana и токенов Alertmanager. Никогда не коммитьте `.env` в Git.
2.  **Лимиты ресурсов:** Обязательно ограничивайте CPU и RAM для каждого сервиса. Для production используйте `deploy.resources.limits` и `reservations`:

    ```yaml
    deploy:
      resources:
        limits:
          cpus: '2'
          memory: 2G
        reservations:
          cpus: '0.5'
          memory: 512M
    ```

3.  **User ID:** Запускайте контейнеры от не-root пользователя (UID 472 для Grafana), если используете bind mounts для данных.
4.  **Жёсткая изоляция (Hardening):** Для production добавьте в каждый сервис (кроме node-exporter и cadvisor, требующих привилегий):

    ```yaml
    security_opt:
      - no-new-privileges:true
      - seccomp:default
    cap_drop:
      - ALL
    cap_add:
      - NET_BIND_SERVICE  # Только если сервис слушает порт <1024
    read_only: true
    tmpfs:
      - /tmp
      - /var/run
    ```

    **Примечание:** `read_only: true` требует монтирования tmpfs для директорий, в которые контейнер должен записывать данные (например, `/tmp`, `/var/run`).

5.  **Права на тома:** Для bind mounts убедитесь, что UID/GID пользователя внутри контейнера совпадает с владельцем директории на хосте:

    ```bash
    # Grafana (UID 472)
    sudo chown -R 472:472 ./grafana/provisioning
    # Alertmanager (UID 65534)
    sudo chown -R 65534:65534 ./alertmanager_data
    ```

### Развёртывание в изолированной среде (Air-gapped)

В закрытом контуре без доступа к интернету используйте следующий алгоритм:

**На хосте с интернетом:**

```bash
# 1. Создайте каталог для образов
mkdir -p /tmp/prom-images && cd /tmp/prom-images

# 2. Скачайте все необходимые образы
docker pull prom/prometheus:v3.13.1
docker pull grafana/grafana:v13.2.3
docker pull prom/alertmanager:v0.33.1
docker pull prom/node-exporter:v1.12.1
docker pull ghcr.io/google/cadvisor:v0.60.6

# 3. Сохраните образы в единый tar-архив
docker save -o prom-images.tar \
  prom/prometheus:v3.13.1 \
  grafana/grafana:v13.2.3 \
  prom/alertmanager:v0.33.1 \
  prom/node-exporter:v1.12.1 \
  ghcr.io/google/cadvisor:v0.60.6

# 4. Вычислите контрольную сумму
sha256sum prom-images.tar > prom-images.tar.sha256

# 5. Перенесите архив на изолированный хост (USB/NFS)
```

**На изолированном хосте:**

```bash
# 1. Загрузите образы
docker load -i prom-images.tar

# 2. Проверьте целостность (опционально)
sha256sum -c prom-images.tar.sha256

# 3. Запустите стек
docker compose up -d
```

**Альтернатива — приватный реестр (Harbor):** Для регулярных обновлений разверните Harbor в изолированной среде и загружайте образы через `docker tag` + `docker push`. Настройте Docker daemon на изолированном хосте на использование реестра как mirror.

### Резервное копирование и восстановление

#### Онлайн-бэкап томов (с запущенными контейнерами)

```bash
# Бэкап тома Prometheus (TSDB)
docker run --rm \
  -v prometheus_data:/data \
  -v $(pwd)/backups:/backup \
  alpine tar -czf /backup/prometheus-$(date +%Y%m%d).tar.gz -C /data .

# Бэкап тома Grafana
docker run --rm \
  -v grafana_data:/data \
  -v $(pwd)/backups:/backup \
  alpine tar -czf /backup/grafana-$(date +%Y%m%d).tar.gz -C /data .

# Бэкап конфигурационных файлов
tar -czf backups/config-$(date +%Y%m%d).tar.gz \
  compose.yml \
  .env \
  prometheus/ \
  alertmanager/
```

#### Восстановление

```bash
# Остановка стека
docker compose down

# Восстановление томов
docker volume create prometheus_data
docker run --rm \
  -v prometheus_data:/data \
  -v $(pwd)/backups:/backup \
  alpine tar -xzf /backup/prometheus-20260822.tar.gz -C /data

# Запуск стека
docker compose up -d
```

#### Автоматизация (cron)

```bash
# /etc/cron.d/docker-monitoring-backup
0 2 * * * root /opt/scripts/monitoring-backup.sh >> /var/log/monitoring-backup.log 2>&1
```

### Обновление и откат

#### Обновление отдельных сервисов

```bash
# Просмотр доступных версий
docker images prom/prometheus

# Обновление образа и пересоздание контейнера
docker compose pull prometheus
docker compose up -d --force-recreate prometheus

# Проверка работоспособности
docker compose ps prometheus
docker compose logs -f prometheus
```

#### Откат на предыдущую версию

```bash
# Откат через предыдущий тег образа
docker compose pull prom/prometheus:v3.12.0
docker compose up -d --force-recreate prometheus

# Или через git, если compose.yml хранится в VCS
git revert HEAD~1 --no-commit
docker compose up -d --force-recreate
```

#### Полное обновление стека

```bash
# Обновление всех образов
docker compose pull

# Пересоздание всех сервисов с проверкой healthcheck
docker compose up -d --force-recreate

# Валидация
docker compose ps
```

### Очистка и удаление

#### Остановка стека без удаления данных

```bash
docker compose down
# Тома и данные сохраняются
```

#### Полная очистка (с удалением данных)

```bash
# Остановка и удаление контейнеров, сетей + томов
docker compose down -v

# Дополнительная очистка неиспользуемых образов и слоёв
docker image prune -a --filter "until=720h"
docker volume prune -f
```

#### Удаление конкретного сервиса

```bash
# Остановка и удаление только Prometheus
docker compose stop prometheus
docker compose rm prometheus

# Удаление тома (если данные не нужны)
docker volume rm prometheus_data
```

### Проверка компонентов

| Компонент | URL | Метод проверки |
|---|---|---|
| **Prometheus** | `http://localhost:9090` | Проверьте **Status → Targets**. Все цели должны быть `UP`. |
| **Grafana** | `http://localhost:3000` | Вход `admin`/`admin`. Проверьте подключение [Data Source](../../../Grafana/grafana_datasources.md). |
| **Alertmanager** | `http://localhost:9093` | Проверьте наличие конфигурации во вкладке **Status**. |

### Обслуживание и отладка

*   **Перезагрузка конфигурации:** Вместо перезапуска контейнера используйте hot reload:
    `curl -X POST http://localhost:9090/-/reload`
*   **Проверка синтаксиса:**
    `docker exec prometheus promtool check config /etc/prometheus/prometheus.yml`
*   **Просмотр ресурсов в реальном времени:**
    `docker stats`
*   **Очистка данных:** Для полного удаления томов при остановке используйте `docker compose down -v`.

### Расширение стека

| Компонент | Назначение | Ссылка |
|---|---|---|
| **Loki** | Агрегация и поиск логов | [Loki Docker Compose](../../../Loki/Docker_Compose/loki_docker_compose_setup.md) |
| **Tempo** | Трассировка запросов (Tracing) | [Tempo overview](../../../Tempo/index.md) |
| **Blackbox Exporter** | Проверка доступности (HTTP, ICMP, TCP) | [Blackbox Exporter](../../Exporters/blackbox/blackbox_exporter_installation_and_setup.md) |

## Диагностика и устранение неполадок

| Проблема | Причина | Решение |
|---|---|---|
| **Prometheus OOM** | Нет лимитов или `--auto-gomemlimit` | Добавьте лимиты в `deploy` и флаг запуска. |
| **cAdvisor 0 metrics** | Нет доступа к `docker.sock` | Проверьте монтирование `/var/run:/var/run:ro`. |
| **Grafana Login Fail** | Неверный пароль в `.env` | Проверьте переменную `GF_SECURITY_ADMIN_PASSWORD`. |
| **DNS-разрешение не работает** | Сервисы в разных сетях | Убедитесь, что все сервисы находятся в одной сети Compose. |
| **Volume permission denied** | Несоответствие UID/GID | Выполните `chown` на хосте под нужным UID (472 для Grafana, 65534 для Alertmanager). |
| **Диск заполнен логами** | Нет ротации | Добавьте `logging` с `max-size` и `max-file` или переключитесь на драйвер `local`. |
| **Time drift в графиках** | Разные часовые пояса | Монтируйте `/etc/localtime` и задайте `TZ` во всех сервисах. |
| **Prometheus не видит targets** | Неверный DNS или сеть | Проверьте `docker compose exec prometheus ping <service-name>`. |

## Дополнительная информация

### Актуальные версии образов (Август 2026)

| Компонент | Образ | Версия |
|---|---|---|
| **Prometheus** | `prom/prometheus` | v3.13.1 |
| **Grafana** | `grafana/grafana` | v13.2.3 |
| **Alertmanager** | `prom/alertmanager` | v0.33.1 |
| **Node Exporter** | `prom/node-exporter` | v1.12.1 |
| **cAdvisor** | `ghcr.io/google/cadvisor` | v0.60.5 |

### Связанные темы

* [Конфигурация Docker Compose](./docker-compose_config.md) — детализация YAML, healthchecks, security.
* [Конфигурация Prometheus](./prometheus_config.md) — scrape-цели, правила и алертинг.
* [Конфигурация Alertmanager](./docker_compose_alertmanager_config.md) — шаблоны и маршруты.
* [Мониторинг Docker-контейнеров](../../../Docker/Docker_metrics/docker_prometheus_integration.md) — интеграция с демоном Docker.
* [Prometheus overview](../../overview.md) — архитектура и внутреннее устройство.
* [Grafana overview](../../../Grafana/grafana_overview.md) — возможности визуализации.
* [HA Setup](../ha_setup.md) — практическое развертывание HA Prometheus + Alertmanager.
* [Capacity Planning](../capacity_planning.md) — формулы расчёта ресурсов.
