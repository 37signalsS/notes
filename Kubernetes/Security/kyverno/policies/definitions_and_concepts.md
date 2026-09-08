# Политики Kyverno: Определения и структура

## Определения

**Политика (Policy)** — основной декларативный манифест Kyverno, определяющий правила контроля, изменения или генерации ресурсов в Kubernetes. Реализует подход **Policy-as-Code**, позволяя описывать требования безопасности и операционные стандарты в YAML/CEL.

### Классификация ресурсов

В актуальных версиях Kyverno (v1.19, август 2026) сосуществуют два архитектурных подхода:

1.  **Классические политики (kyverno.io/v1)** — **deprecated** (удаление запланировано в v1.20):
    *   **ClusterPolicy (cpol)**: Глобальный ресурс, применяемый ко всему кластеру. Поддерживает все типы правил (validate, mutate, generate, verifyImages, cleanup). Работает через Admission Webhook Kyverno (сетевой вызов, 5–15 мс).
    *   **Policy (pol)**: Локальный ресурс, действующий только в рамках одного Namespace.
2.  **Модульные CEL-политики (policies.kyverno.io/v1)** — **Stable** (с v1.18):
    *   **ValidatingPolicy**: Высокопроизводительная валидация через CEL. Транслируется в нативный `ValidatingAdmissionPolicy` Kubernetes, исключая сетевые задержки вебхука.
    *   **MutatingPolicy**: Модульная мутация ресурсов через `ApplyConfiguration` или `JSONPatch`. Транслируется в `MutatingAdmissionPolicy`.
    *   **GeneratingPolicy**: Модульная генерация зависимых ресурсов (создание или клонирование). Запускается асинхронно через Background Controller.
    *   **ImageValidatingPolicy**: Верификация подписей образов (Sigstore/Cosign), аттестаций и SBOM.
    *   **DeletingPolicy**: Асинхронное удаление ресурсов по расписанию (аналог ClusterCleanupPolicy для v2).

| Ресурс | apiVersion | Описание | Когда использовать |
| :--- | :--- | :--- | :--- |
| **ClusterPolicy** | `kyverno.io/v1` | Универсальный (deprecated). | Поддержка legacy-политик, пока не будут мигрированы. |
| **Policy** | `kyverno.io/v1` | Локальная в Namespace. | Командные ограничения без кластерного охвата. |
| **ValidatingPolicy** | `policies.kyverno.io/v1` | Валидация через CEL. | Замена PSA/PSS, CIS Benchmarks, базовые проверки. |
| **MutatingPolicy** | `policies.kyverno.io/v1` | Мутация через CEL. | Инъекция меток, sidecar, автоматическое исправление. |
| **GeneratingPolicy** | `policies.kyverno.io/v1` | Генерация ресурсов. | Автоматическое создание NetworkPolicy, ResourceQuota. |
| **ImageValidatingPolicy** | `policies.kyverno.io/v1` | Верификация образов. | Supply Chain Security, проверка подписей и SBOM. |
| **DeletingPolicy** | `policies.kyverno.io/v1` | Удаление по расписанию. | Очистка завершенных Job, временных Namespace. |

---

## Основные концепции

### Структура манифеста политики

Манифест состоит из стандартных метаданных Kubernetes и спецификации (`spec`), содержащей параметры управления и массив правил.

```yaml
apiVersion: kyverno.io/v1
kind: ClusterPolicy
metadata:
  name: enforce-standard-labels
  annotations:
    policies.kyverno.io/title: "Контроль обязательных меток"
    policies.kyverno.io/severity: "Medium"
spec:
  # Глобальный режим реакции
  validationFailureAction: Enforce
  # Разрешение фонового аудита
  background: true
  # Поведение при отказе контроллера
  failurePolicy: Fail
  # Глубокое управление режимами (v1.12+)
  validationFailureActionOverrides:
    - action: Audit
      namespaces: ["staging", "dev"]
  rules:
    - name: check-team-label
      match:
        any:
          - resources:
              kinds: [Pod]
      validate:
        message: "Поды должны иметь метку 'team'."
        pattern:
          metadata:
            labels:
              team: "?*"
```

### Ключевые параметры спецификации

*   **`validationFailureAction`**: Определяет основную стратегию.
    *   `Audit`: Ресурс разрешается, нарушение фиксируется в `PolicyReport`. Режим по умолчанию для тестирования.
    *   `Enforce`: Запрос блокируется (в Admission) или помечается как `fail` (в фоне).
*   **`validationFailureActionOverrides`**: Позволяет гибко переопределять режим (например, блокировать в `prod`, но только уведомлять в `dev`).
*   **`failurePolicy`**: Управляет поведением API-сервера при недоступности Kyverno.
    *   `Fail`: Безопасность превыше всего — создание ресурсов блокируется.
    *   `Ignore`: Отказоустойчивость превыше всего — ресурсы создаются без проверки.
*   **`applyRules`**: (`All` / `One`) — определяет, нужно ли применять все правила в политике или остановиться на первом сработавшем.
*   **`webhookTimeoutSeconds`**: Тайм-аут вебхука (по умолчанию 10, максимум 30). Увеличение до 30 рекомендуется при использовании внешних `apiCall` с высокой задержкой.

### Механизм выбора ресурсов (match / exclude)

Правила Kyverno работают только с ресурсами, соответствующими условиям `match` и не попадающими под `exclude`. Оба блока поддерживают логические операторы `any` (ИЛИ) и `all` (И).

#### Блок match

Определяет, к каким ресурсам применяется правило:

```yaml
rules:
  - name: check-pod-labels
    match:
      any:
        - resources:
            kinds: [Pod]
            namespaces: [production, staging]
            selector:
              matchLabels:
                app: critical
```

Поля фильтрации:

| Поле | Описание |
| :--- | :--- |
| `kinds` | Типы ресурсов (Pod, Deployment, Namespace и т.д.). |
| `namespaces` | Список пространств имен. |
| `namespaceSelector` | Селектор по меткам Namespace. |
| `selector` | Селектор по меткам самого ресурса. |
| `operations` | Тип операции (CREATE, UPDATE, DELETE). Для v1 — внутри `resources`. |
| `subjects` | Субъекты запроса (User, Group, ServiceAccount). |
| `clusterRoles` | Ограничение по именам ClusterRole субъекта. |

#### Блок exclude

Исключает ресурсы из действия правила (приоритет выше `match`):

```yaml
rules:
  - name: check-pod-labels
    match:
      any:
        - resources:
            kinds: [Pod]
    exclude:
      any:
        - resources:
            namespaces: [kube-system, kube-public, kyverno]
        - clusterRoles: [cluster-admin]
```

**Важно**: Системные Namespace (`kube-system`, `kube-public`, `kyverno`) всегда должны исключаться из политик, блокирующих ресурсы, чтобы предотвратить «мертвую петлю».

#### Preconditions (v1: JMESPath, v2: CEL)

Preconditions позволяют остановить выполнение правила до начала основной обработки, если манифест не соответствует базовым требованиям:

```yaml
rules:
  - name: only-production
    preconditions:
      all:
        - key: "{{ request.object.metadata.labels.env }}"
          operator: Equals
          value: "production"
    validate:
      # ... логика проверки ...
```

В `ValidatingPolicy` (v2) preconditions используют CEL:

```yaml
spec:
  validations:
    - expression: "'env' in object.metadata.labels && object.metadata.labels.env == 'production'"
      message: "Правило применяется только к production."
```

### Аннотации политики

Стандартные аннотации для документирования и интеграции с экосистемой:

| Аннотация | Назначение | Пример |
| :--- | :--- | :--- |
| `policies.kyverno.io/title` | Читаемое имя политики. | `"Запрет привилегированных контейнеров"` |
| `policies.kyverno.io/category` | Категория (Best Practices, Security, Compliance). | `"Pod Security Standards"` |
| `policies.kyverno.io/severity` | Уровень критичности (Critical, High, Medium, Low). | `"High"` |
| `policies.kyverno.io/description` | Подробное описание назначения. | `"Блокирует запуск..."` |
| `policies.kyverno.io/subject` | Тип ресурсов, к которым применяется. | `"Pod"` |
| `policies.kyverno.io/source` | Источник политики (URL или репозиторий). | `"https://github.com/org/policies"` |

**Autogen-аннотации** (только для ClusterPolicy v1):

| Аннотация | Назначение |
| :--- | :--- |
| `policies.kyverno.io/autogen-controllers` | Список контроллеров для автогенерации (или `none` для отключения). |
| `policies.kyverno.io/autogen-replica-count` | Минимальное количество реплик для автогенерации. |

---

## Практические сценарии

### 1. Безопасное внедрение через Audit Mode

Для минимизации влияния на работающие системы используйте цепочку `Audit` → `Analysis` → `Enforce`.

```yaml
apiVersion: kyverno.io/v1
kind: ClusterPolicy
metadata:
  name: require-resource-limits
  annotations:
    policies.kyverno.io/title: "Требование лимитов ресурсов"
    policies.kyverno.io/severity: "Medium"
    policies.kyverno.io/category: "Best Practices"
spec:
  validationFailureAction: Audit
  background: true
  rules:
    - name: check-resource-limits
      match:
        any:
          - resources:
              kinds: [Pod]
      validate:
        message: "Все контейнеры должны иметь лимиты ресурсов (resources.limits)."
        pattern:
          spec:
            containers:
              - resources:
                  limits:
                    memory: "?*"
                    cpu: "?*"
```

**Процесс внедрения:**
1. Примените политику в Audit.
2. Мониторьте `kubectl get polr -A` в течение 1–2 недель.
3. Проанализируйте ложноположительные срабатывания.
4. Переключите на `Enforce`.

### 2. Дифференцированный режим по Namespace (validationFailureActionOverrides)

Блокировка в production, аудит в dev/staging:

```yaml
apiVersion: kyverno.io/v1
kind: ClusterPolicy
metadata:
  name: restrict-host-path
spec:
  validationFailureAction: Enforce
  validationFailureActionOverrides:
    - action: Audit
      namespaces: ["dev", "staging", "testing"]
  background: true
  rules:
    - name: deny-host-path
      match:
        any:
          - resources:
              kinds: [Pod]
      exclude:
        any:
          - resources:
              namespaces: [kube-system, kyverno]
      validate:
        message: "hostPath запрещен. Используйте PVC."
        pattern:
          spec:
            volumes:
              - name: "*"
                (hostPath): null
```

### 3. Использование нативных CEL-политик (v2)

Для простых проверок используйте `ValidatingPolicy` для максимальной производительности (<1 мс задержка):

```yaml
apiVersion: policies.kyverno.io/v1
kind: ValidatingPolicy
metadata:
  name: check-run-as-non-root
  annotations:
    policies.kyverno.io/title: "Запрет запуска от root"
    policies.kyverno.io/severity: "Critical"
spec:
  validationActions: [Deny]
  matchConstraints:
    resourceRules:
      - apiGroups: [""]
        apiVersions: ["v1"]
        operations: ["CREATE", "UPDATE"]
        resources: ["pods"]
  validations:
    - expression: |
        (object.spec.containers + object.spec.?initContainers.orValue([])).all(c,
          has(c.securityContext) && has(c.securityContext.runAsNonRoot) && c.securityContext.runAsNonRoot == true
        )
      message: "Запуск от root запрещен. Укажите securityContext.runAsNonRoot: true."
```

### 4. Генерация ресурсов с clone и synchronize

При создании Namespace автоматически клонируется секрет из эталонного Namespace:

```yaml
apiVersion: kyverno.io/v1
kind: ClusterPolicy
metadata:
  name: clone-registry-credentials
spec:
  rules:
    - name: clone-cred-to-new-ns
      match:
        any:
          - resources:
              kinds: [Namespace]
      exclude:
        any:
          - resources:
              namespaces: [kube-system, kube-public, kyverno]
      generate:
        synchronize: true
        apiVersion: v1
        kind: Secret
        name: registry-credentials
        namespace: "{{ request.object.metadata.name }}"
        clone:
          namespace: kyverno
          name: registry-credentials
```

**Behavior `synchronize`:**
- `true`: При обновлении эталона все сгенерированные ресурсы обновляются автоматически. Удаление триггера удаляет сгенерированный ресурс.
- `false` (по умолчанию): Ресурс создается один раз и управляется независимо.

---

## Дополнительная информация

### Жизненный цикл обработки Admission Request

Процесс обработки запроса в Kyverno строго детерминирован:

1.  **Mutating Webhook (Синхронно)**:
    *   Применяются правила `mutate` (ClusterPolicy v1) или `MutatingPolicy` (v2).
    *   Если манифест изменен, он возвращается в API-сервер для повторной валидации.
    *   **Важно**: Для v2 `MutatingPolicy` с `reinvocationPolicy: IfNeeded` мутация повторяется, если предыдущий мутатор изменил объект.
2.  **Validating Webhook (Синхронно)**:
    *   Проверка правил `validate` (ClusterPolicy v1), `ValidatingPolicy` (v2), `verifyImages` и `ImageValidatingPolicy`.
    *   Если `validationFailureAction: Enforce` (v1) или `validationActions: [Deny]` (v2), запрос отклоняется с кодом 403.
3.  **Persistence**: Ресурс сохраняется в `etcd`.
4.  **Background Activity (Асинхронно)**:
    *   Запускаются правила `generate` (ClusterPolicy v1) или `GeneratingPolicy` (v2).
    *   Формируются `PolicyReport` / `ClusterPolicyReport`.
    *   **Update Requests (UR)**: Создаются для отслеживания статуса генерации и мутации существующих ресурсов.

### Admission-time vs Background

| Аспект | Admission-time | Background |
| :--- | :--- | :--- |
| **Триггер** | Запрос к API-серверу (CREATE/UPDATE/DELETE). | Фоновое сканирование или обновление политики. |
| **Синхронность** | Синхронно — блокирует запрос до завершения. | Асинхронно — не влияет на доступность API. |
| **Типичные правила** | validate, mutate (v1), verifyImages. | generate, mutateExisting, cleanup. |
| **Контроллер** | Admission Controller. | Background Controller. |
| **Поле управления** | `validationFailureAction` / `validationActions`. | `background: true` (v1). |

### Диагностика и типичные ошибки

| Проблема | Вероятная причина | Решение |
| :--- | :--- | :--- |
| Политика не применяется к существующим ресурсам | `background: false` или отсутствует `mutateExisting`. | Установите `background: true` (v1) или используйте `evaluation.mutateExisting.enabled: true` (v2 MutatingPolicy). |
| `generate` не создает ресурсы в новом NS | Нет триггера, проблемы с RBAC или имя NS не подставляется. | Проверьте `kubectl get updaterequests -n kyverno` и права `background-controller`. |
| Ошибка `validation failed` при валидации | Несовпадение шаблона CEL с реальным манифестом. | Используйте `kubectl get policyreport -A` и проверьте логи admission-controller. |
| Мутация не применяется к Pod | Pod создан до применения политики (v1). | Используйте `mutateExisting` + `background: true` (v1) или `evaluation.mutateExisting.enabled: true` (v2). |
| CEL-политика не работает в VAP-режиме | Ошибка в выражении CEL или неверный `matchConstraints`. | Проверьте логи admission-controller, используйте `kubectl create ... --dry-run=Server`. |
| `PolicyException` не действует | Имя политики или правила не совпадает. | Проверьте `policyName` и `ruleNames` в манифесте PolicyException. |
| `verifyImages` не блокирует образ | Образ не в списке `imageReferences`. | Расширьте glob-паттерн или добавьте конкретный реестр. |
| Зависшие UpdateRequests | Ошибка при мутации существующего ресурса. | `kubectl describe updaterequest <ur-name> -n kyverno` для диагностики. |

**Команды диагностики:**

```bash
# Состояние политик
kubectl get clusterpolicy -o wide
kubectl get validatingpolicy -o wide  # v2

# Отчеты о нарушениях
kubectl get polr -A
kubectl get cpolr

# Логи контроллеров
kubectl logs -n kyverno -l app.kubernetes.io/name=kyverno -c admission-controller
kubectl logs -n kyverno -l app.kubernetes.io/name=kyverno -c background-controller

# Зависшие UpdateRequests
kubectl get updaterequests -n kyverno

# Проверка RBAC для background-controller
kubectl auth can-i patch deployments \
  --as=system:serviceaccount:kyverno:kyverno-background-controller
```

### См. также

- **[Типы правил (подробно)](../rules.md)** — синтаксис mutate, validate, generate, cleanup.
- **[Библиотека практических примеров](./practical_scenarios.md)** — CEL и классические сценарии.
- **[Фоновое сканирование](../background.md)** — нюансы аудита существующих ресурсов.
- **[Отчеты и мониторинг](../reports.md)** — работа с Policy Reports.
