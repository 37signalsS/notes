# Конфигурация Helm-чарта kube-prometheus-stack: Обзор

## Определения

**`kube-prometheus-stack`** — это Helm-чарт, предназначенный для развертывания и управления полным стеком мониторинга в среде Kubernetes. Он включает в себя [Prometheus](overview.md), [Alertmanager](../../alertmanager.md), [Grafana](../../../Grafana/grafana_overview.md), а также ключевые экспортеры и конфигурационные ресурсы.

**`values.yaml`** — основной конфигурационный файл Helm-чарта, который позволяет кастомизировать развертываемые компоненты и их параметры.

> **Инструкции по установке:** Полные руководства по онлайн и оффлайн (air-gapped) установке см. в [Практических сценариях](./practical_scenarios.md).

## Базовые концепции

В данном разделе рассматриваются ключевые параметры файла `values.yaml`, используемого для конфигурации стека мониторинга.

## Процесс установки

**Рекомендация:** Всегда работайте с локальной копией чарта. Это позволяет версионировать конфигурацию (`values.yaml`) вместе с кодом вашего приложения и интегрировать развертывание в CI/CD.

1. **Скачать чарт локально:**

    ```bash
    helm repo add prometheus-community https://prometheus-community.github.io/helm-charts
    helm repo update
    helm pull prometheus-community/kube-prometheus-stack --untar
    ```

2. **Создать PV (при необходимости):**

    ```bash
    kubectl apply -f pv-manifests/
    ```

3. **Установить чарт:**

    ```bash
    helm install prometheus ./kube-prometheus-stack \
      --namespace monitoring \
      --create-namespace \
      -f values.yaml
    ```

**Примечание:** После установки проверьте статус подов (`kubectl get pods -n monitoring`), PV/PVC и Ingress.

## Дополнительная информация

Для общего обзора технологий рекомендуется ознакомиться с основными заметками:

- [Helm](../../../Kubernetes/ToolsUtilities/Helm/helm_overview.md)
- [Kubernetes](../../../Kubernetes/kubernetes_overview.md)
- [Prometheus](overview.md)
- [Практические сценарии установки](./practical_scenarios.md)
