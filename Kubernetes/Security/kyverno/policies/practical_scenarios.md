# Политики Kyverno: Практические сценарии

## Определения

**Полный пример политики** — готовый к применению манифест `ClusterPolicy` или `Policy` с заполненными `metadata`, `spec` и `rules`.

**Типы правил в политиках:** `validate` (валидация), `mutate` (мутация), `generate` (генерация), `verifyImages` (проверка подписей). Подробное описание каждого типа — в [Типы правил](../rules.md).

> **Основное руководство:** Это основной файл с полными примерами готовых политик. [Типы правил](../rules.md) описывают детали каждого типа правил и якоря.

---

## Basic Concepts

### Структура полного примера

Каждый пример содержит:

- `apiVersion: kyverno.io/v1` — версия API
- `kind: ClusterPolicy` или `Policy` — область применения
- `metadata.annotations` — аннотации для категоризации ([подробнее](./definitions_and_concepts.md))
- `spec.validationFailureAction` — режим применения (`Enforce`/`Audit`)
- `spec.background` — фоновое сканирование (`true`/`false`)
- `spec.rules` — массив правил

### Когда использовать ClusterPolicy vs Policy

| Критерий | ClusterPolicy | Policy |
|----------|---------------|--------|
| Область | Весь кластер | Один namespace |
| Права | Требуются cluster-wide | Только namespace |
| Когда | Глобальные стандарты безопасности | Namespace-specific правила |

---

## Practical Scenarios

### Требование non-root пользователя

Требует обязательного наличия `securityContext` с `runAsUser > 0` и `runAsGroup > 0`:

```yaml
apiVersion: kyverno.io/v1
kind: ClusterPolicy
metadata:
  name: require-run-as-non-root
  annotations:
    policies.kyverno.io/title: Require Non-Root User
    policies.kyverno.io/category: Security
    policies.kyverno.io/severity: high
    policies.kyverno.io/description: "Containers must run as non-root user to reduce attack surface."
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

---

### Запрет HostPath

Запрещает использование `hostPath` volumes:

```yaml
apiVersion: kyverno.io/v1
kind: ClusterPolicy
metadata:
  name: deny-host-path
  annotations:
    policies.kyverno.io/title: Deny HostPath Volumes
    policies.kyverno.io/category: Security
    policies.kyverno.io/severity: high
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

---

### Требование limits ресурсов

```yaml
apiVersion: kyverno.io/v1
kind: ClusterPolicy
metadata:
  name: require-resource-limits
  annotations:
    policies.kyverno.io/title: Require Resource Limits
    policies.kyverno.io/category: Best Practices
    policies.kyverno.io/severity: medium
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

---

### Запрет privileged контейнеров

```yaml
apiVersion: kyverno.io/v1
kind: ClusterPolicy
metadata:
  name: deny-privileged-containers
  annotations:
    policies.kyverno.io/title: Deny Privileged Containers
    policies.kyverno.io/category: Security
    policies.kyverno.io/severity: high
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

---

### Мутация: Добавление securityContext

Автоматически добавляет `securityContext` для всех Pod:

```yaml
apiVersion: kyverno.io/v1
kind: ClusterPolicy
metadata:
  name: add-security-context
  annotations:
    policies.kyverno.io/title: Add Default Security Context
    policies.kyverno.io/category: Security
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

---

### Генерация: Копирование Secret

Копирует Secret из namespace `template` во все новые namespaces:

```yaml
apiVersion: kyverno.io/v1
kind: ClusterPolicy
metadata:
  name: copy-docker-registry-secret
  annotations:
    policies.kyverno.io/title: Copy Docker Registry Secret
    policies.kyverno.io/category: Operations
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

### Исключение системных namespaces

Политика с исключением для системных namespaces:

```yaml
apiVersion: kyverno.io/v1
kind: ClusterPolicy
metadata:
  name: require-labels-with-exclusions
spec:
  validationFailureAction: Enforce
  background: true
  rules:
    - name: require-app-label
      match:
        resources:
          kinds:
            - Pod
      exclude:
        resources:
          namespaces:
            - kube-system
            - kube-public
            - kyverno
      validate:
        message: "Label 'app' is required"
        pattern:
          metadata:
            labels:
              app: "?*"
```

---

## Additional Information

### Рекомендации по написанию политик

| Практика | Описание |
|----------|----------|
| Начинайте с `Audit` | Тестируйте политику в режиме аудита перед переходом в `Enforce` |
| Используйте `background: true` | Для аудита существующих ресурсов |
| Аннотируйте политики | `title`, `category`, `severity`, `description` для отслеживания |
| Исключайте системные ns | `kube-system`, `kyverno`, `kube-public` |
| Проверяйте отчёты | [Policy Reports](../reports.md) для мониторинга |

### Связанные темы

- [Определения и концепции](./definitions_and_concepts.md) — структура политик, поля spec
- [Типы правил](../rules.md) — типы правил, match/exclude, якоря, операторы
- [Расширенные возможности](./advanced_topics.md) — переменные, foreach, JMESPath
- [Background Scans](../background.md) — фоновое сканирование
- [Отчеты](../reports.md) — мониторинг применения политик
