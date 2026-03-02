# Переменные и Best Practices

## Встроенные переменные CI/CD

Ключевые переменные для управления потоком работ:

| Переменная | Описание | Пример значения |
| :--- | :--- | :--- |
| `$CI_PIPELINE_SOURCE` | Источник запуска | `push`, `merge_request_event`, `schedule`, `api`, `web` |
| `$CI_COMMIT_BRANCH` | Ветка коммита | `main`, `feature/my-feature` |
| `$CI_MERGE_REQUEST_TARGET_BRANCH_NAME` | Целевая ветка MR | `main`, `develop` |
| `$CI_COMMIT_TAG` | Тег (если есть) | `v1.2.3` |
| `$CI_OPEN_MERGE_REQUESTS` | Открытые MR | `group/project!123` |
| `$CI_COMMIT_REF_PROTECTED` | Защищённая ветка | `true`, `false` |
| `$CI_DEFAULT_BRANCH` | Default branch | `main`, `master` |

Полный список: [Predefined variables](https://docs.gitlab.com/ee/ci/variables/predefined_variables.html)

## Best Practices (2025-2026)

1. **Используйте `workflow:rules` вместо `only/except`**
   - `only/except` устарели и не рекомендуются
   - `rules` более гибкие и мощные

2. **Порядок правил важен**
   - Размещайте специфичные правила перед общими
   - Завершайте `workflow:rules` с `when: never` для отклонения лишних

3. **Избегайте дублирования правил**
   - Если `workflow:rules` уже фильтрует пайплайны, не дублируйте в `job:rules`

4. **Используйте `changes` для монорепозиториев**
   - Запускайте тесты только для изменённых компонентов
   - Экономит ресурсы и время

5. **DAG с `needs` для ускорения**
   - Разбивайте длинные последовательности
   - Запускайте независимые задачи параллельно

6. **`resource_group` для production**
   - Всегда используйте для критичных деплоев
   - Предотвращает гонки состояний

7. **Матрицы для тестирования**
   - Используйте для множественных версий/окружений
   - Избегайте дублирования задач

8. **Pipeline inputs для типизированных параметров (GitLab 17+)**
   - Используйте `spec.inputs` вместо переменных для валидации
   - Особенно полезно для компонентов и переиспользуемых пайплайнов

9. **OIDC-аутентификация для внешних сервисов**
   - Используйте `CI_JOB_JWT_TOKEN` для аутентификации в AWS, GCP, Azure
   - Заменяет долгоживущие токены на временные
   - См. [Workload Identity Federation](https://docs.gitlab.com/ee/ci/secrets/authenticate_with_oidc.html)

10. **Компоненты GitLab CI/CD (GitLab 17+)**
    - Переиспользуемые блоки конфигурации с типизированными входами
    - Централизованное управление шаблонами
    - См. [GitLab CI/CD Components](https://docs.gitlab.com/ee/ci/components/)

## Связанные документы

- **[Определения директив](./directives_definitions.md)** — ключевые директивы
- **[workflow:rules и pipeline inputs](./pipeline_inputs.md)** — управление пайплайнами
- **[Основы GitLab CI/CD](../Concepts/gitlab_ci_basics.md)** — базовые концепции
- **[Кэширование в GitLab CI](../gitlab_ci_caching.md)** — оптимизация скорости пайплайнов
- **[Исполнители (Runners)](../gitlab_ci_runners_executors.md)** — настройка сред выполнения
