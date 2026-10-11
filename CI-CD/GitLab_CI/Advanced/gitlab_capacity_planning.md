# Capacity Planning для GitLab CI/CD

**Актуально для:** GitLab 17.x–19.x (Omnibus, Helm)

## Определения

* **Capacity Planning (Планирование мощности)** — процесс прогнозирования требуемых вычислительных ресурсов (CPU, RAM, диск, сеть) для поддержки роста нагрузки без деградации производительности.
* **Concurrency (Параллельность)** — максимальное количество одновременно выполняющихся CI/CD jobs на инстансе или runner'е.
* **Queue Time (Время в очереди)** — время, которое job проводит в очереди перед началом выполнения на runner'е.
* **Job Duration (Длительность job)** — время выполнения CI/CD job от начала до конца.
* **Saturation (Насыщение)** — состояние, при котором добавление дополнительной нагрузки приводит к деградации производительности.
* **Headroom (Запас)** — разница между текущей нагрузкой и максимальной capacity, выраженная в процентах.
* **Right-sizing** — процесс подбора оптимальных размеров ресурсов (CPU, RAM, диск) для workload.
* **CI Load Profile** — характер нагрузки CI/CD инфраструктуры: распределение job по длительности, частота запусков, параллельность.
* **Runner Density** — количество concurrent jobs на один runner-узел.

## Основные концепции

### Жизненный цикл планирования мощности

Capacity Planning для GitLab CI/CD следует циклическому процессу:

1. **Базовое планирование** — оценка начальных ресурсов под существующую нагрузку.
2. **Мониторинг** — сбор метрик производительности всех компонентов.
3. **Анализ трендов** — прогноз роста нагрузки на 3–12 месяцев.
4. **Планирование масштабирования** — определение порогов и стратегий масштабирования.
5. **Валидация** — проверка adequacy capacity после масштабирования.
6. **Пересмотр** — регулярный пересмотр планов при изменении нагрузки.

### Компоненты для планирования

| Компонент | Метрики | Зависимости |
|:---|:---|:---|
| **GitLab Server** | CPU, RAM, Disk IOPS, Network | Количество пользователей, pipelines |
| **PostgreSQL** | CPU, RAM, Disk IOPS, Connections | Объём метаданных, частота pipelines |
| **Valkey/Redis** | RAM, Network | Размер кэша, очередь Sidekiq |
| **Gitaly** | Disk IOPS, Network, CPU | Объём Git-операций, размер репозиториев |
| **Runners** | CPU, RAM, Disk, Network | Количество concurrent jobs, длительность jobs |
| **Registry** | Disk, Network | Объём образов, частота pushes/pulls |
| **Storage (MinIO/Ceph RGW)** | Disk, Network, IOPS | Объём артефактов, LFS, бэкапов |

### Связь с метриками DORA и надёжностью

Анти-паттерны в планировании мощности напрямую влияют на четыре ключевых показателя эффективности поставки (DORA):
- **Deployment Frequency** снижается при отсутствии capacity reserves и ручных действих в пайплайне.
- **Lead Time for Changes** растёт при дублировании YAML и монолитном пайплайне.
- **Mean Time to Recovery (MTTR)** увеличивается при отсутствии автоматического отката, health-гейтов и секретов в логах.
- **Change Failure Rate** повышается при использовании `latest` тегов, пересборке артефактов для разных сред и нестабильных тестах.

### Формулы расчёта

#### Runner capacity

```
Total Concurrent Jobs = Σ (Runner Capacity per executor)
Runner Capacity per executor = (Runner CPU / Job CPU requirement) × (Runner RAM / Job RAM requirement)
Effective Capacity = Total Concurrent Jobs × (1 - Headroom)
```

#### GitLab Server capacity

```
Puma Workers = (Total RAM - Valkey - PostgreSQL) / Puma Worker Memory
Sidekiq Concurrency = (Available CPU × 2) or manual tuning
Max PostgreSQL Connections = (Total RAM × 0.25) / Average Connection Memory
```

#### Storage capacity

```
Git Data Growth = Σ (Repository size × Commit frequency × Users)
Artifact Storage = Σ (Job count × Artifact size × Retention period)
Registry Storage = Σ (Image count × Image size × Layer duplication factor)
Backup Storage = Git Data + Artifacts + DB × Retention period
```

## Практические сценарии

### Сценарий 1: Оценка начальной capacity (Greenfield)

```bash
# Шаг 1: Определение профиля нагрузки
# - Количество пользователей: 500
# - Количество проектов: 100
# - Частота pipelines в день: 200
# - Средняя длительность job: 5 минут
# - Средний размер артефакта: 500 MB

# Шаг 2: Расчёт runner capacity
# Concurrent jobs per day: 200 jobs × 5 min = 1000 job-minutes
# Peak concurrency ( working hours 8h): 200 jobs / 8h = 25 jobs/hour
# With 20% headroom: 25 × 1.2 = 30 concurrent jobs

# Шаг 3: Расчёт runner infrastructure
# Docker executor: 2 CPU + 4 GB RAM per job
# Total CPU: 30 jobs × 2 CPU = 60 vCPU
# Total RAM: 30 jobs × 4 GB = 120 GB
# Recommended: 15 runner nodes × 4 CPU × 8 GB (2 jobs per node)

# Шаг 4: Расчёт GitLab Server
# Users < 1000: Single Node
# CPU: 8 vCPU
# RAM: 32 GB
# Disk: 500 GB NVMe (Gitaly), 200 GB SSD (PostgreSQL)

# Шаг 5: Расчёт storage
# Git Data: 100 projects × 1 GB × 3 months = 300 GB
# Artifacts: 200 jobs/day × 500 MB × 30 days = 3 TB
# Registry: 50 images × 2 GB × 10% duplication = 100 GB
# Total: ~3.5 TB + 20% growth = 4.2 TB
```

### Сценарий 2: Мониторинг и анализ трендов

```yaml
# Prometheus recording rules для capacity planning

groups:
  - name: gitlab_capacity
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

# Alerts
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

### Сценарий 3: Масштабирование runner'ов

```yaml
# Horizontal scaling через Docker Machine / Fleeting

# GitLab Runner config.toml
concurrent = 50
check_interval = 0

[[runners]]
  name = "gitlab-runner"
  url = "https://gitlab.example.com/"
  token = "TOKEN"
  executor = "docker"
  [runners.docker]
    cpu_limit = "2"
    memory_limit = "4Gi"
    cpu_request = "1"
    memory_request = "2Gi"
    helper_image = "gitlab/gitlab-runner-helper:latest"

# Для Kubernetes executor'ов — масштабирование через HPA на основе очереди jobs
# См. SSoT: [Управление парком Runner'ов](./runner_fleet_management.md)
```

### Сценарий 4: Масштабирование PostgreSQL

```ruby
# /etc/gitlab/gitlab.rb

# Single Node (users < 1000)
postgresql['shared_buffers'] = "4GB"
postgresql['work_mem'] = "16MB"
postgresql['maintenance_work_mem'] = "512MB"
postgresql['max_connections'] = 200

# Distributed (users 1000-5000)
postgresql['shared_buffers'] = "8GB"
postgresql['work_mem'] = "32MB"
postgresql['maintenance_work_mem'] = "1GB"
postgresql['max_connections'] = 300

# HA (users > 5000) - External PostgreSQL
postgresql['enable'] = false
gitlab_rails['db_adapter'] = 'postgresql'
gitlab_rails['db_host'] = 'postgresql-ha.internal'
gitlab_rails['db_port'] = 5432
gitlab_rails['db_database'] = 'gitlabhq_production'
gitlab_rails['db_pool'] = 100

# Connection pooling (PgBouncer)
postgresql['pgbouncer_enable'] = true
postgresql['pgbouncer_port'] = 6432
postgresql['pgbouncer_pool_mode'] = 'transaction'
postgresql['pgbouncer_max_client_conn'] = 1000
postgresql['pgbouncer_default_pool_size'] = 50
```

### Сценарий 5: Планирование storage

```bash
# Мониторинг использования storage
df -h /var/opt/gitlab
du -sh /var/opt/gitlab/*

# Расчёт роста storage
# Git Data: ~100 MB per user
# Artifacts: ~10 GB per active user per month
# Registry: ~5 GB per project per month
# Backups: ~2× current data size

# Рекомендации
# - Git Data: NVMe SSD, 500+ GB
# - PostgreSQL: NVMe SSD, 200+ GB
# - Artifacts: S3-совместимое object storage (MinIO, Ceph RGW)
# - Registry: S3-совместимое object storage
# - Backups: Separate storage with retention policy

# MinIO/Ceph RGW config (self-hosted, S3-совместимое)
# /etc/gitlab/gitlab.rb
gitlab_rails['object_store_enabled'] = true
gitlab_rails['object_store_connection'] = {
  'provider' => 'MinIO',
  'endpoint' => 'https://minio.internal.example.com',
  'access_key_id' => 'minio_access_key',
  'secret_access_key' => 'minio_secret_key',
  'path_style' => true
}
gitlab_rails['object_store_objects']['artifacts']['bucket'] = 'gitlab-artifacts'
gitlab_rails['object_store_objects']['lfs']['bucket'] = 'gitlab-lfs'
gitlab_rails['object_store_objects']['uploads']['bucket'] = 'gitlab-uploads'
gitlab_rails['object_store_objects']['packages']['bucket'] = 'gitlab-packages'
```

### Сценарий 6: Cost optimization

```yaml
# Оптимизация runner costs (self-hosted)

# 1. Autoscaling runners (Docker Machine / Fleeting)
# См. SSoT: [Управление парком Runner'ов](./runner_fleet_management.md)

# 2. Job-level resource limits
job_name:
  resources:
    limits:
      cpu: "2"
      memory: "4Gi"
    requests:
      cpu: "500m"
      memory: "1Gi"

# 3. Artifact retention policies
job_name:
  artifacts:
    paths:
      - dist/
    expire_in: 1 week
  cache:
    paths:
      - node_modules/
    key: "${CI_COMMIT_REF_SLUG}"
    policy: push
```

## Операции и команды

### Мониторинг capacity

```bash
# Runner utilization
curl -s "http://gitlab.example.com/api/v4/runners" | jq '.[] | {id, description, active: .active, status: .status}'

# Pipeline queue depth
curl -s "http://gitlab.example.com/api/v4/projects/:id/jobs" | jq '.[] | {id, status, created_at}'

# Disk usage
df -h /var/opt/gitlab
du -sh /var/opt/gitlab/*

# PostgreSQL connections
sudo gitlab-psql -c "SELECT count(*) FROM pg_stat_activity WHERE datname = 'gitlabhq_production';"

# Valkey memory
sudo gitlab-redis-cli INFO memory | grep used_memory_human
```

### Прогнозирование

```bash
# Сбор historical данных
# - Pipelines per day: GitLab API → /projects/:id/pipelines
# - Job duration: GitLab API → /projects/:id/jobs/:id
# - Runner utilization: Prometheus → gitlab_runner_jobs_running_total

# Расчёт трендов
python3 -c "
import pandas as pd
import numpy as np

# Historical data
data = pd.DataFrame({
    'date': pd.date_range('2024-01-01', '2024-06-01', freq='D'),
    'pipelines': np.random.normal(200, 20, 152),
    'avg_duration': np.random.normal(300, 30, 152),
    'concurrent': np.random.normal(15, 3, 152)
})

# 3-month growth rate
pipeline_growth = data['pipelines'].iloc[-90:].mean() / data['pipelines'].iloc[:90].mean()
print(f'Pipeline growth: {pipeline_growth:.2%}')

# Projected capacity need
projected_pipelines = 200 * pipeline_growth
projected_concurrent = projected_pipelines * 5 / 480  # 5 min avg, 8h window
print(f'Projected pipelines: {projected_pipelines:.0f}')
print(f'Projected concurrent: {projected_concurrent:.0f}')
"
```

## Устранение неполадок (Troubleshooting)

| Симптом | Вероятная причина | Действие |
|:---|:---|:---|
| Высокий queue time | Недостаточно runner'ов | Масштабируйте runner'ы, проверьте tags |
| Sidekiq queue растёт | Медленная БД или мало воркеров | Увеличьте `max_concurrency`, оптимизируйте БД |
| Gitaly таймауты | Медленный диск | Используйте NVMe SSD с IOPS > 3000 |
| PostgreSQL connection limit | Исчерпан лимит | Увеличьте `max_connections` или используйте PgBouncer |
| Disk full | Недостаточно storage | Масштабируйте storage, настройте retention policies |
| Registry GC не успевает | Слишком частые pushes | Увеличьте частоту GC, оптимизируйте image layers |

## Лучшие практики и очистка (Best Practices & Cleanup)

### Мониторинг

* **Key metrics:** queue time, job duration, runner utilization, PostgreSQL connections, disk usage.
* **Alerting:** настройте алерты на saturation > 80%, queue time > 5min, disk usage > 85%.
* **Dashboard:** создайте дашборд с key capacity metrics для команды.
* **Historical data:** храните метрики минимум 3 месяца для анализа трендов.

### Масштабирование

* **Horizontal first:** предпочитайте горизонтальное масштабирование вертикальному.
* **Right-sizing:** регулярно пересматривайте resource requests/limits для jobs.
* **Ephemeral runners:** используйте эфемерные runner'ы для гибкого масштабирования capacity.
* **Warm pool:** поддерживайте группу подогретых инстансов для сокращения cold start.

### Planning

* **3-month forecast:** пересматривайте capacity plan каждые 3 месяца.
* **Headroom:** поддерживайте 20-30% запаса capacity.
* **Burst capacity:** имейте возможность кратковременно увеличить capacity на 50-100%.
* **Documentation:** документируйте assumptions и формулы для capacity calculations.

### Очистка

* **Artifact retention:** настройте `expire_in` для артефактов.
* **Cache optimization:** используйте cache для зависимостей.
* **Registry cleanup:** настройте cleanup policies для registry.
* **Backup lifecycle:** автоматически удаляйте старые бэкапы.

## Ограничения и крайние случаи

- **Legacy GitLab (<17.0):** `spec:inputs` и `raw: true` для переменных доступны только в GitLab 16.7+; для более старых версий требуется ручное управление иерархией и экранирование.
- **Self-hosted Runner'ы без внешнего доступа:** TLS между Runner и GitLab требует валидного сертификата; в air-gapped средах используется внутренний CA.
- **Монопольные Runner'ы:** на одном Runner'е с overlapping тегами могут выполняться задачи из разных проектов с разными требованиями к изоляции — требуется careful capacity planning.
- **Большие монореpos:** дублирование YAML и монолитный пайплайн проявляются особенно остро из-за размера кодовой базы; инкрементальные сборки и DAG-пайплайны становятся обязательными.
- **Multi-tenancy / shared runners:** secret sprawl и overlapping tags в мультитенантных окружениях могут привести к утечке данных между проектами; namespace-изоляция и scoped политики обязательны.
- **Высокая нагрузка на CI:** при >500 параллельных jobs требуется отдельный кластер Runner'ов с автоскейлингом; отсутствие `timeout` и `interruptible` становится критичным.

## Дополнительная информация

### См. также

* **[Capacity Planning для CI/CD](../../Core_Concepts/capacity_planning.md)** — общая теория, Закон Литтла, USE-методология
* **[Управление парком Runner'ов](./runner_fleet_management.md)** — масштабирование и конфигурация Runner'ов
* **[CI/CD Anti-patterns](../../ci_cd_antipatterns.md)** — общие анти-паттерны CI/CD
* **[CI/CD Cost Optimization](./cicd_cost_optimization.md)** — оптимизация затрат CI/CD
* **[Администрирование GitLab в масштабе](./gitlab_administration_at_scale.md)** — распределённые архитектуры и масштабирование
* **[Мониторинг и метрики GitLab CI/CD](./monitoring_and_metrics.md)** — Prometheus, Grafana, алертинг

### Внешние ресурсы

* [GitLab Reference Architectures](https://docs.gitlab.com/ee/administration/reference_architectures/)
* [GitLab Scalability Guide](https://docs.gitlab.com/ee/administration/scalability/)
* [GitLab Performance Indicators](https://docs.gitlab.com/ee/administration/monitoring/prometheus/gitlab_metrics.html)
