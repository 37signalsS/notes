# GitLab CI: Механизм `extends`

## Определения

**`extends`** — ключевое слово GitLab CI для наследования конфигурации от одного или нескольких "скрытых" заданий (начинающихся с точки `.`). Позволяет избегать дублирования кода внутри одного файла `.gitlab-ci.yml` или подключенного через `include`.

**Скрытое задание (Hidden Job)** — задание, имя которого начинается с точки (`.base_job`). Оно не добавляется в пайплайн напрямую, а служит исключительно шаблоном для наследования.

## Основные концепции

### Механизм слияния конфигураций

При использовании `extends` GitLab выполняет **обратное глубокое слияние (reverse deep merge)**. Это означает, что параметры из родительского задания копируются в дочернее, но дочернее задание имеет приоритет при совпадении ключей.

#### Поведение для различных типов ключей

| Тип ключа | Поведение | Особенности |
| :--- | :--- | :--- |
| **`variables`** | **Глубокое слияние** | Дочерние значения переопределяют родительские; новые переменные добавляются. |
| **`script`, `before_script`, `after_script`** | **Перезапись** | Дочерний массив строк полностью заменяет родительский. Конкатенация не происходит. |
| **`rules`** | **Перезапись** | Список условий в дочернем задании полностью заменяет родительский список. |
| **`tags`** | **Перезапись** | Дочерний список тегов заменяет родительский. |
| **`artifacts`, `cache`** | **Перезапись** | Перезаписывается весь блок целиком (включая `paths`, `reports` и т.д.). |
| **`image`, `services`, `stage`** | **Перезапись** | Прямая замена значения. |
| **`allow_failure`, `when`, `timeout`, `retry`** | **Перезапись** | Прямая замена значения. |

> **Важно:** Скрипты и массивы (rules, tags) **не конкатенируются**. Для переиспользования отдельных фрагментов скрипта используйте тег [`!reference`](./reference_and_yaml_anchors.md).

### Множественное наследование

`extends` поддерживает наследование от нескольких родительских заданий:

```yaml
extends: [.parent_a, .parent_b, .parent_c]
```

**Порядок слияния:** справа налево. Последнее задание в списке (`.parent_c`) имеет наивысший приоритет и может переопределять значения из предыдущих.

```yaml
.base_defaults:
  image: alpine:latest
  tags:
    - docker

.test_rules:
  rules:
    - if: '$CI_PIPELINE_SOURCE == "merge_request_event"'

.custom_vars:
  variables:
    TEST_ENV: staging

my_test_job:
  extends: [.base_defaults, .test_rules, .custom_vars]
  script:
    - echo "Running tests"
```

### Сравнение с другими механизмами

| Характеристика | `extends` | `!reference` | `include:inputs` |
| :--- | :--- | :--- | :--- |
| **Объект** | Задание (job) целиком | Любой блок (script, rules) | Параметризованный файл |
| **Слияние** | Reverse deep merge | Вставка (инъекция) | Интерполяция значений |
| **Гибкость** | Высокая (для jobs) | Максимальная (для фрагментов) | Максимальная (для шаблонов) |
| **Валидация** | CI Lint | CI Lint | CI Lint |

## Практические сценарии

### Сценарий 1: Шаблонизация по окружениям

Использование двоеточия в именах заданий визуально отделяет шаблон от его реализации:

```yaml
.build_template:
  stage: build
  image: docker:24.0
  variables:
    ENV: "undefined"
  script:
    - echo "Build for $ENV"
    - docker build -t $CI_REGISTRY_IMAGE:$ENV .

build:dev:
  extends: .build_template
  variables:
    ENV: "dev"

build:prod:
  extends: .build_template
  variables:
    ENV: "prod"
```

### Сценарий 2: Комбинация `include` и `extends`

Это основной паттерн для корпоративных CI/CD стандартов.

**Централизованный файл (`templates/docker.yml`):**
```yaml
.docker_base:
  image: docker:24.0
  services:
    - docker:24.0-dind
  script:
    - docker login -u $CI_REGISTRY_USER -p $CI_JOB_TOKEN $CI_REGISTRY
    - docker build -t $IMAGE_NAME .
```

**Рабочий пайплайн (`.gitlab-ci.yml`):**
```yaml
include:
  - project: 'devops/templates'
    file: 'templates/docker.yml'
    ref: 'v1.0.0'

build_app:
  extends: .docker_base
  variables:
    IMAGE_NAME: "my-app:latest"
```

### Сценарий 3: Переопределение сложных блоков (artifacts)

При наследовании важно помнить, что блоки переопределяются целиком.

```yaml
.base_test:
  script: npm test
  artifacts:
    paths:
      - coverage/
    expire_in: 1 week

special_test:
  extends: .base_test
  artifacts:
    paths:
      - custom-reports/
  # expire_in будет ПОТЕРЯН, так как блок artifacts перезаписан полностью
```

## Дополнительная информация

### Ограничения

1. **Глубина наследования:** до 11 уровней (рекомендуется не более 3 для сохранения читаемости).
2. **Область видимости:** `extends` работает только внутри одного файла или с учетом всех `include`. Вы не можете наследоваться от задания, которое не "видимо" в текущем контексте CI Lint.
3. **Запрет на циклы:** круговое наследование (`A extends B`, `B extends A`) вызывает ошибку валидации.

### Валидация через CLI

Для проверки того, как GitLab развернул все ваши `extends`, используйте GitLab CLI:

```bash
# Просмотр финальной конфигурации (expanded)
glab ci lint --show-expanded

# Проверка синтаксиса конкретного проекта
glab ci lint --project group/my-project
```

### Сводная таблица ошибок

| Ошибка | Причина | Решение |
| :--- | :--- | :--- |
| `circular reference detected` | Циклическое наследование | Разорвите цепочку `extends`. |
| `exceeded max levels` | Слишком глубокая иерархия | Используйте композицию вместо глубокого наследования. |
| `unknown extends` | Родитель не определен | Проверьте опечатки в именах скрытых заданий. |

### Связанные разделы

- [Обзор переиспользуемых пайплайнов](./overview.md)
- [Механизм !reference и YAML Anchors](./reference_and_yaml_anchors.md)
- [Механизм include](./include_keyword.md)
- [Переменные и секреты](../Concepts/gitlab_ci_variables_secrets.md)
