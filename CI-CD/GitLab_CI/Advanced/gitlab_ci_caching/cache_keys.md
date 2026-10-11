# Ключи кэша и политики в GitLab CI

**Актуально для:** GitLab 18.x / GitLab Runner 19.x

## Требования и предварительные условия

### Версия GitLab и поддержка функций

| Функция | Минимальная версия | Примечание |
| :--- | :--- | :--- |
| `cache:key` (статический/динамический) | 8.0+ | Базовая поддержка ключей |
| `cache:key:files` | 11.3+ | Хеш по содержимому файлов (максимум 2 файла) |
| `cache:key:files_commits` | 18.4+ | Хеш по последнему коммиту файлов (максимум 2 файла) |
| `cache:key:prefix` | 11.3+ | Статический префикс к хешу файлов |
| `cache:policy` (`pull`/`push`) | 8.10+ | Управление направлением передачи |
| `cache:when` | 8.8+ | Условия сохранения кэша |
| `fallback_keys` (до 5) | 16.0+ | Расширенная цепочка поиска |
| `unprotect` | 15.0+ | Доступ к кэшу защищённых веток |
| `zstd` сжатие | 16.2+ | Алгоритм сжатия по умолчанию |
| `CACHE_COMPRESSION_LEVEL` | 16.11+ | Управление уровнем сжатия |
| `CACHE_COMPRESSION_FORMAT` | 16.2+ | Выбор алгоритма сжатия (`zip`, `zipzstd`, `tarzstd`) |
| `FF_SKIP_NOOP_CACHE` | 16.0+ | Пропуск загрузки при отсутствии изменений |
| `CACHE_FALLBACK_KEY` (глобальный) | 8.0+ | Глобальный резервный ключ для всех задач |

### Необходимые знания

- Базовый синтаксис `.gitlab-ci.yml` и жизненный цикл пайплайна
- Различие между кэшем и артефактами (подробнее — в **[сравнении механизмов](./caching_overview.md)**)
- Предопределённые переменные (`$CI_COMMIT_REF_SLUG`, `$CI_JOB_NAME`, `$CI_DEFAULT_BRANCH`, `$CI_NODE_INDEX`)
- Настройка Runner'ов и Distributed Cache (S3/MinIO)
- Принципы безопасного кэширования (cache poisoning, isolation)
- Переменные оптимизации сжатия: `CACHE_COMPRESSION_FORMAT`, `CACHE_COMPRESSION_LEVEL`, `FF_USE_FASTZIP`, `FF_SKIP_NOOP_CACHE`

### Целевая аудитория

Справочник предназначен для DevOps-инженеров, SRE и системных администраторов, работающих с on-premise и гибридной инфраструктурой. Примеры ориентированы на оптимизацию времени сборки, безопасное кэширование зависимостей и диагностику проблем с кэшем в распределённых командах Shared Runners.

## Базовые концепции

### Определения
- **Ключ кэша (`cache:key`)** — уникальный идентификатор, определяющий область и версию кэша в хранилище (Distributed Cache или локальный диск Runner'а). В отличие от артефактов, кэш является хранилищем с гарантией "best-effort": GitLab (или очистка Runner'а) может удалить старый кэш для освобождения места.
- **Политика кэширования (`cache:policy`)** — параметр, определяющий режим взаимодействия задачи с хранилищем: загрузка (`pull`), сохранение (`push`) или полный цикл (`pull-push`).
- **Резервные ключи (`fallback_keys`)** — список ключей, используемых для поиска альтернативных версий кэша при отсутствии точного совпадения по основному ключу.

### Типы ключей

#### 1. Статический ключ
```yaml
cache:
  key: "global-npm-cache"
  paths:
    - node_modules/
```
**Принцип работы:** Общий кэш для всех задач в проекте, использующих этот ключ.
**Обоснование и ограничения:** Рекомендуется использовать только для неизменяемых данных (например, загруженные бинарные файлы инструментов, базовые SDK). Существует высокий риск "отравления" кэша (cache poisoning) некорректными или вредоносными данными из экспериментальных веток, так как кэш делят все пайплайны.

#### 2. Динамический ключ на базе встроенных переменных
```yaml
cache:
  key: "$CI_COMMIT_REF_SLUG"
  paths:
    - vendor/
```
**Принцип работы:** Изоляция кэша по веткам. Предотвращает конфликты при параллельной разработке разных фич.
**Полезные переменные:**
- `$CI_JOB_NAME_SLUG`: Привязывает кэш к конкретной задаче, что полезно, если разные задачи используют разные версии зависимостей.
- `$CI_CONCURRENT_ID`: Используется для изоляции кэша между параллельными запусками одной и той же задачи на одном Runner'е (например, в матричных сборках).
- `$CI_JOB_IMAGE`: Полезно для разделения кэша, если задачи используют разные Docker-образы (например, `node:18` и `node:20`), предотвращая смешивание бинарных несовместимых модулей.

#### 3. Ключ по хешу файлов (`cache:key:files`) — Рекомендуемый подход
```yaml
cache:
  key:
    files:
      - package-lock.json
      - Gemfile.lock
    prefix: "prod-deps-$CI_JOB_NAME"
  paths:
    - node_modules/
```
**Принцип работы:** GitLab (через Gitaly) вычисляет SHA256 хеш содержимого указанных файлов. Если зависимости не менялись, используется существующий кэш.
**Параметры:**
- `prefix`: Позволяет добавить статический префикс к хешу. Критично при мажорных обновлениях рантаймов (Node.js 18 -> 20), когда хеш `package-lock.json` идентичен, но бинарные зависимости требуют пересборки.
**Ограничения Gitaly (текущие):**
- Максимум **2 файла** или glob-паттерна на ключ. Gitaly выполняет один `git log` на каждый путь; превышение лимита приводит к таймауту создания пайплайна в монорепозиториях.
- Если файл отсутствует, он игнорируется при расчёте хеша. Если ни один файл не найден, fallback ключ становится `default`.
- Поддерживаются glob-паттерны (например, `**/package.json`), но они не перекрывают файл в корне репозитория.

#### 3.1. Ключ по последнему коммиту (`cache:key:files_commits`) — GitLab 18.4+

```yaml
cache:
  key:
    files_commits:
      - package-lock.json
      - Gemfile.lock
    prefix: "prod-deps-$CI_JOB_NAME"
  paths:
    - node_modules/
```
**Принцип работы:** Вместо хеша содержимого файлов вычисляется хеш их истории коммитов (SHA последнего изменения). Кэш пересоздаётся при каждом новом коммите, затрагивающем указанные файлы, даже если содержимое не изменилось.
**Отличие от `files`:** Полезно, когда lock-файл пересоздаётся автоматическими инструментами (renovate, dependabot) без изменения зависимостей — кэш всё равно обновится, отражая новый контекст сборки.
**Ограничения:**
- Максимум 2 файла/паттерна.
- Несовместим с `cache:key:files` в одном блоке кэша.

#### 4. Ключ с префиксом (`cache:key:prefix`)

```yaml
cache:
  key:
    prefix: "deps-$CI_COMMIT_REF_SLUG"
  paths:
    - vendor/
```
**Принцип работы:** Генерирует ключ вида `deps-main-<sha256>`, где `<sha256>` — хеш всех файлов в `paths`. В отличие от `cache:key:files`, хешируются не конкретные файлы-манифесты, а все файлы в указанных директориях.
**Когда использовать:** Когда нет явного lock-файла (например, Go-модули без `go.sum`, или кастомные скрипты установки). Менее детерминирован, чем `files`, но покрывает больше сценариев.

### Множественное кэширование (Multiple Caches)

Позволяет определять до **4 независимых кэшей** в одной задаче. Эффективно для разделения тяжелых зависимостей (например, `node_modules` выкачивается редко) и промежуточных результатов сборки (обновляются часто).

```yaml
test_job:
  cache:
    - key: npm-$CI_COMMIT_REF_SLUG
      paths: [node_modules/]
      policy: pull
    - key: build-assets
      paths: [dist/cache/]
      policy: pull-push
```
**Архитектурный нюанс:** При выполнении задачи на Runner'е все кэши скачиваются параллельно (если позволяет конфигурация) и распаковываются в рабочий каталог. В Distributed Cache (S3) они хранятся как отдельные независимые объекты (архивы).

### Защита и изоляция кэша

С версии GitLab 15.0 по умолчанию включена строгая изоляция кэша между **защищёнными** (`protected`) и **незащищёнными** ветками. С GitLab 18.4.5 поведение суффиксов уточнено: суффикс `-protected` добавляется для пайплайнов, запущенных пользователем с ролью Maintainer или Owner, а также для защищённых тегов. Во всех остальных случаях добавляется `-non_protected`.

**Механизм работы:**
Под капотом GitLab автоматически добавляет скрытый суффикс к ключу кэша перед запросом в хранилище:
- `-protected` для пайплайнов в защищённых ветках/тегах, запущенных Maintainer/Owner.
- `-non_protected` для всех остальных (feature-ветки, merge requests, Developer role на защищённых ветках).

**Управление изоляцией (unprotect):**
Параметр `unprotect: true` отключает добавление суффикса для незащищенных веток, позволяя им читать кэш защищенных.
```yaml
cache:
  key: "shared-cache-tools"
  paths: [bin/]
  unprotect: true
```
**Правило безопасности:** Использование `unprotect: true` допустимо ТОЛЬКО для статических неизменяемых утилит. Для зависимостей (`node_modules`, `.m2`, `vendor`) использовать его **категорически запрещено**, так как вредоносный MR может отравить общий кэш.
Глобальное поведение контролируется в: `Settings > CI/CD > General pipelines > Use separate caches for protected branches`.

### Политики кэширования (cache:policy)

Определяют режим работы с хранилищем. Грамотный выбор политики напрямую влияет на длительность пайплайна.

| Политика | Поведение | Когда использовать (Сценарии) |
| :--- | :--- | :--- |
| `pull-push` (default) | Скачивает перед `before_script`, загружает после `after_script` | Задачи установки/обновления зависимостей, компиляции с инкрементальным кэшем. |
| `pull` | Только скачивает кэш, изменения не сохраняются | Задачи тестирования, линтинга, деплоя, SAST/DAST сканирования. Максимально ускоряет завершение задачи (отсутствует фаза архивации). |
| `push` | Только загружает, старый кэш игнорируется | Первичная "холодная" сборка базовых образов или ночное обновление общих кэшей по расписанию. |

**Условия сохранения (cache:when):**
- `on_success` (по умолчанию) — кэш архивируется только если задача завершилась с exit code 0. Защищает от сохранения частично скачанных пакетов.
- `on_failure` — полезно для сохранения промежуточных логов или дампов при падении сборки.
- `always` — сохранять всегда (используется редко, в основном для аналитики причин падений).

### Резервные ключи (Fallback Keys)

Механизм "постепенного понижения требований" к кэшу. Позволяет feature-ветке (у которой еще нет своего кэша) использовать кэш от `main` вместо сборки с нуля. Поддерживается до **5** резервных ключей (GitLab 16.0+).

```yaml
test_job:
  cache:
    - key: deps-$CI_COMMIT_REF_SLUG
      fallback_keys:
        - deps-$CI_DEFAULT_BRANCH
        - deps-global
      paths:
        - vendor/ruby
```

**Глобальный резервный ключ (`CACHE_FALLBACK_KEY`):**
Помимо per-cache `fallback_keys`, GitLab поддерживает глобальную переменную `CACHE_FALLBACK_KEY`. Она используется, если ни `cache:key`, ни `fallback_keys` не дали результата. Порядок поиска: `cache:key` → `fallback_keys` → `CACHE_FALLBACK_KEY`.

```yaml
variables:
  CACHE_FALLBACK_KEY: "global-deps-cache"

test_job:
  cache:
    key: deps-$CI_COMMIT_REF_SLUG
    paths:
      - vendor/ruby
```

**Алгоритм поиска Runner'ом:**
1. Пытается найти архив по точному совпадению `key` (например, `deps-feature-x-non_protected`).
2. Если не найден, поочередно проверяет ключи из списка `fallback_keys` (например, `deps-main-non_protected`, затем `deps-global-non_protected`).
3. Если ни один fallback не найден, проверяется глобальный `CACHE_FALLBACK_KEY`.
4. Первый найденный архив скачивается и распаковывается.
5. Если ни один не найден, задача выполняется с пустой директорией `paths`.

## Практические сценарии

Подробные примеры конфигурации для Node.js, Python, Java, Docker и монорепозиториев вынесены в специализированный документ: **[Практические сценарии кэширования](./cache_scenarios.md)**.

## DevOps/SRE и on-premise сценарии

### Кэширование зависимостей в матричных сборках

Матричные задачи делят кэш, если ключ `cache:key` не содержит переменных матрицы. Каждая комбинация должна иметь уникальный ключ.

```yaml
test:ansible:
  stage: test
  parallel:
    matrix:
      - PYTHON_VERSION: ["3.10", "3.11", "3.12"]
        TARGET_OS: [centos9, rocky9, ubuntu2204]
  cache:
    - key: ansible-py${PYTHON_VERSION}-${TARGET_OS}-deps
      paths:
        - .venv/
      policy: pull
    - key: ansible-py${PYTHON_VERSION}-lint
      paths:
        - .ansible-lint-cache/
      policy: pull-push
  script:
    - python -m venv .venv && source .venv/bin/activate
    - pip install ansible-core==2.16 ansible-lint
    - ansible-lint playbooks/
```

### Кэширование Terraform-планов и модулей

Для Terraform критично кэшировать `.terraform/` (провайдеры) и промежуточные `tfplan`.

```yaml
.terraform_cache:
  cache:
    - key: terraform-${CI_COMMIT_REF_SLUG}
      paths:
        - $TF_ROOT/.terraform/
      policy: pull-push
    - key: terraform-providers-${TF_VERSION}
      paths:
        - $TF_ROOT/.terraform/providers/
      policy: pull
      fallback_keys:
        - terraform-providers-latest

terraform:plan:
  extends: .terraform_cache
  variables:
    TF_VERSION: "1.9"
    TF_ROOT: "terraform/environments/staging"
  script:
    - cd $TF_ROOT
    - terraform init -backend=false
    - terraform plan -out=tfplan
  artifacts:
    paths:
      - $TF_ROOT/tfplan
    expire_in: 1 hour
```

### Кэширование Go-модулей в монорепозитории

В монорепозиториях с несколькими Go-сервисами кэш разделяется по модулям.

```yaml
.build_go_template:
  cache:
    - key: go-mod-$CI_COMMIT_REF_SLUG
      paths:
        - .gomod/
      policy: pull-push
    - key: go-build-$CI_COMMIT_REF_SLUG
      paths:
        - .gobuild/
      policy: pull-push
  variables:
    GOMODCACHE: "$CI_PROJECT_DIR/.gomod"
    GOCACHE: "$CI_PROJECT_DIR/.gobuild"

build:api:
  extends: .build_go_template
  script:
    - cd services/api && go build ./...

build:worker:
  extends: .build_go_template
  script:
    - cd services/worker && go build ./...
```

### Кэширование Ansible-ролей и Galaxy

```yaml
ansible:test:
  cache:
    - key: galaxy-requirements-$CI_COMMIT_REF_SLUG
      paths:
        - requirements/
      policy: pull-push
    - key: galaxy-roles-$CI_COMMIT_REF_SLUG
      paths:
        - roles/
      policy: pull
      fallback_keys:
        - galaxy-roles-main
  script:
    - ansible-galaxy install -r requirements.yml --roles-path roles/
    - ansible-playbook --syntax-check site.yml
```

### Кэширование в Collector'ах и шардах

При шардинге тестов каждый шард должен иметь уникальный ключ, чтобы избежать коллизий.

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

## Производительность и сжатие (Zstd, Fastzip, CACHE_COMPRESSION_FORMAT)

Кэш перед отправкой архивируется. В огромных проектах архивация может занимать больше времени, чем скачивание пакетов.

1. **Алгоритм Zstd (По умолчанию с 16.2+):**
   - GitLab Runner использует `zstd` вместо стандартного `zip`. Он обеспечивает лучшую степень сжатия при значительно меньшем потреблении CPU.
   - Управление уровнем сжатия: Переменная окружения Runner'а (или пайплайна) `CACHE_COMPRESSION_LEVEL` (от `fastest` до `slowest`, по умолчанию `fast`).
2. **Алгоритм Fastzip (Исторический/Альтернативный):**
   - Если `zstd` недоступен, Runner можно перевести на использование `fastzip` (алгоритм на Go) вместо встроенного unzip-бинарника.
   - Включается переменной: `FF_USE_FASTZIP: "true"`.
3. **`CACHE_COMPRESSION_FORMAT` (GitLab Runner 16.2+):**
   - Позволяет явно выбрать формат архива: `zip` (legacy), `zipzstd` (параллельное сжатие zstd в zip-контейнере), `tarzstd` (максимальное сжатие).
   - Пример: `CACHE_COMPRESSION_FORMAT: "zipzstd"` — оптимально для многоядерных Runner'ов с кэшами >500 МБ.
   - На single-core Runner'ах или для маленьких кэшей используйте `zip` или `zipzstd` с `CACHE_COMPRESSION_LEVEL: "fastest"`.
4. **`FF_SKIP_NOOP_CACHE` (GitLab 16.0+):**
   - Пропускает этап `uploading cache`, если содержимое директорий не изменилось с момента последней загрузки.
   - Включается переменной: `FF_SKIP_NOOP_CACHE: "true"`.

**Рекомендация:** На современных версиях GitLab полагайтесь на `zipzstd` и политику `pull` для максимизации скорости. Для дополнительного ускорения включите `FF_USE_FASTZIP: "true"` и `FF_SKIP_NOOP_CACHE: "true"`.

## Валидация и отладка ключей кэша

### Просмотр ключей кэша через UI

В GitLab 17.x+ доступен раздел `CI/CD > Caches` в настройках проекта, где отображаются все активные ключи кэша с размерами и датами последнего использования.

### Диагностика через логи Runner'а

```bash
# Включите детальные логи
CI_DEBUG_TRACE: "true"

# Ключевые строки в логе:
# Checking cache for <key>...
# Trying to download <key>.zip from <url>    ← кэш найден
# Successfully extracted cache               ← кэш распакован
# Cache not found for key <key>              ← кэш отсутствует
# Downloading cache.zip from...              ← начало скачивания
# Failed to download cache                   ← ошибка скачивания
```

### Проверка ключа через API

```bash
# Просмотр кэша проекта через API
curl --header "PRIVATE-TOKEN: $TOKEN" \
  "https://gitlab.example.com/api/v4/projects/$PROJECT_ID/cache" | \
  jq '.[] | {key, size, created_at, last_used_at}'

# Очистка кэша по ключу (谨慎使用)
curl --request DELETE --header "PRIVATE-TOKEN: $TOKEN" \
  "https://gitlab.example.com/api/v4/projects/$PROJECT_ID/cache?key=$CACHE_KEY"
```

### Валидация конфигурации через CI Lint

```bash
# Проверка синтаксиса cache-конфигурации
curl --header "PRIVATE-TOKEN: $TOKEN" \
  --data "content=$(cat .gitlab-ci.yml | base64)" \
  "https://gitlab.example.com/api/v4/ci/lint" | jq '.valid'
```

### Тестирование key:files перед коммитом

```bash
# Локальная проверка: убедитесь, что lock-файлы существуют
ls -la package-lock.json poetry.lock go.sum Gemfile.lock

# Проверка, что файлы не пустые (SHA256 хеш от пустого файла бесполезен)
wc -c package-lock.json
# → 123456 (должно быть >0)
```

## Лучшие практики

### Выбор типа ключа

| Сценарий | Рекомендуемый ключ | Причина |
| :--- | :--- | :--- |
| Lock-файлы (npm, pip, bundler) | `cache:key:files` | Детерминированная инвалидация |
| Go-модули без `go.sum` | `cache:key:prefix` | Хеш всего `vendor/` |
| Глобальные утилиты (tflint, hadolint) | Статический ключ (`"tools-v2"`) | Неизменяемые бинарники |
| Матричные сборки | `key: $CI_JOB_NAME-$TARGET` | Изоляция по комбинации |
| Feature-ветки → main | `fallback_keys: [main]` | Использование кэша main |
| Шардинг тестов | `key: $CI_JOB_NAME-$CI_NODE_INDEX` | Уникальность шарда |

### Безопасность

| Практика | Описание | Приоритет |
| :--- | :--- | :--- |
| Не использовать `unprotect: true` для зависимостей | Cache poisoning через MR | Критический |
| `policy: pull` для тестов | Предотвращение перезаписи кэша | Высокий |
| `fallback_keys` вместо статических ключей | Изоляция веток + кэш main | Высокий |
| Ограничение `files`/`files_commits` до 2 файлов | Предотвращение Gitaly timeout | Средний |

**Примечание:** Детальный разбор угроз cache poisoning, механизма суффиксов `-protected`/`-non_protected` и контрольных мер см. в **[Лучшие практики кэширования](./cache_best_practices.md#безопасность-security)**.

### Производительность

| Практика | Описание | Приоритет |
| :--- | :--- | :--- |
| `policy: pull` для build-only задач | Нет фазы архивации | Высокий |
| `zipzstd` (`CACHE_COMPRESSION_FORMAT`) для больших кэшей | Параллельное сжатие, скорость > zip | Высокий |
| `FF_SKIP_NOOP_CACHE` | Пропуск загрузки при отсутствии изменений | Средний |
| `expire_in` для промежуточных кэшей | Освобождение места в S3 | Средний |
| Уникальные ключи для матриц | Предотвращение коллизий | Средний |

**Примечание:** Метрики cache hit rate, рекомендации по настройке `CACHE_COMPRESSION_LEVEL` и мониторингу см. в **[Лучшие практики кэширования](./cache_best_practices.md#мониторинг-и-наблюдаемость)**.

### Организация

| Практика | Описание | Приоритет |
| :--- | :--- | :--- |
| Префикс по проекту/сервису | `myproject-npm-$CI_COMMIT_REF_SLUG` | Высокий |
| Разделение тяжёлых зависимостей | `node_modules` отдельно от `dist/` | Средний |
| `fallback_keys` в 2 уровнях | main → global | Средний |
| Документирование ключей в README | Для новых членов команды | Низкий |

## Граничные случаи и ограничения

### Технические лимиты

| Параметр | Лимит | Рекомендация |
| :--- | :--- | :--- |
| Кэшей на задачу | 4 | Используйте минимально необходимое количество |
| Файлов в `cache:key:files` | 2 (Gitaly лимит) | Оставьте только lock-файлы |
| Файлов в `cache:key:files_commits` | 2 (Gitaly лимит) | Оставьте только lock-файлы |
| `fallback_keys` | 5 (GitLab 16.0+) | Достаточно для большинства сценариев |
| Глобальный `CACHE_FALLBACK_KEY` | 1 | Используется как последний резерв |
| Размер кэша | Ограничен диском Runner'а или S3 bucket | Настройте Lifecycle в S3 |
| `prefix` в `key:files` | Без лимита | Используйте короткие префиксы |

### Особые сценарии

**`cache:key:files` с пустым файлом:**
```yaml
# Проблема: если package-lock.json пуст или отсутствует, хеш будет детерминированным
# и кэш НЕ обновится при изменении зависимостей
# Решение: добавьте проверку в before_script
before_script:
  - test -s package-lock.json || (echo "ERROR: lock file missing" && exit 1)
```

**Изоляция кэша в матричных сборках:**
```yaml
# Проблема: все матричные задачи делят один кэш
# Решение: уникальный ключ для каждой комбинации
test:
  parallel:
    matrix:
      - PYTHON_VERSION: ["3.10", "3.11", "3.12"]
  cache:
    key: py${PYTHON_VERSION}-deps  # Уникальный ключ
    paths:
      - .venv/
```

**Кэш и `interruptible: false`:**
```yaml
# Проблема: прерванная задача не сохраняет кэш
# Решение: используйте cache:when: always (осторожно)
cache:
  key: build-$CI_COMMIT_REF_SLUG
  when: always  # Сохраняет кэш даже при падении
```

**Кэширование в шардах:**
```yaml
# Проблема: шарды перезаписывают кэш друг друга
# Решение: уникальный ключ с индексом шарда
test:
  parallel: 8
  cache:
    key: test-shard${CI_NODE_INDEX}-$CI_COMMIT_REF_SLUG
    paths:
      - .cache/
```

**`files_commits` с пустым коммитом:**
```yaml
# Проблема: если файл существует, но коммитов с его участием нет, хеш будет детерминированным
# Решение: убедитесь, что файл реально меняется в истории
cache:
  key:
    files_commits: [package-lock.json]
```

## Sysadmin: управление хранилищем и наблюдаемость

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

### Управление S3/MinIO жизненным циклом

```json
// Lifecycle policy для автоматического удаления старых кэшей
{
  "Rules": [
    {
      "ID": "ExpireCacheAfter3Days",
      "Status": "Enabled",
      "Expiration": { "Days": 3 },
      "Filter": { "Prefix": "cache/" }
    },
    {
      "ID": "AbortIncompleteMultipart",
      "Status": "Enabled",
      "AbortIncompleteMultipartUpload": { "DaysAfterInitiation": 1 },
      "Filter": { "Prefix": "cache/" }
    }
  ]
}
```

```bash
# Применение lifecycle policy через MinIO Client
mc ilm import myminio/gitlab-runner-cache < lifecycle.json
mc ilm ls myminio/gitlab-runner-cache
```

### Мониторинг эффективности кэширования

| Метрика | Целевое значение | Как измерить |
| :--- | :--- | :--- |
| **Cache hit rate** | > 80% | Логи Runner'а: `Checking cache for <key>... Downloading` (miss) vs `Downloading` (hit) |
| **Cache download time** | < 30 сек | Метрика `job_duration_seconds` с разбивкой по этапам |
| **Cache size** | < 1 GB на кэш | `du -sh` на директории кэша или API объектного хранилища |
| **Gitaly timeout rate** | 0% | Мониторинг GitLab: `gitaly_requests_duration_seconds` |

**Команды для диагностики:**

```bash
 # Просмотр логов Runner'а для анализа кэша
 # В логах задачи ищите:
 grep -E "(Checking cache|Downloading|Creating cache|Uploading|Archive is up to date)" job.log

 # Примеры логов и их значение:
 # "Checking cache for my-key-v123..." → Runner ищет кэш
 # "Downloading https://s3.../cache.zip" → Cache miss, загрузка
 # "Archive is up to date! Skipping upload" → FF_SKIP_NOOP_CACHE работает
 # "Creating cache..." → Cache miss, создание нового кэша

 # Просмотр объектов в S3 (MinIO)
 mc ls myminio/gitlab-runner-cache/ --summarize
```

**Примечание:** Детальную настройку Prometheus-мониторинга, индикаторы cache hit rate и рекомендации SRE по ревизии кэшей см. в **[Лучшие практики кэширования](./cache_best_practices.md#мониторинг-и-наблюдаемость)**.

## Устранение неполадок

### Типичные ошибки

| Ошибка | Причина | Решение |
| :--- | :--- | :--- |
| `Cache not found for key` | Ключ не совпадает или кэш отсутствует | Проверьте `unprotect`, используйте `fallback_keys` |
| `Gitaly timeout` | Слишком много файлов в `cache:key:files` | Оставьте максимум 2 файла |
| `Gitaly timeout` при `files_commits` | Слишком много файлов или паттернов | Оставьте максимум 2 файла/паттерна |
| `No space left on device` | Локальный диск Runner'а забит | Настройте очистку или перейдите на S3 |
| `403 Forbidden` (S3) | Истёк pre-signed URL или неверные credentials | Проверьте NTP и IAM-роли |
| Кэш не обновляется | `policy: pull` или `when: on_success` + падение | Проверьте политику и условия сохранения |
| Кэш "отравлен" | `unprotect: true` на зависимостях | Удалите `unprotect`, очистите кэш |
| Матричные задачи делят кэш | `key` не содержит переменных матрицы | Добавьте `$TARGET` в ключ |
| `zstd: not found` | Старый образ Runner'а или ОС | Обновите Runner до 16.2+ или установите `zstd` |
| Кэш не сжимается (`zipzstd` игнорируется) | `CACHE_COMPRESSION_FORMAT` не поддерживается Runner'ом | Проверьте версию Runner'а; используйте `zip` как fallback |

### Диагностика через Runner

```bash
# Просмотр локального кэша Runner'а
ls -la /home/gitlab-runner/cache/

# Проверка размера кэша
du -sh /home/gitlab-runner/cache/

# Очистка локального кэша
rm -rf /home/gitlab-runner/cache/*

# Проверка конфигурации Runner'а (Distributed Cache)
cat /etc/gitlab-runner/config.toml | grep -A5 "\[cache\]"
```

### Диагностика через API

```bash
# Просмотр всех кэшей проекта
curl --header "PRIVATE-TOKEN: $TOKEN" \
  "https://gitlab.example.com/api/v4/projects/$PROJECT_ID/cache" | jq '.[].key'

# Очистка всего кэша проекта (谨慎使用)
curl --request DELETE --header "PRIVATE-TOKEN: $TOKEN" \
  "https://gitlab.example.com/api/v4/projects/$PROJECT_ID/cache"
```

## Дополнительная информация

- **[Обзор механизма кэширования](./caching_overview.md)** — архитектура, уровни хранения, сравнение кэша и артефактов.
- **[Лучшие практики кэширования](./cache_best_practices.md)** — детальный разбор Gitaly Load, безопасность, мониторинг, управление хранилищем и SRE-рекомендации.
- **[Практические сценарии](./cache_scenarios.md)** — готовые конфигурации для Node.js, Python, Go, Rust, Java, PHP, Ruby, Terraform, Ansible, Salt, Helm, Docker.
- **[Артефакты в GitLab CI](./gitlab_ci_artifacts.md)** — передача данных между стадиями.
- **[Кэш и директивки пайплайна](./cache_pipeline_directives.md)** — взаимодействие `rules`, `needs`, `interruptible` и `resource_group` с кэшем.
- **[Кэш в downstream-пайплайнах](./cache_downstream_pipelines.md)** — наследование кэша в parent-child и multi-project пайплайнах.
- **[Кэш и executor'ы](./cache_executor_specifics.md)** — особенности кэширования для Docker, Shell, Kubernetes и Instance executor'ов.
- **[Матричные сборки и сериализация](../workflow_rules/matrix_builds_and_serialization.md)** — изоляция кэша в матричных задачах.
