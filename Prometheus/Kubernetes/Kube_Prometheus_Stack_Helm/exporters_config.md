# Конфигурация экспортеров в kube-prometheus-stack

### Конфигурация `kube-state-metrics`

* `kube-state-metrics.enabled`: `true`
  * **Описание:** Включает развертывание `kube-state-metrics`, который генерирует метрики о состоянии объектов Kubernetes (Deployments, Pods, Nodes и т.д.).
  * **Рекомендация:** Оставить `true`. Это один из ключевых источников метрик о состоянии кластера.

### Конфигурация Node Exporter

> ℹ️ Общую информацию об экспортерах метрик можно найти в заметке: [exporters](overview.md).

* `nodeExporter.enabled`: `true`
  * **Рекомендация:** Оставить `true` для сбора метрик с нод.

* `nodeExporter.hostNetwork`: `true`
  * **Описание:** Позволяет подам Node Exporter использовать сетевой namespace хоста (`hostNetwork: true`) и PID namespace хоста (`hostPID: true`).
  * **Рекомендация:** Оставить `true` для корректного сбора сетевых метрик и метрик процессов с хоста.

* `nodeExporter.resources`:
  * **Рекомендация:** Как и для других компонентов, задать минимальные значения и наблюдать.
