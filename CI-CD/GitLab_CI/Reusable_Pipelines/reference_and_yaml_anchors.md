# GitLab CI: `!reference` и YAML Anchors

## Определения

| Термин | Описание |
| :--- | :--- |
| **`!reference`** | Специальный тег GitLab CI для явной ссылки на другие элементы конфигурации с валидацией через CI Lint |
| **YAML Anchor (`&`)** | Стандартный механизм YAML для определения именованного фрагмента конфигурации |
| **YAML Alias (`*`)** | Стандартный механизм YAML для вставки содержимого, определённого через Anchor |
| **Скрытое задание** | Задание, имя которого начинается с точки (`.`) — не выполняется напрямую, используется как шаблон |

## Основные концепции

### `!reference` vs. YAML Anchors

Оба механизма используются для переиспользования фрагментов конфигурации, но имеют ключевые различия.

#### Сравнительная таблица

| Критерий | `!reference` | YAML Anchors (`&`) / Aliases (`*`) |
| :--- | :--- | :--- |
| **Тип** | Специальный тег GitLab CI | Стандартный механизм YAML |
| **Валидация Lint** | ✅ Полная | ⚠️ Ограниченная |
| **Читаемость** | ✅ Высокая (явная ссылка) | Средняя (требует понимания YAML) |
| **Гибкость** | ✅ Ссылка на любые элементы, включая конкретные элементы списков/словарей | ⚠️ Только полная подстановка фрагмента |
| **Область видимости** | Один документ YAML (файл) | Один документ YAML (файл) |
| **Рекомендация GitLab** | ✅ **Предпочтительно** | ⚠️ Для простых случаев |

> **Best Practice:** Используйте `!reference` в новых проектах для лучшей валидации и читаемости. Избегайте YAML Anchors в сложных конфигурациях [^1].

[^1]: [GitLab CI Best Practices — Avoid YAML Anchors](https://dev.to/zenika/gitlab-ci-10-best-practices-to-avoid-widespread-anti-patterns-2mb5)

### Синтаксис `!reference`

```yaml
# Базовый синтаксис
script:
  - !reference [.hidden_job, script]

# Ссылка на конкретный элемент списка
tags:
  - !reference [.default_tags, tags, 0]

# Ссылка на вложенный ключ
variables:
  !reference [.config, variables, DB_HOST]
```

**Формат:**
```
!reference [<путь_к_заданию>, <ключ1>, <ключ2>, ..., <индекс_или_ключ>]
```

### Синтаксис YAML Anchors

```yaml
# Определение якоря
.default_script: &default_script_definition
  - echo "Step 1"
  - echo "Step 2"

# Использование alias
job1:
  script: *default_script_definition
```

**Формат:**
- `&anchor_name` — определение якоря
- `*anchor_name` — использование (alias)
- `<<: *anchor_name` — merge key для слияния словарей

## Практические сценарии

### Сценарий 1: Переиспользование скриптов через `!reference`

**Определение общего скрипта:**
```yaml
.common_setup:
  - echo "Setting up environment..."
  - bundle install
  - npm ci

build_job:
  stage: build
  script:
    - !reference [.common_setup]
    - echo "Building application..."
    - npm run build

test_job:
  stage: test
  script:
    - !reference [.common_setup]
    - echo "Running tests..."
    - npm test
```

**Преимущества:**
- Изменения в `.common_setup` автоматически применяются ко всем jobs
- Полная валидация через CI Lint
- Читаемая структура

### Сценарий 2: Ссылка на конкретные элементы списка

```yaml
.default_tags: &default_runner_tags
  tags:
    - linux
    - docker
    - medium

build_job:
  stage: build
  tags:
    - !reference [.default_tags, tags, 0]  # Ссылка на первый элемент: "linux"
  script:
    - echo "Building on linux runner"

test_job:
  stage: test
  tags:
    - !reference [.default_tags, tags, 1]  # Ссылка на второй элемент: "docker"
  script:
    - echo "Testing with docker"
```

### Сценарий 3: Переиспользование правил (rules)

```yaml
.mr_rules:
  rules:
    - if: '$CI_PIPELINE_SOURCE == "merge_request_event"'
    - when: manual

deploy_job:
  stage: deploy
  rules:
    - !reference [.mr_rules, rules]
  script:
    - echo "Deploying..."
```

### Сценарий 4: Комбинация `!reference` и `extends`

```yaml
.base_template:
  image: node:20-alpine
  before_script:
    - npm ci

.common_scripts:
  - echo "Common step 1"
  - echo "Common step 2"

build_job:
  extends: .base_template
  script:
    - !reference [.common_scripts]
    - npm run build

test_job:
  extends: .base_template
  script:
    - !reference [.common_scripts]
    - npm test
```

### Сценарий 5: YAML Anchors для простых случаев

```yaml
# Простое переиспользование через YAML Anchors
.after_script_template: &after_script_cleanup
  - echo "Cleaning up..."
  - rm -rf tmp/

job1:
  script:
    - echo "Running job 1"
  after_script:
    - *after_script_cleanup

job2:
  script:
    - echo "Running job 2"
  after_script:
    - *after_script_cleanup
```

> **Примечание:** Для этого случая предпочтительнее использовать `!reference`:
> ```yaml
> after_script:
>   - !reference [.after_script_cleanup]
> ```

### Сценарий 6: Merge Key для словарей

```yaml
.default_cache: &default_cache_config
  key: ${CI_COMMIT_REF_SLUG}
  paths:
    - node_modules/
    - .npm/

build_job:
  stage: build
  cache:
    <<: *default_cache_config
    policy: pull-push
  script:
    - npm install

test_job:
  stage: test
  cache:
    <<: *default_cache_config
    policy: pull
  script:
    - npm test
```

**Результат:**
- `build_job`: кэш с `policy: pull-push` (запись и чтение)
- `test_job`: кэш с `policy: pull` (только чтение)

## Ограничения

| Ограничение | `!reference` | YAML Anchors |
| :--- | :--- | :--- |
| **Межфайловые ссылки** | ❌ Нет (только в пределах одного документа) | ❌ Нет (только в пределах одного документа) |
| **Ссылка на внешний проект** | ❌ Нет | ❌ Нет |
| **Вложенность** | ✅ До 11 уровней | ✅ Без ограничений |
| **Валидация существования** | ✅ Да (CI Lint обнаруживает битые ссылки) | ⚠️ Нет (ошибка только при выполнении) |

### Важные замечания

1. **`!reference` не работает между файлами** — для межфайлового переиспользования используйте `include` + `extends`
2. **YAML Anchors не работают с `include`** — каждый файл `include` имеет независимое пространство имён YAML
3. **`!reference` требует GitLab 14.0+** — в старых версиях используйте YAML Anchors

## Валидация

```bash
# Проверка конфигурации с !reference
gitlab-ci lint --project=my-group/my-project

# Отладка с подстановкой ссылок
gitlab-ci lint --include-debug
```

## Распространённые ошибки

| Ошибка | Причина | Решение |
| :--- | :--- | :--- |
| `!reference: unknown anchor` | Ссылка на несуществующий элемент | Проверьте имя и порядок объявления |
| `circular reference` | Циклическая ссылка | Убедитесь, что нет замкнутой цепочки |
| `YAML alias unknown` | Alias используется до определения | Определите anchor до первого использования |

## Дополнительная информация

### Когда использовать каждый подход

| Сценарий | Рекомендуемый механизм |
| :--- | :--- |
| Переиспользование скриптов внутри файла | `!reference` |
| Переиспользование правил (rules) | `!reference` |
| Переиспользование переменных | `!reference` |
| Простое переиспользование (1-2 jobs) | YAML Anchors |
| Слияние словарей с переопределением | YAML Anchors + Merge Key (`<<:`) |
| Наследование конфигурации задания | `extends` |
| Межфайловое переиспользование | `include` + `extends` |

### Связанные документы

- **[Обзор переиспользуемых пайплайнов](./overview.md)** — сравнение всех подходов
- **[Механизм `extends`](./extends_keyword.md)** — наследование конфигураций
- **[Механизм `include`](./include_keyword.md)** — подключение внешних файлов

### Внешние ресурсы

- [Официальная документация: `!reference`](https://docs.gitlab.com/ci/yaml/#reference)
- [YAML Specification: Anchors and Aliases](https://yaml.org/spec/1.2.2/#anchors-and-aliases)
- [GitLab CI Best Practices](https://dev.to/zenika/gitlab-ci-10-best-practices-to-avoid-widespread-anti-patterns-2mb5)
