# Дополнительные темы настройки Loki в Docker Compose

## Definitions

**Grafana Alloy** — универсальный агент сбора телеметрии от Grafana Labs, рекомендуемый для новых развёртываний вместо Promtail.

## Basic Concepts

### Альтернатива: Grafana Alloy вместо Promtail

Для новых развёртываний рекомендуется использовать Grafana Alloy вместо Promtail. Подробный обзор: [Grafana Alloy](../../Grafana/grafana_alloy_overview.md).

### Постоянное хранилище (Persistence)

В базовой конфигурации используются Docker volumes (`loki_data`, `grafana_data`), обеспечивающие персистентность данных при перезапуске контейнеров. Конфигурация volumes описана в [Настройка Docker Compose](./loki_docker_compose_setup.md).

## Practical Scenarios

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

### Варианты хранилищ для production

| Тип хранилища | Описание | Пример |
| :--- | :--- | :--- |
| **Файловая система** | Простой вариант для тестовых сред | `directory: /loki/chunks` |
| **S3-совместимое** | Масштабируемое хранилище для production | MinIO, Ceph, AWS S3, Yandex Object Storage |
| **GCS** | Google Cloud Storage | Для GCP-окружений |

Пример настройки S3: [loki_overview.md](../loki_overview.md#конфигурация).

### Troubleshooting

| Проблема | Возможная причина | Решение |
| :--- | :--- | :--- |
| **Loki не принимает логи** | Неправильный URL в Promtail | Проверьте `clients.url` в config.yml |
| **Дубликаты логов** | Сбой positions-файла | Удалите `/tmp/positions.yaml` и перезапустите Promtail |
| **Grafana не видит Loki** | Проблема с сетью Docker | Убедитесь, что сервисы в одной сети (`networks: - monitoring`) |
| **413 Request Entity Too Large** | Превышен размер батча | Уменьшите `batch_size` в Promtail или увеличьте лимит в Loki |

## Additional Information

Практическая настройка: [loki_docker_compose_setup.md](./loki_docker_compose_setup.md). Интеграция Fluent Bit: [fluentbit_integration.md](../fluentbit_integration.md). Отправка логов напрямую из Docker: [Loki Docker Driver](../../Docker/Docker_logs/loki_logging_driver_setup.md). Развёртывание в Kubernetes: [loki_stack_setup_guide.md](../../Loki/loki_overview.md).
