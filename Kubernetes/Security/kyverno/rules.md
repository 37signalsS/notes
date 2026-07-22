# Типы правил Kyverno

## Определения

**Правило (rule)** — фундаментальный логический компонент политики Kyverno. Оно определяет условия выбора ресурсов (триггеры) и конкретные действия: проверку на соответствие стандартам (валидация), автоматическую корректировку манифестов (мутация), создание зависимых объектов (генерация), верификацию цепочки поставок (образы и SBOM (Software Bill of Materials)) или удаление по расписанию (очистка).

**Политика (policy)** — структурированный контейнер для одного или нескольких правил. В современной экосистеме Kubernetes (актуально на 2026 год) Kyverno поддерживает два формата декларации:

1.  **Классические политики (v1)**:
    - **Policy**: Применяется только к ресурсам внутри определенного Namespace (пространства имен).
    - **ClusterPolicy**: Глобальный ресурс, действующий на уровне всего кластера.
2.  **Модульные CEL-политики (v2)**: Высокопроизводительные ресурсы, использующие **CEL (Common Expression Language)**. Они могут автоматически транслироваться в нативные `ValidatingAdmissionPolicies` Kubernetes для минимизации задержек.
    - `ValidatingPolicy` / `ClusterValidatingPolicy`
    - `MutatingPolicy` / `ClusterMutatingPolicy`
    - `GeneratingPolicy` / `ClusterGeneratingPolicy`
    - `ImageValidatingPolicy` — специализированный ресурс для безопасности образов.
    - `DeletingPolicy` — новый стандарт для автоматической очистки ресурсов.

Подробное описание архитектуры компонентов (Admission, Background, Cleanup controllers) приведено в [Основных концепциях](./concepts.md).

---

## Основные концепции

### Типы правил и их механизмы

| Тип | Назначение | Ключевые механизмы / Подтипы |
| :--- | :--- | :--- |
| **validate** | Валидация ресурсов | `pattern` (шаблон), `anyPattern`, `deny` (явный запрет), `cel` (выражения) |
| **mutate** | Изменение полей ресурсов | `patchStrategicMerge`, `patchesJson6902`, `foreach` (итерация по массивам) |
| **generate** | Создание/клонирование | `clone` (копирование Secret/ConfigMap), `data` (новое описание), `synchronize` |
| **verifyImages** | Проверка безопасности | Cosign/Sigstore, проверка SBOM, верификация аттестаций (SLSA) |
| **cleanup** / **delete** | Удаление ресурсов | `schedule` (cron-расписание), селекторы времени жизни (TTL) |

### Механизмы выбора: Match и Exclude

Блоки `match` и `exclude` позволяют ювелирно настроить область действия правила, используя логику `any` (ИЛИ) и `all` (И).

```yaml
rules:
  - name: detailed-selector-example
    match:
      all:
        - resources:
            kinds:
              - Pod
            namespaces:
              - development
            operations:
              - CREATE
              - UPDATE
    exclude:
      any:
        - resources:
            selector:
              matchLabels:
                skip-policy: "true"
        - subjects:
            - kind: ServiceAccount
              name: cluster-admin
              namespace: kube-system
```

| Параметр | Техническое описание |
| :--- | :--- |
| `kinds` | Типы ресурсов (например, Deployment, Service, CustomResourceDefinition). |
| `namespaces` | Список пространств имен. Поддерживаются подстановочные знаки (wildcards). |
| `operations` | CREATE, UPDATE, DELETE, CONNECT. Позволяет ограничить политику конкретным жизненным циклом. |
| `subjects` | Пользователи, группы или ServiceAccounts. Позволяет создавать исключения для системных компонентов. |

---

## Практические сценарии

### Валидация с использованием шаблонов (Pattern) и Якорей

Правило `validate` проверяет манифест на соответствие заданному шаблону. Для сложной логики используются **якоря (anchors)**:

```yaml
rules:
  - name: security-context-validation
    validate:
      message: "Настройки безопасности контейнера не соответствуют корпоративному стандарту."
      pattern:
        spec:
          containers:
            - (name): "*" # Проверять все контейнеры
              securityContext:
                allowPrivilegeEscalation: false
                =(runAsNonRoot): true # Обязательное поле
                runAsUser: ">1000"    # Числовое сравнение
```

**Виды якорей:**
- `(field)` — **Conditional (Условный)**: Поле проверяется только в том случае, если оно уже присутствует в манифесте.
- `=(field)` — **Equality/Mandatory (Обязательный)**: Поле ДОЛЖНО присутствовать и иметь указанное значение.
- `^(field)` — **Reference (Ссылка)**: Используется для сравнения значений между разными частями манифеста.
- `+(field)` — **Add if absent (Добавить при отсутствии)**: Только для мутации.
- `>(n)`, `<(n)`, `>=(n)`, `<=(n)` — **Numeric comparison**: Работают внутри шаблонов для проверки версий или лимитов ресурсов.

### Запрещающие правила (Deny) и AdmissionReview

В отличие от `pattern`, правила `deny` используют явные условия для отклонения запроса. Они работают с объектом **AdmissionReview** через JMESPath.

```yaml
rules:
  - name: block-root-exec
    match:
      resources:
        kinds:
          - Pod/exec
    deny:
      conditions:
        - key: "{{ request.operation }}"
          operator: Equals
          value: CONNECT
      message: "Интерактивный доступ к подам запрещен через Kyverno."
```

### Современная валидация через CEL (v1.14+)

Использование CEL (Common Expression Language) позволяет выполнять проверки со скоростью нативного кода Kubernetes.

```yaml
cel:
  expressions:
    - expression: "object.spec.replicas <= 10"
      message: "Количество реплик не может превышать 10 для обеспечения стабильности кластера."
```

### Продвинутая мутация (patchStrategicMerge)

Мутация позволяет внедрять переменные, лейблы или Sidecar-контейнеры.

```yaml
mutate:
  patchStrategicMerge:
    spec:
      containers:
        - (name): "*"
          env:
            - name: CLUSTER_NAME
              value: "production-01"
```

### Верификация образов и SBOM (Supply Chain)

Kyverno 1.17+ предоставляет глубокую интеграцию с Sigstore для проверки безопасности артефактов.

```yaml
verifyImages:
  - imageReferences:
      - "ghcr.io/my-org/*"
    attestors:
      - entries:
          - keys:
              publicKeys: |
                -----BEGIN PUBLIC KEY-----
                ...
    verifySBOM:
      enabled: true
      attestor:
        entries:
          - keys:
              publicKeys: "..."
      # Пример проверки: запрет уязвимостей критического уровня
      conditions:
        - all:
          - key: "{{ sbom.vulnerabilities.critical_count }}"
            operator: Equals
            value: 0
```

### Генерация ресурсов и синхронизация (Clone/Data)

Правила `generate` автоматизируют создание ресурсов при появлении триггера (например, создание `LimitRange` при создании нового `Namespace`).

- `clone`: Копирует существующий ресурс (например, `Secret` с сертификатами) в новый Namespace.
- `data`: Создает ресурс по встроенному шаблону.
- `synchronize: true`: Если исходный ресурс изменится, Kyverno автоматически обновит все сгенерированные копии.

---

## Дополнительная информация

### Таблица операторов условий

Эти операторы используются в блоках `preconditions` и правилах `deny`.

| Оператор | Описание | Пример использования |
| :--- | :--- | :--- |
| `Equals` / `NotEquals` | Прямое сравнение строк или чисел. | `request.operation` |
| `AnyIn` / `AnyNotIn` | Проверка наличия хотя бы одного элемента из списка. | Проверка меток (Labels). |
| `AllIn` / `AllNotIn` | Проверка соответствия всех элементов списка. | Список разрешенных реестров образов. |
| `GreaterThan` / `LessThan` | Числовое сравнение. | Проверка лимитов памяти. |
| `PatternMatch` | Проверка строки на соответствие регулярному выражению (Regex). | Формат имени ресурса. |
| `DurationGreaterThan` | Сравнение временных интервалов. | TTL ресурсов. |

### Важные нюансы эксплуатации

1.  **Background Scan (Фоновое сканирование)**: По умолчанию работает для аудита существующих ресурсов. Если вы измените существующую политику, Kyverno пересканирует кластер и обновит отчеты, но **не удалит** и **не изменит** ресурсы, если не настроен параметр `mutateExistingOnPolicyUpdate` ([подробнее см. background.md](./background.md)).
2.  **Order of Execution**:
    - Сначала выполняются правила **Mutate** (чтобы валидация проверяла уже исправленный объект).
    - Затем **Validate**.
    - Затем **Generate**.
3.  **Failure Action**:
    - `audit`: Нарушение записывается в лог и PolicyReport, запрос разрешается.
    - `enforce`: Запрос блокируется (в Admission) или фиксируется как ошибка (в Background).
4.  **Kyverno и GitOps (Argo CD/Flux)**: При использовании `generate` и `mutate` убедитесь, что GitOps-инструменты игнорируют поля, которыми управляет Kyverno, чтобы избежать "дрифта" конфигурации ([детали в argo-cd.md](./argo-cd.md)).

### См. также
- [Практические примеры написания сложных политик](./policies/practical_scenarios.md)
- [Мониторинг, алертинг и Policy Reporter](./reporter.md)
- [Официальный справочник по CEL в Kyverno](https://kyverno.io/docs/writing-policies/cel/)
