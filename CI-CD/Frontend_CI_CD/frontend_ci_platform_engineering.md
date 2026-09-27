**Актуально для:** GitLab CI 16+, Kubernetes 1.29+, GitLab Runner 16+

# CI Platform Engineering для фронтенда

## Определения

- **Self-hosted Runner** — машина/контейнер, выполняющий CI-джобы внутри вашей инфраструктуры.
- **Runner Fleet** — группа раннеров с одинаковой конфигурацией, масштабируемая под нагрузку.
- **Executor** — стратегия выполнения джобы: `docker`, `kubernetes`, `shell`, `custom`.
- **Ephemeral Runner** — одноразовый раннер, создаваемый для джобы и удаляемый после выполнения.
- **DAG (Directed Acyclic Graph)** — граф зависимостей между джобами; позволяет запускать независимые джобы параллельно, сокращая общее время пайплайна.
- **Parent-child Pipeline** — родительский пайплайн запускает дочерние через trigger, передавая артефакты и переменные.
- **Isolation Boundary** — граница изоляции между джобами: контейнер (Docker), pod (Kubernetes), VM (shell) или хост (custom).
- **Runner Contamination** — накопление артефактов, кэша или состояния в persistent runner между джобами, ведущее к недетерминированным сборкам.
- **Queue Depth** — количество задач, ожидающих свободный раннер с нужным tag; ключевая метрика для autoscaling.
- **Cache Poisoning** — повреждение или подмена содержимого кэша посторонними результатами; предотвращается подписью remote cache и изоляцией.
- **Concurrent Limit** — максимальное количество одновременно выполняемых джоб на раннере; определяется лицензией GitLab и ресурсами executor'а.
- **Artifact Retention** — политика хранения артефактов сборки; для production должна превышать окно возможного отката.
- **Runner Tag Affinity** — механизм маршрутизации джоб на раннеры с соответствующими тегами; AND-логика для нескольких тегов.
- **Fan-in** — паттерн parent-child pipeline, где родитель собирает артефакты от нескольких дочерних пайплайнов.
- **Runner Churn** — частота создания и удаления раннеров; высокий churn увеличивает нагрузку на управляющий plane и registry.

---

## Предварительные требования

- **GitLab CI:** инстанс 16+ (self-hosted); API доступ для регистрации раннеров; лицензия поддерживает необходимое количество concurrent джоб.
- **Kubernetes:** кластер v1.29+ с включёнными стабильными API (`apps/v1`, `autoscaling/v2`); RBAC для service account раннеров; CNI-плагин поддерживающий NetworkPolicy.
- **GitLab Runner:** binary или Helm chart установлен на управляющие узлы fleet; `config.toml` настроен под выбранный executor.
- **Registry:** внутренний OCI-реестр (Harbor, GitLab Container Registry, Nexus) с поддержкой digest и Referrers API; раннеры имеют права на pull/push.
- **Секреты:** Vault 1.15+ или защищённые переменные CI для токенов регистрации, registry credentials, API ключей; secrets не должны попадать в логи.
- **Сеть:** egress от кластера/раннеров к GitLab API, registry, Vault; ingress для UI/API GitLab; DNS resolving для registry и GitLab хоста.
- **Мониторинг:** Prometheus + node_exporter на узлах fleet; Grafana для дашбордов; алертинг на queue time, runner availability, cache hit rate.
- **RBAC:** namespace `gitlab-runner` с минимальными правами для service account; отдельные runners с tags для preview/production.

---

## Основные концепции

### Проблемы фронтенд-CI

Фронтенд-пайплайны имеют специфику, усиливающую общие проблемы CI/CD:

1. **Медленные сборки:** `npm install` + build на каждом джобе без кэша; в монорепо эффект умножается на количество пакетов.
2. **Нестабильные раннеры:** persistent runners с "заражённым" кэшем (`node_modules`, `.turbo`, `.nx/cache`) дают недетерминированные сборки.
3. **Очереди:** при bottleneck на fleet MR копятся, feedback loop растёт; для фронтенда это критично из-за частых релизов и hotfixes.
4. **Изоляция:** shared runners без namespacing уязвимы для cross-project contamination и утечки артефактов между командами.
5. **Стоимость:** переспрос ресурсов без autoscaling leads to either underutilization (idle runners) или overprovisioning (excess capacity).
6. **Cache invalidation:** неверные ключи кэша или его отравление приводят к rebuild всего `node_modules` на каждом пуше.

### Архитектура runner fleet

```
GitLab CI Server
  └── Runner Manager (gitlab-runner process)
       ├── Runner (Docker executor) → ephemeral container per job
       ├── Runner (Kubernetes executor) → pod per job
       ├── Runner (Shell executor) → persistent VM/container
       └── Runner (Custom executor) → bare-metal/ specialised env
            │
            ├── tags: [frontend-build, node-22, x86_64]
            ├── cache: объектное хранилище/MinIO (shared)
            └── concurrency: concurrent * limit
```

**Executor selection для фронтенда:**

| Executor | Изоляция | Масштабирование | Стоимость | Когда использовать |
|:---|:---|:---|:---|:---|
| **docker** | Контейнер | Вертикальное (на хосте) | Средняя | Стандарт для frontend-build джоб; требует DinD или Kaniko |
| **kubernetes** | Pod | Горизонтальное (cluster) | Средняя/низкая при нагрузке | Высокие нагрузки, ephemeral pods, K8s-native инфраструктура |
| **shell** | Нет (shared host) | Нет | Низкая | Только legacy/системные джобы |
| **custom** | Зависит от реализации | Зависит | Высокая | Bare-metal, macOS, embedded окружения |

**Lifecycle runner'а:**
```
Registration → Polling → Job assigned → Executor creates env → Script runs →
Artifacts uploaded → Env destroyed → Runner returns to pool
```

**Ephemeral runner** создаётся и удаляется за один цикл джобы; не хранит состояние между запусками. Это предотвращает contamination, но требует remote cache для ускорения повторных сборок.

**Persistent runner** переиспользуется между джобами; хранит локальный кэш. Экономит время на cold start, но требует обязательной очистки (`cleanup_policy`) и изоляции через tags.

### Cache strategy

| Тип кэша | Хранилище | Скорость | Изоляция | Рекомендация |
|:---|:---|:---|:---|:---|
| Локальный (runner disk) | Disk runner'а | Высокая | Нет | Только persistent runner, single-job |
| Объектное хранилище/MinIO | Object storage | Средняя | По ключу | Стандарт для fleet; требуется для ephemeral runners |
| Remote Turborepo/Nx | Объектное хранилище + подпись | Высокая | По хэшу задач | Монорепо с Turborepo/Nx; обязателен при ephemeral runners |

**Cache key strategy:**
- `cache:key:files` — хэш lock-файла; при изменении lock-файла кэш автоматически инвалидируется. Рекомендуется для `node_modules`.
- По branch/ref — изоляция между ветками; риск утечки артефактов между MR при shared runners.
- По job name — минимальная изоляция; риск contamination при параллельных джобах.

### Artifact lifecycle

Артефакты (`dist/`, coverage, Lighthouse reports, source maps) передаются между stages без повторной сборки. Retention policy:

- **Preview:** 7–30 дней (соответствует TTL preview-окружений).
- **Production:** 90+ дней с versioning; для production откатов нужен доступ к артефакту, по которому был сделан deployment.
- **Security:** артефакты, содержащие source maps или чувствительные данные, должны иметь restricted access и автоматическое удаление по TTL.

### Queue theory

Queue time = время от коммита до начала выполнения джобы на раннере. Две составляющие:

1. **Scheduler delay** — GitLab API отвечает на poll; нормально < 1s.
2. **Resource wait** — нет свободного раннера с нужным tag; здесь работает autoscaling.

**Queue depth alerting:**
- Warning: queue time > 5 минут.
- Critical: queue time > 30 минут или pending jobs > 10.

### Cost model

| Модель | Fixed | Variable | Когда использовать |
|:---|:---|:---|:---|
| Static fleet | Высокий | Низкий | Предсказуемые нагрузки, >80% utilization |
| Autoscaling | Средний | Средний | Переменные нагрузки, непиковые часы |
| Ephemeral K8s | Низкий | Высокий при нагрузке | Высоконагруженные, variable load |
| Serverless CI | Нет | Высокий per-job | Инфраструктурно-лёгкие, редкие запуски |

---

## Практические сценарии

### Сценарий 1: Kubernetes executor с ephemeral pods для фронтенд-раннеров

```yaml
# values.yaml для GitLab Runner Helm chart
gitlabUrl: https://gitlab.example.com/
runnerRegistrationToken: "${RUNNER_TOKEN}"
runners:
  config: |
    [[runners]]
      [runners.kubernetes]
        image = "node:22-bookworm"
        privileged = false
        namespace = "gitlab-runner"
        poll_timeout = 180
        cpu_request = "250m"
        cpu_limit = "500m"
        memory_request = "512Mi"
        memory_limit = "1Gi"
        [runners.kubernetes.node_selector]
          "node-type" = "frontend-ci"
        [runners.kubernetes.tolerations]
          "frontend-ci" = ["dedicated"]
  cache:
    secretName: runner-cache
```

**Валидация:**
```bash
# Раннеры online и active
gitlab-runner list
# → all runners show "online: true, active: true"

# Pod'ы создаются и удаляются после джобы
kubectl get pods -n gitlab-runner -w
# → pods appear during job, disappear after completion

# Cache hit rate
grep -E "Checking cache|Restored cache" <job-log>
# → "Restored cache" appears for cache hits
```

**Troubleshooting:**
| Проблема | Причина | Решение |
|:---|:---|:---|
| Pod stuck in Pending | Нет подходящего node (selector/toleration) | Проверить `kubectl describe node`, labels |
| Cache не восстанавливается | Неверный secretName или endpoint | Проверить `runner-cache` secret, connectivity |
| OOMKilled | memory_limit недостаточен для build | Увеличить до 2Gi или добавить swap |

### Сценарий 2: DAG оптимизация с `needs`

```yaml
# .gitlab-ci.yml — эффективный DAG
stages:
  - install
  - lint
  - test
  - build
  - deploy

install:
  stage: install
  cache:
    key: ${CI_COMMIT_REF_SLUG}-node
    paths:
      - node_modules/
  script:
    - npm ci

lint:
  stage: lint
  needs: [install]
  cache:
    key: ${CI_COMMIT_REF_SLUG}-node
    policy: pull
  script:
    - npm run lint

test:
  stage: test
  needs: [install]
  cache:
    key: ${CI_COMMIT_REF_SLUG}-node
    policy: pull
  script:
    - npm test

build:
  stage: build
  needs: [lint, test]
  script:
    - npm run build
  artifacts:
    paths:
      - dist/
    expire_in: 7 days

deploy:
  stage: deploy
  needs: [build]
  script:
    - ./deploy.sh
  environment:
    name: production
```

**Валидация:**
```bash
# Pipeline DAG visualization
# В GitLab UI: CI/CD → Pipelines → [pipeline] → DAG view
# → lint и test параллельны после install; build ждёт оба; deploy ждёт build

# Проверка параллелизма
# → lint и test запускаются одновременно, нет ожидания
```

**Troubleshooting:**
| Проблема | Причина | Решение |
|:---|:---|:---|
| DAG не работает (stages sequential) | GitLab < 12.3 или `needs` не поддерживается | Проверить версию GitLab; обновить до 16+ |
| Cache miss при parallel jobs | Разные runners без shared cache | Настроить shared cache в объектном хранилище |
| Artifact не передаётся | `needs` без `dependencies` или `artifacts:true` | Добавить `dependencies: [build]` или `artifacts: true` |

### Сценарий 3: Parent-child pipeline для монорепо

```yaml
# Parent pipeline (.gitlab-ci.yml)
stages:
  - detect
  - trigger

detect_changes:
  stage: detect
  script:
    - |
      APPS=$(npx turbo run build --filter=...[origin/main] --dry=json | jq -r '.tasks[].package')
      echo "APPS=$APPS" >> variables.env
  artifacts:
    reports:
      dotenv: variables.env

trigger_app_checkout:
  stage: trigger
  needs: [detect_changes]
  trigger:
    include: .gitlab/ci/app-pipeline.yml
    strategy: depend
    variables:
      APP_NAME: $APP_NAME
```

```yaml
# Child pipeline (.gitlab/ci/app-pipeline.yml)
.stage_template:
  stage: build
  script:
    - cd $APP_NAME && npm ci && npm run build
  artifacts:
    paths:
      - $APP_NAME/dist/
    expire_in: 7 days

build_checkout:
  extends: .stage_template
  only:
    changes:
      - apps/checkout/**

build_catalog:
  extends: .stage_template
  only:
    changes:
      - apps/catalog/**
```

**Валидация:**
```bash
# Child pipeline получает переменные
# → $APP_NAME populated correctly
# Артефакты передаются от child к parent
# → parent pipeline shows artifacts from child
```

**Troubleshooting:**
| Проблема | Причина | Решение |
|:---|:---|:---|
| Child pipeline не видит переменные | `strategy: depend` не установлен | Добавить `strategy: depend` |
| Долгий parent-child pipeline | Родитель ждёт все дочерние | `strategy: depend` или fetch artifacts |
| Artifact lost между pipeline | `artifacts:paths` не совпадает | Проверить paths в child, expire_in |

### Сценарий 4: Автомасштабирование раннеров (Kubernetes executor)

```yaml
# GitLab Runner Autoscaling with Kubernetes
# config.toml
[[runners]]
  name = "frontend-autoscale"
  executor = "kubernetes"
  [runners.kubernetes]
    namespace = "gitlab-runner"
    cpu_request = "250m"
    cpu_limit = "500m"
    memory_request = "512Mi"
    memory_limit = "1Gi"
    [runners.kubernetes.autoscaling]
      capacity = [10, 50]  # min, max pods
      idle_count = 5
      max_requests = 10
```

**Валидация:**
```bash
# При нагрузке создаются новые pods
kubectl get pods -n gitlab-runner -w
# → pods scale up during load, down during idle

# Queue time метрика
# gitlab_runner_job_queue_duration_seconds < 30s
```

**Troubleshooting:**
| Проблема | Причина | Решение |
|:---|:---|:---|
| Pods не создаются | HPA не настроен или resource quota исчерпан | Проверить `kubectl get hpa`, quota |
| Idle pods не удаляются | `idle_count` слишком высок или grace period | Уменьшить idle_count, проверить terminationGracePeriod |
| Throttling | cpu/memory limit достигнут | Увеличить limits или добавить node pool |

### Сценарий 5: Cache strategy с объектным хранилищем

```toml
# config.toml — cache в объектное хранилище
[cache]
  Type = "s3"
  Shared = true
  [cache.s3]
    ServerAddress = "minio.internal:9000"
    BucketName = "runner-cache"
    Insecure = false
```

```yaml
# .gitlab-ci.yml — cache key по lock-файлу
cache:
  key:
    files:
      - package-lock.json
      - turbo.json
  paths:
    - node_modules/
    - .turbo/
```

**Валидация:**
```bash
# Cache hit rate в логе джобы
grep -E "Checking cache|Restored cache|Created cache" <job-log>
# → hit rate > 80% для стабильного репозитория
```

**Troubleshooting:**
| Проблема | Причина | Решение |
|:---|:---|:---|
| Cache miss при каждом запуске | Разные runners без shared cache или неверный key | Проверить Shared=true, bucket policy |
| Cache poisoning | Compromised runner или отсутствие подписи | Подпись remote cache, rotation credentials |
| Object storage timeout | Сетевая разделённость или endpoint недоступен | Проверить connectivity, DNS, endpoint |

---

## Операционные команды

```bash
# Регистрация нового runner'а
gitlab-runner register \
  --url https://gitlab.example.com/ \
  --token $RUNNER_TOKEN \
  --executor kubernetes \
  --tag-list frontend-build,node-22 \
  --run-untagged=false \
  --locked=true

# Проверка состояния runners
gitlab-runner list
# → online: true, active: true, tags: [frontend-build]

# Верификация runners
gitlab-runner verify
# → Verifying runner... is alive

# Очистка Docker resources (persistent runner)
docker system prune -a --filter "until=168h"
docker builder prune -a --filter "until=168h"

# Проверка queue metrics
curl -s http://gitlab-runner:9252/metrics | grep gitlab_runner_job_queue_duration_seconds

# Проверка cache hit rate
grep -c "Restored cache" /tmp/job.log | awk '{print "Cache hits:", $1}'

# Snapshot config.toml
cp /etc/gitlab-runner/config.toml /backup/config.toml.$(date +%Y%m%d)

# Диагностика runner fleet
gitlab-runner status && gitlab-runner --version && \
sudo journalctl -u gitlab-runner --no-pager -n 20
```

---

## Типичные проблемы

| Проблема | Причина | Решение |
|:---|:---|:---|
| Медленная очередь | Недостаточно runners или bottleneck на executor | Автомасштабирование, увеличить concurrent, добавить pool |
| Кэш не переиспользуется | Разные ключи или отсутствие shared cache | Стандартизировать `cache:key:files` по lock-файлу |
| Долгий parent-child pipeline | Родитель ждёт все дочерние | `strategy: depend`, fan-in optimization |
| Runner offline | Ресурсы исчерпаны или network partition | `gitlab-runner verify`, проверить node health |
| Зависшие джобы | Runner убит во время выполнения | `interrupt_timeout`, graceful shutdown, PDB |
| Разные версии Node | Разные образы runners | Фиксировать `image: node:22-bookworm` в джобах |
| Конфликты портов SSR | Persistent runner переиспользует порт | Ephemeral runner или динамические порты |
| Cache poisoning | Compromised runner или нет подписи | Подпись remote cache, rotation credentials |
| Queue depth > 30 min | Нет autoscaling или max capacity достигнут | Увеличить capacity, добавить pool |
| Artifact 404 в CI | `expire_in` слишком короткий | Увеличить до 30–90 дней; production — бессрочно + versioning |

---

## Особые случаи

- **Monorepo (>50 пакетов):** affected-анализ и граф задач занимают десятки секунд. Используйте parent-child пайплайны: родитель вычисляет affected-список, дочерний запускает задачи только для затронутых проектов.
- **Force-push в main:** affected-анализ относительно `origin/main` даёт корректный результат только при линейной истории. При force-push используйте merge-base или защищайте ветку политикой `no force push`.
- **Cache key collision:** если `package-lock.json` меняется в каждом пуше (например, через `npm audit`), remote cache не переиспользуется. Используйте отдельный lock-файл для CI или отключайте автоматические обновления audit.
- **Ephemeral runners и remote cache:** при использовании эфемерных раннеров локальный `.turbo`/`.nx/cache` не сохраняется между джобами, поэтому remote cache обязателен.
- **Dependency hoisting в pnpm/workspace:** hoisting меняет структуру `node_modules`, что влияет на хэш задачи. Фиксируйте workspace Protocol или используйте одинаковый менеджер пакетов.
- **Runner node failure:** при outage узла с persistent runner'ами джобы завершаются с ошибкой. Настройте `interrupt_timeout` и graceful shutdown; используйте ephemeral runners для критичных джоб.
- **Concurrent limit и лицензия:** GitLab CE/EE имеет лимит concurrent джоб; при его достижении новые джобы стоят в очереди несмотря на доступные runners. Мониторьте `gitlab_runner_active_jobs` vs `concurrent`.
- **Registry mirror outage:** при недоступности primary registry CI/CD не может pull/push образов. Настройте registry mirror с webhook trigger; RTO для registry = интервал репликации.
- **Секреты в runner environment:** runner с доступом к Vault/registry должен иметь minimal RBAC; используйте OIDC id_tokens вместо статических ключей.
- **Горячие кэши в preview:** preview-окружения создаются и удаляются автоматически; кэшировать `node_modules` для preview нецелесообразно — используйте shared remote cache с TTL.

---

## Лучшие практики

1. Используйте Kubernetes executor с ephemeral pods для максимальной изоляции и отсутствия contamination.
2. Настройте autoscaling: `capacity = [min, max]`, `idle_count` для экономии; мониторьте queue time.
3. Кэшируйте `node_modules` и `.turbo` по хэшу lock-файла (`cache:key:files`).
4. Для монорепо используйте affected builds + parent-child pipelines; детали — в **[Монорепо CI для фронтенда](./monorepo_frontend_ci.md)**.
5. Фиксируйте версию Node.js через `image: node:22-bookworm` в джобах; не полагайтесь на default на runner'е.
6. Разделяйте runners по типам задач: `frontend-build`, `frontend-deploy`, `frontend-e2e` через tags.
7. Используйте shared cache в объектном хранилище/MinIO с `Shared = true`; мониторьте cache hit rate, алерт при < 80%.
8. Мониторьте queue time (`gitlab_runner_job_queue_duration_seconds`) и алерт при > 5 минут.
9. Для runner'ов с persistent executor настройте `cleanup_policy = "always"` и `clean_period = "24h"`.
10. Используйте OIDC id_tokens для аутентификации в Vault/registry; избегайте статических ключей в переменных CI.
11. Храните `config.toml` в configuration management (Ansible, Puppet); версионируйте изменения.
12. Для DAG используйте `needs` вместо sequential stages; это сокращает время pipeline на 30–50%.
13. Настройте admission controller (OPA/Gatekeeper/Kyverno) для проверки манифестов registry перед применением.
14. Ведите inventory runner'ов: tags, executor type, capacity, owner; обновляйте при изменениях fleet.
15. Тестируйте failover runner fleet: отключайте node/runner, проверяйте autoscaling и queue behavior.
16. Для artifact retention в production используйте 90+ дней с versioning в object storage; настройте lifecycle policy.

---

## Дополнительная информация

### См. также

- **[GitLab CI: runners и executors](../../CI-CD/GitLab_CI/Advanced/gitlab_ci_runners_executors.md)** — типы executor, конфигурация, безопасность, Fleet architecture.
- **[Монорепо CI для фронтенда](./monorepo_frontend_ci.md)** — Turborepo/Nx, affected builds, remote cache.
