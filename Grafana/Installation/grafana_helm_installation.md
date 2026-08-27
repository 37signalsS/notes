# Установка Grafana через Helm

## Определения

**Grafana** — платформа для аналитики и визуализации данных. См. [Обзор Grafana](../grafana_overview.md).

**Helm** — пакетный менеджер для Kubernetes, автоматизирующий жизненный цикл приложений через шаблонизированные чарты.

**Helm-чарт Grafana** — набор шаблонов Kubernetes-ресурсов (Deployment, Service, ConfigMap, Secret, Ingress, ServiceAccount, Role, RoleBinding), необходимых для развертывания Grafana.

**`values.yaml`** — файл параметров конфигурации Helm-чарта, позволяющий переопределять стандартные настройки установки.

**Sidecar (`k8s-sidecar`)** — вспомогательный контейнер (`grafana-sc-dashboards`, `grafana-sc-datasources`), работающий в том же Pod, что и Grafana. Он отслеживает ConfigMaps и Secrets с заданными метками и автоматически загружает их содержимое в Grafana без перезагрузки основного пода. См. [Провиженинг Grafana](../grafana_provisioning.md).

**Unified Alerting** — современная система оповещений Grafana (v8+, стандарт в 12.x), объединяющая алертинг по метрикам, логам и внешним источникам в едином интерфейсе и API.

> **Примечание:** Для установки Grafana в составе полного стека мониторинга рекомендуется использовать [kube-prometheus-stack](../../Prometheus/kubernetes/Kube_Prometheus_Stack_Helm/overview.md).

---

## Предварительные требования

### Версии ПО

| Компонент | Минимальная версия | Рекомендуемая версия (2026) | Примечание |
| :--- | :--- | :--- | :--- |
| **Kubernetes** | 1.25 | 1.28+ | Требуется для Gateway API и стабильной работы Ingress |
| **Helm** | 3.10 | 3.14+ | Поддержка OCI-репозиториев и `helm show values` с ревизиями |
| **Grafana OSS** | 11.x | 12.x / 13.x | LTS-версии получают обновления безопасности |

### Кластер и доступ

*   **Настроенный `kubectl`** с контекстом, указывающим на целевой кластер.
*   **Пространство имен** для изоляции (например, `monitoring`).
*   **StorageClass** для PersistentVolume (если требуется персистентность). Для HA-сценариев StorageClass должен поддерживать `accessModes: [ReadWriteMany]` (например, CephFS, NFS, Longhorn).
*   **Ingress-контроллер** (например, NGINX Ingress Controller или Traefik), если требуется внешний доступ.
*   **Внешняя база данных** (PostgreSQL 12+ или MySQL) — обязательна для режима HA (`replicas > 1`) и горизонтального масштабирования. SQLite не поддерживает конкурентный доступ `ReadWriteMany`.

### RBAC и права

Sidecar-контейнер требует прав на чтение ConfigMaps и Secrets в целевых неймспейсах. Helm-чарт по умолчанию создает ServiceAccount, Role и RoleBinding, но при использовании `searchNamespace: ALL` может потребоваться расширение прав или кластерная роль (ClusterRole).

---

## Основные концепции

### Миграция репозитория (2026)

С начала 2026 года официальные Open Source чарты Grafana Labs переехали в комьюнити-репозиторий. Оригинальный репозиторий `grafana/helm-charts` теперь ориентирован преимущественно на Enterprise-версии.

**Актуальные репозитории для OSS Grafana 12.x/13.x:**

```bash
# HTTP-репозиторий (классический)
helm repo add grafana-community https://grafana-community.github.io/helm-charts
helm repo update

# OCI-репозиторий (рекомендуется для CI/CD)
helm repo add grafana-community oci://ghcr.io/grafana-community/helm-charts
helm repo update
```

**Фиксация версии чарта (best practice):**

```bash
# Просмотр доступных версий
helm search repo grafana-community/grafana --versions

# Фиксация конкретной версии в values/команде
# --version 9.2.0 (пример; проверьте актуальную версию)
```

---

### Персистентность (Persistence)

Для сохранения данных (дашбордов, настроек, пользователей, сессий) требуется использование **PersistentVolumeClaim (PVC)**. По умолчанию Grafana использует SQLite.

**Важно:**
*   SQLite не поддерживает режим доступа `ReadWriteMany`, что ограничивает масштабирование Grafana до одного пода.
*   Для обеспечения высокой доступности (HA) и горизонтального масштабирования необходимо использовать внешнюю базу данных (PostgreSQL или MySQL).
*   PVC также используется для хранения кастомных плагинов и аватаров. В HA-режиме StorageClass должен поддерживать `ReadWriteMany` (RWX).

### Внешний доступ (Ingress)

Ресурс Ingress предоставляет доступ к веб-интерфейсу. При настройке Ingress критически важно синхронизировать параметр `root_url` в `grafana.ini` с фактическим DNS-именем для корректной работы ссылок в уведомлениях и экспорта отчетов.

**Рекомендации:**
*   Используйте `cert-manager` для автоматической выдачи и ротации TLS-сертификатов (Let's Encrypt).
*   Настройте `ingressClassName` в соответствии с используемым контроллером (nginx, traefik).
*   Включите `enable_gzip: true` для компрессии ответов.

### Автоматизация (Provisioning через Sidecar)

Helm-чарт включает sidecar-контейнер (`k8s-sidecar`), который сканирует ConfigMaps и Secrets в кластере на наличие меток (labels). При обнаружении ресурса с заданной меткой sidecar автоматически загружает его в Grafana без перезагрузки основного пода.

**Поддерживаемые типы ресурсов:**

| Тип ресурса | Метка (Label) | Путь монтирования |
| :--- | :--- | :--- |
| **Dashboards** | `grafana_dashboard: "1"` | `/tmp/dashboards` |
| **Datasources** | `grafana_datasource: "1"` | `/etc/grafana/provisioning/datasources` |
| **Alerts** | `grafana_alert: "1"` | `/etc/grafana/provisioning/alerting` |

**Особенности:**
*   Общий размер данных в ConfigMap не должен превышать **1 МБ**. Для больших дашбордов включите `sidecar.dashboards.GZIP: true`.
*   Параметр `sidecar.dashboards.searchNamespace: ALL` позволяет собирать дашборды со всего кластера. Требует соответствующих прав RBAC для ServiceAccount.
*   Используйте аннотацию `grafana_dashboard_folder` (или `grafana_folder` в зависимости от версии sidecar) для автоматического создания папок в UI.
*   Интервал сканирования настраивается через `sidecar.dashboards.watchInterval` (по умолчанию 30s).

### Высокая доступность (High Availability)

Увеличение количества реплик (`replicas > 1`) недостаточно для полноценного HA. Grafana требует централизованного хранилища состояния.

**Требования для HA:**
*   **Внешняя БД:** PostgreSQL версии 12+ или MySQL через параметры `grafana.database.*`. SQLite не поддерживает конкурентный доступ.
*   **Shared Storage:** Для кастомных плагинов и аватаров (через PVC с `accessModes: [ReadWriteMany]`).
*   **Session Management:** Настройка Redis или внешней базы данных для хранения сессий пользователей (`grafana.grafana.ini.sessions`).
*   **Sticky Sessions:** Рекомендуется на уровне Ingress для стабильной работы UI.

### Безопасность

*   **Secret Management:** Используйте `existingSecret` для всех чувствительных данных (пароли БД, токены OAuth, SMTP). Никогда не храните секреты в открытом виде в `values.yaml`.
*   **CSRF Protection:** Строгая проверка `cookie_samesite` в `grafana.ini` (значение `strict` для production).
*   **OAuth/OIDC:** Интеграция с Keycloak, Authentik или GitHub через секции `[auth.generic_oauth]` или `[auth.openid]`.

---

## Практические сценарии

### Сценарий 0: Миграция репозитория и фиксация версий

**Ситуация:** Вы обновляете существующий релиз или создаете новый, используя актуальный комьюнити-репозиторий.

```bash
# 1. Обновление репозитория
helm repo add grafana-community https://grafana-community.github.io/helm-charts
helm repo update
# → "grafana-community" already exists, will update

# 2. Проверка доступных версий
helm search repo grafana-community/grafana --versions
# → NAME                                    CHART VERSION   APP VERSION   DESCRIPTION
# → grafana-community/grafana                9.2.0           13.x          Grafana

# 3. Установка с фиксированной версией чарта
helm upgrade --install grafana grafana-community/grafana \
  --version 9.2.0 \
  --namespace monitoring \
  --create-namespace \
  -f values.yaml \
  --atomic
```

**Миграция с Enterprise-репозитория `grafana/helm-charts`:**

```bash
# Если используется старый репозиторий, удалите его
helm repo remove grafana

# Добавьте комьюнити-репозиторий (см. выше)
helm repo add grafana-community https://grafana-community.github.io/helm-charts
helm repo update

# Обновите релиз (значения values.yaml остаются совместимыми в большинстве случаев)
helm upgrade grafana grafana-community/grafana \
  --namespace monitoring \
  -f values.yaml \
  --atomic
```

---

### Сценарий 1: Быстрый старт (Standalone, < 5 минут)

**Цель:** Развернуть Grafana с базовой персистентностью, доступом через Ingress и автозагрузкой дашбордов. Подходит для Dev/Staging окружений.

**Шаг 1: Создание пространства имен**

```bash
kubectl create namespace monitoring
# → namespace/monitoring created
```

**Шаг 2: Подготовка `values.yaml`**

```yaml
# grafana-values.yaml
admin:
  existingSecret: "grafana-admin-secret" # Рекомендуется создавать отдельно
  adminUserKey: "username"
  adminPasswordKey: "password"

# Фиксация версии чарта для воспроизводимости
# В команде helm upgrade --install используйте --version X.Y.Z

persistence:
  enabled: true
  type: pvc
  size: 10Gi
  storageClassName: standard # Укажите ваш StorageClass

ingress:
  enabled: true
  ingressClassName: nginx
  annotations:
    cert-manager.io/cluster-issuer: letsencrypt-prod # Если используется cert-manager
  hosts:
    - grafana.example.com
  tls:
    - secretName: grafana-tls
      hosts:
        - grafana.example.com

grafana.ini:
  server:
    domain: grafana.example.com
    root_url: "https://%(domain)s/"
    enable_gzip: true
  security:
    cookie_samesite: "strict" # Защита от CSRF

sidecar:
  dashboards:
    enabled: true
    label: grafana_dashboard
    labelValue: "1"
    searchNamespace: ALL # Сканировать все неймспейсы; требует RBAC
    folderAnnotation: "grafana_folder"
    watchInterval: 30s
  datasources:
    enabled: true
    label: grafana_datasource
    labelValue: "1"
    searchNamespace: ALL
```

**Шаг 3: Создание секрета для учетных данных администратора**

```bash
kubectl create secret generic grafana-admin-secret \
  --namespace monitoring \
  --from-literal=username=admin \
  --from-literal=password='<STRONG_PASSWORD>'
# → secret/grafana-admin-secret created
```

**Шаг 4: Установка Helm-релиза**

```bash
helm upgrade --install grafana grafana-community/grafana \
  -f grafana-values.yaml \
  --namespace monitoring \
  --create-namespace \
  --atomic \
  --timeout 5m
# → Release "grafana" has been upgraded. 1 pod(s) are ready
```

**Шаг 5: Валидация установки**

```bash
# Проверка подов и контейнеров (основной и sidecar)
kubectl get pods -n monitoring -l app.kubernetes.io/name=grafana
# → NAME                         READY   STATUS    RESTARTS   AGE
# → grafana-XXXX-xxxxx           2/2     Running   0          1m

# Проверка PVC
kubectl get pvc -n monitoring
# → NAME                 STATUS   VOLUME                                     CAPACITY   ACCESS MODES   STORAGECLASS
# → data-grafana-xxxxx   Bound    pvc-xxxxx-xxxxx-xxxxx                      10Gi       RWO            standard

# Проверка Ingress
kubectl get ingress -n monitoring
# → NAME        CLASS   HOSTS                 ADDRESS   PORTS   AGE
# → grafana     nginx   grafana.example.com             80, 443 1m

# Просмотр логов sidecar (критично при ошибках загрузки дашбордов)
kubectl logs -n monitoring -l app.kubernetes.io/name=grafana -c grafana-sc-dashboards
# → 2026/08/24 17:00:00 {"dashboard":"default/my-app-dashboard","namespace":"monitoring","message":"Added dashboard from ConfigMap"}

# Просмотр логов основного контейнера
kubectl logs -n monitoring -l app.kubernetes.io/name=grafana -c grafana
# → t=2026-08-24T17:00:00+0000 lvl=info msg="Starting Grafana" version=13.0.0
```

---

### Сценарий 2: Базовая установка с Ingress и PVC

Конфигурация для небольших или тестовых окружений. Включает RBAC для sidecar и GZIP-сжатие.

```yaml
# grafana-values.yaml
admin:
  existingSecret: "grafana-admin-secret"
  adminUserKey: "username"
  adminPasswordKey: "password"

persistence:
  enabled: true
  type: pvc
  size: 10Gi
  storageClassName: standard

ingress:
  enabled: true
  ingressClassName: nginx
  annotations:
    cert-manager.io/cluster-issuer: letsencrypt-prod
  hosts:
    - grafana.example.com
  tls:
    - secretName: grafana-tls
      hosts:
        - grafana.example.com

grafana.ini:
  server:
    domain: grafana.example.com
    root_url: "https://%(domain)s/"
    enable_gzip: true
  security:
    cookie_samesite: "strict"

# RBAC для sidecar (если ServiceAccount по умолчанию не имеет прав)
rbac:
  namespaced: true # Создавать Role/ RoleBinding в каждом неймспейсе
  extraRoleRules:
    - apiGroups: [""]
      resources: ["configmaps", "secrets"]
      verbs: ["get", "list", "watch"]

sidecar:
  dashboards:
    enabled: true
    label: grafana_dashboard
    labelValue: "1"
    searchNamespace: ALL
    folderAnnotation: "grafana_folder"
    GZIP: true # Сжатие больших дашбордов (>1MB)
    watchInterval: 30s
  datasources:
    enabled: true
    label: grafana_datasource
    labelValue: "1"
    searchNamespace: ALL
```

**Установка:**

```bash
helm upgrade --install grafana grafana-community/grafana \
  -f grafana-values.yaml \
  --namespace monitoring \
  --create-namespace \
  --atomic
```

---

### Сценарий 3: Production-конфигурация (HA, SMTP, внешняя БД, OIDC)

Рекомендуется для стабильной работы и масштабирования. Включает управление секретами через `helm-secrets` / `sops`, внешнюю PostgreSQL, OIDC-аутентификацию и Session Management.

**Предварительная подготовка секретов:**

```bash
# Создание секрета для внешней PostgreSQL
kubectl create secret generic grafana-db-secret \
  --namespace monitoring \
  --from-literal=user=grafana \
  --from-literal=password='<DB_PASSWORD>'

# Создание секрета для SMTP (если используется)
kubectl create secret generic grafana-smtp-secret \
  --namespace monitoring \
  --from-literal=password='<SMTP_PASSWORD>'
```

**Конфигурация (`production-values.yaml`):**

```yaml
replicas: 3

# Учетные данные администратора через Secret
admin:
  existingSecret: "grafana-admin-secret"
  adminUserKey: "username"
  adminPasswordKey: "password"

# Использование внешней PostgreSQL для обеспечения HA
database:
  type: postgres
  host: postgres-service.db-namespace.svc.cluster.local:5432
  name: grafana
  user: grafana
  existingSecret: "grafana-db-secret"
  userKey: "user"
  passwordKey: "password"

# Передача переменных окружения из секрета
envFromSecret: "grafana-smtp-secret"

# Настройка SMTP для уведомлений
grafana.ini:
  smtp:
    enabled: true
    host: "smtp.sendgrid.net:587"
    user: "apikey"
    password: "${SMTP_PASSWORD}" # Переменная из envFromSecret
    from_address: "grafana@example.com"
    starttls_policy: MandatoryStartTLS
  server:
    root_url: "https://grafana.example.com/"
  security:
    cookie_samesite: "strict"
    admin_only_org_create: true
  unified_alerting:
    enabled: true
    execute_alerts: true
  sessions:
    # Session management через внешний Redis (рекомендуется для HA)
    # database_type: redis
    # database_url: "redis://redis-service.db-namespace:6379"

# OIDC-аутентификация (Keycloak / Authentik / GitHub)
auth:
  generic_oauth:
    enabled: true
    name: "Keycloak"
    client_id: "${OAUTH_CLIENT_ID}"
    client_secret: "${OAUTH_CLIENT_SECRET}"
    scopes: "openid profile email roles"
    auth_url: "https://auth.example.com/realms/master/protocol/openid-connect/auth"
    token_url: "https://auth.example.com/realms/master/protocol/openid-connect/token"
    api_url: "https://auth.example.com/realms/master/protocol/openid-connect/userinfo"
    role_attribute_path: "contains(roles[*], 'admin') && 'Admin' || contains(roles[*], 'editor') && 'Editor' || 'Viewer'"
    allow_sign_up: false

# Настройки безопасности пода
podSecurityContext:
  runAsUser: 472
  runAsGroup: 472
  fsGroup: 472
  fsGroupChangePolicy: "OnRootMismatch" # (v1.23+) Стабильность прав на volume

containerSecurityContext:
  allowPrivilegeEscalation: false
  readOnlyRootFilesystem: true
  capabilities:
    drop:
      - ALL

resources:
  limits:
    cpu: 1000m
    memory: 2Gi
  requests:
    cpu: 500m
    memory: 1Gi

# PersistentVolume для плагинов и аватаров (требует RWX для HA)
persistence:
  enabled: true
  type: pvc
  size: 5Gi
  storageClassName: ceph-fs # Должен поддерживать ReadWriteMany
  accessModes:
    - ReadWriteMany

# Sidecar с расширенными правами
sidecar:
  dashboards:
    enabled: true
    label: grafana_dashboard
    labelValue: "1"
    searchNamespace: ALL
    folderAnnotation: "grafana_folder"
    GZIP: true
    watchInterval: 15s
  datasources:
    enabled: true
    label: grafana_datasource
    labelValue: "1"
    searchNamespace: ALL

# ServiceMonitor для Prometheus Operator
serviceMonitor:
  enabled: true
  namespace: monitoring
  interval: 30s
  labels:
    release: kube-prometheus-stack

# Горизонтальное масштабирование (HPA)
autoscaling:
  enabled: true
  minReplicas: 2
  maxReplicas: 5
  targetCPUUtilizationPercentage: 70
  targetMemoryUtilizationPercentage: 80
```

**Установка:**

```bash
helm upgrade --install grafana grafana-community/grafana \
  -f production-values.yaml \
  --namespace monitoring \
  --create-namespace \
  --atomic \
  --timeout 10m
```

**Валидация HA:**

```bash
# Проверка количества реплик
kubectl get deployment grafana -n monitoring
# → NAME      READY   UP-TO-DATE   AVAILABLE   AGE
# → grafana   3/3     3            3           2m

# Проверка подов в разных зонах (при наличии topologySpreadConstraints)
kubectl get pods -n monitoring -l app.kubernetes.io/name=grafana -o wide
# → grafana-xxx-xxxxx   3/3     Running   0          2m   10.0.0.1   node-1   <none>   <none>
# → grafana-xxx-xxxxx   3/3     Running   0          2m   10.0.1.2   node-2   <none>   <none>
# → grafana-xxx-xxxxx   3/3     Running   0          2m   10.0.2.3   node-3   <none>   <none>
```

---

### Сценарий 4: Миграция с grafana/helm-charts на grafana-community

Если вы используете старый репозиторий `grafana/helm-charts` (ориентированный на Enterprise), выполните миграцию на OSS-чарты:

```bash
# 1. Добавление нового репозитория (приоритет выше старого)
helm repo add grafana-community https://grafana-community.github.io/helm-charts
helm repo update

# 2. Проверка совместимости values.yaml
helm show values grafana-community/grafana > new-values.yaml
# Сравните параметры; большинство ключей совместимы.

# 3. Установка/обновление релиза
helm upgrade --install grafana grafana-community/grafana \
  --namespace monitoring \
  -f values.yaml \
  --atomic

# 4. Удаление старого репозитория (опционально)
helm repo remove grafana
```

**Важно:** В версиях Grafana 13.x некоторые параметры `grafana.ini` могут отличаться. Проверьте [официальную документацию](https://grafana.com/docs/grafana/latest/setup-grafana/configure-grafana/) на предмет изменений в конфигурации.

---

### Сценарий 5: Самомониторинг и масштабирование

Настройка автоматического сбора метрик самой Grafana и горизонтального масштабирования.

```yaml
# monitoring-values.yaml

# Включение ServiceMonitor для Prometheus Operator
serviceMonitor:
  enabled: true
  namespace: monitoring
  interval: 30s
  labels:
    release: kube-prometheus-stack

# Горизонтальное масштабирование по CPU и Memory
autoscaling:
  enabled: true
  minReplicas: 2
  maxReplicas: 5
  targetCPUUtilizationPercentage: 70
  targetMemoryUtilizationPercentage: 80

# Интеграция с External Secrets (использование существующего секрета)
envFromSecret: "grafana-external-secrets"

# Дополнительные метрики для мониторинга самой Grafana
 grafana.ini:
   metrics:
     enabled: true
     basic_auth_username: "metrics_user"
     basic_auth_password: "${METRICS_PASSWORD}"
```

**Валидация метрик:**

```bash
# Проверка эндпоинта /metrics (если включено)
kubectl port-forward svc/grafana -n monitoring 3000:80
curl -u metrics_user:<password> http://localhost:3000/metrics
# → grafana_dashboard_versions_total{version="1"} 42
```

---

### Сценарий 6: Управление жизненным циклом

**Установка или обновление:**

```bash
# --install создает релиз, если его нет
# --atomic откатывает изменения при неудаче
# --wait ждет готовности всех ресурсов
# --timeout задает лимит ожидания
helm upgrade --install grafana grafana-community/grafana \
  -f values.yaml \
  --namespace monitoring \
  --create-namespace \
  --atomic \
  --wait \
  --timeout 5m
```

**Проверка состояния:**

```bash
# Проверка подов и контейнеров (основной и sidecar)
kubectl get pods -n monitoring -l app.kubernetes.io/name=grafana
# → NAME                         READY   STATUS    RESTARTS   AGE
# → grafana-XXXX-xxxxx           2/2     Running   0          5m

# Просмотр логов процесса загрузки дашбордов
kubectl logs -n monitoring -l app.kubernetes.io/name=grafana -c grafana-sc-dashboards
# → 2026/08/24 17:00:00 {"dashboard":"default/node-exporter","namespace":"monitoring","message":"Added dashboard from ConfigMap"}

# Просмотр событий Deployment
kubectl describe deployment grafana -n monitoring
```

**Получение пароля администратора:**

```bash
# Если пароль задан через existingSecret
kubectl get secret grafana-admin-secret -n monitoring \
  -o jsonpath='{.data.password}' | base64 -d; echo

# Если пароль не задан явно и используется автогенерация
kubectl get secret --namespace monitoring grafana \
  -o jsonpath="{.data.admin-password}" | base64 --decode ; echo
```

**Просмотр истории релизов:**

```bash
helm history grafana --namespace monitoring
# → REVISION    UPDATED                     STATUS          CHART                   APP VERSION   DESCRIPTION
# → 1           Mon Aug 24 17:00:00 2026    superseded      grafana-9.2.0          13.x           Install complete
# → 2           Mon Aug 24 17:05:00 2026    deployed        grafana-9.2.0          13.x           Upgrade complete
```

**Очистка (удаление релиза):**

```bash
# Полное удаление релиза и всех ресурсов
helm uninstall grafana --namespace monitoring
# → release "grafana" uninstalled

# С сохранением History (для возможного отката)
helm uninstall grafana --namespace monitoring --keep-history

# Удаление PVC (если не требуется сохранение данных)
kubectl delete pvc -n monitoring -l app.kubernetes.io/name=grafana
```

---

## Best Practices

1.  **Фиксация версий:** Всегда указывайте `--version` для Helm-чарта и фиксируйте версии образов Grafana в `values.yaml` (или используйте digest).
2.  **Secret Management:** Храните пароли, токены и ключи в Kubernetes Secrets или внешних системах (HashiCorp Vault, AWS Secrets Manager). Для управления секретами в Git используйте `sops` или `helm-secrets`. Никогда не коммитьте `values.yaml` с открытыми секретами.
3.  **RBAC:** Минимизируйте права ServiceAccount sidecar. Используйте `searchNamespace: ALL` только при необходимости и предварительно проверяйте политики безопасности кластера.
4.  **Ресурсы:** Всегда задавайте `requests` и `limits` для пода Grafana. Для production начинайте с `requests.memory: 256Mi` и корректируйте по метрикам использования.
5.  **HA-готовность:** Используйте внешнюю БД и RWX-хранилище. Тестируйте отказ одного пода перед запуском в production.
6.  **TLS:** Включайте TLS на уровне Ingress и используйте `cert-manager` для автоматической ротации.
7.  **Provisioning:** Все провиженинговые файлы (дашборды, датасорсы) храните в Git. Используйте `editable: false` для автоматически созданных источников данных, чтобы предотвратить Configuration Drift.
8.  **Обновления:** Тестируйте обновление Grafana в staging-окружении перед применением в production. Используйте `helm upgrade --dry-run --debug` для проверки манифестов.

---

**Связанные темы:**
- [Безопасность и жёсткая настройка](../grafana_security_hardening.md) — hardening Grafana (TLS, cookie, секреты) при деплое через Helm

## Дополнительная информация

### Устранение неполадок

| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| **PVC не переходит в Bound** | Неверный `storageClassName` или отсутствие ресурсов | Проверьте описание PVC: `kubectl describe pvc`; убедитесь, что StorageClass существует и доступна |
| **CrashLoopBackOff основного контейнера** | Ошибка в `grafana.ini` или правах на volume | Проверьте логи: `kubectl logs <pod> -c grafana`; проверьте SecurityContext и права на PVC |
| **CrashLoopBackOff sidecar** | Неверные метки на ConfigMap/Secret или превышен лимит размера 1 МБ | Проверьте логи: `kubectl logs <pod> -c grafana-sc-dashboards`; проверьте метки и размер ConfigMap |
| **Дашборды не импортируются** | Отсутствует метка на ConfigMap или неверный JSON | Проверьте наличие label `grafana_dashboard: "1"` (или значения из `sidecar.label`/`sidecar.labelValue`); валидируйте JSON-схему |
| **ServiceMonitor не собирает метрики** | Несоответствие селекторов меток | Убедитесь, что метки в `serviceMonitor.labels` совпадают с ожидаемыми в Prometheus Operator |
| **Графана недоступна через Ingress** | Неверный `root_url` или проблемы с TLS | Проверьте `grafana.ini.server.root_url` и статус сертификата: `kubectl describe certificate` |
| **OOMKilled** | Недостаточно памяти для загрузки больших дашбордов | Увеличьте `resources.limits.memory`; включите `sidecar.dashboards.GZIP: true` |
| **RBAC Error (sidecar)** | ServiceAccount не имеет прав на чтение ConfigMaps в неймспейсах | Расширьте Role или используйте ClusterRole с правильным селектором неймспейсов |

### Edge Cases и технические нюансы

1.  **Лимит размера ConfigMap (1 МБ):** Kubernetes ограничивает размер ConfigMap 1 МБ. Если дашборды не загружаются, включите `sidecar.dashboards.GZIP: true` или разбейте дашборды на несколько ConfigMap.
2.  **ReadWriteMany (RWX):** Требуется для HA-режима (совместный доступ к плагинам и аватарам). Убедитесь, что ваш StorageClass поддерживает RWX. Если нет, используйте внешнее хранилище (NFS, CephFS, Longhorn).
3.  **Concurrent Provisioning:** Grafana обрабатывает файлы провиженинга параллельно. Для ресурсов одного типа (например, два файла `datasources.yaml`) порядок применения зависит от алфавитного порядка имен файлов.
4.  **Configuration Drift:** Изменения, сделанные через UI, не сохраняются обратно в конфигурационные файлы. После перезапуска Grafana вернет состояние, описанное в провиженинговых файлах. Используйте `editable: false` для источников данных, чтобы исключить конфликты.
5.  **Downgrade:** Grafana 13.x не поддерживает downgrade до 11.x без потери данных (изменения схемы БД). Всегда тестируйте обновления.
6.  **Sidecar и namespaces:** При `searchNamespace: ALL` sidecar сканирует все неймспейсы, кроме системных (`kube-system`, `kube-public`). Для кастомного списка используйте `sidecar.dashboards.namespaces: ["monitoring", "app"]`.
7.  **Helm-секреты (sops):** Для интеграции с `sops` используйте плагин `helm-secrets`. Пример команды: `sops -d values.yaml.sops | helm upgrade grafana grafana-community/grafana -f -`.

### Полезные команды Helm

```bash
# Вывод всех доступных параметров чарта (с фиксацией версии)
helm show values grafana-community/grafana --version 9.2.0

# Просмотр значений, установленных в релизе
helm get values grafana --namespace monitoring

# Отладка манифестов без применения (Dry Run)
helm install test grafana-community/grafana -f values.yaml --dry-run --debug

# Валидация синтаксиса values.yaml
helm lint grafana-community/grafana -f values.yaml

# Откат на предыдущую ревизию
helm rollback grafana 1 --namespace monitoring
```

**См. также:**

- [Провиженинг Grafana](../grafana_provisioning.md) — детальное описание работы sidecar.
- [Высокая доступность Grafana](../high_availability.md) — архитектурные нюансы масштабирования.
- [Конфигурация Grafana в kube-prometheus-stack](../../Prometheus/kubernetes/Kube_Prometheus_Stack_Helm/grafana_config.md) — специфика встроенной Grafana.
- [Управление плагинами](../grafana_plugins.md) — установка и обновление расширений.
