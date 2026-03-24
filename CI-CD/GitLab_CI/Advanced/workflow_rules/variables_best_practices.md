# Переменные и Best Practices

## Определения

**Встроенные переменные CI/CD** — предопределённые переменные, автоматически предоставляемые GitLab в каждом пайплайне. Используются для управления потоком работ и доступа к метаданным.

## Основные концепции

**Ключевые переменные для workflow:**

| Переменная | Описание | Пример |
| :--- | :--- | :--- |
| `$CI_PIPELINE_SOURCE` | Источник запуска | `push`, `merge_request_event`, `schedule`, `api`, `web` |
| `$CI_COMMIT_BRANCH` | Ветка коммита | `main`, `feature/my-feature` |
| `$CI_MERGE_REQUEST_TARGET_BRANCH_NAME` | Целевая ветка MR | `main`, `develop` |
| `$CI_COMMIT_TAG` | Тег | `v1.2.3` |
| `$CI_OPEN_MERGE_REQUESTS` | Открытые MR | `group/project!123` |
| `$CI_COMMIT_REF_PROTECTED` | Защищённая ветка | `true`, `false` |
| `$CI_DEFAULT_BRANCH` | Default branch | `main`, `master` |

Полный список: [Predefined variables](https://docs.gitlab.com/ee/ci/variables/predefined_variables.html).

## Практические сценарии

**Используйте `workflow:rules` вместо `only/except`:** `only/except` устарели, `rules` более гибкие.

**Порядок правил важен:** специфичные правила размещайте перед общими, завершайте `workflow:rules` с `when: never`.

**Избегайте дублирования:** если `workflow:rules` фильтрует пайплайны, не дублируйте правила в `job:rules`.

**`changes` для монорепозиториев:** запускайте тесты только для изменённых компонентов.

**DAG с `needs`:** разбивайте последовательности, запускайте независимые задачи параллельно.

**`resource_group` для production:** предотвращает гонки состояний при деплое.

**Матрицы для тестирования:** используйте `parallel:matrix` для множественных версий/окружений.

**Pipeline inputs (GitLab 17+):** используйте `spec.inputs` для валидации параметров вместо переменных.

**OIDC-аутентификация:** используйте `CI_JOB_JWT_TOKEN` для аутентификации в AWS, GCP, Azure вместо долгоживущих токенов. Подробнее: [Workload Identity Federation](https://docs.gitlab.com/ee/ci/secrets/authenticate_with_oidc.html).

**Компоненты GitLab (GitLab 17+):** переиспользуемые блоки конфигурации с типизированными входами. Подробнее: [GitLab CI/CD Components](https://docs.gitlab.com/ee/ci/components/).
