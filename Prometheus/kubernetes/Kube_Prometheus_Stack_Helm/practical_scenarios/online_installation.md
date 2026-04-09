# Online Installation (kube-prometheus-stack)

> [Назад к оглавлению](../overview.md)

> **SSoT для темы:** стандартная установка kube-prometheus-stack в Kubernetes с доступом к интернету через Helm.  
> **Смежные темы:** [Kube-Prometheus-Stack Overview](../overview.md) — обзоры компонентов, версии, архитектура; [Offline Air-gapped Installation](./offline_airgapped_installation.md) — установка без доступа к интернету.

## Definitions

**Онлайн установка** — развёртывание kube-prometheus-stack в Kubernetes-кластер с прямым доступом к интернету. Helm автоматически загружает чарт из public-репозитория (`prometheus-community`), а kubelet pull-ит образы из docker.io, quay.io, ghcr.io.

**Helm release** — экземпляр развёрнутого чарта в Kubernetes. Управляется командами `helm install`, `helm upgrade`, `helm uninstall`. Имя релиза влияет на имена создаваемых ресурсов (Service, Pod, Secret).

## Basic Concepts

### Что развёртывается при установке

```
helm install kps prometheus-community/kube-prometheus-stack
    │
    ├── Prometheus Operator (Deployment)
    │       └── Управляет lifecycle Prometheus и Alertmanager
    │
    ├── Prometheus Server (StatefulSet)
    │       └── Сбор и хранение метрик (TSDB)
    │
    ├── Alertmanager (StatefulSet)
    │       └── Маршрутизация и дедупликация оповещений
    │
    ├── Grafana (Deployment)
    │       └── Визуализация, дашборды, алерты
    │
    ├── Node Exporter (DaemonSet)
    │       └── Метрики хостов (CPU, память, диски)
    │
    ├── kube-state-metrics (Deployment)
    │       └── Метрики объектов K8s (Pods, Deployments, Nodes)
    │
    └── CRDs (Prometheus, Alertmanager, ServiceMonitor, PodMonitor, Probe, ...)
            └── Custom Resource Definitions для Prometheus Operator
```

### Именование ресурсов: влияние имени релиза

Имя Helm-release определяет префикс имён создаваемых ресурсов. Это критично для `port-forward` и скриптов.

| Имя релиза | Prometheus Service | Grafana Service |
|---|---|---|
| `monitoring` | `prometheus-operated` | `monitoring-grafana` |
| `kps` | `kube-prometheus-kube-prome-prometheus` | `kube-prometheus-grafana` |

> **Рекомендация:** Используйте имя релиза `monitoring` для коротких и предсказуемых имён ресурсов.

### Отличия от offline-установки

| Параметр | Online | Offline (Air-gapped) |
|---|---|---|
| Источник чарта | `https://prometheus-community.github.io/helm-charts` | `oci://harbor.domain.local/helm/` |
| Источник образов | docker.io, quay.io, ghcr.io (автоматически) | Приватный Harbor/Nexus |
| `global.imageRegistry` | Не требуется | Обязателен |
| Подготовка артефактов | Не требуется | 3 этапа: pull → save → push в Harbor |

> **Подробнее:** [Offline Air-gapped Installation](./offline_airgapped_installation.md).

## Practical Scenarios

### Сценарий 1: Минимальная установка (без кастомизации)

**Задача:** Быстро развернуть мониторинг для тестирования или разработки.

```bash
# Создание namespace (опционально, --create-namespace сделает это автоматически)
kubectl create namespace monitoring

# Подключение репозитория
helm repo add prometheus-community https://prometheus-community.github.io/helm-charts
helm repo update

# Установка
helm install kps prometheus-community/kube-prometheus-stack \
  -n monitoring --create-namespace
```

**Проверка:**

```bash
# Проверка подов
kubectl get pods -n monitoring

# Проверка CRD
kubectl get crd | grep monitoring.coreos.com

# Проверка ServiceMonitor'ов
kubectl get servicemonitor -n monitoring
```

### Сценарий 2: Установка с Ingress для внешнего доступа

**Задача:** Развернуть мониторинг с доступом через Ingress (NGINX).

**Шаг 1: Создание values.yaml**

```yaml
# values.yaml
prometheus:
  ingress:
    enabled: true
    ingressClassName: nginx
    annotations:
      nginx.ingress.kubernetes.io/backend-protocol: "HTTP"
    hosts:
      - prometheus.k8s.domain.local
    paths:
      - /
    pathType: Prefix

grafana:
  ingress:
    enabled: true
    ingressClassName: nginx
    annotations:
      nginx.ingress.kubernetes.io/backend-protocol: "HTTP"
    hosts:
      - grafana.k8s.domain.local
    path: /
    pathType: Prefix
```

**Шаг 2: Установка**

```bash
helm install kps prometheus-community/kube-prometheus-stack \
  -n monitoring --create-namespace -f values.yaml
```

**Доступ:**

- Prometheus: `http://prometheus.k8s.domain.local`
- Grafana: `http://grafana.k8s.domain.local`

### Сценарий 3: Доступ к UI через port-forward (без Ingress)

**Задача:** Временный доступ к Prometheus и Grafana без настройки Ingress.

```bash
# Grafana — порт 3000 → 80
kubectl --namespace monitoring port-forward svc/kube-prometheus-grafana 3000:80

# Prometheus — порт 9090
kubectl --namespace monitoring port-forward svc/kube-prometheus-kube-prome-prometheus 9090:9090
```

> **Примечание:** Имена Service зависят от имени релиза. Для релиза `monitoring` используйте `prometheus-operated` и `monitoring-grafana`.

### Сценарий 4: Получение учётных данных Grafana

**Пароль (автосгенерированный):**

```bash
kubectl -n monitoring get secret kube-prometheus-grafana \
  -o jsonpath='{.data.admin-password}' | base64 -d; echo
```

**Логин:** `admin`

> **Примечание:** Для релиза `monitoring` имя Secret — `monitoring-grafana`. Можно переопределить пароль в values.yaml:

```yaml
grafana:
  adminPassword: "my-secure-password"
```

### Сценарий 5: Обновление и удаление

**Обновление чарта:**

```bash
helm repo update
helm upgrade kps prometheus-community/kube-prometheus-stack \
  -n monitoring -f values.yaml
```

**Удаление:**

```bash
helm uninstall kps -n monitoring
# CRD НЕ удаляются автоматически — для полного удаления:
kubectl delete crd -l app.kubernetes.io/managed-by=Helm  # ОСТОРОЖНО: удалит все CRD чартов
```

> **Важно:** `helm uninstall` не удаляет CRD по дизайну (защита от потери данных). CRD необходимо удалять вручную при полной деинсталляции.

## Additional Information

### Troubleshooting

| Симптом | Причина | Решение |
|---|---|---|
| `ImagePullBackOff` на поде | Квота/Rate limit docker.io | Проверить `kubectl describe pod`; использовать `imagePullSecrets` |
| Pending pod'ов | Недостаточно ресурсов на нодах | Проверить `kubectl describe pod` → events; масштабировать кластер |
| CRD не созданы | Ошибка при установке CRD (конфликт с существующими) | Удалить конфликтующие CRD; `kubectl get crd \| grep monitoring` |
| Grafana недоступна через Ingress | Ingress controller не установлен | Установить NGINX Ingress: `helm install ingress-nginx ...` |
| port-forward завершается | Service не найден | Проверить имя Service: `kubectl get svc -n monitoring`; сверить с именем релиза |
| Prometheus не видит targets | ServiceMonitor'ы не подхвачены | Проверить `kubectl get servicemonitor -n monitoring`; логи Prometheus Operator |

### Диагностика

```bash
# Все ресурсы в namespace monitoring
kubectl get all -n monitoring

# Проверка CRD
kubectl get crd | grep -E 'prometheus|alertmanager|servicemonitor|podmonitor'

# Логи Prometheus Operator
kubectl logs -n monitoring -l app.kubernetes.io/name=prometheus-operator --tail=50

# Проверка ServiceMonitor → Target связывания
kubectl get servicemonitor -n monitoring -o wide

# Проверка событий namespace
kubectl get events -n monitoring --sort-by='.lastTimestamp'
```

### Best Practices

1. **Выделяйте отдельный namespace** — `monitoring` изолирует компоненты от рабочих нагрузок.
2. **Используйте values.yaml всегда** — даже для минимальной установки; это упрощает воспроизведение и обновление.
3. **Фиксируйте версию чарта** — `helm install kps prometheus-community/kube-prometheus-stack --version 82.4.3` для воспроизимости.
4. **Ingress + TLS для production** — никогда не оставляйте Prometheus и Grafana без аутентификации и TLS в production-среде.
5. **Регулярно обновляйте** — следите за [GitHub Releases](https://github.com/prometheus-community/helm-charts/releases) kube-prometheus-stack; обновляйте через `helm upgrade`.

### Связанные ресурсы

| Ресурс | Описание |
|---|---|
| [Kube-Prometheus-Stack Overview](../overview.md) — версии компонентов, архитектура, CRD, Service Discovery |
| [Offline Air-gapped Installation](./offline_airgapped_installation.md) — установка без доступа к интернету |
| [Master Nodes Monitoring](./master_nodes_monitoring.md) — сбор метрик с master/control-plane нод |
| [External Monitoring](./external_monitoring.md) — мониторинг внешних ресурсов через static_configs |
| [Node Exporter Enrichment](./node_exporter_enrichment.md) — обогащение метрик через relabeling |
