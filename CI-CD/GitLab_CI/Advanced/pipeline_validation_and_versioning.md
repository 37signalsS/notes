# Валидация и версионирование пайплайнов GitLab CI/CD

## Определения

**Валидация пайплайнов** — комплексный процесс проверки синтаксиса (YAML Lint), логической целостности (DAG, зависимости) и контекстуальной корректности конфигурации.

**Ключевые инструменты и методы:**

-   **CI Lint API (Dry Run)** — метод глубокой валидации (GitLab 16.11+), имитирующий создание пайплайна. Проверяет не только синтаксис, но и права доступа, наличие образов, существование артефактов и корректность `rules` в контексте конкретной ветки или события.
-   **Версионирование шаблонов (Infrastructure as Code)** — практика применения фиксированных меток (теги SemVer, commit SHA) к подключаемым YAML-ресурсам для предотвращения каскадных сбоев при обновлении инструментов.
-   **Pipeline Execution Policies** — корпоративный механизм (GitLab 17.x–19.x) для принудительного внедрения задач безопасности и комплаенса, которые невозможно пропустить или переопределить на уровне проекта.
-   **Validation Gates** — промежуточные проверки внутри пайплайна, блокирующие дальнейшее выполнение (например, деплой) при обнаружении логических ошибок в сгенерированных конфигурациях.

## Основные концепции

### Иерархия валидации
Проверка конфигурации должна выполняться на нескольких уровнях:
1.  **IDE Level**: Использование плагинов для VS Code/JetBrains с поддержкой схемы GitLab CI.
2.  **Pre-commit Level**: Использование `glab ci lint` для локальной проверки перед пушем.
3.  **Server Level (Dry Run)**: Автоматическая проверка через API при создании Merge Request.
4.  **Runtime Level**: Валидация динамически генерируемых дочерних пайплайнов перед их запуском.

### Стратегии версионирования и их риски

| Стратегия | Пример (`ref`) | Стабильность | Гибкость | Рекомендация 2026 |
| :--- | :--- | :--- | :--- | :--- |
| **Commit SHA** | `abcdef12` | Максимальная | Нулевая | Для критической инфраструктуры (Bank/Fintech) |
| **SemVer (Full)** | `v1.2.3` | Высокая | Низкая | Стандарт для CI/CD Catalog компонентов |
| **SemVer (Minor)** | `v1.2` | Средняя | Средняя | Получение патчей безопасности автоматически |
| **Static Branch** | `main` / `stable` | Низкая | Высокая | **Запрещено** для Production (риск каскадного падения) |

## Практические сценарии

### Сценарий 1: Продвинутая валидация через Lint API (Dry Run)

Использование `dry_run: true` позволяет проверить логику `rules` и `needs` до запуска тяжелых задач.

```yaml
validate_pipeline_logic:
  stage: .pre
  image: alpine:3.21
  script:
    - apk add --no-cache curl jq
    - |
      # Кодируем содержимое текущего файла в JSON
      content=$(cat .gitlab-ci.yml)
      data=$(jq --null-input --arg yaml "$content" '{content: $yaml, dry_run: true, project_id: $CI_PROJECT_ID}')
      
      response=$(curl --fail -sS \
            --header "PRIVATE-TOKEN: ${CI_API_V4_TOKEN}" \
            --header "Content-Type: application/json" \
            --data "$data" \
            "${CI_API_V4_URL}/projects/${CI_PROJECT_ID}/ci/lint")
      
      if [[ $(echo "$response" | jq '.valid') != "true" ]]; then
        echo "Pipeline logic error in branch ${CI_COMMIT_REF_NAME}:"
        echo "$response" | jq -r '.errors[]'
        exit 1
      fi
  rules:
    - if: $CI_PIPELINE_SOURCE == "merge_request_event"
```

### Сценарий 2: Canary Rollout для CI-шаблонов

Метод плавного обновления общих пайплайнов компании, чтобы не сломать все проекты одновременно.

```yaml
include:
  - project: 'ops/ci-library'
    file: '/templates/base.yml'
    # Используем переменную для управления версией
    ref: $CI_TEMPLATE_VERSION

variables:
  # По умолчанию используем стабильную версию
  CI_TEMPLATE_VERSION: "v2.5.0"

# В экспериментальных ветках или для отдельных групп включаем Canary
workflow:
  rules:
    - if: '$CI_PROJECT_NAMESPACE =~ /^canary-testers\//'
      variables:
        CI_TEMPLATE_VERSION: "v2.6.0-rc1"
    - when: always
```

### Сценарий 3: Локальная отладка через `glab` (v19.x)

Инструмент `glab` позволяет диагностировать проблемы наследования и интерполяции `inputs` без коммита.

```bash
# 1. Проверка синтаксиса с имитацией переменных MR
glab ci lint --dry-run --variable CI_PIPELINE_SOURCE=merge_request_event

# 2. Получение финального YAML со всеми разрешенными !reference и extends
glab ci lint --show-expanded > processed-config.yml

# 3. Валидация конкретного файла (например, сгенерированного скриптом)
glab ci lint path/to/generated-ci.yml
```

### Сценарий 4: Принудительное исполнение политик (Scheduled Policies)

Настройка политик безопасности на уровне группы для регулярного аудита.

1.  Создайте проект `security-policies` в вашей группе.
2.  В проекте настройте `policy.yml`:
    ```yaml
    scan_execution_policy:
      - name: Weekly Security Audit
        enabled: true
        rules:
          - type: schedule
            cadence: "0 0 * * 0" # Каждое воскресенье
        actions:
          - scan: secret_detection
          - scan: container_scanning
    ```

## Устранение неполадок (Troubleshooting)

### Типичные проблемы
-   **`Circular dependency detected`**: Возникает при использовании `needs`, когда задачи A и B зависят друг от друга (напрямую или через цепочку). Решение: Используйте `stages` для разделения независимых блоков.
-   **`Included file not found`**: Ошибка в путях `include:local` или отсутствие прав у `CI_JOB_TOKEN` для `include:project`. Решение: Проверьте область видимости проекта (Visibility) и настройки Token Access.
-   **`Input validation failed`**: Переданный параметр не соответствует типу в `spec:inputs`. Решение: Проверьте `merged YAML` в Pipeline Editor, чтобы увидеть, какие значения реально попадают в компонент.
-   **`Empty pipeline error`**: Все задачи отфильтрованы через `rules`. Решение: Добавьте задачу-заглушку (placeholder) или исправьте логику `workflow:rules`.

### Инструменты диагностики
-   **Pipeline Editor (Merged YAML)**: Главный инструмент для понимания того, что "видит" сервер.
-   **Variables Trace**: Используйте `export` в тестовой задаче для проверки итогового значения версий шаблонов.

## Дополнительная информация

### См. также
-   **[Основы GitLab CI/CD](../Concepts/gitlab_ci_basics.md)** — база и глоссарий.
-   **[Обзор переиспользуемых пайплайнов](../Reusable_Pipelines/overview.md)** — выбор между `extends` и `include`.
-   **[Справочник каталога компонентов](../Reusable_Pipelines/ci_cd_catalog_reference.md)** — спецификации SemVer для каталога.
-   **[Управление релизами и SemVer](./release_management_and_semver.md)** — автоматизация создания тегов.
-   **[Правила запуска задач](./workflow_rules/job_rules.md)** — детализация логики `rules`.
