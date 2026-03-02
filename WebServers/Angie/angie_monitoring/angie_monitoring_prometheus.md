# Мониторинг Angie — Интеграция с Prometheus

## Практический сценарий: Интеграция с Prometheus

### Шаг 1: Настройка эндпоинта в Angie

Создайте защищенный `location`, который будет экспортировать метрики в формате Prometheus. Это решение **является нативным** и, в отличие от аналогов для NGINX, **не требует использования njs** или других скриптовых языков.

```nginx
server {
    listen 80;
    # ...
    location = /metrics {
        prometheus all; # Экспорт всех метрик из шаблона "all"
        allow 127.0.0.1; # IP-адрес сервера Prometheus
        deny all;
    }
}
```

*Убедитесь, что в `angie.conf` подключен шаблон `prometheus.conf`.*

### Шаг 2: Настройка Prometheus

Добавьте в `prometheus.yml` новую задачу для сбора метрик.

```yaml
scrape_configs:
  - job_name: 'angie'
    metrics_path: /metrics
    static_configs:
      - targets: ['localhost:80'] # Адрес сервера Angie
```

### Шаг 3: Визуализация в Grafana

1. Подключите Prometheus как источник данных в Grafana.
2. Импортируйте официальный дашборд Angie, используя ID `2719`.

---

**См. также:**

- [Основные концепции мониторинга](./angie_monitoring_concepts.md)
- [Настройка Console Lite и API](./angie_monitoring_console.md)
- [Создание пользовательских метрик](./angie_monitoring_custom_metrics.md)
