# Политики Kyverno: Дополнительная информация

## Важные замечания

1. **Background scan не применяется к существующим ресурсам** — политика срабатывает только при CREATE/UPDATE ([подробнее](./background.md))
2. По умолчанию примеры политик в документации используют `validationFailureAction: audit`
3. Для полной защиты необходимо переключить на `validationFailureAction: Enforce`
4. Политики применяются к **Pod** — Kyverno проверяет итоговый Pod, сгенерированный из Deployment/StatefulSet/DaemonSet

---

## Операторы условий

| Оператор | Описание | Пример |
|----------|----------|--------|
| `AnyIn` / `AnyNotIn` | Проверка элемента массива на вхождение/невхождение | `AnyNotIn: ["value1", "value2"]` |
| `AllIn` / `AllNotIn` | Проверка всех элементов массива | `AllIn: ["value1", "value2"]` |
| `Equal` / `NotEqual` | Равенство / неравенство | `Equal: "value"` |
| `GreaterThanOrEquals` / `LessThanOrEquals` | Числовые сравнения | `GreaterThanOrEquals: 100` |
| `PatternMatch` | Проверка по regex-шаблону | `PatternMatch: "^prod-*"` |
| `In` / `NotIn` | Проверка значения в списке | `In: ["value1", "value2"]` |

---

## Переменные в политиках

Kyverno поддерживает подстановку переменных:

| Переменная | Описание |
|------------|----------|
| `{{request.object.metadata.name}}` | Имя ресурса |
| `{{request.object.metadata.namespace}}` | Namespace ресурса |
| `{{request.userInfo.username}}` | Имя пользователя |
| `{{@}}` | Ссылка на текущий элемент в foreach |

---

## Пример с foreach

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

---

## Связанные темы

- [Типы правил](./rules.md) — детальное описание типов правил
- [Практические сценарии](./scenarios.md) — реальные случаи использования
- [Отчеты](./reports.md) — мониторинг применения политик
- [Background Scans](./background.md) — фоновое сканирование

---

## Ссылки на связанные файлы

- [Определения и концепции](./definitions_and_concepts.md) — базовая информация
- [Практические сценарии](./practical_scenarios.md) — примеры политик
