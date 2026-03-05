# GitLab CI: Каталог Компонентов — Основные концепции

## Преимущества компонентов перед `include`

| Критерий | `include:project` | CI/CD Catalog (Components) |
| :--- | :--- | :--- |
| **Версионирование** | Теги (рекомендуется) | **Semver** (обязательно для каталога) |
| **Типизация** | Нет | **Да** (`spec:inputs` с типами) |
| **Валидация** | Базовая | **Полная** (валидация inputs) |
| **Каталог** | Внешний репозиторий | **Встроенный в GitLab** (UI, поиск) |
| **Документация** | Ручная | **Автоматическая** (из `spec:inputs`) |
| **Изоляция** | Высокая | **Полная** (самодостаточные блоки) |

## Архитектура компонента

**Минимальная структура:**

```
component-repo/
├── .gitlab-ci.yml          # Метаданные: spec:inputs
└── templates/
    └── build.yml           # Основная логика компонента
```

**Или упрощённая (один файл):**

```
component-repo/
└── .gitlab-ci.yml          # spec:inputs + логика
```

## Синтаксис `spec:inputs`

```yaml
spec:
  inputs:
    <input-name>:
      default: <value>          # Необязательно: значение по умолчанию
      description: "<text>"     # Необязательно: описание для документации
      type: <string|boolean|number>  # Необязательно: тип данных
      regex: "<pattern>"        # Необязательно: валидация через regex
```

**Пример:**

```yaml
spec:
  inputs:
    stage:
      default: build
      type: string
      description: "CI stage for the job"
    
    target_branch:
      type: string
      default: main
      description: "Branch to trigger on"
      regex: '^(main|develop|feature/.*)$'
    
    enable_cache:
      type: boolean
      default: true
      description: "Enable caching"
    
    timeout:
      type: number
      default: 30
      description: "Job timeout in minutes"
```

> **Важно:** `spec:inputs` не может быть пустым. Если входы не используются, сделайте `spec:` пустым:
>
> ```yaml
> spec:
> ---
> ```

## Использование интерполяции в компонентах

Компоненты поддерживают интерполяцию переменных через синтаксис `$[[ inputs.<name> ]]`:

```yaml
# templates/build.yml
build_job:
  stage: $[[ inputs.stage ]]
  image: $[[ inputs.image ]]
  timeout: $[[ inputs.timeout ]]m
  rules:
    - if: '$CI_COMMIT_BRANCH == $[[ inputs.target_branch ]]'
  script:
    - echo "Building with cache: $[[ inputs.enable_cache ]]"
```

## Связанные документы

- [Определения](./ci_cd_catalog_definitions.md)
- [Практические сценарии](./ci_cd_catalog_scenarios.md)
- [Ограничения](./ci_cd_catalog_limits.md)
- [Справочная информация](./ci_cd_catalog_reference.md)
