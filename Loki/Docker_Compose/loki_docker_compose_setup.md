# Практическая настройка Loki в Docker Compose

## Определения

**Loki** — горизонтально масштабируемая система агрегации логов от Grafana Labs, которая индексирует только метаданные (метки), а не полный текст логов. Это позволяет значительно снизить затраты на хранение и обработку данных по сравнению с традиционными полнотекстовыми поисковыми системами. Подробная архитектура: [loki_overview.md](../loki_overview.md).

**Docker Compose** — инструмент для определения и запуска многоконтейнерных Docker-приложений с помощью YAML-файлов. Он обеспечивает оркестрацию локальных сервисов, управление сетями и томами данных в рамках одного проекта.

**Grafana Alloy** — современный универсальный агент для сбора телеметрии (логов, метрик, трейсов). Построен на базе OpenTelemetry Collector и является официальной заменой Promtail и Grafana Agent.

**LogQL** — язык запросов, вдохновленный Prometheus (PromQL), используемый для фильтрации и анализа логов в Loki.

## Основные концепции

Для полноценного сбора логов в Docker с использованием Loki требуется три основных компонента. Информация актуальна на **август 2026 года**.

| Компонент | Назначение | Актуальная версия | Примечание |
| :--- | :--- | :--- | :--- |
| **Loki** | Сервер для приема, хранения и индексации логов | `3.7.5` | Основной бэкенд системы. Версия 3.x включает новый движок запросов и поддержку Bloom-фильтров. |
| **Grafana Alloy** | Универсальный агент для сбора телеметрии | `1.18.1` | **Рекомендуемый агент**. Поддерживает динамическое обнаружение контейнеров через Docker API. |
| **Grafana** | Визуализация и запросы (LogQL) | `13.1.3` | Единый UI для мониторинга. Включает новые инструменты Logs Drilldown. |
| **Promtail** | Агент для сбора логов (Legacy) | — | **Удален** начиная с версии 3.7.3. Поддержка прекращена в пользу Alloy. |

> **Важно:** Использование Promtail в новых проектах не рекомендуется. Alloy предоставляет более гибкую настройку пайплайнов обработки логов и нативную поддержку OpenTelemetry. Подробнее см. [Grafana Alloy](../../Grafana/grafana_alloy_overview.md).

## Практические сценарии

### Конфигурация Docker Compose

Ниже приведен современный пример `compose.yml` (Compose Spec) для развертывания стека логирования.

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

  alloy:
    image: grafana/alloy:v1.18.1
    container_name: monitoring-alloy
    volumes:
      - /var/run/docker.sock:/var/run/docker.sock:ro
      - ./alloy/config.alloy:/etc/alloy/config.alloy:ro
      - alloy_data:/var/lib/alloy
    command: run --storage.path=/var/lib/alloy /etc/alloy/config.alloy
    ports:
      - "12345:12345" # UI Alloy для отладки
    restart: always
    networks:
      - monitoring
    depends_on:
      - loki

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
    restart: always
    networks:
      - monitoring
    depends_on:
      - loki

volumes:
  loki_data:
  alloy_data:
  grafana_data:

networks:
  monitoring:
    driver: bridge
```

### Настройка Grafana Alloy

Конфигурация Alloy использует декларативный язык (HCL-like) для описания потоков данных.

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

// 3. Сбор логов и передача в приемник
loki.source.docker "local_docker" {
  host       = "unix:///var/run/docker.sock"
  targets    = discovery.relabel.docker_logs.output
  forward_to = [loki.write.local_loki.receiver]
}

// 4. Отправка данных в Loki API
loki.write "local_loki" {
  endpoint {
    url = "http://loki:3100/loki/api/v1/push"
    // Настройка батчинга для оптимизации производительности
    batch_size = 1048576 // 1MB
    batch_wait = "1s"
  }
}
```

### Конфигурация Loki (Storage и Retention)

Для работы Loki 3.x требуется минимальная конфигурация хранилища.

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

compactor:
  working_directory: /loki/retention
  compaction_interval: 10m
  retention_enabled: true
  retention_delete_delay: 2h
  retention_delete_worker_count: 150
```

### Безопасность и ограничение доступа

В среде Docker Compose базовую защиту можно реализовать через Nginx Reverse Proxy (с Basic Auth) перед Loki или через внутренние настройки авторизации.

1. **Basic Auth в Alloy:**
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

2. **Лимиты ресурсов в Compose:**
Всегда ограничивайте потребление памяти для Loki, так как при тяжелых запросах потребление RAM может резко возрасти.
```yaml
    deploy:
      resources:
        limits:
          memory: 2G
        reservations:
          memory: 512M
```

### Поиск и устранение неисправностей

| Проблема | Возможная причина | Решение |
| :--- | :--- | :--- |
| **Alloy не видит контейнеры** | Нет доступа к `docker.sock` | Проверьте монтирование сокета и права доступа (`chmod 666` на хосте, если необходимо) |
| **Ошибка 429 (Too Many Requests)** | Превышены лимиты Loki | Увеличьте `ingestion_rate_mb` и `ingestion_burst_size_mb` в `limits_config` |
| **Логи отображаются с задержкой** | Большой `batch_wait` в Alloy | Уменьшите интервал отправки в конфигурации `loki.write` |
| **Пустые результаты Explore** | Неверный селектор меток | Проверьте метки через Alloy UI (порт 12345) в разделе `discovery.relabel` |

## Дополнительная информация

* **Обзор архитектуры:** [loki_overview.md](../loki_overview.md) — детальное описание компонентов и потоков данных.
* **Развертывание в Kubernetes:** [loki_installation.md](../loki_stack_setup/loki_installation.md) — переход от Docker Compose к Helm-чартам.
* **Подробно об Alloy:** [Grafana Alloy](../../Grafana/grafana_alloy_overview.md) — возможности и компоненты нового агента.
* **Официальная документация:** [Grafana Loki Docs](https://grafana.com/docs/loki/latest/) — справочник по всем параметрам конфигурации.
