# Продвинутые рабочие процессы GitLab CI/CD

## Определения

Данный документ содержит обзор продвинутых возможностей GitLab CI/CD для управления пайплайнами. Подробные темы вынесены в отдельные файлы.

## Основные концепции → Тематические заметки

### Стратегии запуска

- **[Определения директив](./workflow_rules/directives_definitions.md)** — ключевые директивы: `workflow:rules`, `rules`, `needs`, `parallel:matrix`, `resource_group`
- **[workflow:rules и pipeline inputs](./workflow_rules/pipeline_inputs.md)** — управление запуском пайплайнов, избежание дублирования, auto-cancel, динамические переменные, типизированные параметры (GitLab 17+)

### Управление задачами

- **[Правила запуска задач](./workflow_rules/job_rules.md)** — условный запуск задач, `changes` для монорепозиториев, комбинированные правила, pipeline schedules

### Зависимости и производительность

- **[DAG с needs](./workflow_rules/dag_with_needs.md)** — направленный ациклический граф, ускорение пайплайнов, Complex DAG, `resource_group` для сериализации деплоев

### Матричные сборки

- **[Матричные сборки и сериализация](./workflow_rules/practical_scenarios.md)** — `parallel:matrix` для разных версий/окружений, защита production от гонок состояний

### Переменные и рекомендации

- **[Переменные и Best Practices](./workflow_rules/variables_best_practices.md)** — встроенные переменные CI/CD, рекомендации по использованию (2025-2026), OIDC-аутентификация, компоненты GitLab

## Связанные документы

- **[Основы GitLab CI/CD](../Concepts/gitlab_ci_basics.md)** — базовые концепции Pipeline, Stage, Job
- **[Кэширование в GitLab CI](./gitlab_ci_caching.md)** — оптимизация скорости пайплайнов
- **[Исполнители (Runners)](./gitlab_ci_runners_executors.md)** — настройка сред выполнения
- **[Дочерние пайплайны](./gitlab_ci_downstream_pipelines.md)** — декомпозиция сложных пайплайнов
- **[Валидация и версионирование](./pipeline_validation_and_versioning.md)** — проверка конфигурации
