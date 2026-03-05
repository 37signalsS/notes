# Типы `include`

## `include:local`

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

## `include:project`

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

## `include:remote`

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

## `include:template`

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

## `include:component`

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
