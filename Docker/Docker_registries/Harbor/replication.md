# Harbor: Репликация артефактов

**Актуально для:** Harbor 2.16.x

## Определения

* **Репликация (Replication)**: Синхронизация артефактов между двумя реестрами — Harbor↔Harbor или Harbor↔внешний реестр. Два направления: **Push-based** (из Harbor в целевой реестр) и **Pull-based** (из исходного реестра в Harbor).
* **Endpoint (Registries Endpoint)**: Учётная запись доступа к внешнему реестру: URL, тип, учётные данные, настройки TLS. Один endpoint может использоваться несколькими правилами.
* **Replication Rule**: Правило репликации: источник/назначение, фильтры (проект, тег, лейбл, тип ресурса), триггер и политика перезаписи.
* **Триггер**: Условие запуска правила: вручную (Manual), по событию (Event-based — при push артефакта) или по расписанию (Scheduled — cron).
* **Override**: Политика перезаписи существующего артефакта в целевом реестре при совпадении тега.
* **Job Service Dashboard**: Панель администратора для мониторинга фоновых задач, включая задачи репликации.

## Основные концепции

### Зачем репликация в продакшене

| Сценарий | Решение |
| :--- | :--- |
| Dev → Prod promotion образов | Push-based: push в Dev-реестр автоматически реплицируется в Prod |
| DR (аварийное восстановление) | Push-based в резервный инстанс в другой площадке |
| Распределение по площадкам / edge | Pull-based: периферийные Harbor затягивают по расписанию |
| Обход лимитов upstream | Pull-based из Docker Hub через endpoint с учётными данными |

### Поддерживаемые адаптеры

Официально поддерживаемые типы endpoints (оба направления, если не указано иное):

| Реестр | Pull | Push |
| :--- | :--- | :--- |
| Harbor | ✓ | ✓ |
| Docker Distribution | ✓ | ✓ |
| Docker Hub | ✓ | ✓ |
| Quay | ✓ | ✓ |
| GitLab Registry | ✓ | ✓ |
| Artifactory | ✓ | ✓ |
| AWS ECR / Azure ACR / GCR / AliCR / Huawei SWR | ✓ | ✓ |
| GitHub Container Registry (GHCR) | ✓ | ✓ |
| VolcEngine Container Registry | ✓ | ✓ |
| Tencent TCR | ✓ | ✓ |
| Artifact Hub | ✓ | — |

> Полный список и статус адаптеров — в [Harbor Compatibility List](https://goharbor.io/docs/2.16.0/install-config/harbor-compatibility-list/).

### Как работает репликация

1. **Job Service** выполняет задачи репликации (фоновые задачи, очередь в Redis).
2. Для каждого реплицируемого репозитория создаётся worker; количество параллельных задач ограничено `jobservice.max_job_workers` в `harbor.yml` (дефолт **10**) — см. [эксплуатацию](./operations.md#сценарий-1-тюнинг-производительности).
3. Артефакт передаётся по digest — реплицируется точное содержимое, а не тег.
4. При event-based триггере задача создаётся сразу после push; при scheduled — по cron; при manual — администратором.
5. **SBOM и подписи** реплицируются вместе с артефактом: SBOM (Harbor 2.11+) хранится как OCI-артефакт (Referrers) и копируется pull/push-based правилом вместе с субъектом; подписи Cosign/Notation (OCI 1.1 Referrers) реплицируются аналогично. Детали жизненного цикла SBOM — в [sbom.md](./sbom.md).
6. **Chunked blob upload** (Harbor 2.16+) для Azure ACR: большие блобы загружаются чанками, что снижает потребление памяти и повышает надёжность при нестабильной сети.
7. **Event-based фильтрация** (Harbor 2.16+): query к event policies оптимизирован — учитываются только релевантные правила, уменьшая нагрузку на Job Service.
8. **Referrers API proxy** (Harbor 2.16+): при pull-based репликации Referrers (SBOM, подписи, attestations) проксируются с upstream-реестра с пагинацией и локальным слиянием, сохраняя цепочку происхождения.

> **Важно:** Репликация между разными мажорными версиями Harbor не поддерживается из-за изменений API. Минорные версии внутри одной мажорной (например, 2.15.x ↔ 2.16.x) совместимы для базовых операций, но новые фичи (Referrers proxy, chunked upload) требуют 2.16+ на обеих сторонах.

## Практические сценарии

### Сценарий 1: Создание endpoint

1. **Administration → Registries → New Endpoint**.
2. Параметры:

| Параметр | Пример | Назначение |
| :--- | :--- | :--- |
| **Name** | `prod-harbor` | Идентификатор endpoint в правилах |
| **Provider / Type** | `Harbor` | Тип целевого реестра (список см. в таблице адаптеров) |
| **Endpoint URL** | `https://harbor-prod.corp.local` | Корневой URL реестра (для Harbor — базовый URL инстанса) |
| **Access ID** | `robot$production+repl` | Логин (для Harbor — имя робот-аккаунта) |
| **Access Secret** | `***` | Токен/пароль робот-аккаунта |
| **Insecure** | выключено | Разрешить HTTP/самоподписанный TLS (только тесты) |
| **Verify Remote Cert** | включено | Проверка TLS-сертификата целевого реестра |

3. **Test Endpoint** — проверка связности и прав.

> Для репликации используйте **робот-аккаунт** с правами Pull/Push на целевом проекте, а не учётку администратора — принцип least privilege.
>
> **Специфика провайдеров:**
> - **AWS ECR**: Access ID = AWS Access Key ID, Access Secret = AWS Secret Access Key (ключи с правами на ECR)
> - **GCR / Artifact Registry**: Access ID = пусто, Access Secret = весь JSON сервисного аккаунта
> - **Quay**: Access Secret = JSON с полями `account_name`, `docker_cli_password`, опционально `oauth2_token`
> - **Azure ACR**: Access ID = client_id, Access Secret = client_secret (service principal с ролью AcrPush/AcrPull)

### Сценарий 2: Push-based репликация Dev → Prod

Автоматический promotion образов при push в Dev:

1. **Administration → Replication → New Rule**.
2. **Source**: текущий инстанс (Local Harbor), проект `myapp-dev`.
3. **Destination**: endpoint `prod-harbor`, проект `myapp-prod`.
4. **Trigger**: **Event-based** — задача запускается при каждом push в проект-источник.
5. **Filters**: по тегам (например, `v*` — только релизные теги) или лейблам (например, `env=prod`).
6. **Override**: включить перезапись, если теги в Prod могут обновляться.
7. **Delete remote resources when locally deleted** (опционально): при удалении артефакта в источнике он удалится и в назначении.
8. **Save** → **Replicate** для немедленного запуска.

```bash
# Проверка: push в Dev и проверка появления в Prod
docker push harbor-dev.corp.local/myapp-dev/app:v1.3.0
# → v1.3.0: digest: sha256:abcd... size: 1024

curl -sk -u "robot$production+repl:$ROBOT_SECRET" \
  "https://harbor-prod.corp.local/v2/myapp-prod/app/tags/list"
# → {"name":"myapp-prod/app","tags":["v1.3.0"]}
```

> **Ограничение event-based:** удаление, retag и push триггерят репликацию. Изменение лейблов — нет. Для репликации по изменению лейблов используйте scheduled с фильтром по лейблу.

### Сценарий 3: Pull-based репликация по расписанию

Затягивание образов из внешнего реестра (например, Docker Hub) в изолированный контур:

1. Endpoint: Provider `Docker Hub`, URL `https://registry-1.docker.io`, учётные данные Docker Hub (повышают rate limits с 100 до 200 pulls/6ч для анонимных, до 5000 для аутентифицированных).
2. Правило: **Source** — endpoint Docker Hub, фильтр по проекту/репозиторию (`library/nginx`).
3. **Trigger**: **Scheduled**, cron `0 */6 * * *` (каждые 6 часов).
4. **Filters**: Name `library/nginx`, Tag `latest` или `1.2*`, Resource `artifact`.
5. **Save** → **Replicate**.

> **Важно для Docker Hub:** в имени репозитория обязательно указывайте `library/` для официальных образов (например, `library/nginx`, а не просто `nginx`).

### Сценарий 4: Pull-based репликация с удалением (sync зеркала)

Полная синхронизация зеркала upstream-реестра с удалением устаревших артефактов:

1. Endpoint: внешний реестр (Harbor / Docker Hub / ECR и т.д.).
2. Правило: **Pull-based**, Source — endpoint, Destination — локальный проект.
3. **Trigger**: **Scheduled**, cron `0 2 * * *` (ежедневно в 02:00).
4. **Filters**: широкий фильтр по имени (например, `**` для всего каталога) или конкретные репозитории.
5. **Override**: включено.
4. **Delete remote resources when locally deleted**: **НЕ включать** для pull-based (удаляет в источнике, а не в назначении — см. граничные случаи).

### Сценарий 5: Фильтры правила — расширенные паттерны

| Фильтр | Пример | Эффект |
| :--- | :--- | :--- |
| **Project name** | `myapp-dev` | Только артефакты проекта |
| **Name** | `library/**` | Все репозитории под library/ (двойная звёздочка = рекурсивно) |
| **Name** | `{library,goharbor}/**` | Альтернативы: library/** ИЛИ goharbor/** |
| **Tag** | `v*`, `release-*` | Только теги под маску |
| **Tag** | `1.?` | 1.0, 1.1, 1.9 — но не 1.10 |
| **Label** | `env=prod` | Только артефакты с лейблом |
| **Label decoration** | `matches` / `excludes` | Включить или исключить по лейблу |
| **Resource type** | `image` / `chart` / `artifact` | Тип артефакта (`artifact` = образы + OCI artifacts) |

Фильтры комбинируются (AND). Лейблы удобны для promotion: пометили артефакт лейблом `env=prod` — правило реплицирует его в Prod.

> **Паттерны name/tag:**
> - `*` — любые символы кроме `/`
> - `**` — любые символы включая `/` (должен быть отдельным компонентом пути: `path/**` валидно, `path**` нет)
> - `?` — один любой символ кроме `/`
> - `{alt1,alt2}` — альтернативы

### Сценарий 6: Мониторинг и диагностика репликации

```bash
# Статус задач репликации через API
curl -sk -u "admin:$PASS" \
  "https://harbor-dev.corp.local/api/v2.0/replication/executions" | \
  jq '.[] | {id, status, startTime: .start_time, resource: .resource}'

# Логи конкретного выполнения
curl -sk -u "admin:$PASS" \
  "https://harbor-dev.corp.local/api/v2.0/replication/executions/<execution_id>/tasks" | \
  jq '.[] | {status, statusText: .status_text}'

# Очередь задач Job Service (метрика Prometheus)
curl -s http://harbor-dev.corp.local:9090/metrics | grep harbor_task_queue_size
# → harbor_task_queue_size{...} 3

# Метрики репликации (Harbor 2.12+)
curl -s http://harbor-dev.corp.local:9090/metrics | grep -E 'harbor_replication_(total|duration|failures)'
# → harbor_replication_total{status="success"} 142
# → harbor_replication_duration_seconds_bucket{le="10"} 138
# → harbor_replication_failures_total 3
```

В UI: **Administration → Job Service Dashboard** — статус всех фоновых задач, включая репликацию.

**Harbor CLI** (goharbor/harbor-cli):
```bash
harbor replication policies list
harbor replication executions list --policy <policy_name>
harbor replication start --policy <policy_name>
```

## Операции и команды

| Задача | Команда / API |
| :--- | :--- |
| Список правил репликации | `GET /api/v2.0/replication/policies` |
| Создать правило | `POST /api/v2.0/replication/policies` |
| Запустить правило вручную | `POST /api/v2.0/replication/policies/{id}/execution` |
| Статус выполнений | `GET /api/v2.0/replication/executions` |
| Детали задачи | `GET /api/v2.0/replication/executions/{id}/tasks` |
| Список endpoints | `GET /api/v2.0/registries` |
| Создать endpoint | `POST /api/v2.0/registries` |
| Проверить endpoint | `POST /api/v2.0/registries/{id}/ping` |
| CLI: список правил | `harbor replication policies list` |
| CLI: запуск | `harbor replication start --policy <name>` |

## Валидация

```bash
# 1. Endpoint доступен
curl -sk -u "admin:$PASS" "https://harbor-dev.corp.local/api/v2.0/registries" | jq '.[] | {name, type, url}'

# 2. Правило существует и включено
curl -sk -u "admin:$PASS" "https://harbor-dev.corp.local/api/v2.0/replication/policies" | \
  jq '.[] | {name, enabled, trigger: .trigger.type}'

# 3. Артефакт реплицирован (digest совпадает)
DIGEST_DEV=$(skopeo inspect --format '{{.Digest}}' docker://harbor-dev.corp.local/myapp-dev/app:v1.3.0)
DIGEST_PROD=$(skopeo inspect --format '{{.Digest}}' docker://harbor-prod.corp.local/myapp-prod/app:v1.3.0)
[ "$DIGEST_DEV" = "$DIGEST_PROD" ] && echo "OK: digest совпадает"
# → OK: digest совпадает

# 4. Referrers (SBOM, подписи) реплицированы
skopeo inspect --format '{{json .Referrers}}' docker://harbor-prod.corp.local/myapp-prod/app:v1.3.0 | jq '.[] | select(.artifactType=="application/vnd.cncf.notary.v2.signature" or .artifactType=="application/spdx+json")'
# → должен показать реплицированные Referrers

# 5. Проверка метрик репликации
curl -s http://harbor-dev.corp.local:9090/metrics | grep harbor_replication_total
# → harbor_replication_total{status="success"} 142
```

## Troubleshooting

| Симптом | Причина | Решение |
| :--- | :--- | :--- |
| Задача репликации `Error` | Недоступен endpoint или неверные учётные данные | **Test Endpoint**; проверьте сеть, TLS, права робот-аккаунта |
| Артефакт не реплицируется | Фильтр не совпадает | Проверьте фильтры по тегу/лейблу/проекту; включите debug-логи Job Service |
| Репликация «зависла» | Очередь Job Service переполнена | Метрика `harbor_task_queue_size`; увеличьте `max_job_workers` в `harbor.yml` |
| `manifest unknown` в целевом реестре | Артефакт удалён GC в источнике | Перепушите артефакт в источник |
| Подписи не реплицируются | Подписи — отдельные Referrers | Harbor реплицирует Referrers вместе с артефактом (OCI 1.1); для legacy-Notary см. документацию |
| Event-based не срабатывает | Webhook/триггер отключён или неверный проект | Проверьте тип триггера в правиле и что push был в отфильтрованный проект |
| `401 Unauthorized` при push в целевой | Робот-аккаунт без прав Push в целевом проекте | Добавьте робот-аккаунт в проект назначения с ролью Project Admin или Custom с Push |
| `x509: certificate signed by unknown authority` | Самоподписанный TLS на целевом реестре | Включите **Insecure** или добавьте CA в trust store Harbor ( см. [operations.md](./operations.md#tls-сертификаты) ) |
| Репликация больших блобов падает (OOM) | Отсутствует chunked upload для Azure ACR | Harbor 2.16+: chunked blob upload включается автоматически для ACR; обновите версию |
| Pull-based: `rate limit exceeded` | Превышен лимит Docker Hub / upstream | Настройте аутентифицированный endpoint; используйте кэш-прокси; снизьте частоту cron |
| `Delete remote resources when locally deleted` удаляет не в том реестре | Непонимание направления | Для push-based: удаляет в destination. Для pull-based: удаляет в source (upstream)! Используйте с осторожностью. |

## Граничные случаи

* **Репликация и версии**: инстансы могут отличаться по версии Harbor, но сильно различающиеся мажорные версии могут не поддерживать общие фичи (например, Referrers API требует 2.11+ с обеих сторон). Минорные версии внутри 2.x совместимы для базовых операций.
* **Proxy Cache ≠ Replication**: proxy cache (см. [работу с Harbor](./usage.md#сценарий-6-настройка-proxy-cache-pull-through-cache)) — pull-only кэш upstream; репликация — полноценная синхронизация с фильтрами и триггерами.
* **Immutable теги в целевом проекте**: при включённом immutable теге и выключенном override репликация нового содержимого под тем же тегом отклоняется.
* **Квоты**: реплицированные артефакты учитываются в квоте целевого проекта — следите за `harbor_project_quota_usage_byte`.
* **Сетевые требования**: для event-based репликации целевой Harbor должен быть доступен с инстанса-источника (Job Service инициирует соединение).
* **Delete remote resources — направление действия**:
  - **Push-based**: при удалении артефакта в *источнике* он удаляется в *назначении* (безопасно для promotion).
  - **Pull-based**: при удалении артефакта в *источнике (upstream)* он удаляется в *Harbor* — но опция в UI называется одинаково, что вводит в заблуждение. Для pull-based зеркал используйте с осторожностью или отключите.
* **Event-based ограничения**: триггеры срабатывают на push, retag, delete. **Изменение лейблов не триггерит event-based репликацию**. Для репликации по лейблам используйте scheduled.
* **Chunked upload (Harbor 2.16+)**: автоматически используется для Azure ACR при push-based репликации больших блобов (>4MB). Для других провайдеров — стандартный монолитный upload.
* **Multi-arch репликация**: OCI Image Index и все child-артефакты реплицируются вместе по digest. Фильтр `Resource: artifact` включает и multi-arch манифесты. См. [multi_arch.md](./multi_arch.md).
* **Concurrency и производительность**: дефолт `max_job_workers=10`. Для больших репликаций (сотни образов за раз) увеличьте до 20-50 в зависимости от CPU/сети. Мониторьте `harbor_task_queue_size` и `harbor_replication_duration_seconds`.
* **Репликация в изолированные контуры (air-gapped)**: используйте pull-based с scheduled триггером; исходящие соединения инициирует изолированный Harbor. Event-based невозможен без входящей связи.

## Harbor и автоматизация обновления образов (ArgoCD Image Updater)

Harbor часто выступает источником истины для версий образов: CI пушит образ в Harbor, а GitOps-инструмент отслеживает реестр и обновляет манифесты. Два механизма:

| Механизм | Как работает | Интеграция с Harbor |
| :--- | :--- | :--- |
 | **ArgoCD Image Updater v1.x** | CRD `ImageUpdater`; отслеживает теги/дайджесты в реестре и обновляет манифесты (Git write-back или API) | Регистр в `argocd-image-updater-config` ConfigMap (`registries.conf`); аутентификация — робот-аккаунт Harbor (Pull Secret) |

**Типовая схема (ArgoCD Image Updater v1.x — CRD-based):**

```yaml
# ConfigMap для реестра
apiVersion: v1
kind: ConfigMap
metadata:
  name: argocd-image-updater-config
  namespace: argocd
data:
  registries.conf: |
    registries:
    - name: Harbor
      prefix: harbor.corp.local
      api_url: https://harbor.corp.local/api/v2.0
      credentials: secret://argocd/harbor-robot-secret
---
# Secret с робот-аккаунтом
apiVersion: v1
kind: Secret
metadata:
  name: harbor-robot-secret
  namespace: argocd
type: kubernetes.io/dockerconfigjson
stringData:
  .dockerconfigjson: <base64-encoded>
---
# ImageUpdater CR (v1.x)
apiVersion: argocd-image-updater.argoproj.io/v1alpha1
kind: ImageUpdater
metadata:
  name: myapp-updater
  namespace: argocd
spec:
  writeBackConfig:
    method: "git"
    gitConfig:
      repository: "git@github.com:myorg/infra.git"
      branch: "main"
      writeBackTarget: "helmvalues:./apps/myapp/values.yaml"
  applicationRefs:
  - namePattern: "myapp-prod"
    images:
    - alias: "app"
      imageName: "harbor.corp.local/myapp-prod/app:^1.0"
      commonUpdateSettings:
        updateStrategy: "semver"
        pullSecret: "secret://argocd/harbor-robot-secret"
```

**Legacy v0.x (аннотации — устарело):**
```yaml
# Аннотации в Application/манифесте ArgoCD
argocd-image-updater.argoproj.io/<alias>.image-list: myapp=harbor.corp.local/myapp-prod/app
argocd-image-updater.argoproj.io/<alias>.update-strategy: latest
# Аутентификация в Harbor: секрет с логином робот-аккаунта
#   формат логина: robot$myapp-prod+updater
```

**Рекомендации по безопасности:**
- Используйте отдельный робот-аккаунт для Image Updater с правами **Pull only** на нужных проектах
- Для приватных проектов создайте Kubernetes Secret с `username: robot$project+bot` и `password: <token>`

Полная практика обеих инструментов (установка, стратегии обновления, pin к digest, troubleshooting) — в [ArgoCD Image Updater](../../../GitOps/ArgoCD/argocd_image_updater.md); теория образов как артефактов в GitOps — [Containerization and Image Storage](../../../GitOps/Concepts/containerization_and_image_storage.md).

## Best Practices

| Область | Рекомендация |
| :--- | :--- |
| **Учётные данные** | Всегда используйте робот-аккаунты с минимальными правами (Pull/Push на конкретных проектах) |
| **Event-based vs Scheduled** | Event-based для promotion (Dev→Prod); Scheduled для зеркалирования upstream и air-gapped контуров |
| **Фильтры** | Используйте лейблы (`env=prod`, `release=true`) вместо сложных тег-паттернов — понятнее и безопаснее |
| **Override** | Включайте только когда понимаете последствия: перезапись тега в Prod может сломать развёрнутые поды |
| **Delete remote** | Для push-based promotion — безопасно. Для pull-based зеркал — **отключите**, иначе удаление в upstream удалит копии |
| **Мониторинг** | Настройте алерты на `harbor_replication_failures_total > 0` и `harbor_task_queue_size > 50` |
| **Производительность** | `max_job_workers`: 10 (дефолт) для малых инстансов; 20-50 для больших репликаций; мониторьте CPU/сеть Job Service |
| **TLS** | Всегда `Verify Remote Cert: true` в продакшене. Для самоподписанных — добавьте CA в trust store, не используйте Insecure |
| **Мульти-архитектура** | Фильтр `Resource: artifact` реплицирует и манифесты, и child-образы. Не фильтруйте по `image` отдельно. |
| **DR / Backup** | Репликация в резервный Harbor — часть DR-стратегии. Проверяйте восстановление раз в квартал. См. [upgrade_backup.md](./upgrade_backup.md) |
| **Версионирование** | Держите инстансы в одной мажорной ветке (2.x). Планируйте обновление заранее — Referrers API, chunked upload требуют 2.11+/2.16+ |

## Дополнительная информация

* Официальная документация: [Configuring Replication](https://goharbor.io/docs/2.16.0/administration/configuring-replication/).
* **Promotion образов между средами** (стратегии и GitOps) — [Image Promotion Strategies](../../../CI-CD/GitLab_CI/Advanced/image_promotion_strategies.md).
* **DR для реестра** — [Резервное копирование и DR для CI/CD](../../../CI-CD/Core_Concepts/ci_cd_backup_dr.md).
* **Harbor 2.16 Release Notes** — [v2.16.0](https://github.com/goharbor/harbor/releases/tag/v2.16.0) (chunked upload ACR, event policy filter, referrers proxy).

### Связанные документы

* **[Обзор Harbor](./overview.md)** — компоненты (Job Service).
* **[Работа с Harbor](./usage.md)** — базовый сценарий репликации, робот-аккаунты, webhook.
* **[Эксплуатация Harbor](./operations.md)** — тюнинг `max_job_workers`, метрики, TLS.
* **[Harbor REST API](./api.md)** — автоматизация репликации.
* **[SBOM](./sbom.md)** — репликация SBOM с артефактом.
* **[Лейблы](./labels.md)** — фильтры репликации по лейблам.
* **[Multi-arch](./multi_arch.md)** — репликация OCI Image Index.
* **[P2P Preheat](./p2p_preheat.md)** — драконы и репликация для распределённых кластеров.
