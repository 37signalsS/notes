# Деплой cAdvisor и сбор метрик контейнеров

**Актуально для:** Docker Engine 20.10+, cAdvisor v0.60.x

## Определения

**cAdvisor (Container Advisor)** — open-source инструмент от Google для мониторинга потребления ресурсов и производительности запущенных контейнеров. Агент cAdvisor работает на каждом хосте, автоматически обнаруживает все контейнеры и собирает детальные метрики из cgroups. Экспортирует данные в формате Prometheus через HTTP-эндпоинт `/metrics`.

**Docker-only режим** — конфигурация cAdvisor, при которой инструмент игнорирует системные cgroups ОС и отслеживает только контейнеры Docker. Включается флагом `--docker_only=true`.

**Housekeeping interval** — интервал сбора метрических снимков cAdvisor. По умолчанию 1s; увеличение до 10s снижает нагрузку на CPU и объем данных в Prometheus.

**Prometheus Exporter** — приложение, преобразующее внутренние данные системы в формат метрик Prometheus и предоставляющее их через HTTP-эндпоинт (обычно `/metrics`). cAdvisor является exporter'ом для контейнерных метрик, Node Exporter — для метрик хоста, Docker Engine metrics — для метрик демона.

**Scrape** — механизм Prometheus периодического получения (опроса) метрик с целевых эндпоинтов. Конфигурация scrape определяет целевые адреса (`targets`), интервал опроса (`scrape_interval`), параметры аутентификации и relabeling.

## Предварительные требования

- **Docker Engine:** 20.10 или выше (рекомендуется 24.0+)
- **Ядро Linux:** cgroup v2 требует ядро v4.15+ (v5.2+ рекомендуется)
- **Права доступа:** для монтирования `/sys/fs/cgroup` и `/var/run/docker.sock` требуется root или `--privileged`
- **Порт:** 8080/tcp должен быть доступен для Prometheus
- **Образ:** `ghcr.io/google/cadvisor:v0.60.6` (реестр `gcr.io` устарел начиная с v0.56.x)
- **Среда:** Linux. На Windows/macOS cAdvisor не предоставляет доступ к cgroups хоста.

## Практические сценарии

### 1. Деплой cAdvisor (standalone)

Запуск cAdvisor как отдельного контейнера с монтированием необходимых путей:

```bash
docker run -d \
  --name cadvisor \
  --restart unless-stopped \
  -p 8080:8080 \
  -v /:/rootfs:ro \
  -v /var/run:/var/run:ro \
  -v /sys:/sys:ro \
  -v /var/lib/docker/:/var/lib/docker:ro \
  -v /dev/disk/:/dev/disk:ro \
  --privileged \
  --device=/dev/kmsg \
  ghcr.io/google/cadvisor:v0.60.6
```

**Параметры:**
- `-v /:/rootfs:ro` — корневая ФС хоста (для определения типа ОС и размера диска)
- `-v /var/run:/var/run:ro` — Docker socket (для обнаружения контейнеров)
- `-v /sys:/sys:ro` — sysfs (данные cgroups)
- `-v /var/lib/docker/:/var/lib/docker:ro` — слои образов
- `--privileged` — доступ к cgroups v1/v2 (альтернатива — конкретные capabilities)
- `--device=/dev/kmsg` — kernel messages для детекции OOM событий

**Проверка:**
```bash
curl -s http://localhost:8080/metrics | head -20
# → HELP container_cpu_usage_seconds_total ...
# → TYPE container_cpu_usage_seconds_total counter
```

**Веб-интерфейс:** `http://localhost:8080` — встроенная панель с графиками по каждому контейнеру.

### 2. cAdvisor в Docker Compose (полный стек)

Деплой Prometheus + cAdvisor + Grafana:

```yaml
version: '3.8'

services:
  cadvisor:
    image: ghcr.io/google/cadvisor:v0.60.6
    container_name: cadvisor
    restart: unless-stopped
    ports:
      - "8080:8080"
    volumes:
      - /:/rootfs:ro
      - /var/run:/var/run:ro
      - /sys:/sys:ro
      - /var/lib/docker/:/var/lib/docker:ro
      - /dev/disk/:/dev/disk:ro
    privileged: true
    devices:
      - /dev/kmsg
    networks:
      - monitoring
    command:
      - '--housekeeping_interval=10s'
      - '--docker_only=true'
      - '--disable_metrics=advtcp,udp,sched,hugetlb'

  prometheus:
    image: prom/prometheus:v3.14.0
    container_name: prometheus
    restart: unless-stopped
    ports:
      - "9090:9090"
    volumes:
      - ./prometheus.yml:/etc/prometheus/prometheus.yml:ro
      - prometheus_data:/prometheus
    command:
      - '--config.file=/etc/prometheus/prometheus.yml'
      - '--storage.tsdb.retention.time=30d'
    networks:
      - monitoring

  grafana:
    image: grafana/grafana:13.2.3
    container_name: grafana
    restart: unless-stopped
    ports:
      - "3000:3000"
    volumes:
      - grafana_data:/var/lib/grafana
    environment:
      - GF_SECURITY_ADMIN_PASSWORD=admin
    networks:
      - monitoring

volumes:
  prometheus_data:
  grafana_data:

networks:
  monitoring:
    driver: bridge
```

### 3. Production-hardened деплой

Для production сред рекомендуется дополнительная изоляция и ограничение ресурсов:

```yaml
services:
  cadvisor:
    image: ghcr.io/google/cadvisor:v0.60.6
    container_name: cadvisor
    restart: unless-stopped
    ports:
      - "8080:8080"
    volumes:
      - /:/rootfs:ro
      - /var/run:/var/run:ro
      - /sys:/sys:ro
      - /var/lib/docker/:/var/lib/docker:ro
      - /dev/disk/:/dev/disk:ro
    devices:
      - /dev/kmsg
    read_only: true
    tmpfs:
      - /tmp
    networks:
      - monitoring
    command:
      - '--housekeeping_interval=10s'
      - '--docker_only=true'
      - '--disable_metrics=advtcp,udp,sched,hugetlb'
    deploy:
      resources:
        limits:
          cpus: '0.5'
          memory: 128M
        reservations:
          cpus: '0.1'
          memory: 64M
```

**Примечания:**
- `read_only: true` + `tmpfs` предотвращают запись в контейнерный слой
- `deploy.resources` ограничивают потребление ресурсов самим cAdvisor
- `reservations.cpus` в compose (non-Swarm) не применяется — работает только `reservations.memory` (soft limit); `limits` применяются полностью
- Вместо `--privileged` можно использовать capabilities: `--cap-add SYS_ADMIN` + `--security-opt apparmor=unconfined`, но это менее переносимо между дистрибутивами

### 4. Конфигурация Prometheus scrape

Файл `prometheus.yml` для сбора метрик с cAdvisor:

```yaml
global:
  scrape_interval: 15s
  evaluation_interval: 15s

scrape_configs:
  # Метрики cAdvisor (per-container)
  - job_name: 'cadvisor'
    static_configs:
      - targets: ['cadvisor:8080']
    scrape_interval: 10s
    metric_relabel_configs:
      - source_labels: [container_name]
        regex: '^$'
        action: drop

  # Метрики Docker Engine (daemon stats)
  - job_name: 'docker-engine'
    static_configs:
      - targets: ['host.docker.internal:9323']
```

**Динамическое обнаружение контейнеров (docker_sd_config):**

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

**Запуск контейнера с лейблами для автоматического обнаружения:**

```bash
docker run -d \
  --name my-app \
  -l prometheus_scrape=true \
  -l prometheus_port=8080 \
  -l prometheus_path=/metrics \
  -l prometheus_job=my-application \
  my-app:latest
```

## Валидация

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

# 6. Проверка OOM детекции (если смонтирован /dev/kmsg)
curl -s http://localhost:8080/metrics | grep container_oom_events_total
```

## Диагностика и устранение неполадок

### permission denied на /sys/fs/cgroup

- **Причина:** Недостаточно прав или SELinux/AppArmor блокируют доступ.
- **Решение:** Используйте `--privileged` или смонтируйте `/sys/fs/cgroup:/sys/fs/cgroup:ro`. Для RHEL/CentOS с SELinux добавьте `:z` или `:Z` к mount опции.

### cAdvisor не видит контейнеры

- **Причина:** `/var/run/docker.sock` не смонтирован или Docker daemon не запущен.
- **Решение:** Проверьте mounts: `docker inspect cadvisor | grep -A5 Mounts`. Убедитесь, что socket доступен: `ls -la /var/run/docker.sock`.

### Метрики не появляются в Prometheus

- **Причина:** Неправильный `scrape_interval`, firewall, или cAdvisor не отвечает.
- **Диагностика:**
  ```bash
  # Проверка доступности с хоста Prometheus
  curl -s http://cadvisor-host:8080/metrics | wc -l
  
  # Проверка targets в Prometheus UI
  # http://prometheus:9090/targets
  ```
- **Решение:** Проверьте сетевую связность, firewall правила, и конфигурацию `scrape_configs`.

### Высокий CPU на больших кластерах

- **Причина:** По умолчанию cAdvisor собирает метрики каждую 1s и экспортирует все подсистемы.
- **Решение:** Увеличьте `--housekeeping_interval` до `10s` или `15s`. Отключите ненужные метрики: `--disable_metrics=advtcp,udp,sched,hugetlb`. Используйте `metric_relabel_configs` для отсечения лишних меток.

### Устаревший образ

- **Причина:** Уязвимости безопасности или несовместимость с новыми версиями Docker/cgroups.
- **Решение:** Обновляйте до актуальной версии. Проверяйте releases на GitHub: `ghcr.io/google/cadvisor`.

### cgroups v1/v2 конфликт

- **Причина:** Хост использует смешанную конфигурацию или неправильные пути.
- **Диагностика:**
  ```bash
  stat -f /sys/fs/cgroup | head -5
  mount | grep cgroup
  ```
- **Решение:** Для cgroup v2 используйте `--privileged` или убедитесь, что монтирование `/sys` включает `cgroup2fs`.

### Метрики диска (fs) отсутствуют

- **Причина:** Не проброшен `/var/lib/docker` или неправильный путь.
- **Решение:** Проверьте volumes в compose/manifest. Убедитесь, что `/var/lib/docker` смонтирован как `:ro`.

## Лучшие практики

- **Используйте `ghcr.io/google/cadvisor`** вместо устаревшего `gcr.io`. Начиная с v0.56.x образы публикуются только в GitHub Container Registry.
- **Включайте `--docker_only=true`** в production. Это предотвращает утечку метрик системных процессов ОС и снижает кардинальность.
- **Ограничьте `housekeeping_interval`** значением `10s` или выше для сред с >100 контейнеров. Интервал 1s создает избыточную нагрузку.
- **Монтируйте `/dev/kmsg`** для детекции OOM событий. Без этого cAdvisor не может фиксировать kills, и единственный источник — `dmesg` хоста.
- **Не используйте `--privileged` без необходимости.** В tightly secured средах предпочитайте минимальный набор capabilities. Однако для универсальности между дистрибутивами `--privileged` остается практичным выбором.
- **Настройте `metric_relabel_configs`** в Prometheus для отсечения инфраструктурных метрик (пустые `container_name`, неиспользуемые сети). Это снижает объем TSDB на 40-60%.
- **Используйте `read_only: true`** для контейнера cAdvisor в production. Это ограничивает blast radius при компрометации.
- **Мониторьте сам cAdvisor** через его же метрики (`container_cpu_usage_seconds_total`, `container_memory_working_set_bytes`). При деградации cAdvisor автоматика теряет глаза.
- **Обновляйте образ регулярно** (не реже квартала). cAdvisor активно развивается, и новые версии исправляют поддержку cgroup v2 и метрики.
- **Для >500 контейнеров на хост** рассмотрите federation или развертывание cAdvisor на выделенных узлах мониторинга.

## Дополнительная информация

Нативные метрики Docker и cAdvisor дополняют друг друга. Используйте оба источника для полной картины.

- **[Нативные метрики Docker](./docker_native_metrics.md)** — быстрая диагностика через `docker stats`, встроенный экспортер демона (порт 9323).
- **[Интеграция Docker с Prometheus](./docker_prometheus_integration.md)** — полная конфигурация сбора метрик Docker Engine.
- **[Справочник метрик Docker Engine](./docker_engine_metrics_reference.md)** — метрики демона `engine_daemon_` с версиями.
- **[Grafana для Docker-метрик](./docker_grafana_dashboards.md)** — дашборды, провиженинг, алерты, корреляция с логами.
- **[Docker метрики: вопросы на собеседованиях](./docker_metrics_interview_qa.md)** — краткие ответы на вопросы SRE-собеседований.
- **[cAdvisor (Container Advisor)](../../Prometheus/Exporters/cadvisor.md)** — SSoT: полный справочник метрик, PromQL паттернов, Grafana дашбордов и правил алертинга.
- **[Node Exporter](../../Prometheus/Exporters/node_exporter.md)** — метрики хоста (диски, сеть, системные службы).
- **[Контрольные группы (cgroups)](../../Linux/Core/cgroups.md)** — теоретическая база механизмов ограничения ресурсов.
- **[Конфигурация Docker daemon](../docker_daemon_config.md)** — настройка `daemon.json`, включая `metrics-addr`.

**См. также:**
- **[cAdvisor в Docker Compose](../../Prometheus/installation/docker_stack/docker-compose_config.md)** — деплой cAdvisor как сервиса в Compose, permissions для `/sys/fs/cgroup`.
- **[Docker Stack мониторинга](../../Prometheus/installation/docker_stack/overview.md)** — полный стек мониторинга на Docker.
- **[Мониторинг удалённых хостов](../../Prometheus/installation/docker_stack/remote_hosts_monitoring.md)** — сбор метрик с внешних Docker-хостов.
