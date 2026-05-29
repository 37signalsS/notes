# Ключи кэша и политики в GitLab CI

## Определения

**Ключ кэша (`cache:key`)** — уникальный идентификатор, определяющий область и версию кэша. При изменении ключа GitLab создаёт новый кэш.

**Политика кэширования (`cache:policy`)** — параметр, определяющий режим работы с кэшем: загрузка (`pull`), сохранение (`push`) или оба действия (`pull-push`).

**Fallback key** — резервный ключ, используемый для поиска кэша, если основной ключ не найден.

## Основные концепции

### Типы ключей

#### Статический ключ

```yaml
cache:
  key: "global-npm-cache"
  paths:
    - node_modules/
```

**Использование:** Глобальный кэш для всех задач и веток. Не рекомендуется для production из-за риска устаревания кэша.

#### Динамический ключ (переменные)

```yaml
cache:
  key: "$CI_COMMIT_REF_SLUG"
  paths:
    - vendor/
```

**Использование:** Раздельный кэш для разных веток. Полезно для изоляции кэша между feature-ветками.

#### Ключ по файлам зависимостей (рекомендуется)

```yaml
cache:
  key:
    files:
      - package-lock.json
      - Gemfile.lock
  paths:
    - node_modules/
    - vendor/ruby
```

**Использование:** Кэш автоматически обновляется при изменении файлов зависимостей. Оптимальный выбор для большинства сценариев.

#### Ключ по коммитам файлов

```yaml
cache:
  key:
    files_commits:
      - package.json
      - requirements.txt
  paths:
    - dependencies/
```

**Использование:** Кэш обновляется при изменении содержимого файлов (а не только их наличия). Требует GitLab 14.0+.

### Суффиксы ключей для защищённых веток

Для защищённых веток GitLab автоматически добавляет суффиксы к ключам кэша:

| Сценарий | Суффикс |
| :--- | :--- |
| Защищённая ветка + роль Maintainer/Owner | `-protected` |
| Незащищённая ветка или роль Developer | `-non_protected` |

**Пример:** `main-protected` vs `feature-non_protected`

### Политики кэширования

| Политика | Описание | Когда использовать |
| :--- | :--- | :--- |
| `pull-push` (по умолчанию) | Загружает и сохраняет кэш | Задачи, которые обновляют зависимости |
| `pull` | Только загружает, не сохраняет | Задачи, которые только потребляют кэш (тесты, линтеры) |
| `push` | Только сохраняет, не загружает | Задачи, которые только создают кэш |

### Резервные ключи (Fallback Keys)

Fallback keys позволяют использовать резервный кэш, если основной не найден:

```yaml
test:
  cache:
    - key: cache-$CI_COMMIT_REF_SLUG
      fallback_keys:
        - cache-$CI_DEFAULT_BRANCH
        - cache-main
      paths:
        - vendor/ruby
```

**Порядок поиска:**

1. `cache-$CI_COMMIT_REF_SLUG`
2. `cache-$CI_DEFAULT_BRANCH`
3. `cache-main`
4. Без кэша → создание нового

## Практические сценарии

### Сценарий 1: Переопределение политики в задачах

```yaml
default:
  cache: &global_cache
    key: "$CI_COMMIT_REF_SLUG"
    paths:
      - node_modules/
    policy: pull-push

install_deps:
  stage: build
  script:
    - npm ci
  cache:
    <<: *global_cache
    policy: pull-push

test:
  stage: test
  script:
    - npm test
  cache:
    <<: *global_cache
    policy: pull
```

### Сценарий 2: Глобальный fallback через переменные

```yaml
variables:
  CACHE_FALLBACK_KEY: fallback-key

job:
  cache:
    key: "$CI_COMMIT_REF_SLUG"
    paths:
      - binaries/
```

### Сценарий 3: Раздельные кэши для разных компонентов

```yaml
test:
  cache:
    - key:
        files:
          - Gemfile.lock
      paths:
        - vendor/ruby
      policy: pull-push

    - key:
        files:
          - yarn.lock
      paths:
        - .yarn-cache/
      policy: pull-push

    - key:
        files:
          - requirements.txt
      paths:
        - .venv/
      policy: pull
```

## Дополнительная информация

### Ограничения

- Максимум 4 кэша на задачу
- Размер кэша ограничен настройками сервера GitLab
- Fallback keys требуют GitLab 14.0+

### Рекомендации по выбору ключей

1. **Для зависимостей** — используйте ключи по файлам (`package-lock.json`, `Gemfile.lock`)
2. **Для временных файлов** — используйте динамические ключи по веткам
3. **Для общих данных** — используйте статические ключи с осторожностью
4. **Для production** — избегайте статических ключей из-за риска устаревания кэша

### Troubleshooting

Для решения проблем с кэшем см. [лучшие практики](./cache_best_practices.md), [обзор механизма](./caching_overview.md) и [практические сценарии](./cache_scenarios.md).
