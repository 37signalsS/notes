# Установка Prometheus в Kubernetes через Helm

## Определения

**Helm** — менеджер пакетов для Kubernetes, позволяющий описывать, устанавливать и обновлять сложные приложения через шаблонизированные чарты.

**kube-prometheus-stack** — основной Helm-чарт сообщества для развертывания полного стека мониторинга. Включает в себя:
*   **Prometheus Operator**: управляет жизненным циклом Prometheus и Alertmanager через Custom Resources (CRD).
*   **Prometheus Server**: сбор и хранение метрик.
*   **Alertmanager**: обработка и маршрутизация оповещений.
*   **Grafana**: визуализация данных.
*   **Exporters**: Node Exporter и Kube State Metrics для сбора системных метрик.

**Standalone установка** — развертывание отдельных компонентов (например, только Alertmanager или только Prometheus) с использованием их индивидуальных чартов.

## Основные концепции

### Почему kube-prometheus-stack?

В отличие от ручной установки, использование стека обеспечивает:
1.  **Автоматизацию Scrape-конфигураций**: Через `ServiceMonitor` и `PodMonitor` вместо ручного редактирования `prometheus.yml`.
2.  **Декларативность**: Вся конфигурация (ретенция, ресурсы, алерты) описывается в едином `values.yaml`.
3.  **Готовые дашборды**: Автоматический импорт преднастроенных дашбордов Grafana для мониторинга кластера Kubernetes.

### Актуальные версии (прогноз на 2026)

| Компонент | Версия приложения | Репозиторий чарта |
| :--- | :--- | :--- |
| **KPS Stack** | 82.x.x (Chart) | `prometheus-community/kube-prometheus-stack` |
| **Prometheus** | 3.11.x | В составе стека |
| **Alertmanager** | 0.32.x | В составе стека |
| **Grafana** | 11.x.x | В составе стека |

## Практические сценарии

### Сценарий 1: Установка полного стека (kube-prometheus-stack)

Это рекомендуемый способ для большинства Kubernetes-кластеров.

**1. Добавление репозитория:**
```bash
helm repo add prometheus-community https://prometheus-community.github.io/helm-charts
helm repo update
```

**2. Создание базового `values.yaml`:**
```yaml
# values.yaml
prometheus:
  prometheusSpec:
    retention: 30d
    storageSpec:
      volumeClaimTemplate:
        spec:
          storageClassName: longhorn # Укажите ваш StorageClass
          accessModes: ["ReadWriteOnce"]
          resources:
            requests:
              storage: 20Gi

grafana:
  adminPassword: "strong-password-here"
  ingress:
    enabled: true
    ingressClassName: nginx
    hosts:
      - grafana.k8s.example.com
```

**3. Установка:**
```bash
helm install monitoring prometheus-community/kube-prometheus-stack \
  --namespace monitoring --create-namespace \
  -f values.yaml
```

### Сценарий 2: Standalone установка Alertmanager

Используется, если Prometheus уже развернут иным способом или находится вне кластера.

**1. Создание `values.yaml`:**
```yaml
config:
  global:
    resolve_timeout: 5m
  route:
    receiver: 'default-receiver'
  receivers:
    - name: 'default-receiver'
      # Настройка Telegram/Slack здесь
```

**2. Установка:**
```bash
helm install alertmanager prometheus-community/alertmanager \
  --namespace monitoring -f values.yaml
```

> Подробности настройки — в разделе **[Alertmanager: установка через Helm](../kubernetes/Kube_Prometheus_Stack_Helm/alertmanager_config.md)**.

### Сценарий 3: Обновление конфигурации

Любые изменения вносятся через обновление релиза Helm:

```bash
# Проверка изменений (diff)
helm diff upgrade monitoring prometheus-community/kube-prometheus-stack -f values.yaml

# Применение
helm upgrade monitoring prometheus-community/kube-prometheus-stack \
  --namespace monitoring -f values.yaml
```

## Дополнительная информация

### Проверка статуса

После установки убедитесь, что все компоненты запущены:
```bash
kubectl get pods -n monitoring
kubectl get servicemonitors -n monitoring
```

### Удаление стека

```bash
helm uninstall monitoring -n monitoring
# Примечание: CRD (Custom Resource Definitions) не удаляются автоматически.
# Их нужно удалять вручную, если это необходимо:
# kubectl delete crd prometheuses.monitoring.coreos.com ...
```

### См. также
*   **[Установка Prometheus: обзор](./overview.md)** — сравнение методов.
*   **[Обзор kube-prometheus-stack](../kubernetes/Kube_Prometheus_Stack_Helm/overview.md)** — глубокое погружение в компоненты.
*   **[Конфигурация Alertmanager в KPS](../kubernetes/Kube_Prometheus_Stack_Helm/alertmanager_config.md)**.
*   **[Helm: общие сведения](../../../Kubernetes/ToolsUtilities/Helm/helm_overview.md)**.

---
**Надежность:** 10 (SSoT + Валидация kube-prometheus-stack)
**,file_path: