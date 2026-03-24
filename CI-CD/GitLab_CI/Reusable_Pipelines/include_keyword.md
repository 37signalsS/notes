# GitLab CI: Механизм `include`

## Definitions

**`include`** — механизм GitLab CI для подключения внешних YAML-файлов к конфигурации пайплайна. Позволяет создавать модульные, переиспользуемые конфигурации, размещая общие шаблоны в отдельных файлах.

**Важно:** Файлы `include` обрабатываются **первыми**, затем сливаются с основной конфигурацией `.gitlab-ci.yml`. Локальная конфигурация имеет приоритет и перезаписывает включённую.

## Basic Concepts

### Типы `include`

| Тип | Описание | Когда использовать |
| :--- | :--- | :--- |
| **`include:local`** | Файл в том же репозитории и ветке | Разделение конфигурации внутри проекта |
| **`include:project`** | Файл из другого проекта на том же экземпляре GitLab | Централизованные шаблоны для группы проектов |
| **`include:remote`** | Файл по публичному URL | Сторонние шаблоны, публичные библиотеки |
| **`include:template`** | Встроенные шаблоны GitLab (Auto DevOps, SAST, DAST) | Быстрая настройка стандартных пайплайнов |
| **`include:component`** | CI/CD компонент из каталога | Версионируемые компоненты с `spec:inputs` |

### Синтаксис

#### Краткая форма (только для `local`)

```yaml
include:
  - '.gitlab-ci/build.yml'
  - '.gitlab-ci/test.yml'
```

#### Полная форма

```yaml
include:
  - local: '.gitlab-ci/build.yml'

  - project: 'group/ci-templates'
    ref: v1.0.0
    file: '/docker/build.yml'

  - remote: 'https://example.com/.gitlab-ci.yml'

  - template: 'Security/SAST.gitlab-ci.yml'

  - component: '$CI_SERVER_FQDN/group/component@1.0.0'
```

### `include:local`

Подключает файл из того же репозитория и ветки.

```yaml
include:
  - local: '.gitlab-ci/build.yml'
```

**Ограничения:**

- Путь должен начинаться с `/` или быть относительным
- Нельзя использовать пути через Git submodules
- Расширение: `.yml` или `.yaml`

**Пример структуры:**

```
project/
├── .gitlab-ci.yml
└── .gitlab-ci/
    ├── build.yml
    ├── test.yml
    └── deploy.yml
```

```yaml
# .gitlab-ci.yml
include:
  - local: '.gitlab-ci/build.yml'
  - local: '.gitlab-ci/test.yml'
  - local: '.gitlab-ci/deploy.yml'

stages:
  - build
  - test
  - deploy
```

### `include:project`

Подключает файл из другого проекта на том же экземпляре GitLab.

```yaml
include:
  - project: 'group/ci-templates'
    ref: main
    file: '/docker/build.yml'
```

**Параметры:**

| Параметр | Обязательный | Описание |
| :--- | :--- | :--- |
| `project` | Да | Путь проекта (например, `group/ci-templates`) |
| `file` | Да | Путь файла в проекте (начинается с `/`) |
| `ref` | Нет | Ветка, тег или SHA (по умолчанию — `HEAD`) |

**Рекомендации по версионированию:**

| Тип `ref` | Рекомендация | Пример |
| :--- | :--- | :--- |
| **Тег (SemVer)** | ✅ Рекомендуется | `ref: v1.2.0` |
| **Commit SHA** | ✅ Максимальная стабильность | `ref: e3262fdd0914fa823210cdb79a8c421e2cef79d8` |
| **Ветка** | ⚠️ Не рекомендуется (нестабильно) | `ref: main` |
| **Частичный SemVer** | ✅ Для автообновлений | `ref: '1.2'` (только для опубликованных компонентов) |

**Пример:**

```yaml
include:
  - project: 'group/ci-templates'
    ref: v1.2.0  # Тег вместо main
    file: '/docker/build.yml'
```

### `include:remote`

Подключает файл по публичному URL.

```yaml
include:
  - remote: 'https://example.com/.gitlab-ci.yml'
```

**Параметры (GitLab 17.9+):**

| Параметр | Описание |
| :--- | :--- |
| `integrity` | SHA256-хеш для проверки целостности файла |
| `cache` | Время кэширования удалённого файла (GitLab 18.9+, эксперимент) |

**Пример с проверкой целостности:**

```yaml
include:
  - remote: 'https://example.com/.gitlab-ci.yml'
    integrity: 'sha256-L3/GAoKaw0Arw6hDCKeKQlV1QPEgHYxGBHsH4zG1IY8='
```

### `include:template`

Использует встроенные шаблоны GitLab.

```yaml
include:
  - template: 'Security/SAST.gitlab-ci.yml'
  - template: 'Jobs/Node.js.gitlab-ci.yml'
```

**Доступные шаблоны:**

- `Security/SAST.gitlab-ci.yml` — статический анализ безопасности
- `Security/DAST.gitlab-ci.yml` — динамический анализ безопасности
- `Jobs/Node.js.gitlab-ci.yml` — шаблон для Node.js проектов
- `Jobs/Python.gitlab-ci.yml` — шаблон для Python проектов
- `Jobs/Go.gitlab-ci.yml` — шаблон для Go проектов

### `include:component`

CI/CD компонент из каталога (GitLab 16.0+).

```yaml
include:
  - component: '$CI_SERVER_FQDN/group/component@1.0.0'
    inputs:
      stage: build
      target_branch: main
```

**Синтаксис пути:**

```
$CI_SERVER_FQDN/<project-path>/<component-name>@<version>
```

**Форматы версий:**

| Формат | Пример | Рекомендация |
| :--- | :--- | :--- |
| **SemVer (полный)** | `@1.2.0` | ✅ Для релизов |
| **SemVer (частичный)** | `@1.2` или `@1` | ✅ Для автообновлений |
| **Commit SHA** | `@e3262fd...` | ✅ Для максимальной стабильности |
| **~latest** | `@~latest` | ⚠️ Только если доверяете автору |

**Важно:** Для компонентов в CI/CD Catalog обязательно семантическое версионирование (GitLab 16.10+).

### Дополнительные параметры

#### `include:inputs`

Передача входных параметров в подключаемый файл (для компонентов и шаблонов с `spec:inputs`).

```yaml
include:
  - local: '.gitlab-ci/build.yml'
    inputs:
      environment: production
      enable_cache: true
```

#### `include:rules`

Условное включение файлов.

```yaml
include:
  - local: '.gitlab-ci/deploy.yml'
    rules:
      - if: '$CI_COMMIT_BRANCH == "main"'
```

Файл будет включён только если условие истинно.

#### `include:integrity`

Проверка целостности удалённого файла через SHA256 (GitLab 17.9+).

```yaml
include:
  - remote: 'https://example.com/.gitlab-ci.yml'
    integrity: 'sha256-<hash>'
```

### Ограничения

| Ограничение | Значение |
| :--- | :--- |
| Максимум включений на пайплайн | **150** (включая вложенные) |
| Время ожидания разрешения файлов | **30 секунд** |
| Расширения файлов | `.yml`, `.yaml` |
| Глобальные ключи в `include` | `stages:`, `default:` влияют на весь пайплайн |

### Приоритеты слияния

| Конфигурация | Приоритет |
| :--- | :--- |
| Задание в `.gitlab-ci.yml` | **Наивысший** |
| `default:` в `.gitlab-ci.yml` | Средний |
| Файлы `include:` | **Низший** |

## Practical Scenarios

### Сценарий 1: Модульная конфигурация проекта

**Структура:**

```
project/
├── .gitlab-ci.yml
└── .gitlab-ci/
    ├── build.yml
    ├── test.yml
    └── deploy.yml
```

```yaml
# .gitlab-ci.yml
include:
  - local: '.gitlab-ci/build.yml'
  - local: '.gitlab-ci/test.yml'
  - local: '.gitlab-ci/deploy.yml'

stages:
  - build
  - test
  - deploy
```

### Сценарий 2: Централизованные шаблоны для группы проектов

**Репозиторий шаблонов (`group/ci-templates`):**

```
ci-templates/
├── docker-build.yml
├── nodejs-test.yml
└── kubernetes-deploy.yml
```

```yaml
# docker-build.yml
.docker_build:
  stage: build
  image: docker:24.0
  services:
    - docker:24.0-dind
  script:
    - docker build -t $CI_REGISTRY_IMAGE:$CI_COMMIT_SHORT_SHA .
    - docker push $CI_REGISTRY_IMAGE:$CI_COMMIT_SHORT_SHA
```

**Проект (`.gitlab-ci.yml`):**

```yaml
include:
  - project: 'group/ci-templates'
    ref: v1.2.0
    file: '/docker-build.yml'

stages:
  - build

build:
  extends: .docker_build
  variables:
    DOCKER_BUILDKIT: "1"
```

### Сценарий 3: Условное включение для разных окружений

```yaml
include:
  - local: '.gitlab-ci/build.yml'

  - local: '.gitlab-ci/deploy-dev.yml'
    rules:
      - if: '$CI_COMMIT_BRANCH == "develop"'

  - local: '.gitlab-ci/deploy-prod.yml'
    rules:
      - if: '$CI_COMMIT_BRANCH == "main"'
```

### Сценарий 4: Использование компонента с inputs

```yaml
include:
  - component: '$CI_SERVER_FQDN/group/security/secret-detection@1.0.0'
    inputs:
      stage: security
      scan_path: './config/secrets'
```

## Additional Information

### Валидация

```bash
# Проверка конфигурации
gitlab-ci lint --project=my-group/my-project

# Отладка include
gitlab-ci lint --include-debug
```

### Распространённые ошибки

| Ошибка | Причина | Решение |
| :--- | :--- | :--- |
| `file does not exist` | Неправильный путь к файлу | Проверьте путь и расширение |
| `exceeded max includes` | Более 150 включений | Упростите структуру |
| `timeout waiting for include` | Файл недоступен более 30 сек | Проверьте доступность remote/project |

### Связанные документы

- **[Обзор переиспользуемых пайплайнов](../overview.md)** — сравнение подходов
- **[Механизм `extends`](../extends_keyword.md)** — наследование конфигураций
- **[CI/CD Catalog](../ci_cd_catalog_components.md)** — создание компонентов
- **[Переменные и секреты](../../Concepts/gitlab_ci_variables_secrets.md)** — управление переменными

### Внешние ресурсы

- [Официальная документация: `include`](https://docs.gitlab.com/ci/yaml/#include)
- [Официальная документация: CI/CD Components](https://docs.gitlab.com/ci/components/)
