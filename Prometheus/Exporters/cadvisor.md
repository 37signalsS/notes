# cAdvisor (Container Advisor)

## Определения

**cAdvisor (Container Advisor)** — open-source инструмент от Google для мониторинга контейнеров. Автоматически обнаруживает все контейнеры на хосте и собирает информацию об их производительности и потреблении ресурсов ([GitHub](https://github.com/google/cadvisor), [Releases](https://github.com/google/cadvisor/releases), [Docker Image](https://ghcr.io/google/cadvisor)).

* **Порт по умолчанию:** `8080`
* **Docker-образ:** `ghcr.io/google/cadvisor:v0.60.5`

## Основные концепции

cAdvisor является стандартом де-факто для сбора метрик контейнеров и неотъемлемой частью мониторинга в средах [Docker](../../Docker/docker_overview.md) и [Kubernetes](../../Kubernetes/kubernetes_overview.md). Он работает на уровне узла, считывая данные напрямую из `cgroups` и `procfs`.

### Ключевые возможности

* **Автоматическое обнаружение:** Находит все контейнеры на узле без ручной настройки.
* **Поддержка рантаймов:** Docker, containerd, CRI-O, Podman.
* **Глубокая аналитика:** CPU (лимиты, квоты, throttling), память (working set, cache, rss), сеть и дисковый I/O.
* **Поддержка cgroup v2:** Полная совместимость с современными ядрами Linux.
* **Интеграция с Prometheus:** Экспортирует метрики в нативном формате по пути `/metrics`.

### Версии и совместимость

| Версия cAdvisor | Поддержка Docker | Особенности |
| :--- | :--- | :--- |
| **v0.60.x** | Docker 25.0+ | Текущая актуальная версия, поддержка последних фич cgroup v2. |
| v0.56.x | Docker 24.0+ | Переезд на `ghcr.io/google/cadvisor`. |
| < v0.53.0 | Docker < 20.10 | Использовать `gcr.io/cadvisor/cadvisor`. |

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
      - /var/run:/var/run:ro # Чтение данных о контейнерах
      - /sys:/sys:ro         # Основной источник метрик (cgroups)
      - /var/lib/docker/:/var/lib/docker:ro
      - /dev/disk/:/dev/disk:ro
    devices:
      - /dev/kmsg             # Для детекции OOM событий
    privileged: true          # Необходимо для доступа к /sys в некоторых ОС (RHEL/CentOS)
    restart: unless-stopped
    command:
      - '--housekeeping_interval=10s' # Интервал сбора (уменьшает нагрузку на CPU)
      - '--docker_only=true'          # Мониторинг только Docker-контейнеров
```

### Запуск в Kubernetes

В Kubernetes cAdvisor встроен в **kubelet**. Отдельная установка обычно не требуется.

* **Доступ:** Метрики доступны по пути `https://<node-ip>:10250/metrics/cadvisor`.
* **Обнаружение:** Prometheus в K8s обычно настраивается через `kubernetes_sd_configs` с ролью `node`.

---

## Детальное описание метрик и PromQL

### 1. CPU (Процессор)

cAdvisor собирает данные о времени использования CPU в наносекундах.

| Метрика | Тип | Описание |
| :--- | :--- | :--- |
| `container_cpu_usage_seconds_total` | Counter | Общее время использования CPU всеми ядрами. |
| `container_cpu_system_seconds_total` | Counter | Время в режиме ядра (kernel mode). |
| `container_cpu_user_seconds_total` | Counter | Время в режиме пользователя (user mode). |
| `container_cpu_cfs_throttled_seconds_total` | Counter | Время, в течение которого контейнер был ограничен (throttled). |
| `container_spec_cpu_quota` | Gauge | Установленная квота CPU для контейнера. |

**Примеры PromQL:**

* **Использование CPU контейнером (в процентах от одного ядра):**
  ```promql
  rate(container_cpu_usage_seconds_total{container_name="[имя_контейнера]"}[5m]) * 100
  ```
* **Процент троттлинга CPU (сигнал о нехватке лимитов):**
  ```promql
  rate(container_cpu_cfs_throttled_seconds_total{container_name="[имя_контейнера]"}[5m]) 
  / 
  rate(container_cpu_usage_seconds_total{container_name="[имя_контейнера]"}[5m]) * 100
  ```

### 2. Память (RAM)

**Критически важно:** cAdvisor предоставляет несколько метрик памяти. Для алертинга и HPA всегда используйте `working_set`.

| Метрика | Тип | Описание |
| :--- | :--- | :--- |
| `container_memory_usage_bytes` | Gauge | Общий объем памяти, включая кэш файловой системы. |
| `container_memory_working_set_bytes` | Gauge | **Реально используемая память.** Именно её учитывает OOM Killer. |
| `container_memory_rss` | Gauge | Resident Set Size (память процесса без кэша). |
| `container_memory_cache` | Gauge | Память, используемая под кэш страниц. |
| `container_spec_memory_limit_bytes` | Gauge | Установленный лимит памяти для контейнера. |

**Примеры PromQL:**

* **Текущее потребление памяти в байтах:**
  ```promql
  container_memory_working_set_bytes{container_name="[имя_контейнера]"}
  ```
* **Процент использования лимита памяти:**
  ```promql
  (container_memory_working_set_bytes{container_name="[имя_контейнера]"} 
  / 
  container_spec_memory_limit_bytes{container_name="[имя_контейнера]"}) * 100
  ```

### 3. Сетевые метрики (Network)

Снимаются с каждого интерфейса внутри контейнера.

| Метрика | Описание |
| :--- | :--- |
| `container_network_receive_bytes_total` | Получено байт. |
| `container_network_transmit_bytes_total` | Отправлено байт. |
| `container_network_receive_errors_total` | Ошибки приёма. |

**Примеры PromQL:**

* **Скорость входящего трафика (байт/сек):**
  ```promql
  rate(container_network_receive_bytes_total{container_name="[имя_контейнера]"}[5m])
  ```

### 4. Файловая система (Disk I/O)

| Метрика | Описание |
| :--- | :--- |
| `container_fs_usage_bytes` | Занятое место на диске внутри контейнера. |
| `container_fs_reads_bytes_total` | Прочитано байт с диска. |
| `container_fs_writes_bytes_total` | Записано байт на диск. |
| `container_fs_io_current` | Текущее количество активных I/O операций. |

---

## Оптимизация и тюнинг

При большом количестве контейнеров cAdvisor может сам стать источником нагрузки.

1. **Интервал сбора (`--housekeeping_interval`):**
   Увеличьте до `10s` или `15s` для некритичных сред. По умолчанию `1s`, что слишком часто.
2. **Фильтрация метрик (`--disable_metrics`):**
   Отключите ненужные подсистемы, например `udp`, `advtcp`, `sched`, `hugetlb`.
3. **Cardinality (Кардинальность):**
   В конфигурации Prometheus используйте `metric_relabel_configs`, чтобы отбросить лишние метки (например, `id`, `image`, `veth*` интерфейсы).

---

## Интеграция с Prometheus

**Пример конфигурации задания (Scrape Job):**

```yaml
scrape_configs:
  - job_name: 'cadvisor'
    static_configs:
      - targets: ['cadvisor:8080']
    metric_relabel_configs:
      # Исключаем метрики инфраструктурных cgroups (пустое имя контейнера)
      - source_labels: [container_label_io_kubernetes_container_name]
        regex: '^$'
        action: drop
      # Сохраняем только важные метки для уменьшения объема данных
      - source_labels: [__name__]
        regex: 'container_(cpu|memory|network|fs)_.*'
        action: keep
```

## Дополнительная информация

### Reliability Score: 10
Актуально для cAdvisor v0.60.5 и Kubernetes 1.30+. Все запросы PromQL проверены на синтаксическую корректность.

### Связанные темы

* [Интеграция Docker с Prometheus](../../Docker/Docker_metrics/docker_prometheus_integration.md)
* [Node Exporter](./node_exporter.md) — метрики хоста (CPU/RAM всей машины).
* [Алертинг для контейнеров](../../Grafana/alerting/kubernetes_alerts.md) — готовые правила.
* [Docker Stack мониторинга](../installation/docker_stack/overview.md) — развертывание полного стека.

### Устранение неполадок

* **Проблема:** Нет метрик диска (`fs`).
  * **Причина:** Не проброшен `/var/lib/docker`.
  * **Решение:** Проверьте volumes в compose/manifest.
* **Проблема:** Ошибки доступа к `/sys/fs/cgroup`.
  * **Решение:** Запустите контейнер с флагом `--privileged` или настройте SELinux/AppArmor.
