# GitLab CI: Механизм `extends`

### Основные концепции

#### `extends` — Логика слияния конфигураций

Когда задание использует `extends`, GitLab CI выполняет слияние (merge) конфигураций от родительского ("скрытого") задания к дочернему. Важно понимать, как это происходит:

- **Скрипты (`script`, `before_script`, `after_script`):** Скрипты из родительского задания **конкатенируются** со скриптами дочернего задания. Если дочернее задание имеет `script` или `before_script`/`after_script`, они будут выполнены **после** соответствующих скриптов из `extends`-задания.
- **Другие ключи (например, `variables`, `rules`, `cache`):** Для большинства других ключей происходит **глубокое слияние (deep merge)**. Это означает, что если ключ присутствует как в родительском, так и в дочернем задании, значения из дочернего задания **переопределяют** или **дополняют** значения из родительского.
  - Если дочернее задание определяет ключ, отсутствующий в родительском, он добавляется.
  - Если ключ является словарем (map), его поля сливаются.
  - Если ключ является списком (list), он обычно **заменяется** списком из дочернего задания, если дочерний список не пуст.

Список ключей `extends` может быть использован для наследования от нескольких скрытых заданий. В этом случае слияние происходит последовательно, справа налево (т.е. последнее задание в списке `extends` будет иметь приоритет).

### Практические сценарии

#### Сценарий 1: Использование `extends` для наследования конфигураций

**Пример наследования от одного скрытого задания:**

```yaml
.base_job:
  image: ruby:2.7
  script:
    - echo "This is from the base job."
  variables:
    BASE_VAR: "base_value"
    OVERRIDE_ME: "base_override"
  rules:
    - if: '$CI_COMMIT_BRANCH == "main"'

test_job:
  extends: .base_job
  script:
    - echo "This is from the test job. It will run after the base script."
  variables:
    TEST_VAR: "test_value"
    OVERRIDE_ME: "test_override" # Переопределит BASE_VAR
  rules:
    - if: '$CI_PIPELINE_SOURCE == "merge_request_event"' # Заменит правило из .base_job
```

В результате `test_job` будет иметь:
- `image: ruby:2.7`
- `script`: объединение скриптов из `.base_job` и `test_job`.
- `variables`: `BASE_VAR: "base_value"`, `OVERRIDE_ME: "test_override"`, `TEST_VAR: "test_value"`.
- `rules`: только правило из `test_job` (`if: '$CI_PIPELINE_SOURCE == "merge_request_event"'`).

**Пример наследования от нескольких скрытых заданий:**

```yaml
.base_defaults:
  image: alpine:latest

.test_rules:
  rules:
    - if: '$CI_PIPELINE_SOURCE == "merge_request_event"'

my_test_job:
  extends:
    - .base_defaults
    - .test_rules
  script:
    - echo "Running tests"
```

В этом примере `my_test_job` сначала наследует от `.base_defaults`, затем сливается с `.test_rules`.
