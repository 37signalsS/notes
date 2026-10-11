# Path filters и changed files в GitLab CI/CD

**Актуально для:** GitLab 17.x–19.x

## Требования и предварительные условия

### Версия GitLab и поддержка функций

| Функция | Минимальная версия | Примечание |
| :--- | :--- | :--- |
| `workflow:rules` | 12.3+ | Глобальная фильтрация пайплайнов |
| `rules:changes` | 11.4+ | Фильтрация по изменённым файлам |
| `rules:changes:compare_to` (литералы) | 12.3+ | Сравнение с фиксированной веткой |
| `rules:changes:compare_to` (переменные) | 17.2+ | Динамическое сравнение для MR |
| `only:changes` | устарел | Заменён на `rules:changes` |

### Необходимые знания

- Базовый синтаксис `.gitlab-ci.yml` и жизненный цикл пайплайна
- Механизм `rules` и комбинирование `if`/`changes`/`exists` — см. SSoT **[Правила запуска задач](../workflow_rules/job_rules.md#правила-запуска-задач-rules)**
- DAG-модель выполнения и влияние `needs` на порядок запуска — см. **[DAG с needs](../workflow_rules/dag_with_needs.md)**
- Архитектура пайплайнов GitLab (pre-receive hooks, workflow, job) — см. **[Конструктор рабочих процессов](../gitlab_ci_workflow_builder.md)**

### Целевая аудитория

Справочник предназначен для DevOps-инженеров, SRE и системных администраторов, управляющих on-premise и гибридной инфраструктурой GitLab. Примеры ориентированы на оптимизацию времени сборки, предотвращение запуска пайплайнов при нерелевантных изменениях и обеспечение стабильности монорепозиториев.

## Определения

**Changed files (изменённые файлы)** — список файлов, изменённых в рамках коммита/merge request. Используется для определения, нужно ли запускать пайплайн для конкретных изменений.

**rules:changes** — современный механизм фильтрации jobs по изменённым файлам. Поддерживает сложные паттерны и логические выражения. Заменяет устаревший `only:changes`.

**workflow:rules** — глобальные правила запуска всего пайплайна. Позволяют предотвратить запуск пайплайна при нерелевантных изменениях (например, только документация).

**only:changes** — устаревший ключ, фильтрующий запуск job по изменённым файлам. Заменён на `rules:changes` в современных версиях GitLab.

## Основные концепции

### Архитектура фильтрации в GitLab CI/CD

```
Push → Pre-receive hooks (push rules)
  → Commit validation
    → Workflow:rules (весь пайплайн)
      → Job:rules (отдельные jobs)
        → rules:changes (по файлам)
        → rules:if (по веткам/событиям)
```

### Сравнение механизмов фильтрации

| Механизм | Уровень | Тип фильтрации | Когда применяется |
| :--- | :--- | :--- | :--- |
| **workflow:rules** | Pipeline | Всё или ничего | Перед созданием pipeline |
| **rules:changes** | Job | Изменённые файлы | При выборе jobs для запуска |
| **rules:if** | Job | Ветка, событие, переменные | При выборе jobs для запуска |
| **only/except** | Job | Устаревшие фильтры | Legacy, не рекомендуется |

### Changed files: как работает

GitLab сравнивает текущий коммит с предыдущим в рамках MR/push:

| Событие | Сравнение |
| :--- | :--- |
| **Push в ветку** | Текущий коммит vs предыдущий коммит |
| **Merge Request** | Head branch vs Base branch |
| **Merge Train** | Все коммиты в очереди |
| **Tag push** | Текущий tag vs предыдущий tag |

### Changed files: ограничения

| Ограничение | Описание | Workaround |
| :--- | :--- | :--- |
| **Первые коммиты в ветке** | Нет предыдущего коммита для сравнения → `changes` пуст | Добавьте `when: always` fallback |
| **Merge/squash merge** | GitLab не может определить changed files до merge | Используйте `rules:if` вместо `changes` |
| **Подмодули** | Изменения в подмодулях не отслеживаются через `changes` | Используйте `rules:if` с проверкой подмодулей |
| **Большие MR** | > 1000 файлов — `changes` может быть неполным | Разбивайте большие MR |

### only:changes vs rules:changes

| Критерий | only:changes | rules:changes |
| :--- | :--- | :--- |
| **Синтаксис** | Устаревший | Современный |
| **Гибкость** | Ограниченная | Высокая (поддерживает `exists`, `paths`) |
| **Логические выражения** | Нет | Да (`if`, `changes` комбинации) |
| **Рекомендация** | Не использовать | Да |

## Практические сценарии

### Сценарий 1: Запуск только при изменениях в backend

```yaml
workflow:
  rules:
    - if: $CI_PIPELINE_SOURCE == "merge_request_event"
    - if: $CI_COMMIT_BRANCH == "main"

# Запускается только при изменениях в backend/
backend_test:
  stage: test
  script: npm run test:backend
  rules:
    - if: $CI_PIPELINE_SOURCE == "merge_request_event"
      changes:
        - backend/**/*
      when: always
    - if: $CI_COMMIT_BRANCH == "main"
      when: always

# Запускается только при изменениях в frontend/
frontend_test:
  stage: test
  script: npm run test:frontend
  rules:
    - if: $CI_PIPELINE_SOURCE == "merge_request_event"
      changes:
        - frontend/**/*
      when: always
    - if: $CI_COMMIT_BRANCH == "main"
      when: always
```

### Сценарий 2: Path filter для monorepo

```yaml
# Сервис A
service_a:
  stage: test
  script: ./test-service-a.sh
  rules:
    - if: $CI_PIPELINE_SOURCE == "push"
      changes:
        - services/service-a/**/*
        - shared-libs/lib-a/**/*
      when: always
    - when: never

# Сервис B
service_b:
  stage: test
  script: ./test-service-b.sh
  rules:
    - if: $CI_PIPELINE_SOURCE == "push"
      changes:
        - services/service-b/**/*
        - shared-libs/lib-b/**/*
      when: always
    - when: never
```

### Сценарий 3: Запуск при изменении конфигурации

```yaml
# Запуск lint/tests только при изменениях в конфигах
config_lint:
  stage: lint
  script: .gitlab/ci/lint-config.sh
  rules:
    - if: $CI_PIPELINE_SOURCE == "merge_request_event"
      changes:
        - .gitlab-ci.yml
        - "**/*.ci.yml"
        - config/**/*
        - deploy/**/*
      when: always
    - if: $CI_COMMIT_BRANCH == "main"
      when: always

# Запуск деплоя при любых изменениях в main
deploy:
  stage: deploy
  script: ./deploy.sh
  rules:
    - if: $CI_COMMIT_BRANCH == "main"
      when: always
```

### Сценарий 4: Использование workflow:rules для оптимизации

```yaml
# Весь пайплайн пропускается, если изменения только в документации
workflow:
  rules:
    - if: $CI_PIPELINE_SOURCE == "merge_request_event"
      changes:
        - "**/*.md"
        - "**/*.txt"
        - docs/**/*
      when: never  # Пропустить весь пайплайн
    - if: $CI_PIPELINE_SOURCE == "merge_request_event"
    - if: $CI_COMMIT_BRANCH == "main"
```

### Сценарий 5: Миграция с only:changes на rules:changes

```yaml
# Было (only:changes — устаревший)
old_job:
  only:
    refs:
      - merge_requests
    changes:
      - backend/**/*

# Стало (rules:changes — современный)
new_job:
  rules:
    - if: $CI_PIPELINE_SOURCE == "merge_request_event"
      changes:
        - backend/**/*
      when: always
    - if: $CI_COMMIT_BRANCH == "main"
      when: always
```

### Сценарий 6: Performance implications для больших репозиториев

В монорепозиториях с >1000 файлов `changes` может быть неполным или медленным:

```yaml
# Оптимизация: используйте несколько правил с приоритизацией
fast_lint:
  stage: lint
  script: npm run lint
  rules:
    - if: $CI_PIPELINE_SOURCE == "merge_request_event"
      changes:
        - "**/*.ts"
        - "**/*.js"
      when: always
    - when: never

# Для очень больших MR используйте exists вместо changes
config_check:
  stage: lint
  script: .gitlab/ci/check-config.sh
  rules:
    - if: $CI_PIPELINE_SOURCE == "merge_request_event"
      exists:
        - .gitlab-ci.yml
        - config/**/*
      when: always
```

## Валидация и диагностика

### CI Lint и симуляция пайплайна

```bash
# Встроенный линтер в GitLab: CI/CD > Editor > Validate
# Или через API:
curl --header "PRIVATE-TOKEN: $TOKEN" \
  "https://gitlab.example.com/api/v4/projects/$PROJECT_ID/ci/lint" \
  -d '{"content":"$(cat .gitlab-ci.yml)"}'
```

Проверьте:
1. **Simulate pipeline** — показывает, какие jobs запустятся для указанного ветки/тега/MR без реального выполнения.
2. **Empty Pipeline** — если симуляция возвращает пустой пайплайн, проверьте `workflow:rules` на наличие fallback-правила.
3. **`rules:changes` coverage** — убедитесь, что паттерны покрывают lock-файлы и необходимые директории.

### Проверка changed files через git diff

```bash
# Сравнение текущего коммита с предыдущим
git diff --name-only HEAD~1 HEAD

# Для MR: сравнение с целевой веткой
git diff --name-only origin/main...HEAD

# Проверка, попадает ли файл под паттерн
git diff --name-only origin/main...HEAD | grep -E '^backend/.*\.py$'
```

### API: получение списка changed files для pipeline

```bash
# Список коммитов в pipeline
curl --header "PRIVATE-TOKEN: $TOKEN" \
  "https://gitlab.example.com/api/v4/projects/$PROJECT_ID/pipelines/$PIPELINE_ID/commits" | \
  jq '.[].id'

# Сравнение двух коммитов через API
curl --header "PRIVATE-TOKEN: $TOKEN" \
  "https://gitlab.example.com/api/v4/projects/$PROJECT_ID/repository/compare?from=$FROM_REF&to=$TO_REF" | \
  jq '.diffs[].new_path'
```

### Проверка фильтрации jobs через API

```bash
# Получите список jobs пайплайна
curl --header "PRIVATE-TOKEN: $TOKEN" \
  "https://gitlab.example.com/api/v4/projects/$PROJECT_ID/pipelines/$PIPELINE_ID/jobs" | \
  jq '.[].name'
```

### Push rules: серверная валидация

```bash
# Включение push rules через API
curl --header "PRIVATE-TOKEN: $TOKEN" \
  -X PUT \
  "https://gitlab.example.com/api/v4/projects/$PROJECT_ID/push_rule" \
  -d "branch_name_regex=^(main|release/.*)$" \
  -d "commit_message_regex=(feat|fix|chore|docs):"
```

## Устранение неполадок

| Проблема | Возможная причина | Решение |
| :--- | :--- | :--- |
| Pipeline не запускается | `workflow:rules` слишком строгий | Проверьте правила, используйте `when: always` для critical jobs |
| Job не запускается при изменении файлов | `changes` паттерн не совпадает | Проверьте точность пути, используйте `git diff --name-only` |
| Первый коммит в ветке — job не запускается | `changes` пуст для первого коммита | Добавьте fallback правило `when: always` |
| `changes` неполный для больших MR | > 1000 файлов в MR | Разбивайте MR или используйте `exists` |
| Slow pipeline creation | Множество `changes` паттернов | Упростите правила, используйте `workflow:rules` для фильтрации на уровне pipeline |

## Граничные случаи и ограничения

### `rules:changes` и первый коммит в ветке

При создании ветки из `main` первый коммит не имеет предыдущего коммита для сравнения. GitLab возвращает пустой список changed files, и задача с `rules:changes` не запускается. Решение — добавьте fallback-правило `when: always` для критичных задач.

```yaml
rules:
  - if: $CI_PIPELINE_SOURCE == "merge_request_event"
    changes:
      - backend/**/*
    when: always
  - when: always  # Fallback для первого коммита
```

### `rules:changes` и merge/squash merge

GitLab вычисляет changed files до merge. При squash merge или rebase предыдущий коммит может быть потерян, и `changes` работает корректно только если сравнение идёт с базовой веткой MR. Для динамических сценариев используйте `rules:changes:compare_to` с переменной `$CI_MERGE_REQUEST_TARGET_BRANCH_NAME` (GitLab 17.2+).

```yaml
rules:
  - if: $CI_PIPELINE_SOURCE == "merge_request_event"
    changes:
      compare_to: $CI_MERGE_REQUEST_TARGET_BRANCH_NAME
      paths:
        - backend/**/*
    when: always
```

Детали синтаксиса `compare_to` — см. SSoT **[Правила запуска задач](../workflow_rules/job_rules.md)**.

### `rules:changes` и большие MR (>1000 файлов)

GitLab ограничивает объём diff для `changes`. При MR > 1000 файлов список может быть неполным, и задачи не запустятся, хотя изменились релевантные файлы. Решения:
- Разбивайте MR на несколько.
- Используйте `exists` для проверки наличия lock-файлов.
- Фильтруйте на уровне `workflow:rules`, чтобы пайплайн создавался только для релевантных изменений.

### Подмодули и внешние зависимости

Изменения в Git submodules не отражаются в `rules:changes`, так как GitLab сравнивает только файлы в репозитории проекта. Для проверки изменений в подмодулях используйте `rules:if` с проверкой переменной `CI_REPOSITORY_URL` или кастомного скрипта.

### `workflow:rules` и scheduled/tag пайплайны

Если `workflow:rules` не покрывает `schedule` и `tag` источники, пайплайн не создаётся, и задачи с `rules:changes` не запускаются. Добавьте явные условия:

```yaml
workflow:
  rules:
    - if: $CI_PIPELINE_SOURCE == "merge_request_event"
    - if: $CI_COMMIT_BRANCH == "main"
    - if: $CI_PIPELINE_SOURCE == "schedule"
    - if: $CI_PIPELINE_SOURCE == "tag"
```

### `rules:changes` и dotenv/артефакты

Переменные из `artifacts:reports:dotenv` вычисляются после парсинга конфигурации и недоступны в `rules` или `workflow:rules`. Для условного запуска используйте только предопределённые переменные GitLab.

### Empty Pipeline

Если все задачи отфильтрованы через `rules`, GitLab создаёт пустой пайплайн. Частые причины:
- `workflow:rules` не включает источник (ветка, MR, schedule).
- `rules:changes` пуст для первого коммита без fallback.
- Конфликт `rules` задач, исключающий все задачи одновременно.

Решение — проверьте CI Lint и Simulate pipeline.

## Best Practices

### Разработка (Dev)

1. **Используйте `rules:changes` вместо `only:changes`:** Современный синтаксис более гибкий и поддерживается в GitLab 12.3+.
2. **Добавляйте fallback для `changes`:** Первый коммит в ветке — `changes` пуст. Всегда добавляйте `when: always` для critical jobs.
3. **Используйте `workflow:rules` для оптимизации:** Пропускайте лишние пайплайны на уровне workflow, а не jobs.
4. **Избегайте слишком широких паттернов:** `**/*` в `changes` может привести к неожиданному запуску jobs.
5. **Тестируйте правила:** Используйте Pipeline Lint для проверки `rules` перед коммитом.

### Эксплуатация (DevOps/SRE)

1. **Мониторьте длину changed files:** MR > 1000 файлов — `changes` может быть неполным. Разбивайте большие MR.
2. **Аудит workflow:rules:** Регулярно проверяйте, что `workflow:rules` не блокирует критичные пайплайны.
3. **Используйте group-level workflow:rules:** Настройте общие правила для всех проектов в группе.
4. **Тестируйте производительность:** Большое количество `changes` паттернов замедляет создание pipeline.

### Sysadmin

1. **Настройте лимиты для MR:** Ограничьте максимальный размер MR (например, 500 файлов) для стабильности `changes`.
2. **Мониторьте pipeline creation time:** Если создание pipeline занимает >30 секунд — проверьте `rules` на сложность.
3. **Используйте push rules для серверной валидации:** Push rules работают на уровне GitLab Server и не зависят от Runner'ов.

## Дополнительная информация

### См. также

- **[CI/CD Security Hardening](../Advanced/cicd_security_hardening.md)** — защита CI/CD, push rules, CODEOWNERS
- **[Workflow rules: directives definitions](../Advanced/workflow_rules/directives_definitions.md)** — синтаксис workflow:rules
- **[Job rules: практические сценарии](../Advanced/workflow_rules/job_rules.md)** — правила запуска jobs
- **[Matrix builds и serialization](../Advanced/workflow_rules/matrix_builds_and_serialization.md)** — matrix jobs
- **[Merge request approval rules](../Tutorials/merge_request_approval_rules.md)** — approval rules и CODEOWNERS

### Внешние ресурсы

- [GitLab: rules:changes](https://docs.gitlab.com/ee/ci/yaml/#ruleschanges)
- [GitLab: Push rules](https://docs.gitlab.com/ee/repository/push_rules.html)
- [GitLab: CODEOWNERS](https://docs.gitlab.com/ee/user/project/code_owners.html)
