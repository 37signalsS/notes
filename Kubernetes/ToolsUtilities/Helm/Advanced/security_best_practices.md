# Безопасность и best practices Helm

## Определения

**Безопасность Helm** — практики защиты секретов, валидации чартов и ограничения прав доступа.

**Best Practices** — рекомендации по структуре чартов, шаблонам и CI/CD.

## Базовые концепции

### Области применения

Безопасность и best practices Helm охватывают:

1. **Защита секретов** — шифрование, внешние хранилища, передача через CI/CD
2. **Валидация чартов** — статический анализ, policy-as-code, проверка манифестов
3. **Ограничение прав** — RBAC, изоляция namespace, управление историей релизов
4. **Структура чарта** — семантическое версионирование, документирование параметров
5. **CI/CD интеграция** — атомарные обновления, откаты, diff-проверки

### Инструменты

- `helm lint` — статический анализ чарта
- `helm template` — рендеринг для проверки манифестов
- `helm diff` — сравнение текущей и целевой версии релиза
- `kubeconform` — валидация Kubernetes-манифестов
- `conftest` — policy-as-code через OPA/Rego

> **Навигация:** [Главная Advanced](./index.md) | [Сценарии](./scenarios.md) | [Паттерны](./patterns_troubleshooting.md)

---

## Практические сценарии

### Безопасность

#### Секреты

- Не храните секреты в `values.yaml` в открытом виде
- Используйте [helm-secrets](https://github.com/jkroepke/helm-secrets) или external secrets operator
- Для CI/CD передавайте секреты через переменные окружения

#### Валидация

```bash
# Линтинг чарта
helm lint ./chart

# Проверка манифестов
helm template ./chart | kubeconform -strict

# Проверка с policy-as-code
helm install --dry-run ./chart | conftest test -
```

#### Ограничение прав

- Используйте RBAC для ограничения прав Helm в кластере
- Применяйте `--namespace` для изоляции релизов
- Ограничивайте историю через `--history-max 10`

---

### Best Practices

#### Структура чарта

- Следуйте SemVer для `version` в Chart.yaml
- Используйте `Chart.lock` для фиксации зависимостей
- Разделяйте values по окружениям (`values-dev.yaml`, `values-prod.yaml`)
- Документируйте параметры в `values.yaml` через комментарии

#### Шаблоны

- Используйте именованные шаблоны для имён и меток
- Применяйте `required` для обязательных параметров
- Избегайте сложной логики в шаблонах
- Тестируйте шаблоны через `helm template`

#### CI/CD

- Используйте `helm diff` перед обновлением production
- Применяйте `--atomic` для автоматического отката
- Для управления множеством релизов — [Helmfile](../helmfile_overview.md) или [Helmwave](../helmwave_overview.md)

---

## Дополнительная информация

### Связанные темы

- [Helm Overview](../helm_overview.md) — базовые концепции Helm
- [Helm Commands](../helm_commands_and_workflow.md) — руководство по командам
- [Helmfile](../helmfile_overview.md) — декларативный оркестратор
- [Helmwave](../helmwave_overview.md) — альтернатива Helmfile
