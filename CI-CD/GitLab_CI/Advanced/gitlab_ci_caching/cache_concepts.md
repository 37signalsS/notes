# Артефакты и кэш в GitLab CI

> **Примечание:** Этот файл был декомпозирован на тематические заметки. Актуальная информация находится в директории **[gitlab_ci_caching/](./gitlab_ci_caching/)**.

## Навигация

- **[gitlab_ci_caching/caching_overview.md](./gitlab_ci_caching/caching_overview.md)** — определения, кэш vs. артефакты
- **[gitlab_ci_caching/artifacts.md](./gitlab_ci_caching/artifacts.md)** — конфигурация артефактов, передача между задачами
- **[gitlab_ci_caching/cache_keys.md](./gitlab_ci_caching/cache_keys.md)** — ключи кэша, политики, fallback
- **[gitlab_ci_caching/cache_best_practices.md](./gitlab_ci_caching/cache_best_practices.md)** — лучшие практики, troubleshooting

## Краткое описание

**Кэширование в GitLab CI** — механизм сохранения файлов между запусками пайплайнов для ускорения сборок.

**Артефакты в GitLab CI** — файлы, сохраняемые после выполнения задач для передачи между стадиями пайплайна.

**Ключевые отличия:**

| Признак | Кэш | Артефакты |
| :--- | :--- | :--- |
| **Назначение** | Ускорение задач | Передача результатов |
| **Гарантия** | Не гарантируется | Гарантируются |
| **Хранение** | Локально на Runner | На сервере GitLab |

## Связанные документы

- **[Основы GitLab CI](../../Concepts/gitlab_ci_basics.md)** — базовые концепции
- **[Артефакты и управление релизами](../../../artifact_management.md)** — общая теория
