# Netdata: Мониторинг в реальном времени

## Определения

**Netdata** — высокопроизводительная система для мониторинга производительности систем и приложений в реальном времени. Ключевое отличие от Prometheus — детализация метрик **до секунды** и готовые интерактивные дашборды без настройки.

**Область применения:**

- Отладка производительности в реальном времени
- Анализ проблем при нагрузочном тестировании
- Быстрый обзор состояния хоста или контейнера

Подробно о концепциях наблюдаемости: **[Observability Definitions](../../Concepts/Observability_and_Monitoring/observability_definitions.md)**.

## Основные концепции

### Архитектура в Kubernetes

Установка через официальный Helm-чарт разворачивает Netdata по модели Parent/Child:

- **Parent `Deployment`** — один главный под агрегирует данные от дочерних агентов, предоставляет централизованный UI (User Interface), хранит историю в `PersistentVolume`.
- **Child `DaemonSet`** — под-агент на каждом узле собирает метрики хоста (CPU (Central Processing Unit), память, диски, сеть) и из `cgroups` (Control Groups) контейнеров.
- **Service Discovery** — дочерние агенты автоматически обнаруживают родительский под и отправляют метрики.

### Преимущества и недостатки

**Преимущества:**

- **Реальное время** — обновление данных каждую секунду
- **Авто-обнаружение** — мониторинг сотен сервисов без конфигурации
- **Нулевая конфигурация** — дашборды доступны сразу
- **Низкое потребление** — легковесные агенты

**Недостатки:**

- **Дашборды** — встроенные дашборды негибкие, кастомизация ограничена (в отличие от Grafana)
- **Долгосрочное хранение** — для долгосрочного анализа лучше использовать Prometheus; Netdata может быть источником метрик

### Методологии мониторинга

Netdata покрывает принципы методологий **[USE](../../Concepts/Observability_and_Monitoring/monitoring_methodologies.md)** (Utilization, Saturation, Errors) для инфраструктуры и **[RED](../../Concepts/Observability_and_Monitoring/monitoring_methodologies.md)** (Rate, Errors, Duration) для сервисов.

## Практические сценарии

### Установка через Helm

Netdata рекомендуется устанавливать через официальный Helm-чарт.

**Шаг 1: Добавление репозитория**

```bash
helm repo add netdata https://netdata.github.io/helmchart/
# → "netdata" has been added to your repositories
helm repo update
# → Hang tight while we grab the latest from your chart repositories...
# → ...Successfully got an update from the "netdata" chart repository
```

**Шаг 2: Отладка конфигурации (`--dry-run`)**

Перед установкой полезно посмотреть сгенерированные манифесты и переопределить значения по умолчанию:

```bash
helm install netdata netdata/netdata \
  --namespace monitoring \
  --set image.pullPolicy=IfNotPresent \
  --set parent.database.storageClass=managed-nfs-storage \
  --set child.resources.requests.cpu=100m \
  --set parent.resources.limits.memory=1Gi \
  --set ingress.enabled=false \
  --dry-run --debug
# → [YAML (Yet Another Markup Language) manifests output for all Netdata resources]
```

Параметры:

- `--dry-run --debug` — генерация и вывод YAML-манифестов без применения в кластере
- `parent.database.storageClass` — `StorageClass` для `PersistentVolume` с историческими данными
- `child.resources.requests.cpu` — запросы CPU для child-агента
- `parent.resources.limits.memory` — лимиты памяти для parent-пода
- `ingress.enabled=false` — отключение Ingress для ручной настройки с TLS (Transport Layer Security)

**Шаг 3: Установка релиза**

```bash
helm install netdata netdata/netdata \
  --namespace monitoring \
  --create-namespace \
  --set image.pullPolicy=IfNotPresent \
  --set parent.database.storageClass=managed-nfs-storage \
  --set child.resources.requests.cpu=100m \
  --set parent.resources.limits.memory=1Gi \
  --set ingress.enabled=false
# → NAME: netdata
# → LAST DEPLOYED: Sat Jun  6 15:30:00 2026
# → NAMESPACE: monitoring
# → STATUS: deployed
# → REVISION: 1
```

**Шаг 4: Доступ через Ingress**

Создание `Ingress`-ресурса для доступа к родительскому поду:

```yaml
# netdata-ingress.yaml
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: netdata-ingress
  namespace: monitoring
  annotations:
    cert-manager.io/issuer: "kubernetes-ca-issuer"
spec:
  ingressClassName: system-ingress
  tls:
  - hosts:
    - netdata.k8s.local
    secretName: internal-services-secret
  rules:
  - host: netdata.k8s.local
    http:
      paths:
      - path: /
        pathType: Prefix
        backend:
          service:
            name: netdata
            port:
              name: http
```

Настройка cert-manager: **[CA (Certificate Authority) кластера для внутренних сертификатов](../ToolsUtilities/cert_manager/cluster_ca.md)**.

### Удаление Netdata

```bash
helm uninstall netdata -n monitoring
# → release "netdata" uninstalled
```

Helm удаляет все связанные ресурсы (`Deployment`, `DaemonSet`, `Service`, `PVC` (PersistentVolumeClaim)).

> **Примечание:** `PersistentVolume` может сохраниться при `reclaimPolicy: Retain`.

## Дополнительная информация

### Интеграция с Prometheus

Netdata может отдавать метрики в формате Prometheus через настройку в `values.yaml` Helm-чарта. Это позволяет использовать Netdata как источник метрик для существующих Prometheus-инсталляций.

### Смежные темы

- **[Monitoring and Logging Architecture](./kubernetes-monitoring-logging-architecture.md)** — слои мониторинга в Kubernetes
- **[Metrics Collection Strategies](../../Concepts/Observability_and_Monitoring/metrics_collection_strategies.md)** — стратегии сбора метрик
- **[Prometheus Installation](../../../Prometheus/installation/prometheus_server_installation.md)** — долгосрочное хранение и алертинг
