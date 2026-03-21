# Продвинутые темы Helm

## Определения

Базовые определения Helm описаны в [обзорном документе](../helm_overview.md).

**Продвинутые темы** — создание репозиториев, адаптивные шаблоны, интеграция с Kustomize, безопасность и best practices.

---

## Файлы

| Файл | Описание |
|------|----------|
| [scenarios.md](./scenarios.md) | Создание репозитория, гибридное использование с Kustomize, адаптивные шаблоны |
| [patterns_troubleshooting.md](./patterns_troubleshooting.md) | Частые проблемы и паттерны их решения |
| [security_best_practices.md](./security_best_practices.md) | Безопасность и best practices |

---

## Additional Information

### Инструменты для оркестрации

Для декларативного управления множеством Helm-релизов (Infrastructure as Code) используются специализированные инструменты:

- **[Helmfile](../helmfile_overview.md)**: Популярный оркестратор, использующий `helmfile.yaml` для описания желаемого состояния релизов.
- **[Helmwave](../helmwave_overview.md)**: Более гибкая альтернатива, которая использует Go-шаблоны для всей конфигурации, обеспечивая максимальную динамичность.

### Плагины

Функциональность Helm расширяется с помощью плагинов. Один из самых востребованных — **[helm-diff](../helm_plugins.md#helm-diff)**, который позволяет просматривать изменения (`diff`) перед применением обновления.

### Связанные темы

- [Helm Overview](../helm_overview.md) — базовые концепции Helm
- [Helm Commands](../helm_commands_and_workflow.md) — руководство по командам
- [Kustomize](../../kustomize/kustomize_overview.md) — управление конфигурацией через патчи
