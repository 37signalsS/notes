# Написание политик Kyverno

## Определения

**Политика (Policy)** — набор правил Kyverno, объединенных общей целью. Определяет какие ресурсы проверять/изменять и какие действия применять.

**Типы политик**:
- **Policy** — namespace-scoped, применяется к ресурсам в конкретном namespace
- **ClusterPolicy** — cluster-scoped, применяется ко всему кластеру

> **SSoT**: Это основной файл по написанию политик. [Типы правил](./rules.md) описывают детали правил.

---

## Basic Concepts

### Структура политики

```yaml
apiVersion: kyverno.io/v1
kind: ClusterPolicy  # или Policy
metadata:
  name: policy-name
  annotations:
    policies.kyverno.io/title: Заголовок
    policies.kyverno.io/category: security
    policies.kyverno.io/severity: high
    policies.kyverno.io/description: Описание политики
spec:
  validationFailureAction: Enforce  # или Audit
  background: true  # фоновое сканирование
  rules:
    - name: rule-name
      match:
        resources:
          kinds:
            - Pod
      validate:
        # ... правило валидации
```

### Поля spec

| Поле | Тип | Описание |
|------|-----|----------|
| `validationFailureAction` | `Enforce` / `Audit` | Действие при нарушении (`Enforce` — запретить, `Audit` — только отчет) |
| `background` | `true` / `false` | Включить фоновое сканирование (по умолчанию `true`) |
| `rules` | array | Набор правил (минимум одно) |
| `failurePolicy` | `Fail` / `Ignore` | Действие при ошибке webhook (по умолчанию `Fail`) |

### Match и Exclude

```yaml
rules:
  - name: example-rule
    match:
      any:  # Логическое OR
        - resources:
            kinds:
              - Pod
            namespaces:
              - default
              - user1
            operations:
              - CREATE
              - UPDATE
    exclude:
      all:  # Логическое AND
        - resources:
            namespaces:
              - kube-system
            names:
              - "kube-*"
```

| Параметр | Описание |
|----------|----------|
| `any` / `all` | Логическое объединение условий (OR / AND) |
| `kinds` | Типы ресурсов (Pod, Deployment, Service, etc.) |
| `namespaces` | Namespace для применения |
| `names` | Имена ресурсов (поддерживает wildcard `*`) |
| `operations` | Операции: CREATE, UPDATE, DELETE, CONNECT |

---

## Practical Scenarios

### Валидация с помощью pattern

Правило `validate` с типом `pattern` проверяет манифест на соответствие шаблону:

```yaml
rules:
  - name: require-run-as-non-root
    match:
      resources:
        kinds:
          - Pod
    validate:
      failureAction: Enforce
      message: "Container must run as non-root user"
      pattern:
        spec:
          =(securityContext):
            runAsNonRoot: true
            runAsUser: ">0"
```

**Якоря (anchors)**:
- `(field)` — опциональное поле: если присутствует, проверяется условие
- `=(field)` — обязательное поле
- `>(n)`, `>=(n)`, `=(n)`, `<(n)`, `<=(n)` — числовые сравнения
- `*` — wildcard (любое значение)

### Запрещающие правила (deny)

Правило `deny` использует условия для запрета:

```yaml
rules:
  - name: deny-host-path
    match:
      resources:
        kinds:
          - Pod
    deny:
      conditions:
        - key: "{{ request.object.spec.volumes[*].hostPath }}"
          operator: AnyNotIn
          value:
            - ""
            - null
      message: "HostPath volumes are forbidden"
```

Условия работают с **AdmissionReview** — JSON-объект, содержащий информацию о запросе:
- `request.object` — проверяемый ресурс
- `request.userInfo` — информация о пользователе
- `request.namespace` — namespace операции

### Примеры политик

#### Требование non-root пользователя

Требует обязательного наличия `securityContext` с `runAsUser > 0`:

```yaml
apiVersion: kyverno.io/v1
kind: ClusterPolicy
metadata:
  name: require-run-as-non-root
spec:
  validationFailureAction: Enforce
  background: true
  rules:
    - name: run-as-non-root-user
      match:
        resources:
          kinds:
            - Pod
      validate:
        message: "runAsUser must be greater than 0"
        pattern:
          spec:
            =(securityContext):
              runAsUser: ">0"
    - name: run-as-non-root-group
      match:
        resources:
          kinds:
            - Pod
      validate:
        message: "runAsGroup must be greater than 0"
        pattern:
          spec:
            =(securityContext):
              runAsGroup: ">0"
```

#### Запрет HostPath

Запрещает использование `hostPath` volumes:

```yaml
apiVersion: kyverno.io/v1
kind: ClusterPolicy
metadata:
  name: deny-host-path
spec:
  validationFailureAction: Enforce
  background: true
  rules:
    - name: deny-host-path
      match:
        resources:
          kinds:
            - Pod
      deny:
        conditions:
          - key: "{{ request.object.spec.volumes[*].hostPath }}"
            operator: AnyNotIn
            value:
              - ""
              - null
        message: "HostPath volumes are forbidden"
```

> **Примечание**: Данная политика не перехватывает `PersistentVolume` с типом `Local`. Необходимо создавать отдельную политику для PV.

#### Требование limits ресурсов

```yaml
apiVersion: kyverno.io/v1
kind: ClusterPolicy
metadata:
  name: require-resource-limits
spec:
  validationFailureAction: Enforce
  background: true
  rules:
    - name: require-limits
      match:
        resources:
          kinds:
            - Pod
      validate:
        message: "CPU and memory limits are required"
        pattern:
          spec:
            containers:
              - resources:
                  limits:
                    memory: "?*"
                    cpu: "?*"
```

#### Запрет privileged контейнеров

```yaml
apiVersion: kyverno.io/v1
kind: ClusterPolicy
metadata:
  name: deny-privileged-containers
spec:
  validationFailureAction: Enforce
  background: true
  rules:
    - name: deny-privileged
      match:
        resources:
          kinds:
            - Pod
      validate:
        message: "Privileged containers are forbidden"
        pattern:
          spec:
            containers:
              - =(securityContext):
                  privileged: false
```

#### Мутация: Добавление securityContext

```yaml
apiVersion: kyverno.io/v1
kind: ClusterPolicy
metadata:
  name: add-security-context
spec:
  rules:
    - name: add-default-securitycontext
      match:
        resources:
          kinds:
            - Pod
      mutate:
        patchStrategicMerge:
          spec:
            securityContext:
              runAsNonRoot: true
              runAsUser: 1000
              fsGroup: 1000
```

#### Генерация: Копирование Secret

```yaml
apiVersion: kyverno.io/v1
kind: ClusterPolicy
metadata:
  name: copy-docker-registry-secret
spec:
  rules:
    - name: copy-secret
      match:
        resources:
          kinds:
            - Namespace
      generate:
        kind: Secret
        name: docker-registry-credentials
        namespace: "{{request.object.metadata.name}}"
        clone:
          namespace: template
          name: docker-registry-credentials
        synchronize: true
```

---

## Additional Information

### Важные замечания

1. **Background scan не применяется к существующим ресурсам** — политика срабатывает только при CREATE/UPDATE ([подробнее](./background.md))
2. По умолчанию примеры политик в документации используют `validationFailureAction: audit`
3. Для полной защиты необходимо переключить на `validationFailureAction: Enforce`
4. Политики применяются к **Pod** — Kyverno проверяет итоговый Pod, сгенерированный из Deployment/StatefulSet/DaemonSet

### Операторы условий

| Оператор | Описание | Пример |
|----------|----------|--------|
| `AnyIn` / `AnyNotIn` | Проверка элемента массива на вхождение/невхождение | `AnyNotIn: ["value1", "value2"]` |
| `AllIn` / `AllNotIn` | Проверка всех элементов массива | `AllIn: ["value1", "value2"]` |
| `Equal` / `NotEqual` | Равенство / неравенство | `Equal: "value"` |
| `GreaterThanOrEquals` / `LessThanOrEquals` | Числовые сравнения | `GreaterThanOrEquals: 100` |
| `PatternMatch` | Проверка по regex-шаблону | `PatternMatch: "^prod-*"` |
| `In` / `NotIn` | Проверка значения в списке | `In: ["value1", "value2"]` |

### Переменные в политиках

Kyverno поддерживает подстановку переменных:

| Переменная | Описание |
|------------|----------|
| `{{request.object.metadata.name}}` | Имя ресурса |
| `{{request.object.metadata.namespace}}` | Namespace ресурса |
| `{{request.userInfo.username}}` | Имя пользователя |
| `{{@}}` | Ссылка на текущий элемент в foreach |

### Пример с foreach

```yaml
rules:
  - name: require-readonly-rootfs
    match:
      resources:
        kinds:
          - Pod
    validate:
      message: "Root filesystem must be read-only"
      foreach:
        - list: "request.object.spec.containers"
          deny:
            conditions:
              - key: "{{ element.securityContext.readOnlyRootFilesystem }}"
                operator: NotEquals
                value: true
```

### Связанные темы

- [Типы правил](./rules.md) — детальное описание типов правил
- [Практические сценарии](./scenarios.md) — реальные случаи использования
- [Отчеты](./reports.md) — мониторинг применения политик
- [Background Scans](./background.md) — фоновое сканирование
