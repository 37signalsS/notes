# Обогащение метрик node-exporter

> [Назад к оглавлению](../practical_scenarios.md)

Позволяет определить специфичные для `node-exporter` правила `relabeling` для обогащения метрик.

* **Пример:** Добавление читаемого имени узла в метрики.

    ```yaml
    prometheus:
      prometheusSpec:
        scrapeClasses:
          - name: node-exporter
            relabelingConfigs:
              - sourceLabels: [__meta_kubernetes_pod_node_name]
                targetLabel: node
                action: replace
    ```
