# Настройка мониторинга внешних ресурсов (static_configs)

> [Назад к оглавлению](../practical_scenarios.md)

Позволяет добавлять кастомные `scrape_configs` напрямую в конфигурацию Prometheus. Это основной способ настроить мониторинг целей, которые находятся **вне Kubernetes** (виртуальные машины, физические серверы).

* **Пример:** Мониторинг внешнего хоста с `node-exporter`.

    ```yaml
    prometheus:
      prometheusSpec:
        additionalScrapeConfigs:
          - job_name: 'external-nodes'
            static_configs:
              - targets: ['192.168.1.100:9100', '192.168.1.101:9100']
                labels:
                  env: 'production'
    ```
