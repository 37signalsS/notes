# Конфигурация Helm-чарта kube-prometheus-stack: Обзор

## Определения

**`kube-prometheus-stack`** — это Helm-чарт, предназначенный для развертывания и управления полным стеком мониторинга в среде Kubernetes. Он включает в себя [Prometheus](../overview.md), [Alertmanager](../alertmanager.md), [Grafana](../../Grafana/grafana_overview.md), а также ключевые экспортеры и конфигурационные ресурсы.

**`values.yaml`** — основной конфигурационный файл Helm-чарта, который позволяет кастомизировать развертываемые компоненты и их параметры.

## Базовые концепции

В данном разделе рассматриваются ключевые параметры файла `values.yaml`, используемого для конфигурации стека мониторинга.

## Процесс установки

1.  **Скачать чарт локально:**
    ```bash
    helm repo add prometheus-community https://prometheus-community.github.io/helm-charts
    helm repo update
    helm pull prometheus-community/prometheus --untar
    ```
    **Рекомендация:** Всегда работайте с локальной копией чарта. Это позволяет версионировать конфигурацию (`values.yaml`) вместе с кодом вашего приложения и интегрировать развертывание в CI/CD. Установка через CI/CD помогает избежать несоответствий версий и конфигураций, которые могут привести к болезненным проблемам при обновлении.

2.  **Создать PV (при необходимости):**
    ```bash
    kubectl apply -f pv-manifests/
    ```

3.  **Установить чарт:**
    ```bash
    helm install prometheus ./prometheus 
      --namespace monitoring 
      --create-namespace 
      -f values.yaml
    ```
    **Примечание:** Если при установке возникают ошибки, например, из-за пустых списков в `values.yaml` (как в строке 493 в примере), убедитесь, что все списки корректно заполнены или закомментированы. После успешной установки проверьте статус подов (`kubectl get pods -n monitoring`), PV/PVC (`kubectl get pv,pvc -n monitoring`) и Ingress (`kubectl get ingress -n monitoring`).

## Дополнительная информация

Для общего обзора технологий рекомендуется ознакомиться с основными заметками:
- [Helm](../../Kubernetes/ToolsUtilities/helm_overview.md)
- [Kubernetes](../../Kubernetes/kubernetes_overview.md)
- [Prometheus](../overview.md)
