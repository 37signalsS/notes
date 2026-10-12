# Argo CD: Методы отслеживания ресурсов (Resource Tracking)

**Актуально для:** Argo CD v3.5+ (покрывает v3.4.x, v3.5.x, v3.6.x; методы: annotation, annotation+label, label; bare-metal / on-premise)

## Предварительные требования

1. **Развернутый кластер Kubernetes** (v1.28–v1.32+) под управлением kubelet/containerd на bare-metal или виртуальных машинах.
2. **Установленный Argo CD** (см. [Установка и настройка](./argocd_installation_and_setup.md)).
3. **Утилиты управления:** `kubectl` с правами администратора кластера (`cluster-admin`), `argocd` CLI и `jq`.
4. **Базовое понимание GitOps-механизмов:** [Synchronization](./synchronization.md), [AppProject](./argocd_appproject_deep.md), [Удаление и очистка ресурсов](./argocd_deletion_and_cleanup.md).

## Определения

**Resource Tracking (Отслеживание ресурсов)** — системный механизм контроллера `argocd-application-controller`, с помощью которого Argo CD идентифицирует принадлежность объектов в Kubernetes конкретному манифесту `Application`. Механизм управляет обнаружением расхождений (diff), автоматическим удалением устаревших объектов (prune), каскадным удалением и изоляцией управления.

**Tracking ID (`argocd.argoproj.io/tracking-id`)** — структурированная строка идентификатора в Kubernetes-аннотации ресурса, фиксирующая метаданные владельца в формате:
`<app-name>:<group>/<kind>:<namespace>/<name>`.

**Instance Label (`app.kubernetes.io/instance`)** — стандартная Kubernetes-метка, внедряемая в управляемые ресурсы при использовании методов `label` или `annotation+label`. Имя ключа может быть переопределено параметром `application.instanceLabelKey` в `argocd-cm`.

**Installation ID (`installationID`)** — уникальный идентификатор конкретного экземпляра Argo CD, проставляемый в аннотацию `argocd.argoproj.io/installation-id`. Позволяет запускать несколько независимых контроллеров Argo CD в одном физическом кластере без конфликтов владения ресурсами.

**Self-Referencing Annotation (Самоссылающаяся аннотация)** — проверка соответствия, при которой контроллер сверяет группу, вид, пространство имен и имя текущего объекта с данными, зашитыми в значении аннотации `argocd.argoproj.io/tracking-id`. Если свойства объекта не совпадают со значением аннотации (например, объект скопирован внешним оператором в другой namespace), аннотация признается non-self-referencing.

**Orphaning (Осиротение ресурсов)** — состояние, при котором объект Kubernetes сохраняется в кластере после удаления управляющего им `Application` (при флаге `--cascade=false`) либо теряет привязку к манифестам в Git и не удаляется сборщиком мусора из-за отключенного флага `prune`.

## Архитектура и принцип работы

### Внутренний жизненный цикл отслеживания

```text
┌────────────────────────────────────────────────────────────────────────┐
│                        GitOps Reconciliation Loop                      │
└────────────────────────────────────────────────────────────────────────┘
                                   │
                                   ▼
 ┌──────────────────────┐                     ┌────────────────────────┐
 │   argocd-repo-server │                     │  Kubernetes API Server │
 │  (Target Manifests)  │                     │   (Live State Cache)   │
 └──────────────────────┘                     └────────────────────────┘
            │                                              │
            │ Desired State                                │ Live Objects
            │                                              │ (Informer Cache)
            ▼                                              ▼
┌────────────────────────────────────────────────────────────────────────┐
│                     argocd-application-controller                      │
│                                                                        │
│ 1. Фильтрация объектов по Tracking Metadata                            │
│    ├─ annotation       → argocd.argoproj.io/tracking-id                │
│    ├─ annotation+label → argocd.argoproj.io/tracking-id + instance     │
│    └─ label            → app.kubernetes.io/instance                    │
│                                                                        │
│ 2. Проверка валидности (Self-Referencing Check)                        │
│    Совпадает ли <group>/<kind>:<namespace>/<name> с реальным объектом? │
│    ├─ Да  → Объект принадлежит Application, участвует в Diff/Sync      │
│    └─ Нет → Non-self-referencing: игнорируется, не удаляется в Prune   │
│                                                                        │
│ 3. Сравнение (Diff Engine)                                             │
│    ├─ Объект есть в Git и в Live State     → Проверка OutOfSync / Diff │
│    ├─ Объект есть в Git, нет в Live State   → Создание (Sync)           │
│    └─ Объект есть в Live State, нет в Git   → Пометка RequiresPruning   │
└────────────────────────────────────────────────────────────────────────┘
```

Контроллер Argo CD не выполняет медленный последовательный опрос каждого ресурса через прямые HTTP-запросы. Вместо этого он поддерживает локальный in-memory кэш состояния кластера через Kubernetes SharedInformers. При обработке `Application` контроллер сопоставляет кэшированные объекты с манифестами, сгенерированными `argocd-repo-server`.

### Сравнение методов отслеживания

В Argo CD метод отслеживания задается глобально в ConfigMap `argocd-cm` параметром `application.resourceTrackingMethod`:

| Параметр | Метод `annotation` (Default) | Метод `annotation+label` | Метод `label` (Legacy) |
| :--- | :--- | :--- | :--- |
| **Ключ идентификации** | `argocd.argoproj.io/tracking-id` | `argocd.argoproj.io/tracking-id` | `app.kubernetes.io/instance` (или `application.instanceLabelKey`) |
| **Формат значения** | `<app>:<group>/<kind>:<ns>/<name>` | `<app>:<group>/<kind>:<ns>/<name>` (в аннотации) + `<app>` (в метке) | `<app>` (обрезается до 63 символов по RFC 1123) |
| **Роль метки `instance`** | Не устанавливается | Только информационная (для внешних инструментов) | Основной идентификатор владения |
| **Лимит длины** | 256 КБ (лимит аннотаций K8s) | Аннотация 256 КБ; метка усекается до 63 символов | Жесткий лимит 63 символа |
| **Конфликты с Helm** | Исключены | Исключены (метка не используется для reconciler) | **Высокий риск**: Helm чарты перезаписывают `app.kubernetes.io/instance` |
| **Защита от копирования (Self-referencing)** | Встроена (проверяется точный GVK/NS/Name) | Встроена | Отсутствует (любой скопированный объект с меткой считается своим) |
| **Совместимость с kube-state-metrics** | Требует парсинга аннотаций или custom metrics | Полная (доступны стандартные метки `app.kubernetes.io/instance`) | Полная |
| **Рекомендация для SRE** | **Стандарт для Production** | **Стандарт при интеграции с Prometheus / Grafana** | Не рекомендуется (только для устаревших систем) |

### Детали формата Tracking ID

Значение аннотации формируется детерминированно:

```text
<application-name>:<api-group>/<Kind>:<namespace>/<resource-name>
```

Правила формирования компонентов:
- **Core API Group (`""`):** Для базовых ресурсов ядра Kubernetes (таких как `ConfigMap`, `Secret`, `Service`, `PersistentVolumeClaim`) имя группы пустое:
  `my-app:/ConfigMap:production/app-config`
  `my-app:/Service:production/web-service`
- **Именованные группы:** Для ресурсов с явной API Group:
  `my-app:apps/Deployment:production/web-server`
  `my-app:networking.k8s.io/Ingress:production/main-ingress`
- **Cluster-scoped ресурсы:** Для ресурсов без пространства имен (`ClusterRole`, `ClusterRoleBinding`, `Namespace`, `StorageClass`, `CustomResourceDefinition`) поле `<namespace>` остается пустым:
  `my-app:rbac.authorization.k8s.io/ClusterRole:/cluster-viewer`
  `my-app:/Namespace:/production`

### Механизм Non-Self-Referencing Annotations

В инфраструктурах с высокой степенью автоматизации сторонние утилиты (например, Hierarchical Namespace Controller — HNC, контроллеры синхронизации секретов, операторы репликации ConfigMap или системы резервного копирования) часто дублируют объекты из одного пространства имен в другое вместе со всеми метаданными.

1. **В режиме `label`:** Если HNC скопировал `Secret` с меткой `app.kubernetes.io/instance: my-app` из пространства имен `team-a` в `team-b`, контроллер Argo CD обнаружит в `team-b` объект с меткой приложения. Так как в Git-манифестах приложения `my-app` секрета для `team-b` нет, Argo CD сочтет его устаревшим и удалит (`prune`), сломав работу потребителя в целевом неймспейсе.
2. **В режимах `annotation` и `annotation+label`:** Контроллер считывает `argocd.argoproj.io/tracking-id`. Значение содержит исходный namespace: `my-app:/Secret:team-a/app-secret`. Контроллер проверяет фактическое размещение объекта (`team-b`). Несоответствие (`team-a != team-b`) классифицирует аннотацию как non-self-referencing:
   - Объект полностью игнорируется в циклах diff.
   - Объект не отображается в дереве синхронизации приложения.
   - Объект **не подвергается автоматическому удалению (`prune`)**.

### Изоляция нескольких инстансов через Installation ID

Когда в одном кластере развернуто несколько независимых инсталляций Argo CD (например, системный Argo CD для Core-компонентов и отдельные клиентские инсталляции для продуктовых команд), совпадение имен приложений приведет к конфликту управления ресурсами.

Параметр `installationID` в ConfigMap `argocd-cm`:
```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: argocd-cm
  namespace: argocd
data:
  installationID: "cluster-infra-prod"
```

При его активации Argo CD добавляет ко всем управляемым ресурсам аннотацию:
`argocd.argoproj.io/installation-id: cluster-infra-prod`

В процессе reconciliation контроллер фильтрует ресурсы кластера, принимая во внимание только те объекты, чья аннотация `installation-id` в точности соответствует собственному идентификатору экземпляра. Объекты с другим `installation-id` не затрагиваются, предотвращая коллизии владения и случайный взаимный prune.

## Практические сценарии и конфигурация

### Сценарий 1: Базовая настройка режима `annotation` (Default)

Рекомендуемый стандарт для подавляющего большинства on-premise сред Kubernetes. Полностью устраняет конфликты с чартами Helm.

**1. Конфигурация `argocd-cm`:**

```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: argocd-cm
  namespace: argocd
  labels:
    app.kubernetes.io/name: argocd-cm
    app.kubernetes.io/part-of: argocd
data:
  application.resourceTrackingMethod: "annotation"
```

Применение конфигурации:
```bash
kubectl apply -n argocd -f - <<EOF
apiVersion: v1
kind: ConfigMap
metadata:
  name: argocd-cm
  namespace: argocd
data:
  application.resourceTrackingMethod: "annotation"
EOF
# → configmap/argocd-cm configured
```

**2. Перезапуск или hot-reload контроллера:**
`argocd-application-controller` отслеживает изменения `argocd-cm` через informer и применяет новый метод динамически без перезапуска подов.

**3. Проверка метаданных на ресурсе кластера:**

```bash
# Проверка наличия tracking-id аннотации на Deployment
kubectl get deployment backend-api -n production -o jsonpath='{.metadata.annotations.argocd\.argoproj\.io/tracking-id}'
# → backend-api:apps/Deployment:production/backend-api

# Проверка отсутствия управляющей метки instance
kubectl get deployment backend-api -n production -o jsonpath='{.metadata.labels.app\.kubernetes\.io/instance}'
# → (пусто или содержит имя релиза Helm без вмешательства Argo CD)
```

---

### Сценарий 2: Режим `annotation+label` для мониторинга в Prometheus

Сценарий необходим, если в инфраструктуре используются дашборды Grafana или алерты Alertmanager, опирающиеся на сквозную метку `app.kubernetes.io/instance` из метрик `kube-state-metrics` (`kube_pod_labels`, `kube_deployment_labels`).

**1. Настройка ConfigMap:**

```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: argocd-cm
  namespace: argocd
data:
  application.resourceTrackingMethod: "annotation+label"
  # Опционально: переопределение ключа метки при конфликтах
  # application.instanceLabelKey: "argocd.argoproj.io/instance"
```

**2. Применение и синхронизация приложения:**

```bash
kubectl apply -n argocd -f - <<EOF
apiVersion: v1
kind: ConfigMap
metadata:
  name: argocd-cm
  namespace: argocd
data:
  application.resourceTrackingMethod: "annotation+label"
EOF
# → configmap/argocd-cm configured

# Инициирование жесткого обновления и синхронизации
argocd app get payment-service --hard-refresh
# → Application payment-service refreshed successfully

argocd app sync payment-service
# → TIMESTAMP GROUP KIND STATUS HEALTH NAME
# → 2026-10-12T15:10:00Z apps Deployment Synced Healthy payment-service
```

**3. Валидация одновременного наличия аннотации и метки:**

```bash
kubectl get deployment payment-service -n production -o jsonpath='{range .metadata}{"Annotation: "}{.annotations.argocd\.argoproj\.io/tracking-id}{"\nLabel: "}{.labels.app\.kubernetes\.io/instance}{"\n"}{end}'
# → Annotation: payment-service:apps/Deployment:production/payment-service
# → Label: payment-service
```

В этом режиме контроллер Argo CD принимает решения о diff и prune исключительно по аннотации `tracking-id`. Метка `payment-service` экспортируется в `kube-state-metrics`, позволяя выполнять PromQL-запросы вида:

```promql
sum by (app_kubernetes_io_instance) (
  rate(container_cpu_usage_seconds_total{namespace="production"}[5m])
  * on (namespace, pod) group_left(app_kubernetes_io_instance)
  kube_pod_labels{app_kubernetes_io_instance="payment-service"}
)
```

---

### Сценарий 3: Разрешение конфликтов с Helm чартами

Большинство официальных чартов Helm (Bitnami, Prometheus Community, Ingress-NGINX) генерируют стандартные селекторы Pod:

```yaml
spec:
  selector:
    matchLabels:
      app.kubernetes.io/name: {{ include "common.names.name" . }}
      app.kubernetes.io/instance: {{ .Release.Name }}
```

**Проблема в режиме `label`:**
1. Если имя `Application` в Argo CD (`my-redis-app`) не совпадает с `releaseName` в манифесте Helm (`redis-prod`), Argo CD перезаписывает метку `app.kubernetes.io/instance` на `my-redis-app`.
2. Так как селекторы в `spec.selector.matchLabels` у объекта `Deployment` являются неизменяемыми (immutable), Kubernetes API возвращает ошибку `Invalid: spec.template.metadata.labels: Invalid value: field is immutable`.
3. Приложение входит в вечный статус `SyncFailed` / `OutOfSync`.

**Решение:**
Переход на `application.resourceTrackingMethod: annotation` полностью освобождает метку `app.kubernetes.io/instance` от вмешательства Argo CD:

```yaml
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: my-redis-app
  namespace: argocd
spec:
  project: default
  source:
    repoURL: https://charts.bitnami.com/bitnami
    chart: redis
    targetRevision: 19.x.x
    helm:
      releaseName: redis-prod
  destination:
    server: https://kubernetes.default.svc
    namespace: database
  syncPolicy:
    automated:
      prune: true
      selfHeal: true
```

Argo CD запишет:
- `annotations["argocd.argoproj.io/tracking-id"] = "my-redis-app:/Service:database/redis-prod-master"`
- `labels["app.kubernetes.io/instance"] = "redis-prod"` (оставлено Helm без искажения).

---

### Сценарий 4: Безопасная поэтапная миграция методов в Production

Смена глобального метода отслеживания на работающем production-кластере несет риск непреднамеренного удаления ресурсов при включенном `automated.prune: true`. Ниже приведена проверенная SRE-процедура миграции с `label` на `annotation` без даунтайма.

```text
┌────────────────────────────────────────────────────────────────────────┐
│                        План миграции (SRE Checklist)                   │
├────────────────────────────────────────────────────────────────────────┤
│ 1. Временное отключение automated.prune на критичных приложениях       │
│ 2. Обновление параметра в ConfigMap argocd-cm                          │
│ 3. Пакетный Hard-Refresh всех Application                              │
│ 4. Контролируемая синхронизация (наложение новых аннотаций)            │
│ 5. Валидация live-состояния ресурсов                                  │
│ 6. Повторное включение automated.prune                                 │
└────────────────────────────────────────────────────────────────────────┘
```

**Шаг 1: Скрипт временной блокировки auto-prune:**

```bash
# Получение списка приложений с активным auto-prune
APPS_WITH_PRUNE=$(kubectl get applications.argoproj.io -n argocd -o json | jq -r '.items[] | select(.spec.syncPolicy.automated.prune == true) | .metadata.name')

# Временное отключение prune
for app in $APPS_WITH_PRUNE; do
  kubectl patch application "$app" -n argocd --type=merge -p '{"spec":{"syncPolicy":{"automated":{"prune":false}}}}'
done
# → application.argoproj.io/backend-api patched
# → application.argoproj.io/frontend-web patched
```

**Шаг 2: Переключение метода в `argocd-cm`:**

```bash
kubectl patch configmap argocd-cm -n argocd --type=merge -p '{"data":{"application.resourceTrackingMethod":"annotation"}}'
# → configmap/argocd-cm patched
```

**Шаг 3: Массовый refresh приложений:**

```bash
for app in $(kubectl get applications.argoproj.io -n argocd -o jsonpath='{.items[*].metadata.name}'); do
  argocd app get "$app" --hard-refresh > /dev/null 2>&1
done
```

**Шаг 4: Массовая синхронизация для внедрения аннотаций:**

```bash
for app in $(kubectl get applications.argoproj.io -n argocd -o jsonpath='{.items[*].metadata.name}'); do
  argocd app sync "$app" --prune=false > /dev/null 2>&1
done
```

**Шаг 5: Проверка успешного наложения аннотаций:**

```bash
# Проверка процента объектов с аннотацией tracking-id
TOTAL_DEPLOYMENTS=$(kubectl get deployments -A --no-headers | wc -l)
TRACKED_DEPLOYMENTS=$(kubectl get deployments -A -o json | jq '[.items[] | select(.metadata.annotations["argocd.argoproj.io/tracking-id"] != null)] | length')

echo "Deployments: $TRACKED_DEPLOYMENTS из $TOTAL_DEPLOYMENTS содержат tracking-id"
# → Deployments: 42 из 42 содержат tracking-id
```

**Шаг 6: Возврат automated prune:**

```bash
for app in $APPS_WITH_PRUNE; do
  kubectl patch application "$app" -n argocd --type=merge -p '{"spec":{"syncPolicy":{"automated":{"prune":true}}}}'
done
# → application.argoproj.io/backend-api patched
# → application.argoproj.io/frontend-web patched
```

---

### Сценарий 5: Изоляция инстансов в Shared Cluster через Installation ID

В multi-tenant on-premise кластерах, где развернуто несколько контроллеров Argo CD (например, `argocd-system` и `argocd-tenants`), настройка `installationID` предотвращает перехват чужих ресурсов.

**1. Конфигурация первого контроллера (`namespace: argocd-system`):**

```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: argocd-cm
  namespace: argocd-system
data:
  application.resourceTrackingMethod: "annotation"
  installationID: "infra-system-ctrl"
```

**2. Конфигурация второго контроллера (`namespace: argocd-tenants`):**

```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: argocd-cm
  namespace: argocd-tenants
data:
  application.resourceTrackingMethod: "annotation"
  installationID: "tenant-apps-ctrl"
```

**3. Результат в метаданных ресурса:**
Если оба инстанса имеют приложение с одинаковым именем `ingress-controller`:
- Ресурсы системного контроллера:
  ```yaml
  metadata:
    annotations:
      argocd.argoproj.io/tracking-id: ingress-controller:apps/Deployment:system/ingress-ctrl
      argocd.argoproj.io/installation-id: infra-system-ctrl
  ```
- Ресурсы пользовательского контроллера:
  ```yaml
  metadata:
    annotations:
      argocd.argoproj.io/tracking-id: ingress-controller:apps/Deployment:tenant-a/ingress-ctrl
      argocd.argoproj.io/installation-id: tenant-apps-ctrl
  ```

Контроллер `infra-system-ctrl` при проверке кэша видит объекты с `installation-id: tenant-apps-ctrl` и игнорирует их, предотвращая взаимное удаление.

---

### Сценарий 6: Контроль Orphaned ресурсов через AppProject

В Argo CD встроен механизм обнаружения ресурсов, находящихся в целевом неймспейсе приложения, но не управляемых GitOps. Это предотвращает ручное создание объектов администраторами в обход Git.

**1. Конфигурация `AppProject`:**

```yaml
apiVersion: argoproj.io/v1alpha1
kind: AppProject
metadata:
  name: production-project
  namespace: argocd
spec:
  description: "Production Project с аудитом брошенных объектов"
  sourceRepos:
    - "https://git.internal.domain/infra/production.git"
  destinations:
    - namespace: "production"
      server: "https://kubernetes.default.svc"
  orphanedResources:
    warn: true
    ignore:
      # Исключение системных объектов и ConfigMap от kubelet
      - group: ""
        kind: ConfigMap
        name: kube-root-ca.crt
      - group: ""
        kind: Secret
        name: default-token-*
```

**2. Отображение в UI и CLI:**
При появлении ресурса без аннотации `tracking-id` в пространстве имен `production` Argo CD выставляет предупреждение:
```bash
argocd app get production-stack
# → Warning: Project 'production-project' has orphaned resources: [apps/Deployment/production/manual-debug-pod]
```

## Диагностика и устранение неполадок

### Базовые команды диагностики

```bash
# 1. Проверка текущего метода отслеживания в ConfigMap
kubectl get configmap argocd-cm -n argocd -o jsonpath='{.data.application\.resourceTrackingMethod}'
# → annotation

# 2. Проверка установленного installationID
kubectl get configmap argocd-cm -n argocd -o jsonpath='{.data.installationID}'
# → infra-system-ctrl

# 3. Инспекция полного набора tracking-метаданных на Deployment
kubectl get deployment backend-api -n production -o json | jq '{
  labels: {
    instance: .metadata.labels["app.kubernetes.io/instance"]
  },
  annotations: {
    tracking_id: .metadata.annotations["argocd.argoproj.io/tracking-id"],
    installation_id: .metadata.annotations["argocd.argoproj.io/installation-id"]
  }
}'
# → {
# →   "labels": { "instance": null },
# →   "annotations": {
# →     "tracking_id": "backend-api:apps/Deployment:production/backend-api",
# →     "installation_id": "infra-system-ctrl"
# →   }
# → }

# 4. Поиск всех объектов в пространстве имен, не имеющих tracking-id аннотации (ручные объекты)
kubectl get all -n production -o json | jq -r '.items[] | select(.metadata.annotations["argocd.argoproj.io/tracking-id"] == null) | "\(.kind)/\(.metadata.name)"'
# → Service/manual-test-nodeport
# → Pod/debug-toolbox
```

### Типичные ошибки и способы решения

| Ошибка / Симптом | Первопричина | Диагностика | Решение |
| :--- | :--- | :--- | :--- |
| `field is immutable: spec.template.metadata.labels` при деплое Helm-чарта | Использование метода `label`. Argo CD пытается переписать метку `app.kubernetes.io/instance`, входящую в неизменяемый selector Pod. | `argocd app get <app>` возвращает `SyncFailed`. В логах `controller` сообщение об ошибке мутации `matchLabels`. | Установить `application.resourceTrackingMethod: annotation` в `argocd-cm`. Выполнить `argocd app sync <app> --force`. |
| Ресурсы внезапно помечаются `RequiresPruning` после смены метода | Метод изменен в `argocd-cm`, но приложение еще не было синхронизировано, либо аннотации отсутствуют в Live State. | Проверить расхождение: `argocd app diff <app>`. Обратить внимание на блок `metadata.annotations`. | Отключить auto-prune, выполнить `argocd app sync <app>` для наложения аннотаций, затем вернуть auto-prune. |
| Коллизия имен: одно приложение управляет чужими ресурсами | В одном кластере запущены два инстанса Argo CD, либо имя приложения превышает 63 символа в режиме `label` (произошло усечение). | Выполнить `kubectl get <res> -o yaml` и проверить значение `argocd.argoproj.io/installation-id` и `tracking-id`. | 1. Настроить уникальный `installationID` в каждом `argocd-cm`.<br>2. Переключиться на метод `annotation`. |
| Объект, скопированный внешним оператором (HNC, Kyverno), удаляется Argo CD | Метод `label` не проверяет GVK/Namespace объекта. Скопированный объект имеет старую метку и считается устаревшим. | Проверить логи `argocd-application-controller` по ключевому слову `pruned resource`. | Переключиться на `annotation`. Механизм non-self-referencing предотвратит удаление скопированного объекта. |
| Приложение зависает в статусе `OutOfSync` из-за постоянного различия аннотаций | Admission-вебхук кластера (Kyverno, Gatekeeper) удаляет или модифицирует аннотацию `argocd.argoproj.io/tracking-id`. | `kubectl get events -n <ns>` — поиск предупреждений о мутациях admission webhook. | Добавить исключение в правила Kyverno/Gatekeeper для аннотаций пространства имен `argocd.argoproj.io/*`. |

### Мониторинг и метрики Prometheus

Метрики экспортируются сервисом `argocd-application-controller-metrics:8082`:

```promql
# 1. Частота циклов сверки состояния ресурсов
rate(argocd_app_reconcile_count[5m])

# 2. Количество ресурсов в кэше контроллера (по видам объектов)
argocd_cluster_api_resource_objects{server="https://kubernetes.default.svc"}

# 3. Ошибки синхронизации приложений из-за конфликтов метаданных
increase(argocd_app_sync_total{phase="Failed"}[15m])
```

## Лучшие практики

1. **Стандартизируйте метод `annotation`:**
   Всегда используйте `application.resourceTrackingMethod: annotation` как настройку по умолчанию для всех on-premise сред. Это исключает 100% проблем совместимости с Helm и устраняет лимит длины в 63 символа.
2. **Используйте `annotation+label` осознанно:**
   Включайте комбинированный метод только в том случае, если существующий стек мониторинга (Prometheus, VictoriaMetrics) критически зависит от метки `app.kubernetes.io/instance` для сопоставления метрик подов через `kube-state-metrics`.
3. **Всегда задавайте `installationID`:**
   Даже если в кластере сейчас работает один экземпляр Argo CD, добавление `installationID` предотвратит катастрофические последствия в будущем при развертывании тестового контроллера или изолированного экземпляра для отдельной команды.
4. **Безопасная миграция:**
   Никогда не переключайте `application.resourceTrackingMethod` "на лету" без предварительного снятия флага `prune: true` с критических продуктовых сервисов.
5. **Защищайте tracking-метаданные в Admission Webhooks:**
   При написании кластерных политик безопасности (Kyverno, OPA Gatekeeper) настраивайте правила исключений, запрещающие удаление или мутацию аннотаций `argocd.argoproj.io/*` сторонними пользователями или служебными учетными записями.

## Ограничения и граничные случаи

### Ограничения
- **CRD с жесткой валидацией метаданных:** Некоторые устаревшие или специализированные CRD содержат схемы OpenAPI v3 с `additionalProperties: false` на уровне `metadata.annotations`. Попытка Argo CD внедрить `tracking-id` завершится ошибкой валидации API Server. В таких изолированных случаях требуется использовать `ignoreDifferences` или корректировать CRD.
- **Длина аннотаций:** Хотя аннотации не имеют лимита в 63 символа, лимит всего объекта Kubernetes (etcd) составляет 1.5 МБ. Формат `tracking-id` занимает не более 200–300 байт, поэтому риск исчерпания памяти отсутствует.
- **Необратимость автоматического Prune:** Если метод отслеживания переключен, а старые объекты потеряли связь до синхронизации, контроллер воспримет их как чужие/осиротевшие. При ручном удалении приложения без флага `--no-cascade` они могут остаться в кластере.

### Граничные случаи
- **Ресурсы ядра без API Group:** Ресурсы ядра (`v1`) формируют идентификатор с пустым полем группы (`/ConfigMap:ns/name`). Это штатное поведение, парсер контроллера ожидает ведущий слэш.
- **Ресурсы без Namespace:** Кластерные объекты (`ClusterRole`, `Namespace`) содержат двоеточие и слэш без указания namespace (`:/name`). При написании парсеров или скриптов автоматизации на `bash` / `jq` необходимо учитывать регулярное выражение:
  `^([^:]+):([^/]*)/([^:]+):([^/]*)/(.+)$`
- **Ручное переименование Application:** Если имя `Application` изменено в YAML-манифесте без переноса состояния, Argo CD создаст новый `tracking-id`. Все старые ресурсы в кластере со старым `tracking-id` будут восприняты как осиротевшие и удалены при включенном `prune`. Для переименования необходимо либо сначала отключить `prune`, либо использовать процедуру миграции с обновлением аннотаций.

## Дополнительная информация

### См. также

- [Синхронизация ресурсов в Argo CD](./synchronization.md) — Жизненный цикл синхронизации, фазы, стратегии diff, Sync Waves и Hooks.
- [Удаление и очистка ресурсов](./argocd_deletion_and_cleanup.md) — Механика Prune, финализаторы, каскадное удаление и защита от случайного уничтожения.
- [Игнорирование различий (Ignore Differences)](./synchronization/ignore_differences.md) — Тонкая настройка diff через jqPathExpressions и managedFields.
- [Интеграция с Helm](./helm_integration.md) — Особенности совместной работы с Helm-чартами, releaseName и управление параметрами.
- [Обзор архитектуры Argo CD](./argocd_overview.md) — Компоненты ядра: API Server, Application Controller, Repo Server, Dex.
- [Установка и базовая настройка](./argocd_installation_and_setup.md) — Первоначальное развертывание, конфигурация ConfigMap `argocd-cm` и параметры контроллера.
- [Мультитенантность в Argo CD](./argocd_multi_tenancy.md) — Изоляция команд, AppProject, multi-instance архитектуры и разграничение прав.
- [Глубокое погружение в AppProject](./argocd_appproject_deep.md) — Ограничение источников, целевых пространств имен и аудит брошенных ресурсов (`orphanedResources`).

### Ссылки

- [Argo CD Official Docs — Resource Tracking](https://argo-cd.readthedocs.io/en/stable/user-guide/resource_tracking/)
- [Argo CD Official Docs — Declarative Setup & ConfigMap Reference](https://argo-cd.readthedocs.io/en/stable/operator-manual/declarative-setup/)
- [Argo CD Official Docs — Orphaned Resources Monitoring](https://argo-cd.readthedocs.io/en/stable/user-guide/orphaned-resources/)
- [Kubernetes Documentation — Well-Known Labels, Annotations and Taints](https://kubernetes.io/docs/reference/labels-annotations-taints/)
