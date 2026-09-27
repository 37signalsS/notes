# Интеграция Grafana с Prometheus Operator

## Определения

**Интеграция Grafana в Prometheus Operator** — процесс обеспечения визуализации метрик, собранных Оператором, с использованием механизмов автоматического обнаружения (discovery) и провижининга. В рамках стандартного стека (`kube-prometheus-stack`) Grafana развёртывается как стандартный Deployment с вспомогательными sidecar-контейнерами для динамической загрузки конфигурации.

**Grafana Sidecar (k8s-sidecar)** — специализированный контейнер (`kiwigrid/k8s-sidecar`), работающий в том же поде, что и Grafana. Он отслеживает объекты ConfigMap и Secret в Kubernetes API по специфическим меткам и автоматически монтирует их содержимое в файловую систему Grafana, инициируя обновление дашбордов и источников данных без перезагрузки сервиса.

**Grafana Alloy** — универсальный агент сбора телеметрии (метрики, логи, трассировки), пришедший на смену Grafana Agent в конце 2025 года. Он нативно поддерживает CRD Prometheus Operator (`ServiceMonitor`, `PodMonitor`) и является рекомендуемым компонентом для интеграции в современные (2026+) observability-стеки.

**LGTM Stack** — стандартный набор компонентов observability: **L**ogs (логи), **G**rafana (визуализация), **T**races (трассировки), **M**etrics (метрики). В контексте Prometheus Operator LGTM означает связку Prometheus + Alertmanager + Grafana (+ Loki/Tempo для логов и трейсов).

**Datasource UID** — уникальный идентификатор источника данных в Grafana, который стабилизирует ссылки из дашбордов и алертов. Вместо имени датасорса используются UID, что предотвращает поломку дашбордов при переименовании или миграции.

**Grafana Operator** — отдельный Kubernetes Operator (от Grafana Labs), управляющий инстансами Grafana через CRD `Grafana`. В контексте Prometheus Operator он может использоваться как альтернатива sidecar-провижинингу, но обеспечивает более строгий контроль над конфигурацией через Kubernetes-native API.

**ServiceMonitor Auto-Discovery** — механизм, при котором Prometheus Operator автоматически добавляет Prometheus-инстансы как targets. Sidecar или Grafana Operator могут затем автоматически создавать источники данных в Grafana на основе обнаруженных ServiceMonitor'ов.

> **Смотрите также:** [Обзор Grafana](../../../Grafana/grafana_overview.md), [Концепции Prometheus Operator](./concepts.md), [Конфигурация Grafana в Helm](../Kube_Prometheus_Stack_Helm/grafana_config.md).

## Основные концепции

### Почему для Grafana нет CRD в базовом Операторе

Prometheus Operator изначально спроектирован для управления жизненным циклом Prometheus и Alertmanager. Grafana является независимым инструментом визуализации. Разработчики стека выбрали путь интеграции через нативные ресурсы Kubernetes (ConfigMap, Secret) вместо создания проприетарных CRD. Это обеспечивает:
- **Переносимость:** Дашборды остаются стандартными JSON-файлами.
- **GitOps-совместимость:** Любой инструмент (ArgoCD, Flux) может управлять дашбордами через стандартные манифесты ConfigMap.
- **Гибкость:** Возможность использования различных версий Grafana и внешних инстансов без ожидания обновлений Оператора.

### Механизмы интеграции: Sidecar vs Alloy vs Grafana Operator

Начиная с 2025–2026 годов, в экосистеме Kubernetes установились три основных подхода:

| Характеристика | Grafana Sidecar (k8s-sidecar) | Grafana Alloy (Flow mode) | Grafana Operator |
| :--- | :--- | :--- | :--- |
| **Основная роль** | Провижининг дашбордов и Data Sources. | Сбор телеметрии, интеграция OTLP и CRD. | Полное управление жизненным циклом Grafana через CRD. |
| **Механизм работы** | Сканирование ConfigMap/Secret по лейблам. | Компонентная модель (River), поддержка ServiceMonitor. | Reconcile-цикл, аналогичный Prometheus Operator. |
| **Безопасность** | RBAC для чтения ConfigMap/Secret. | mTLS, токены ServiceAccount. | Kubernetes-native RBAC + Grafana API keys. |
| **Lifecycle** | Обычный контейнер в поде Grafana. | Native Sidecar (K8s 1.29+) или独立 Deployment. | CRD驱动的控制器，独立于 Grafana Pod. |
| **Гибкость** | Высокая (стандартные K8s ресурсы). | Средняя (требует изучение River). | Низкая (привязан к версии Operator). |

### ServiceMonitor Auto-Discovery flow

При использовании Prometheus Operator связка работает следующим образом:

1.  **Prometheus Operator** создает `Prometheus` CR и генерирует конфигурацию `prometheus.yaml` с секцией `scrape_configs` для всех `ServiceMonitor` и `PodMonitor`.
2.  **Prometheus** начинает скрейпить targets по этим конфигурациям.
3.  **Sidecar (k8s-sidecar)** или **Grafana Operator** обнаруживает изменения в ConfigMap/Secret, созданных оператором или пользователем.
4.  При наличии ConfigMap с меткой `grafana_datasource: "1"` sidecar автоматически создает источник данных в Grafana, указывающий URL Prometheus API (обычно `http://<prometheus-service>:9090`).
5.  **Grafana** подключается к Prometheus и начинает отображать метрики.

**Важно для SRE:** В этом потоке нет автоматического создания датасорса "из ничего" — требуется явный ConfigMap или `GrafanaDatasource` CR (если используется Grafana Operator). Sidecar не создает источники данных на основе ServiceMonitor'ов сам; он только синхронизирует уже описанные в K8s ресурсы.

### RBAC и права доступа для Sidecar

Для работы sidecar-контейнеру необходим ServiceAccount с правами на чтение ConfigMap и Secret в целевых неймспейсах. Минимальная политика:

```yaml
apiVersion: v1
kind: ServiceAccount
metadata:
  name: grafana-sc-sa
  namespace: monitoring
---
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRole
metadata:
  name: grafana-sc-role
rules:
  - apiGroups: [""]
    resources: ["configmaps", "secrets"]
    verbs: ["get", "list", "watch"]
  - apiGroups: [""]
    resources: ["namespaces"]
    verbs: ["get", "list"]
---
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRoleBinding
metadata:
  name: grafana-sc-binding
subjects:
  - kind: ServiceAccount
    name: grafana-sc-sa
    namespace: monitoring
roleRef:
  kind: ClusterRole
  name: grafana-sc-role
  apiGroup: rbac.authorization.k8s.io
```

**Безопасность (2026):** Ограничьте `searchNamespace` конкретными неймспейсами вместо `ALL`. Используйте `watch` с таймаутом, чтобы избежать утечек ресурсов API. Для production сред добавьте NetworkPolicy, разрешающую egress только к API Server (port 443) и DNS (port 53).

### Взаимодействие с Prometheus Operator и ServiceMonitor

Prometheus Operator не управляет дашбордами напрямую, но через механизм `externalLabels` и стандартизированные имена сервисов можно строить предсказуемые источники данных. Рекомендуется:
- Использовать стабильный `serviceMonitorSelector` в ресурсе `Prometheus`.
- Указывать `externalLabels` для Prometheus, чтобы отличать данные разных кластеров/HA-групп.
- В дашбордах использовать переменные на основе `label_values(prometheus_replica, job)` для переключения между инстансами.

### Архитектура обнаружения ресурсов

Sidecar-контейнер реализует декларативный подход "наблюдай и обновляй":

1.  **Watch (Наблюдение):** Sidecar следит за событиями в Kubernetes API.
2.  **Фильтрация:** Выбираются только ресурсы с метками:
    - `grafana_dashboard: "1"` — для дашбордов.
    - `grafana_datasource: "1"` — для источников данных.
3.  **Синхронизация:** JSON-содержимое записывается в `/tmp/dashboards` или `/etc/grafana/provisioning/datasources`.
4.  **Hot Reload:** Grafana сканирует эти директории и мгновенно отображает изменения в UI.

## Практические сценарии

### Сценарий 1: Интеграция с внешней Grafana через mTLS

Если Grafana развернута в отдельном кластере или как Managed Service:

1.  **Настройка Prometheus:** В ресурсе `Prometheus` настраивается Remote Write или открывается доступ к API через Ingress/Gateway API.
2.  **Безопасность (2026):** Использование `cert-manager` для генерации сертификатов. В Grafana создается Data Source с включенным TLS и указанием CA, клиентского сертификата и ключа.
3.  **URL источника:** Используется внешний адрес, например `https://prometheus.monitoring.example.com`.

**Полная конфигурация NetworkPolicy для внешней Grafana:**
```yaml
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: allow-grafana-to-prometheus
  namespace: monitoring
spec:
  podSelector:
    matchLabels:
      app.kubernetes.io/name: prometheus
  policyTypes:
    - Ingress
  ingress:
    - from:
        - podSelector:
            matchLabels:
              app.kubernetes.io/name: grafana
          namespaceSelector:
            matchLabels:
              kubernetes.io/metadata.name: monitoring
      ports:
        - protocol: TCP
          port: 9090
```

### Сценарий 2: Полный Deployment Grafana с Sidecar и RBAC

Минимальная конфигурация для production:

```yaml
apiVersion: v1
kind: ServiceAccount
metadata:
  name: grafana-sc-sa
  namespace: monitoring
---
apiVersion: apps/v1
kind: Deployment
metadata:
  name: grafana
  namespace: monitoring
spec:
  replicas: 1
  selector:
    matchLabels:
      app.kubernetes.io/name: grafana
  template:
    metadata:
      labels:
        app.kubernetes.io/name: grafana
    spec:
      serviceAccountName: grafana-sc-sa
      containers:
        - name: grafana
          image: grafana/grafana:12.0.0
          ports:
            - containerPort: 3000
              name: http
          livenessProbe:
            httpGet:
              path: /api/health
              port: http
            initialDelaySeconds: 30
            periodSeconds: 10
          readinessProbe:
            httpGet:
              path: /api/health
              port: http
            initialDelaySeconds: 5
            periodSeconds: 5
          volumeMounts:
            - name: grafana-storage
              mountPath: /var/lib/grafana
        - name: grafana-sc-dashboards
          image: kiwigrid/k8s-sidecar:latest
          env:
            - name: LABEL
              value: "grafana_dashboard"
            - name: FOLDER
              value: "/tmp/dashboards"
          volumeMounts:
            - name: dashboards
              mountPath: /tmp/dashboards
      volumes:
        - name: dashboards
          emptyDir: {}
        - name: grafana-storage
          persistentVolumeClaim:
            claimName: grafana-pvc
---
apiVersion: v1
kind: Service
metadata:
  name: grafana
  namespace: monitoring
spec:
  selector:
    app.kubernetes.io/name: grafana
  ports:
    - port: 80
      targetPort: http
      name: http
```

**RBAC для sidecar:**
```yaml
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRole
metadata:
  name: grafana-sc-role
rules:
  - apiGroups: [""]
    resources: ["configmaps", "secrets"]
    verbs: ["get", "list", "watch"]
  - apiGroups: [""]
    resources: ["namespaces"]
    verbs: ["get", "list"]
---
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRoleBinding
metadata:
  name: grafana-sc-binding
subjects:
  - kind: ServiceAccount
    name: grafana-sc-sa
    namespace: monitoring
roleRef:
  kind: ClusterRole
  name: grafana-sc-role
  apiGroup: rbac.authorization.k8s.io
```

### Сценарий 3: Управление дашбордами как код (GitOps)

Для автоматизации добавления дашбордов через ArgoCD/Flux:

1.  Создайте манифест ConfigMap.
2.  Добавьте JSON дашборда в секцию `data`.
3.  Установите необходимые аннотации для sidecar:

```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: app-health-dashboard
  namespace: monitoring
  labels:
    grafana_dashboard: "1"
  annotations:
    k8s-sidecar-target-directory: "/tmp/dashboards/application"
    grafana_folder: "Application Metrics" # Папка в UI (v11+)
spec:
  data:
    app-metrics.json: |-
      {
        "uid": "app-metrics-2026",
        "title": "Application Metrics",
        "panels": [],
        "schemaVersion": 39,
        "version": 1
      }
```

**Валидация:**
```bash
kubectl get cm -n monitoring -l grafana_dashboard=1
kubectl logs -n monitoring -l app.kubernetes.io/name=grafana -c grafana-sc-dashboards | grep -i "loaded dashboard"
```

### Сценарий 4: Provisioning Prometheus DataSource через ConfigMap

Автоматическое создание источника данных для Prometheus Operator:

```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: prometheus-datasource
  namespace: monitoring
  labels:
    grafana_datasource: "1"
data:
  prometheus.yaml: |-
    apiVersion: 1
    datasources:
      - name: Prometheus-Prod
        type: prometheus
        uid: prometheus-prod-01
        url: http://prometheus-operated.monitoring.svc.cluster.local:9090
        access: proxy
        isDefault: true
        editable: false
        jsonData:
          timeInterval: "15s"
          httpMethod: "POST"
          queryTimeout: "60s"
          manageAlerts: true
        secureJsonData:
          basicAuthUser: "prometheus"
          basicAuthPassword: "${PROM_PASSWORD}"
```

**Важно:** Используйте `uid` для стабильных ссылок. `isDefault: true` делает источник данных выбранным по умолчанию в новых дашбордах. `editable: false` защищает от случайных изменений через UI.

### Сценарий 5: Использование Grafana Alloy как Native Sidecar

В Kubernetes 1.29+ Alloy может работать как `initContainer` с `restartPolicy: Always`, обеспечивая сбор метрик с первых секунд жизни пода.

```yaml
spec:
  initContainers:
    - name: alloy
      image: grafana/alloy:v1.3.0
      restartPolicy: Always
      args: ["run", "--server.http.listen-addr=0.0.0.0:12345", "/etc/alloy/config.alloy"]
      # Alloy автоматически обнаружит ServiceMonitor этого приложения
```

### Сценарий 6: Backup и восстановление настроек Grafana

Для SRE критически важно иметь версионное резервное копирование дашбордов и источников данных. Sidecar предоставляет простой способ:

```bash
# Экспорт всех дашбордов из ConfigMap
kubectl get cm -n monitoring -l grafana_dashboard=1 -o yaml > grafana-dashboards-backup-$(date +%Y%m%d).yaml

# Экспорт всех источников данных
kubectl get cm -n monitoring -l grafana_datasource=1 -o yaml > grafana-datasources-backup-$(date +%Y%m%d).yaml

# Восстановление из backup
kubectl apply -f grafana-dashboards-backup-20260101.yaml
kubectl apply -f grafana-datasources-backup-20260101.yaml
```

Для полного бэкапа (включая пользователей, папки, настройки) используйте HTTP API:

```bash
GRAFANA_URL="http://grafana.monitoring.svc.cluster.local:3000"
API_TOKEN="eyJrIjoi..."

curl -s -H "Authorization: Bearer ${API_TOKEN}" \
  "${GRAFANA_URL}/api/admin/export" > grafana-full-backup-$(date +%Y%m%d).json
```

## Дополнительная информация

### Диагностика проблем интеграции

Если дашборд или источник данных не появляется в Grafana:

1.  **Проверка меток:** `kubectl get cm -n <namespace> -l grafana_dashboard=1` — убедитесь, что ресурс виден.
2.  **Логи sidecar-контейнера:**
    `kubectl logs -f <grafana-pod> -c grafana-sc-dashboards`
    Ищите ошибки `Forbidden` (проблемы RBAC) или `Invalid JSON`.
3.  **Объем ConfigMap:** Помните о лимите в 1MB на один ConfigMap. Большие дашборды следует разбивать или использовать Gzip-сжатие (поддерживается `k8s-sidecar`).
4.  **RBAC проверка:**
    ```bash
    kubectl auth can-i get configmaps \
      --as=system:serviceaccount:monitoring:grafana-sc-sa \
      -n monitoring
    ```
5.  **NetworkPolicy проверка:**
    ```bash
    kubectl exec -n monitoring <grafana-pod> -- curl -sI http://prometheus-operated.monitoring.svc.cluster.local:9090
    ```
6.  **Проверка health endpoint Grafana:**
    ```bash
    kubectl exec -n monitoring <grafana-pod> -c grafana -- curl -s http://localhost:3000/api/health
    # → {"commit":"...","database":"ok","version":"12.0.0"}
    ```

### Совместимость версий

| Компонент | Минимальная версия | Рекомендуемая | Примечание |
| :--- | :--- | :--- | :--- |
| **Grafana** | 11.0 | 12.x (LTS) или 13.x | До 11.x нет unified alerting и RBAC provisioning. |
| **k8s-sidecar** | 1.8.0 | latest | В 1.8+ добавлена поддержка `grafana_alert` и папок. |
| **Grafana Alloy** | 1.3.0 | latest | Требует K8s 1.29+ для Native Sidecar. |
| **Prometheus Operator** | 0.62+ | 0.72+ | Для корректной работы с externalLabels. |
| **Kubernetes** | 1.24 | 1.29+ | Для Native Sidecar и `restartPolicy: Always`. |

### Best Practices

1.  **UID стабильности:** Всегда задавайте `uid` вручную для датасорсов и дашбордов. Это защищает от случайных пересозданий при изменении `name`.
2.  **editable: false:** Запрещайте редактирование из UI для всех провижининых ресурсов. Источник истины — Git.
3.  **ConfigMap размер:** Один ConfigMap < 1MB. Для больших дашбордов используйте Gzip (`sidecar.dashboards.GZIP: true`) или разделение на файлы.
4.  **RBAC минимальные права:** Раздавайте sidecar'у только `get/list/watch` на ConfigMap/Secret в конкретных неймспейсах. Избегайте `ClusterRole` в production, если возможно.
5.  **Назначение `isDefault`:** Только один источник данных должен иметь `isDefault: true` на один кластер.
6.  **Мониторинг самой Grafana:** Настройте ServiceMonitor для Grafana (метрики `grafana_*`) и алерты на `grafana_request_duration_seconds`, `grafana_dashboard_versions_total`.
7.  **Версионирование:** Используйте семантические версии в JSON-дашбордах (`"version": 1`) и отслеживайте изменения через Git.
8.  **Папки:** Используйте аннотацию `grafana_folder` вместо `k8s-sidecar-target-directory` для группировки (рекомендуется с v11+).

### Связанные темы

*   **[Провиженинг Grafana](../../../Grafana/grafana_provisioning.md)** — глубокая настройка через файлы.
*   **[Источники данных Grafana](../../../Grafana/grafana_datasources.md)** — параметры подключения к Prometheus/Mimir.
*   **[Grafana Alloy — Обзор](../../../Grafana/grafana_alloy_overview.md)** — возможности нового агента.
