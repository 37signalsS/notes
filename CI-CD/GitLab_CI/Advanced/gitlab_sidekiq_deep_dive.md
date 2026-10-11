# Sidekiq: глубинное погружение

**Актуально для:** GitLab 17.x–19.x

## Определения

* **Sidekiq** — многопоточный фоновый обработчик задач на Ruby, используемый GitLab для асинхронных операций. Встроен в Omnibus GitLab и управляется через `gitlab-ctl`.
* **Job (Задача)** — единица работы в очереди Sidekiq (email, миграции, webhook, CI/CD и т.д.). Каждая задача содержит класс воркера, уникальный JID и сериализованные аргументы.
* **Queue (Очеред)** — упорядоченный список задач, ожидающих выполнения. Очереди именованные; GitLab использует сотни очередей, сгруппированных по feature category.
* **Worker (Воркер)** — класс Ruby, определяющий логику обработки конкретного типа задач. В GitLab воркеры автоматически регистрируются в `all_queues.yml`.
* **Concurrency (Параллельность)** — количество потоков, одновременно обрабатывающих задачи в рамках одного процесса Sidekiq.
* **Process (Процесс)** — экземпляр sidekiq-cluster, управляющий одной или несколькими группами очередей. В Omnibus управляется через `sidekiq['processes']` и `sidekiq['queue_groups']`.
* **Queue Group** — группа очередей, обрабатываемая одним процессом sidekiq-cluster. Определяется элементом массива `sidekiq['queue_groups']`.
* **Queue Selector** — механизм выбора очередей по правилам (feature category, urgency, resource boundary) вместо явного перечисления имён. Включается через `sidekiq['queue_selector'] = true`.
* **Sidekiq Queue** — отдельная очередь для группы задач (например, `mailers`, `default`, `priority`).
* **Dead Set (Мёртвый набор)** — задачи, которые исчерпали все попытки выполнения. Хранятся в сортированном множестве Redis/Valkey.
* **Retry Set** — задачи, находящиеся в состоянии повторного выполнения после временной ошибки.
* **Scheduled Set** — задачи, запланированные к выполнению в будущем (cron или отложенный enqueue).
* **Latency (Задержка очереди)** — разница в секундах между текущим временем и временем постановки самой старой задачи в очередь.
* **Sidekiq Memory Killer** — встроенный middleware GitLab, завершающий job при превышении порога RSS-памяти процесса Sidekiq.
* **Valkey** — in-memory хранилище (форк Redis), используемое в GitLab 19.x как основной брокер сообщений для очередей Sidekiq. В Omnibus управляется через те же ключи `redis['...']` в `gitlab.rb`.
* **sidekiq-cluster** — утилита GitLab, управляющая несколькими процессами Sidekiq и их группами очередей.

## Предварительные требования

### Железо и ОС

| Компонент | Требование |
|:---|:---|
| CPU | 4+ vCPU (рекомендуется 8+ для production). Количество процессов Sidekiq не должно превышать количество ядер, выделенных для Sidekiq. |
| RAM | 16+ ГБ (рекомендуется 32+ ГБ). Sidekiq потребляет 1–2 ГБ на процесс при concurrency 20–25. |
| Диск | 50+ ГБ SSD для `/var/opt/gitlab`. Логи Sidekiq находятся в `/var/log/gitlab/sidekiq/`. |
| ОС | Linux с systemd (Rocky Linux 9, AlmaLinux 9, Ubuntu 22.04/24.04 LTS). |

### Программное обеспечение

| Компонент | Версия | Примечание |
|:---|:---|:---|
| GitLab | 17.x–19.x | Omnibus, Docker или Helm |
| Valkey/Redis | Valkey 7.2+ или Redis 7.2+ | Redis 6 удалён в GitLab 19.0 |
| PostgreSQL | 17+ (GitLab 19.0) | Соединения от Sidekiq идут через PgBouncer при HA-конфигурации |

### Сеть

| Порт | Назначение |
|:---|:---|
| 6379 | Valkey/Redis (брокер очередей Sidekiq) |
| 8080–8092 | Sidekiq health-check сервер (опционально) |
| 9090 | Prometheus (сбор метрик Sidekiq) |

### Права

Требуется доступ `root` или `sudo` для управления сервисами и применения `gitlab-ctl reconfigure`. Для API-вызовов необходим токен администратора (`PRIVATE-TOKEN` с правами `api` и `admin`).

## Основные концепции

### Архитектура Sidekiq в GitLab

Sidekiq в GitLab состоит из трёх компонентов:

1. **Sidekiq Server (sidekiq-cluster)** — группа процессов, выполняющих задачи из очередей. Каждый процесс имеет собственный пул Ruby-потоков (concurrency).
2. **Valkey/Redis** — брокер сообщений, хранящий очереди. В GitLab 19.x используется Valkey 7.2+; управление через те же ключи `redis['...']` в `gitlab.rb`.
3. **Sidekiq UI** — веб-интерфейс для мониторинга (Admin Area → Monitoring → Background Jobs). В Omnibus доступен по адресу `/-/sidekiq`.

### Жизненный цикл задачи

```
Job Enqueue → Valkey/Redis Queue → sidekiq-cluster (thread pool) → Worker Execution
                                                              ↓
                                                    Success (ACK) / Retry / Dead Set
```

**Состояния задачи:**
1. **Enqueued** — задача находится в очереди, ожидает свободного потока.
2. **Running** — задача выполняется воркером.
3. **Completed** — задача выполнена успешно, подтверждение (ACK) отправлено в Valkey/Redis.
4. **Retry** — задача вернула временную ошибку, запланирована к повторному выполнению.
5. **Dead** — задача исчерпала все попытки (по умолчанию 25 попыток за ~21 день), перемещена в Dead Set.
6. **Scheduled** — задача запланирована к выполнению в будущем времени.

### Типы задач GitLab

| Категория | Примеры задач | Приоритет | Очереди |
|:---|:---|:---|:---|
| **Email** | Отправка уведомлений, приглашений | Средний | `mailers` |
| **CI/CD** | Обработка пайплайнов, webhook'ов | Высокий | `pipeline_*`, `webhook_*` |
| **Repository** | Git-операции, архивация | Высокий | `repository_*` |
| **Merge Request** | Обновление MR, проверки | Средний | `merge_*` |
| **Security** | Сканирование, compliance | Низкий | `security_*` |
| **Maintenance** | Очистка кэша, удаление старых данных | Низкий | `maintenance_*` |

### Модель обработки задач

```
Job → Valkey/Redis Queue → sidekiq-cluster (threads) → Worker → Result
                                    ↓
                              Dead Set (при ошибке)
```

### sidekiq-cluster и queue groups

`sidekiq-cluster` запускает несколько процессов Sidekiq, каждый из которых слушает заданный набор очередей. Количество процессов задаётся длиной массива `sidekiq['queue_groups']`:

```ruby
# Каждый элемент массива = один процесс
sidekiq['queue_groups'] = ['*']     # 1 процесс, все очереди
sidekiq['queue_groups'] = ['*'] * 4 # 4 процесса, каждый слушает все очереди
sidekiq['queue_groups'] = [
  'feature_category=continuous_integration,pages&urgency!=high',
  'resource_boundary!=cpu&urgency=high',
  '*'
]
```

**Правила:**
- Количество процессов не должно превышать количество ядер CPU, выделенных для Sidekiq.
- Если `sidekiq['queue_selector'] = true`, все элементы `queue_groups` должны использовать синтаксис правил (не подстановочный знак `*`).

### Queue Selector и worker matcher

Queue selector позволяет распределять задачи по процессам на основе метаданных воркеров:

```ruby
# /etc/gitlab/gitlab.rb
sidekiq['enable'] = true
sidekiq['queue_selector'] = true
sidekiq['queue_groups'] = [
  'name=project_export',           # Процесс для project_export
  'name!=project_export'           # Остальные процессы
]
```

**Доступные поля для правил:**
- `feature_category` — категория функции воркера (например, `continuous_integration`, `importers`)
- `urgency` — срочность (`low`, `medium`, `high`)
- `resource_boundary` — тип ресурса (`cpu`, `memory`, `unknown`)
- `name` — точное имя очереди

### Sidekiq Memory Killer

Middleware GitLab, защищающий от OOM:

| Параметр | По умолчанию | Описание |
|:---|:---|:---|
| `sidekiq['memory_killer']` | `true` | Включение middleware |
| `sidekiq['memory_killer_max_rss']` | `4 GB` | Порог RSS-памяти |
| `sidekiq['memory_killer_shutdown_timeout']` | `5s` | Таймаут graceful shutdown |

При превышении порога Middleware завершает самый долгий job в текущем процессе и инициирует перезапуск.

## Практические сценарии

### Сценарий 1: Мониторинг очередей Sidekiq

```bash
# 1. Доступ к Admin UI
# Откройте https://gitlab.example.com/admin/background_jobs
# Или https://gitlab.example.com/-/sidekiq (GitLab 17.x+)

# 2. Проверка через CLI
sudo gitlab-ctl status sidekiq

# 3. Просмотр логов Sidekiq
sudo gitlab-ctl tail sidekiq
sudo gitlab-ctl tail sidekiq --lines 100

# 4. Проверка размера очередей через API
curl -H "PRIVATE-TOKEN: <token>" "https://gitlab.example.com/api/v4/admin/sidekiq/queues"

# 5. Проверка метрик через API
curl -s -H "PRIVATE-TOKEN: <token>" "https://gitlab.example.com/api/v4/sidekiq/queue_metrics"
# → { "queues": { "default": { "backlog": 0, "latency": 0 } } }

curl -s -H "PRIVATE-TOKEN: <token>" "https://gitlab.example.com/api/v4/sidekiq/process_metrics"
# → { "processes": [ { "hostname": "gitlab", "concurrency": 25, "queues": [...], "busy": 0 } ] }

curl -s -H "PRIVATE-TOKEN: <token>" "https://gitlab.example.com/api/v4/sidekiq/compound_metrics"
# → Комбинированный ответ: queues + processes + jobs

# 6. Проверка метрик Prometheus
curl -s http://localhost:9090/api/v1/query?query=sidekiq_queue_size
curl -s http://localhost:9090/api/v1/query?query=sidekiq_running_jobs
```

**Валидация:**
- `gitlab-ctl status sidekiq` должен показать `run: sidekiq: (pid XXXX) Xs` для каждого процесса.
- API `/sidekiq/queue_metrics` возвращает JSON с полями `backlog` и `latency` для каждой очереди.
- Prometheus-метрики `sidekiq_queue_size` и `sidekiq_running_jobs` содержат числовые значения > 0.

### Сценарий 2: Настройка параллелизма и процессов

```ruby
# /etc/gitlab/gitlab.rb

# Количество потоков на процесс Sidekiq (по умолчанию: количество CPU * 2, макс. 50)
sidekiq['concurrency'] = 20

# Ограничения concurrency для адаптивного масштабирования
sidekiq['max_concurrency'] = 25
sidekiq['min_concurrency'] = 5

# Количество процессов Sidekiq (по умолчанию: 2)
sidekiq['processes'] = 2

# Группы очередей для каждого процесса
# Длина массива = количество процессов sidekiq-cluster
sidekiq['queue_groups'] = ['*'] * 4

# Queue selector (включает правила выбора очередей)
sidekiq['queue_selector'] = false

# Sidekiq Memory Killer
sidekiq['memory_killer'] = true
sidekiq['memory_killer_max_rss'] = '4 GB'
sidekiq['memory_killer_shutdown_timeout'] = 5

# Применение
sudo gitlab-ctl reconfigure
```

**Валидация:**
- `sudo gitlab-rake sidekiq:queues` показывает распределение очередей по процессам.
- Admin UI → Monitoring → Background Jobs отображает правильное количество процессов.
- `ps aux | grep sidekiq` показывает `N` процессов с ожидаемым количеством потоков.

### Сценарий 3: Очистка Dead Set и Retry Set

```bash
# Просмотр статистики через rake
sudo gitlab-rake sidekiq:dead
sudo gitlab-rake sidekiq:retry

# Просмотр через Rails console
sudo gitlab-rails console
> Sidekiq::DeadSet.new.size
> Sidekiq::RetrySet.new.size
> Sidekiq::ScheduledSet.new.size

# Удаление всех мёртвых задач (RAILS CONSOLE!)
sudo gitlab-rails console
> Sidekiq::DeadSet.new.clear

# Удаление конкретной задачи по классу воркера
> dead_set = Sidekiq::DeadSet.new
> dead_set.each { |job| job.delete if job.args[0]['class'] == 'MyWorker' }

# Удаление задач из Retry Set
> retry_set = Sidekiq::RetrySet.new
> retry_set.each { |job| job.delete if job.args[0]['class'] == 'MyWorker' }
```

**Валидация:**
- После очистки `Sidekiq::DeadSet.new.size` возвращает `0`.
- Метрика `sidekiq_dead_jobs` в Prometheus падает до базового уровня.

### Сценарий 4: Диагностика и устранение накопления очереди

```bash
# 1. Проверка размера очереди
sudo gitlab-rake sidekiq:queues

# 2. Диагностика через Sidekiq check script
sudo gitlab-rails runner /opt/gitlab/embedded/service/gitlab-rails/lib/tasks/sidekiq/check.rake

# 3. Проверка логов Sidekiq
sudo gitlab-ctl tail sidekiq

# 4. Проверка доступности Valkey/Redis
sudo gitlab-ctl status redis
redis-cli ping

# 5. Проверка соединений PostgreSQL
sudo gitlab-psql -d gitlabhq_production -c "SELECT count(*) FROM pg_stat_activity;"
sudo gitlab-psql -d gitlabhq_production -c "SELECT * FROM pg_locks WHERE NOT granted;"

# 6. Проверка метрик Valkey
redis-cli info memory
redis-cli info stats

# 7. Временное увеличение параллелизма (если причина — недостаток потоков)
sudo gitlab-ctl restart sidekiq

# 8. Мониторинг восстановления
watch -n 10 'sudo gitlab-rake sidekiq:queues'
```

**Валидация:**
- Очередь уменьшается на видимую величину в течение 5–10 минут.
- `sidekiq_queue_size` в Prometheus возвращается к пороговым значениям.
- Нет новых ошибок в логах Sidekiq после рестарта.

### Сценарий 5: Настройка алертов Prometheus

```yaml
# prometheus/gitlab_alerts.yml
groups:
  - name: sidekiq
    rules:
      - alert: SidekiqQueueGrowing
        expr: sidekiq_queue_size > 1000
        for: 10m
        labels:
          severity: warning
        annotations:
          summary: "Sidekiq queue size is growing"
          description: "Queue {{ $labels.queue }} has {{ $value }} jobs"

      - alert: SidekiqDeadJobsHigh
        expr: sidekiq_dead_jobs > 50
        for: 5m
        labels:
          severity: critical
        annotations:
          summary: "High number of dead Sidekiq jobs"
          description: "Dead set has {{ $value }} jobs"

      - alert: SidekiqLatencyHigh
        expr: histogram_quantile(0.95, rate(sidekiq_queue_latency_seconds_bucket[5m])) > 30
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "Sidekiq queue latency is high"
          description: "p95 latency {{ $value }}s"

      - alert: SidekiqMemoryKillerActive
        expr: increase(gitlab_sidekiq_memory_killer_total[10m]) > 0
        for: 0m
        labels:
          severity: critical
        annotations:
          summary: "Sidekiq Memory Killer terminated jobs"
          description: "Memory killer ran {{ $value }} times in last 10m"

      - alert: SidekiqProcessDown
        expr: up{job="sidekiq"} == 0
        for: 1m
        labels:
          severity: critical
        annotations:
          summary: "Sidekiq process is down"
```

**Валидация:**
- В Prometheus UI видно все 5 правил в статусе `inactive` или `firing`.
- Проверка алерта: искусственно создайте очередь из 1000+ задач и убедитесь, что алерт переходит в `firing`.

### Сценарий 6: External Sidekiq (масштабирование на отдельном хосте)

```ruby
# /etc/gitlab/gitlab.rb на хосте gitlab-sidekiq-host
sidekiq['enable'] = true
sidekiq['listen_address'] = '0.0.0.0'
sidekiq['queue_groups'] = ['*'] * 4
sidekiq['metrics_enabled'] = true
sidekiq['exporter_tls_enabled'] = false
sidekiq['listen_address'] = '0.0.0.0'
sidekiq['listen_port'] = 8082
```

**Валидация:**
- В Admin UI → Monitoring → Background Jobs виден новый хост с ожидаемым количеством процессов.
- `curl http://gitlab-sidekiq-host:8082/readiness` возвращает `{"status":"ok"}`.
- Метрики Sidekiq с внешнего хоста появляются в Prometheus с соответствующим label `instance="gitlab-sidekiq-host:8082"`.

### Сценарий 7: Graceful shutdown и ротация процессов

```bash
# Graceful shutdown Sidekiq (дождаться завершения текущих job'ов)
sudo gitlab-ctl stop sidekiq

# Проверка, что процессы завершились корректно
sudo gitlab-ctl status sidekiq

# Применение новой конфигурации
sudo gitlab-ctl reconfigure

# Запуск Sidekiq
sudo gitlab-ctl start sidekiq

# Проверка статуса
sudo gitlab-ctl status sidekiq
```

**Валидация:**
- Все процессы `sidekiq: (pid XXXX) Xs` имеют статус `run`.
- В логах `/var/log/gitlab/sidekiq/sidekiq.log` нет ошибок после рестарта.
- Sidekiq UI показывает все процессы в статусе `ready`.

## Операции и команды

### Управление процессами

```bash
# Статус всех процессов Sidekiq
sudo gitlab-ctl status sidekiq

# Запуск/остановка/перезапуск
sudo gitlab-ctl start sidekiq
sudo gitlab-ctl stop sidekiq
sudo gitlab-ctl restart sidekiq

# Просмотр логов
sudo gitlab-ctl tail sidekiq
sudo gitlab-ctl tail sidekiq --lines 100

# Health-check endpoints (если настроен health-check сервер)
curl http://localhost:8092/readiness
curl http://localhost:8092/liveness
```

### Полезные rake-задачи

```bash
# Просмотр всех очередей
sudo gitlab-rake sidekiq:queues

# Просмотр dead set
sudo gitlab-rake sidekiq:dead

# Просмотр retry set
sudo gitlab-rake sidekiq:retry

# Очистка dead set
sudo gitlab-rake sidekiq:clear_dead

# Обработка конкретной очереди (через sidekiq-cluster)
sudo gitlab-rake sidekiq:process_queue queue=mailers

# Просмотр всех очередей (альтернативный синтаксис)
sudo gitlab-rake gitlab:sidekiq:queues

# Проверка здоровья Sidekiq
sudo gitlab-rake sidekiq:health_check
```

### Полезные команды Rails console

```ruby
# Просмотр всех очередей
Sidekiq::Queue.all.map(&:name)

# Размер конкретной очереди
Sidekiq::Queue.new("mailers").size

# Latency конкретной очереди (секунды)
Sidekiq::Queue.new("mailers").latency

# Dead set
Sidekiq::DeadSet.new.size
Sidekiq::DeadSet.new.clear

# Retry set
Sidekiq::RetrySet.new.size
Sidekiq::RetrySet.new.clear

# Scheduled jobs
Sidekiq::ScheduledSet.new.size

# Статистика
Sidekiq::Stats.new.processed
Sidekiq::Stats.new.failed
Sidekiq::Stats.new.enqueued
Sidekiq::Stats.new.queues

# Статистика процессов
Sidekiq::ProcessSet.new.map { |p|
  {
    "hostname" => p["hostname"],
    "concurrency" => p["concurrency"],
    "queues" => p["queues"],
    "busy" => p["busy"]
  }
}
```

## Типичные ошибки и решения

| Симптом | Причина | Решение | Диагностика |
|:---|:---|:---|:---|
| Очередь растёт | Недостаточная параллельность | Увеличьте `concurrency` или добавьте процессы | `sidekiq_queue_size` в Prometheus |
| Dead jobs растут | Ошибки в workers | Исправьте код worker'ов, очистите dead set | Логи Sidekiq, Sentry |
| Sidekiq OOM | Memory Killer или system OOM | Увеличьте `memory_killer_max_rss` или добавьте RAM | `dmesg`, логи Sidekiq |
| Sidekiq не запускается | Valkey/Redis недоступен | Проверьте доступность: `gitlab-ctl status redis` | `redis-cli ping` |
| Задачи выполняются медленно | Блокировки в БД | Проверьте долгие запросы в PostgreSQL | `pg_stat_activity`, `pg_locks` |
| Высокое CPU | Слишком высокая параллельность | Уменьшите `concurrency` | `top`, `htop` по процессам Sidekiq |
| Высокое использование Valkey | Слишком много процессов/потоков | Снизьте `concurrency` и количество процессов | `redis-cli info memory` |
| Высокая latency очереди | Бэклог задач, медленные воркеры | Проверьте медленные workers, увеличьте parallelism | `sidekiq_queue_latency_seconds` |
| Sidekiq Memory Killer срабатывает часто | RSS превышает порог | Увеличьте `memory_killer_max_rss`, оптимизируйте worker | Логи `/var/log/gitlab/sidekiq/` |
| sidekiq-cluster не стартует | Неверный синтаксис `queue_groups` | Проверьте синтаксис queue_selector | `gitlab-ctl tail sidekiq` |
| Очереди исчезают после рестарта | Утечка соединений Valkey/Redis | Проверьте `maxclients` и таймауты | `redis-cli info clients` |

## Лучшие практики

### Производительность

* **Concurrency:** начните с `CPU cores * 2` (макс. 50), мониторьте и корректируйте.
* **Processes:** для больших инстансов используйте 2+ процесса Sidekiq, но не более количества ядер CPU.
* **Очереди:** разделяйте критичные и некритичные задачи по разным группам очередей с разным количеством процессов.
* **Queue Selector:** используйте правила выбора очередей вместо перечисления имён для гибкости масштабирования.
* **Мониторинг:** отслеживайте размер очереди (`backlog`), latency (`latency`), время обработки, dead jobs и память процессов.

### Надёжность

* **Dead Set:** регулярно проверяйте и очищайте dead set. Настройте алерт на рост `sidekiq_dead_jobs > 50`.
* **Retry:** настройте политику повторных попыток для критичных задач (по умолчанию 25 попыток за ~21 день).
* **Graceful shutdown:** используйте `gitlab-ctl stop sidekiq` для корректного завершения задач.
* **Health Checks:** настройте readiness/liveness эндпоинты для мониторинга доступности Sidekiq.
* **Sidekiq Memory Killer:** оставьте включённым, настройте порог RSS под объём RAM инстанса.

### Безопасность

* **Изоляция:** не запускайте Sidekiq с повышенными привилегиями.
* **Secrets:** не храните секреты в аргументах задач (используйте Vault или CI/CD variables).
* **API токены:** используйте токены с минимально необходимыми правами для доступа к Sidekiq API.
* **Redis/Valkey ACL:** ограничьте доступ к брокеру сообщений, если он используется совместно с другими сервисами.

### Эксплуатация (DevOps/SRE)

* **Ротация логов:** настройте logrotate для `/var/log/gitlab/sidekiq/` (по умолчанию 30 дней).
* **Бэкап Valkey:** регулярно создавайте снапшоты RDB/AOF, особенно перед обновлением GitLab.
* **Change Management:** применяйте изменения `gitlab.rb` через `gitlab-ctl reconfigure` и валидируйте через `gitlab-rake gitlab:check SANITIZE=true`.
* **Восстановление после сбоя:** при проблемах с очередями не удаляйте задачи из Valkey/Redis вручную — используйте официальные rake-задачи или API.
* **Capacity Planning:** пересматривайте `concurrency` и количество процессов при росте числа пользователей/проектов.

### Восстановление (Cleanup)

```bash
# Откат изменений concurrency
sudo gitlab-ctl reconfigure

# Если рестарт не помог, вернитесь к предыдущей конфигурации
sudo cp /etc/gitlab/gitlab.rb.bak /etc/gitlab/gitlab.rb
sudo gitlab-ctl reconfigure
sudo gitlab-ctl restart sidekiq
```

## Пограничные случаи

### Высоконагруженные инстансы (>10 000 пользователей)

При большом объёме CI/CD операций:
- Используйте 4+ процесса Sidekiq с `queue_selector` для разделения importers и обычных задач.
- Настройте `min_concurrency` / `max_concurrency` для адаптивного управления потоками.
- Рассмотрите внешний Sidekiq на выделенном хосте.

### Ограничения соединений PostgreSQL

Sidekiq создаёт много короткоживущих соединений. При большом количестве процессов используйте PgBouncer:

```ruby
# /etc/gitlab/gitlab.rb
postgresql['max_connections'] = 200
pgbouncer['enable'] = true
pgbouncer['port'] = 6432
```

### Проблемы с памятью Ruby

Ruby GC может работать inefficiently при большом количестве потоков. Рекомендации:
- Используйте `RUBY_GC_HEAP_GROWTH_FACTOR` для настройки роста кучи.
- Ограничьте `concurrency` до 25 на процесс при RAM < 32 ГБ.
- Включите `sidekiq['memory_killer']` для предотвращения OOM Killer ядра.

### Резкое наполнение очередей после рестарта

При рестарте Sidekiq все запланированные задачи (Scheduled Set) могут одновременно попасть в очереди. Для смягчения:
- Используйте `sidekiq['interval'] = 5` для уменьшения интервала поллинга scheduled jobs.
- Убедитесь, что количество процессов после рестарта соответствует `queue_groups`.

## Дополнительная информация

### Связанные темы

* **[Архитектура GitLab](../Concepts/gitlab_platform_architecture.md)** — общая архитектура и компоненты
* **[Управление инстансом GitLab](./gitlab_instance_administration.md)** — бэкап, восстановление, обновление
* **[Управление базами данных GitLab](./gitlab_database_management.md)** — PostgreSQL и Valkey/Redis
* **[Мониторинг и метрики GitLab](./monitoring_and_metrics.md)** — Prometheus, Grafana, алертинг

### Полезные ссылки

* [GitLab Sidekiq Metrics API](https://docs.gitlab.com/api/sidekiq_metrics)
* [GitLab Admin Sidekiq Queues API](https://docs.gitlab.com/api/admin_sidekiq_queues)
* [GitLab Extra Sidekiq Processes](https://docs.gitlab.com/administration/operations/extra_sidekiq_processes)
* [GitLab Sidekiq Memory Killer](https://docs.gitlab.com/administration/operations/sidekiq_memory_killer.html)
* [GitLab Sidekiq Health Check](https://docs.gitlab.com/administration/sidekiq/sidekiq_health_check)
* [Sidekiq Documentation](https://github.com/sidekiq/sidekiq)
