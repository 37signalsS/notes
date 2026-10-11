# Кэш и executor'ы в GitLab CI

**Актуально для:** GitLab 19.x / GitLab Runner 19.x
**Совместимость:** GitLab 18.x / Runner 18.x поддерживаются, но ряд оптимизаций (`zipzstd`, `FF_USE_PARALLEL_CACHE_TRANSFER`, `config lint`) требует 19.x.

## Определения

**Эфемерный кэш (Ephemeral cache)** — кэш, который создаётся и удаляется вместе с средой выполнения задачи. Характерен для Docker и Kubernetes executor'ов без персистентных volumes.

**Персистентный кэш (Persistent cache)** — кэш, который сохраняется между запусками задач. Характерен для Shell executor и Docker/Kubernetes executor'ов с volumes.

## Предварительные требования

Для корректного кэширования с учетом особенностей executor'ов необходимо обеспечить:

- **GitLab Runner:** версия 19.x (для `zipzstd` требуется 19.3+). Runner должен быть не более одной мажорной версии позади GitLab instance.
- **GitLab Server:** версия 19.x.
- **Сетевая доступность:**
  - Runner → GitLab API: порт 443 (HTTPS) или 8443 (self-signed).
  - Runner → S3/MinIO: порт 443 (или 9000 для MinIO без TLS).
  - Для Kubernetes executor: Runner должен иметь доступ к API-серверу кластера (по умолчанию 6443).
- **RBAC (Kubernetes):** ServiceAccount runner с правами `create/get/list/watch/delete` на Pods, ConfigMaps, PersistentVolumeClaims в namespace `gitlab-runner`.
- **Синхронизация времени (NTP):** требуется для корректной работы pre-signed URL в Distributed Cache и для корректного сравнения временных меток кэша.
- **Дисковое пространство Runner'а:** для временной распаковки кэша необходимо свободное место, превышающее суммарный размер `paths` (рекомендуется минимум 2x).
- **Права доступа к volumes (Docker/Shell):** пользователь `gitlab-runner` должен иметь права на запись в директорию кэша.

### Переменные окружения и конфигурация Runner

| Переменная / Параметр | Версия | Значение по умолчанию | Описание |
| :--- | :--- | :--- | :--- |
| `CACHE_COMPRESSION_FORMAT` | 16.2+ | `zip` | Формат архива: `zip`, `zipzstd` (Runner 19.3+), `tarzstd`. |
| `FF_USE_FASTZIP` | 13.1+ | `false` (удален в 19.7) | Включает конкурентную упаковку/распаковку. |
| `FF_SKIP_NOOP_CACHE` | 16.0+ | `false` | Пропуск загрузки при отсутствии изменений. |
| `FF_USE_PARALLEL_CACHE_TRANSFER` | 18.10+ | `false` | Параллельная загрузка/выгрузка в S3. |
| `CACHE_CONCURRENCY` | 18.10+ | `1` | Число параллельных потоков при передаче. |
| `CACHE_LIMIT` | 13.12+ | `0` (нет лимита) | Максимальный размер кэша в байтах на задачу. |
| `poll_timeout` (K8s) | — | `180` сек | Таймаут ожидания ответа GitLab API. При таймауте кэш не загружается. |
| `helper_image` (K8s) | — | `registry.gitlab.com/gitlab-org/gitlab-runner/gitlab-runner-helper:x86_64-latest` | Образ для загрузки/выгрузки кэша. Должен иметь доступ к volumes. |

## Основные концепции

Общий обзор executor'ов и `config.toml`: см. SSoT **[Обзор GitLab Runner и Executor'ов](../gitlab_ci_runners_executors.md)**.

### 1. Docker executor

#### 1.1. Архитектура кэширования

Docker executor создаёт контейнер для каждой задачи. Кэш может храниться:
- **В volumes Runner'а** — персистентные тома, смонтированные в контейнер.
- **В Distributed Cache (S3/MinIO)** — общий кэш между несколькими Runner'ами.
- **Локально в контейнере** — ephemeral, теряется после завершения задачи.

#### 1.2. Конфигурация volumes в config.toml

```toml
[[runners]]
  executor = "docker"
  [runners.docker]
    image = "node:20"
    volumes = [
      "/cache",
      "/var/run/docker.sock:/var/run/docker.sock"
    ]
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

**Объяснение:**
- `/cache` — стандартный путь для кэша Runner'а. Runner создаёт поддиректории для каждого кэша.
- `/var/run/docker.sock` — доступ к Docker демону (для DinD или docker build).

#### 1.3. Docker-in-Docker (DinD) и кэш

При использовании DinD (`services: [docker:dind]`) кэш Docker слоёв хранится внутри DinD-контейнера. После завершения задачи DinD-контейнер удаляется, и кэш слоёв теряется.

**Решение:** Используйте Docker BuildKit с кэшированием в Registry:

```yaml
build_image:
  stage: build
  image: docker:24
  services:
    - docker:24-dind
  variables:
    DOCKER_BUILDKIT: "1"
    CACHE_IMAGE: "$CI_REGISTRY_IMAGE/cache"
  script:
    - docker login -u $CI_REGISTRY_USER -p $CI_REGISTRY_PASSWORD $CI_REGISTRY
    - docker buildx build \
        --cache-from type=registry,ref=$CACHE_IMAGE \
        --cache-to type=registry,ref=$CACHE_IMAGE,mode=max \
        -t $CI_REGISTRY_IMAGE:$CI_COMMIT_SHA \
        --push .
```

**Примечание:** Docker layer caching через Registry не использует GitLab Runner Cache. Это отдельный механизм.

#### 1.4. pull_policy и кэш

`pull_policy = "if-not-present"` ускоряет запуск задач за счёт использования локального кэша образов Docker на Runner'е.

```toml
[[runners]]
  executor = "docker"
  [runners.docker]
    pull_policy = ["if-not-present"]
```

**Эффект:** Если образ уже есть на Runner'е, он не скачивается заново. Это сокращает время запуска задачи.

### 2. Shell executor

#### 2.1. Архитектура кэширования

Shell executor выполняет задачи напрямую на хосте. Кэш хранится в файловой системе хоста.

**Преимущества:**
- Быстрый доступ к кэшу (нет overhead контейнеризации).
- Кэш персистирует между задачами автоматически.

**Недостатки:**
- Нет изоляции между задачами (риск загрязнения среды).
- Зависимость от ОС и библиотек хоста.

#### 2.2. Конфигурация

```toml
[[runners]]
  executor = "shell"
  [runners.shell]
    bash = "/bin/bash"
```

**Кэш:** Runner создаёт директорию `/home/gitlab-runner/cache/` (по умолчанию) или ту, что указана в `volumes` (если используется Docker-контейнер для Runner'а).

#### 2.3. Очистка кэша

```bash
# Просмотр локального кэша
ls -la /home/gitlab-runner/cache/

# Проверка размера
du -sh /home/gitlab-runner/cache/

# Очистка кэшей старше 3 дней
find /home/gitlab-runner/cache/ -name "*.zip" -mtime +3 -delete

# Автоматическая очистка через cron
0 2 * * * gitlab-runner find /home/gitlab-runner/cache/ -name "*.zip" -mtime +3 -delete
```

### 3. Kubernetes executor

#### 3.1. Архитектура кэширования

Kubernetes executor создаёт под для каждой задачи. По умолчанию кэш **не персистит** между подами, так как поды ephemeral.

**Варианты кэширования:**
- **emptyDir** — кэш живёт только во время выполнения пода. Не подходит для общего кэша между задачами.
- **PVC (Persistent Volume Claim)** — персистентный volume, доступный между подами.
- **Distributed Cache (S3/MinIO)** — общий кэш между всеми подами.

#### 3.2. Конфигурация emptyDir

```yaml
cache:
  key:
    files: [package-lock.json]
    prefix: npm
  paths: [.npm/]
  policy: pull-push
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

**Примечание:** emptyDir теряется при удалении пода. Подходит только для кэша между стадиями внутри одного пайплайна.

#### 3.3. Конфигурация PVC

```yaml
cache:
  key:
    files: [package-lock.json]
    prefix: npm
  paths: [.npm/]
  policy: pull-push
```

```toml
[[runners]]
  executor = "kubernetes"
  [runners.kubernetes]
    namespace = "gitlab-runner"
    [runners.kubernetes.volumes]
      [[runners.kubernetes.volumes.pvc]]
        name = "gitlab-runner-cache"
        claim_name = "gitlab-runner-cache-pvc"
        mount_path = "/cache"
```

**PVC манифест:**

```yaml
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: gitlab-runner-cache-pvc
  namespace: gitlab-runner
spec:
  accessModes:
    - ReadWriteMany
  resources:
    requests:
      storage: 100Gi
  storageClassName: "standard"
```

**Важно:** Для параллельных задач используйте `ReadWriteMany` (RWX) access mode. Иначе PVC может быть смонтирован только в один под одновременно.

#### 3.4. Distributed Cache для Kubernetes

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

**Преимущества:**
- Общий кэш между всеми подами и кластерами.
- Нет необходимости в PVC.
- Масштабируемость.

**Недостатки:**
- Зависимость от сети.
- Задержка при загрузке/выгрузке кэша.

#### 3.5. Параметры Kubernetes executor'а, влияющие на кэш

| Параметр | Влияние на кэш |
| :--- | :--- |
| `poll_timeout` | Время ожидания Runner'ом ответа от GitLab API. При таймауте задача может не загрузить кэш. |
| `namespace` | Namespace, в котором создаются поды. Кэш изолирован по namespace. |
| `volumes` | Volumes для персистентного кэша. |
| `pod_security_context` | Права доступа в поде. Влияет на возможность записи в `/cache`. |
| `helper_image` | Образ, используемый для загрузки/выгрузки кэша. Должен иметь доступ к volumes. |

### 4. Instance executor

#### 4.1. Архитектура кэширования

Instance executor создаёт отдельную виртуальную машину для каждой задачи. После завершения задачи VM удаляется.

**Кэш:** Возможен только через Distributed Cache (S3/MinIO), так как локальный кэш на VM теряется после удаления.

```yaml
cache:
  key:
    files: [package-lock.json]
    prefix: npm
  paths: [.npm/]
  policy: pull-push
```

```toml
[[runners]]
  executor = "instance"
  [runners.instance]
    # Конфигурация зависит от плагина (libvirt, VMware, Proxmox)
```

### 5. Сравнение executor'ов

| Executor | Тип кэша | Персистентность | Изоляция | Производительность |
| :--- | :--- | :--- | :--- | :--- |
| **Docker** | Volumes / S3 | Персистентный (volumes) | Высокая | Средняя (overhead контейнеризации) |
| **Shell** | Локальный диск | Персистентный | Низкая | Высокая (нет overhead) |
| **Kubernetes** | emptyDir / PVC / S3 | emptyDir: ephemeral; PVC/S3: персистентный | Высокая | Средняя (overhead Kubernetes) |
| **Instance** | S3 | Эфемерный (VM удаляется) | Максимальная | Низкая (создание VM) |

### 6. Практические сценарии

#### Сценарий 1: Docker executor с локальным кэшем

```yaml
cache:
  key:
    files: [package-lock.json]
    prefix: npm
  paths: [.npm/]
  policy: pull-push
```

```toml
[[runners]]
  executor = "docker"
  [runners.docker]
    image = "node:20"
    volumes = ["/cache"]
    [runners.cache]
      Type = "s3"
      Shared = true
      [runners.cache.s3]
        BucketName = "gitlab-runner-cache"
```

#### Сценарий 2: Shell executor на bare-metal

```yaml
cache:
  key:
    files: [package-lock.json]
    prefix: npm
  paths: [.npm/]
  policy: pull-push
```

```toml
[[runners]]
  executor = "shell"
  [runners.shell]
    bash = "/bin/bash"
```

**Кэш:** `/home/gitlab-runner/cache/` на хосте.

#### Сценарий 3: Kubernetes executor с PVC

```yaml
cache:
  key:
    files: [package-lock.json]
    prefix: npm
  paths: [.npm/]
  policy: pull-push
```

```toml
[[runners]]
  executor = "kubernetes"
  [runners.kubernetes]
    namespace = "gitlab-runner"
    [runners.kubernetes.volumes]
      [[runners.kubernetes.volumes.pvc]]
        name = "gitlab-runner-cache"
        claim_name = "gitlab-runner-cache-pvc"
        mount_path = "/cache"
```

#### Сценарий 4: Kubernetes executor с Distributed Cache

```yaml
cache:
  key:
    files: [package-lock.json]
    prefix: npm
  paths: [.npm/]
  policy: pull-push
```

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

### Troubleshooting

| Проблема | Executor | Причина | Решение |
| :--- | :--- | :--- | :--- |
| Кэш не загружается в Kubernetes | Kubernetes | PVC смонтирован в read-only или отсутствует RWX | Проверьте `accessModes: [ReadWriteMany]` в PVC. Для параллельных задач RWX обязателен. |
| `Permission denied` на `/cache` в Kubernetes | Kubernetes | `pod_security_context` или `fsGroup` не настроен | Добавьте `fsGroup: 1000` в `pod_spec` или настройте права на volume. |
| Кэш теряется после перезапуска Runner'а | Docker | Volume `/cache` не указан в `config.toml` или удалён | Проверьте `volumes = ["/cache"]` в секции `[runners.docker]`. |
| DinD: кэш слоёв теряется | Docker | DinD-контейнер удаляется после задачи | Используйте Docker BuildKit с Registry (`--cache-from/--cache-to type=registry`) или внешний registry. |
| Медленная работа кэша на Shell | Shell | Кэш на сетевой файловой системе (NFS) | Перенесите кэш на локальный SSD. Для нескольких Runner'ов используйте Distributed Cache. |
| `helper_image` не найден | Kubernetes | Устаревший helper image без поддержки `zipzstd` | Обновите `helper_image` до версии с GitLab Runner 19.3+. |
| Race condition при параллельной записи | Все | Несколько задач с `policy: pull-push` используют один ключ | Оставьте `pull-push` только для одной задачи (например, `install_deps`). Остальные — `pull`. |
| Кэш не инвалидируется | Все | Пустой lock-файл в `cache:key:files` | Проверьте, что lock-файл не пустой. Добавьте `before_script` с проверкой. |
| `Gitaly timeout` при создании пайплайна | Все | Слишком много файлов в `cache:key:files` | Оставьте не более 2 lock-файлов. |

#### Диагностика

```bash
# Проверка конфигурации Runner'а (Runner 19.3+)
gitlab-runner config lint /etc/gitlab-runner/config.toml

# Просмотр локального кэша
ls -la /home/gitlab-runner/cache/
du -sh /home/gitlab-runner/cache/

# Очистка кэшей старше 3 дней
find /home/gitlab-runner/cache/ -name "*.zip" -mtime +3 -delete

# Проверка событий Pod'ов в Kubernetes
kubectl describe pod -n gitlab-runner -l app=gitlab-runner

# Просмотр объектов в S3/MinIO
mc ls myminio/gitlab-runner-cache/ --summarize
```

### Best Practices

#### Выбор executor'а под сценарий

| Сценарий | Рекомендуемый executor | Обоснование |
| :--- | :--- | :--- |
| Монопольный Runner на bare-metal | Shell | Максимальная скорость, нет overhead контейнеризации. Кэш на локальном диске. |
| Несколько Runner'ов, общий кэш | Docker + S3/MinIO | Изоляция задач + персистентный Distributed Cache. |
| Динамические окружения, масштабирование | Kubernetes + PVC или S3 | Эфемерные поды, персистентный кэш через PVC или S3. |
| Высокие требования к изоляции | Instance / Kubernetes | Максимальная изоляция, но кэш только через Distributed Cache. |
| Windows-задачи | Docker (docker-windows) или Shell | Kubernetes executor для Windows имеет ограничения. |

#### SRE: Мониторинг и алертинг

- **Cache hit rate:** целевое значение > 80%. Измеряется по логам Runner'а (`Checking cache` → `Downloading` = miss, `Downloading` = hit). Ниже 80% — ключи слишком специфичны или кэш удаляется слишком агрессивно.
- **Время загрузки/выгрузки кэша:** < 30 сек на задачу. При превышении проверьте сеть между Runner'ом и S3, включите `FF_USE_PARALLEL_CACHE_TRANSFER`.
- **Gitaly timeout rate:** должно быть 0%. Если возникают таймауты — уменьшите количество файлов в `cache:key:files` до 2.
- **Ошибки доступа к volumes (Kubernetes):** мониторьте события Pod'ов (`kubectl describe pod`), проверьте `pod_security_context` и права ServiceAccount.
- **Дисковое пространство Runner'а:** алерт при заполнении > 80%. Настройте `CACHE_LIMIT` и cron-очистку.

#### Sysadmin: Эксплуатация

- **Очистка локального кэша (Shell/Docker):**
  ```bash
  # Просмотр размера
  du -sh /home/gitlab-runner/cache/
  
  # Очистка кэшей старше 3 дней
  find /home/gitlab-runner/cache/ -name "*.zip" -mtime +3 -delete
  
  # Автоматическая очистка через cron
  0 2 * * * gitlab-runner find /home/gitlab-runner/cache/ -name "*.zip" -mtime +3 -delete
  ```
- **S3/MinIO Lifecycle:** настройте политику автоматического удаления объектов старше 3-5 дней. Это предотвращает бесконечный рост bucket и снижает стоимость хранилища.
- **Валидация конфигурации Runner'а (Runner 19.3+):**
  ```bash
  gitlab-runner config lint /etc/gitlab-runner/config.toml
  ```
- **Обновление helper_image (Kubernetes):** поддерживайте актуальный helper image для использования новых форматов сжатия (`zipzstd`).

### 7. Дополнительная информация

#### См. также

- **[Обзор кэширования](./caching_overview.md)** — архитектура и уровни хранения.
- **[Ключи и политики](./cache_keys.md)** — `cache:key`, `fallback_keys`, `policy`.
- **[Лучшие практики](./cache_best_practices.md)** — безопасность, мониторинг, SRE.
- **[Практические сценарии](./cache_scenarios.md)** — примеры для языков и инфраструктуры.
- **[Кэш и директивки пайплайна](./cache_pipeline_directives.md)** — взаимодействие `rules`, `needs`, `interruptible` и `resource_group` с кэшем.
- **[Кэш в downstream-пайплайнах](./cache_downstream_pipelines.md)** — наследование кэша в parent-child и multi-project пайплайнах.
- **[Обзор GitLab Runner и Executor'ов](../gitlab_ci_runners_executors.md)** — типы executor'ов, конфигурация `config.toml`, lifecycle задачи.
- **[Матричные сборки и сериализация](../workflow_rules/matrix_builds_and_serialization.md)** — изоляция кэша в матричных задачах.
