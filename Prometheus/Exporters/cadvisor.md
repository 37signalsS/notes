# cAdvisor (Container Advisor)

## Определения

**cAdvisor (Container Advisor)** — open-source инструмент от Google для мониторинга контейнеров. Автоматически обнаруживает все контейнеры на хосте и собирает информацию об их производительности и потреблении ресурсов.

* **Порт по умолчанию:** `8080`
* **Репозиторий:** [google/cadvisor](https://github.com/google/cadvisor)
* **Docker-образ:** `ghcr.io/google/cadvisor:v0.56.2`

> **Важно:** Начиная с v0.56.0, cAdvisor мигрировал с `gcr.io/cadvisor/cadvisor` на `ghcr.io/google/cadvisor`.

## Основные концепции

cAdvisor является стандартом де-факто для сбора метрик контейнеров и неотъемлемой частью мониторинга в средах [Docker](../../Docker/docker_overview.md) и [Kubernetes](../../Kubernetes/kubernetes_overview.md).

### Ключевые возможности

* Автоматическое обнаружение контейнеров на хосте
* Сбор метрик CPU, памяти, сети, файловой системы
* Экспорт метрик в формате Prometheus
* Встроенный веб-интерфейс с UI для просмотра метрик
* Минимальные требования к ресурсам
* Поддержка Docker, containerd, CRI-O

### Версии и совместимость

| Версия cAdvisor | Поддержка Docker | Репозиторий |
| :--- | :--- | :--- |
| v0.56.0+ | Docker 25.0+ | `ghcr.io/google/cadvisor` |
| v0.53.0 – v0.55.x | Docker 20.10+ | `gcr.io/cadvisor/cadvisor` |
| < v0.53.0 | Docker < 20.10 | `gcr.io/cadvisor/cadvisor` |

## Практические сценарии

### Запуск в Docker

**Docker Compose:**

```yaml
services:
  cadvisor:
    image: ghcr.io/google/cadvisor:v0.56.2
    container_name: cadvisor
    ports:
      - "8080:8080"
    volumes:
      - /:/rootfs:ro
      - /var/run:/var/run:rw
      - /sys:/sys:ro
      - /var/lib/docker/:/var/lib/docker:ro
      - /dev/disk/:/dev/disk:ro
    restart: unless-stopped
```

**Docker CLI:**

```bash
docker run \
  --volume=/:/rootfs:ro \
  --volume=/var/run:/var/run:rw \
  --volume=/sys:/sys:ro \
  --volume=/var/lib/docker/:/var/lib/docker:ro \
  --volume=/dev/disk/:/dev/disk:ro \
  --publish=8080:8080 \
  --detach=true \
  --name=cadvisor \
  --restart=unless-stopped \
  ghcr.io/google/cadvisor:v0.56.2
```

### Запуск в Kubernetes

**Helm (kube-prometheus-stack):**

cAdvisor уже встроен в kubelet и не требует отдельной установки. Метрики доступны через ServiceMonitor.

**Manifest (если нужен отдельный cAdvisor):**

```yaml
apiVersion: apps/v1
kind: DaemonSet
metadata:
  name: cadvisor
spec:
  selector:
    matchLabels:
      app: cadvisor
  template:
    metadata:
      labels:
        app: cadvisor
    spec:
      containers:
      - name: cadvisor
        image: ghcr.io/google/cadvisor:v0.56.2
        ports:
        - containerPort: 8080
        volumeMounts:
        - name: rootfs
          mountPath: /rootfs
          readOnly: true
        - name: var-run
          mountPath: /var/run
          readOnly: false
        - name: sys
          mountPath: /sys
          readOnly: true
        - name: docker-lib
          mountPath: /var/lib/docker
          readOnly: true
      volumes:
      - name: rootfs
        hostPath:
          path: /
      - name: var-run
        hostPath:
          path: /var/run
      - name: sys
        hostPath:
          path: /sys
      - name: docker-lib
        hostPath:
          path: /var/lib/docker
```

### Основные метрики

#### CPU

```
container_cpu_usage_seconds_total{container_name="myapp"}     # Общее время использования CPU
container_cpu_system_seconds_total{container_name="myapp"}    # Время в kernel mode
container_cpu_user_seconds_total{container_name="myapp"}      # Время в user mode
container_cpu_cfs_throttled_seconds_total                     # Время throttling CPU
container_cpu_load_average_10s                                # Средняя нагрузка за 10 сек
```

**Пример PromQL:** использование CPU контейнером в %

```promql
rate(container_cpu_usage_seconds_total{container_name="myapp"}[5m]) * 100
```

#### Память

```
container_memory_usage_bytes{container_name="myapp"}          # Общее использование памяти
container_memory_working_set_bytes{container_name="myapp"}    # Working set памяти
container_memory_cache{container_name="myapp"}                # Кэш память
container_memory_rss{container_name="myapp"}                  # RSS память
container_memory_swap{container_name="myapp"}                 # Swap память
container_memory_failcnt{container_name="myapp"}              # Счётчик неудач выделения памяти
```

**Пример PromQL:** использование памяти контейнером

```promql
container_memory_working_set_bytes{container_name="myapp"}
```

#### Сеть

```
container_network_receive_bytes_total{container_name="myapp", interface="eth0"}    # Получено байт
container_network_transmit_bytes_total{container_name="myapp", interface="eth0"}   # Отправлено байт
container_network_receive_packets_total{container_name="myapp"}                    # Получено пакетов
container_network_transmit_packets_total{container_name="myapp"}                   # Отправлено пакетов
container_network_receive_errors_total{container_name="myapp"}                     # Ошибки приёма
container_network_transmit_errors_total{container_name="myapp"}                    # Ошибки передачи
```

**Пример PromQL:** входящий трафик контейнера в байт/сек

```promql
rate(container_network_receive_bytes_total{container_name="myapp"}[5m])
```

#### Файловая система

```
container_fs_usage_bytes{container_name="myapp"}              # Использование ФС
container_fs_reads_bytes_total{container_name="myapp"}        # Прочитано байт
container_fs_writes_bytes_total{container_name="myapp"}       # Записано байт
container_fs_io_current                                       # Текущие I/O операции
```

#### Прочие метрики

```
container_start_time_seconds{container_name="myapp"}          # Время запуска контейнера
container_last_seen{container_name="myapp"}                   # Последнее время видимости
container_tasks_state{container_name="myapp", state="running"} # Состояние задач
container_spec_memory_limit_bytes{container_name="myapp"}     # Лимит памяти
container_spec_cpu_quota{container_name="myapp"}              # CPU quota
container_spec_cpu_period{container_name="myapp"}             # CPU period
```

### Интеграция с Prometheus

**Конфигурация scrape:**

```yaml
scrape_configs:
  - job_name: 'cadvisor'
    static_configs:
      - targets: ['cadvisor:8080']
    metric_relabel_configs:
      # Удалить ненужные метрики
      - source_labels: [__name__]
        regex: 'container_.*_seconds_total'
        action: keep
```

### Алертинг

**Контейнер использует много CPU:**

```yaml
- alert: ContainerHighCPU
  expr: rate(container_cpu_usage_seconds_total{container_name="myapp"}[5m]) > 0.8
  for: 10m
  labels:
    severity: warning
  annotations:
    summary: "Контейнер {{ $labels.container_name }} использует много CPU"
    description: "Использование CPU превышает 80%"
```

**Контейнер использует много памяти:**

```yaml
- alert: ContainerHighMemory
  expr: container_memory_working_set_bytes{container_name="myapp"} / container_spec_memory_limit_bytes{container_name="myapp"} > 0.9
  for: 5m
  labels:
    severity: warning
  annotations:
    summary: "Контейнер {{ $labels.container_name }} использует много памяти"
    description: "Использование памяти превышает 90% лимита"
```

**Контейнер перезапустился:**

```yaml
- alert: ContainerRestarted
  expr: increase(container_start_time_seconds{container_name="myapp"}[1h]) > 0
  labels:
    severity: warning
  annotations:
    summary: "Контейнер {{ $labels.container_name }} перезапустился"
    description: "Контейнер был перезапущен в течение последнего часа"
```

## Дополнительная информация

### Связка с Node Exporter

Для полной картины мониторинга хоста `cAdvisor` (метрики контейнеров) используется в связке с **[node_exporter](./node_exporter.md)** (метрики хост-системы):

* **cAdvisor:** метрики внутри контейнеров (CPU, память, сеть каждого контейнера)
* **node_exporter:** метрики хоста (общее использование ресурсов, диск, сеть хоста)

### Альтернативные инструменты

* **[draganm/missing-container-metrics](https://github.com/draganm/missing-container-metrics)** — для специфичных метрик, отсутствующих в cAdvisor
* **[Vector](../../Vector/Concepts/vector_overview.md)** — сбор метрик напрямую из cgroups
* **[Filebeat](../../ELK_Stack/Filebeat/filebeat_overview.md)** — сбор метрик и логов

### Связанные темы

* [Интеграция Docker с Prometheus](../../Docker/Docker_metrics/docker_prometheus_integration.md)
* [Нативные метрики Docker](../../Docker/Docker_metrics/docker_native_metrics.md)
* [Мониторинг Kubernetes](../../Kubernetes/monitoring.md)

### Официальные ресурсы

* [GitHub Repository](https://github.com/google/cadvisor)
* [Docker Image](https://ghcr.io/google/cadvisor)
* [Releases](https://github.com/google/cadvisor/releases)
