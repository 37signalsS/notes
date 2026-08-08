# Политики Kyverno: Определения и структура

## Определения

**Политика (Policy)** — основной декларативный манифест Kyverno, определяющий правила контроля, изменения или генерации ресурсов в Kubernetes. Реализует подход **Policy-as-Code**, позволяя описывать требования безопасности и операционные стандарты в YAML/CEL.

### Классификация ресурсов

В актуальных версиях Kyverno (2025–2026) сосуществуют два архитектурных подхода:

1.  **Классические политики (v1)**:
    *   **ClusterPolicy (cpol)**: Глобальный ресурс, применяемый ко всему кластеру. Поддерживает все типы правил (validate, mutate, generate, verifyImages).
    *   **Policy (pol)**: Локальный ресурс, действующий только в рамках одного Namespace.
2.  **Модульные CEL-политики (v2)**:
    *   **ValidatingPolicy / MutatingPolicy**: Узкоспециализированные ресурсы, ориентированные на максимальную производительность. Они транслируются в нативные `ValidatingAdmissionPolicies` Kubernetes, что исключает сетевые задержки на вызов внешнего вебхука.

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

---

## Практические сценарии

### 1. Безопасное внедрение через Audit Mode

Для минимизации влияния на работающие системы используйте цепочку `Audit` → `Analysis` → `Enforce`.

```yaml
spec:
  validationFailureAction: Audit
  background: true # Обязательно для сканирования уже запущенных подов
  rules:
    - name: check-resource-limits
      # ... логика проверки ...
```
*Результаты сканирования будут доступны в `kubectl get polr -A`.*

### 2. Использование нативных CEL-политик (v2)

Для простых проверок (например, валидация полей Pod) используйте модульные ресурсы для экономии ресурсов CPU/RAM.

```yaml
apiVersion: policies.kyverno.io/v1
kind: ValidatingPolicy
metadata:
  name: check-run-as-non-root
spec:
  validationActions: [Deny]
  validations:
    - expression: "object.spec.securityContext.runAsNonRoot == true"
      message: "Запуск от root запрещен."
```

---

## Дополнительная информация

### Жизненный цикл обработки Admission Request

Процесс обработки запроса в Kyverno строго детерминирован:

1.  **Mutating Webhook (Синхронно)**:
    *   Применяются правила `mutate`.
    *   Если манифест изменен, он возвращается в API-сервер для повторной валидации.
2.  **Validating Webhook (Синхронно)**:
    *   Проверка правил `validate` и `verifyImages`.
    *   Если `validationFailureAction: Enforce`, запрос отклоняется с кодом 403.
3.  **Persistence**: Ресурс сохраняется в `etcd`.
4.  **Background Activity (Асинхронно)**:
    *   Запускаются правила `generate`.
    *   Формируются `PolicyReport`.
    *   **Update Requests (UR)**: Создаются для отслеживания статуса генерации.

### См. также

- **[Типы правил (подробно)](../rules.md)** — основы синтаксиса mutate, validate, generate.
- **[Библиотека практических примеров](./practical_scenarios.md)** — CEL и классические сценарии.
- **[Фоновое сканирование](../background.md)** — нюансы аудита существующих ресурсов.
- **[Отчеты и мониторинг](../reports.md)** — работа с Policy Reports.
