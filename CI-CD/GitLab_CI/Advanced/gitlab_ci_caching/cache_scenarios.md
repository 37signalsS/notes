# Практические сценарии кэширования в GitLab CI

## Требования и предварительные условия
- **Инфраструктура:** GitLab Runner с настроенным `Distributed Cache` (S3/MinIO) для гарантии доступности кэша между разными узлами.
- **Версии GitLab:** Примеры актуальны для GitLab 17.x–19.x (включая лимиты Gitaly на `cache:key:files` и алгоритмы `zstd`).

## Базовые концепции

### Принципы эффективных сценариев

1.  **Соблюдение принципа DRY (Don't Repeat Yourself):** Использование якорей YAML (`&` и `*`) или ключевого слова `!reference` для переиспользования блоков конфигурации кэша.
2.  **Асимметричные политики (`pull`, `push`, `pull-push`):**
    *   Задача установки зависимостей (например, `npm ci`) должна иметь политику `pull-push`.
    *   Задачи потребители (линтеры, тесты) должны иметь **строго** политику `pull`. Это предотвращает перезапись кэша, защищает от `Cache Poisoning` и ускоряет пайплайн (убирает фаза архивации в конце).
3.  **Детерминированная валидация (`cache:key:files`):** Привязка кэша к хэшу lock-файлов (`package-lock.json`, `poetry.lock`, `go.sum`). Если lock-файл не изменился, кэш считается актуальным.
4.  **Разделение контекстов (Множественное кэширование):** Если проект требует и `node_modules`, и `.m2` (Java), они должны лежать в разных кэшах с разными ключами. GitLab допускает до 4 кэшей на одну задачу.
5.  **Трансляция путей:** GitLab Runner архивирует только те файлы, которые находятся *внутри* `$CI_PROJECT_DIR`. Глобальные кэши инструментов (например, `~/.npm` или `~/.cache/pip`) необходимо переопределять через переменные окружения, направляя их в директорию проекта.

## Практические сценарии по языкам и технологиям

### Сценарий 1 — Node.js (NPM / Yarn / pnpm / bun)

Экосистема JavaScript сильно зависит от глубоких деревьев зависимостей. Цель — кэшировать как сами модули (`node_modules`), так и внутренний кэш пакетного менеджера.

**Вариант А: Стандартный NPM**
```yaml
variables:
  # Перенаправляем глобальный кэш npm внутрь проекта
  NPM_CONFIG_CACHE: "$CI_PROJECT_DIR/.npm"

.node_cache: &node_cache
  key:
    files: [package-lock.json]
    prefix: npm
  paths:
    - .npm/
  policy: pull

install_deps:
  stage: .pre
  cache:
    <<: *node_cache
    policy: pull-push
  script:
    # --prefer-offline ускоряет установку, используя пакеты из $NPM_CONFIG_CACHE
    - npm ci --prefer-offline

test_app:
  stage: test
  cache:
    <<: *node_cache
  script:
    - npm run test
```
*Почему не кэшируется `node_modules`?* В современных пайплайнах (особенно с Node.js) кэширование глобальной директории `.npm` эффективнее, так как `npm ci` работает детерминированно и очень быстро при наличии локального кэша пакетов, исключая проблемы с платформозависимыми бинарниками (например, `node-sass`).

**Вариант Б: Современный pnpm (2026 Standard)**
```yaml
variables:
  PNPM_STORE_PATH: "$CI_PROJECT_DIR/.pnpm-store"

cache:
  key:
    files: [pnpm-lock.yaml]
  paths:
    - .pnpm-store/

install_pnpm:
  script:
    - corepack enable pnpm
    - pnpm config set store-dir $PNPM_STORE_PATH
    - pnpm install --frozen-lockfile
```

### Сценарий 2 — Python (uv / pip / Poetry)

В 2026 году стандартом де-факто для CI/CD является `uv` благодаря его скорости (написан на Rust) и встроенному управлению окружениями.

**Вариант А: Использование `uv` (Рекомендуется)**
```yaml
variables:
  UV_CACHE_DIR: "$CI_PROJECT_DIR/.uv-cache"

.python_cache:
  cache:
    - key:
        files: [pyproject.toml, uv.lock]
      paths: [.uv-cache/]
      policy: pull

install:
  extends: .python_cache
  cache:
    - policy: pull-push
  script:
    - curl -LsSf https://astral.sh/uv/install.sh | sh
    - uv sync --frozen
```
*Механика:* `uv sync` создает виртуальное окружение `.venv` (по умолчанию в корне проекта) и использует кэшированные wheels из `.uv-cache`. 

**Вариант Б: Классический Pip + Venv**
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
  - pip install --require-hashes -r requirements.txt
```

### Сценарий 3 — Go (Golang)

Для Go необходимо разделять кэш скачанных модулей (`GOMODCACHE`) и кэш результатов компиляции (`GOCACHE`).

```yaml
variables:
  GOMODCACHE: "$CI_PROJECT_DIR/.go/pkg/mod"
  GOCACHE: "$CI_PROJECT_DIR/.go/cache/build"
  GOLANGCI_LINT_CACHE: "$CI_PROJECT_DIR/.go/cache/lint"

cache:
  key:
    files: [go.sum]
    prefix: go-v1
  paths:
    - .go/
  policy: pull-push

test_and_lint:
  image: golang:1.22
  script:
    - go mod download
    - go test -v ./...
    - golangci-lint run
```
*Почему `prefix: go-v1`?* При смене мажорной версии Go формат внутренних кэшей может меняться. Префикс позволяет быстро инвалидировать старый кэш.

### Сценарий 4 — Rust (Cargo)

Компиляция Rust крайне ресурсоемка. Cargo хранит скачанные крейты и индекс реестра.

```yaml
variables:
  CARGO_HOME: "$CI_PROJECT_DIR/.cargo"

cache:
  key:
    files: [Cargo.lock]
    prefix: rust-build
  paths:
    - .cargo/bin/
    - .cargo/registry/index/
    - .cargo/registry/cache/
    - target/
```
*Рекомендация:* Для ускорения `cargo fetch` в современных версиях используется Sparse Index (по умолчанию с Rust 1.70+). Кэширование директории `target/` значительно ускоряет инкрементальную сборку, но размер кэша может достигать нескольких гигабайт.

### Сценарий 5 — Java (Maven / Gradle)

Главная задача — сохранить загруженные `.jar` пакеты и артефакты плагинов, чтобы не выкачивать "половину интернета" при каждом запуске.

**Maven:**
```yaml
variables:
  # Переопределяем локальный репозиторий
  MAVEN_OPTS: "-Dmaven.repo.local=$CI_PROJECT_DIR/.m2/repository"

cache:
  key:
    files: [pom.xml]
  paths:
    - .m2/repository/

build_java:
  script:
    # Использование режима offline/batch для предотвращения проверок обновлений плагинов
    - mvn clean package -B -o -DskipTests 
```

**Gradle:**
```yaml
variables:
  GRADLE_USER_HOME: "$CI_PROJECT_DIR/.gradle"

cache:
  key:
    files: [build.gradle.kts, gradle/wrapper/gradle-wrapper.properties]
  paths:
    - .gradle/caches/
    - .gradle/wrapper/
```

### Сценарий 6 — PHP (Composer)

```yaml
variables:
  COMPOSER_CACHE_DIR: "$CI_PROJECT_DIR/.composer-cache"

cache:
  key:
    files: [composer.lock]
  paths:
    - .composer-cache/

install_php_deps:
  script:
    - composer install --prefer-dist --no-progress --no-suggest
```

### Сценарий 7 — Ruby (Bundler)

```yaml
variables:
  BUNDLE_PATH: "$CI_PROJECT_DIR/vendor/ruby"

cache:
  key:
    files: [Gemfile.lock]
  paths:
    - vendor/ruby

install_gems:
  script:
    - bundle config set --local path 'vendor/ruby'
    - bundle install --jobs $(nproc)
```

## Инфраструктурные и архитектурные сценарии

### Сценарий 8 — Кэширование слоёв Docker через Registry (BuildKit)

Классический `docker build` не использует GitLab Runner Cache. Вместо этого применяется кэширование внутри Docker Registry с использованием BuildKit.

```yaml
build_image:
  stage: build
  image: docker:24.0.5
  services:
    - docker:24.0.5-dind
  variables:
    DOCKER_BUILDKIT: 1
  script:
    - docker login -u $CI_REGISTRY_USER -p $CI_REGISTRY_PASSWORD $CI_REGISTRY
    - >
      docker build 
      --cache-from type=registry,ref=$CI_REGISTRY_IMAGE/cache:latest 
      --cache-to type=registry,ref=$CI_REGISTRY_IMAGE/cache:latest,mode=max 
      -t $CI_REGISTRY_IMAGE:$CI_COMMIT_SHA .
    - docker push $CI_REGISTRY_IMAGE:$CI_COMMIT_SHA
```
*Механика:* `mode=max` сохраняет метаданные и слои всех этапов multi-stage сборки. Кэш живет в `Container Registry`, а не в `Distributed Cache` GitLab'а.

### Сценарий 9 — Монорепозиторий с разделением кэша (Selective Caching)

В монорепозиториях (например, Frontend на React + Backend на Go) использование единого кэша приведет к "Gitaly Timeout" (из-за огромного количества файлов) и перерасходу сети.

```yaml
.cache_base:
  policy: pull-push
  
frontend_job:
  extends: .cache_base
  cache:
    key:
      files: [apps/frontend/package-lock.json]
    paths: [apps/frontend/.npm/]
  rules:
    - changes: [apps/frontend/**/*]
  script:
    - cd apps/frontend && npm ci

backend_job:
  extends: .cache_base
  cache:
    key:
      files: [apps/backend/go.sum]
    paths: [apps/backend/.go/]
  rules:
    - changes: [apps/backend/**/*]
  script:
    - cd apps/backend && go test ./...
```

### Сценарий 10 — Защита от холодного старта (Fallback Keys)

Использование `fallback_keys` позволяет новой feature-ветке (у которой еще нет кэша) использовать кэш от ветки `main`, избегая полной сборки с нуля.

```yaml
test_feature:
  cache:
    - key: "cache-$CI_COMMIT_REF_SLUG"
      fallback_keys:
        - "cache-$CI_DEFAULT_BRANCH" # Используем кэш main, если свой еще не создан
        - "cache-global"
      paths:
        - vendor/
  script:
    - make test
```

## Валидация и устранение неполадок

### Как убедиться, что кэш работает?
1.  **Чтение логов Runner'а:** Ищите строки `Checking cache for...`, `Downloading cache.zip from...` в начале задачи.
2.  **Время выполнения:** Задача `npm ci` с кэшем должна выполняться за секунды (вывод: `added X packages in Xs`), тогда как "холодная" сборка занимает минуты.
3.  **Сохранение кэша:** В конце задачи должна присутствовать секция `Creating cache...` и `Uploading cache.zip to...`. Если там написано `Archive is up to date!`, значит `FF_SKIP_NOOP_CACHE` работает корректно.

### Диагностика типичных ошибок

| Проблема | Причина и решение |
| :--- | :--- |
| **Gitaly Timeout при создании Pipeline** | **Причина:** Слишком много файлов в `cache:key:files` (максимум 2) или огромный монорепозиторий. **Решение:** Используйте статический ключ с префиксом или якоря YAML для сокращения конфигурации. |
| **Кэш собирается каждый раз с нуля** | **Причина:** Несовпадение ключей между ветками (Protected vs Unprotected) или пути кэша находятся ВНЕ каталога проекта (`$CI_PROJECT_DIR`). **Решение:** Используйте `fallback_keys` и проверяйте переменные путей (`X_CACHE_DIR`). |
| **Ошибка 403 при скачивании (Distributed Cache)** | **Причина:** Срок жизни (TTL) pre-signed URL от GitLab истек, либо IAM-роль Runner'а потеряла доступ к S3. **Решение:** Проверить настройки `config.toml` Runner'а и синхронизацию времени NTP. |
| **Раздувание кэша (No space left on device)** | **Причина:** Накапливание старых версий пакетов в локальных папках вроде `target/` или `node_modules/`. **Решение:** Включите регулярную инвалидацию ключа (смена префикса) или очистите кэш через UI GitLab (Clear runner caches). |

## Дополнительная информация

### Связанные документы

- **Ключи и политики:** [настройка cache:key](./cache_keys.md)
- **Концепции и механизмы:** [обзор кэширования](./caching_overview.md)
- **Рекомендации:** [лучшие практики](./cache_best_practices.md)
