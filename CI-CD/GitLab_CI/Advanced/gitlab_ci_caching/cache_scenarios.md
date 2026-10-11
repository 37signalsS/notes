# Практические сценарии кэширования в GitLab CI

**Актуально для:** GitLab 18.x / GitLab Runner 19.x

## Требования и предварительные условия

### Версия GitLab и поддержка функций

| Функция | Минимальная версия | Примечание |
| :--- | :--- | :--- |
| `cache:key:files` | 11.3+ | Хеш по содержимому lock-файлов (максимум 2 файла) |
| `cache:key:files_commits` | 18.4+ | Хеш по последнему коммиту файлов (максимум 2 файла) |
| `cache:key:prefix` | 11.3+ | Статический префикс к хешу файлов |
| `cache:policy` (`pull`/`push`) | 8.10+ | Асимметричные политики |
| `cache:when` | 8.8+ | Условия сохранения кэша |
| `fallback_keys` (до 5) | 16.0+ | Цепочка поиска альтернативных ключей |
| `CACHE_FALLBACK_KEY` (глобальный) | 8.0+ | Глобальный резервный ключ для всех задач |
| `zstd` сжатие | 16.2+ | Алгоритм по умолчанию |
| `CACHE_COMPRESSION_FORMAT` | 16.2+ | Выбор алгоритма сжатия (`zip`, `zipzstd`, `tarzstd`) |
| `CACHE_COMPRESSION_LEVEL` | 16.11+ | Управление уровнем сжатия |
| `FF_SKIP_NOOP_CACHE` | 16.0+ | Пропуск пустых операций архивации |
| `unprotect` | 15.0+ | Доступ к кэшу защищённых веток |

### Необходимые знания

- Базовый синтаксис `.gitlab-ci.yml` и жизненный цикл пайплайна
- Различие между кэшем и артефактами (подробнее — в **[сравнении механизмов](./caching_overview.md)**)
- Предопределённые переменные (`$CI_COMMIT_REF_SLUG`, `$CI_JOB_NAME`, `$CI_DEFAULT_BRANCH`, `$CI_NODE_INDEX`)
- Настройка Runner'ов и локальное кэширование
- Принципы безопасного кэширования (cache poisoning, isolation) — см. **[Лучшие практики кэширования](./cache_best_practices.md#безопасность-security)**
- Параметры ключей и политики — см. **[Ключи и политики](./cache_keys.md#базовые-концепции)**

### Целевая аудитория

Справочник предназначен для DevOps-инженеров, SRE и системных администраторов, работающих с on-premise и гибридной инфраструктурой. Примеры ориентированы на оптимизацию времени сборки и безопасное кэширование зависимостей в распределённых командах Shared Runners.

## Базовые концепции

### Принципы эффективных сценариев

Данный раздел содержит краткие правила, на которых строятся сценарии ниже. Детальное объяснение параметров `cache:key`, `cache:policy`, `fallback_keys`, изоляции protected/unprotected и ограничений Gitaly см. в **[Ключи и политики](./cache_keys.md#базовые-концепции)**. Безопасность и SRE-рекомендации — в **[Лучшие практики кэширования](./cache_best_practices.md)**.

1.  **DRY и переиспользование:** Используйте якоря YAML (`&` / `*`) или `!reference` для единого определения кэша в проекте.
2.  **Асимметричные политики:** Задачи установки зависимостей — `pull-push`, задачи-потребители (линтеры, тесты) — строго `pull`.
3.  **Детерминированный ключ:** Привязывайте ключ к lock-файлам (`package-lock.json`, `go.sum`, `uv.lock`). Если lock-файл не изменился — кэш актуален.
4.  **Разделение контекстов:** Разные экосистемы (`node_modules`, `.m2`, `.venv`) требуют разных кэшей. GitLab допускает до 4 кэшей на задачу.
5.  **Трансляция путей:** Runner архивирует только файлы внутри `$CI_PROJECT_DIR`. Глобальные кэши инструментов перенаправляйте в проект через переменные окружения.

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

**Вариант А2: Упрощённый кэш (CI/CD optimized)**

Ключ может строиться только от `uv.lock` (без `pyproject.toml`), если конфигурация проекта в `pyproject.toml` редко меняется. Путь кэша можно перенаправить в стандартную директорию `.cache/uv`:

```yaml
variables:
  UV_CACHE_DIR: "$CI_PROJECT_DIR/.cache/uv"

cache:
  key:
    files:
      - uv.lock
  paths:
    - .cache/uv

install_deps:
  image: ghcr.io/astral-sh/uv:python3.13-slim
  cache:
    policy: pull-push
  script:
    - uv sync --frozen
```

**Настройка self-hosted Runner для кэширования:**

Для self-hosted Docker-раннеров необходимо в `config.toml` включить локальное кэширование и пробросить том для кэша:
```toml
[[runners]]
  name = "python-uv-runner"
  executor = "docker"
  [runners.docker]
    disable_cache = false
    volumes = [
      "/var/lib/gitlab-runner/cache:/cache",
      "/var/run/docker.sock:/var/run/docker.sock"
    ]
  [runners.cache]
    Type = "filesystem"
    Shared = true
    [runners.cache.filesystem]
      Prefix = "gitlab-cache-"
```

**Проблема кастомного индекса (nexus-proxy):**

При использовании приватного PyPI-прокси (например, Nexus) вместо публичного PyPI, `uv` меняет `uv.lock`, так как URL-источника зависимостей фиксируется внутри. Это приводит к конфликту: lock-файл, сгенерированный локально (PyPI), не совпадает с lock-файлом из CI (Nexus).

```yaml
# ОШИБКА: uv.lock изменяется между локальной сборкой и CI
install:
  variables:
    UV_INDEX_URL: "https://nexus.example.com/repository/pypi/simple/"
  script:
    - uv sync --frozen  # → FAILED: lock file mismatch
```

**Решения:**
1. **Один индекс для всех:** Используйте один и тот же `UV_INDEX_URL` в CI и локально (через `.env` или `direnv`). Lock-файл не будет меняться.
2. **Разделение lock-файлов:** Генерируйте отдельные lock-файлы для разных индексов (`uv lock --group prod --output uv.lock.ci`) и переключайте их в CI.
3. **`--no-index` + `--find-links`:** Для полностью офлайн-сборки используйте зеркалирование пакетов в локальную директорию через `uv export` и `UV_INDEX_STRATEGY=unsafe-best-match`.

*Механика:* `UV_INDEX_URL` влияет на разрешение транзитивных зависимостей. Если Nexus проксирует PyPI с задержкой, версии пакетов могут расходиться, и `uv.lock` потребует обновления.

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

### Сценарий 7.1 — C/C++ (Conan / CMake)

Для C/C++ кэшируются скачанные пакеты Conan и кэш сборки CMake. Вместо кэширования всего `build/` кэшируйте только пакеты и лог сборки.

```yaml
variables:
  CONAN_HOME: "$CI_PROJECT_DIR/.conan2"
  CMAKE_BUILD_DIR: "$CI_PROJECT_DIR/build"

cache:
  key:
    files:
      - conanfile.txt
      - CMakeLists.txt
  paths:
    - .conan2/
    - build/CMakeFiles/
    - build/CMakeCache.txt
  policy: pull-push

build:
  script:
    - conan install . --build=missing
    - cmake -B build -S .
    - cmake --build build -- -j$(nproc)
```

### Сценарий 7.2 — .NET (NuGet)

NuGet кэширует пакеты в `~/.nuget/packages`. Для детерминированной сборки используйте `packages.lock.json`.

```yaml
variables:
  NUGET_PACKAGES: "$CI_PROJECT_DIR/.nuget/packages"

cache:
  key:
    files:
      - packages.lock.json
      - Directory.Packages.props
  paths:
    - .nuget/packages/
  policy: pull-push

build:
  image: mcr.microsoft.com/dotnet/sdk:8.0
  script:
    - dotnet restore --locked-mode
    - dotnet build --no-restore
```

### Сценарий 7.3 — Perl (Carton / cpm)

Perl кэширует установленные модули. Carton использует `local/`, cpm использует `~/.perl-cpm`.

```yaml
variables:
  PERL_LOCAL_LIB_ROOT: "$CI_PROJECT_DIR/perl5"
  PERL_MB_OPT: "--install_base $CI_PROJECT_DIR/perl5"
  PERL_MM_OPT: "INSTALL_BASE=$CI_PROJECT_DIR/perl5"
  PATH: "$CI_PROJECT_DIR/perl5/bin:$PATH"

cache:
  key:
    files: [cpanfile.snapshot]
  paths:
    - perl5/

install_deps:
  script:
    - cpanm --notest --installdeps --with-recommends --with-suggests .
    - carton install
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

## DevOps/SRE и on-premise сценарии

### Сценарий 11 — Кэширование Terraform-модулей и провайдеров

Для Terraform критично кэшировать `.terraform/` (провайдеры) и промежуточные планы. Без кэша каждый запуск скачивает все провайдеры заново.

```yaml
.terraform_cache:
  cache:
    - key: terraform-providers-${TF_VERSION}-${CI_COMMIT_REF_SLUG}
      paths:
        - $TF_ROOT/.terraform/providers/
      policy: pull-push
    - key: terraform-plugins-${TF_VERSION}
      paths:
        - $TF_ROOT/.terraform/plugins/
      policy: pull
      fallback_keys:
        - terraform-plugins-latest
  variables:
    TF_VERSION: "1.9"
    TF_ROOT: "terraform/environments/staging"

terraform:plan:
  extends: .terraform_cache
  script:
    - cd $TF_ROOT
    - terraform init -backend=false
    - terraform plan -out=tfplan
  artifacts:
    paths:
      - $TF_ROOT/tfplan
    expire_in: 1 hour

terraform:apply:
  extends: .terraform_cache
  script:
    - cd $TF_ROOT
    - terraform init -backend=false
    - terraform apply -auto-approve tfplan
  dependencies:
    - terraform:plan
```

**Почему `.terraform/providers/` вместо всего `.terraform/`?** Полная директория `.terraform/` может содержать sensitive данные (state lock, backend config). Разделение позволяет безопасно кэшировать только провайдеры.

### Сценарий 12 — Кэширование Ansible-ролей и Galaxy

Ansible скачивает роли и коллекции при каждом запуске. Кэширование `roles/` и `requirements/` значительно ускоряет повторные запуски.

```yaml
ansible:lint:
  cache:
    - key: galaxy-roles-${CI_COMMIT_REF_SLUG}
      paths:
        - roles/
      policy: pull
      fallback_keys:
        - galaxy-roles-main
    - key: galaxy-collections-${CI_COMMIT_REF_SLUG}
      paths:
        - collections/
      policy: pull
  script:
    - ansible-galaxy install -r requirements.yml --roles-path roles/
    - ansible-galaxy collection install -r requirements.yml --collections-path collections/
    - ansible-lint playbooks/

ansible:deploy:
  extends: .ansible_cache
  cache:
    - policy: pull-push
  script:
    - ansible-playbook -i inventory/production site.yml
  environment:
    ANSIBLE_FORCE_COLOR: "true"
```

### Сценарий 13 — Кэширование Salt-состояний и Pillar

Salt кэширует модули и состояния. В on-premise средах с bare-metal серверами это критично для быстрых повторных.apply.

```yaml
.salt_cache:
  cache:
    - key: salt-states-${CI_COMMIT_REF_SLUG}
      paths:
        - salt/base/
      policy: pull-push
    - key: salt-modules-${SALT_VERSION}
      paths:
        - .salt/cache/
      policy: pull
      fallback_keys:
        - salt-modules-latest

salt:apply:
  extends: .salt_cache
  script:
    - salt-call --local state.apply base test=False
  environment:
    PYTHONDONTWRITEBYTECODE: "1"

salt:test:
  extends: .salt_cache
  script:
    - salt-call --local state.apply base test=True --output=json
```

### Сценарий 14 — Кэширование Helm-чартов и зависимостей

Helm скачивает зависимости при каждом `dependency build`. Кэширование `.helm/` и `charts/` ускоряет повторные запуски.

```yaml
.helm_cache:
  cache:
    - key: helm-deps-${CI_COMMIT_REF_SLUG}
      paths:
        - charts/
      policy: pull
    - key: helm-cache-${HELM_VERSION}
      paths:
        - .helm/cache/repository/
      policy: pull-push
      fallback_keys:
        - helm-cache-latest

helm:lint:
  extends: .helm_cache
  script:
    - helm dependency build charts/myapp
    - helm lint charts/myapp

helm:package:
  extends: .helm_cache
  script:
    - helm dependency build charts/myapp
    - helm package charts/myapp
  artifacts:
    paths:
      - "*.tgz"
```

### Сценарий 15 — Кэширование Docker BuildKit для multi-arch сборок

BuildKit поддерживает кэширование слоёв в registry. Для multi-arch сборок через `buildx` это значительно ускоряет повторные сборки.

```yaml
.docker_buildx_cache:
  image: docker:24.0.5
  services:
    - docker:24.0.5-dind
  variables:
    DOCKER_BUILDKIT: "1"
    BUILDX_CACHE: "$CI_REGISTRY_IMAGE/cache"

.build:setup:
  script:
    - docker buildx create --use --driver docker-container
    - docker login -u $CI_REGISTRY_USER -p $CI_REGISTRY_PASSWORD $CI_REGISTRY

.build:push:
  script:
    - >
      docker buildx build
      --platform linux/amd64,linux/arm64
      --cache-from type=registry,ref=$BUILDX_CACHE
      --cache-to type=registry,ref=$BUILDX_CACHE,mode=max
      --push -t $CI_REGISTRY_IMAGE:$CI_COMMIT_SHA .
```

### Сценарий 16 — Кэширование системных пакетов (bare-metal部署)

Для bare-metal серверов и on-premise сред кэширование системных пакетов (nginx, postgres, etc.) через local mirror или apt/yum cache.

```yaml
.deploy:bare_metal:
  cache:
    - key: apt-cache-${TARGET_OS}
      paths:
        - /var/cache/apt/archives/
      policy: pull
  script:
    - ssh deploy@server "apt-get install -y --no-install-recommends nginx postgresql-client"
  environment:
    APT_CACHE_DIR: "/var/cache/apt/archives"
```

**Примечание:** В Docker-контейнерах кэширование системных пакетов малоэффективно (контейнер ephemeral). Этот сценарий适用于 shell-раннеров на bare-metal серверах.

### Сценарий 17 — Кэширование зависимостей в Collector'ах и шардах

При шардинге тестов каждый шард должен иметь уникальный ключ.

```yaml
test:sharded:
  parallel: 8
  cache:
    - key: test-deps-$CI_NODE_INDEX-$CI_COMMIT_REF_SLUG
      paths:
        - .pytest-cache/
        - .tox/
      policy: pull-push
    - key: test-results-$CI_NODE_INDEX
      paths:
        - results-$CI_NODE_INDEX.xml
      policy: push
```

## Sysadmin: управление локальным хранилищем и наблюдаемость

### Очистка локального кэша Runner'а

Для shell-раннеров на bare-metal или VM:

```bash
# Просмотр локального кэша
ls -la /home/gitlab-runner/cache/

# Проверка размера
du -sh /home/gitlab-runner/cache/

# Очистка кэшей старше 3 дней
find /home/gitlab-runner/cache/ -name "*.zip" -mtime +3 -delete

# Автоматическая очистка через cron (root)
# /etc/cron.d/gitlab-runner-cache
0 2 * * * gitlab-runner find /home/gitlab-runner/cache/ -name "*.zip" -mtime +3 -delete
```

### Мониторинг эффективности кэширования

| Метрика | Целевое значение | Как измерить |
| :--- | :--- | :--- |
| **Cache hit rate** | > 80% | Логи Runner'а: `Checking cache for <key>... Downloading` (miss) vs `Downloading` (hit) |
| **Cache download time** | < 30 сек | Метрика `job_duration_seconds` с разбивкой по этапам |
| **Cache size** | < 1 GB на кэш | `du -sh` на директории кэша |
| **Gitaly timeout rate** | 0% | Мониторинг GitLab: `gitaly_requests_duration_seconds` |

```bash
 # Просмотр логов Runner'а для анализа кэша
 # В логах задачи ищите:
 grep -E "(Checking cache|Downloading|Creating cache|Uploading|Archive is up to date)" job.log

 # Просмотр метрик GitLab Prometheus
 curl -s "http://gitlab.example.com/-/metrics" | grep gitaly_requests_duration_seconds
```

**Примечание:** Детальную настройку Prometheus-мониторинга и рекомендации SRE по ревизии кэшей см. в **[Лучшие практики кэширования](./cache_best_practices.md#мониторинг-и-наблюдаемость)**.

## Валидация и устранение неполадок

### Как убедиться, что кэш работает?

1. **Чтение логов Runner'а:** Ищите строки `Checking cache for...`, `Downloading cache.zip from...` в начале задачи.
2. **Время выполнения:** Задача `npm ci` с кэшем должна выполняться за секунды (вывод: `added X packages in Xs`), тогда как "холодная" сборка занимает минуты.
3. **Сохранение кэша:** В конце задачи должна присутствовать секция `Creating cache...` и `Uploading cache.zip to...`. Если там написано `Archive is up to date!`, значит `FF_SKIP_NOOP_CACHE` работает корректно.
4. **Отладочные переменные:** Добавьте `CI_DEBUG_TRACE: "true"` для получения детальных логов.

### Диагностика через API

```bash
# Просмотр всех кэшей проекта
curl --header "PRIVATE-TOKEN: $TOKEN" \
  "https://gitlab.example.com/api/v4/projects/$PROJECT_ID/cache" | \
  jq '.[] | {key, size, created_at, last_used_at}'

# Очистка кэша по ключу (谨慎使用)
curl --request DELETE --header "PRIVATE-TOKEN: $TOKEN" \
  "https://gitlab.example.com/api/v4/projects/$PROJECT_ID/cache?key=$CACHE_KEY"

# Очистка всего кэша проекта
curl --request DELETE --header "PRIVATE-TOKEN: $TOKEN" \
  "https://gitlab.example.com/api/v4/projects/$PROJECT_ID/cache"
```

### Валидация конфигурации через CI Lint

```bash
# Проверка синтаксиса
curl --header "PRIVATE-TOKEN: $TOKEN" \
  --data "content=$(cat .gitlab-ci.yml | base64)" \
  "https://gitlab.example.com/api/v4/ci/lint" | jq '.valid'
```

### Диагностика локального кэша Runner'а

```bash
# Просмотр локального кэша
ls -la /home/gitlab-runner/cache/

# Проверка размера
du -sh /home/gitlab-runner/cache/

# Очистка локального кэша
rm -rf /home/gitlab-runner/cache/*

# Проверка конфигурации Runner'а (Distributed Cache)
cat /etc/gitlab-runner/config.toml | grep -A5 "\[cache\]"
```

### Диагностика типичных ошибок

| Проблема | Причина и решение |
| :--- | :--- |
| **Gitaly Timeout при создании Pipeline** | **Причина:** Слишком много файлов в `cache:key:files` (максимум 2) или огромный монорепозиторий. **Решение:** Используйте статический ключ с префиксом или якоря YAML для сокращения конфигурации. |
| **Кэш собирается каждый раз с нуля** | **Причина:** Несовпадение ключей между ветками (Protected vs Unprotected) или пути кэша находятся ВНЕ каталога проекта (`$CI_PROJECT_DIR`). **Решение:** Используйте `fallback_keys` и проверяйте переменные путей (`X_CACHE_DIR`). |
| **Ошибка 403 при скачивании** | **Причина:** Истёк pre-signed URL или неверные credentials кэш-хранилищу. **Решение:** Проверьте настройки `config.toml` Runner'а и синхронизацию времени NTP. |
| **Раздувание кэша (No space left on device)** | **Причина:** Накапливание старых версий пакетов в локальных папках вроде `target/` или `node_modules/`. **Решение:** Включите регулярную инвалидацию ключа (смена префикса) или очистите кэш через UI GitLab (Clear runner caches). |

## Infrastructure и executor-специфичные сценарии

### Сценарий 18 — Кэширование в Kubernetes executor

Kubernetes executor создаёт новый под для каждой задачи. По умолчанию кэш не персистит между подами. Для кэширования используйте PVC или Distributed Cache.

**Вариант А: PVC (Persistent Volume Claim) для локального кэша**

```yaml
cache:
  key:
    files: [package-lock.json]
    prefix: npm
  paths:
    - .npm/
  policy: pull-push
```

В `config.toml` Runner'а укажите PVC:

```toml
[[runners]]
  executor = "kubernetes"
  [runners.kubernetes]
    namespace = "gitlab-runner"
    poll_timeout = 180
    [runners.kubernetes.pod_security_context]
      run_as_user = 1000
      run_as_group = 1000
    [runners.kubernetes.volumes]
      [[runners.kubernetes.volumes.pvc]]
        name = "gitlab-runner-cache"
        claim_name = "gitlab-runner-cache-pvc"
        mount_path = "/cache"
```

**Вариант Б: emptyDir для ephemeral кэша (между стадиями внутри одного под)**

```yaml
cache:
  key:
    files: [package-lock.json]
  paths:
    - .npm/
```

```toml
[[runners]]
  executor = "kubernetes"
  [runners.kubernetes]
    namespace = "gitlab-runner"
    [runners.kubernetes.volumes]
      [[runners.kubernetes.volumes.empty_dir]]
        name = "gitlab-runner-cache"
        mount_path = "/cache"
        medium = "Memory"  # Или "HugePages" для больших кэшей
```

**Вариант В: Distributed Cache (S3/MinIO) — рекомендуется для production**

Используйте S3-совместимое хранилище для общего кэша между всеми подами:

```toml
[[runners]]
  executor = "kubernetes"
  [runners.cache]
    Type = "s3"
    Shared = true
    [runners.cache.s3]
      BucketName = "gitlab-runner-cache"
      BucketLocation = "us-east-1"
      [runners.cache.s3 Authentication]
        AccessKey = "..."
        SecretKey = "..."
```

**Валидация:** Проверьте, что кэш создаётся и загружается между задачами. В логах ищите `Downloading cache` и `Uploading cache`.

### Сценарий 19 — Кэширование сканеров безопасности (Trivy, gitleaks)

Сканеры безопасности скачивают базы уязвимостей и правила при каждом запуске. Кэширование этих данных значительно ускоряет пайплайн.

**Trivy (сканирование образов):**

```yaml
variables:
  TRIVY_CACHE_DIR: "$CI_PROJECT_DIR/.trivy-cache"

cache:
  key:
    files: [trivy.yaml]
    prefix: trivy-db
  paths:
    - .trivy-cache/
  policy: pull-push

trivy:scan:
  stage: test
  image: aquasec/trivy:latest
  script:
    - trivy image --cache-dir $TRIVY_CACHE_DIR $CI_REGISTRY_IMAGE:$CI_COMMIT_SHA
```

**gitleaks (поиск секретов):**

```yaml
variables:
  GITLEAKS_CACHE: "$CI_PROJECT_DIR/.gitleaks-cache"

cache:
  key:
    files: [.gitleaks.toml]
    prefix: gitleaks-rules
  paths:
    - .gitleaks-cache/
  policy: pull-push

secret_detection:
  stage: test
  image: zricethezav/gitleaks:latest
  script:
    - gitleaks detect --source=$CI_PROJECT_DIR --config=.gitleaks.toml
```

**Syft (генерация SBOM):**

```yaml
variables:
  SYFT_CACHE: "$CI_PROJECT_DIR/.syft-cache"

cache:
  key:
    files: [package-lock.json, go.sum]
    prefix: syft-cache
  paths:
    - .syft-cache/
  policy: pull-push

sbom:generate:
  stage: test
  image: anchore/syft:latest
  script:
    - syft dir:$CI_PROJECT_DIR -o cyclonedx-json=sbom.json
  artifacts:
    paths:
      - sbom.json
    reports:
      cyclonedx: sbom.json
```

**Валидация:** При первом запуске сканер скачает базы (минуты). При последующих — использует кэш (секунды). В логах ищите `Loading cache` или `Using cached database`.

### Сценарий 20 — Resource group для сериализации записи кэша

При параллельных задачах с `policy: pull-push` последняя завершившаяся перезаписывает кэш. Для предотвращения гонки используйте `resource_group`:

```yaml
stages:
  - build
  - test

install_deps:
  stage: build
  cache:
    key: deps-$CI_COMMIT_REF_SLUG
    paths: [node_modules/]
    policy: pull-push
  resource_group: cache-write
  script:
    - npm ci

test_1:
  stage: test
  cache:
    key: deps-$CI_COMMIT_REF_SLUG
    paths: [node_modules/]
    policy: pull
  script:
    - npm test

test_2:
  stage: test
  cache:
    key: deps-$CI_COMMIT_REF_SLUG
    paths: [node_modules/]
    policy: pull
  script:
    - npm test
```

**Важно:** `resource_group` serializes только задачи с одинаковым именем группы. Задачи `test_1` и `test_2` могут выполняться параллельно, а `install_deps` будет ждать завершения предыдущей записи.

**Режимы `resource_group_process_mode`:**

| Режим | Поведение | Когда использовать |
| :--- | :--- | :--- |
| `unordered` | По готовности раннеров | Базовая сериализация |
| `oldest_first` | По порядку создания | Критические деплои, миграции БД |
| `newest_first` | Приоритет свежей задачи | CD, где важен только актуальный код |
| `newest_ready_first` | Свежая из готовых | Сложные `rules` с фильтрацией |

Детальный разбор — в **[Матричные сборки и сериализация](../workflow_rules/matrix_builds_and_serialization.md)**.

## Лучшие практики

Общие рекомендации по выбору ключей, политик и организации кэша собраны в отдельном файле: **[Лучшие практики кэширования](./cache_best_practices.md)**. Там детально разобраны Gitaly Load, безопасность, мониторинг и SRE-стратегии. В этом файле практические сценарии уже следуют этим правилам.

## Граничные случаи и ограничения

Технические лимиты и редкие сценарии поведения кэша детально описаны в **[Ключи и политики](./cache_keys.md#граничные-случаи-и-ограничения)**. Здесь оставлены только специфичные для практических сценариев комментарии.

## Дополнительная информация

### Связанные документы

- **[Ключи и политики](./cache_keys.md)** — детальный справочник параметров `cache:key`.
- **[Обзор кэширования](./caching_overview.md)** — архитектура, уровни хранения, сравнение с артефактами.
- **[Лучшие практики](./cache_best_practices.md)** — детальный разбор Gitaly Load и стратегий.
- **[Артефакты в GitLab CI](./gitlab_ci_artifacts.md)** — передача данных между стадиями.
- **[Кэш и директивки пайплайна](./cache_pipeline_directives.md)** — взаимодействие `rules`, `needs`, `interruptible` и `resource_group` с кэшем.
- **[Кэш в downstream-пайплайнах](./cache_downstream_pipelines.md)** — наследование кэша в parent-child и multi-project пайплайнах.
- **[Кэш и executor'ы](./cache_executor_specifics.md)** — особенности кэширования для Docker, Shell, Kubernetes и Instance executor'ов.
- **[Матричные сборки и сериализация](../workflow_rules/matrix_builds_and_serialization.md)** — изоляция кэша в матричных задачах.
