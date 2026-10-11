# Сборка в монорепозиториях (Monorepo Build Systems)

**Актуально для:** self-hosted CI/CD (GitLab CI, GitHub Actions, Jenkins) 2024–2026

> Область применения: практики DevOps, SRE и SysAdmin при эксплуатации самостоятельно развёрнутых систем. Материалы, относящиеся к публичным облакам и технологиям искусственного интеллекта, не рассматриваются.

## Определения

- **Монорепозиторий (Monorepo)** — подход, при котором исходный код нескольких проектов, библиотек или сервисов хранится в едином репозитории. Противоположность polyrepo (отдельный репозиторий на каждый сервис).
- **Инкрементальная сборка (Incremental Build)** — сборка только изменённых модулей и их зависимостей, а не всего кодового дерева.
- **Remote Build Cache** — централизованное хранилище артефактов сборки (зависимости, промежуточные слои), разделяемое между раннерами для ускорения повторных сборок.
- **Dependency Graph** — граф зависимостей между модулями/пакетами в репозитории; используется для определения затронутых изменением модулей.
- **Build System** — инструмент, управляющий процессом компиляции, кэшированием и зависимостями (Bazel, Nx, Turborepo, Gradle, Maven, Pants, Buck2).
- **Affected Build** — сборка только тех модулей, которые затронуты изменением (по dependency graph).
- **Hermetic Build** — изолированная сборка, при которой все зависимости явно объявлены и не зависят от состояния окружения.
- **Task Graph / Pipeline Graph** — направленный граф задач (build, test, lint) с зависимостями между проектами.
- **Workspace Tool** — инструмент управления workspace-зависимостями в JS/TS-монорепозиториях (pnpm workspaces, Yarn workspaces, npm workspaces).
- **Change Sets / Changesets** — механизм версионирования и публикации пакетов в монорепо, фиксирующий изменения между релизами.
- **Rush** — оркестратор задач и политик от Microsoft для больших JS/TS-монорепозиториев с кэшированием и change tracking.
- **Pants** — система сборки от ThoughtWorks, ориентированная на Python-монорепозитории с hermetic builds.

## Основные концепции

### Проблемы монорепозиториев в CI/CD

Без специальных подходов монорепозиторий создаёт bottlenecks:

1. **Долгие сборки:** Каждый пуш запускает сборку всего репозитория, даже если изменён один модуль.
2. **Flaky-тесты на чужом коде:** Падение теста в модуле A блокирует деплой модуля B.
3. **Resource contention:** Параллельные джобы разных команд конкурируют за слоты раннеров.
4. **Cache invalidation:** Общий кэш быстро загрязняется, а изоляция по проектам отсутствует.
5. **Дрейф lock-файлов:** В JS/TS-монорепо частые изменения `pnpm-lock.yaml`/`package-lock.json` инвалидируют кэш даже при неизменном коде.
6. **Версионное рассинхронизация:** При отсутствии Changesets отдельные пакеты в монорепо могут накапливать несовместимые изменения.

### Архитектура сборки монорепозитория

```
Commit → Change Detection → Dependency Graph → Affected Modules → Incremental Build → Test → Artifact
```

1. **Change Detection:** Определение изменённых файлов/модулей между коммитом и базовой веткой.
2. **Dependency Graph:** Построение графа для определения затронутых модулей.
3. **Affected Modules:** Фильтрация: сборке подлежат только изменённые модули + их потребители.
4. **Incremental Build:** Выполнение сборки только для затронутых модулей.
5. **Remote Cache:** Загрузка/выгрузка промежуточных артефактов в центральный кэш.

### Self-hosted Remote Build Cache

Для self-hosted окружений remote cache разворачивается on-prem:

- **Bazel:** `bazel-remote` (от Buchgr) — open-source реализация, хранящая содержимое на диске с LRU-эвикцией и бэкендами S3/GCS/Azure Blob. Docker-образы: `buchgr/bazel-remote-cache`, `quay.io/bazel-remote/bazel-remote`. Текущая версия `v2.6.1`. Поддерживает HTTP REST и gRPC-протоколы.
- **Gradle:** Встроенная поддержка remote build cache через плагин `com.gradle.build-cache` с бэкендами S3 (через плагин `androidx.build.gradle.s3buildcache`), HTTP или самописным сервером. Альтернативы: `buildless` (drop-in), `org.hiero.gradle.feature.build-cache`.
- **Nx:** Self-hosted Nx Cloud или собственный сервер кэша. Официально поддерживается on-prem развёртывание.
- **Turborepo:** Официально поддерживает только Vercel Remote Cache. Для on-prem требуется S3-совместимый бакет (MinIO, Ceph RGW), но это не официальный продукт Vercel.
- **Подпись кэша:** Для предотвращения cache poisoning используется секретный ключ (`TURBO_REMOTE_CACHE_SIGNATURE_KEY` для Turborepo, аналогичные механизмы для Nx).

### Инструменты сборки монорепозиториев

| Инструмент | Язык/Экосистема | Incremental Build | Remote Cache | DAG | Примечание |
|:---|:---|:---|:---|:---|:---|
| **Bazel** | Polyglot (Java, Go, Python, C++, JS) | Да (action graph) | Да (HTTP/gRPC, bazel-remote) | Да | Самый строгий, требует hermetic builds |
| **Nx** | JS/TS (Node.js) | Да (affected command) | Да (Nx Cloud, self-hosted) | Да | Лучший DX для JS-монорепозиториев |
| **Turborepo** | JS/TS (Node.js) | Да (hash-based) | Да (Vercel Remote Cache, S3 on-prem) | Да | Проще Nx, хорошо интегрируется с Vercel |
| **Gradle** | JVM (Java, Kotlin, Groovy) | Да (task avoidance, build cache) | Да (build cache, HTTP/GRPC/S3) | Да | Enterprise-стандарт для JVM |
| **Maven** | JVM (Java) | Частично (incremental build, reactor) | Да (build cache) | Ограниченно | Менее гибкий, чем Gradle |
| **Buck2** | Polyglot (Rust, Java, Python) | Да (action graph) | Да (remote cache) | Да | От Facebook/Meta, стабилен в 2026 |
| **Pants** | Polyglot (Python-first, JS, Go, Rust) | Да ( hermetic, fine-grained) | Да (remote cache, HTTP) | Да | Лучший выбор для Python-монорепо |
| **Rush** | JS/TS (Node.js) | Да (сборка по changesets) | Нет (через отдельные инструменты) | Ограниченно | Microsoft, для крупных организаций |

### Сравнение Bazel, Nx и Turborepo

| Критерий | Bazel | Nx | Turborepo |
|:---|:---|:---|:---|
| **Подход** | Hermetic builds, action graph | Affected + task pipeline | Hash-based pipeline |
| **Кэширование** | Content-addressable, GRPC/HTTP | Nx Cloud / self-hosted | Remote Cache (Vercel / S3 on-prem) |
| **DAG** | Да (action graph) | Да (task graph) | Да (pipeline graph) |
| **Remote Execution** | Да (REAPI) | Ограниченно | Нет |
| **Сложность внедрения** | Высокая | Средняя | Низкая |
| **Экосистема** | Polyglot | JS/TS | JS/TS |

### Workspace package managers

В JS/TS-монорепо выбор менеджера пакетов влияет на хэш задач и remote cache:

- **pnpm (рекомендуемый стандарт 2026):** Контентно-адресуемое хранилище (`/pnpm/store`), workspace Protocol, строгая изоляция зависимостей. Фиксируйте workspace Protocol в `pnpm-workspace.yaml`, иначе hoisting ломает reproducible builds.
- **Yarn Modern (Berry):** Plug'n'Play или node_modules linker, PnP требует особой настройки в CI.
- **npm workspaces:** Встроенная поддержка, но менее эффективное кэширование, чем pnpm.

### Управление версиями в монорепо

- **Changesets:** Автоматизация версионирования и changelog для множества пакетов в одном репозитории. PR с changeset описывает изменения; авто-версия и публикация происходят через GitHub Action или скрипт.
- **Lerna:** Управление версиями и publishing, актуален для legacy JS-монорепо; в 2026 предпочтительнее Changesets или Nx release.
- **Rush:** Встроенный change tracking и policy enforcement; подходит для организаций с жёсткими требованиями к версионированию.

## Практические сценарии

### Предпосылки

Перед внедрением инкрементальной сборки убедитесь, что окружение готово:

- **CI-система:** GitLab CI, GitHub Actions или Jenkins с поддержкой DAG, matrix strategies и артефактов.
- **Fixated tool versions:** Фиксированные версии Bazel/Nx/Turborepo/Gradle в lock-файлах или CI-образах. Разные версии меняют хэш зависимостей и ломают remote cache.
- **Self-hosted runners:** Доступные раннеры с идентичным окружением (образы, версии инструментов).
- **Remote cache backend:** Развёрнутый on-prem сервер кэша (bazel-remote, MinIO, Nexus, Nx self-hosted).
- **Секреты CI:** Токены доступа к remote cache, подписи кэша, registry credentials.
- **Git shallow clone:** Включён `GIT_DEPTH`, но достаточно глубокий для affected-анализа относительно базовой ветки.

### Сценарий 1: Bazel + GitLab CI (Go + Python)

#### Структура
```
monorepo/
├── BUILD.bazel
├── apps/
│   ├── service-a/
│   │   └── BUILD.bazel
│   └── service-b/
│       └── BUILD.bazel
├── libs/
│   ├── shared-go/
│   │   └── BUILD.bazel
│   └── shared-py/
│       └── BUILD.bazel
└── .bazelrc
```

#### .gitlab-ci.yml
```yaml
stages:
  - affected
  - build
  - test
  - deploy

affected:
  stage: affected
  image: bazel:9.2.0
  script:
    - bazel query "kind(.*_binary, //apps/...)" --output=label | grep -v "//apps/service-a" > affected.txt
  artifacts:
    paths: [affected.txt]

build_service_a:
  stage: build
  needs: [affected]
  image: bazel:9.2.0
  script:
    - bazel build --remote_cache=http://cache.internal:9092 //apps/service-a:binary
  cache:
    key: bazel-cache
    paths: [~/.cache/bazel]

test_service_a:
  stage: test
  needs: [build_service_a]
  image: bazel:9.2.0
  script:
    - bazel test //apps/service-a:test
```

#### Валидация
- При изменении только `service-a` собирается и тестируется только он.
- При изменении `shared-go` собираются оба сервиса.
- Время пайплайна сокращается на 70–90% по сравнению с полной сборкой.

### Сценарий 2: Nx + GitHub Actions (React + Node.js)

#### Структура
```
monorepo/
├── nx.json
├── apps/
│   ├── web/
│   ├── mobile/
│   └── admin/
├── libs/
│   ├── ui/
│   └── utils/
└── package.json
```

#### .github/workflows/ci.yml
```yaml
name: CI
on:
  push:
    branches: [main]
  pull_request:
    branches: [main]

jobs:
  affected:
    runs-on: ubuntu-latest
    outputs:
      apps: ${{ steps.affected.outputs.apps }}
    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 0
      - uses: actions/setup-node@v4
        with:
          node-version: 22
          cache: 'npm'
      - run: npm ci
      - id: affected
        run: |
          npx nx affected:graph --base=origin/main --head=${{ github.sha }} > affected.json
          jq -r '.nodes[].name' affected.json | grep -E "^apps/" > affected-apps.txt
          echo "apps=$(cat affected-apps.txt | tr '\n' ',')" >> $GITHUB_OUTPUT

  build:
    needs: affected
    runs-on: ubuntu-latest
    strategy:
      matrix:
        app: ${{ fromJson(needs.affected.outputs.apps) }}
    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 0
      - uses: actions/setup-node@v4
        with:
          node-version: 22
          cache: 'npm'
      - run: npm ci
      - run: npx nx run ${{ matrix.app }}:build --with-deps
        env:
          NX_CLOUD_ACCESS_TOKEN: ${{ secrets.NX_CLOUD_TOKEN }}
```

#### Валидация
- `npx nx affected:graph` показывает только затронутые приложения.
- При изменении `libs/ui` пересобираются все зависимые приложения.
- Nx Remote Cache (self-hosted) ускоряет повторные сборки на 50–80%.

### Сценарий 3: Turborepo + GitLab CI (Next.js + Prisma)

#### Структура
```
monorepo/
├── turbo.json
├── apps/
│   ├── web/
│   └── docs/
├── packages/
│   ├── ui/
│   ├── db/
│   └── config/
└── package.json
```

#### turbo.json
```json
{
  "pipeline": {
    "build": {
      "dependsOn": ["^build"],
      "outputs": [".next/**", "!.next/cache/**"]
    },
    "test": {
      "dependsOn": ["build"],
      "outputs": ["coverage/**"]
    },
    "lint": {
      "dependsOn": ["^lint"]
    }
  }
}
```

#### .gitlab-ci.yml
```yaml
stages:
  - build
  - test
  - deploy

build:
  stage: build
  image: node:22
  script:
    - turbo run build --filter=...[origin/main] --cache
  cache:
    key: turbo-cache
    paths: [node_modules/.cache/turbo]

test:
  stage: test
  image: node:22
  script:
    - turbo run test --filter=...[origin/main]
```

### Сценарий 4: Gradle + Remote Build Cache (Java/Kotlin)

#### settings.gradle.kts
```kotlin
rootProject.name = "monorepo"
include("service-a", "service-b", "shared-lib")
```

#### build.gradle.kts (root)
```kotlin
plugins {
    id("org.gradle.caching") version "8.11"
}
```

#### .gitlab-ci.yml
```yaml
stages:
  - affected
  - build
  - test

affected:
  stage: affected
  image: gradle:8.11-jdk17
  script:
    - git diff --name-only HEAD^ HEAD > changed.txt
    - gradle :affected > affected-modules.txt
  artifacts:
    paths: [affected-modules.txt]

build_service:
  stage: build
  needs: [affected]
  image: gradle:8.11-jdk17
  script:
    - gradle build --build-cache --remote-cache=http://cache.internal:9092
  cache:
    key: gradle-cache
    paths: [~/.gradle/caches/]
```

### Сценарий 5: Change Detection для монорепозитория

#### Bash-скрипт (универсальный)
```bash
#!/usr/bin/env bash
set -euo pipefail

BASE_REF="${1:-origin/main}"
HEAD_REF="${2:-HEAD}"

CHANGED=$(git diff --name-only "$BASE_REF" "$HEAD_REF")
AFFECTED=$(echo "$CHANGED" | awk -F'/' '{print $1}' | sort -u)

KNOWN_MODULES="apps/web apps/mobile libs/ui libs/utils"
MODULES=""
for module in $AFFECTED; do
  if echo "$KNOWN_MODULES" | grep -qw "$module"; then
    MODULES="$MODULES $module"
  fi
done

echo "$MODULES" | tr ' ' '\n' | sort -u
```

#### Использование в пайплайне
```yaml
detect_changes:
  stage: affected
  script:
    - ./detect-changes.sh origin/main $CI_COMMIT_SHA > affected-modules.txt
  artifacts:
    paths: [affected-modules.txt]

build_module:
  stage: build
  needs: [detect_changes]
  script:
    - MODULE=$(cat affected-modules.txt | grep -E "^$MODULE_NAME$" | head -1)
    - if [ -n "$MODULE" ]; then bazel build //$MODULE:all; fi
```

### Сценарий 6: Changesets + GitHub Actions (JS/TS версионирование)

#### Структура
```
monorepo/
├── .changeset/
├── packages/
│   ├── ui/
│   └── utils/
└── package.json
```

#### .github/workflows/changesets.yml
```yaml
name: Changesets
on:
  push:
    branches: [main]

jobs:
  version:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 0
      - uses: actions/setup-node@v4
        with:
          node-version: 22
          cache: 'pnpm'
      - run: corepack enable pnpm
      - run: pnpm install --frozen-lockfile
      - run: pnpm changeset version
      - run: pnpm install --frozen-lockfile
      - run: git push origin main --follow-tags
```

#### Валидация
- PR с changeset создаёт changelog-запись.
- Merge в main запускает версионирование и теги.
- Зависимости между пакетами обновляются автоматически.

## Ограничения и крайние случаи

- **Глубокие зависимости:** Если модуль A зависит от B, а B от C, изменение в C затрагивает A. Dependency graph должен учитывать транзитивные зависимости.
- **Cache poisoning:** Общий remote cache между проектами — поверхность атаки. Изолируйте кэш по проекту/группе; используйте подпись кэша.
- **Cold start:** При пустом remote cache первая сборка монорепозитория может занимать часы. Требуется seeding кэша или baseline сборка.
- **Hermetic builds:** Bazel/Pants требуют hermetic builds (все зависимости изолированы). Нарушение этого принципа приводит к flaky-сборкам.
- **Large monorepos (>100k files):** Bazel action graph может занимать гигабайты RAM. Требуется выделенный сервер для remote caching и execution.
- **Mixed ecosystems:** Монорепозиторий с Java + JS + Go требует универсального инструмента (Bazel, Pants) или отдельных конфигураций для каждого языка.
- **Force-push в main:** Affected-анализ относительно `origin/main` даёт корректный результат только при линейной истории. При force-push используйте merge-base или защищайте ветку политикой `no force push`.
- **Circular dependencies:** Циклы в графе зависимостей приводят к неочевидным ошибкам CI. Визуализируйте граф (`bazel query`, `nx graph`, `turbo run build --graph`) для поиска циклов.
- **Ephemeral runners:** При использовании эфемерных раннеров локальный кэш не сохраняется между джобами, поэтому remote cache обязателен.
- **Lock-файл дрейф:** Частые обновления lock-файлов (npm audit, dependabot) инвалидируют remote cache. Используйте отдельный lock-файл для CI или отключайте автоматические обновления в пайплайне.

## Лучшие практики

1. **Фиксируйте версии инструментов:** Bazel, Nx, Turborepo, Gradle, Node.js — всё должно иметь pinned версию в CI-образах и lock-файлах.
2. **Используйте affected-фильтрацию:** Никогда не собирайте весь репозиторий без необходимости. Включайте `--filter=...[origin/main]` или аналог.
3. **Включайте remote cache с подписью:** Предотвращает cache poisoning и обеспечивает reproducibility между раннерами.
4. **Изолируйте кэш по проекту:** Не используйте общий remote cache между разными командами/сервисами без политик доступа.
5. **Кэшируйте по lock-файлам:** `cache:key` должен зависеть от `pnpm-lock.yaml`/`package-lock.json`/`go.sum`/`build.gradle`, а не от ветки.
6. **Ограничивайте параллелизм:** Используйте `concurrency` в CI, чтобы не перегружать раннеры и внешние сервисы (artifact registry, CDN).
7. **Мониторинг hit rate:** Alert на падение remote cache hit rate < 80% — это признак сломанного кэша или отравления.
8. **Parent-child пайплайны для больших монорепо (>50 пакетов):** Родительский пайплайн вычисляет affected-список, дочерний выполняет задачи. Ускоряет создание пайплайна.
9. **Reproducible builds:** Фиксируйте Node.js в `.nvmrc`, используйте `--frozen-lockfile`, отключайте недетерминированные вставки.
10. **Валидация affected-списка:** Перед деплоем запустите dry-run и проверьте, что в списке нет неизменённых приложений.

## Валидация

- **Affected detection:** после настройки запустите `turbo run build --filter=...[origin/main] --dry=json` или `npx nx affected:graph` и убедитесь, что список затронутых пакетов соответствует реальным изменениям.
- **Remote cache hit rate:** в отчёте Turborepo есть поле `FULL TURBO` / `FULL TURBO REMOTE` — hit rate должен быть >80% для стабильного репозитория. Для Bazel проверяйте логи `bazel-remote` на долю cache hits.
- **Cache integrity:** после настройки подписи кэша убедитесь, что при передаче кэша между раннерами не возникает `Signature verification failed` или `Cache miss` при ожидаемом хите.
- **Reproducibility:** в CI добавьте `node --version` / `bazel --version` / `gradle --version` в логи и сравните с зафиксированными версиями; расхождение ломает reproducibility.
- **Deploy list validation:** перед деплоем запустите dry-run и проверьте, что в списке нет неизменённых приложений.

## Дополнительная информация

### См. также

- **[Монорепозитории в GitLab CI/CD](../GitLab_CI/Advanced/gitlab_monorepo_ci.md)** — стратегии CI/CD для монорепозиториев.
- **[Монорепо CI для фронтенда](../Frontend_CI_CD/monorepo_frontend_ci.md)** — Turborepo/Nx в деталях, remote cache на on-prem, validation.
- **[Инкрементальные сборки в CI/CD](../Core_Concepts/cost-optimization.md)** — оптимизация затрат на сборку.
- **[Кэширование в GitLab CI](../GitLab_CI/Advanced/gitlab_ci_caching/caching_overview.md)** — распределённый кэш для GitLab Runner.
- **[Архитектура пайплайнов](../Core_Concepts/pipeline_architecture.md)** — паттерны построения конвейеров.
- **[Автоматизация зависимостей](../dependency_automation.md)** — Renovate/Dependabot, lock-файлы, SCA.
- **[Управление артефактами](../artifact_management.md)** — реестры пакетов, промоушн артефактов.
