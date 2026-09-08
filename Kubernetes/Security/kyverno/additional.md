# Агрегированные роли Kyverno и продвинутые возможности

## Определения

**Агрегированные ClusterRoles** — механизм Kubernetes, позволяющий динамически расширять права существующих ролей через использование селекторов по меткам (labels). В контексте Kyverno это основной способ предоставления контроллерам прав на манипуляцию ресурсами (создание, изменение, удаление) без прямого редактирования системных ролей.

Kyverno использует собственный префикс меток `rbac.kyverno.io/aggregate-to-*`, отличный от стандартного Kubernetes `rbac.authorization.k8s.io/aggregate-to-*`. Это изоляцияNamespace позволяет избежать конфликтов с встроенными ролями кластера и явно указывать, что расширение предназначено для контроллеров Kyverno.

**GlobalContextEntry (v1.15+)** — кастомный ресурс Kyverno (CR), определяющий источник данных для кэширования в памяти контроллера. Позволяет политикам обращаться к справочникам (списки команд, разрешенные реестры) без повторных сетевых вызовов к внешним системам при каждом Admission-запросе. Поддерживает два источника: `kubernetesResource` (ConfigMap/Secret в кластере) и `apiCall` (HTTP-эндпоинт).

**Update Request (UR)** — внутренний ресурс Kyverno в пространстве имен `kyverno`, используемый для отслеживания и выполнения асинхронных операций мутации (`mutateExisting`) и генерации (`generate`) существующих ресурсов. UR служит промежуточным буфером между Background Controller и целевыми ресурсами кластера, обеспечивая надежность и возможность повторных попыток при сбоях.

**Жизненный цикл UR**:
- **Pending** — UR создан, ожидает обработки воркером Background Controller.
- **Processing** — контроллер считывает UR и применяет изменения к целевому ресурсу.
- **Completed** — операция выполнена успешно, UR помечен для автоматической очистки (v1.14+).
- **Failed** — операция завершилась ошибкой (RBAC, конфликт оптимистичной блокировки). Kyverno повторяет попытку до 3 раз с экспоненциальной задержкой.
- **Skip** — ресурс не соответствует текущему состоянию политики (например, был удален).

---

## Основные концепции

### Механизм агрегации прав в Kyverno

В отличие от стандартной агрегации RBAC Kubernetes, где контроллер `kube-controller-manager` собирает итоговые права, Kyverno реализует собственную логику расширения через метки с префиксом `rbac.kyverno.io/`. Это дизайнерское решение обеспечивает:

1. **ИзоляциюNamespace**: права контроллеров Kyverno не пересекаются с системными ролями.
2. **Явность назначения**: метка сразу указывает, для какого контроллера предназначено расширение.
3. **Гибкость**: каждый контроллер имеет отдельный селектор, что позволяет создавать детализированные политики минимальных привилегий.

**Алгоритм работы**:
1. При старте или обновлении политик Kyverno сканирует существующие `ClusterRole` на наличие меток агрегации.
2. Для каждого контроллера определяется целевая агрегирующая роль (например, `system:aggregated-kyverno-background-controller`).
3. Контроллер Kyverno (не kube-controller-manager) вычисляет объединение правил из всех ролей с соответствующей меткой.
4. Итоговые права применяются к ServiceAccount соответствующего контроллера через `ClusterRoleBinding`.

> **Важно**: В отличие от стандартной RBAC-агрегации, Kyverno может обновлять итоговые права в реальном времени при добавлении новых модульных ролей, без перезапуска контроллеров.

### Контроллеры и метки агрегации (v3.x)

| Контроллер | Метка агрегации | Назначение прав |
| :--- | :--- | :--- |
| **admission-controller** | `rbac.kyverno.io/aggregate-to-admission-controller: "true"` | Права на чтение данных для сложных CEL-валидаций, верификацию образов, доступ к API для `apiCall`. |
| **background-controller** | `rbac.kyverno.io/aggregate-to-background-controller: "true"` | Права на `generate`, `mutateExisting`, создание `UpdateRequest`. |
| **reports-controller** | `rbac.kyverno.io/aggregate-to-reports-controller: "true"` | Управление жизненным циклом `PolicyReport`, `ClusterPolicyReport`, `AdmissionReport`. Запись в агрегированный API. |
| **cleanup-controller** | `rbac.kyverno.io/aggregate-to-cleanup-controller: "true"` | Удаление ресурсов по расписанию через `CleanupPolicy` / `DeletingPolicy`. |

### Архитектура контроллеров и разделение обязанностей

Kyverno использует архитектуру с разделением обязанностей между четырьмя основными контроллерами. Каждый контроллер работает в отдельном Deployment и имеет изолированный ServiceAccount:

| Контроллер | ServiceAccount | Масштабирование | Критичность |
| :--- | :--- | :--- | :--- |
| **admission-controller** | `kyverno-admission-controller` | Horizontal по нагрузке (latency-sensitive) | Критический: блокирует API при недоступности |
| **background-controller** | `kyverno-background-controller` | Масштабируется по количеству URs | Важный: влияет на генерацию и мутацию |
| **reports-controller** | `kyverno-reports-controller` | Масштабируется по объему отчетов | Стандартный: аудит и наблюдаемость |
| **cleanup-controller** | `kyverno-cleanup-controller` | Обычно 1 реплика | Низкая: фоновая очистка |

### Глубокий разбор UpdateRequest

`UpdateRequest` — промежуточный Custom Resource (CR), который обеспечивает надежную асинхронную обработку операций `generate` и `mutateExisting`.

**Жизненный цикл**:
1. **Создание**: Background Controller создает UR при:
   - Применении новой политики с `mutateExisting: true` (v1) или `evaluation.mutateExisting.enabled: true` (v2).
   - Применении новой политики с `generate` + `generateExisting: true`.
   - Обновлении существующей политики, затрагивающей уже запущенные ресурсы.
2. **Выполнение**: Воркер `updateRequestWorkers` (по умолчанию 10) выбирает UR из очереди, применяет изменения и обновляет статус.
3. **Очистка**: После успешного выполнения (`Completed`) UR автоматически удаляется (начиная с v1.14). Если `spec.background: false` (v1) или политика не фоновая, UR не создается.

**Структура UR**:
```yaml
apiVersion: kyverno.io/v1
kind: UpdateRequest
metadata:
  name: <policy-name>-<resource-namespace>-<resource-name>-<uid>
  namespace: kyverno
spec:
  policy: <policy-name>
  rule: <rule-name>
  resource:
    apiVersion: <target-apiVersion>
    kind: <target-kind>
    namespace: <target-namespace>
    name: <target-name>
    uid: <target-uid>
status:
  state: Completed | Failed | Pending | Skip
  message: "Описание результата"
```

**Параметры конфигурации Background Controller**:
- `--updateRequestWorkers`: количество параллельных воркеров (по умолчанию 10). Увеличьте для кластеров с >5000 объектов.
- `--backgroundScanWorkers`: количество воркеров для фонового сканирования (по умолчанию 10).
- `--updateRequestDelayOnFailure`: задержка перед повторной попыткой при ошибке (по умолчанию 1s, экспоненциальный backoff до 60s).

### GlobalContextEntry: архитектура и типы

GlobalContextEntry решает проблему повторных сетевых вызовов при использовании `apiCall` или чтении тяжелых ConfigMaps. Данные кэшируются в памяти контроллера и обновляются асинхронно.

**Типы источников**:

| Тип | Принцип работы | Latency | Применение |
| :--- | :--- | :--- | :--- |
| `kubernetesResource` | Чтение ConfigMap/Secret из кластера через K8s API с настраиваемым интервалом. | N/A (in-memory) | Справочники, допустимые команды, реестры. |
| `apiCall` | HTTP GET к внешнему эндпоинту с интервалом обновления `periodSeconds`. | N/A (in-memory) | Инвентаризация, внешние системы авторизации. |

**Параметры спецификации**:
- `spec.kubernetesResource`: чтение из кластера.
  - `group`, `version`, `kind`: GVK целевого ресурса.
  - `name`, `namespace`: имя и namespace ресурса.
- `spec.apiCall`: HTTP-вызов.
  - `urlPath`: URL эндпоинта.
  - `method`: GET (по умолчанию).
  - `periodSeconds`: интервал обновления кэша (по умолчанию 300s).
  - `jmesPath`: извлечение данных из ответа.

**Ограничения**:
- GlobalContextEntry **не поддерживает** запись (write). Только чтение.
- При обновлении источника данных (ConfigMap) изменения появляются в кэше не мгновенно, а после истечения `periodSeconds` (по умолчанию 300 секунд).
- Если внешний API недоступен (`apiCall`), кэш продолжает возвращать последние успешные данные (stale-while-revalidate). Это предотвращает блокировку кластера.
- Объем кэшированных данных ограничен памятью процесса контроллера. Для объемных справочников (>10 MB) используйте `apiCall` с фильтрацией через `jmesPath`.

### Продвинутые механизмы

*   **CEL-First Admission**: Использование нативных `ValidatingAdmissionPolicies` Kubernetes для базовых проверок снижает задержку (latency) API-запросов на 30–50% по сравнению с вебхуком Kyverno. Однако VAP поддерживает только валидацию, без мутации и генерации.
*   **Автоматическое управление UR**: В версиях 1.14+ Kyverno автоматически очищает успешно выполненные `UpdateRequests`, предотвращая засорение хранилища `etcd`. Политики с `mutateExisting` на постоянной основе требуют мониторинга количества создаваемых UR.
*   **Background Scan modes**: Режим фонового сканирования (`spec.background: true` в v1, `evaluation.background.enabled: true` в v2) позволяет формировать `PolicyReport` для существующих ресурсов. Важно: фоновое сканирование в режиме `Enforce` не блокирует существующие ресурсы, а лишь фиксирует нарушения в отчетах.

---

## Практические сценарии

### 1. Делегирование прав на генерацию (Generate)

Необходимо для политик, создающих инфраструктурные объекты (NetworkPolicy, ResourceQuota, LimitRange) при появлении нового Namespace.

```yaml
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRole
metadata:
  name: kyverno:generate-network-policies
  labels:
    rbac.kyverno.io/aggregate-to-background-controller: "true"
rules:
  - apiGroups: ["networking.k8s.io"]
    resources: ["networkpolicies"]
    verbs: ["create", "update", "patch", "get", "list", "watch"]
```

**Проверка**:
```bash
kubectl auth can-i create networkpolicies \
  --as=system:serviceaccount:kyverno:kyverno-background-controller
# → yes
```

### 2. Полная валидация RBAC для всех контроллеров

Пошаговая проверка прав для каждого контроллера Kyverno. Выполняется после установки или при диагностике проблем с генерацией/мутацией.

```bash
# 1. Admission Controller: чтение ресурсов для валидации
kubectl auth can-i get deployments \
  --as=system:serviceaccount:kyverno:kyverno-admission-controller
kubectl auth can-i get configmaps \
  --as=system:serviceaccount:kyverno:kyverno-admission-controller

# 2. Background Controller: генерация и мутация
kubectl auth can-i create resourcequotas \
  --as=system:serviceaccount:kyverno:kyverno-background-controller
kubectl auth can-i patch deployments \
  --as=system:serviceaccount:kyverno:kyverno-background-controller
kubectl auth can-i create networkpolicies \
  --as=system:serviceaccount:kyverno:kyverno-background-controller

# 3. Reports Controller: запись отчетов
kubectl auth can-i create policyreports.kyverno.io \
  --as=system:serviceaccount:kyverno:kyverno-reports-controller
kubectl auth can-i get namespaces \
  --as=system:serviceaccount:kyverno:kyverno-reports-controller

# 4. Cleanup Controller: удаление ресурсов
kubectl auth can-i delete jobs \
  --as=system:serviceaccount:kyverno:kyverno-cleanup-controller
kubectl auth can-i delete namespaces \
  --as=system:serviceaccount:kyverno:kyverno-cleanup-controller
```

Если любая команда возвращает `no`, создайте соответствующую `ClusterRole` с меткой агрегации и правилами `rules`.

### 3. Настройка Global Context для внешних данных

Используется для кэширования данных из внешнего API или тяжелого ConfigMap, чтобы исключить нагрузку на источник при каждом Admission-запросе.

**Вариант A: Кэширование ConfigMap (рекомендуется для статических справочников)**:
```yaml
apiVersion: kyverno.io/v1alpha2
kind: GlobalContextEntry
metadata:
  name: allowed-teams-cache
spec:
  kubernetesResource:
    group: ""
    version: "v1"
    kind: ConfigMap
    name: teams-metadata
    namespace: kyverno
```

**Вариант B: Кэширование внешнего API**:
```yaml
apiVersion: kyverno.io/v1alpha2
kind: GlobalContextEntry
metadata:
  name: inventory-cache
spec:
  apiCall:
    urlPath: "https://inventory.corp.internal/api/v1/teams"
    method: GET
    periodSeconds: 300
    jmesPath: "teams[].name"
```

**Использование в политике (v2 ValidatingPolicy)**:
```yaml
apiVersion: policies.kyverno.io/v1alpha1
kind: ValidatingPolicy
metadata:
  name: check-team-exists
spec:
  validationActions: [Deny]
  matchConstraints:
    resourceRules:
      - apiGroups: [""]
        apiVersions: ["v1"]
        operations: ["CREATE", "UPDATE"]
        resources: ["namespaces"]
  context:
    - name: teams
      globalContextEntry: allowed-teams-cache
  validations:
    - expression: "variables.teams.data.allowed.contains(object.metadata.labels['team'])"
      message: "Namespace должен принадлежать зарегистрированной команде."
```

### 4. Управление жизненным циклом (Cleanup TTL)

Kyverno позволяет реализовать концепцию "временных сред" без написания сложных политик, используя стандартные метки.

```yaml
# Пример временного Namespace для QA
apiVersion: v1
kind: Namespace
metadata:
  name: feature-branch-qa
  labels:
    cleanup.kyverno.io/ttl: "12h" # Удаление через 12 часов
    app.kubernetes.io/managed-by: kyverno
```

**Проверка работы очистки**:
```bash
# Просмотр политик очистки
kubectl get clusterdeletingpolicy -A

# Проверка создания CronJob для очистки
kubectl get cronjob -n kyverno

# Просмотр логов cleanup-controller
kubectl logs -n kyverno -l app.kubernetes.io/component=cleanup-controller --tail=50
```

### 5. Мутация существующих ресурсов (mutateExisting)

Пример политики, которая асинхронно добавляет метку безопасности во все существующие Namespace, где она отсутствует. Использует `targets` для точного выбора ресурсов.

```yaml
apiVersion: kyverno.io/v1
kind: ClusterPolicy
metadata:
  name: enforce-security-label
spec:
  mutateExistingOnPolicyUpdate: false # Рекомендуется false при использовании targets
  rules:
    - name: add-label-to-namespaces
      match:
        any:
          - resources:
              kinds: [Namespace]
              selector:
                matchLabels:
                  environment: "production"
      mutate:
        targets:
          - apiVersion: v1
            kind: Namespace
            selector:
              matchLabels:
                security-audit: null # Обрабатывать только те, где метки нет
        patchStrategicMerge:
          metadata:
            labels:
              security-audit: "enabled"
              audit-date: "{{ time_now_utc() }}"
```

**Проверка выполнения**:
```bash
# Просмотр созданных UpdateRequests
kubectl get updaterequests -n kyverno -l policy=enforce-security-label

# Детальная информация о конкретном UR
kubectl describe updaterequest enforce-security-label-default-<uid> -n kyverno
```

### 6. Исключения через PolicyException с TTL

Вместо ослабления глобальной политики используйте точечные исключения с автоматическим истечением срока действия. Это позволяет командам приложений запускать критичные сервисы без нарушения общих стандартов кластера.

```yaml
apiVersion: kyverno.io/v1
kind: PolicyException
metadata:
  name: legacy-app-exception
  namespace: team-backend
  annotations:
    kyverno.io/exception-ttl: "48h" # Автоматическое удаление через 48 часов
spec:
  exceptions:
    - policyName: disallow-privileged-containers
      ruleNames:
        - check-privileged
  match:
    any:
      - resources:
          kinds:
            - Pod
          namespaces:
            - team-backend
          names:
            - legacy-*
```

**Важно**: `PolicyException` требует отдельного RBAC-контроля. Рекомендуется выделить отдельную группу через `ClusterRoleBinding` с правами на создание `policyexceptions` только в разрешенных namespace.

### 7. Интеграция с GitOps (Argo CD)

При использовании Argo CD для управления политиками Kyverno необходимо учитывать особенности Server-Side Apply (SSA) и взаимодействия с мутацией.

**Рекомендации**:
1. **Отключение автоматической мутации манифестов политик**: Argo CD может конфликтовать с внутренней мутацией Kyverno. Используйте `argocd.argoproj.io/sync-options: Prune=false` для ресурсов `PolicyReport`.
2. **Server-Side Apply**: Убедитесь, что Argo CD использует SSA (`--server-side`), чтобы не перезаписывать управляемые поля.
3. **Health check**: Настройте кастомный health check для Kyverno ресурсов в Argo CD, так как стандартный `kubectl` не всегда корректно определяет состояние политик.

```yaml
# Argo CD Application для Kyverno политик
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: kyverno-policies
  namespace: argocd
spec:
  project: default
  source:
    repoURL: https://git.corp.internal/platform/kyverno-policies.git
    targetRevision: main
    path: policies
  destination:
    server: https://kubernetes.default.svc
    namespace: kyverno
  syncPolicy:
    automated:
      prune: true
      selfHeal: true
    syncOptions:
      - ServerSideApply=true
      - Prune=false # Не удалять PolicyReports
```

### 8. Shift-Left тестирование политик

Интеграция проверки политик в CI/CD пайплайн для раннего обнаружения нарушений до деплоя в кластер.

```bash
# Установка Kyverno CLI
curl -sSLo kyverno.tar.gz https://github.com/kyverno/kyverno/releases/download/v1.19.0/kyverno-cli_v1.19.0_linux_x86_64.tar.gz
tar -xzf kyverno.tar.gz kyverno
sudo mv kyverno /usr/local/bin/

# Запуск тестов для директории с политиками
kyverno test ./policies/ --detailed-results

# Применение политики в dry-run режиме (только отчет, без блокировки)
kyverno apply ./policies/disallow-privileged.yaml \
  --resource ./test-fixtures/pod-privileged.yaml \
  --policy-report
```

**GitLab CI пример**:
```yaml
kyverno_scan:
  image: ghcr.io/kyverno/kyverno:latest
  script:
    - kyverno test ./policies/ --detailed-results
  rules:
    - changes:
        - "policies/**/*.yaml"
        - ".kyvernoignore"
```

---

## Техническое обслуживание и диагностика

### Мониторинг UpdateRequests

Если фоновые операции (мутация существующих ресурсов) не выполняются, проверьте состояние ресурсов UR:

```bash
# Просмотр всех UR в пространстве имен kyverno
kubectl get updaterequests -n kyverno -o wide

# Фильтрация по политике
kubectl get updaterequests -n kyverno -l policy=enforce-security-label

# Детальная диагностика конкретного UR
kubectl describe updaterequest <ur-name> -n kyverno

# Просмотр зависших или ошибочных запросов
kubectl get updaterequests -n kyverno -o json | jq '.items[] | select(.status.state != "Completed")'
```

### Оптимизация производительности контроллеров

При использовании внешнего сервера отчетов или больших кластеров (>5000 объектов) настройте параметры в Helm `values.yaml`:

```yaml
# values.yaml для Helm-установки Kyverno
backgroundController:
  replicas: 2
  resources:
    limits:
      cpu: "500m"
      memory: "512Mi"
    requests:
      cpu: "200m"
      memory: "256Mi"
  envVars:
    - name: BACKGROUND_SCAN_INTERVAL
      value: "12h" # Полное сканирование раз в 12 часов
    - name: UPDATE_REQUEST_WORKERS
      value: "20" # Увеличить для больших кластеров

reportsController:
  replicas: 2
  resources:
    limits:
      cpu: "500m"
      memory: "512Mi"
  envVars:
    - name: BACKGROUND_SCAN_INTERVAL
      value: "12h"

admissionController:
  replicas: 3 # HA: минимум 3 реплики
  resources:
    limits:
      cpu: "1000m"
      memory: "1Gi"
  envVars:
    - name: WEBHOOK_TIMEOUT
      value: "15" # Увеличить для сложных CEL-проверок
```

### Диагностика RBAC и агрегации прав

Методология поиска проблем с правами контроллеров:

```bash
# Шаг 1: Проверка что метки агрегации установлены
kubectl get clusterrole -l rbac.kyverno.io/aggregate-to-background-controller=true

# Шаг 2: Проверка итоговых правил (должны быть не пустыми)
kubectl get clusterrole -l rbac.kyverno.io/aggregate-to-background-controller=true -o jsonpath='{.rules}' | jq .

# Шаг 3: Проверка ClusterRoleBinding
kubectl get clusterrolebinding -l rbac.kyverno.io/aggregate-to-background-controller=true

# Шаг 4: Проверка конкретного права
kubectl auth can-i create networkpolicies \
  --as=system:serviceaccount:kyverno:kyverno-background-controller

# Шаг 5: Проверка логов контроллера на ошибки RBAC
kubectl logs -n kyverno -l app.kubernetes.io/component=background-controller --tail=100 | grep -i "forbidden\|unauthorized"
```

### Типичные ошибки и решения

| Проблема | Вероятная причина | Решение |
| :--- | :--- | :--- |
| UpdateRequest в состоянии Failed | Нет прав на `patch` целевого ресурса | Создайте ClusterRole с меткой агрегации и verbs: [patch, update, get, list, watch] |
| GlobalContext возвращает stale данные | Слишком большой `periodSeconds` | Уменьшите интервал до 60s для актуальных данных |
| Background Controller не создает UR | `spec.background: false` или `mutateExisting` не включен | Проверьте конфигурацию политики и логи контроллера |
| Reports Controller не создает PolicyReport | Нет прав на создание `policyreports.kyverno.io` | Добавьте правила для `policyreports`, `clusterpolicyreports` в ClusterRole |
| Cleanup не удаляет ресурсы | `schedule` не сработал или нет прав на delete | Проверьте CronJob в namespace kyverno и права cleanup-controller |
| Конфликт с Argo CD | Argo CD перезаписывает мутированные ресурсы | Используйте SSA и `Prune=false` для отчетов |
| Высокая задержка Admission | Большое количество правил или `apiCall` в политике | Используйте CEL-based ValidatingPolicy (v2) и GlobalContext |

### Проверка целостности кластера после изменений

```bash
# Проверка что все контроллеры запущены
kubectl get pods -n kyverno

# Проверка состояния вебхуков
kubectl get validatingwebhookconfigurations kyverno-resource-validating-webhook-cfg -o yaml
kubectl get mutatingwebhookconfigurations kyverno-resource-mutating-webhook-cfg -o yaml

# Проверка что политики загружены
kubectl get clusterpolicy,validatingpolicy,mutatingpolicy,generatingpolicy -A

# Проверка последних Admission-отчетов
kubectl get admissionreport -A --sort-by=.metadata.creationTimestamp | tail -20
```

---

## Дополнительная информация

### Связанные темы

- **[Обзор RBAC](../rbac/rbac_overview.md)** — основы управления доступом.
- **[Агрегация ролей (общая)](../rbac/aggregation_scenarios.md)** — общие примеры расширения прав в Kubernetes.
- **[Основные концепции Kyverno](./concepts.md)** — архитектура и движок CEL.
- **[Типы правил (rules)](./rules.md)** — подробности работы mutate и generate.
- **[Фоновое сканирование](./background.md)** — архитектура Background и Reports Controller.
- **[Продвинутые возможности](./policies/advanced_topics.md)** — CEL, GlobalContext, V2 API.

### Ссылки и ресурсы

- [Kyverno Reports Server](https://github.com/kyverno/reports-server) — внешнее хранилище для масштабируемых отчетов.
- [Официальная документация по Global Context](https://kyverno.io/docs/writing-policies/context/global-context/)
- [Официальная документация по UpdateRequests](https://kyverno.io/docs/background-operations/)
- [Официальная документация по RBAC](https://kyverno.io/docs/installation/rbac/)
