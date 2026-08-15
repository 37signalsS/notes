# Практические сценарии kube-prometheus-stack

## Обзор

В данном разделе собраны руководства по решению специфических задач при использовании Helm-чарта `kube-prometheus-stack`.

## Список сценариев

### Установка и базовое развертывание
*   **[Онлайн-установка](./practical_scenarios/online_installation.md)** — стандартное развертывание в кластере с доступом к интернету.
*   **[Offline (Air-gapped) установка](./practical_scenarios/offline_airgapped_installation.md)** — развертывание в изолированных контурах.
*   **[Настройка Persistent Volumes](./practical_scenarios/persistent_volumes.md)** — обеспечение сохранности данных TSDB.

### Мониторинг инфраструктуры
*   **[Мониторинг Master-нод](./practical_scenarios/master_nodes_monitoring.md)** — сбор метрик с компонентов Control Plane.
*   **[Мониторинг etcd](./etcd-monitoring.md)** — специфические настройки для etcd.
*   **[Обогащение метрик Node Exporter](./practical_scenarios/node_exporter_enrichment.md)** — добавление кастомных лейблов и коллекторов.

### Мониторинг приложений
*   **[Мониторинг Node.js приложения](./practical_scenarios/app_monitoring_node_js.md)** — полный цикл от Deployment до ServiceMonitor и AlertingRules.
*   **[Мониторинг внешних целей](./practical_scenarios/external_monitoring.md)** — подключение ресурсов вне кластера Kubernetes.

### Безопасность и доступ
*   **[Настройка веб-аутентификации](./practical_scenarios/web_authentication.md)** — защита UI интерфейсов Prometheus и Alertmanager.

## Диагностика
При возникновении проблем со сценарными настройками обращайтесь к разделу **[Troubleshooting](../../operator/troubleshooting.md)**.
