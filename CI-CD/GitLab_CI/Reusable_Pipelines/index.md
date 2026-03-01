# Переиспользуемые пайплайны GitLab CI

Модульные, переиспользуемые конфигурации GitLab CI — от простых шаблонов до версионируемых компонентов каталога.

## Навигация

### Основные документы

| Документ | Описание |
| :--- | :--- |
| **[Обзор](./overview.md)** | Сравнение всех подходов, рекомендации по выбору, принципы слияния |
| **[Механизм `extends`](./extends_keyword.md)** | Наследование конфигураций, множественное наследование, слияние ключей |
| **[Механизм `include`](./include_keyword.md)** | Все типы include, версионирование, условное включение |
| **[`!reference` и YAML Anchors](./reference_and_yaml_anchors.md)** | Вставка фрагментов, сравнение механизмов |
| **[CI/CD Catalog Components](./ci_cd_catalog_components.md)** | Создание компонентов, `spec:inputs`, публикация в каталог |
| **[Эволюция пайплайнов](./evolution_example.md)** | Практический пример: от дублирования к компонентам |

### Быстрый выбор подхода

| Потребность | Документ |
| :--- | :--- |
| Убрать дублирование в одном файле | [`extends`](./extends_keyword.md) |
| Вставить общий скрипт | [`!reference`](./reference_and_yaml_anchors.md) |
| Разделить на файлы | [`include`](./include_keyword.md) |
| Шаринг между проектами | [`include:project`](./include_keyword.md) |
| Публичная библиотека | [Components](./ci_cd_catalog_components.md) |

## Связанные разделы

- **[GitLab CI Basics](../Concepts/gitlab_ci_basics.md)** — основы GitLab CI
- **[Переменные и секреты](../Concepts/gitlab_ci_variables_secrets.md)** — управление переменными
- **[Кэширование](../Advanced/gitlab_ci_caching.md)** — ускорение сборок
- **[GitLab Flow](../Tutorials/gitlab_flow.md)** — стратегия ветвления

## Внешние ресурсы

- [Официальная документация: YAML Syntax](https://docs.gitlab.com/ci/yaml/)
- [Официальная документация: CI/CD Components](https://docs.gitlab.com/ci/components/)
- [Best Practices: 10+ антипаттернов](https://dev.to/zenika/gitlab-ci-10-best-practices-to-avoid-widespread-anti-patterns-2mb5)
