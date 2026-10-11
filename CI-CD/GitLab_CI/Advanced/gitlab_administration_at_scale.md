# Администрирование GitLab в масштабе

**Актуально для:** GitLab 18.0–19.4 (Enterprise / Large Scale)

## Определения

* **Administration at Scale (Администрирование в масштабе)** — управление GitLab инстансом с >2000 пользователей, высокими требованиями к SLA и производительности.
* **Multi-node Architecture** — распределённая архитектура с разнесением компонентов по нескольким серверам.
* **Horizontal Scaling** — масштабирование за счёт добавления серверов (в отличие от вертикального масштабирования).
* **Sharding** — разделение данных между несколькими узлами (пользователи, группы, проекты).
* **Geo Replication** — территориально распределённые read-only зеркала инстанса.
* **Maintenance Window** — запланированный период времени для проведения работ (обновление, миграция).
* **Change Management** — процесс управления изменениями в production-среде.
* **Capacity Ceiling** — максимальная нагрузка, при которой производительность инстанса остаётся в пределах SLA.
* **Topology** — схема размещения компонентов GitLab и связей между ними.

## Архитектура и принцип работы

### Топологии по масштабу

| Пользователей | Архитектура | Компоненты |
|:---|:---|:---|
| < 1000 | Single Node | Omnibus |
| 1000–2000 | Single Node (powered) | Omnibus + выделенный диск |
| 2000–5000 | Distributed | Gitaly + БД на выделенных серверах |
| 5000–10000 | HA Distributed | Rails/Sidekiq в Kubernetes или за балансировщиком, Gitaly + БД на VM |
| > 10000 | Geo + Sharding | Geo-репликация, разделение по группам |

### Компоненты для масштабирования

| Компонент | Тип | Стратегия масштабирования |
|:---|:---|:---|
| **Puma/Rails** | Stateless | Горизонтальное (добавление нод за балансировщиком) |
| **Sidekiq** | Stateless | Горизонтальное (добавление процессов) |
| **Gitaly** | Stateful | Функциональное (вынос на выделенные серверы) |
| **PostgreSQL** | Stateful | Функциональное (HA с Patroni) |
| **Valkey/Redis** | Stateful | Функциональное (вынос на выделенный сервер) |
| **Registry** | Stateful | Функциональное (внешний Registry или вынос) |

### Жизненный цикл запроса в распределённой архитектуре

1. **Внешний запрос** поступает на точку входа (Nginx или hardware/software LB).
2. **LB** распределяет трафик между Rails/Puma-нодами по health check.
3. **Puma** обрабатывает API и веб-интерфейс, delegates тяжелые запросы Workhorse.
4. **Workhorse** проксирует артефакты, Git LFS, репозитории в Gitaly.
5. **Gitaly** выполняет низкоуровневые Git-операции.
6. **Sidekiq** обрабатывает асинхронные фоновые задачи через Valkey.
7. **PostgreSQL** хранит метаданные инстанса.

### Оси масштабирования

GitLab можно масштабировать по трём осям:

1. **Вертикальное масштабирование** — увеличение ресурсов одного сервера (CPU, RAM, диск). Применимо до порога ~2000 пользователей.
2. **Горизонтальное масштабирование** — добавление серверов в пул stateless-компонентов (Puma, Sidekiq). Основной способ масштабирования web-уровня.
3. **Функциональное масштабирование** — вынос отдельных stateful-компонентов на выделенные серверы с HA-кластерами (PostgreSQL, Gitaly, Valkey).

### Точки отказа при масштабировании

При переходе от Single Node к Distributed architecture появляются новые SPOF:

- **Сеть между компонентами** — между LB и Rails, Rails и Gitaly, Rails и БД.
- **Valkey** — при сбое останавливаются Sidekiq, кэш, сессии.
- **PostgreSQL** — при сбое недоступен весь инстанс.
- **Gitaly** — при сбое недоступны Git-операции (clone, push, pull).

Для каждой SPOF требуется HA-конфигурация или план восстановления.

## Предварительные требования

### Роли и зоны ответственности

| Роль | Ответственность |
|:---|:---|
| **Dev** | Использование инстанса, базовое понимание ограничений при масштабировании |
| **DevOps / SRE** | Проектирование топологии, конфигурация gitlab.rb, настройка балансировщика, мониторинг, алертинг, capacity planning, change management |
| **Sysadmin** | Развёртывание железа/VM, сеть, хранилище, ОС, бэкап, disaster recovery, доступ к management plane |

### Аппаратные требования по тирам

| Тир | Пользователей | CPU | RAM | Диск | Сеть |
|:---|:---|:---|:---|:---|:---|
| Distributed | 2000–5000 | 8+ vCPU | 32+ ГБ | 500+ ГБ NVMe | 10 Гбит/с |
| HA Distributed | 5000–10000 | 16+ vCPU | 64+ ГБ | 1+ ТБ NVMe | 10 Гбит/с, низкая задержка |
| Geo + Sharding | > 10000 | 32+ vCPU | 128+ ГБ | 2+ ТБ NVMe | 10 Гбит/с, dedicated VLAN |

### Программные требования

- **ОС:** Linux с systemd (Rocky Linux 9, AlmaLinux 9, Ubuntu 22.04/24.04 LTS)
- **GitLab:** 18.0+ (для Gitaly Cluster с RAFT рекомендуется 17.0+)
- **PostgreSQL:** 15+ (GitLab 18.x), 17+ (GitLab 19.x)
- **Valkey:** 7.2+ (GitLab 19.x) или Redis 7.2+
- **Load Balancer:** Nginx, HAProxy, F5 или cloud-native LB с health check на `/-/readiness`
- **Мониторинг:** Prometheus 2.40+, Alertmanager, Grafana

### Сетевые требования

- Разделение на подсети: management, application, database, storage.
- Порты между компонентами:
  - Rails ↔ PostgreSQL: 5432
  - Rails ↔ Valkey: 6379
  - Rails ↔ Gitaly: 8075
  - LB ↔ Rails: 8080
  - LB ↔ Workhorse: 8181
- Firewall между подсетями; административный доступ только через bastion/VPN.

## Конфигурация

### Схема distributed topology

При переходе к distributed architecture каждая нода отключает встроенные сервисы и подключается к внешним:

```ruby
# /etc/gitlab/gitlab.rb на Rails-нодах

postgresql['enable'] = false
redis['enable'] = false
gitaly['enable'] = false
nginx['enable'] = false

gitlab_rails['db_adapter'] = 'postgresql'
gitlab_rails['db_encoding'] = 'unicode'
gitlab_rails['db_host'] = 'postgresql.internal'
gitlab_rails['db_port'] = 5432
gitlab_rails['db_database'] = 'gitlabhq_production'
gitlab_rails['db_username'] = 'gitlab'
gitlab_rails['db_password'] = 'secure_password'

gitlab_rails['redis_port'] = 6379
gitlab_rails['redis_host'] = 'redis.internal'
gitlab_rails['redis_password'] = 'secure_password'

gitlab_rails['gitaly_address'] = 'tcp://gitaly.internal:8075'
gitlab_rails['gitaly_token'] = 'gitaly_auth_token'
```

### Конфигурация Gitaly на выделенном сервере

```ruby
# /etc/gitlab/gitlab.rb на Gitaly-ноде

postgresql['enable'] = false
redis['enable'] = false
nginx['enable'] = false
puma['enable'] = false
sidekiq['enable'] = false
gitlab_workhorse['enable'] = false
prometheus_monitoring['enable'] = false

gitaly['enable'] = true
gitaly['listen_addr'] = '0.0.0.0:8075'
gitaly['auth_token'] = 'gitaly_auth_token'

gitaly['configuration'] = {
  concurrency: [
    { rpc: "/gitaly.SmartHTTPService/PostReceivePack", max_per_repo: 3 },
    { rpc: "/gitaly.SmartHTTPService/PostUploadPack", max_per_repo: 10 }
  ],
  storage: [
    { name: "default", path: "/var/opt/gitlab/git-data/repositories" }
  ]
}

sudo gitlab-ctl reconfigure
```

### Конфигурация балансировщика

```nginx
# /etc/nginx/conf.d/gitlab.conf

upstream gitlab_rails {
  server rails-1.internal:8080 max_fails=3 fail_timeout=30s;
  server rails-2.internal:8080 max_fails=3 fail_timeout=30s;
  server rails-3.internal:8080 max_fails=3 fail_timeout=30s;
}

upstream gitlab_workhorse {
  server rails-1.internal:8181 max_fails=3 fail_timeout=30s;
  server rails-2.internal:8181 max_fails=3 fail_timeout=30s;
  server rails-3.internal:8181 max_fails=3 fail_timeout=30s;
}

server {
  listen 80;
  server_name gitlab.example.com;

  client_max_body_size 0;
  chunked_transfer_encoding on;

  location / {
    proxy_read_timeout 300;
    proxy_connect_timeout 300;
    proxy_redirect off;
    proxy_pass http://gitlab_workhorse;

    proxy_set_header Host $http_host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
  }
}
```

### Мониторинг в масштабе

```yaml
# prometheus/gitlab_scaled.yml
groups:
  - name: gitlab_scaled
    rules:
      - alert: GitLabPumaLatencyHigh
        expr: histogram_quantile(0.95, sum(rate(gitlab_http_request_duration_seconds_bucket[5m])) by (le, endpoint)) > 1
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "GitLab Puma latency p95 > 1s"
          description: "Endpoint {{ $labels.endpoint }} has p95 latency {{ $value }}s"

      - alert: GitLabSidekiqQueueGrowing
        expr: sidekiq_queue_size > 1000
        for: 10m
        labels:
          severity: warning
        annotations:
          summary: "Sidekiq queue growing"
          description: "Queue {{ $labels.queue }} has {{ $value }} jobs"

      - alert: GitLabGitalyHighLatency
        expr: gitaly_request_duration_seconds > 1
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "Gitaly high latency"
          description: "Gitaly p95 latency is above 1 second"
```

## Практические сценарии

### Сценарий 1: Distributed Architecture (2000+ пользователей)

Разнесение компонентов по выделенным серверам. Rails/Sidekiq-ноды stateless, размещаются за балансировщиком. Gitaly, PostgreSQL, Valkey выносятся на отдельные серверы или HA-кластеры.

### Сценарий 2: Настройка Gitaly на выделенном сервере

Gitaly выносится на отдельный сервер с NVMe-дисками. Настройка concurrency limit по RPC и storage path. См. конфигурацию в разделе [Конфигурация](#конфигурация).

### Сценарий 3: Настройка балансировщика

LB распределяет трафик между Rails/Puma и Workhorse. Health check на `/-/readiness` и `/-/liveness`. Таймауты настроены на 300s для длительных операций.

### Сценарий 4: Мониторинг в масштабе

Настройка Prometheus alerts на ключевые метрики: p95 latency Puma, размер очереди Sidekiq, задержка Gitaly, соединения PostgreSQL. См. пример в разделе [Конфигурация](#конфигурация).

### Сценарий 5: Планирование изменений (Change Management)

```bash
# 1. Создание maintenance window
# - Уведомить пользователей за 24 часа
# - Запланировать в нерабочее время
# - Подготовить бэкап

# 2. Бэкап
sudo gitlab-backup create CRON=1
sudo cp /etc/gitlab/gitlab-secrets.json /backup/secrets-$(date +%Y%m%d).json

# 3. Перевод в режим обслуживания
sudo gitlab-rake gitlab:maintenance:on

# 4. Выполнение изменений
# - Обновление пакетов
# - Миграции БД
# - Изменения конфигурации

# 5. Проверка
sudo gitlab-ctl status
sudo gitlab-rake gitlab:check SANITIZE=true

# 6. Вывод из режима обслуживания
sudo gitlab-rake gitlab:maintenance:off

# 7. Мониторинг
sudo gitlab-ctl tail
```

> **Примечание:** детальные процедуры бэкапа и восстановления см. в [Управление инстансом GitLab](./gitlab_instance_administration.md). Детали стратегий обновления — в [Обновление и обслуживание GitLab](./gitlab_upgrades_and_maintenance.md).

## Валидация и диагностика

### Проверка статуса в масштабе

```bash
# Общий статус
sudo gitlab-ctl status

# Проверка конкретных компонентов
sudo gitlab-ctl status puma
sudo gitlab-ctl status sidekiq
sudo gitlab-ctl status gitaly
sudo gitlab-ctl status postgresql
sudo gitlab-ctl status redis

# Проверка метрик
sudo gitlab-ctl metrics
```

### Проверка здоровья

```bash
# Полная проверка здоровья
sudo gitlab-rake gitlab:check SANITIZE=true

# Проверка отдельных компонентов
sudo gitlab-rake gitlab:check SANITIZE=true --skip=uploads,artifacts,builds

# Проверка миграций БД
sudo gitlab-rake gitlab:db:migrate:status

# Проверка репозиториев
sudo gitlab-rake gitlab:check:repos
```

### Проверка производительности

```bash
# Использование CPU
top -u git

# Использование памяти
free -h
ps aux --sort=-%mem | head

# Использование диска
df -h
du -sh /var/opt/gitlab/*

# Использование сети
ss -s
netstat -an | grep :443 | wc -l
```

### Валидация after-change

После любого изменения конфигурации или топологии:

1. `sudo gitlab-ctl status` — все компоненты в `run`.
2. `sudo gitlab-rake gitlab:check SANITIZE=true` — нет предупреждений.
3. Проверка health endpoint: `curl -k https://gitlab.example.com/-/readiness` → `{"status":"ok"}`.
4. Проверка метрик Sidekiq: очередь < 1000 job, latency < 5s.
5. Проверка Gitaly: `gitlab-ctl tail gitaly` — нет ошибок, RPC latency < 1s.
6. Проверка PostgreSQL: активные соединения < `max_connections` × 0.8.

## Операции и команды

### Проверка статуса

```bash
sudo gitlab-ctl status
sudo gitlab-ctl status puma
sudo gitlab-ctl status sidekiq
sudo gitlab-ctl status gitaly
sudo gitlab-ctl status postgresql
sudo gitlab-ctl status redis
sudo gitlab-ctl metrics
```

### Проверка здоровья

```bash
sudo gitlab-rake gitlab:check SANITIZE=true
sudo gitlab-rake gitlab:check SANITIZE=true --skip=uploads,artifacts,builds
sudo gitlab-rake gitlab:db:migrate:status
sudo gitlab-rake gitlab:check:repos
```

### Мониторинг ресурсов

```bash
# CPU
top -u git

# Память
free -h
ps aux --sort=-%mem | head

# Диск
df -h
du -sh /var/opt/gitlab/*

# Сеть
ss -s
netstat -an | grep :443 | wc -l
```

### Управление Sidekiq

```bash
# Статус процессов Sidekiq
sudo gitlab-ctl status sidekiq

# Количество очередей
sudo gitlab-rake gitlab:sidekiq:queues

# Остановка/запуск
sudo gitlab-ctl restart sidekiq
```

## Типичные ошибки и решения

| Симптом | Причина | Решение |
|:---|:---|:---|
| Высокое CPU | Недостаточная производительность | Вертикальное/горизонтальное масштабирование |
| Нехватка памяти | Мало RAM для PostgreSQL/Sidekiq | Увеличьте RAM или оптимизируйте конфигурацию |
| Медленные запросы | Проблемы с БД | Проверьте индексы, long-running queries |
| Очередь Sidekiq растёт | Недостаточная параллельность | Увеличьте `concurrency`, добавьте процессы |
| Gitaly таймауты | Медленный диск | Используйте SSD/NVMe |
| Репликация отстаёт | Сетевая задержка | Проверьте сеть, увеличьте bandwidth |
| Puma 502 Bad Gateway | Перегрузка Workers | Увеличьте `workers` и `worker_processes` |
| PostgreSQL connection limit | Слишком много соединений | Внедрите PgBouncer, настройте pool |
| Valkey memory full | Eviction policy | Настройте `maxmemory-policy` на `allkeys-lru` |
| Git push slow | Gitaly concurrency limit | Увеличьте `max_per_repo` для `PostReceivePack` |

## Best Practices

### Для DevOps / SRE

- **Capacity Planning:** отслеживайте рост пользователей, проектов, CI/CD jobs. Планируйте топологию при приближении к порогу.
- **Change Management:** все изменения через maintenance window с бэкапом, проверкой и мониторингом 24–72 часа после.
- **Observability:** настройте алерты на ключевые метрики (очередь Sidekiq, задержка Gitaly, соединения PostgreSQL, p95 latency Puma).
- **Automation:** конфигурация через IaC (Ansible, Terraform), конфигурационные изменения через CI/CD pipeline с approval gates.
- **Network Segmentation:** размещайте компоненты в отдельных подсетях. Firewall между application, database, storage.

### Для Sysadmin

- **Железо:** SSD/NVMe обязательны для Gitaly и PostgreSQL. Отдельные диски для `/var/opt/gitlab/git-data/repositories`.
- **HA:** Patroni + Consul для PostgreSQL HA. Gitaly Cluster (RAFT) для Git-данных на VM.
- **Connection Pooling:** PgBouncer для PostgreSQL при большом количестве соединений от Rails-нод.
- **Secrets Management:** `gitlab-secrets.json` — самый критичный файл. Храните в offsite, версионируйте изменения.
- **Бэкап:** регулярные бэкапы с offsite-хранением. Тестируйте восстановление минимум раз в квартал (DR Drill).
- **Monitoring Stack:** Prometheus + Alertmanager + Grafana на выделенных серверах или в отдельном namespace Kubernetes.

### Для Architect

- **Topology Choice:** выбирайте topology по пользователям и SLA. Не переусложняйте для <2000 пользователей.
- **Stateless First:** максимально выносите stateless-компоненты (Puma, Sidekiq) для простого горизонтального масштабирования.
- **Stateful Strategy:** для stateful-компонентов используйте HA-кластеры с автоматическим failover, а не manual procedures.
- **Geo Replication:** применяйте GitLab Geo для территориально распределённых команд и DRP, а не только для ускорения Git-операций.

## Граничные случаи и ограничения

### Air-gapped окружения

При отсутствии доступа к внешним реестрам и интернету:
- Все компоненты разворачиваются из локальных mirror.
- Gitaly, PostgreSQL, Valkey — полностью изолированные.
- Бэкапы — sneakernet-бандл на выделенный носитель.
- Мониторинг — локальный стек Prometheus + Alertmanager без внешних интеграций.

### Cross-project и Group-level ограничения

При >10000 пользователей:
- Sharding по группам требует ручного управления или кастомных инструментов.
- Cross-group CI/CD — повышенная нагрузка на Sidekiq и PostgreSQL.
- GitLab Geo — только read-only для проектов; push должен идти на primary.

### Fallback и degraded mode

При отказе одного из компонентов:
- Gitaly недоступен → Git-операции блокируются, но веб-интерфейс доступен для чтения.
- Valkey недоступен → Sidekiq останавливается, кэш сбрасывается, сессии пользователей инвалидируются.
- PostgreSQL недоступен → весь инстанс недоступен.

### Ограничения масштабирования

- **Gitaly:** не поддерживает Kubernetes; развёртывание только на VM.
- **PostgreSQL:** вертикальное масштабирование до ~2000 соединений; для большего — PgBouncer + Patroni.
- **Valkey:** single-threaded для большинства операций; горизонтальное масштабирование через Cluster или Sentinel.
- **Sidekiq:** ограничен memory per-process; при большом количестве очередей — несколько процессов с фильтрацией очередей.
- **GitLab Geo:** не заменяет primary; latency replication может достигать минут для больших репозиториев.

### Migration между топологиями

Миграция с Single Node на Distributed:
1. Развёртывание external PostgreSQL с Patroni.
2. Развёртывание external Valkey.
3. Развёртывание Gitaly с миграцией данных.
4. Переключение Rails-нод на внешние сервисы.
5. Валидация и gradual traffic shift.
6. Удаление Single Node.

Миграция требует maintenance window с бэкапом и планом отката.

## Дополнительная информация

### Связанные темы

* **[Архитектура GitLab](../Concepts/gitlab_platform_architecture.md)** — общая архитектура и компоненты
* **[Управление инстансом GitLab](./gitlab_instance_administration.md)** — бэкап, восстановление, обновление
* **[Обновление и обслуживание GitLab](./gitlab_upgrades_and_maintenance.md)** — zero-downtime обновления, blue-green, maintenance
* **[Управление базами данных GitLab](./gitlab_database_management.md)** — PostgreSQL и Valkey/Redis
* **[Gitaly: глубинное погружение](./gitlab_gitaly_deep_dive.md)** — детали работы Gitaly
* **[Capacity Planning для GitLab CI/CD](./gitlab_capacity_planning.md)** — планирование мощности CI/CD инфраструктуры

### Полезные ресурсы

* [GitLab Scalability Guide](https://docs.gitlab.com/ee/administration/scalability/)
* [GitLab Reference Architectures](https://docs.gitlab.com/ee/administration/reference_architectures/)
* [GitLab Performance Indicators](https://docs.gitlab.com/ee/administration/monitoring/prometheus/gitlab_metrics.html)
* [GitLab Geo Documentation](https://docs.gitlab.com/ee/administration/geo/)
