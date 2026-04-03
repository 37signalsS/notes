# Политики Kyverno: Определения и базовые концепции

## Определения

**Политика (Policy)** — набор правил Kyverno, объединенных общей целью. Определяет какие ресурсы проверять/изменять и какие действия применять.

**Типы политик**:

- **Policy** — namespace-scoped, применяется к ресурсам в конкретном namespace
- **ClusterPolicy** — cluster-scoped, применяется ко всему кластеру

> **Основное руководство:** Это основной файл по структуре политик. [Типы правил](../rules.md) описывают детали правил и match/exclude условия.

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

### Поля metadata.annotations

| Аннотация | Описание | Пример |
|-----------|----------|--------|
| `policies.kyverno.io/title` | Отображаемое имя политики | `Require Non-Root User` |
| `policies.kyverno.io/category` | Категория (группировка) | `security`, `best-practices` |
| `policies.kyverno.io/severity` | Критичность нарушения | `low`, `medium`, `high`, `critical` |
| `policies.kyverno.io/description` | Подробное описание | Текст с описанием цели политики |

### Поля spec

| Поле | Тип | Описание |
|------|-----|----------|
| `validationFailureAction` | `Enforce` / `Audit` | Действие при нарушении (`Enforce` — блокировать, `Audit` — только отчёт) |
| `background` | `true` / `false` | Фоновое сканирование существующих ресурсов (по умолчанию `true`) |
| `rules` | array | Набор правил (минимум одно) |
| `failurePolicy` | `Fail` / `Ignore` | Действие при ошибке webhook (по умолчанию `Fail`) |

### Разница между Enforce и Audit

| Режим | Поведение | Когда использовать |
|-------|-----------|-------------------|
| `Enforce` | Блокирует создание/обновление ресурса при нарушении | Продакшен, после отладки |
| `Audit` | Только генерирует отчёт, ресурс создаётся | Отладка политик, аудит существующих ресурсов |

### Match и Exclude

Условия применения правил подробно описаны в разделе [Типы правил](../rules.md#match-и-exclude). Ключевые параметры: `any`/`all` (логическое объединение), `kinds` (типы ресурсов), `namespaces`, `names` (поддерживает wildcard `*`), `operations` (CREATE, UPDATE, DELETE, CONNECT).

---

## Practical Scenarios

### Минимальная политика

```yaml
apiVersion: kyverno.io/v1
kind: ClusterPolicy
metadata:
  name: minimal-policy
spec:
  validationFailureAction: Enforce
  rules:
    - name: require-label
      match:
        resources:
          kinds:
            - Pod
      validate:
        message: "Label 'app' is required"
        pattern:
          metadata:
            labels:
              app: "?*"
```

### Политика с background: false

```yaml
apiVersion: kyverno.io/v1
kind: ClusterPolicy
metadata:
  name: enforce-only-new
spec:
  validationFailureAction: Enforce
  background: false  # Не сканировать существующие ресурсы
  rules:
    - name: require-label
      match:
        resources:
          kinds:
            - Pod
      validate:
        message: "Label 'app' is required"
        pattern:
          metadata:
            labels:
              app: "?*"
```

**Когда использовать `background: false`:**
- Политики применяются только к новым ресурсам
- Не нужны отчёты для существующих ресурсов
- Экономия ресурсов кластера

### Политика с failurePolicy: Ignore

```yaml
apiVersion: kyverno.io/v1
kind: ClusterPolicy
metadata:
  name: soft-enforce
spec:
  validationFailureAction: Enforce
  failurePolicy: Ignore  # При ошибке webhook — пропустить запрос
  rules:
    - name: require-label
      match:
        resources:
          kinds:
            - Pod
      validate:
        message: "Label 'app' is required"
        pattern:
          metadata:
            labels:
              app: "?*"
```

**Когда использовать `failurePolicy: Ignore`:**
- Критичные workloads, которые не должны блокироваться при сбое Kyverno
- Риск: нарушение может пройти при недоступности webhook

---

## Additional Information

### Жизненный цикл политики

1. **Создание** — политика применяется к кластеру
2. **Background scan** — существующие ресурсы проверяются, генерируются отчёты
3. **Admission** — новые/обновлённые ресурсы проверяются в реальном времени
4. **Отчёты** — результаты записываются в [Policy Reports](../reports.md)
5. **Enforce** — при нарушении и режиме `Enforce` ресурс блокируется

### Связанные темы

- [Типы правил](../rules.md) — типы правил, match/exclude, операторы условий
- [Практические сценарии](./practical_scenarios.md) — примеры политик
- [Расширенные возможности](./advanced_topics.md) — переменные, foreach, JMESPath
- [Background Scans](../background.md) — фоновое сканирование
- [Отчеты](../reports.md) — мониторинг применения политик
