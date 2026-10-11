# cAdvisor (Container Advisor)

## Определения

**cAdvisor (Container Advisor)** — специализированный инструмент с открытым исходным кодом от Google, предназначенный для анализа потребления ресурсов и мониторинга производительности работающих контейнеров. Он автоматически обнаруживает все контейнеры на хосте и собирает детальные метрики (CPU, память, диск, сеть).

*   **Порт по умолчанию:** `8080`
*   **Репозиторий:** [GitHub](https://github.com/google/cadvisor)
*   **Docker-образ:** `ghcr.io/google/cadvisor:v0.60.6` (актуально на 2026 год).

**cgroup v2** — современная подсистема ядра Linux для управления ресурсами. cAdvisor v0.60+ обеспечивает полную поддержку cgroup v2, что критично для современных дистрибутивов (Ubuntu 22.04+, RHEL 9+, Debian 12+), где используется единая иерархия контрольных групп.

**См. также:** [Экспортеры Prometheus: Обзор](./overview.md), [Интеграция Docker с Prometheus](../../Docker/Docker_metrics/docker_prometheus_integration.md).

## Основные концепции

cAdvisor является стандартом де-факто для сбора метрик контейнеров и неотъемлемой частью мониторинга в средах [Docker](../../Docker/docker_overview.md) и [Kubernetes](../../Kubernetes/kubernetes_overview.md). Он работает на уровне узла, считывая данные напрямую из `cgroups` и `procfs`.

### Архитектура

```
┌─────────────────────────────────────────────────────────────┐
│                        Host (узел)                          │
│                                                             │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐                  │
│  │Container │  │Container │  │Container │                  │
│  │    A     │  │    B     │  │    C     │                  │
│  └────┬─────┘  └────┬─────┘  └────┬─────┘                  │
│       │              │              │                        │
│       ▼              ▼              ▼                        │
│  ┌─────────────────────────────────────────────┐            │
│  │              cgroups v1/v2                  │            │
│  │  /sys/fs/cgroup/.../<id>/cpu.stat          │            │
│  │  /sys/fs/cgroup/.../<id>/memory.stat       │            │
│  │  /sys/fs/cgroup/.../<id>/io.stat           │            │
│  └──────────────────┬──────────────────────────┘            │
│                     │                                       │
│                     ▼                                       │
│  ┌─────────────────────────────────────────────┐            │
│  │            cAdvisor Agent                   │            │
│  │  • Считывает данные из cgroups              │            │
│  │  • Агрегирует по контейнерам                │            │
│  │  • Предоставляет /metrics endpoint          │            │
│  │  • Встроенный UI для диагностики            │            │
│  └──────────────────┬──────────────────────────┘            │
│                     │ :8080                                  │
│                     ▼                                       │
│              Prometheus                                     │
│              (scrape / service discovery)                   │
└─────────────────────────────────────────────────────────────┘
```

### Ключевые возможности

*   **Автоматическое обнаружение:** Находит все контейнеры (Docker, containerd, CRI-O, Podman) на узле без ручной настройки.
*   **Поддержка рантаймов:** Помимо Docker, поддерживаются современные среды исполнения контейнеров через интеграцию с `containerd` и `CRI`.
*   **Глубокая аналитика:** CPU (лимиты, квоты, throttling), память (Working Set, Cache, RSS, RSS Hugetlb), сеть и дисковый I/O.
*   **Поддержка cgroup v2:** Полная совместимость с современными ядрами Linux.
*   **Детекция OOM-событий:** При монтировании `/dev/kmsg` cAdvisor может фиксировать факты выселения контейнеров по нехватке памяти (Out of Memory).
*   **Интеграция с Prometheus:** Экспортирует метрики в нативном формате по пути `/metrics`.
*   **Встроенный веб-интерфейс:** Доступен по порту `8080` для быстрой визуальной диагностики метрик по каждому контейнеру.

### Docker Engine Metrics vs cAdvisor

Docker предоставляет встроенный экспортер метрик (порт `9323`), который дополняет cAdvisor, но не заменяет его:

| Параметр | Docker Engine Metrics | cAdvisor |
| :--- | :--- | :--- |
| **Порт** | `9323` | `8080` |
| **Обнаружение** | Встроен в daemon | Отдельный агент |
| **Гранулярность** | Агрегированная статистика daemon | Per-container детализация |
| **Метрики** | Состояния контейнеров, health-check'и, таймеры операций, ошибки сборки | CPU, RAM, Network, Disk I/O, Processes |
| **Настройка** | `daemon.json` | `docker run` / Compose |
| **Данные** | Состояние Docker Engine | Потребление ресурсов каждым контейнером |
| **Применение** | Мониторинг самого демона | Мониторинг приложений в контейнерах |

**Рекомендация:** использовать оба источника одновременно. Docker Engine metrics для здоровья демона, cAdvisor — для детализации по контейнерам. Подробнее: [Деплой cAdvisor и сбор метрик контейнеров](../../Docker/Docker_metrics/docker_cadvisor_deployment.md).

### Версии и совместимость (2025–2026)

| Версия cAdvisor | Поддержка Docker | Особенности |
| :--- | :--- | :--- |
| **v0.60.x** | Docker 25.0+ | Текущая актуальная версия, поддержка последних фич cgroup v2. |
| **v0.56.x** | Docker 24.0+ | Переезд на `ghcr.io/google/cadvisor`. Предыдущий реестр `gcr.io` устарел. |
| **< v0.53.0** | Docker < 20.10 | Использовать только для legacy-систем. |

## Практические сценарии

### Запуск в Docker (Stand-alone)

Для корректной работы cAdvisor требуется доступ к системным директориям хоста.

**Docker Compose:**

```yaml
services:
  cadvisor:
     image: ghcr.io/google/cadvisor:v0.60.6
    container_name: cadvisor
    ports:
      - "8080:8080"
    volumes:
      - /:/rootfs:ro
      - /var/run:/var/run:ro     # Чтение данных о контейнерах
      - /sys:/sys:ro             # Основной источник метрик (cgroups)
      - /var/lib/docker/:/var/lib/docker:ro # Данные об образах и слоях
      - /dev/disk/:/dev/disk:ro  # Статистика дисков
    devices:
      - /dev/kmsg                # Для детекции OOM событий
    privileged: true             # Требуется для доступа к /sys в ОС с SELinux (RHEL/CentOS)
    restart: unless-stopped
    command:
      - '--housekeeping_interval=10s' # Интервал сбора (уменьшает нагрузку на CPU)
      - '--docker_only=true'          # Мониторинг только Docker-контейнеров
      - '--disable_metrics=advtcp,udp,sched,hugetlb' # Отключение ненужных метрик
```

### Запуск в Kubernetes

В Kubernetes cAdvisor встроен в **kubelet**. Отдельная установка обычно не требуется.

*   **Доступ:** Метрики доступны по пути `https://<node-ip>:10250/metrics/cadvisor`.
*   **Обнаружение:** Prometheus обычно настраивается через `kubernetes_sd_configs` с ролью `node`.
*   **Включение порта:** В старых версиях K8s требовался флаг `--cadvisor-port=4194`. В современных (1.18+) используется встроенный `metric-provider`.
*   **RBAC:** Для доступа к метрикам через API kubelet необходимы права `get`, `proxy` на `nodes/proxy` в ClusterRole.

## Детальное описание метрик и PromQL

### 1. Процессор (CPU)

cAdvisor собирает данные о времени использования CPU в наносекундах.

| Метрика | Тип | Описание |
| :--- | :--- | :--- |
| `container_cpu_usage_seconds_total` | Counter | Общее время использования CPU всеми ядрами. |
| `container_cpu_system_seconds_total` | Counter | Время в режиме ядра (kernel mode). |
| `container_cpu_user_seconds_total` | Counter | Время в режиме пользователя (user mode). |
| `container_cpu_cfs_throttled_seconds_total` | Counter | Время, в течение которого контейнер был ограничен (throttled). |
| `container_cpu_cfs_periods_total` | Counter | Количество периодов CFS (Completely Fair Scheduler). |
| `container_cpu_cfs_throttled_periods_total` | Counter | Количество периодов, в которых происходил throttling. |
| `container_spec_cpu_quota` | Gauge | Установленная квота CPU для контейнера. |
| `container_spec_cpu_period` | Gauge | Период CFS для квоты CPU. |

**Примеры PromQL:**

*   **Использование CPU контейнером (в процентах от одного ядра):**
    ```promql
    rate(container_cpu_usage_seconds_total{container_name!=""}[5m]) * 100
    ```
*   **Процент троттлинга CPU (сигнал о нехватке лимитов):**
    ```promql
    rate(container_cpu_cfs_throttled_seconds_total[5m]) 
    / 
    rate(container_cpu_usage_seconds_total[5m]) * 100
    ```
*   **Процент использования CPU от установленного лимита:**
    ```promql
    rate(container_cpu_usage_seconds_total{container!="",container!="POD"}[5m])
    /
    (container_spec_cpu_quota{container!="",container!="POD"} / container_spec_cpu_period{container!="",container!="POD"})
    * 100
    ```

### 2. Память (Memory)

**Критически важно:** cAdvisor предоставляет несколько метрик памяти. Для алертинга и HPA всегда используйте `working_set`. Метрика `usage` включает кэш файловой системы, который ОС может очистить.

| Метрика | Тип | Описание |
| :--- | :--- | :--- |
| `container_memory_usage_bytes` | Gauge | Общий объем памяти, включая кэш файловой системы. |
| `container_memory_working_set_bytes` | Gauge | **Реально используемая память.** Именно её учитывает OOM Killer. |
| `container_memory_rss` | Gauge | Resident Set Size (память процесса без кэша). |
| `container_memory_cache` | Gauge | Память, используемая под кэш страниц. |
| `container_memory_failures_total` | Counter | Количество событий нехватки памяти (OOM-событий). |
| `container_memory_failures_limit` | Counter | Количество событий нехватки памяти, близких к лимиту. |
| `container_spec_memory_limit_bytes` | Gauge | Установленный лимит памяти для контейнера. |

**Примеры PromQL:**

*   **Текущее потребление памяти в байтах:**
    ```promql
    container_memory_working_set_bytes{container_name!=""}
    ```
*   **Процент использования лимита памяти:**
    ```promql
    (container_memory_working_set_bytes{container_name!=""} 
    / 
    container_spec_memory_limit_bytes{container_name!=""} != 0) * 100
    ```
*   **Прогноз достижения лимита памяти (линейная экстраполяция):**
    ```promql
    predict_linear(
      container_memory_working_set_bytes{container!=""}[30m], 3600
    )
    /
    container_spec_memory_limit_bytes{container!=""} > 1.0
    ```

### 3. Сетевые метрики (Network)

Снимаются с каждого интерфейса внутри контейнера.

| Метрика | Тип | Описание |
| :--- | :--- | :--- |
| `container_network_receive_bytes_total` | Counter | Получено байт. |
| `container_network_transmit_bytes_total` | Counter | Отправлено байт. |
| `container_network_receive_errors_total` | Counter | Ошибки приёма. |
| `container_network_receive_packets_dropped_total` | Counter | Отброшенные входящие пакеты. |
| `container_network_transmit_packets_dropped_total` | Counter | Отброшенные исходящие пакеты. |

### 4. Файловая система (Disk I/O)

| Метрика | Тип | Описание |
| :--- | :--- | :--- |
| `container_fs_usage_bytes` | Gauge | Занятое место на диске внутри контейнера. |
| `container_fs_reads_bytes_total` | Counter | Прочитано байт с диска. |
| `container_fs_writes_bytes_total` | Counter | Записано байт на диск. |
| `container_fs_reads_total` | Counter | Количество операций чтения. |
| `container_fs_writes_total` | Counter | Количество операций записи. |
| `container_fs_io_current` | Gauge | Текущее количество активных I/O операций. |

### 5. Процессы и потоки (Processes)

| Метрика | Тип | Описание |
| :--- | :--- | :--- |
| `container_processes` | Gauge | Количество процессов в контейнере. |
| `container_threads` | Gauge | Количество потоков в контейнере. |
| `container_spec_pids_limit` | Gauge | Лимит количества процессов (PIDs). |

## Grafana дашборды

Готовые дашборды для визуализации метрик cAdvisor:

| ID | Назначение | Метрики |
| :--- | :--- | :--- |
| **14282** | cAdvisor Full | Детальные метрики CPU, RAM, Network, Disk I/O, Processes |
| **1229** | Docker и cAdvisor | CPU, RAM, Network контейнеров и хоста |
| **10619** | Docker Engine & Containerd | Расширенная статистика daemon + containerd |
| **11600** | Node Exporter Full | Метрики хоста (используется совместно с cAdvisor) |

Установка: Dashboards → Import → ввести ID → Load → выбрать источник данных Prometheus.

## Правила алертинга (Prometheus Recording & Alerting Rules)

Пример правил для мониторинга проблем контейнеров:

```yaml
groups:
  - name: container_alerts
    rules:
      # Высокое использование CPU (>80% от лимита)
      - alert: ContainerHighCpuUsage
        expr: |
          (
            rate(container_cpu_usage_seconds_total{container!="",container!="POD"}[5m])
            /
            (container_spec_cpu_quota{container!="",container!="POD"} / container_spec_cpu_period{container!="",container!="POD"})
          ) > 0.8
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "Контейнер {{ $labels.name }} — CPU >80%"
          dashboard_url: "http://grafana/dashboard/d/containers"

      # Память близка к лимиту (>90%)
      - alert: ContainerMemoryNearLimit
        expr: |
          (
            container_memory_working_set_bytes{container!="",container!="POD"}
            /
            container_spec_memory_limit_bytes{container!="",container!="POD"}
          ) > 0.9
        for: 2m
        labels:
          severity: critical
        annotations:
          summary: "Контейнер {{ $labels.name }} — память >90% от лимита"

      # OOM Killed
      - alert: ContainerOomKilled
        expr: increase(container_oom_events_total{container!="",container!="POD"}[5m]) > 0
        labels:
          severity: critical
        annotations:
          summary: "Контейнер {{ $labels.name }} завершен из-за OOM"

      # Высокий CPU Throttling
      - alert: ContainerCpuThrottling
        expr: |
          rate(container_cpu_cfs_throttled_seconds_total{container!="",container!="POD"}[5m])
          /
          rate(container_cpu_usage_seconds_total{container!="",container!="POD"}[5m]) > 0.25
        for: 10m
        labels:
          severity: warning
        annotations:
          summary: "Контейнер {{ $labels.name }} — CPU throttling >25%"
```

## Оптимизация и тюнинг

При большом количестве контейнеров cAdvisor может сам стать источником нагрузки.

1.  **Интервал сбора (`--housekeeping_interval`):**
    Увеличьте до `10s` или `15s` для некритичных сред. По умолчанию `1s`, что слишком часто.
2.  **Фильтрация метрик (`--disable_metrics`):**
    Отключите ненужные подсистемы, например `udp`, `advtcp`, `sched`, `hugetlb`. Это существенно снижает потребление памяти и CPU cAdvisor-ом.
3.  **Docker Only (`--docker_only`):**
    Предотвращает попытки мониторинга инфраструктурных cgroups самой ОС.
4.  **Снижение кардинальности (Cardinality):**
    В конфигурации Prometheus используйте `metric_relabel_configs`, чтобы отбросить лишние метки (например, `id`, `image`, `veth*` интерфейсы).

### Масштабирование и кардинальность

*   **До 100 контейнеров на узел:** один экземпляр cAdvisor, `scrape_interval: 10s`.
*   **100–500 контейнеров:** увеличьте `scrape_interval` до `30s`, используйте `metric_relabel_configs` для отсечения неиспользуемых метрик.
*   **Более 500 контейнеров:** рассмотрите federation или развертывание cAdvisor на выделенных узлах мониторинга.
*   **Оценка объема данных:** примерно 1–2 КБ на метрику в час при `scrape_interval: 15s`.

## Интеграция с Prometheus

### Статическая конфигурация

```yaml
scrape_configs:
  - job_name: 'cadvisor'
    static_configs:
      - targets: ['cadvisor:8080']
    scrape_interval: 10s
    metric_relabel_configs:
      # Исключаем метрики инфраструктурных cgroups (пустое имя контейнера)
      - source_labels: [container_name]
        regex: '^$'
        action: drop
      # Сохраняем только важные метки для уменьшения объема данных
      - source_labels: [__name__]
        regex: 'container_(cpu|memory|network|fs)_.*'
        action: keep
```

### Динамическое обнаружение (Docker Service Discovery)

```yaml
scrape_configs:
  - job_name: 'docker-containers'
    docker_sd_configs:
      - host: unix:///var/run/docker.sock
        refresh_interval: 5s
    relabel_configs:
      # Собирать метрики только с контейнеров с лейблом prometheus_scrape=true
      - source_labels: [__meta_docker_container_label_prometheus_scrape]
        regex: true
        action: keep

      # Установить job_name по лейблу
      - source_labels: [__meta_docker_container_label_prometheus_job]
        target_label: job

      # Установить путь для scrape по лейблу
      - source_labels: [__meta_docker_container_label_prometheus_path]
        target_label: __metrics_path__
        regex: (.+)

      # Добавить лейбл с именем контейнера
      - source_labels: [__meta_docker_container_name]
        target_label: container_name
```

### Kubernetes Service Discovery

```yaml
scrape_configs:
  - job_name: 'kubernetes-cadvisor'
    kubernetes_sd_configs:
      - role: node
    scheme: https
    tls_config:
      ca_file: /var/run/secrets/kubernetes.io/serviceaccount/ca.crt
    bearer_token_file: /var/run/secrets/kubernetes.io/serviceaccount/token
    relabel_configs:
      - source_labels: [__address__]
        replacement: kubernetes.default.svc:443
        target_label: __address__
      - source_labels: [__meta_kubernetes_node_label_kubernetes_io_hostname]
        replacement: /api/v1/nodes/${1}/proxy/metrics/cadvisor
        target_label: __metrics_path__
```

## Валидация и проверка

После развертывания cAdvisor выполните проверку:

```bash
# 1. Проверка доступности эндпоинта /metrics
curl -s http://localhost:8080/metrics | head -20
# → Ожидается: вывод метрик в формате Prometheus text exposition

# 2. Проверка работы веб-интерфейса
curl -s http://localhost:8080/ | head -20
# → Ожидается: HTML-страница с интерфейсом cAdvisor

# 3. Проверка обнаружения контейнеров
curl -s http://localhost:8080/metrics | grep container_cpu_usage_seconds_total | wc -l
# → Ожидается: количество контейнеров на хосте (минимум 1 для самого cAdvisor)

# 4. Проверка cgroup v2
stat -f /sys/fs/cgroup | head -5
# → Ожидается: cgroup2fs (для v2) или tmpfs (для v1)

# 5. Проверка в Prometheus
curl -s 'http://prometheus:9090/api/v1/targets' | jq '.data.activeTargets[] | select(.job=="cadvisor")'
# → Ожидается: health = "up", lastError = null
```

## Дополнительная информация

### Устранение неполадок (Troubleshooting)

*   **Нет метрик диска (`fs`):**
    *   **Причина:** Не проброшен `/var/lib/docker` или неправильный путь.
    *   **Решение:** Проверьте volumes в compose/manifest. Убедитесь, что `/var/lib/docker` смонтирован как `:ro`.
*   **Ошибки доступа к `/sys/fs/cgroup`:**
    *   **Решение:** Запустите контейнер с флагом `--privileged` или настройте политики SELinux/AppArmor. В современных ядрах с cgroup v2 убедитесь, что cgroup монтируется с правильными опциями.
*   **Пустые имена контейнеров в выводе:**
    *   **Причина:** cAdvisor собирает данные по всей иерархии cgroups, включая системные процессы ОС.
    *   **Решение:** Фильтруйте метрики в Prometheus, используя `container_name!=""`.
*   **`permission denied` на `/sys/fs/cgroup`:**
    *   **Решение:** Добавить `--privileged` или смонтировать `/sys/fs/cgroup:/sys/fs/cgroup:ro`.
*   **cAdvisor не видит контейнеры:**
    *   **Решение:** Проверить, примонтирован ли `/var/run/docker.sock` (для Docker) или доступен ли containerd socket.
*   **Метрики не появляются в Prometheus:**
    *   **Решение:** Проверить `scrape_interval` и доступность порта `8080`. Проверить firewall между Prometheus и cAdvisor.
*   **Высокий CPU на больших кластерах:**
    *   **Решение:** Увеличить `scrape_interval`, использовать `metric_relabel_configs`, отключить ненужные метрики (`--disable_metrics`).
*   **Устаревший образ:**
    *   **Решение:** Обновлять до последней версии (исправления безопасности). Проверять актуальность тега в репозитории.
*   **cgroups v1/v2 конфликт:**
    *   **Решение:** Определить версию: `stat -f /sys/fs/cgroup | head -5`; для v2 использовать `--privileged`.

**См. также:**
*   [Интеграция Docker с Prometheus](../../Docker/Docker_metrics/docker_prometheus_integration.md)
*   [Деплой cAdvisor и сбор метрик контейнеров](../../Docker/Docker_metrics/docker_cadvisor_deployment.md) — подробные сценарии развертывания.
*   [Node Exporter](./node_exporter.md) — метрики хоста (CPU/RAM всей машины).
*   [Алертинг для контейнеров](../../Grafana/alerting/kubernetes_alerts.md).
*   [Docker Stack мониторинга](../installation/docker_stack/overview.md).
