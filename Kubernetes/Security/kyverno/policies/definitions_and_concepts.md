# Политики Kyverno: Определения и структура

## Определения

**Политика (Policy)** — декларативный манифест, описывающий набор правил для автоматизации контроля, изменения или создания ресурсов в кластере Kubernetes. В экосистеме Kyverno политики являются основным инструментом реализации концепции «Политики как код» (Policy as Code).

### Типы ресурсов по области действия

| Тип ресурса | Область действия | Описание |
| :--- | :--- | :--- |
| **ClusterPolicy** | Весь кластер | Глобальный ресурс, применяемый ко всем пространствам имен. |
| **Policy** | Пространство имен | Локальный ресурс, действующий только внутри конкретного Namespace. |

### Специализированные типы (v1.14+)

Начиная с версий 2024–2025 гг., Kyverno внедряет модульные CEL-политики (Common Expression Language), которые работают быстрее за счет нативной интеграции с Kubernetes API:
*   **ValidatingPolicy**: Ориентирована исключительно на валидацию ресурсов через CEL.
*   **MutatingPolicy**: Предназначена для мутации ресурсов на основе CEL.

---

## Основные концепции

### Структура манифеста политики

Политики описываются в формате YAML и состоят из метаданных и спецификации (`spec`), включающей одно или несколько правил.

```yaml
apiVersion: kyverno.io/v1
kind: ClusterPolicy
metadata:
  name: check-security-labels
  annotations:
    policies.kyverno.io/title: "Обязательные метки безопасности"
    policies.kyverno.io/category: "Security"
    policies.kyverno.io/severity: "Medium"
spec:
  # Режим: Enforce (блокировка) или Audit (только отчет)
  validationFailureAction: Enforce
  # Фоновое сканирование существующих ресурсов
  background: true
  # Действие при недоступности вебхука: Fail или Ignore
  failurePolicy: Fail
  rules:
    - name: check-team-label
      match:
        any:
          - resources:
              kinds:
                - Pod
      validate:
        message: "Метка 'team' обязательна для всех подов."
        pattern:
          metadata:
            labels:
              team: "?*"
```

### Ключевые параметры спецификации

*   **`validationFailureAction`**: Определяет поведение при нарушении.
    *   `Audit`: Пропускает ресурс, фиксируя нарушение в `PolicyReport`. Рекомендуется для тестирования новых политик.
    *   `Enforce`: Блокирует запрос на создание или изменение ресурса.
*   **`background`**: (по умолчанию `true`) — включает периодическое сканирование уже запущенных объектов для формирования отчетов.
*   **`failurePolicy`**: Определяет поведение API-сервера, если контроллер Kyverno недоступен.
    *   `Fail`: Запросы к ресурсам будут блокироваться.
    *   `Ignore`: Запросы будут разрешены без проверки.
*   **`validationFailureActionOverrides`**: Позволяет задать разные режимы для Admission-контроля и фонового сканирования (например, блокировать новые поды, но только логировать нарушения в старых).

---

## Практические сценарии

### 1. Безопасное внедрение политики (Audit → Enforce)

При внедрении новой политики на живой кластер важно сначала оценить её влияние через режим аудита.

```yaml
apiVersion: kyverno.io/v1
kind: ClusterPolicy
metadata:
  name: audit-resource-limits
spec:
  # Сначала используем Audit, чтобы увидеть нарушения в отчетах
  validationFailureAction: Audit
  background: true
  rules:
    - name: check-memory-limits
      match:
        resources:
          kinds:
            - Pod
      validate:
        message: "Лимиты памяти обязательна."
        pattern:
          spec:
            containers:
              - resources:
                  limits:
                    memory: "?*"
```

### 2. Исключение критических сервисов (failurePolicy: Ignore)

Для предотвращения блокировки кластера при сбоях в работе самого Kyverno (например, невозможности развернуть системные компоненты), используйте `failurePolicy: Ignore`.

```yaml
spec:
  validationFailureAction: Enforce
  failurePolicy: Ignore # Кластер продолжит работу, даже если Kyverno упадет
  rules:
    - name: check-readiness-probe
      # ... логика проверки ...
```

---

## Дополнительная информация

### Жизненный цикл обработки запроса

1.  **Admission Request**: API-сервер Kubernetes получает запрос и направляет его в мутирующий вебхук Kyverno.
2.  **Mutation**: Применяются правила `mutate`. Если ресурс изменен, он передается дальше.
3.  **Validation**: Применяются правила `validate` и `verifyImages`. В режиме `Enforce` нарушение прерывает цепочку.
4.  **Generation**: После сохранения ресурса в `etcd` срабатывают правила `generate` (выполняются асинхронно).
5.  **Reporting**: Информация о результатах записывается в `PolicyReport` (для Namespace-ресурсов) или `ClusterPolicyReport` (для кластерных).

### См. также

- **[Типы правил (validate, mutate, generate)](../rules.md)** — глубокое погружение в синтаксис.
- **[Фоновое сканирование](../background.md)** — особенности анализа существующих ресурсов.
- **[Отчеты и мониторинг](../reports.md)** — как работать с Policy Reports.
- **[CEL в Kyverno](https://kyverno.io/docs/writing-policies/cel/)** — официальное руководство по новому движку политик.
