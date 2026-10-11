# Capacity Planning для CI/CD

**Актуально для:** self-hosted CI/CD (GitLab CI, GitHub Actions, Jenkins) 2024–2026

> Область применения: практики DevOps, SRE и SysAdmin при эксплуатации самостоятельно развёрнутых систем. Материалы, относящиеся к публичным облакам и технологиям искусственного интеллекта, не рассматриваются.

> **Примечание:** Общая теория Capacity Planning, Закон Литтла и USE-методология описаны в **[Capacity Planning (общий)](../../Concepts/capacity-planning.md)**. Детальный расчёт для GitLab — в **[Capacity Planning для GitLab CI/CD](../GitLab_CI/Advanced/gitlab_capacity_planning.md)**. Управление парком раннеров — в **[Управление парком раннеров](./runner-fleet-management.md)**. Данный файл связывает эти дисциплины в контексте CI/CD.

## Определения

- **Capacity Planning в CI/CD** — процесс прогнозирования требуемых ресурсов для инфраструктуры пайплайнов: раннеров, CI-серверов, реестров артефактов и вспомогательных сервисов. Цель — поддерживать Queue Time в пределах SLO при разумной стоимости.
- **Queue Time (Время в очереди)** — время, которое job проводит в очереди перед началом выполнения на runner'е. Рост Queue Time при стабильной нагрузке — первый сигнал нехватки capacity.
- **Runner Density (Плотность раннеров)** — количество параллельных jobs на один runner-узел. Определяется через bin-packing по требованиям job'ов.
- **Headroom (Запас)** — разница между текущей нагрузкой и максимальной capacity, выраженная в процентах. Обычно 20–30% для CI/CD инфраструктуры.
- **CI Load Profile (Профиль нагрузки CI)** — распределение job по длительности, частоте запусков и параллельности. Определяет требуемую конфигурацию флота.
- **Saturation (Насыщение)** — состояние, при котором добавление дополнительной нагрузки приводит к деградации производительности (рост Queue Time, OOM, ошибки запуска).
- **Ephemeral Runner (Эфемерный раннер)** — runner, создаваемый под задачу и автоматически удаляемый после выполнения. Позволяет гибко масштабировать capacity.
- **Warm Pool (Группа подогретых инстансов)** — пул заранее запущенных раннеров, готовых принять job без cold start.
- **Cold Start (Холодный старт)** — задержка при первом запуске runner'а или загрузке образа. В 2026 году median cold-start queue time на hosted runners без warm pool составляет ~38 секунд; warm pool сокращает это значение на ~90%.
- **Little's Law для CI/CD** — связь между параллельными jobs (L), скоростью запуска (λ) и средним временем выполнения (W): `L = λ × W`. Применяется для расчёта необходимого количества слотов.
- **Kingman's Formula (Формула Кингмана)** — аппроксимация времени ожидания в очереди: `Wq ≈ (Ca² + Cs²) / 2 × ρ / (1 - ρ) × Ws`, где Ca — коэффициент вариации arrivals, Cs — coefficient of variation service time, ρ — утилизация, Ws — среднее время обслуживания. Показывает экспоненциальный рост Queue Time при подходе утилизации к 100%.
- **USE-методология для CI/CD** — мониторинг по трём осям: Utilization (утилизация CPU/RAM/диска runner'а), Saturation (очередь jobs, длина очереди), Errors (OOMKill, No space, таймауты).
- **Bin-packing** — стратегия размещения нескольких параллельных jobs на один узел так, чтобы минимизировать неиспользуемые остатки CPU/RAM.
- **Fair Share (Справедливое распределение)** — ограничение максимального количества параллельных слотов на одного пользователя/проект, чтобы один тяжёлый пайплайн не заблокировал весь флот.

## Основные концепции

### Теоретические основы для CI/CD

#### Закон Литтла

Фундаментальный закон теории очередей, применяемый к расчёту runner capacity:

```
Concurrency (L) = Arrival Rate (λ) × Average Job Duration (W)
```

**Пример:** Если команда запускает 20 пайплайнов в час со средним временем 10 минут, требуется `20 × (10/60) ≈ 3.3` одновременных слота. С headroom 25% — 5 слотов.

#### Формула Кингмана

Показывает, почему планирование на 100% утилизации опасно для CI/CD:

- **80% утилизации:** время ожидания в 4 раза больше, чем при 0%
- **90% утилизации:** в 9 раз больше
- **99% утилизации:** в 99 раз больше

**Вывод:** Для CI/CD с SLO на Queue Time < 2 мин утилизация не должна превышать 70–80%.

#### USE-методология

Для каждого компонента CI/CD Infrastructure:

| Ось | Что измерять | CI/CD пример |
|:---|:---|:---|
| **Utilization** | % времени, когда ресурс занят | CPU usage runner'а, disk usage registry |
| **Saturation** | Очередь к ресурсу | Длина очереди jobs, pending jobs |
| **Errors** | Ошибки ресурса | OOMKill, No space left, runner offline |

### Зачем CI/CD нужно Capacity Planning

CI/CD инфраструктура имеет специфические паттерны нагрузки:

- **Всплески по расписанию:** утренний коммит-шторм, запуск пайплайнов после merge в main.
- **Неравномерность job:** сборка монолита (15–30 мин) vs линтер (10 сек). Heavy job может заблокировать очередь.
- **Рост команд:** каждое новое команда увеличивает параллельные job, но эффективность bin-packing падает при фрагментации.
- **Cost pressure:** переплата за idle capacity vs задержки разработчиков из-за очередей.

Цель Capacity Planning в CI/CD — найти баланс между:
- **Временем фидбека** (Queue Time < N минут)
- **Стоимостью инфраструктуры** (оптимальный размер узлов, использование прерываемых инстансов)
- **Надёжностью** (headroom для пиков, graceful degradation при перегрузке)

### CI Load Profile: паттерны нагрузки

Понимание профиля нагрузки — основа для расчёта capacity:

| Паттерн | Описание | Влияние на capacity |
|:---|:---|:---|
| **Commit Storm** | Волна коммитов утром/после ланча | Пиковая параллельность, требует warm pool |
| **Merge Wave** | Массовый merge в main после ревью | Всплеск длинных пайплайнов |
| **Nightly Batch** | Ежедневные полные сборки/тесты в ночное время | Планируйте в off-peak, используйте dedicated узлы |
| **Release Burst** | Множественные релизы одновременно | Требует burst capacity 50–100% |
| **Flaky Retry Storm** | Каскадные перезапуски упавших jobs | Временное увеличение очереди, мониторьте retry rate |

### Компоненты CI/CD, требующие планирования

| Компонент | Метрики | Зависимости |
|:---|:---|:---|
| **CI-сервер** | CPU, RAM, Disk IOPS, Network | Количество users, pipelines, артефактов |
| **Раннеры** | CPU, RAM, concurrent jobs, Queue Time | Типы job, параллельность, размер команды |
| **Реестр артефактов** | Disk, Network, IOPS | Объём образов, частота pushes/pulls |
| **Служба секретов** | RAM, Network, IOPS | Количество concurrent requests, TTL токенов |
| **Хранилище артефактов** | Disk, Network, IOPS | Объём артефактов, retention политика |
| **База данных CI** | CPU, RAM, Disk IOPS, Connections | Количество users, pipelines, retention логов |
| **Кэш / CDN** | RAM, Network, Hit Ratio | Размер зависимостей, количество miss |

### Формулы расчёта

#### Runner capacity

```
Total Concurrent Slots = Σ (Runner Capacity per executor)
Runner Capacity per executor = (Runner CPU / Job CPU requirement) × (Runner RAM / Job RAM requirement)
Effective Capacity = Total Concurrent Slots × (1 - Headroom)
Peak Slots ≈ (avg_parallel_jobs_peak × avg_job_duration_sec) / acceptable_queue_time_sec × headroom
```

#### Registry / Storage

```
Storage Growth = (artifact_size × pushes_per_day × retention_days) + (logs_size × pipelines_per_day × retention_days)
```

### Стратегии масштабирования

| Стратегия | Описание | Где применять |
|:---|:---|:---|
| **Reactive Scaling** | Масштабирование по факту появления job в очереди | GitLab Runner Kubernetes executor |
| **Predictive Scaling** | Подготовка мощностей к пикам (утренний шторм, понедельник) | Persistent runners, Warm Pools |
| **KEDA** | Event-driven scaling на основе очереди GitLab/GitHub | Kubernetes-based runner fleet |
| **Bin-packing** | Упаковка job на узлы с учётом их требований | Все типы раннеров |
| **Tiered runners** | Выделенные узлы для heavy job, общие — для легких | Оркестраторы (K8s, Docker) |

### Метрики для мониторинга

| Метрика | Инструмент | Порог для алерта |
|:---|:---|:---|
| **Queue Time** | Prometheus (`gitlab_runner_job_queue_duration_seconds`) | p95 > 5 мин |
| **Runner Saturation** | Prometheus (`gitlab_runner_job_total` / concurrent) | > 80% |
| **Job Duration trends** | CI built-in analytics | Рост > 20% WoW |
| **Failed jobs (capacity-related)** | CI logs, OOMKill, No space | > 5% от всех failures |
| **Disk usage** | node_exporter, cAdvisor | > 80% на runner'ах и registry |
| **Registry push/pull latency** | Registry metrics | p95 > 2 сек |
| **Warm Pool hit rate** | Custom metric | < 70% — пересмотреть размер пула |

## Практические сценарии

### Сценарий 1: Расчёт runner fleet для команды из 50 инженеров

#### Предпосылки
- 50 инженеров, среднее 3 commit/день на человека.
- Средняя длительность job: 8 мин (build+test).
- Пиковая параллельность: 30 simultaneous jobs.
- Размер job: 2 CPU / 4 GiB RAM.

#### Расчёт

```
Peak Slots = (30 jobs × 480 sec) / 300 sec acceptable queue × 1.25 headroom = 60 slots
Runner nodes (16 CPU / 32 GiB): 60 / 7 jobs per node = 9 nodes
```

#### Валидация
- Queue Time p95 < 2 мин при пиковой нагрузке.
- Утилизация узлов 65–75% (с запасом).
- Возможность absorption всплесков (понедельник, релиз) без добавления узлов.

#### Устранение неполадок
- **Queue Time растёт:** добавить 1–2 узла или вынести heavy job на выделенные раннеры.
- **OOM на runner'ах:** пересмотреть bin-packing; возможно, job требует больше RAM, чем планировалось.
- **Disk full:** настроить `docker system prune` или использовать ephemeral runners.

---

### Сценарий 2: Registry capacity planning

#### Предпосылки
- 200 pushes/день, средний размер образа 800 MB.
- Retention: 30 дней.

#### Расчёт

```
Daily Growth = 200 pushes × 800 MB = 160 GB/day
30-day Storage = 160 GB × 30 = 4.8 TB
+ overhead (blobs, manifests) = ~6 TB
```

#### Рекомендации
- Реестр на SSD с IOPS > 3000.
- Алерт на 70% заполнения.
- Сжатие (zstd) и replication policy для экономии места.

---

### Сценарий 3: Capacity Planning при росте команды

#### Предпосылки
- Команда вырастет с 50 до 100 инженеров за 6 месяцев.
- Текущая инфраструктура: 9 runner-узлов.

#### Прогноз
- Пиковая параллельность: 60 simultaneous jobs.
- Peak Slots = 120 slots (с headroom 1.25).
- Runner nodes: 120 / 7 = 18 узлов.

#### План масштабирования
- Месяц 1–2: добавить 4 узла (итого 13).
- Месяц 3–4: добавить ещё 4 узла (итого 17).
- Месяц 5–6: добавить 1–2 узла для headroom.

#### Валидация
- Queue Time остаётся < 2 мин.
- Утилизация узлов 60–70%.
- Cost increase оправдан ростом throughput.

---

### Сценарий 4: Warm Pool для сокращения cold-start Queue Time

#### Предпосылки
- Пиковые нагрузки утром (09:00–10:00) создают очередь из-за cold start.
- Средний cold-start без warm pool: 38 сек (Latchkey 2026).
- Цель: Queue Time p95 < 10 сек для latency-sensitive jobs.

#### Решение
- Настроить warm pool из 5–10 готовых runner'ов.
- Для Kubernetes-based флота: `minReplicaCount` в KEDA ScaledObject.
- Для Docker-autoscaler: `idle_count = 5`, `idle_time = "5m"`.

#### Валидация
- Queue Time p95 сокращается с 38 сек до < 5 сек.
- Cold-start jobs в warm pool: 0.
- Увеличение idle cost на 10–15% окупается сокращением developer wait time.

---

### Сценарий 5: KEDA-based автоскейлинг для GitLab CI

#### Предпосылки
- Runner fleet на Kubernetes, GitLab self-hosted.
- Пиковая нагрузка непредсказуема, нужен реактивный scaling.

#### Конфигурация

```yaml
apiVersion: keda.sh/v1alpha1
kind: ScaledObject
metadata:
  name: gitlab-runner-scaler
  namespace: gitlab
spec:
  scaleTargetRef:
    name: gitlab-runner
    kind: Deployment
  minReplicaCount: 2
  maxReplicaCount: 50
  cooldownPeriod: 300
  pollingInterval: 30
  triggers:
    - type: prometheus
      metadata:
        serverAddress: http://prometheus-server.monitoring.svc.cluster.local
        metricName: gitlab_runner_jobs_queued_total
        threshold: "10"
        query: sum(gitlab_runner_jobs_queued_total{runner="gitlab-runner"})
```

#### Валидация
- При росте очереди до 10 jobs — запускаются новые раннеры.
- При спаде — через 5 мин (cooldown) начинается scale-down.
- Queue Time остаётся < 2 мин при пиках.

---

### Сценарий 6: Change Detection и affected-анализ для capacity planning

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

#### Валидация
- При изменении одного модуля запускается только его сборка.
- При изменении shared-библиотеки — сборка всех зависимых модулей.
- Общая нагрузка на флот сокращается на 60–90%.

---

### Сценарий 7: Мониторинг и алертинг capacity (Prometheus)

#### Prometheus recording rules

```yaml
groups:
  - name: gitlab_capacity
    interval: 5m
    rules:
      - record: gitlab:runner:concurrent:usage:ratio
        expr: sum(gitlab_runner_jobs_running_total) / sum(gitlab_runner_concurrent_total)

      - record: gitlab:pipeline:queue:duration:p95
        expr: histogram_quantile(0.95, sum(rate(gitlab_ci_pipeline_duration_seconds_bucket[5m])) by (le))

      - record: gitlab:sidekiq:queue:size:total
        expr: sum(gitlab_sidekiq_queue_size_total)

      - record: gitlab:disk:usage:ratio
        expr: sum(gitlab_storage_disk_bytes_used) / sum(gitlab_storage_disk_bytes_total)

      - record: gitlab:postgres:connections:usage:ratio
        expr: sum(gitlab_postgres_connections_active) / sum(gitlab_postgres_connections_max)
```

#### Алерты

```yaml
      - alert: GitLabRunnerSaturationHigh
        expr: gitlab:runner:concurrent:usage:ratio > 0.8
        for: 10m
        labels:
          severity: warning
        annotations:
          summary: "GitLab Runner saturation > 80%"
          description: "Runner utilization is {{ $value }}"

      - alert: GitLabPipelineQueueTimeHigh
        expr: gitlab:pipeline:queue:duration:p95 > 300
        for: 10m
        labels:
          severity: warning
        annotations:
          summary: "Pipeline queue time p95 > 5min"
          description: "Queue time p95 is {{ $value }}s"
```

#### Валидация
- Алерт срабатывает при saturation > 80% в течение 10 мин.
- Queue Time p95 > 5 мин вызывает предупреждение.
- Диск usage > 80% — алерт warning.

---

## Операции и команды

### Оценка capacity runner'ов

```bash
# Расчёт пиковых слотов
PEAK_JOBS=30
JOB_DURATION_SEC=480
ACCEPTABLE_QUEUE_SEC=300
HEADROOM=1.25

PEAK_SLOTS=$(( (PEAK_JOBS * JOB_DURATION_SEC) / ACCEPTABLE_QUEUE_SEC * HEADROOM ))
echo "Peak Slots: $PEAK_SLOTS"
# → Peak Slots: 60

# Расчёт количества узлов (16 CPU / 32 GiB, job требует 2 CPU / 4 GiB)
JOBS_PER_NODE=7
NODES=$(( PEAK_SLOTS / JOBS_PER_NODE ))
echo "Runner nodes needed: $NODES"
# → Runner nodes needed: 9
```

### Проверка утилизации runner'ов

```bash
# Через GitLab API
curl -s "http://gitlab.example.com/api/v4/runners" | jq '.[] | {id, description, active: .active, status: .status}'

# Длина очереди
curl -s "http://gitlab.example.com/api/v4/projects/:id/jobs" | jq '.[] | {id, status, created_at}'
```

### Мониторинг storage

```bash
# Использование диска
df -h /var/opt/gitlab
du -sh /var/opt/gitlab/*

# Прогноз роста storage
DAILY_GROWTH_GB=160
RETENTION_DAYS=30
TOTAL_STORAGE=$(( DAILY_GROWTH_GB * RETENTION_DAYS ))
echo "Storage needed: ${TOTAL_STORAGE}GB + overhead"
# → Storage needed: 4800GB + overhead
```

### Проверка PostgreSQL connections

```bash
sudo gitlab-psql -c "SELECT count(*) FROM pg_stat_activity WHERE datname = 'gitlabhq_production';"
```

## Устранение неполадок

| Симптом | Причина | Решение |
|:---|:---|:---|
| **Queue Time растёт** | Недостаточно runner'ов или wrong tags | Добавить узлы, проверить matching runner'ов |
| **Runner Saturation > 80%** | Пиковая нагрузка, недостаточная capacity | Масштабировать флот, включить warm pool |
| **OOM на runner'ах** | Перегруженный bin-packing | Увеличить RAM на узлах, вынести heavy job |
| **Cold start > 60 сек** | Тяжёлый golden image, холодный кэш | Оптимизировать образ, включить warm pool |
| **Disk full** | Нет retention policies | Настроить GC, cleanup артефактов, расширить storage |
| **Registry GC не успевает** | Слишком частые pushes | Увеличить частоту GC, оптимизировать image layers |
| **Jobs зависают в pending** | Автокейлер не работает | Проверить health autoscaler, minReplicaCount |
| **No space left on device** | Логи/кэш/артефакты заполнили диск | `docker system prune`, ограничить retention |
| **Cache poisoning** | Общий кэш между проектами | Изолировать кэш по namespace/project |

## Валидация

- **Queue Time baseline:** после настройки runner'ов запустите пиковую нагрузку (10–15 min burst) и измерьте p95 Queue Time. Должен быть < 2 мин для Tier-1 jobs.
- **Runner Saturation:** мониторьте `gitlab_runner_concurrent_usage_ratio`. При > 80% в течение 10 мин — план масштабирования.
- **Storage growth:** измерьте daily growth за 1 неделю и спрогнозируйте на 30/90 дней. Алерт на 70% заполнения.
- **Warm Pool effectiveness:** сравните Queue Time с warm pool и без (отключите minReplicaCount на 1 час). Разница должна быть > 80%.
- **Affected detection accuracy:** запустите change detection на Known Changes и убедитесь, что список affected-модулей совпадает с реальными изменениями.
- **Reproducibility:** фиксируйте версии инструментов (Bazel, Nx, Gradle, Node.js) в CI-образах. Расхождение версий ломает reproducible builds и увеличивает Queue Time.

## Ограничения и крайние случаи

- **Cold start эфемерных раннеров:** Загрузка ОС/образа добавляет латентность. Для latency-чувствительных пайплайнов — warm pools или постоянные раннеры.
- **Large monorepos (>100k files):** Affected-анализ может занимать значительное время. Требуется выделенный сервер для remote caching и execution.
- **Force-push в main:** Affected-анализ относительно `origin/main` даёт корректный результат только при линейной истории. При force-push используйте merge-base.
- **Mixed ecosystems:** Монорепозиторий с Java + JS + Go требует универсального инструмента (Bazel, Pants) или отдельных конфигураций для каждого языка.
- **Lock-файл дрейф:** Частые обновления lock-файлов инвалидируют remote cache. Используйте отдельный lock-файл для CI или отключайте автоматические обновления.
- **Эпизодические всплески:** Раз в квартал/полгода могут возникать всплески, нарушающие baseline. Используйте burst capacity, а не постоянный overprovisioning.
- **Multi-tenancy и честность:** Общий флот между командами требует Fair Share политик, иначе одна команда может monopolise capacity.
- **Headroom для failure domain:** При потере одного узла (N+1) оставшейся capacity должно хватать. Учитывайте это при bin-packing.

## Лучшие практики

### GitHub Actions: специфика capacity planning

Для GitHub Actions capacity планирование отличается от GitLab CI из-за ограничений платформы и модели runner'ов.

**Ограничения платформы (2026):**
- **Максимум 50 workflow'ов на один запуск** (с ноября 2025).
- **Глубина вложенности reusable workflows** — до 10 уровней.
- **Квота кэша** — 10 ГБ по умолчанию на репозиторий (до 10 ТБ с оплатой).
- **Артефакты** — 500 МБ на артефакт, общий лимит зависит от плана.
- **Минуты** — 2000 минут/мес для публичных репозиториев (Free).
- **Параллельные шаги** — с июня 2026 года (ключевые слова `background`, `wait`, `wait-all`, `cancel`, `parallel`).
- **`queue: max` в concurrency-группах** — с мая 2026 года.

**Расчёт capacity для GitHub Actions:**
```
Concurrency (L) = Arrival Rate (λ) × Average Job Duration (W)
```

**Пример:** Если команда запускает 30 workflow'ов в час со средним временем 8 минут:
- `30 × (8/60) = 4` одновременных слота.
- С headroom 25% — 5 слотов.

**Hosted vs Self-hosted:**
| Параметр | Hosted | Self-hosted |
|---|---|---|
| Стоимость | $0.008/мин (Linux), $0.08/мин (macOS) | Амортизация + электроэнергия |
| Cold Start | ~38 секунд (median 2026) | Зависит от образа |
| Контроль | Ограничен | Полный |
| Идеален для | Публичные репо, мелкие задачи | Приватные репо, тяжёлые задачи, внутренние сети |

**Мониторинг capacity:**
- **Queue Time** — разница между `created_at` и `started_at` в ответе Workflow Runs API.
- **Runner Saturation** — для self-hosted: метрики ARC или prometheus-экспортер.
- **Workflow Duration** — p95 из `gh run list --json duration`.
- **Concurrency** — `gh run list --json databaseId` + подсчёт одновременных runs.

**Сценарий: масштабирование self-hosted runner'ов через ARC:**
ARC (actions-runner-controller) масштабирует эфемерные runner-поды по числу назначенных job'ов: listener long-poll'ит GitHub Actions Service и патчит EphemeralRunnerSet с нужным числом реплик. Целевое число раннеров = `minRunners` + назначенные job'ы. Детальная настройка (Helm-чарты `gha-runner-scale-set-controller` / `gha-runner-scale-set`, GitHub App auth, containerMode) — в **[Actions Runner Controller](../../Github_CI/actions_runner_controller.md)**. Прежние CRD-режимы (`RunnerDeployment`, API `actions.summerwind.net/v1alpha1`) — legacy, поддержка только сообществом.

**KEDA для autoscaling:**
```yaml
apiVersion: keda.sh/v1alpha1
kind: ScaledObject
metadata:
  name: github-runner-scaler
spec:
  scaleTargetRef:
    name: runner-deployment
  triggers:
  - type: github-actions
    metadata:
      repository: org/repo
      workflow: build
      metricName: github_actions_jobs_queued_total
```

**Валидация:**
- Queue Time baseline: пиковая нагрузка 10–15 мин, p95 < 2 мин.
- Runner Saturation: при > 80% в течение 10 мин — план масштабирования.
- Workflow Duration: p95 < 15 мин для Tier-1 jobs.
- Storage: еженедельный учёт growth, алерт на 70% заполнения.

1. **Собирайте baseline 2–4 недели** перед расчётом. Один день нерепрезентативен.
2. **Headroom 20–30%:** CI/CD инфраструктура более чувствительна к пикам, чем production сервисы.
3. **Формула Кингмана — ваш ориентир:** при утилизации > 80% Queue Time растёт экспоненциально. Не стремитесь к 100%.
4. **Little's Law для sanity check:** `Concurrency = Arrival Rate × Avg Duration`. Если расчёт даёт 10 слотов, а у вас 50 — пересмотрите assumptions.
5. **Separate heavy jobs:** интеграционные тесты, сборка монолита — на выделенных узлах (taints).
6. **Ephemeral runners для динамической нагрузки:** холодные старты дешевле, чем простаивающие узлы.
7. **Warm Pools для latency-sensitive jobs:** сокращают Queue Time на 80–90% (Latchkey 2026).
8. **KEDA для реактивного scaling:** event-driven scaling на основе очереди — стандарт 2026 для Kubernetes-based флота.
9. **Monitor trends, not snapshots:** рост Queue Time на 20% WoW важнее текущего значения.
10. **Fair Share политики:** ограничьте параллельные slots на команду/проект.
11. **Cost optimization:** используйте прерываемые инстансы для некритичных job, ARM64 для сборок.
12. **Валидация affected-списка:** перед деплоем запустите dry-run и проверьте, что в списке нет неизменённых приложений.

## Дополнительная информация

### См. также

- **[Capacity Planning (общий)](../../Concepts/capacity-planning.md)** — общая теория, Закон Литтла, USE-методология.
- **[Управление парком раннеров](./runner-fleet-management.md)** — расчёт capacity, bin-packing, стратегии масштабирования.
- **[Capacity Planning для GitLab CI/CD](../GitLab_CI/Advanced/gitlab_capacity_planning.md)** — детальный расчёт для GitLab Omnibus/Helm/Kubernetes.
- **[Оптимизация затрат в CI/CD](./cost-optimization.md)** — FinOps и оптимизация стоимости.
- **[Наблюдаемость пайплайнов](./pipeline_observability.md)** — мониторинг, логирование, трейсинг.
- **[Профилирование производительности CI/CD](./performance_profiling.md)** — CPU, IO, Memory-bound узкие места.
- **[Стратегии развёртывания](../Deployment_Strategies/deployment_health_checks_and_rollback.md)** — capacity requirements для Blue/Green, Canary.
