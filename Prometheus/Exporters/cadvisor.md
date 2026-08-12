# cAdvisor (Container Advisor)

## Определения

**cAdvisor (Container Advisor)** — специализированный инструмент с открытым исходным кодом от Google, предназначенный для анализа потребления ресурсов и мониторинга производительности работающих контейнеров. Он автоматически обнаруживает все контейнеры на хосте и собирает детальные метрики (CPU, память, диск, сеть).

*   **Порт по умолчанию:** `8080`
*   **Репозиторий:** [GitHub](https://github.com/google/cadvisor)
*   **Docker-образ:** `ghcr.io/google/cadvisor:v0.60.5` (актуально на 2026 год).

**cgroup v2** — современная подсистема ядра Linux для управления ресурсами. cAdvisor v0.60+ обеспечивает полную поддержку cgroup v2, что критично для современных дистрибутивов (Ubuntu 22.04+, RHEL 9+, Debian 12+), где используется единая иерархия контрольных групп.

**См. также:** [Экспортеры Prometheus: Обзор](./overview.md), [Интеграция Docker с Prometheus](../../Docker/Docker_metrics/docker_prometheus_integration.md).

## Основные концепции

cAdvisor является стандартом де-факто для сбора метрик контейнеров и неотъемлемой частью мониторинга в средах [Docker](../../Docker/docker_overview.md) и [Kubernetes](../../Kubernetes/kubernetes_overview.md). Он работает на уровне узла, считывая данные напрямую из `cgroups` и `procfs`.

### Ключевые возможности

*   **Автоматическое обнаружение:** Находит все контейнеры (Docker, containerd, CRI-O, Podman) на узле без ручной настройки.
*   **Поддержка рантаймов:** Помимо Docker, поддерживаются современные среды исполнения контейнеров через интеграцию с `containerd` и `CRI`.
*   **Глубокая аналитика:** CPU (лимиты, квоты, throttling), память (Working Set, Cache, RSS, RSS Hugetlb), сеть и дисковый I/O.
*   **Поддержка cgroup v2:** Полная совместимость с современными ядрами Linux.
*   **Детекция OOM-событий:** При монтировании `/dev/kmsg` cAdvisor может фиксировать факты выселения контейнеров по нехватке памяти (Out of Memory).
*   **Интеграция с Prometheus:** Экспортирует метрики в нативном формате по пути `/metrics`.

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
    image: ghcr.io/google/cadvisor:v0.60.5
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

## Детальное описание метрик и PromQL

### 1. Процессор (CPU)

cAdvisor собирает данные о времени использования CPU в наносекундах.

| Метрика | Тип | Описание |
| :--- | :--- | :--- |
| `container_cpu_usage_seconds_total` | Counter | Общее время использования CPU всеми ядрами. |
| `container_cpu_system_seconds_total` | Counter | Время в режиме ядра (kernel mode). |
| `container_cpu_user_seconds_total` | Counter | Время в режиме пользователя (user mode). |
| `container_cpu_cfs_throttled_seconds_total` | Counter | Время, в течение которого контейнер был ограничен (throttled). |
| `container_spec_cpu_quota` | Gauge | Установленная квота CPU для контейнера. |

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

### 2. Память (Memory)

**Критически важно:** cAdvisor предоставляет несколько метрик памяти. Для алертинга и HPA всегда используйте `working_set`. Метрика `usage` включает кэш файловой системы, который ОС может очистить.

| Метрика | Тип | Описание |
| :--- | :--- | :--- |
| `container_memory_usage_bytes` | Gauge | Общий объем памяти, включая кэш файловой системы. |
| `container_memory_working_set_bytes` | Gauge | **Реально используемая память.** Именно её учитывает OOM Killer. |
| `container_memory_rss` | Gauge | Resident Set Size (память процесса без кэша). |
| `container_memory_cache` | Gauge | Память, используемая под кэш страниц. |
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

### 3. Сетевые метрики (Network)

Снимаются с каждого интерфейса внутри контейнера.

| Метрика | Описание |
| :--- | :--- |
| `container_network_receive_bytes_total` | Получено байт. |
| `container_network_transmit_bytes_total` | Отправлено байт. |
| `container_network_receive_errors_total` | Ошибки приёма. |
| `container_network_receive_packets_dropped_total` | Отброшенные входящие пакеты. |

### 4. Файловая система (Disk I/O)

| Метрика | Описание |
| :--- | :--- |
| `container_fs_usage_bytes` | Занятое место на диске внутри контейнера. |
| `container_fs_reads_bytes_total` | Прочитано байт с диска. |
| `container_fs_writes_bytes_total` | Записано байт на диск. |
| `container_fs_io_current` | Текущее количество активных I/O операций. |

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

## Интеграция с Prometheus

**Пример конфигурации задания (Scrape Job):**

```yaml
scrape_configs:
  - job_name: 'cadvisor'
    static_configs:
      - targets: ['cadvisor:8080']
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

**См. также:**
*   [Интеграция Docker с Prometheus](../../Docker/Docker_metrics/docker_prometheus_integration.md)
*   [Node Exporter](./node_exporter.md) — метрики хоста (CPU/RAM всей машины).
*   [Алертинг для контейнеров](../../Grafana/alerting/kubernetes_alerts.md).
*   [Docker Stack мониторинга](../installation/docker_stack/overview.md).
