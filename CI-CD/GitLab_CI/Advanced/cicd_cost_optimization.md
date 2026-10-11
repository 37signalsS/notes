# CI/CD Cost Optimization

**Актуально для:** GitLab 18.x / GitLab Runner 19.x

> Область применения: on-premise / self-hosted GitLab. Публичные облака и AI-технологии в данном документе не рассматриваются.

## Определения

**CI/CD Cost Optimization** — процесс минимизации совокупной стоимости владения (TCO) инфраструктуры CI/CD на self-hosted GitLab без потери производительности и качества доставки ПО. Включает оптимизацию compute, storage, network и лицензионных расходов.

**Cost per Pipeline** — удельная стоимость одного запуска пайплайна, складывающаяся из потребления CPU, RAM, дискового пространства и сетевого трафика на Runner'ах и сервере GitLab.

**Effective Cost** — реальная стоимость вычислительных ресурсов с учётом их утилизации. Формула:

```
Effective Cost = Nominal Cost / Utilization Rate
```

При низкой утилизации (например, 30%) effective cost в 3+ раза превышает номинальный, что делает right-sizing Runner'ов ключевым фактором оптимизации.

**Cache Hit Rate** — доля успешных восстановлений кэша от общего числа запусков. Ключевая метрика эффективности использования хранилища и сетевых ресурсов.

**Artifact Retention Cost** — стоимость хранения артефактов во времени, определяемая объёмом хранилища, политиками Retention и частотой доступа.

## Основные концепции

### Архитектура стоимости self-hosted GitLab

Стоимость инфраструктуры CI/CD в on-premise окружении состоит из четырёх компонентов:

| Компонент | Источники затрат | Механизмы оптимизации |
|:---|:---|:---|
| **Compute** | CPU/RAM Runner'ов, время выполнения задач | Right-sizing, параллелизация, DAG, auto-scaling |
| **Storage** | Артефакты, кэш, логи, Docker layers | Retention policies, сжатие, lifecycle, очистка |
| **Network** | Трафик Runner ↔ GitLab, Registry, внешние зависимости | Кэширование зависимостей, remote cache, артефакты вместо кэша для больших файлов |
| **License** | GitLab Premium/Ultimate, инструменты сборки | Оптимальный тариф, модульность пайплайнов |

### Факторы, влияющие на стоимость

**Compute:**
- Тип и количество Runner'ов (concurrent, limit)
- Утилизация CPU/RAM (utilisation rate)
- Время выполнения задач (duration)
- Количество параллельных запусков
- Использование ephemeral runners vs persistent

**Storage:**
- Объём артефактов (`.statistics.build_artifacts_size`)
- Размер кэша (локальный + remote)
- Retention period (`expire_in`)
- Параметр `keep_latest` (по умолчанию включён)
- Логи пайплайнов (настраивается в Admin Area)

**Network:**
- Загрузка зависимостей (npm, pip, maven)
- Передача артефактов между стадиями
- Доступ к реестрам (GitLab Container Registry, Nexus, Artifactory)
- Внешние API (Vault, scanners)

**License:**
- GitLab тариф (Free, Premium, Ultimate)
- Количество seats
- Включённые фичи (Compliance Frameworks, Pipeline Execution Policies, Merge Trains)

### Экономика Runner'ов

**Утилизация как ключевой показатель:**

| Утилизация | Effective Cost | Рекомендация |
|:---|:---|:---|
| < 40% | 2.5x номинальной стоимости | Right-sizing или уменьшение парка |
| 40–70% | 1.4–2.5x | Оптимальный диапазон для dedicated runners |
| 70–85% | 1.2–1.4x | Высокая эффективность |
| > 85% | < 1.2x | Риск очередей; рассмотрите масштабирование |

**Параметры `config.toml`, влияющие на стоимость:**

| Параметр | Влияние на стоимость |
|:---|:---|
| `concurrent` | Глобальный лимит параллельных задач; избыток ведёт к простояю |
| `limit` (per runner) | Лимит задач на конкретный Runner; помогает балансировать нагрузку |
| `check_interval` | Частота опроса очереди; слишком частое опрос увеличивает нагрузку на API |
| `shutdown_timeout` | Время graceful shutdown; влияет на утилизацию ресурсов |
| `clean_policy` / `clean_period` | Автоматическая очистка Docker ресурсов; предотвращает утечку диска |
| `pull_policy` | `if-not-present` сокращает трафик и время загрузки образов |
| `shm_size` | Недостаток `/dev/shm` приводит к падениям и повторам задач |

### Оптимизация артефактов и хранилища

**Параметр `expire_in`** — основной инструмент управления стоимостью хранения. Формат: `<число> <единица>` (`1 hour`, `7 days`, `30 days`) или `never`.

| Тип артефакта | Рекомендуемый `expire_in` | Обоснование |
|:---|:---|:---|
| Промежуточные сборки (build) | 1–7 дней | Нужны только для последующих стадий |
| Отчёты тестирования | 7–30 дней | Требуются для аудита и отладки |
| Docker образы (CI artifacts) | 7 дней | В продакшен пушатся в Registry |
| Логи пайплайнов | 7–30 дней | Доступны в UI GitLab |
| Release артефакты | `never` или 90+ дней | Критичны для отката и аудита |

**`keep_latest`** — по умолчанию GitLab сохраняет артефакты последнего успешного пайплайна в ветке независимо от `expire_in`. Это может приводить к неконтролируемому росту хранилища. Управляется в **Admin Area > CI/CD > Continuous Integration** (instance-level) или **Settings > CI/CD > Artifacts** (group/project-level, Premium+).

### Оптимизация кэша

Cache hit rate напрямую влияет на стоимость:

| Cache Hit Rate | Эффективность | Действие |
|:---|:---|:---|
| < 50% | Низкая | Ключи слишком специфичные или кэш редко используется |
| 50–75% | Приемлемая | Есть потенциал улучшения через `cache:key:files` |
| 75–90% | Хорошая | Стабильная работа |
| > 90% | Отличная | Экономия времени и трафика |

**Важно:** зависимости (`node_modules`, `vendor`, `.m2`) должны кэшироваться, а не передаваться через артефакты. Передача зависимостей через артефакты создаёт архивы размером в сотни мегабайт на каждый запуск, засоряет хранилище и замедляет пайплайн.

### Разделение артефактов и кэша

Артефакты и кэш решают разные задачи:

| Механизм | Назначение | Надёжность | Размер |
|:---|:---|:---|:---|
| `cache` | Зависимости, ускоряющие повторные запуски | Best-effort | Ограничен лимитом Runner'а |
| `artifacts` | Результаты сборки, передаваемые между стадиями | Guaranteed delivery | До 100 MB (instance default) |

## Практические сценарии

### Сценарий 1: Анализ потребления хранилища артефактов (SysAdmin)

```bash
#!/bin/bash
# analyze_artifact_storage.sh
# Анализ потребления хранилища артефактами

GITLAB_URL="https://gitlab.example.com"
TOKEN="$GITLAB_API_TOKEN"

echo "=== Top 10 проектов по размеру артефактов ==="
curl --header "PRIVATE-TOKEN: $TOKEN" \
  "$GITLAB_URL/api/v4/projects?order_by=build_artifacts_size&sort=desc&per_page=10" | \
  jq '.[] | {name: .name, size: (.statistics.build_artifacts_size / 1024 / 1024 | floor), artifacts_size: .statistics.build_artifacts_size}'

echo ""
echo "=== Проверка глобальных настроек ==="
curl --header "PRIVATE-TOKEN: $TOKEN" \
  "$GITLAB_URL/api/v4/application/settings" | \
  jq '{artifacts_size_limit, ci_max_artifact_size, keep_latest_artifact, artifact_expired_before}'
```

### Сценарий 2: Аудит retention policies

Проверка настроек `expire_in` и `keep_latest` на уровне group/project:

```bash
#!/bin/bash
# audit_retention.sh
# Аудит настроек хранения артефактов

GITLAB_URL="https://gitlab.example.com"
TOKEN="$GITLAB_API_TOKEN"
GROUP_ID="67890"

echo "=== Retention policies для проектов группы ==="
curl --header "PRIVATE-TOKEN: $TOKEN" \
  "$GITLAB_URL/api/v4/groups/$GROUP_ID/projects?per_page=100" | \
  jq -r '.[] | "\(.path_with_namespace)\t\(.statistics.build_artifacts_size / 1024 / 1024 | floor) MB"'
```

### Сценарий 3: Очистка старых артефактов

```bash
#!/bin/bash
# cleanup_old_artifacts.sh
# Очистка артефактов через rake-задачу (self-managed)

echo "=== Очистка артефактов старше 30 дней ==="
echo "DRY_RUN: $DRY_RUN"

if [ "$DRY_RUN" = "true" ]; then
  echo "DRY RUN: gitlab-rake gitlab:artifacts:expire"
else
  sudo gitlab-rake "gitlab:artifacts:expire"
fi
```

Для проектов с S3-совместимым хранилищем (MinIO, Ceph RGW) настройте Lifecycle Policies для автоматического удаления объектов старше N дней.

### Сценарий 4: Оптимизация Docker образов

```dockerfile
# Multi-stage build для минимизации размера образа
FROM golang:1.22-alpine AS builder
WORKDIR /app
COPY go.mod go.sum ./
RUN go mod download
COPY . .
RUN CGO_ENABLED=0 go build -ldflags="-s -w" -o /app/binary

FROM alpine:3.19
RUN addgroup -g 1000 -S appgroup && adduser -u 1000 -S appuser -G appgroup
WORKDIR /app
COPY --from=builder /app/binary /app/binary
USER appuser
ENTRYPOINT ["/app/binary"]
```

| Образ | До | После | Экономия |
|:---|:---|:---|:---|
| Node.js | ~1.2 GB | ~180 MB | 85% |
| Python | ~950 MB | ~220 MB | 77% |
| Go | ~800 MB | ~15 MB | 98% |

### Сценарий 5: Правильное разделение cache и artifacts

```yaml
variables:
  PIP_CACHE_DIR: "$CI_PROJECT_DIR/.cache/pip"
  NPM_CONFIG_CACHE: "$CI_PROJECT_DIR/.cache/npm"

# Зависимости — через cache
build:
  stage: build
  cache:
    key:
      files:
        - package-lock.json
    paths:
      - .cache/npm
      - node_modules/
    policy: pull-push
  script:
    - npm ci
    - npm run build
  artifacts:
    paths:
      - dist/
    expire_in: 7 days

# Тесты — только чтение кэша
test:
  stage: test
  cache:
    key:
      files:
        - package-lock.json
    paths:
      - .cache/npm
    policy: pull
  script:
    - npm test
```

### Сценарий 6: Анализ утилизации Runner'ов

```bash
#!/bin/bash
# analyze_runners.sh
# Анализ использования GitLab runners

GITLAB_URL="https://gitlab.example.com"
TOKEN="$GITLAB_API_TOKEN"

echo "=== Runner Fleet Utilization ==="

RUNNERS=$(curl --header "PRIVATE-TOKEN: $TOKEN" \
  "$GITLAB_URL/api/v4/runners?per_page=100" | jq -r '.[] | "\(.id)\t\(.description)\t\(.status)\t\(.active)\t\(.online)\t\(.jobs_completed)"')

echo "$RUNNERS" | while IFS=$'\t' read -r id desc status active online jobs; do
  echo "Runner $id: $desc | status=$status | active=$active | online=$online | jobs=$jobs"
done
```

### Сценарий 7: Настройка config.toml для оптимизации стоимости

```toml
# /etc/gitlab-runner/config.toml
concurrent = 20              # Глобальный лимит; подбирайте под CPU/RAM хоста
check_interval = 3
shutdown_timeout = 30

[session_server]
  session_timeout = 1800
  session_affinity = true

[[runners]]
  name = "docker-prod"
  url = "https://gitlab.example.com"
  token = "glrt-xxxxxxxxxxxx"
  executor = "docker"
  limit = 10                 # Лимит задач на этом Runner'е
  max_concurrent = 10

  [runners.docker]
    image = "alpine:latest"
    privileged = false
    shm_size = "256m"
    pull_policy = ["if-not-present"]
    memory = "4g"
    cpus = "2"
    volumes = ["/cache", "/tmp/artifacts:/tmp/artifacts"]
    security_opt = ["no-new-privileges"]

  [runners.cache]
    Type = "s3"
    Shared = true
    [runners.cache.s3]
      ServerAddress = "minio.internal:9000"
      BucketName = "runner-cache"
      Insecure = false
```

### Сценарий 8: Conditional jobs для экономии

```yaml
# Пропуск лишних задач
test:unit:
  stage: test
  rules:
    - changes:
        - src/**/*
        - tests/**/*
    - if: $CI_PIPELINE_SOURCE == "merge_request_event"
  script:
    - npm run test:unit

# Запуск только при изменениях в инфраструктуре
deploy:infra:
  stage: deploy
  rules:
    - changes:
        - terraform/**/*
        - ansible/**/*
  script:
    - ./deploy-infra.sh
```

## Устранение неполадок (Troubleshooting)

| Проблема | Причина | Решение |
|:---|:---|:---|
| Высокий effective cost | Низкая утилизация Runner'ов (<40%) | Уменьшите парк или добавьте автоскейлинг; см. **[Управление парком Runner'ов](../Advanced/runner_fleet_management.md)** |
| Хранилище артефактов растёт | `keep_latest` включён, `expire_in` не настроен | Отключите `keep_latest` в Admin Area; настройте `expire_in`; см. **[Артефакты в GitLab CI](../Advanced/gitlab_ci_caching/gitlab_ci_artifacts.md)** |
| Низкий cache hit rate (<50%) | Слишком специфичные ключи или частое удаление кэша | Используйте `cache:key:files`; см. **[Лучшие практики кэширования](../Advanced/gitlab_ci_caching/cache_best_practices.md)** |
| `413 Request Entity Too Large` | Размер артефакта превышает лимит | Увеличьте `ci_max_artifact_size` в Admin Area или используйте `exclude`; см. **[Артефакты в GitLab CI](../Advanced/gitlab_ci_caching/gitlab_ci_artifacts.md)** |
| Очереди задач | `concurrent` слишком мал или Runner'ы недоступны | Увеличьте `concurrent` или добавьте Runner'ы; проверьте теги; см. **[Управление парком Runner'ов](../Advanced/runner_fleet_management.md)** |
| Медленный пайплайн | Отсутствует DAG, нет кэширования, тяжёлые образы | Включите `needs`; кэшируйте зависимости; используйте multi-stage builds; см. **[Оптимизация производительности пайплайнов](../Advanced/pipeline_performance_optimization.md)** |
| Артефакты не удаляются по `expire_in` | Активна опция `keep_latest` | Отключите "Keep artifacts from most recent successful jobs" |
| Утечка диска на Runner'е | `clean_policy` не настроен, старые контейнеры/образы | Настройте `clean_policy = "always"` и `clean_period = "24h"` в `config.toml` |
| Высокий трафик Registry | Повторная отправка одинаковых образов | Используйте `cache:from:latest` или `--cache-from` для Docker build |

## Ограничения и крайние случаи (Edge Cases)

1. **`keep_latest` игнорирует `expire_in`**: Артефакты последнего успешного пайплайна в ветке сохраняются независимо от срока хранения. Для проектов с ограниченным хранилищем отключайте `keep_latest` на group/project уровне (Premium+).

2. **Dotenv-переменные и матричные сборки**: Переменные из `reports: dotenv` недоступны в блоке `rules` и не работают между инстансами `parallel:matrix`. Для передачи данных между матричными задачами используйте файловые артефакты или API.

3. **Артефакты при `extends`**: Блок `artifacts` при `extends` перезаписывается целиком, а не сливается. Если дочерняя задача переопределяет только `paths`, остальные параметры (`expire_in`, `when`, `reports`) будут утеряны.

4. **Артефакты >1 GB**: Требуют увеличения `proxy_read_timeout` и `client_max_body_size` на обратном прокси (Nginx/Apache). Для артефактов >5 GB используйте внешний Object Storage и загрузку через API.

5. **`interruptible` и артефакты**: При отмене пайплайна через `auto_cancel` артефакты **не сохраняются**, даже при `when: always`. Для критичных задач используйте `interruptible: false`.

6. **Multi-project артефакты**: Для `needs:project` требуется настройка Zero Trust Allowlist (GitLab 17.0+). Без неё возвращается `403 Forbidden`.

7. **Закон Муи (Mooi's Law)**: Время, сэкономленное на ускорении пайплайна, часто reinvested в дополнительные проверки. Это нормальное явление; цель — не минимизировать время любой ценой, а оптимизировать bottleneck'ы с наибольшим влиянием на cost.

## Валидация

Проверка корректности настроек cost optimization:

```bash
# 1. Проверка лимитов артефактов
curl --header "PRIVATE-TOKEN: $TOKEN" \
  "https://gitlab.example.com/api/v4/application/settings" | \
  jq '.artifacts_size_limit, .ci_max_artifact_size, .keep_latest_artifact'

# 2. Проверка размера артефактов проекта
curl --header "PRIVATE-TOKEN: $TOKEN" \
  "https://gitlab.example.com/api/v4/projects/$PROJECT_ID" | \
  jq '.statistics.build_artifacts_size'

# 3. Проверка утилизации Runner'ов
curl --header "PRIVATE-TOKEN: $TOKEN" \
  "https://gitlab.example.com/api/v4/runners?per_page=100" | \
  jq '[.[] | select(.active == true)] | length'

# 4. Мониторинг метрик GitLab Prometheus
curl -s "http://gitlab.example.com/-/metrics" | grep gitlab_ci_artifact
curl -s "http://gitlab.example.com/-/metrics" | grep gitlab_runner_jobs_running_total
```

## Рекомендации (Best Practices)

**Инфраструктура:**
- Right-sizing Runner'ов под профиль нагрузки (CPU/RAM по потребностям, а не по максимуму)
- Настройка `concurrent` и `limit` в `config.toml` на основе доступных ресурсов хоста
- Использование ephemeral runners для изоляции и предотвращения утечек состояния
- Регулярный аудит активных Runner'ов; деактивация неиспользуемых

**Хранилище:**
- `expire_in` для всех артефактов без исключения
- Отключение `keep_latest` для проектов с ограниченным хранилищем
- Lifecycle Policies для Object Storage (MinIO/Ceph RGW)
- Использование Package Registry для крупных бинарников вместо CI artifacts
- Разделение временных и релизных артефактов

**Пайплайны:**
- DAG (`needs`) вместо последовательных стадий для сокращения времени и потребления
- Кэширование зависимостей, артефакты — только для результатов сборки
- `pull_policy: ["if-not-present"]` для сокращения трафика
- Conditional jobs (`rules:changes`) для пропуска ненужных задач
- Параллелизация тестов через `parallel:matrix`

**Мониторинг:**
- Отслеживание cache hit rate (цель >80%)
- Мониторинг дискового пространства Runner'ов (`<80%`)
- Алерты на рост `build_artifacts_size` проекта
- Регулярный анализ утилизации Runner'ов

## Дополнительная информация

### Связанные темы

- **[Артефакты в GitLab CI](../Advanced/gitlab_ci_caching/gitlab_ci_artifacts.md)** — SSoT для retention, `keep_latest`, лимитов и cleanup артефактов
- **[Управление парком Runner'ов](../Advanced/runner_fleet_management.md)** — SSoT для Fleet Management, auto-scaling, `config.toml`
- **[Оптимизация производительности пайплайнов](../Advanced/pipeline_performance_optimization.md)** — SSoT для DAG, кэширования, параллелизма
- **[Лучшие практики кэширования](../Advanced/gitlab_ci_caching/cache_best_practices.md)** — SSoT для cache hit rate, ключей, стратегий
- **[Мониторинг и метрики](../Advanced/monitoring_and_metrics.md)** — метрики Runner'ов и пайплайнов
- **[Управление артефактами](../../artifact_management.md)** — общие концепции SBOM, retention, аттестаций

### Чек-лист оптимизации

**Инфраструктура:**
- [ ] Проведен аудит текущих расходов на CI/CD
- [ ] Определены неиспользуемые Runner'ы
- [ ] Настроены `concurrent` и `limit` в `config.toml`
- [ ] Настроена автоматическая очистка Docker (`clean_policy`)
- [ ] Настроен `pull_policy: ["if-not-present"]`

**Хранилище:**
- [ ] Настроен `expire_in` для всех артефактов
- [ ] Проверен параметр `keep_latest`
- [ ] Настроены Lifecycle Policies для Object Storage
- [ ] Крупные бинарники вынесены в Package Registry
- [ ] Регулярно проводится анализ `build_artifacts_size`

**Пайплайны:**
- [ ] Используется DAG (`needs`) вместо последовательных стадий
- [ ] Зависимости кэшируются, не передаются через артефакты
- [ ] Настроен cache hit rate >80%
- [ ] Используются conditional jobs (`rules:changes`)
- [ ] Применяются multi-stage Docker builds

**Мониторинг:**
- [ ] Настроены метрики утилизации Runner'ов
- [ ] Мониторится дисковое пространство
- [ ] Настроены алерты на рост артефактов
- [ ] Регулярно проводится анализ slow jobs
