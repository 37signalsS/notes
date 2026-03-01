## Определения

**[cAdvisor (Container Advisor)](https://github.com/google/cadvisor)** — это open-source инструмент от Google для мониторинга контейнеров. Он автоматически обнаруживает все контейнеры на хосте и собирает информацию об их производительности и потреблении ресурсов.

## Основные концепции

cAdvisor является стандартом де-факто для сбора метрик контейнеров и неотъемлемой частью мониторинга в средах [Docker](../../Docker/docker_overview.md) и [Kubernetes](../../Kubernetes/kubernetes_overview.md).

### Ключевые возможности

- Автоматическое обнаружение контейнеров на хосте
- Сбор метрик CPU, памяти, сети, файловой системы
- Экспорт метрик в формате Prometheus
- Встроенный веб-интерфейс
- Минимальные требования к ресурсам

### Версии и совместимость

| Версия cAdvisor | Поддержка Docker |
| :--- | :--- |
| v0.56.0+ | Docker 25.0+ |
| v0.53.0 | Docker 20.10+ |

> **Важно**: Начиная с v0.56.0, cAdvisor перенесен из репозитория `gcr.io/cadvisor/cadvisor` в `ghcr.io/cadvisor/cadvisor`.

## Практические сценарии

### Запуск в Docker

```yaml
services:
  cadvisor:
    image: ghcr.io/cadvisor/cadvisor:v0.56.0
    container_name: cadvisor
    ports:
      - "8080:8080"
    volumes:
      - /:/rootfs:ro
      - /var/run:/var/run:rw
      - /sys:/sys:ro
      - /var/lib/docker/:/var/lib/docker:ro
    restart: unless-stopped
```

### Основные метрики

- `container_cpu_usage_seconds_total` — общее время использования CPU
- `container_memory_usage_bytes` — использование памяти
- `container_network_receive_bytes_total` — принятые байты по сети
- `container_network_transmit_bytes_total` — переданные байты по сети

## Дополнительная информация

Подробнее о настройке интеграции cAdvisor с Prometheus см. в разделе [Интеграция Docker с Prometheus](../../Docker/Docker_metrics/docker_prometheus_integration.md).

Альтернативные инструменты: [draganm/missing-container-metrics](https://github.com/draganm/missing-container-metrics) для специфичных метрик.
