# Типы правил Kyverno

## Определения

**Правило (Rule)** — фундаментальный логический компонент политики Kyverno, определяющий триггеры (условия выбора ресурсов) и действия: проверку на соответствие стандартам (валидация), автоматическую корректировку манифестов (мутация), создание зависимых объектов (генерация), верификацию цепочки поставок (образы) или очистку.

Каждое правило уникально идентифицируется именем в рамках политики. Одна политика может содержать множество правил, каждый из которых выполняет одну или несколько функций (validate, mutate, generate, verifyImages, cleanup). Правила применяются последовательно в порядке объявления в YAML-манифесте.

**Политика (Policy)** — декларативный манифест, содержащий массив правил. С 2026 года стандартом является разделение на:
*   **Классические политики (v1)**: `ClusterPolicy` и `Namespace Policy`. Используют JMESPath и шаблоны Pattern.
*   **Модульные CEL-политики (v2)**: `ValidatingPolicy`, `MutatingPolicy` и `GeneratingPolicy`. Используют **CEL (Common Expression Language)** для нативной интеграции с Kubernetes API.

**Условия предварительной проверки (Preconditions)** — блок внутри правила, позволяющий остановить выполнение правила до начала основной обработки, если манифест не соответствует базовым требованиям (например, отсутствие определенных аннотаций). Preconditions поддерживают как JMESPath (v1), так и CEL (v2) выражения.

---

## Ресурсы политик

| Ресурс | Версия | Описание | Применение |
| :--- | :--- | :--- | :--- |
| **ClusterPolicy** | v1 | Универсальный глобальный ресурс. | Сложные JMESPath-сценарии, `generate`. |
| **Policy** | v1 | Локальная политика в Namespace. | Командные ограничения. |
| **ValidatingPolicy**| v2 (CEL) | Высокопроизводительная валидация. | Замена PSA, PSS, CIS Benchmarks. |
| **MutatingPolicy** | v2 (CEL) | Модульная мутация ресурсов. | Инъекция технических меток и sidecars. |
| **GeneratingPolicy**| v2 (CEL) | Модульная генерация (v1.15+). | Автоматизация инфраструктуры. |
| **ImageValidatingPolicy** | v2 | Верификация артефактов и SBOM. | Безопасность цепочки поставок. |
| **ClusterCleanupPolicy** | v1 | Фоновая очистка ресурсов. | Гигиена кластера, FinOps. |

---

## Механизмы выбора: Match и Exclude

Блоки `match` и `exclude` поддерживают логические операторы `any` (ИЛИ) и `all` (И) для фильтрации ресурсов.

```yaml
rules:
  - name: hardened-selector
    match:
      all:
        - resources:
            kinds: [Pod]
            operations: [CREATE, UPDATE]
        - subjects:
            - kind: Group
              name: "system:authenticated"
    exclude:
      any:
        - resources:
            namespaces: [kube-system, kyverno]
        - clusterRoles: [cluster-admin]
```

### Условия Preconditions

Используются для фильтрации ресурсов на основе значений полей перед применением логики правила.

```yaml
preconditions:
  all:
    - key: "{{ request.object.metadata.labels.env }}"
      operator: Equals
      value: "production"
```

---

## Переменные и контекст

### Системные источники
Kyverno предоставляет доступ к метаданным запроса через синтаксис `{{ variable }}`:
*   `request.object`: Манифест создаваемого ресурса.
*   `request.oldObject`: Состояние ресурса до изменения (доступно при UPDATE).
*   `request.userInfo`: Информация о пользователе (имя, группы).
*   `serviceCall`: Результаты HTTP-запросов к внешним системам.

### Глобальный контекст (GlobalContext)
Механизм кэширования справочников (v1.17+), исключающий повторные вызовы API.
```yaml
context:
  - name: trusted-teams
    globalContextEntry:
      name: organization-roster
```

---

## Валидация (validate)

### Шаблоны и Якоря (v1)
Используются для декларативной проверки структуры манифеста.

| Якорь | Тип | Смысл |
| :--- | :--- | :--- |
| `(field)` | Conditional | Проверять, только если поле присутствует. |
| `=(field)` | Equality | Поле обязано присутствовать и иметь точное значение. |
| `^(field)` | Reference | Ссылка на другое поле в этом же манифесте. |
| `+(field)` | Addition | Поле должно существовать (минимум один элемент в списке). |

**Пример: Требование наличия labels**
```yaml
validate:
  pattern:
    metadata:
      labels:
        app: "?*"
        env: "?*"
```

### Явный запрет (Deny)
Позволяет блокировать запросы на основе логических условий.

```yaml
validate:
  deny:
    conditions:
      all:
        - key: "{{ request.object.spec.replicas }}"
          operator: GreaterThan
          value: 10
```

### Валидация с использованием CEL (v2)
Для политик нового поколения CEL обеспечивает более производительную проверку без JMESPath.

```yaml
# Пример ValidatingPolicy на CEL: запрет привилегированных контейнеров
apiVersion: policies.kyverno.io/v1alpha1
kind: ValidatingPolicy
metadata:
  name: deny-privileged
spec:
  validationActions: [Deny]
  matchConstraints:
    resourceRules:
      - apiGroups: [""]
        apiVersions: [v1]
        operations: [CREATE, UPDATE]
        resources: [pods]
  validations:
    - expression: "!object.spec.containers.exists(c, c.securityContext.privileged == true)"
      message: "Привилегированные контейнеры запрещены политикой безопасности."
```

### Ограничение образов по реестру
```yaml
validate:
  pattern:
    spec:
      containers:
        - image: "registry.internal.company.com/*"
```

### Блокировка удаления критичных ресурсов
```yaml
validate:
  deny:
    conditions:
      all:
        - key: "{{ request.operation }}"
          operator: Equals
          value: DELETE
        - key: "{{ request.object.metadata.labels.critical }}"
          operator: Equals
          value: "true"
```

---

## Мутация (mutate)

### Стратегии мутации
1.  **patchStrategicMerge**: Добавление или обновление блоков (стиль kubectl patch).
2.  **patchesJson6902**: Точечное редактирование через JSON-пути (add, remove, replace).
3.  **foreach**: Циклическая обработка массивов.
    *   `element`: текущий элемент массива.
    *   `elementIndex`: индекс текущего элемента.

**Пример: Добавление лимитов ресурсов через patchStrategicMerge**
```yaml
mutate:
  patchStrategicMerge:
    spec:
      containers:
        - (name): "?*"
          resources:
            limits:
              memory: "512Mi"
              cpu: "500m"
            requests:
              memory: "256Mi"
              cpu: "250m"
```

### Мутация с условиями (предусловия)
```yaml
rules:
  - name: add-sidecar-logging
    match:
      any:
        - resources:
            kinds: [Deployment]
    preconditions:
      all:
        - key: "{{ request.object.metadata.labels.environment }}"
          operator: Equals
          value: "production"
    mutate:
      patchStrategicMerge:
        spec:
          template:
            spec:
              containers:
                - name: log-agent
                  image: fluent/fluent-bit:latest
```

### Мутация существующих ресурсов (mutateExisting)
Kyverno может изменять уже запущенные объекты в фоновом режиме при обновлении политики.

```yaml
mutate:
  targets:
    - apiVersion: v1
      kind: Deployment
      namespace: "{{ request.namespace }}"
  patchStrategicMerge:
    metadata:
      labels:
        security-scan: "enabled"
```

**Важно:** При использовании `mutateExisting` убедитесь, что контроллер Kyverno имеет RBAC-права на целевые ресурсы. См. [Дополнительные права](./additional.md).

---

## Генерация (generate)

Автоматизирует создание инфраструктурных ресурсов.
*   **data**: Создание объекта "с нуля" по шаблону.
*   **clone**: Копирование эталонного ресурса (например, секрета из `default` в новый NS).
*   **synchronize**: Гарантирует, что при изменении эталона или шаблона все сгенерированные ресурсы обновятся автоматически.

### Пример: Автоматическое создание LimitRange для нового Namespace
```yaml
apiVersion: kyverno.io/v1
kind: ClusterPolicy
metadata:
  name: auto-limitrange
spec:
  rules:
    - name: generate-limitrange
      match:
        any:
          - resources:
              kinds: [Namespace]
      generate:
        synchronize: true
        apiVersion: v1
        kind: LimitRange
        name: default-limits
        namespace: "{{ request.object.metadata.name }}"
        data:
          spec:
            limits:
              - type: Container
                default:
                  cpu: "500m"
                  memory: "256Mi"
                defaultRequest:
                  cpu: "100m"
                  memory: "128Mi"
```

### Пример: Клонирование NetworkPolicy из эталона
```yaml
generate:
  synchronize: true
  apiVersion: networking.k8s.io/v1
  kind: NetworkPolicy
  name: default-deny
  namespace: "{{ request.object.metadata.name }}"
  clone:
    namespace: kyverno
    name: default-deny-template
```

---

## Верификация артефактов (verifyImages)

Интеграция с **Sigstore/Cosign** для защиты цепочки поставок.
*   **Signatures**: Проверка криптографической подписи образа.
*   **Attestations**: Проверка доказательств безопасности (результаты сканирования, прохождение тестов).
*   **VSA (Vulnerability Scanning Attestations)**: Проверка того, что образ прошел сканирование на критические уязвимости.
*   **SBOM**: Валидация состава ПО (проверка лицензий и библиотек).

### Пример: Верификация подписи Cosign
```yaml
apiVersion: kyverno.io/v1
kind: ClusterPolicy
metadata:
  name: verify-image-signature
spec:
  validationFailureAction: Enforce
  rules:
    - name: check-cosign-signature
      match:
        any:
          - resources:
              kinds: [Pod]
      verifyImages:
        - imageReferences:
            - "registry.internal.company.com/*"
          attestations:
            - type: https://cosign.sigstore.dev/attestation/vuln/v1
              conditions:
                - all:
                    - key: "{{ scanner.result.summary.criticalCount }}"
                      operator: Equals
                      value: 0
```

### Пример: Проверка SBOM на запрещенные лицензии
```yaml
verifyImages:
  - imageReferences:
      - "myapp/*"
    attestations:
      - type: https://spdx.dev/Document
        conditions:
          - all:
              - key: "{{ contains(@.licenseConcluded, 'GPL-3.0') }}"
                operator: Equals
                value: false
```

---

## Очистка ресурсов (Cleanup)

Реализуется через специализированный контроллер и ресурс `ClusterCleanupPolicy`.
*   **schedule**: Cron-расписание выполнения.
*   **conditions**: Фильтры для удаления (например, возраст ресурса > 30 дней).
*   **FinOps**: Автоматическое удаление временных Namespace в нерабочее время.

### Пример: Удаление завершенных Job старше 24 часов
```yaml
apiVersion: kyverno.io/v1
kind: ClusterCleanupPolicy
metadata:
  name: cleanup-completed-jobs
spec:
  matchResources:
    any:
      - resources:
          kinds: [Job]
  conditions:
    any:
      - key: "{{ request.object.status.conditions[?(@.type=='Complete')].status }}"
        operator: Equals
        value: "True"
      - key: "{{ time_since('{{ request.object.status.completionTime }}', now(), '') }}"
        operator: GreaterThan
        value: "24h"
  schedule: "0 */6 * * *"  # Каждые 6 часов
```

---

## Дополнительная информация

### Очередность и жизненный цикл
1. **Mutate** (синхронно) → 2. **Validate** & **VerifyImages** (синхронно) → 3. **Generate** & **Cleanup** (асинхронно через `UpdateRequest`).

### Нюансы эксплуатации
- **CEL vs JMESPath**: CEL выполняется на 40-60% быстрее за счет компиляции и отсутствия сетевых вызовов в VAP-режиме.
- **SSRF Protection**: Все внешние вызовы (`apiCall`) должны быть явно разрешены в конфигурации контроллера.
- **UpdateRequests**: Если мутация или генерация не срабатывает, проверьте ресурсы `updaterequests` в пространстве имен `kyverno`.

### Диагностика проблем с правилами

**Типовые ошибки и решения:**

| Проблема | Вероятная причина | Решение |
| :--- | :--- | :--- |
| Политика не применяется к существующим ресурсам | Отсутствует фоновое сканирование или `mutateExisting` | Убедитесь что `spec.background: true` и используйте `targets` в mutate |
| `generate` не создает ресурсы в новом NS | Нет триггера или проблемы с RBAC | Проверьте `updaterequests` и права контроллера |
| Ошибка `validation failed` при валидации | Несовпадение шаблона с реальным манифестом | Используйте `kubectl get policyreport -A` для диагностики |
| Мутация не применяется к Pod | Pod создан до применения политики | Используйте `mutateExisting` + `background: true` |
| CEL-политика не работает в VAP-режиме | Ошибка в выражении CEL | Проверьте логи Admission Controller, используйте `dryRun` |

### Best Practices

1. **Именование правил**: Используйте описательные имена в формате `verb-noun-condition` (например, `deny-privileged-containers`, `mutate-add-default-labels`).
2. **Тестируйте перед применением**: Используйте `kyverno test` для проверки политик:
   ```bash
   kyverno test ./policies/ --detailed-results
   ```
3. **Начинайте с Audit Mode**: Перед `Enforce` установите `validationFailureAction: Audit` для мониторинга влияния политик.
4. **Исключайте системные Namespace**: Всегда добавляйте `exclude` для `kube-system`, `kyverno`, `istio-system`.
5. **Используйте Preconditions**: Для сложной логики вместо вложенных `match` блоков.
6. **Документируйте политики**: Добавляйте аннотации с описанием назначения правила.

### Практические сценарии для DevOps/SRE

| Задача | Тип правила | Ключевые поля |
| :--- | :--- | :--- |
| Блокировка привилегированных контейнеров | validate | `securityContext.privileged` |
| Автоматическое добавление меток окружения | mutate | `patchStrategicMerge.metadata.labels` |
| Генерация NetworkPolicy для нового NS | generate | `clone` или `data` |
| Верификация подписей образов | verifyImages | `attestations`, `signatures` |
| Очистка завершенных Job | cleanup | `schedule`, `conditions` |
| Запрет использования тегов `:latest` | validate | `image: "*:latest"` в deny |
| Добавление sidecar-контейнера логирования | mutate | `foreach` по контейнерам |
| Генерация ResourceQuota для Namespace | generate | `data.spec.hard` |

### См. также
- [Основные концепции и архитектура CEL](./concepts.md)
- [Фоновое сканирование и жизненный цикл UR](./background.md)
- [Система отчетов PolicyReports](./reports.md)
- [Интеграция с Argo CD и GitOps](./argo-cd.md)
