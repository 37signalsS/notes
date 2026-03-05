# Настройка Loki с помощью Docker Compose — Дополнительные темы

## 1. Альтернатива: Grafana Alloy вместо Promtail

Для новых развертываний рекомендуется использовать **Grafana Alloy** вместо Promtail.

### docker-compose.yml с Alloy

```yaml
  alloy:
    image: grafana/alloy:v1.0.0
    container_name: ${PROJECT_NAME:-monitoring}-alloy
    volumes:
      - /var/log:/var/log:ro
      - /var/lib/docker/containers:/var/lib/docker/containers:ro
      - ./alloy/config.alloy:/etc/alloy/config.alloy:ro
    command: run --server.http.listen-addr=0.0.0.0:12345 /etc/alloy/config.alloy
    restart: always
    networks:
      - monitoring
    depends_on:
      - loki
```

### config.alloy для Alloy

```alloy
// Сбор логов контейнеров
loki.source.file "containers" {
  path    = "/var/lib/docker/containers/*/*-json.log"
  labels  = { job = "container_logs" }
  forward = [loki.write.default.receiver]
}

// Отправка в Loki
loki.write "default" {
  endpoint {
    url = "http://loki:3100/loki/api/v1/push"
  }
}
```

> **Подробнее:** [Grafana Alloy](../../Grafana/grafana_alloy_overview.md) — полный обзор и руководство по миграции.

## 2. Постоянное хранилище (Persistence)

В базовой конфигурации выше используются Docker volumes (`loki_data`, `grafana_data`), что обеспечивает **персистентность данных** при перезапуске контейнеров.

Для production-окружения рассмотрите:

| Тип хранилища | Описание | Пример |
| :--- | :--- | :--- |
| **Файловая система** | Простой вариант для тестовых сред | `directory: /loki/chunks` |
| **S3-совместимое** | Масштабируемое хранилище для production | MinIO, Ceph, AWS S3, Yandex Object Storage |
| **GCS** | Google Cloud Storage | Для GCP-окружений |

> **Конфигурация S3:** [loki_overview.md](../loki_overview.md#конфигурация) — пример настройки хранения в S3.

## 3. Troubleshooting

| Проблема | Возможная причина | Решение |
| :--- | :--- | :--- |
| **Loki не принимает логи** | Неправильный URL в Promtail | Проверьте `clients.url` в config.yml |
| **Дубликаты логов** | Сбой positions-файла | Удалите `/tmp/positions.yaml` и перезапустите Promtail |
| **Grafana не видит Loki** | Проблема с сетью Docker | Убедитесь, что сервисы в одной сети (`networks: - monitoring`) |
| **413 Request Entity Too Large** | Превышен размер батча | Уменьшите `batch_size` в Promtail или увеличьте лимит в Loki |

## Связанные документы

- **[Основные концепции](./loki_docker_concepts.md)** — определения и компоненты
- **[Настройка Docker Compose](./loki_docker_compose_setup.md)** — конфигурация, запуск, проверка
- **[loki_overview.md](../loki_overview.md)** — базовые концепции и архитектура Loki
- **[loki_stack_setup_guide.md](../loki_stack_setup_guide.md)** — развертывание в Kubernetes
- **[fluentbit_integration.md](../fluentbit_integration.md)** — интеграция Fluent Bit вместо Promtail
- **[Loki Docker Driver](../../Docker/Docker_logs/loki_logging_driver_setup.md)** — отправка логов напрямую из Docker
- **[Grafana Alloy](../../Grafana/grafana_alloy_overview.md)** — рекомендуемый агент для новых развертываний
