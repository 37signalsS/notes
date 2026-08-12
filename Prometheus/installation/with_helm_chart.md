# Установка Prometheus в Kubernetes через Helm

Этот файл служит указателем на актуальные инструкции по развертыванию стека мониторинга с использованием Helm-чарта `kube-prometheus-stack`.

## Основные инструкции (SSoT)

Согласно архитектуре базы знаний, подробные практические сценарии разделены по типам окружения:

*   **[Онлайн-установка (Online Installation)](../kubernetes/Kube_Prometheus_Stack_Helm/practical_scenarios/online_installation.md)** — основной сценарий для кластеров с доступом к интернету. Включает настройку персистентности, Ingress и лимитов ресурсов.
*   **[Установка в закрытом контуре (Offline/Air-gapped)](../kubernetes/Kube_Prometheus_Stack_Helm/practical_scenarios/offline_airgapped_installation.md)** — инструкции для изолированных сред (без доступа к внешним репозиториям).

## Краткая справка

**kube-prometheus-stack** — это «umbrella chart», который объединяет:
*   **Prometheus Operator** (управление через CRD).
*   **Prometheus Server**, **Alertmanager**, **Grafana**.
*   **Node Exporter** и **Kube State Metrics**.

## См. также
*   **[Обзор kube-prometheus-stack](../kubernetes/Kube_Prometheus_Stack_Helm/overview.md)** — описание компонентов и версий.
*   **[Helm: общие сведения](../../../Kubernetes/ToolsUtilities/Helm/helm_overview.md)**.
