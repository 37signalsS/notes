# Наследование переменных в downstream pipelines

## Определения

**Наследование переменных** — механизм передачи переменных из upstream (родительского) pipeline в downstream (дочерний) pipeline. Различается для parent-child и multi-project pipelines.

## Основные концепции

### Сравнение наследования

| Тип переменных | Child Pipelines | Multi-project Pipelines |
| :--- | :--- | :--- |
| **Predefined (CI_*)** | Наследуют все | Наследуют только относящиеся к downstream проекту |
| **Project/Group variables** | Наследуют все | **НЕ наследуют** |
| **Variables из задачи** | Наследуют | **Только явно указанные** в `trigger:variables` |
| **Masked variables** | Наследуют | **НЕ наследуют** (риск unmask!) |

### 1. Variables keyword (наследование)

```yaml
variables:
  VERSION: "1.0.0"

staging:
  variables:
    ENVIRONMENT: staging
  stage: deploy
  trigger:
    include:
      - local: path/to/child-pipeline.yml
```

- `ENVIRONMENT` доступен во всех jobs downstream pipeline
- `VERSION` наследуется как default variable

### 2. Блокировка наследования

```yaml
trigger-job:
  inherit:
    variables: false  # Блокировать наследование default variables
  variables:
    JOB_VAR: value
  trigger:
    include:
      - local: path/to/child-pipeline.yml
```

- `DEFAULT_VAR` не передаётся в triggered pipeline
- `JOB_VAR` доступен

### 3. Predefined variables (интерполяция)

```yaml
trigger-job:
  variables:
    PARENT_BRANCH: $CI_COMMIT_REF_NAME  # Сохраняет как job variable
  trigger:
    include:
      - local: path/to/child-pipeline.yml
```

⚠️ **Важно:** Не используйте для masked variables в multi-project pipelines (masking не передаётся).

## Практические сценарии

### 4. Inputs keyword (рекомендуется для GitLab 17+)

**Преимущества перед `variables`:**

- Type checking
- Validation через `options`
- Descriptions
- Default values
- Безопасность (защита от инъекций)

**В target configuration:**

```yaml
# child-pipeline.yml
spec:
  inputs:
    environment:
      description: "Окружение для деплоя"
      options: [staging, production]
      default: staging
    version:
      type: string
      description: "Версия приложения"
      default: "1.0.0"
    enable_tests:
      type: boolean
      description: "Запускать ли тесты"
      default: true
```

**При запуске:**

```yaml
staging:
  trigger:
    include:
      - local: path/to/child-pipeline.yml
    inputs:
      environment: staging
      version: "1.0.0"
      enable_tests: true

production:
  trigger:
    include:
      - local: path/to/child-pipeline.yml
    inputs:
      environment: production
      version: "1.0.0"
      enable_tests: false
```

**Использование в triggered pipeline:**

```yaml
# В child-pipeline.yml
deploy_job:
  script:
    - echo "Deploying version $[[ inputs.version ]] to $[[ inputs.environment ]]"
    - |
      if [[ "$[[ inputs.enable_tests ]]" == "true" ]]; then
        echo "Running tests..."
        npm test
      fi
```

### 5. Dotenv variable inheritance (Premium/Ultimate)

```yaml
# Upstream
build_vars:
  stage: build
  script:
    - echo "BUILD_VERSION=hello" >> build.env
  artifacts:
    reports:
      dotenv: build.env

deploy:
  stage: deploy
  trigger: my/downstream_project

# Downstream
test:
  stage: test
  script:
    - echo $BUILD_VERSION
  needs:
    - project: my/upstream_project
      job: build_vars
      ref: master
      artifacts: true
```

## Дополнительная информация

### Миграция с variables на inputs

| Variables | Inputs |
| :--- | :--- |
| `$VARIABLE_NAME` | `$[[ inputs.VARIABLE_NAME ]]` |
| Нет валидации типов | Строгая типизация (string, boolean, number) |
| Нет проверки значений | `options` для допустимых значений |
| Может быть переопределена | Защищено от несанкционированного изменения |

### Рекомендации

- Используйте `inputs` для GitLab 17+
- Избегайте передачи secret/masked variables в multi-project
- Явно указывайте переменные в `trigger:variables` для multi-project

---

**Связанные документы:**

- [Определения](./definitions.md)
- [Parent-child Pipelines](./parent_child_pipelines.md)
- [Multi-project Pipelines](./multi_project_pipelines.md)
- [Best Practices](./best_practices.md)
