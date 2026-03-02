# Сбор метрик с master-нод

> [Назад к оглавлению](../practical_scenarios.md)

Позволяет подам Node Exporter размещаться на master-нодах, которые по умолчанию имеют `taint` (например, `NoSchedule`).

* **Рекомендация:** Добавить `toleration`, чтобы собирать метрики со всех узлов кластера.

    ```yaml
    nodeExporter:
      tolerations:
        - operator: "Exists"
          effect: "NoSchedule"
    ```
