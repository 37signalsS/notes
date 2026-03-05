# Политики Kyverno: Определения и базовые концепции

## Определения

**Политика (Policy)** — набор правил Kyverno, объединенных общей целью. Определяет какие ресурсы проверять/изменять и какие действия применять.

**Типы политик**:

- **Policy** — namespace-scoped, применяется к ресурсам в конкретном namespace
- **ClusterPolicy** — cluster-scoped, применяется ко всему кластеру

> **Основное руководство:** Это основной файл по написанию политик. [Типы правил](./rules.md) описывают детали правил.

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

## Ссылки

- [Практические сценарии](./practical_scenarios.md) — примеры политик
- [Дополнительная информация](./advanced_topics.md) — операторы, переменные, важные замечания
