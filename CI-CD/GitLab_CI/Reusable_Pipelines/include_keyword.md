# GitLab CI: Механизм `include`

## Определения

**`include`** — механизм GitLab CI для подключения внешних YAML-файлов к конфигурации пайплайна. Позволяет создавать модульные, переиспользуемые конфигурации, размещая общие шаблоны в отдельных файлах.

**Важно:** Файлы `include` обрабатываются **первыми**, затем сливаются с основной конфигурацией `.gitlab-ci.yml`. Локальная конфигурация имеет приоритет и перезаписывает включённую.

## Базовые концепции

### Типы `include`

| Тип | Описание | Когда использовать |
| :--- | :--- | :--- |
| **`include:local`** | Файл в том же репозитории и ветке | Разделение конфигурации внутри проекта |
| **`include:project`** | Файл из другого проекта на том же экземпляре GitLab | Централизованные шаблоны для группы проектов |
| **`include:remote`** | Файл по URL | Сторонние шаблоны, публичные библиотеки |
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

### `include:project`

Подключает файл из другого проекта на том же экземпляре GitLab.

```yaml
include:
  - project: 'group/ci-templates'
    ref: v1.2.0
    file: '/docker/build.yml'
```

**Рекомендации по версионированию:**

- **Тег (SemVer):** Рекомендуется (`ref: v1.2.0`)
- **Commit SHA:** Максимальная стабильность
- **Ветка:** Не рекомендуется (нестабильно)

### `include:remote`

Подключает файл по публичному URL.

```yaml
include:
  - remote: 'https://example.com/.gitlab-ci.yml'
    integrity: 'sha256-L3/GAoKaw0Arw6hDCKeKQlV1QPEgHYxGBHsH4zG1IY8='
```

**Параметры:**

- **`integrity`**: SHA256-хеш для проверки целостности файла (GitLab 17.9+)
- **`cache`**: Время кэширования удалённого файла (GitLab 18.9+, эксперимент)

### `include:template`

Использует встроенные шаблоны GitLab (SAST, DAST и др.).

```yaml
include:
  - template: 'Security/SAST.gitlab-ci.yml'
```

### `include:component`

CI/CD компонент из каталога (GitLab 16.0+).

```yaml
include:
  - component: '$CI_SERVER_FQDN/group/component@1.0.0'
    inputs:
      stage: build
```

### Дополнительные параметры

#### `include:inputs`

Передача входных параметров в подключаемый файл (для компонентов и шаблонов с `spec:inputs`). Подробный синтаксис `spec:inputs` описан в [CI/CD Catalog](./ci_cd_catalog_components.md).

```yaml
include:
  - local: '.gitlab-ci/build.yml'
    inputs:
      environment: production
```

#### `include:rules`

Условное включение файлов.

```yaml
include:
  - local: '.gitlab-ci/deploy.yml'
    rules:
      - if: '$CI_COMMIT_BRANCH == "main"'
```

### Ограничения и приоритеты

| Ограничение | Значение |
| :--- | :--- |
| Максимум включений | **150** (включая вложенные) |
| Время ожидания | **30 секунд** |
| Приоритет слияния | Задание в `.gitlab-ci.yml` имеет **наивысший** приоритет |

## Практические сценарии

### Сценарий 1: Модульная конфигурация проекта

Разделение большого пайплайна на логические блоки внутри одного репозитория.

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

Использование общего репозитория шаблонов для стандартизации процессов.

```yaml
# В целевом проекте
include:
  - project: 'group/ci-templates'
    ref: v1.2.0
    file: '/docker-build.yml'

build:
  extends: .docker_build
```

### Сценарий 3: Условное включение (rules)

Подключение конфигураций деплоя только для соответствующих веток.

```yaml
include:
  - local: '.gitlab-ci/deploy-prod.yml'
    rules:
      - if: '$CI_COMMIT_BRANCH == "main"'
```

## Дополнительная информация

### Валидация

Для проверки синтаксиса и отладки `include` используйте GitLab CI Lint:

```bash
# Просмотр полностью развернутой конфигурации (expanded)
gitlab-ci lint --include-debug
```

### Распространённые ошибки

| Ошибка | Причина | Решение |
| :--- | :--- | :--- |
| `file does not exist` | Неправильный путь или ветка | Проверьте путь и параметр `ref` |
| `exceeded max includes` | Глубина или количество > 150 | Упростите иерархию подключений |
| `timeout waiting for include` | Файл недоступен по сети | Проверьте доступность URL для `remote` |

### Связанные документы

- **[Обзор переиспользуемых пайплайнов](./overview.md)** — сравнение всех подходов
- **[Механизм `extends`](./extends_keyword.md)** — наследование конфигураций
- **[CI/CD Catalog](./ci_cd_catalog_components.md)** — создание и использование компонентов
- **[Переменные и секреты](../../Concepts/gitlab_ci_variables_secrets.md)** — управление переменными

### Внешние ресурсы

- [Официальная документация: `include`](https://docs.gitlab.com/ci/yaml/#include)
- [Официальная документация: CI/CD Components](https://docs.gitlab.com/ci/components/)
