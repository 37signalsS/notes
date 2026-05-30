# Конфигурация Grafana в kube-prometheus-stack

## Определения

**Grafana в kube-prometheus-stack** — компонент Helm-чарта, развёртывающий Grafana как Deployment с Sidecar-контейнером для автоматической загрузки дашбордов и источников данных из ConfigMap. Конфигурация управляется через `values.yaml` в секции `grafana.*`.

> **См. также:** [Обзор Grafana](../../../Grafana/grafana_overview.md), [Установка Grafana через Helm](../../../Grafana/Installation/grafana_helm_installation.md).

## Основные концепции

### Структура Helm-параметров

| Параметр | Описание | Значение по умолчанию |
| :--- | :--- | :--- |
| `grafana.enabled` | Включение компонента | `true` |
| `grafana.adminUser` | Имя администратора | `admin` |
| `grafana.adminPassword` | Пароль администратора | Автогенерация (из Secret) |
| `grafana.grafana.ini` | Конфигурация `grafana.ini` (server, auth, smtp) | `{}` |
| `grafana.sidecar.dashboards` | Sidecar для автоматической загрузки дашбордов | `enabled: true` |
| `grafana.sidecar.datasources` | Sidecar для автоматической настройки источников данных | `enabled: true` |
| `grafana.persistence` | PersistentVolume для хранения данных Grafana | `enabled: false` |
| `grafana.additionalGrafanaPlugins` | Дополнительные плагины | `[]` |
| `grafana.ingress` | Ingress для внешнего доступа | `enabled: false` |
| `grafana.replicas` | Количество реплик | `1` |

### Sidecar-механизм

Sidecar — контейнер в том же Pod, что и Grafana, который отслеживает изменения Kubernetes-ресурсов и загружает их в Grafana.

| Sidecar | Метка ConfigMap | Назначение |
| :--- | :--- | :--- |
| **Dashboards** | `grafana_dashboard: "1"` | Автозагрузка JSON-дашбордов |
| **Datasources** | `grafana_datasource: "1"` | Автонастройка источников данных |

**Ключевые параметры sidecar:**

| Параметр | Описание |
| :--- | :--- |
| `sidecar.dashboards.enabled` | Включение sidecar для дашбордов |
| `sidecar.dashboards.label` | Метка для поиска ConfigMap |
| `sidecar.dashboards.labelValue` | Значение метки (по умолчанию `"1"`) |
| `sidecar.dashboards.searchNamespace` | Namespace для поиска (`ALL` — все namespaces) |
| `sidecar.datasources.enabled` | Включение sidecar для datasources |
| `sidecar.datasources.label` | Метка для поиска ConfigMap |

### PersistentVolume

Grafana хранит в PVC: дашборды, созданные через UI, настройки пользователей, плагины, сессии. Без PVC данные теряются при перезапуске Pod.

| Режим | Когда использовать |
| :--- | :--- |
| `persistence.enabled: true` | Production — сохранение кастомных дашбордов |
| `persistence.enabled: false` (default) | Тестовые среды, все дашборды через ConfigMap |

### Безопасность и аутентификация

| Параметр | Описание |
| :--- | :--- |
| `grafana.admin.existingSecret` | Использование существующего Secret для пароля |
| `grafana.grafana.ini.server.root_url` | Публичный URL для корректных ссылок в алертах |
| `grafana.grafana.ini.auth` | Настройки OAuth/LDAP/GitHub аутентификации |
| `grafana.grafana.ini.security` | Настройки безопасности (admin-only org creation, etc.) |

## Практические сценарии

### Production-конфигурация с HA и PersistentVolume

```yaml
grafana:
  enabled: true
  replicas: 2

  # Учетные данные через Secret
  admin:
    existingSecret: "grafana-admin-secret"
    adminUserKey: "username"
    adminPasswordKey: "password"

  # Конфигурация grafana.ini
  grafana.ini:
    server:
      root_url: "https://grafana.example.com"
    auth:
      disable_login_form: false
    security:
      admin_only_org_create: true
    smtp:
      enabled: true
      host: "smtp.yandex.ru:465"
      user: "alerts@example.com"
      password: "${SMTP_PASSWORD}"
      from_address: "grafana@example.com"

  # PersistentVolume
  persistence:
    enabled: true
    type: pvc
    storageClassName: longhorn
    accessModes:
      - ReadWriteOnce
    size: 10Gi

  # Ресурсы
  resources:
    requests:
      cpu: 100m
      memory: 256Mi
    limits:
      cpu: 500m
      memory: 512Mi

  # Sidecar для дашбордов
  sidecar:
    dashboards:
      enabled: true
      label: grafana_dashboard
      labelValue: "1"
      searchNamespace: ALL
    datasources:
      enabled: true
      label: grafana_datasource
      labelValue: "1"
      searchNamespace: ALL
```

### Минимальная конфигурация для тестовой среды

```yaml
grafana:
  enabled: true
  adminPassword: "admin"
  persistence:
    enabled: false
  sidecar:
    dashboards:
      enabled: true
    datasources:
      enabled: true
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

### Провиженинг кастомных дашбордов через ConfigMap

Создайте ConfigMap с меткой `grafana_dashboard: "1"`:

```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: my-app-dashboard
  namespace: my-app
  labels:
    grafana_dashboard: "1"
data:
  my-app-dashboard.json: |
    {
      "uid": "my-app-dashboard",
      "title": "My Application Dashboard",
      "panels": [],
      "schemaVersion": 30
    }
```

> **См. также:** [Провиженинг дашбордов через ConfigMap](../../../Grafana/grafana_provisioning.md).

### Установка дополнительных плагинов

```yaml
grafana:
  additionalGrafanaPlugins:
    - grafana-piechart-panel
    - grafana-worldmap-panel
    - yesoreyeram-boomtable-panel
```

> **См. также:** [Плагины Grafana](../../../Grafana/grafana_plugins.md).

### Отключение Grafana

```yaml
grafana:
  enabled: false
```

> **Важно:** При отключении Grafana дашборды остаются доступны через прямой доступ к Prometheus UI (`/graph`). Однако визуализация и алертинг через Grafana будут недоступны.

### Проверка работы Grafana

```bash
# Проверка Pod Grafana
kubectl get pods -n monitoring -l app.kubernetes.io/name=grafana

# Проверка PVC
kubectl get pvc -n monitoring -l app.kubernetes.io/name=grafana

# Получение пароля администратора (автогенерация)
kubectl get secret monitoring-grafana -n monitoring \
  -o jsonpath="{.data.admin-password}" | base64 -d

# Доступ через port-forward
kubectl port-forward svc/monitoring-grafana -n monitoring 3000:80
```

### Создание Secret для пароля администратора

```bash
kubectl create secret generic grafana-admin-secret \
  --from-literal=username=admin \
  --from-literal=password="MySecurePassword123!" \
  -n monitoring
```

```yaml
grafana:
  admin:
    existingSecret: "grafana-admin-secret"
    adminUserKey: "username"
    adminPasswordKey: "password"
```

## Дополнительная информация

### Подбираемые параметры (эмпирически)

| Параметр | Начальное значение | Метрика для наблюдения |
| :--- | :--- | :--- |
| `requests.memory` | `256Mi` | `container_memory_usage_bytes` |
| `requests.cpu` | `100m` | `rate(container_cpu_usage_seconds_total[5m])` |
| `persistence.size` | `10Gi` | `kubelet_volume_stats_capacity_bytes` |
| `replicas` | `2` (HA) | `up{job="grafana"}` |

### Связанные темы

* [Обзор Grafana](../../../Grafana/grafana_overview.md) — общая информация о платформе
* [Установка Grafana через Helm](../../../Grafana/Installation/grafana_helm_installation.md) — standalone установка
* [Провиженинг](../../../Grafana/grafana_provisioning.md) — управление конфигурацией как код
* [Провиженинг дашбордов через ConfigMap](../../../Grafana/grafana_provisioning.md) — sidecar-механизм
* [Источники данных](../../../Grafana/grafana_datasources.md) — подключение Prometheus, Loki и др.
* [Плагины](../../../Grafana/grafana_plugins.md) — расширение функциональности
