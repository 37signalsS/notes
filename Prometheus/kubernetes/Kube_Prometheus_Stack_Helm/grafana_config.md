# Конфигурация Grafana в kube-prometheus-stack

## Определения

**Grafana в kube-prometheus-stack** — основной интерфейс визуализации стека мониторинга. В рамках Helm-чарта развёртывается как `Deployment` с набором вспомогательных контейнеров (sidecars) для реализации подхода **Monitoring as Code**.

**Grafana Sidecar (k8s-sidecar)** — специализированный контейнер (`kiwigrid/k8s-sidecar`), работающий в том же Pod, что и Grafana. Он отслеживает объекты ConfigMap и Secret в Kubernetes API и автоматически провижинит их содержимое (дашборды, источники данных, алерты) в Grafana без перезагрузки сервиса.

**Unified Alerting** — современная система оповещений (введена в Grafana 8+, стандарт в 12.x/13.x), объединяющая алертинг по метрикам, логам и внешним источникам в едином интерфейсе и API.

**Datasource UID** — уникальный идентификатор источника данных в Grafana, который стабилизирует ссылки из дашбордов и алертов. В контексте kube-prometheus-stack UID предотвращает поломку дашбордов при переименовании или миграции инстанса Prometheus.

**ServiceMonitor** — CRD Prometheus Operator, определяющий, как Prometheus должен скрейпить сервис. В контексте Grafana используется для самомониторинга (сбор метрик `/metrics` самой Grafana).

> **См. также:** [Обзор Grafana](../../../Grafana/grafana_overview.md), [Установка Grafana через Helm](../../../Grafana/Installation/grafana_helm_installation.md), [Интеграция с Prometheus Operator](../operator/grafana_integration.md).

## Основные концепции

### Архитектура Grafana в стеке

В kube-prometheus-stack Grafana развёртывается как стандартный компонент стека. Helm-чарт создаёт полный набор ресурсов:

| Ресурс | Назначение |
| :--- | :--- |
| `Deployment` | Основной контейнер Grafana + sidecar-контейнеры |
| `Service` | Внутренний доступ к порту `3000` |
| `ServiceAccount` | Учётная запись для sidecar и самого Grafana |
| `Role` / `RoleBinding` | Права на чтение ConfigMap/Secret в определённых неймспейсах |
| `Secret` | Учётные данные администратора и внешней БД |
| `Ingress` (опционально) | Внешний доступ через HTTP/HTTPS |
| `ServiceMonitor` (опционально) | Сбор метрик самой Grafana Prometheus-ом |
| `PersistentVolumeClaim` (опционально) | Сохранение настроек, плагинов, аватаров |

**Жизненный цикл:**
1. Helm-релиз создаёт ресурсы в порядке зависимости (Secret → PVC → ServiceAccount → RBAC → Deployment).
2. Pod запускается: init-контейнеры (если есть) → основной контейнер Grafana → sidecar-контейнеры.
3. Sidecar сканирует ConfigMap/Secret с заданными метками и копирует JSON-дашборды/YAML-конфигурации во временные директории.
4. Grafana подхватывает файлы из провиженинговых директорий (hot reload).
5. При обновлении Helm-релиза Kubernetes применяет Rolling Update: новый Pod готовится → readinessProve проходит → старый Pod завершается.

### Ключевые Helm-параметры (values.yaml)

| Параметр | Назначение | Особенности |
| :--- | :--- | :--- |
| `grafana.enabled` | Включение компонента | Обязателен для работы UI. |
| `grafana.adminPassword` | Пароль администратора | Рекомендуется `existingSecret`. |
| `grafana.grafana.ini` | Глобальные настройки сервера | Секции `[security]`, `[auth]`, `[unified_alerting]`. |
| `grafana.sidecar.dashboards` | Автозагрузка дашбордов | Поддерживает фильтрацию по лейблам и namespaces. |
| `grafana.sidecar.datasources` | Настройка источников | Автоматически подключает Prometheus и Loki. |
| `grafana.persistence` | PersistentVolume | Требуется для сохранения настроек пользователей. |
| `grafana.replicas` | Масштабирование | **Критично:** требует внешней БД (PostgreSQL/MySQL). |
| `grafana.database.*` | Внешняя БД | `type`, `host`, `name`, `user`, `existingSecret`. |
| `grafana.serviceMonitor.enabled` | Самомониторинг | Включает ServiceMonitor для сбора метрик Grafana. |
| `grafana.serviceMonitor.namespace` | Неймспейс ServiceMonitor | Обычно совпадает с `monitoring`. |
| `grafana.defaultDashboardsEnabled` | Встроенные дашборды | Включает набор стандартных дашбордов чарта. |
| `grafana.resources` | Лимиты ресурсов | `requests`/`limits` для CPU и памяти. |
| `grafana.podSecurityContext` | Безопасность пода | `runAsUser: 472`, `fsGroup: 472`. |
| `grafana.containerSecurityContext` | Безопасность контейнера | `readOnlyRootFilesystem: true`, `allowPrivilegeEscalation: false`. |

### Механизм Sidecar и провижининг

Sidecar-контейнер обеспечивает динамическую синхронизацию ресурсов Kubernetes с внутренним хранилищем Grafana.

| Тип ресурса | Метка (Label) | Путь монтирования |
| :--- | :--- | :--- |
| **Dashboards** | `grafana_dashboard: "1"` | `/tmp/dashboards` |
| **Datasources** | `grafana_datasource: "1"` | `/etc/grafana/provisioning/datasources` |
| **Alerts** | `grafana_alert: "1"` | `/etc/grafana/provisioning/alerting` |

**Особенности эксплуатации:**
1. **Лимиты ConfigMap:** Общий размер данных в ConfigMap не должен превышать 1 МБ. Для больших дашбордов используйте сжатие (параметр `sidecar.dashboards.GZIP`).
2. **Namespaces:** Параметр `sidecar.dashboards.searchNamespace: ALL` позволяет собирать дашборды со всего кластера. Требует соответствующих прав RBAC для ServiceAccount.
3. **Hot Reload:** Grafana автоматически подхватывает файлы из директорий провижининга. Интервал сканирования настраивается в `sidecar.dashboards.watchInterval`.
4. **Папки:** Используйте аннотацию `grafana_folder` (или `grafana_dashboard_folder` в зависимости от версии sidecar) для автоматического создания папок в UI.

### Встроенные дашборды kube-prometheus-stack

Helm-чарт включает набор стандартных дашбордов (включается через `defaultDashboardsEnabled: true`).

**Ключевые категории:**
- **Kubernetes / Compute Resources:** Детализация по кластеру, узлам, неймспейсам и подам. Базируется на метриках `kube-state-metrics` и `cAdvisor`.
- **Prometheus:** Состояние TSDB, загрузка CPU, ошибки Remote Write.
- **Alertmanager:** Активные инциденты и статусы маршрутизации.
- **CoreDNS / Node Exporter:** Производительность инфраструктурных компонентов.

**Оптимизация:** При большом количестве неймспейсов генерация ConfigMap со встроенными дашбордами может превысить лимиты Kubernetes (1MB). В таких случаях рекомендуется включать только необходимые группы дашбордов через `coreDns.dashboards.enabled` и аналогичные параметры.

### Высокая доступность (High Availability)

Увеличение количества реплик (`replicas > 1`) недостаточно для полноценного HA. Grafana требует централизованного хранилища состояния.

**Требования для HA:**
*   **Внешняя БД:** `grafana.database.*` (PostgreSQL версии 12+ или MySQL). SQLite не поддерживает конкурентный доступ.
*   **Shared Storage:** Для кастомных плагинов и аватаров (через PVC с `accessModes: [ReadWriteMany]`).
*   **Session Management:** Настройка Redis или базы данных для хранения сессий пользователей (`grafana.grafana.ini.sessions`).
*   **Sticky Sessions:** Рекомендуется на уровне Ingress для стабильной работы UI.
*   **secret_key:** Должен быть идентичен на всех репликах для валидации сессий и расшифровки секретов.

### Безопасность и аутентификация

*   **CSRF Protection:** Строгая проверка `cookie_samesite` в `grafana.ini`.
*   **OAuth/OIDC:** Интеграция с Keycloak, Authentik или GitHub через секции `[auth.generic_oauth]`.
*   **Secret Management:** Использование `existingSecret` для всех чувствительных данных (пароли БД, токены OAuth, SMTP).
*   **Pod Security:** `runAsUser: 472`, `readOnlyRootFilesystem: true`, `allowPrivilegeEscalation: false`.

## Практические сценарии

### Предварительные требования

- **Kubernetes** 1.25+ (1.28+ рекомендуется для Gateway API и стабильной работы Ingress).
- **Helm** 3.10+ (3.14+ рекомендуется для OCI-репозиториев).
- **StorageClass** с поддержкой `ReadWriteMany` (RWX) для HA-режима (CephFS, NFS, Longhorn).
- **Внешняя база данных** (PostgreSQL 12+ или MySQL) — обязательна для режима HA (`replicas > 1`).
- **Ingress-контроллер** (NGINX, Traefik) — если требуется внешний доступ.
- **cert-manager** — для автоматической выдачи и ротации TLS-сертификатов.
- **ServiceAccount** с правами на чтение ConfigMap/Secret в целевых неймспейсах.

### Сценарий 1: Production-конфигурация с HA, внешней БД и OIDC

```yaml
# values.yaml для kube-prometheus-stack
grafana:
  enabled: true
  replicas: 3

  # Учётные данные через Secret
  admin:
    existingSecret: "grafana-admin-secret"
    adminUserKey: "username"
    adminPasswordKey: "password"

  # Конфигурация grafana.ini (v13.x)
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
      provider:
        foldersFromFilesStructure: true # Создание папок по структуре ФС
    datasources:
      enabled: true
      label: grafana_datasource
      labelValue: "1"
      searchNamespace: ALL

  # ServiceMonitor для самомониторинга
  serviceMonitor:
    enabled: true
    namespace: monitoring
    interval: 30s
    labels:
      release: kube-prometheus-stack

  # Безопасность пода
  podSecurityContext:
    runAsUser: 472
    runAsGroup: 472
    fsGroup: 472
    fsGroupChangePolicy: "OnRootMismatch"

  containerSecurityContext:
    allowPrivilegeEscalation: false
    readOnlyRootFilesystem: true
    capabilities:
      drop:
        - ALL
```

### Сценарий 2: Установка и валидация

```bash
# 1. Добавление репозитория
helm repo add prometheus-community https://prometheus-community.github.io/helm-charts
helm repo update

# 2. Установка/обновление релиза
helm upgrade --install monitoring prometheus-community/kube-prometheus-stack \
  -f values.yaml \
  --namespace monitoring \
  --create-namespace \
  --atomic \
  --timeout 10m

# 3. Проверка подов и контейнеров (основной и sidecar)
kubectl get pods -n monitoring -l app.kubernetes.io/name=grafana
# → NAME                         READY   STATUS    RESTARTS   AGE
# → monitoring-grafana-XXXX-xxxxx           2/2     Running   0          1m

# 4. Проверка PVC
kubectl get pvc -n monitoring
# → NAME                 STATUS   VOLUME                                     CAPACITY   ACCESS MODES   STORAGECLASS
# → data-monitoring-grafana-xxxxx   Bound    pvc-xxxxx-xxxxx-xxxxx                      10Gi       RWX            ceph-fs

# 5. Проверка Ingress
kubectl get ingress -n monitoring
# → NAME        CLASS   HOSTS                 ADDRESS   PORTS   AGE
# → monitoring-grafana   nginx   grafana.example.com             80, 443 1m

# 6. Проверка логов sidecar (критично при ошибках загрузки дашбордов)
kubectl logs -n monitoring -l app.kubernetes.io/name=grafana -c grafana-sc-dashboards
# → 2026/08/24 17:00:00 {"dashboard":"default/my-app-dashboard","namespace":"monitoring","message":"Added dashboard from ConfigMap"}

# 7. Проверка логов основного контейнера
kubectl logs -n monitoring -l app.kubernetes.io/name=grafana -c grafana
# → t=2026-08-24T17:00:00+0000 lvl=info msg="Starting Grafana" version=13.0.0
```

### Сценарий 3: Проверка работы и диагностика

```bash
# Доступ через port-forward (если Ingress недоступен)
kubectl port-forward svc/monitoring-grafana -n monitoring 3000:80

# Извлечение пароля (при автогенерации)
kubectl get secret monitoring-grafana -n monitoring \
  -o jsonpath="{.data.admin-password}" | base64 -d

# Проверка API здоровья
curl -s -o /dev/null -w "%{http_code}" http://admin:admin123@localhost:3000/api/health
# → 200

# Проверка метрик самой Grafana
curl -s http://localhost:3000/metrics | grep grafana_http_request_duration_seconds_count | head

# Просмотр событий Deployment
kubectl describe deployment monitoring-grafana -n monitoring
```

### Сценарий 4: Провижининг кастомных дашбордов через ConfigMap

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

**Генерация ConfigMap через Kustomize.** В production-репозиториях дашборды обычно собираются через `configMapGenerator` с `disableNameSuffixHash: true` — без этого Kustomize добавляет хеш-суффикс к имени ConfigMap, и sidecar создаёт **новые** дашборды, не удаляя старые (дублирование после обновления).

```yaml
# kustomization.yaml
configMapGenerator:
  - name: grafana-dashboards-infra
    namespace: observability
    options:
      disableNameSuffixHash: true
      labels:
        grafana_dashboard: "1"
      annotations:
        grafana_folder: "Infrastructure"
    files:
      - dashboards/cluster-overview.json
      - dashboards/flux-reconciliation.json
      - dashboards/elasticsearch-cluster.json
```

> **Важно:** при `disableNameSuffixHash: true` смена данных не вызовет автоматический rolling update. Для применения изменений используйте `kubectl rollout restart deployment/kube-prom-stack-grafana -n observability` вручную, либо используйте аннотацию `checksum/config` в шаблоне пода. Подробнее о паттерне: [Генераторы ConfigMap и Secret](../../Kubernetes/ToolsUtilities/kustomize/kustomize_generators.md#32-отключение-хеш-суффикса).

**Подготовка JSON-дашбордов для Git.** Перед коммитом в репозиторий:

1. **Удалите поле `id`** — оно специфично для конкретного кластера Grafana и приводит к конфликтам при переносе дашборда между инстансами.
2. **Замените жёстко заданные UID datasource на переменную** — иначе дашборд будет привязан к конкретному источнику и не перенесётся между окружениями:

```json
{
  "templating": {
    "list": [
      {
        "name": "datasource",
        "type": "datasource",
        "query": "prometheus"
      }
    ]
  },
  "panels": [
    {
      "datasource": {"type": "prometheus", "uid": "${datasource}"}
    }
  ]
}
```

**Структура папок по доменам:**

```
dashboards/
  infrastructure/
    cluster-overview.json
    node-exporter.json
  application/
    apisix.json
    elasticsearch.json
  flux/
    flux-control-plane.json
    flux-reconciliation.json
```

С combined `foldersFromFilesStructure: true` и аннотацией `grafana_folder` папки создаются автоматически. При работе с Flux каждая директория или ConfigMap становится отдельным kustomize-источником, применяемым автоматически — никакого ручного импорта дашбордов из UI.

### Сценарий 5: Upgrade и Rollback релиза

```bash
# Просмотр истории релизов
helm history monitoring --namespace monitoring

# Upgrade с фиксацией версии чарта
helm upgrade monitoring prometheus-community/kube-prometheus-stack \
  --version 55.0.0 \
  -f values.yaml \
  --namespace monitoring \
  --atomic \
  --timeout 10m

# Rollback на предыдущую ревизию (если upgrade провалился)
helm rollback monitoring 1 --namespace monitoring

# Проверка после rollback
kubectl get pods -n monitoring -l app.kubernetes.io/name=grafana
```

### Сценарий 6: Резервное копирование и восстановление

```bash
# 1. Список всех Helm-релизов
helm list -A | grep monitoring

# 2. Экспорт значений релиза
helm get values monitoring -n monitoring > backup-values.yaml

# 3. Экспорт всех ConfigMap с дашбордами
kubectl get cm -n monitoring -l grafana_dashboard=1 -o yaml > grafana-dashboards-backup-$(date +%Y%m%d).yaml

# 4. Экспорт всех ConfigMap с источниками данных
kubectl get cm -n monitoring -l grafana_datasource=1 -o yaml > grafana-datasources-backup-$(date +%Y%m%d).yaml

# Восстановление из backup
kubectl apply -f grafana-dashboards-backup-20260101.yaml
kubectl apply -f grafana-datasources-backup-20260101.yaml
```

### Сценарий 7: Очистка окружения

```bash
# Полное удаление релиза и всех ресурсов
helm uninstall monitoring --namespace monitoring

# С сохранением History (для возможного отката)
helm uninstall monitoring --namespace monitoring --keep-history

# Удаление PVC (если не требуется сохранение данных)
kubectl delete pvc -n monitoring -l app.kubernetes.io/name=grafana

# Удаление неймспейса (если он создавался для стека)
kubectl delete namespace monitoring
```

### Сценарий 8: Провижининг источников данных и контакт-пойнтов через additionalDataSources

Параметр `grafana.additionalDataSources` в values.yaml kube-prometheus-stack позволяет добавлять источники данных сверх тех, что создаются автоматически (Prometheus, Loki, Alertmanager). Параметр `grafana.alerting.contactpoints.yaml` аналогично добавляет контакт-пойнты через Helm values. Оба параметра передаются в Grafana как файлы провижининга (см. [Файлы провиженинга источников данных](../../Grafana/grafana_provisioning.md#провиженинг-источников-данных-datasources)).

```yaml
# values.yaml
grafana:
  # Дополнительные источники данных (передаются в provisioning/datasources/*.yaml)
  additionalDataSources:
    - name: Prometheus-dev
      type: prometheus
      url: http://prometheus-operated.observability.svc.cluster.local:9090
      isDefault: false
      jsonData:
        timeInterval: "30s"
        exemplarTraceIdDestinations:
          - name: trace_id
            datasourceUid: tempo

    - name: VictoriaMetrics
      type: prometheus
      url: http://victoria-metrics.observability.svc.cluster.local:8428
      isDefault: false

    - name: Elasticsearch
      type: elasticsearch
      url: http://elasticsearch-master.observability.svc.cluster.local:9200
      jsonData:
        index: "vector-*"
        timeField: "@timestamp"
        logMessageField: message

    - name: Loki-VictoriaLogs
      type: loki
      url: http://victoria-logs.observability.svc.cluster.local:9428

  # Контакт-пойнты через Helm values (передаются в provisioning/alerting/*.yaml)
  alerting:
    contactpoints.yaml:
      apiVersion: 1
      contactPoints:
        - orgId: 1
          name: Telegram
          receivers:
            - uid: telegram-receiver
              type: telegram
              settings:
                bottoken: "${TELEGRAM_BOT_TOKEN}"
                chatid: "${TELEGRAM_CHAT_ID}"
```

**Ожидаемый результат:** после `helm upgrade --install` контейнер sidecar копирует YAML-файлы в `/etc/grafana/provisioning/datasources` и `/etc/grafana/provisioning/alerting` соответственно; Grafana применяет их при старте и при hot reload.

**Валидация:**
```bash
# Проверка источников данных
kubectl exec -n observability deploy/kube-prom-stack-grafana -- \
  curl -s -H "Authorization: Bearer <SA_TOKEN>" \
  http://localhost:3000/api/datasources/uid/prometheus-dev | jq '.uid'
# → "prometheus-dev"

# Проверка логов sidecar
kubectl logs -n observability deploy/kube-prom-stack-grafana -c grafana-sc-dashboard
```

**Типичные проблемы:**
- Источник не появляется — проверьте, что `url` соответствует DNS-имени сервиса в нужном неймспейсе; проверьте через `kubectl exec` из пода Grafana: `curl -v http://prometheus-operated.observability.svc.cluster.local:9090`.
- Контакт-пойнт не создаётся — убедитесь, что переменные окружения (`${TELEGRAM_BOT_TOKEN}`) переданы в контейнер Grafana через `env`/`envFrom`. Интерполяция выполняется только при загрузке файла; ротация требует рестарта.

## Дополнительная информация

### Подбираемые параметры ресурсов (эмпирически)

| Параметр | Базовое значение | Метрика для мониторинга OOM/Троттлинга |
| :--- | :--- | :--- |
| `requests.memory` | `256Mi` | `container_memory_working_set_bytes` |
| `requests.cpu` | `100m` | `rate(container_cpu_cfs_throttled_seconds_total[5m])` |
| `persistence.size` | `10Gi` | `kubelet_volume_stats_available_bytes` |
| `replicas` | `2` (HA) | `up{job="grafana"}` |

### Интеграция с Unified Alerting

В Grafana 12.x/13.x система Unified Alerting включена по умолчанию. При интеграции с `kube-prometheus-stack` вы можете выбрать один из сценариев:
1.  Управлять алертами через CRD `PrometheusRule` (рекомендуется для K8s-нативного подхода).
2.  Настроить Alertmanager как Datasource в Grafana, чтобы отправлять оповещения из Grafana Alerting в единый Alertmanager кластера.
3.  Использовать SNE (Single-Node Evaluation) для HA-режима, чтобы только Primary-узел выполнял вычисления.

### Устранение неполадок (Troubleshooting)

| Симптом | Вероятная причина | Решение |
| :--- | :--- | :--- |
| **Pod CrashLoopBackOff** | Ошибка в `grafana.ini` или правах на PVC | Проверьте логи: `kubectl logs <pod> -c grafana`; проверьте SecurityContext и права на PVC |
| **Дашборды не импортируются** | Отсутствует метка на ConfigMap или неверный JSON | Проверьте наличие label `grafana_dashboard: "1"`; валидируйте JSON-схему |
| **Дублирование дашбордов после обновления** | Kustomize добавил хеш-суффикс к имени ConfigMap | Используйте `disableNameSuffixHash: true` в `configMapGenerator`; [подробности](../../Kubernetes/ToolsUtilities/kustomize/kustomize_generators.md#32-отключение-хеш-суфикса) |
| **Sidecar не синхронизирует** | Неверная метка/неймспейс/путь | Сверьте `grafana_dashboard: "1"`, `searchNamespace`, путь назначения sidecar |
| **ServiceMonitor не собирает метрики** | Несоответствие селекторов меток | Убедитесь, что метки в `serviceMonitor.labels` совпадают с ожидаемыми в Prometheus Operator |
| **Grafana недоступна через Ingress** | Неверный `root_url` или проблемы с TLS | Проверьте `grafana.ini.server.root_url` и статус сертификата: `kubectl describe certificate` |
| **OOMKilled** | Недостаточно памяти для загрузки больших дашбордов | Увеличьте `resources.limits.memory`; включите `sidecar.dashboards.GZIP: true` |
| **RBAC Error (sidecar)** | ServiceAccount не имеет прав на чтение ConfigMap в неймспейсах | Расширьте Role или используйте ClusterRole с правильным селектором неймспейсов |

### Ограничения и особые случаи (Edge Cases)

1. **Лимит размера ConfigMap (1 МБ):** Kubernetes ограничивает размер ConfigMap 1 МБ. Если дашборды не загружаются, включите `sidecar.dashboards.GZIP: true` или разбейте дашборды на несколько ConfigMap.
2. **ReadWriteMany (RWX):** Требуется для HA-режима (совместный доступ к плагинам и аватарам). Убедитесь, что ваш StorageClass поддерживает RWX. Если нет, используйте внешнее хранилище (NFS, CephFS, Longhorn).
3. **Configuration Drift:** Изменения, сделанные через UI, не сохраняются обратно в конфигурационные файлы. После перезапуска Grafana вернет состояние, описанное в провиженинговых файлах. Используйте `editable: false` для источников данных, чтобы исключить конфликты.
4. **SQLite в HA:** SQLite не поддерживает одновременную запись из нескольких процессов. В HA-режиме используйте исключительно PostgreSQL или MySQL.
5. **Время drift в HA:** Разница во времени между узлами >500 мс приводит к дребезгу алертов. Обязательно используйте NTP/Chrony.
6. **Downgrade:** Grafana 13.x не поддерживает downgrade до 11.x без потери данных (изменения схемы БД). Всегда тестируйте обновления.

### Связанные темы

- [Конфигурация компонентов](./other_components_config.md) — детализация разделов `values.yaml` (RBAC, reload, default rules, Thanos Ruler, Push Gateway).
- [Конфигурация Alertmanager](./alertmanager_config.md) — routing, receivers, AlertmanagerConfig CRD.
- [Конфигурация Grafana](../../../Grafana/grafana_provisioning.md) — провижининг, sidecar, дашборды.
- [Источники данных Grafana](../../../Grafana/grafana_datasources.md) — параметры подключений к Prometheus, Loki, Elasticsearch.
- [Контакт-пойнты и алертинг](../../../Grafana/alerting/provisioning.md) — файловый провиженинг контакт-пойнтов, политик, шаблонов.
- [Monitoring as Code](../../../Grafana/monitoring_as_code.md) — GitOps, Git Sync, Flux, kustomize для дашбордов и алертинга.
- [Генераторы ConfigMap и Secret](../../Kubernetes/ToolsUtilities/kustomize/kustomize_generators.md) — `configMapGenerator` с `disableNameSuffixHash`.
- [Практические сценарии](./practical_scenarios.md) — специфические кейсы установки.
- [Мониторинг etcd](./etcd-monitoring.md) — TLS, ServiceMonitor, EndpointSlice.
