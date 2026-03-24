# Ключи кэша и политики в GitLab CI

## Ключ кэша (`cache:key`)

Ключ определяет уникальность кэша. При изменении ключа GitLab создаёт новый кэш.

## Типы ключей

### 1. Статический ключ

```yaml
cache:
  key: "global-npm-cache"
  paths:
    - node_modules/
```

**Использование:** Глобальный кэш для всех задач и веток.

### 2. Динамический ключ (переменные)

```yaml
cache:
  key: "$CI_COMMIT_REF_SLUG"  # Разный кэш для каждой ветки
  paths:
    - vendor/
```

**Использование:** Раздельный кэш для разных веток.

### 3. Ключ по файлам зависимостей (рекомендуется)

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

**Использование:** Кэш автоматически обновляется при изменении файлов зависимостей.

### 4. Ключ по коммитам файлов

```yaml
cache:
  key:
    files_commits:
      - package.json
      - requirements.txt
  paths:
    - dependencies/
```

**Использование:** Кэш обновляется при изменении содержимого файлов (а не только их наличия).

## Суффиксы ключей

Для защищённых веток GitLab автоматически добавляет суффиксы:

| Сценарий | Суффикс |
| :--- | :--- |
| Защищённая ветка + роль Maintainer/Owner | `-protected` |
| Незащищённая ветка или роль Developer | `-non_protected` |

**Пример:** `main-protected` vs `feature-non_protected`

---

## Политики кэширования (`cache:policy`)

| Политика | Описание | Когда использовать |
| :--- | :--- | :--- |
| `pull-push` (по умолчанию) | Загружает и сохраняет кэш | Задачи, которые обновляют зависимости |
| `pull` | Только загружает, не сохраняет | Задачи, которые только потребляют кэш (тесты) |
| `push` | Только сохраняет, не загружает | Задачи, которые только создают кэш |

### Пример переопределения политики

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
    policy: pull-push  # Обновляет кэш

test:
  stage: test
  script:
    - npm test
  cache:
    <<: *global_cache
    policy: pull  # Только использует кэш
```

---

## Резервные ключи (Fallback Keys)

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

### Порядок поиска

1. `cache-$CI_COMMIT_REF_SLUG`
2. `cache-$CI_DEFAULT_BRANCH`
3. `cache-main`
4. Без кэша → создание нового

### Глобальный fallback

```yaml
variables:
  CACHE_FALLBACK_KEY: fallback-key

job:
  cache:
    key: "$CI_COMMIT_REF_SLUG"
    paths:
      - binaries/
```

## Связанные документы

- **[Кэширование и артефакты — Обзор](./caching_overview.md)** — общая информация
- **[Артефакты](./artifacts.md)** — конфигурация артефактов
- **[Лучшие практики](./cache_best_practices.md)** — оптимизация и troubleshooting
- **[Сценарии кэширования](./cache_scenarios.md)** — практические примеры
