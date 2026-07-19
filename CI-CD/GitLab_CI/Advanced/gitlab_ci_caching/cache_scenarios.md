# Практические сценарии кэширования в GitLab CI

## Определения

**Практический сценарий кэширования** — типовая конфигурация кэширования для распространённых задач разработки (управление зависимостями, монорепозитории, контейнерные сборки).

**Якорь YAML (`&` / `*`)** — механизм переиспользования конфигурации в GitLab CI через `&anchor_name` (объявление) и `*anchor_name` (ссылка).

**BuildKit** — современный движок сборки Docker-образов, обеспечивающий эффективное кэширование слоёв и параллельное выполнение задач.

## Основные концепции

### Принципы построения сценариев

1. **Использование якорей YAML** для переиспользования конфигурации кэша между задачами.
2. **Настройка политик** (`pull`, `push`, `pull-push`) для оптимизации времени выполнения пайплайна.
3. **Кэширование по файлам зависимостей** (`package-lock.json`, `go.sum`, `Cargo.lock`) для автоматической инвалидации кэша.
4. **Разделение кэшей** для разных экосистем внутри одного проекта (NPM + Python + Go).

### Ограничения и особенности

- **Лимиты:** Максимум 4 кэша на одну задачу.
- **Размер:** Кэш сжимается в `.zip`, размер ограничен настройками сервера.
- **Изоляция:** Кэши защищённых веток изолированы по умолчанию для предотвращения атак на цепочку поставок.

## Практические сценарии

### Сценарий 1 — Кэширование зависимостей Node.js (NPM/Yarn)

Рекомендуемый подход с использованием локального кэша NPM:

```yaml
variables:
  npm_config_cache: "$CI_PROJECT_DIR/.npm"

default:
  cache: &global_cache
    key:
      files:
        - package-lock.json
    paths:
      - node_modules/
      - .npm/
    policy: pull

install_dependencies:
  stage: .pre
  script:
    - npm ci --prefer-offline
  cache:
    <<: *global_cache
    policy: pull-push

test_job:
  stage: test
  script:
    - npm run test
  cache:
    <<: *global_cache
    policy: pull
```

**Ключевые моменты:**
- `npm ci --prefer-offline` максимально использует локальный кэш `.npm`.
- Задача `install_dependencies` выполняется в `.pre` для подготовки кэша для всего пайплайна.

### Сценарий 2 — Кэширование зависимостей Python (Pip)

Использование виртуального окружения и кэша pip:

```yaml
variables:
  PIP_CACHE_DIR: "$CI_PROJECT_DIR/.cache/pip"

cache:
  key:
    files:
      - requirements.txt
    prefix: $CI_COMMIT_REF_SLUG
  paths:
    - .cache/pip
    - .venv/

before_script:
  - python -m venv .venv
  - source .venv/bin/activate
  - pip install --cache-dir .cache/pip -r requirements.txt
```

**Ключевые моменты:**
- Использование `prefix` с именем ветки предотвращает конфликты между разными ветками разработки.

### Сценарий 3 — Кэширование зависимостей Go

Эффективное кэширование модулей и кэша компиляции:

```yaml
variables:
  GOPATH: $CI_PROJECT_DIR/.go
  GOLANGCI_LINT_CACHE: $CI_PROJECT_DIR/.golangci-lint-cache

cache:
  key:
    files:
      - go.sum
  paths:
    - .go/pkg/mod/
    - .golangci-lint-cache/
    - $CI_PROJECT_DIR/.cache/go-build

test:
  image: golang:1.21
  script:
    - go test -v ./...
```

### Сценарий 4 — Кэширование зависимостей Rust (Cargo)

Кэширование реестра и скомпилированных артефактов:

```yaml
variables:
  CARGO_HOME: $CI_PROJECT_DIR/.cargo

cache:
  key:
    files:
      - Cargo.lock
  paths:
    - .cargo/bin/
    - .cargo/registry/index/
    - .cargo/registry/cache/
    - target/
```

### Сценарий 5 — Кэширование слоёв Docker через Registry (BuildKit)

Современный способ ускорения сборки без использования `docker pull/push` вручную:

```yaml
build:
  stage: build
  image: docker:24.0.5
  services:
    - docker:24.0.5-dind
  variables:
    DOCKER_BUILDKIT: 1
  script:
    - docker build 
      --cache-from type=registry,ref=$CI_REGISTRY_IMAGE/cache:latest 
      --cache-to type=registry,ref=$CI_REGISTRY_IMAGE/cache:latest,mode=max 
      -t $CI_REGISTRY_IMAGE:$CI_COMMIT_SHA .
    - docker push $CI_REGISTRY_IMAGE:$CI_COMMIT_SHA
```

**Ключевые моменты:**
- `mode=max` сохраняет кэш всех слоёв, включая промежуточные.
- Кэш хранится в реестре образов, что делает его доступным для любых Runner'ов.

### Сценарий 6 — Монорепозиторий с разделением кэша

Использование `rules:changes` для выборочного кэширования:

```yaml
.frontend_cache: &frontend_cache
  key:
    files:
      - frontend/package-lock.json
  paths:
    - frontend/node_modules/

frontend_test:
  cache: *frontend_cache
  rules:
    - changes:
        - frontend/**/*
  script:
    - cd frontend && npm test
```

### Сценарий 7 — Резервные ключи (Fallback Keys)

Использование кэша основной ветки для новых feature-веток:

```yaml
job:
  cache:
    - key: "cache-$CI_COMMIT_REF_SLUG"
      fallback_keys:
        - "cache-$CI_DEFAULT_BRANCH"
        - "global-cache"
      paths:
        - vendor/
```

## Дополнительная информация

### Устранение типичных проблем

- **Кэш не обновляется:** Проверьте правильность путей в `paths` (они должны быть относительны `$CI_PROJECT_DIR`).
- **Медленная загрузка:** Большие кэши (гигабайты) могут замедлять пайплайн сильнее, чем повторная установка. Используйте `artifacts` для передачи результатов сборки.
- **Конфликты версий:** Если вы обновили версию языка (например, Node.js 16 -> 20), добавьте префикс в `key`, чтобы инвалидировать старый кэш.

### Связанные документы

- **Ключи и политики:** [настройка cache:key](./cache_keys.md)
- **Концепции и механизмы:** [обзор кэширования](./caching_overview.md)
- **Рекомендации:** [лучшие практики](./cache_best_practices.md)
