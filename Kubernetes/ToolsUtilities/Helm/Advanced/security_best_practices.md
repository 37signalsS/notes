# Безопасность и best practices Helm

## Определения

**Безопасность Helm** — практики защиты секретов, валидации чартов и ограничения прав доступа.

**Best Practices** — рекомендации по структуре чартов, шаблонам и CI/CD.

> **Навигация:** [Главная Advanced](./index.md) | [Сценарии](./scenarios.md) | [Паттерны](./patterns_troubleshooting.md)

---

## Practical Scenarios

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

## Additional Information

### Связанные темы

- [Helm Overview](../helm_overview.md) — базовые концепции Helm
- [Helm Commands](../helm_commands_and_workflow.md) — руководство по командам
- [Helmfile](../helmfile_overview.md) — декларативный оркестратор
- [Helmwave](../helmwave_overview.md) — альтернатива Helmfile
