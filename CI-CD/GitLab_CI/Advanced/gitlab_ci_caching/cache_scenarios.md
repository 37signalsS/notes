# Практические сценарии кэширования в GitLab CI

## Определения

**Практический сценарий кэширования** — оптимизированная конфигурация для конкретного стека технологий, минимизирующая время загрузки зависимостей и сборки артефактов.

**Якорь YAML (`&` / `*`)** — встроенный механизм переиспользования блоков кода, позволяющий избежать дублирования настроек кэша в рамках одного файла.

**BuildKit** — современный движок сборки Docker-образов, обеспечивающий эффективное кэширование слоёв и параллельное выполнение задач через Registry.

**Distributed Cache** — модель хранения, где кэш находится во внешнем хранилище (S3/MinIO), что позволяет всем Runner'ам проекта (включая масштабируемые в облаке) использовать общие данные.

**Zstd (Zstandard)** — высокоэффективный алгоритм сжатия, используемый GitLab Runner (16.2+) по умолчанию. Значительно быстрее стандартного `zip`.

## Основные концепции

### Принципы эффективных сценариев

1. **Использование якорей YAML** для соблюдения принципа DRY.
2. **Настройка политик** (`pull`, `push`, `pull-push`) для исключения лишних операций ввода-вывода.
3. **Кэширование по файлам зависимостей** для автоматической инвалидации при обновлении `lock`-файлов.
4. **Разделение кэшей** (до 4 записей) для разных экосистем (например, Node.js + Java) внутри одного проекта.
5. **Локальные пути:** Переопределение путей кэша в `$CI_PROJECT_DIR`, так как Runner архивирует только данные внутри корня проекта.
6. **Типизация через `spec:inputs`:** Динамическое формирование префиксов ключей кэша в переиспользуемых компонентах.

### Ограничения и особенности

- **Лимиты:** Максимум **4 кэша** на одну задачу.
- **Размер:** Кэш сжимается в `.zip` (или `.zstd`), размер ограничен настройками инстанса (на GitLab.com — 5ГБ).
- **Изоляция:** Кэши защищённых веток изолированы суффиксом `-protected` для предотвращения атак на цепочку поставок (Supply Chain Security).

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

### Сценарий 2 — Кэширование зависимостей Python (Pip/Poetry)

Использование виртуального окружения и локального хранилища пакетов.

**Pip:**
```yaml
variables:
  PIP_CACHE_DIR: "$CI_PROJECT_DIR/.cache/pip"

cache:
  key:
    files: [requirements.txt]
  paths:
    - .cache/pip
    - .venv/

before_script:
  - python -m venv .venv
  - source .venv/bin/activate
  - pip install -r requirements.txt
```

**Poetry:**
```yaml
variables:
  POETRY_CACHE_DIR: "$CI_PROJECT_DIR/.cache/poetry"
  POETRY_VIRTUALENVS_IN_PROJECT: "true"

cache:
  key:
    files: [poetry.lock]
  paths:
    - .cache/poetry
    - .venv/
```

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

### Сценарий 5 — Кэширование зависимостей Java (Maven/Gradle)

Обеспечение персистентности локального репозитория и оберток (wrappers) для JVM-стека.

**Maven:**
```yaml
variables:
  MAVEN_OPTS: "-Dmaven.repo.local=$CI_PROJECT_DIR/.m2/repository"

cache:
  key:
    files:
      - pom.xml
  paths:
    - .m2/repository/
```

**Gradle:**
```yaml
variables:
  GRADLE_USER_HOME: "$CI_PROJECT_DIR/.gradle"

cache:
  key:
    files:
      - build.gradle
      - gradle/wrapper/gradle-wrapper.properties
  paths:
    - .gradle/caches/
    - .gradle/wrapper/
```

### Сценарий 6 — Кэширование слоёв Docker через Registry (BuildKit)

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

### Сценарий 7 — Монорепозиторий с разделением кэша

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

### Сценарий 8 — Резервные ключи (Fallback Keys)

Использование кэша основной ветки для новых feature-веток (GitLab 16.0+ поддерживает до 5 ключей):

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

- **Кэш не обновляется:** Проверьте правильность путей в `paths` (они должны быть относительны `$CI_PROJECT_DIR`). Если хеш `lock`-файла не меняется, кэш не будет пересобран.
- **Медленная загрузка:** Большие кэши (гигабайты) могут замедлять пайплайн сильнее, чем повторная установка. Используйте `artifacts` для передачи результатов сборки и `FF_USE_FASTZIP: "true"` для ускорения работы с архивами.
- **Конфликты версий:** При обновлении мажорных версий рантаймов добавляйте статический префикс в `key:prefix`, чтобы инвалидировать несовместимый кэш.
- **Лимиты Gitaly (17.x+):** В очень больших репозиториях избегайте использования слишком большого количества файлов в `key:files`, так как это создает нагрузку на сервер при генерации пайплайна.

### Связанные документы

- **Ключи и политики:** [настройка cache:key](./cache_keys.md)
- **Концепции и механизмы:** [обзор кэширования](./caching_overview.md)
- **Рекомендации:** [лучшие практики](./cache_best_practices.md)

---

**Надёжность:** 10 (SSoT + Документация GitLab 17.x–19.x + Практический опыт)
**Свежесть:** GitLab 19.2 (2026)
**Триггеры обновления:** Появление новых пакетных менеджеров, изменения в синтаксисе BuildKit, релизы GitLab 20.x.
