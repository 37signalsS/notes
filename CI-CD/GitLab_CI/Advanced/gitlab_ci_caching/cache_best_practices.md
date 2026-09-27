# Лучшие практики кэширования в GitLab CI — глубокое погружение

## Определения

**Лучшие практики кэширования** — совокупность архитектурных и конфигурационных решений, направленных на достижение максимальной скорости пайплайна при сохранении целостности данных и безопасности инфраструктуры.

**Инвалидация кэша (Invalidation)** — процесс принудительного сброса устаревших или поврежденных данных. В GitLab CI наиболее эффективным методом является изменение `prefix` в ключе или обновление хешируемых файлов (например, `package-lock.json`).

**Отравление кэша (Cache Poisoning)** — атака или ошибка конфигурации, при которой некорректные зависимости (например, из экспериментальной ветки) попадают в общий кэш и ломают сборки в основной ветке (`main`). Это требует строгой изоляции на уровне ключей.

**Нагрузка на Gitaly (Gitaly Load)** — вычислительные затраты на стороне сервера GitLab при расчете MD5-хешей для файлов, указанных в `cache:key:files`. Избыточное количество файлов в этом списке может привести к замедлению создания пайплайнов в крупных репозиториях.

**Setup-Consumer Pattern** — архитектурный паттерн, разделяющий задачи на «поставщиков» (обновляют кэш) и «потребителей» (только читают кэш), что исключает состояние гонки (race conditions) при параллельном выполнении.

## Предварительные требования

Для применения современных практик оптимизации необходимо обеспечить:
- **GitLab Runner:** версия 16.2+ (для полной поддержки Zstd и `FF_USE_FASTZIP`).
- **GitLab Server:** версия 17.1+ (для корректной работы с лимитами Gitaly на количество кэшей).
- **Объектное хранилище:** настроенный Distributed Cache (S3, MinIO, GCS) для работы в масштабируемых средах (Kubernetes).

### Переменные окружения и конфигурация Runner

| Переменная | Версия | Значение по умолчанию | Описание |
| :--- | :--- | :--- | :--- |
| `FF_USE_FASTZIP` | 13.1+ | `false` | Включает конкурентную упаковку/распаковку через fastzip. Эффективно на многоядерных Runner'ах. |
| `FF_SKIP_NOOP_CACHE` | 16.0+ | `false` | Пропуск этапа `uploading cache` если содержимое директорий не изменилось. Экономит сетевой трафик. |
| `CACHE_COMPRESSION_LEVEL` | 16.11+ | `fast` | Уровень сжатия: `fastest`, `fast`, `default`, `slow`, `slowest`. Менее агрессивное сжатие = быстрее упаковка. |
| `CACHE_LIMIT` | 13.12+ | `0` (нет лимита) | Максимальный размер кэша в байтах на одну задачу. При превышении Runner удаляет самые старые кэши. |
| `ARTIFACT_COMPRESSION_LEVEL` | 16.11+ | `fast` | Уровень сжатия артефактов (отдельно от кэша). Аналог `CACHE_COMPRESSION_LEVEL`. |

**Пример использования:**
```yaml
variables:
  FF_USE_FASTZIP: "true"
  FF_SKIP_NOOP_CACHE: "true"
  CACHE_COMPRESSION_LEVEL: "fast"

build:
  stage: build
  script: make build
```

**На Runner'е (config.toml):**
```toml
[[runners]]
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

## Основные концепции

### 1. Стратегия выбора ключей и изоляция

Выбор ключа определяет баланс между точностью попадания и стабильностью.

*   **Динамическое хеширование (Standard):** Использование `cache:key:files` гарантирует, что кэш обновится только при изменении зависимостей. 
*   **Изоляция сред:** Всегда добавляйте `prefix` (например, `node-v20-`), чтобы при смене версии Node.js или ОС Runner'а не возникло конфликтов бинарных артефактов (например, `node-gyp` сборки).
*   **Защита веток:** GitLab автоматически изолирует кэш защищённых веток. Не используйте `unprotect: true` для зависимостей, так как это открывает вектор атаки для отравления кэша основной ветки через вредоносные Merge Request.

### 2. Оптимизация I/O и сжатия

В высоконагруженных пайплайнах время упаковки/распаковки может превышать время установки пакетов.

*   **`FF_SKIP_NOOP_CACHE` (GitLab 17.x+):** Эта переменная (устанавливается в `"true"`) заставляет Runner проверять, изменилось ли содержимое директорий перед загрузкой. Если изменений нет, стадия `uploading cache` пропускается, что экономит сетевой трафик и время выполнения `after_script`.
*   **Zstd против Zip:** Алгоритм Zstd (используется по умолчанию в 16.2+) обеспечивает многопоточную распаковку. Для максимального эффекта на многоядерных Runner'ах включите `FF_USE_FASTZIP: "true"`. Это позволяет эффективно использовать все доступные CPU для I/O операций.

### 3. Иерархия и резервные ключи (Fallback Keys)

Для новых веток (где lock-файл еще не захеширован) используйте `fallback_keys`. Это предотвращает «холодный старт», позволяя новой ветке подтянуть зависимости из `main`.

```yaml
cache:
  - key:
      files: [package-lock.json]
      prefix: "npm-$CI_COMMIT_REF_SLUG"
    fallback_keys:
      - "npm-$CI_DEFAULT_BRANCH" # База из основной ветки
      - "npm-global-v1"          # Глобальный резервный кэш
    paths: [node_modules/]
```

### 4. Управление политиками (Pull/Push)

Использование `policy: pull` в задачах тестирования и линтинга является критически важным:
1.  **Скорость:** Пропускается этап упаковки и загрузки архива в S3 в конце задачи.
2.  **Безопасность:** Тестовые задачи не могут случайно перезаписать «чистый» кэш, созданный задачей сборки.
3.  **Конкурентность:** При запуске 100 параллельных тестов в матрице сборки, они не будут создавать нагрузку на запись в объектное хранилище.

## Практические сценарии

### Сценарий 1: Принудительное обновление и валидация

Если кэш поврежден («отравлен»), используйте один из методов:

1.  **Yaml-инвалидация (Рекомендуется):** Измените `prefix` в ключе (например, с `v1` на `v2`).
2.  **UI:** **Build → Cache → Clear runner caches**.
3.  **Валидация:** После запуска задачи проверьте логи Runner'а. Сообщение `Checking cache for <key>... No URL provided, cache will not be downloaded` подтверждает, что старый кэш отброшен и Runner создаст новый.

### Сценарий 2: Оптимизация в монорепозитории

Используйте `files` для точечного отслеживания изменений в подпроектах.

```yaml
.backend_cache: &backend_cache
  key:
    files: [backend/go.sum]
    prefix: backend-v1
  paths: [backend/vendor/]

api_test:
  cache:
    - <<: *backend_cache
      policy: pull
  script: cd backend && go test ./...
```

**Валидация:** Изменение файла в `frontend/` не должно приводить к пересборке кэша в задаче `api_test`. Это проверяется по отсутствию сообщения `Creating cache...` в конце лога задачи.

### Сценарий 3: Глобальная оптимизация через !reference

Для избежания дублирования конфигурации в 50+ задачах используйте механизм `!reference`.

```yaml
.cache_config:
  cache:
    key: "global-v1-$CI_COMMIT_REF_SLUG"
    paths: [.npm/]
    policy: pull

install_deps:
  extends: .cache_config
  cache:
    policy: pull-push # Только здесь разрешаем запись
```

### Сценарий 4: Go modules с кэшированием `GOPATH/pkg/mod`

```yaml
.go_cache: &go_cache
  key:
    files: [go.sum]
    prefix: go-${CI_COMMIT_REF_SLUG}
  paths:
    - .go/pkg/mod/
    - .go/build/
  policy: pull

go_build:
  stage: build
  cache:
    <<: *go_cache
    policy: pull-push
  script:
    - export GOPATH="$CI_PROJECT_DIR/.go"
    - go build ./cmd/server
  variables:
    GOMODCACHE: "$CI_PROJECT_DIR/.go/pkg/mod"
    GOCACHE: "$CI_PROJECT_DIR/.go/build"

go_test:
  stage: test
  cache: *go_cache
  script:
    - go test ./... -count=1
```

**Валидация:** Проверьте, что `go test` не загружает модули заново — в логе не должно быть `go: downloading ...`.

### Сценарий 5: Python/uv с изолированными кэшами

```yaml
.python_cache: &python_cache
  key:
    files: [uv.lock]
    prefix: python-${CI_COMMIT_REF_SLUG}
  paths:
    - .venv/
  policy: pull

install_python_deps:
  stage: .pre
  image: python:3.12
  cache:
    <<: *python_cache
    policy: pull-push
  script:
    - pip install uv
    - uv sync --frozen
  variables:
    UV_CACHE_DIR: "$CI_PROJECT_DIR/.uv-cache"

python_test:
  stage: test
  image: python:3.12
  cache: *python_cache
  script:
    - pip install uv
    - uv run pytest
```

### Сценарий 6: Multi-ecosystem монорепозиторий

Для проектов с несколькими экосистемами (frontend + backend) используйте независимые кэши:

```yaml
.node_cache:
  key:
    files: [frontend/package-lock.json]
    prefix: node-${CI_COMMIT_REF_SLUG}
  paths: [.npm/]

.go_cache:
  key:
    files: [backend/go.sum]
    prefix: go-${CI_COMMIT_REF_SLUG}
  paths: [.go/pkg/mod/]

frontend_build:
  stage: build
  cache:
    <<: *node_cache
    policy: pull-push
  script:
    - cd frontend && npm ci --prefer-offline

backend_build:
  stage: build
  cache:
    <<: *go_cache
    policy: pull-push
  script:
    - cd backend && go build ./...

frontend_test:
  stage: test
  cache:
    <<: *node_cache
    policy: pull
  script:
    - cd frontend && npm test

backend_test:
  stage: test
  cache:
    <<: *go_cache
    policy: pull
  script:
    - cd backend && go test ./...
```

### Сценарий 7: Docker layer caching через Container Registry

Для ускорения сборки Docker-образов используйте кэширование слоёв через Registry:

```yaml
build_docker:
  stage: build
  image: docker:27
  services: [docker:29.8-dind]
  variables:
    DOCKER_BUILDKIT: "1"
    CACHE_IMAGE: "$CI_REGISTRY_IMAGE/cache"
  before_script:
    - docker login -u $CI_REGISTRY_USER -p $CI_REGISTRY_PASSWORD $CI_REGISTRY
  script:
    - |
      docker buildx build \
        --cache-from type=registry,ref=$CACHE_IMAGE \
        --cache-to type=registry,ref=$CACHE_IMAGE,mode=max \
        -t $CI_REGISTRY_IMAGE:$CI_COMMIT_SHA \
        -t $CI_REGISTRY_IMAGE:latest \
        --push .
```

## Дополнительная информация

### Безопасность (Security)

Cache Poisoning — одна из наиболее серьёзных угроз при кэшировании. Некорректные или вредоносные зависимости из экспериментальной ветки могут попасть в общий кэш и сломать сборки в `main`.

| Мера | Описание | Приоритет |
| :--- | :--- | :--- |
| **Изоляция protected/unprotected** | GitLab автоматически добавляет суффикс `-protected` / `-non_protected` к ключам кэша для защищённых веток. Кэши MR от разработчиков **никогда** не перезаписывают кэши `main`. | Критический |
| **`policy: pull` для тестов** | Тестовые задачи и линтеры должны только читать кэш. Только одна задача (обычно `install_deps`) должна иметь `pull-push`. | Критический |
| **Запрет `unprotect: true`** | Не используйте `unprotect: true` для кэша зависимостей — это открывает вектор атаки для перезаписи кэша `main` из MR. | Критический |
| **Изоляция по веткам** | Используйте `$CI_COMMIT_REF_SLUG` в ключе для автоматической изоляции кэшей разных веток. | Высокий |
| **`fallback_keys` вместо общих ключей** | Общие статические ключи (`global-v1`) опасны: они доступны всем веткам. Используйте `fallback_keys` для безопасного доступа к кэшу `main`. | Высокий |
| **Ограничение `files` в ключе** | Не более 2 lock-файлов в `cache:key:files` — это снижает поверхность атаки на Gitaly и уменьшает риск случайной инвалидации. | Средний |

**Механизм суффиксов protected/non_protected:**

| Ветка | Роль пользователя | Суффикс ключа |
| :--- | :--- | :--- |
| Защищённая (`main`) | Developer | `main-protected` |
| Защищённая (`main`) | Maintainer | `main-protected` |
| Обычная (`feature`) | Developer | `feature-non_protected` |
| Обычная (`feature`) | Maintainer | `feature-protected` |

**Важно:** Если Developer запускает пайплайн в защищённой ветке, его кэш попадает в тот же ключ, что и Maintainer. Это безопасно, но может приводить к перезаписи кэша при параллельном выполнении. Решение — использовать `policy: pull` для Developer-задач в защищённых ветках.

### Мониторинг и наблюдаемость

Измерение эффективности кэширования критично для поддержки оптимального времени сборки.

**Индикаторы эффективности:**

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

# Проверка размера локального кэша Runner'а
du -sh /home/gitlab-runner/cache/

# Просмотр объектов в S3 (MinIO)
mc ls myminio/gitlab-runner-cache/ --summarize
```

**Настройка мониторинга в Prometheus (self-managed):**

```yaml
# gitlab_runner_metrics.yml
groups:
  - name: cache_metrics
    rules:
      - record: gitlab_runner_cache_download_duration_seconds
        expr: rate(gitlab_runner_cache_downloaded_bytes_total[5m])
      - record: gitlab_runner_cache_upload_duration_seconds
        expr: rate(gitlab_runner_cache_uploaded_bytes_total[5m])
```

### Граничные случаи и ограничения (Edge Cases)

1.  **Символические ссылки (Symlinks):** По умолчанию Runner сохраняет симлинки как ссылки, а не как копии файлов. Если кэш распаковывается в среду, где целевой файл ссылки отсутствует, пайплайн упадет.
2.  **Регистрозависимость:** Пути в `paths` чувствительны к регистру. Путь `Node_Modules/` не подхватит стандартную директорию в Linux Runner.
3.  **Лимиты S3:** При использовании MinIO/S3 помните о лимитах на размер одного объекта (multipart upload). Кэши более 5 ГБ могут требовать специфической настройки Runner'а (`runners.cache.s3.MaxMultipartUploadSize`).
4.  **Пустой lock-файл:** Если `cache:key:files` ссылается на пустой файл, хеш будет детерминированным и кэш НЕ обновится при изменении зависимостей. Решение: добавьте проверку в `before_script`:
    ```yaml
    before_script:
      - test -s package-lock.json || { echo "lock file is empty"; exit 1; }
    ```
5.  **Множественные lock-файлы:** Если ОДИН из файлов в `cache:key:files` не изменился, кэш НЕ обновится даже если другой файл изменился. Решение: используйте отдельные кэши для разных экосистем (см. Сценарий 6).
6.  **Race condition при параллельных задачах:** Если две задачи с одним ключом и `policy: pull-push` выполняются одновременно, последняя завершившаяся перезапишет кэш первой. Решение: только одна задача на ключ должна иметь `pull-push`.
7.  **Суффикс protected/non_protected:** Ключи кэша автоматически получают суффикс `-protected` для защищённых веток и `-non_protected` для обычных. Это может приводить к неожиданным промахам кэша при переходе между ветками. Используйте `fallback_keys` для безопасного доступа к кэшу `main`.
8.  **Размер архива:** Все кэши одной задачи архивируются в один `cache.zip`. Если суммарный размер превышает возможности Runner'а (CPU/RAM), упаковка может занять больше времени, чем установка зависимостей. Контролируйте общий размер через `CACHE_LIMIT`.

### Управление хранилищем кэша (self-managed инстансы)

**Локальное хранилище:**
```bash
# Просмотр использования
du -sh /home/gitlab-runner/cache/

# Очистка кэша старше 7 дней
find /home/gitlab-runner/cache/ -name "*.zip" -mtime +7 -delete

# Настройка автоматической очистки через cron
# /etc/cron.d/gitlab-runner-cache
0 2 * * * gitlab-runner find /home/gitlab-runner/cache/ -name "*.zip" -mtime +3 -delete
```

**S3/MinIO Lifecycle:**
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

**API управления кэшем (GitLab 17.0+):**

```bash
# Просмотр кэшей проекта (требует admin-доступ)
curl --header "PRIVATE-TOKEN: $TOKEN" \
  "https://gitlab.example.com/api/v4/projects/$PROJECT_ID/cache" | \
  jq '.[] | {key, path, created_at}'

# Удаление конкретного кэша
curl --request DELETE --header "PRIVATE-TOKEN: $TOKEN" \
  "https://gitlab.example.com/api/v4/projects/$PROJECT_ID/cache?key=$CACHE_KEY&ref=main"

# Удаление всех кэшей проекта
curl --request DELETE --header "PRIVATE-TOKEN: $TOKEN" \
  "https://gitlab.example.com/api/v4/projects/$PROJECT_ID/cache"
```

### Чек-лист лучших практик

**Конфигурация:**
- [ ] Используйте `cache:key:files` с привязкой к lock-файлам (не более 2-х).
- [ ] Добавляйте `prefix` с именем экосистемы или версией runtime.
- [ ] Настройте `fallback_keys` с базовым ключом из `main`.
- [ ] Включите `FF_USE_FASTZIP: "true"` и `FF_SKIP_NOOP_CACHE: "true"`.

**Политики:**
- [ ] Только одна задача на ключ — `policy: pull-push`.
- [ ] Тесты, линтеры, статический анализ — `policy: pull`.
- [ ] Never `unprotect: true` для зависимостей.

**Безопасность:**
- [ ] Изоляция protected/unprotected включена по умолчанию (не отключайте).
- [ ] `fallback_keys` вместо общих статических ключей.
- [ ] Регулярная ревизия кэшей через API.

**Мониторинг и размер:**
- [ ] Контролируйте размер кэша (< 1 ГБ на кэш, до 4 кэшей на задачу).
- [ ] Отслеживайте cache hit rate через логи Runner'а.
- [ ] Настройте S3 lifecycle для автоматической очистки.

### Устранение неполадок

| Проблема | Возможная причина | Решение |
| :--- | :--- | :--- |
| `Permission Denied (S3)` | Неверные права IAM или Secret Key | Проверьте `config.toml` Runner'а. Для S3 нужны права `s3:PutObject` и `s3:GetObject`. |
| Кэш не загружается в конце задачи | Политика `pull` или отсутствие изменений | Проверьте `cache:policy`. Если включен `FF_SKIP_NOOP_CACHE`, это нормальное поведение при отсутствии изменений. |
| Ошибка `zstd: not found` | Старый образ Runner'а или ОС | Обновите GitLab Runner до 16.2+ или установите пакет `zstd` в базовый образ задачи. |
| `Gitaly timeout` | Слишком много файлов в `cache:key:files` | Оставьте в списке только основные lock-файлы (не более 2-х). |
| Кэш перезаписывается из MR | Race condition или `policy: pull-push` в тестах | Убедитесь, что только одна задача (install_deps) имеет `pull-push`. Тесты — `pull`. |
| `Cache not found for key` после MR | Защищённая ветка + обычный ключ | Проверьте суффикс `-protected`/`-non_protected`. Используйте `fallback_keys`. |
| Кэш не инвалидируется при обновлении | Пустой lock-файл или он не в `files` | Проверьте `package-lock.json` на пустоту. Добавьте файл в `cache:key:files`. |
| Медленная упаковка кэша | Большой размер + не включен Fastzip | Включите `FF_USE_FASTZIP: "true"` и `CACHE_COMPRESSION_LEVEL: "fast"`. |
| `ERROR: Failed to create cache.zip` | Недостаточно места на диске Runner'а | Очистите локальный кэш: `find /home/gitlab-runner/cache/ -mtime +3 -delete`. |
| Кэш распаковывается с ошибками | Симлинки или разные ОС (macOS ↔ Linux) | Не кэшируйте симлинки. Используйте одну архитектуру для Builder и Runner'ов. |
| `uv.lock mismatch` в CI | Кастомный `UV_INDEX_URL` (nexus-proxy) меняет разрешение зависимостей | Используйте один и тот же индекс в CI и локально. См. **[Сценарий 2](./cache_scenarios.md#сценарий-2--python-uv--pip--poetry)**. |

### Рекомендации SRE

1. **Измеряйте cache hit rate** — цель > 80%. Ниже = ключи слишком специфичные или кэш удаляется.
2. **Контролируйте размер** — кэш > 1 ГБ замедляет пайплайн из-за времени упаковки/распаковки.
3. **Настройте S3 lifecycle** — автоматическое удаление кэшей старше 3-5 дней.
4. **Используйте `CACHE_LIMIT`** — установите max размер кэша на Runner'е для предотвращения переполнения хранилища.
5. **Ревизия кэшей** — ежемесячно проверяйте API список кэшей проекта, удаляйте устаревшие.
6. **Документируйте ключи** — ведите реестр ключей кэша с описанием что кэшируется и почему.
7. **Тестируйте инвалидацию** — при изменении lock-файла проверяйте, что кэш действительно пересобирается.
8. **Мониторьте Gitaly** — при > 1000.lock-файлов в монорепозитории кэширование может вызывать таймауты.

### См. также

*   **[Обзор кэширования и артефактов](./caching_overview.md)** — сравнение механизмов.
*   **[Ключи и политики](./cache_keys.md)** — детальный справочник параметров.
*   **[Практические сценарии](./cache_scenarios.md)** — реализация для конкретных стеков (NPM, Python, Go).


