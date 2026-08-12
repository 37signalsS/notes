# Конфигурация Grafana в kube-prometheus-stack

## Определения

**Grafana в kube-prometheus-stack** — основной интерфейс визуализации стека мониторинга. В рамках Helm-чарта развёртывается как `Deployment` с набором вспомогательных контейнеров (sidecars) для реализации подхода **Monitoring as Code**.

**Grafana Sidecar (k8s-sidecar)** — специализированный контейнер (`kiwigrid/k8s-sidecar`), работающий в том же Pod, что и Grafana. Он отслеживает объекты ConfigMap и Secret в Kubernetes API и автоматически провижинит их содержимое (дашборды, источники данных, алерты) в Grafana без перезагрузки сервиса.

**Unified Alerting** — современная система оповещений (введена в Grafana 8+, стандарт в 12.x), объединяющая алертинг по метрикам, логам и внешним источникам в едином интерфейсе и API.

> **См. также:** [Обзор Grafana](../../../Grafana/grafana_overview.md), [Установка Grafana через Helm](../../../Grafana/Installation/grafana_helm_installation.md), [Интеграция с Prometheus Operator](../operator/grafana_integration.md).

## Основные концепции

### Ключевые Helm-параметры (values.yaml)

| Параметр | Назначение | Особенности (v12.x) |
| :--- | :--- | :--- |
| `grafana.enabled` | Включение компонента | Обязателен для работы UI. |
| `grafana.adminPassword` | Пароль администратора | Рекомендуется `existingSecret`. |
| `grafana.grafana.ini` | Глобальные настройки сервера | Секции `[security]`, `[auth]`, `[unified_alerting]`. |
| `grafana.sidecar.dashboards` | Автозагрузка дашбордов | Поддерживает фильтрацию по лейблам и namespaces. |
| `grafana.sidecar.datasources` | Настройка источников | Автоматически подключает Prometheus и Loki. |
| `grafana.persistence` | PersistentVolume | Требуется для сохранения настроек пользователей. |
| `grafana.replicas` | Масштабирование | **Критично:** требует внешней БД (PostgreSQL/MySQL). |

### Механизм Sidecar и провижининг

Sidecar-контейнер обеспечивает динамическую синхронизацию ресурсов Kubernetes с внутренним хранилищем Grafana.

| Тип ресурса | Метка (Label) | Путь монтирования |
| :--- | :--- | :--- |
| **Dashboards** | `grafana_dashboard: "1"` | `/tmp/dashboards` |
| **Datasources** | `grafana_datasource: "1"` | `/etc/grafana/provisioning/datasources` |
| **Alerts** | `grafana_alert: "1"` | `/etc/grafana/provisioning/alerting` |

**Особенности эксплуатации:**
1.  **Лимиты ConfigMap:** Общий размер данных в ConfigMap не должен превышать 1 МБ. Для больших дашбордов используйте сжатие (параметр `sidecar.dashboards.GZIP`).
2.  **Namespaces:** Параметр `sidecar.dashboards.searchNamespace: ALL` позволяет собирать дашборды со всего кластера. Требует соответствующих прав RBAC для ServiceAccount.
3.  **Hot Reload:** Grafana автоматически подхватывает файлы из директорий провижининга. Интервал сканирования настраивается в `sidecar.dashboards.watchInterval`.

### Высокая доступность (High Availability)

Увеличение количества реплик (`replicas > 1`) недостаточно для полноценного HA. Grafana требует централизованного хранилища состояния.

**Требования для HA:**
*   **Внешняя БД:** `grafana.database.*` (PostgreSQL версии 12+ или MySQL). SQLite не поддерживает конкурентный доступ.
*   **Shared Storage:** Для кастомных плагинов и аватаров (через PVC с `accessModes: [ReadWriteMany]`).
*   **Session Management:** Настройка Redis или базы данных для хранения сессий пользователей (`grafana.grafana.ini.sessions`).
*   **Sticky Sessions:** Рекомендуется на уровне Ingress для стабильной работы UI.

### Безопасность и аутентификация

В 2026 году стандарт безопасности включает:
*   **CSRF Protection:** Строгая проверка `cookie_samesite` в `grafana.ini`.
*   **OAuth/OIDC:** Интеграция с Keycloak, Authentik или GitHub через секции `[auth.generic_oauth]`.
*   **Secret Management:** Использование `existingSecret` для всех чувствительных данных (пароли БД, токены OAuth, SMTP).

## Практические сценарии

### Production-конфигурация с HA, внешней БД и OIDC

```yaml
grafana:
  enabled: true
  replicas: 2

  # Учетные данные через Secret
  admin:
    existingSecret: "grafana-admin-secret"
    adminUserKey: "username"
    adminPasswordKey: "password"

  # Конфигурация grafana.ini (v12.x)
  grafana.ini:
    server:
      root_url: "https://grafana.example.com"
    database:
      type: postgres
      host: "postgres.db.svc.cluster.local:5432"
      name: "grafana"
      user: "grafana"
      password: "${DB_PASSWORD}" # Берется из env
    auth.generic_oauth:
      enabled: true
      name: "Keycloak"
      client_id: "${OAUTH_CLIENT_ID}"
      client_secret: "${OAUTH_CLIENT_SECRET}"
      scopes: "openid profile email roles"
      auth_url: "https://auth.example.com/realms/master/protocol/openid-connect/auth"
      token_url: "https://auth.example.com/realms/master/protocol/openid-connect/token"
      api_url: "https://auth.example.com/realms/master/protocol/openid-connect/userinfo"
      role_attribute_path: "contains(roles[*], 'admin') && 'Admin' || contains(roles[*], 'editor') && 'Editor' || 'Viewer'"
    security:
      cookie_samesite: "strict"
      admin_only_org_create: true
    unified_alerting:
      enabled: true

  # Передача секретов в переменные окружения
  envFromSecret: "grafana-env-secret"

  # PersistentVolume (для плагинов)
  persistence:
    enabled: true
    type: pvc
    storageClassName: ceph-fs # Должен быть ReadWriteMany для HA
    accessModes:
      - ReadWriteMany
    size: 5Gi

  # Ресурсы
  resources:
    requests:
      cpu: 200m
      memory: 256Mi
    limits:
      cpu: 1000m
      memory: 1Gi

  # Sidecar-механизмы
  sidecar:
    dashboards:
      enabled: true
      label: grafana_dashboard
      labelValue: "1"
      searchNamespace: ALL
      folderAnnotation: "grafana_folder" # Поддержка папок
    datasources:
      enabled: true
      label: grafana_datasource
      labelValue: "1"
      searchNamespace: ALL
```

### Доступ через Ingress

```yaml
grafana:
  ingress:
    enabled: true
    ingressClassName: nginx
    annotations:
      cert-manager.io/cluster-issuer: letsencrypt
    hosts:
      - grafana.example.com
    tls:
      - secretName: grafana-tls
        hosts:
          - grafana.example.com
```

### Провижининг кастомных дашбордов через ConfigMap

Создайте ConfigMap с меткой `grafana_dashboard: "1"` и укажите папку через аннотацию:

```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: my-app-dashboard
  namespace: monitoring
  labels:
    grafana_dashboard: "1"
  annotations:
    grafana_folder: "Application Metrics"
data:
  my-app-dashboard.json: |
    {
      "uid": "my-app-dashboard",
      "title": "My Application Dashboard",
      "panels": [],
      "schemaVersion": 39
    }
```

> **См. также:** [Провижининг дашбордов через ConfigMap](../../../Grafana/grafana_provisioning.md).

### Проверка работы и диагностика

```bash
# Проверка основного контейнера
kubectl logs -n monitoring -l app.kubernetes.io/name=grafana -c grafana

# Проверка Sidecar-контейнера (критично при ошибках загрузки дашбордов)
kubectl logs -n monitoring -l app.kubernetes.io/name=grafana -c grafana-sc-dashboard

# Доступ через port-forward (если Ingress недоступен)
kubectl port-forward svc/monitoring-grafana -n monitoring 3000:80

# Извлечение пароля (при автогенерации)
kubectl get secret monitoring-grafana -n monitoring \
  -o jsonpath="{.data.admin-password}" | base64 -d
```

## Дополнительная информация

### Встроенные дашборды kube-prometheus-stack

Helm-чарт включает набор стандартных дашбордов (включается через `defaultDashboardsEnabled: true`).

**Ключевые категории (2026):**
*   **Kubernetes / Compute Resources:** Детализация по кластеру, узлам, неймспейсам и подам. Базируется на метриках `kube-state-metrics` и `cAdvisor`.
*   **Prometheus:** Состояние TSDB, загрузка CPU, ошибки Remote Write.
*   **Alertmanager:** Активные инциденты и статусы маршрутизации.
*   **CoreDNS / Node Exporter:** Производительность инфраструктурных компонентов.

> **Оптимизация:** При большом количестве неймспейсов генерация ConfigMap со встроенными дашбордами может превысить лимиты Kubernetes (1MB). В таких случаях рекомендуется включать только необходимые группы дашбордов через `coreDns.dashboards.enabled` и аналогичные параметры.

### Подбираемые параметры ресурсов (эмпирически)

| Параметр | Базовое значение | Метрика для мониторинга OOM/Троттлинга |
| :--- | :--- | :--- |
| `requests.memory` | `256Mi` | `container_memory_working_set_bytes` |
| `requests.cpu` | `100m` | `rate(container_cpu_cfs_throttled_seconds_total[5m])` |
| `persistence.size` | `10Gi` | `kubelet_volume_stats_available_bytes` |
| `replicas` | `2` (HA) | `up{job="grafana"}` |

### Интеграция с Unified Alerting

В Grafana 12.x система Unified Alerting включена по умолчанию. При интеграции с `kube-prometheus-stack` вы можете выбрать один из сценариев:
1.  Управлять алертами через CRD `PrometheusRule` (рекомендуется для K8s-нативного подхода).
2.  Настроить Alertmanager как Datasource в Grafana, чтобы отправлять оповещения из Grafana Alerting в единый Alertmanager кластера.

### Связанные темы

* [Обзор Grafana](../../../Grafana/grafana_overview.md) — архитектура платформы.
* [Установка Grafana через Helm](../../../Grafana/Installation/grafana_helm_installation.md) — standalone сценарий.
* [Провижининг конфигурации](../../../Grafana/grafana_provisioning.md) — подход Config as Code.
* [Источники данных](../../../Grafana/grafana_datasources.md) — настройка датасорсов.
* [Аутентификация и RBAC](../../../Grafana/grafana_user_management_and_authentication.md) — управление пользователями.
