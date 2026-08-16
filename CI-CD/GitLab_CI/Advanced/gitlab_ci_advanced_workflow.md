# Продвинутые рабочие процессы GitLab CI/CD

## Определения

**Продвинутые рабочие процессы (Advanced Workflows)** — это архитектурный уровень проектирования CI/CD, направленный на создание сложных, масштабируемых и самодокументированных конвейеров. Они объединяют методы динамической оркестрации, превентивной безопасности и глубокой оптимизации ресурсов.

**Ключевые инструменты и директивы:**

-   **`rules` и `workflow:rules`**: Глобальное и локальное управление жизненным циклом пайплайна. Позволяют реализовать логику Branching и Merge Request пайплайнов без дублирования.
-   **`needs` (DAG)**: Механизм построения Направленных Ациклических Графов. Устраняет бутылочное горлышко стадий, позволяя задачам запускаться асинхронно.
-   **`parallel:matrix`**: Динамическое размножение задач для кросс-платформенного тестирования и параллельного выполнения.
-   **`resource_group`**: Система блокировок (mutex) на уровне GitLab для предотвращения конфликтов при одновременном доступе к ограниченным ресурсам (например, окружениям).
-   **Pipeline Inputs (`spec:inputs`)**: Механизм типизации параметров, превращающий YAML-конфигурацию в структурированный интерфейс с валидацией типов (`string`, `number`, `boolean`) на этапе компиляции.
-   **OIDC (ID tokens)**: Протокол федеративной аутентификации, позволяющий джобе получать кратковременные права доступа к внешним облакам (AWS, GCP) и Vault без статических секретов.
-   **Pipeline Execution Policies**: Корпоративный стандарт принудительного исполнения задач безопасности и комплаенса, который невозможно обойти на уровне проекта (GitLab 17.x–19.x).
-   **SLSA & SBOM**: Стандарты безопасности цепочек поставок (Software Supply Chain), обеспечивающие проверяемость происхождения кода и прозрачность состава артефактов.

## Основные концепции

### Оптимизация и производительность

Современные пайплайны в 2026 году ориентированы на максимальную скорость обратной связи (Feedback Loop).

1.  **Ациклические графы (DAG)**: Директива `needs` позволяет задачам игнорировать границы стадий.
    -   **`needs:optional`**: Позволяет зависеть от задачи, которая может быть не включена в текущий пайплайн (например, при селективном запуске в монорепозиториях).
2.  **Матричные сборки**: Использование `parallel:matrix`. Для оптимизации рекомендуется использовать матричную адресацию зависимостей (`needs:parallel:matrix`), связывающую сборки и тесты 1:1.
3.  **Автоматическая отмена (`workflow:auto_cancel`)**:
    -   **`on_new_commit`**: Режим `conservative` предотвращает отмену критических стадий деплоя, в то время как `interruptible: true` позволяет мгновенно высвобождать раннеры при новых коммитах.
    -   **`on_job_failure: all`**: Режим Fail-Fast, который немедленно останавливает весь пайплайн при критической ошибке, экономя бюджет на облачные вычисления.
4.  **Типизированный запуск через Inputs**: С версии GitLab 17.11 директива `spec:inputs` может использоваться в корневом файле, заменяя текстовые поля переменных на выпадающие списки и флажки в UI «Run Pipeline».

### Безопасность и Compliance (Supply Chain Security)

1.  **Zero Trust через ID Tokens**: Использование `id_tokens` обеспечивает модель **Workload Identity Federation**. Раннер получает JWT, аудитория (`aud`) которого проверяется внешним провайдером. Это полностью устраняет риск компрометации статических токенов доступа.
2.  **Pipeline Execution Policies**: Позволяют ИБ-инженерам внедрять обязательные стадии (сканирование на уязвимости, проверка лицензий) во все проекты группы. С версии **19.x** поддерживаются **Scheduled Execution Policies** для регулярного аудита состояния безопасности всех репозиториев.
3.  **Генерация аттестаций (SLSA)**: Автоматическое создание доказательств сборки в доверенной среде. Использование `artifacts:reports:cyclonedx` для генерации SBOM (Software Bill of Materials) в формате JSON, что является обязательным для комплаенса в современных Enterprise-средах.

### Сложные архитектуры пайплайнов

1.  **Parent-Child Pipelines**: Решение для монорепозиториев.
    -   **Изоляция**: Ошибки в одном сервисе не блокируют CI/CD других.
    -   **inputs**: Передача параметров через `trigger:inputs` (GitLab 18.0+) для валидации конфигурации дочернего пайплайна.
2.  **Dynamic Pipeline Generation**: Программная генерация YAML через скрипты (Python/Go). Используется, когда количество окружений или задач зависит от внешнего API (например, список динамических Feature-бранчей).

## Практические сценарии

### Сценарий 1: Управление через Pipeline Inputs (GitLab 18.x)

Создание удобного интерфейса для ручного запуска деплоя с валидацией параметров.

```yaml
spec:
  inputs:
    environment:
      type: string
      default: staging
      options: [staging, production]
    perform_cleanup:
      type: boolean
      default: true

workflow:
  rules:
    - if: $CI_PIPELINE_SOURCE == "web"
    - if: $CI_COMMIT_BRANCH == $CI_DEFAULT_BRANCH

deploy_job:
  stage: deploy
  script:
    - echo "Deploying to $[[ inputs.environment ]]"
    - if [ "$[[ inputs.perform_cleanup ]]" = "true" ]; then ./cleanup.sh; fi
```

### Сценарий 2: Аутентификация в AWS через OIDC (Zero Trust)

Исключение использования `AWS_ACCESS_KEY_ID`.

```yaml
deploy:aws:
  id_tokens:
    GITLAB_OIDC_TOKEN:
      aud: https://gitlab.com
  variables:
    AWS_ROLE_ARN: "arn:aws:iam::123456789012:role/GitLabCI"
    AWS_REGION: "us-east-1"
  script:
    - >
      AWS_CREDS=$(aws sts assume-role-with-web-identity 
      --role-arn ${AWS_ROLE_ARN} 
      --role-session-name "GitLabCI-${CI_PIPELINE_ID}" 
      --web-identity-token ${GITLAB_OIDC_TOKEN} 
      --query 'Credentials.[AccessKeyId,SecretAccessKey,SessionToken]' 
      --output text)
    - export AWS_ACCESS_KEY_ID=$(echo $AWS_CREDS | awk '{print $1}')
    - # ... деплой
```

### Сценарий 3: Генерация SBOM и аттестация SLSA

Обеспечение прозрачности состава артефактов.

```yaml
build_app:
  stage: build
  script:
    - ./build.sh
    - syft . -o cyclonedx-json=bom.json
  artifacts:
    reports:
      cyclonedx: bom.json
    paths:
      - build/app.bin

sign_artifacts:
  stage: test
  needs: [build_app]
  id_tokens:
    SIGSTORE_ID_TOKEN:
      aud: sigstore
  script:
    - cosign sign-blob build/app.bin --bundle cosign.bundle --identity-token $SIGSTORE_ID_TOKEN
```

### Сценарий 4: Глобальная очередь с resource_group

Предотвращение конфликтов при деплое в одну базу данных.

```yaml
db_migrate:
  stage: deploy
  resource_group: database_cluster_prod
  resource_group_process_mode: oldest_first # Строгий FIFO порядок
  script:
    - ./run_migrations.sh
  interruptible: false # Нельзя прерывать миграцию
```

## Устранение неполадок (Troubleshooting)

### Распространенные ошибки
-   **`Validation failed: spec:inputs`**: Несоответствие переданных параметров ожидаемым типам или опциям. Решение: Проверить `inputs` в UI и в YAML вызове.
-   **`OIDC identity provider rejected token`**: Ошибка в `aud` (audience) или в настройках Trust Policy на стороне облака. Решение: Проверить соответствие `sub` клейма (project path, ref).
-   **Deadlock в Resource Group**: Если задача зависла и удерживает группу, последующие пайплайны будут ждать бесконечно. Решение: Ручная очистка в `CI/CD -> Resource Groups` или настройка `timeout`.
-   **DAG Circular Dependency**: Задачи A и B зависят друг от друга в `needs`. Решение: Использование `stages` для разделения логики или пересмотр графа.

### Инструменты диагностики
-   **CI Lint с симуляцией**: В Pipeline Editor обязательно выбирайте «Simulate pipeline» для проверки `rules` и `inputs`.
-   **CI_DEBUG_SERVICES**: Включите для отладки проблем с Docker-in-Docker или интеграциями.
-   **Exporting Variables**: Вывод `env | sort` (без секретов!) помогает понять иерархию приоритетов переменных.

## Дополнительная информация

### Сравнение стратегий управления

| Инструмент | Уровень влияния | Основной кейс использования | Рекомендация 2026 |
| :--- | :--- | :--- | :--- |
| **`workflow:rules`** | Пайплайн | Фильтрация триггеров (MR, Push, API) | Использовать для исключения дублей |
| **`resource_group`** | Ресурс | Предотвращение Race Conditions | Всегда для Production БД |
| **`spec:inputs`** | Конфигурация | Типизация и UI-формы | Замена неструктурированным переменным |
| **`auto_cancel`** | Раннеры | Экономия ресурсов | Режим `on_job_failure: all` для Dev |

### См. также

-   **[Основы GitLab CI/CD](../Concepts/gitlab_ci_basics.md)** — база и глоссарий.
-   **[Конструктор рабочих процессов](./gitlab_ci_workflow_builder.md)** — детализация по стадиям и артефактам.
-   **[DAG с needs](./workflow_rules/dag_with_needs.md)** — глубокое погружение в графы.
-   **[Матричные сборки и сериализация](./workflow_rules/matrix_builds_and_serialization.md)** — подробнее о `parallel:matrix` и `resource_group`.
-   [Безопасность цепочки поставок (Supply Chain Security)](../../../Security/Supply_Chain_Security/overview.md) — детализация SBOM и аттестаций.
-   [Sigstore и OIDC](../../../Security/Tools/sigstore.md) — использование временных токенов для подписи артефактов.
-   [HashiCorp Vault: Zero Trust](../../../Vault/zero_trust.md) — концепция беспарольного доступа.

