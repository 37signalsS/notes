# Управление инстансом GitLab

**Актуально для:** GitLab 17.x–19.x (Omnibus, Docker, Helm)

## Определения

* **Instance Administration (Администрирование инстанса)** — комплекс операций по управлению GitLab Server: бэкап, восстановление, обновление, безопасность, масштабирование и мониторинг.
* **gitlab-secrets.json** — файл с ключами шифрования базы данных, сессиями, CI/CD переменными и другими секретами. Без него восстановление после сбоя невозможно.
* **gitlab.rb** — основной конфигурационный файл GitLab (Ansible-совместимый). Все параметры инстанса задаются через этот файл.
* **gitlab-ctl** — утилита управления Omnibus GitLab (status, restart, tail, reconfigure).
* **gitlab-rake** — утилита для выполнения административных задач (проверки, миграции, очистки).
* **Maintenance Mode (Режим обслуживания)** — состояние, при котором GitLab отклоняет входящие запросы, позволяя выполнять операции без риска повреждения данных.
* **DR Drill (Тренировка восстановления)** — плановое упражнение по восстановлению инстанса из бэкапа в изолированной среде.
* **Immutable Backup (Иммутабельный бэкап)** — резервная копия, защищённая от изменений и удаления на уровне хранилища (WORM/append-only).
* **RTO/RPO** — Recovery Time Objective (максимальное время простоя) и Recovery Point Objective (максимальная потеря данных).

## Основные концепции

### Жизненный цикл управления инстансом

Управление GitLab инстансом следует циклическому процессу:

1. **Развёртывание** — Omnibus/Docker/Helm + внешние зависимости (БД, кэш, хранилище).
2. **Конфигурация** — `gitlab.rb`, `gitlab-secrets.json`, переменные окружения.
3. **Бэкап** — регулярное создание резервных копий всех критичных данных.
4. **Мониторинг** — метрики компонентов, алертинг, логи.
5. **Обновление** — плановые обновления по официальным путям обновления.
6. **Восстановление** — процедуры восстановления при сбоях.

### Критичные данные для бэкапа

| Категория | Путь/Источник | Важность |
|:---|:---|:---|
| Конфигурация | `/etc/gitlab/gitlab.rb` | Обязательно |
| Секреты | `/etc/gitlab/gitlab-secrets.json` | Обязательно |
| Бэкап БД | `/var/opt/gitlab/backups/` | Обязательно |
| Git-репозитории | `/var/opt/gitlab/git-data/repositories` | Обязательно |
| Артефакты | `/var/opt/gitlab/gitlab-rails/shared/artifacts` | Рекомендуется |
| LFS-объекты | `/var/opt/gitlab/gitlab-rails/shared/lfs-objects` | Рекомендуется |
| Uploads | `/var/opt/gitlab/gitlab-rails/shared/uploads` | Рекомендуется |
| Registry | `/var/opt/gitlab/gitlab-rails/shared/registry` | По необходимости |
| Packages | `/var/opt/gitlab/gitlab-rails/shared/packages` | По необходимости |

### Стратегия бэкапа 3-2-1 для GitLab

Адаптация классической стратегии под специфику GitLab:

1. **3 копии:** рабочая версия + локальный бэкап + offsite-копия.
2. **2 носителя:** быстрый SSD для оперативного восстановления + медленный/архивный (NAS, выделенный узел) для долгого хранения.
3. **1 копия вне контура:** sneakernet-бандл или реплика на выделенный узел в другой подсети.

### Требования и ограничения

| Компонент | Требование |
|:---|:---|
| Лицензия | Premium/Ultimate для Geo, Gitaly Cluster, advanced monitoring. CE достаточно для базового администрирования. |
| PostgreSQL | 15+ (GitLab 18.x), 17+ (GitLab 19.x). HA требует Patroni + Consul. |
| Valkey/Redis | Valkey 7.2+ или Redis 7.2+. Redis 6 удалён в GitLab 19.0. |
| Сеть | Задержка между Rails и Gitaly < 2 ms. Изолированные подсети для management, application, database, storage. |
| Диски | SSD/NVMe для PostgreSQL и Gitaly. IOPS > 3000. Избегайте HDD для активных данных. |
| NTP | Синхронизация времени на всех узлах (разница < 100 ms). |
| ОС | Linux с systemd (Rocky Linux 9, AlmaLinux 9, Ubuntu 22.04/24.04 LTS). |

**Ограничения:**
* Kubernetes-развёртывания с Gitaly Cluster имеют статус beta начиная с GitLab 19.1. Для production HA Git-данных используйте VM.
* Минимальное количество узлов: 3 для RAFT-консенсуса (1 primary, 2 secondary).
* GitLab.com (SaaS) не поддерживает кастомизацию gitlab.rb и некоторые административные rake-задачи.
* В air-gapped окружениях требуется локальный registry для пакетов и container images.

## Практические сценарии

### Сценарий 1: Полный бэкап инстанса (Omnibus)

```bash
# 1. Создание полного бэкапа (включает БД, репозитории, артефакты, LFS)
sudo gitlab-backup create CRON=1
# → [2026-06-01 02:00:01] Creating backup archive: 1748774401_2026_06_01_19.0.0_gitlab_backup.tar

# 2. Бэкап конфигурации и секретов (ОБЯЗАТЕЛЬНО!)
sudo cp /etc/gitlab/gitlab-secrets.json /backup/gitlab-secrets-$(date +%Y%m%d).json
sudo cp /etc/gitlab/gitlab.rb /backup/gitlab-config-$(date +%Y%m%d).rb

# 3. Проверка контрольных сумм
sha256sum /backup/*.tar /backup/*.json

# 4. Offsite-копирование (rsync на выделенный узел)
rsync -avz --progress /backup/ backup.internal:/data/offsite/gitlab/
```

### Сценарий 2: Выборочный бэкап (только база данных)

```bash
# Пропуск тяжёлых компонентов (репозитории, артефакты, LFS)
sudo gitlab-backup create SKIP=tar,repositories,uploads,builds,artifacts,pages,lfs,terraform_state,registry,packages,ci_secure_files,agent_plan_content,external_diffs

# Бэкап только PostgreSQL
sudo gitlab-ctl pg-backup /backup/postgresql-$(date +%Y%m%d).sql.gz
```

### Сценарий 3: Восстановление инстанса

```bash
# 1. Перевод в режим обслуживания
sudo gitlab-rake gitlab:maintenance:on

# 2. Остановка критичных сервисов
sudo gitlab-ctl stop puma
sudo gitlab-ctl stop sidekiq
sudo gitlab-ctl stop unicorn

# 3. Восстановление бэкапа
sudo gitlab-backup restore BACKUP=1748774401_2026_06_01_19.0.0

# 4. Восстановление конфигурации и секретов
sudo cp /backup/gitlab-secrets-20260601.json /etc/gitlab/gitlab-secrets.json
sudo cp /backup/gitlab-config-20260601.rb /etc/gitlab/gitlab.rb

# 5. Применение конфигурации
sudo gitlab-ctl reconfigure

# 6. Запуск сервисов
sudo gitlab-ctl start

# 7. Вывод из режима обслуживания
sudo gitlab-rake gitlab:maintenance:off

# 8. Проверка статуса
sudo gitlab-ctl status
sudo gitlab-rake gitlab:check SANITIZE=true
```

### Сценарий 4: Обновление GitLab (Omnibus)

Процедуры standard и zero-downtime обновления Omnibus описаны в [Обновление и обслуживание GitLab](./gitlab_upgrades_and_maintenance.md).

### Сценарий 5: Обновление GitLab (Docker)

Процедуры обновления Docker-инстанса описаны в [Обновление и обслуживание GitLab](./gitlab_upgrades_and_maintenance.md).

### Сценарий 6: Управление секретами инстанса

```bash
# Просмотр текущих секретов
sudo gitlab-ctl show-secrets

# Ротация секретов (требует downtime)
sudo gitlab-rake gitlab:secrets:rotate

# Проверка целостности секретов
sudo gitlab-rake gitlab:secrets:check
```

### Сценарий 7: Режим обслуживания

Подробности использования maintenance mode при обновлении описаны в [Обновление и обслуживание GitLab](./gitlab_upgrades_and_maintenance.md).

### Сценарий 8: Восстановление после потери gitlab-secrets.json

```bash
# 1. Проверка доступных бэкапов
ls -lh /backup/gitlab-secrets-*.json

# 2. Восстановление секретов
sudo cp /backup/gitlab-secrets-20260601.json /etc/gitlab/gitlab-secrets.json
sudo chown root:root /etc/gitlab/gitlab-secrets.json
sudo chmod 600 /etc/gitlab/gitlab-secrets.json

# 3. Проверка целостности секретов
sudo gitlab-rake gitlab:secrets:check

# 4. Применение конфигурации
sudo gitlab-ctl reconfigure

# 5. Проверка доступа к БД
sudo gitlab-rake gitlab:check SANITIZE=true

# Если бэкап секретов отсутствует:
# - Восстановите инстанс с нуля (новая БД, новый gitlab-secrets.json)
# - Пересоздайте проекты и импортируйте репозитории
# - Ротация всех паролей и токенов
```

### Сценарий 9: Откат после неудачного обновления

Процедуры отката описаны в [Обновление и обслуживание GitLab](./gitlab_upgrades_and_maintenance.md).

### Сценарий 10: Бэкап и восстановление Helm (Kubernetes)

```bash
# 1. Бэкап секретов и PersistentVolumeClaims
kubectl get secret -n gitlab -o yaml > /backup/gitlab-k8s-secrets-$(date +%Y%m%d).yaml
kubectl get pvc -n gitlab -o yaml > /backup/gitlab-k8s-pvc-$(date +%Y%m%d).yaml

# 2. Бэкап базы данных
kubectl exec -n gitlab -it gitlab-postgresql-0 -- \
  pg_dump -U postgres gitlabhq_production | gzip > /backup/gitlab-db-$(date +%Y%m%d).sql.gz

# 3. Снэпшот PV (если поддерживается storage class)
kubectl get pv -n gitlab
kubectl apply -f - <<EOF
apiVersion: snapshot.storage.k8s.io/v1
kind: VolumeSnapshot
metadata:
  name: gitlab-pv-snapshot-$(date +%Y%m%d)
  namespace: gitlab
spec:
  volumeSnapshotClassName: csi-hostpath-snapshot-class
  source:
    persistentVolumeClaimName: gitlab-data
EOF

# 4. Сохранение Helm-релиза
helm get values gitlab -n gitlab > /backup/gitlab-helm-values-$(date +%Y%m%d).yaml
helm get manifest gitlab -n gitlab > /backup/gitlab-helm-manifest-$(date +%Y%m%d).yaml

# Восстановление:
# 1. Восстановите PV из снапшота
# 2. Восстановите секреты: kubectl apply -f gitlab-k8s-secrets-*.yaml
# 3. Восстановите БД: kubectl exec -it gitlab-postgresql-0 -- \
#    psql -U postgres gitlabhq_production < gitlab-db-*.sql.gz
# 4. Примените Helm-релиз: helm upgrade gitlab gitlab/gitlab -f values.yaml
```

### Сценарий 11: Восстановление после сбоя PostgreSQL

```bash
# 1. Определение причины сбоя
sudo gitlab-ctl status postgresql
sudo gitlab-ctl tail postgresql --since 1h

# 2. Если PostgreSQL не стартует из-за corrupted WAL:
sudo gitlab-ctl stop postgresql
sudo su - postgres -c "pg_resetwal /var/opt/gitlab/postgresql/data"

# 3. Восстановление из бэкапа
sudo gitlab-ctl start postgresql
sudo gitlab-backup restore BACKUP=1748774401_2026_06_01_19.0.0

# 4. Проверка целостности
sudo gitlab-psql -c "SELECT count(*) FROM projects;"
sudo gitlab-rake gitlab:check SANITIZE=true

# 5. Если используется streaming replication:
# - Проверьте состояние standby
sudo -u gitlab-psql /opt/gitlab/embedded/bin/pg_ctl -D /var/opt/gitlab/postgresql/data promote
# - Обновите connection string в gitlab.rb
# - Выполните reconfigure
```

## Валидация

После каждой критичной операции (бэкап, восстановление, обновление) выполняйте проверки:

```bash
# 1. Статус всех компонентов
sudo gitlab-ctl status
# → все сервисы должны быть в состоянии run

# 2. Проверка здоровья
sudo gitlab-rake gitlab:check SANITIZE=true
# → GitLab should report: Check complete: passed

# 3. Проверка готовности API
curl -s -o /dev/null -w "%{http_code}" http://localhost:8080/-/ready
# → 200

# 4. Проверка миграций БД
sudo gitlab-rake gitlab:db:migrate:status
# → все миграции должны быть в состоянии up

# 5. Проверка целостности репозиториев
sudo gitlab-rake gitlab:git:fsck
# → no errors reported

# 6. Проверка очередей Sidekiq
sudo gitlab-rake gitlab:sidekiq:check
# → queue depth должен быть адекватным (не thousands of jobs)

# 7. Проверка секретов
sudo gitlab-rake gitlab:secrets:check
# → все секреты целостны

# 8. Проверка логов на ошибки
sudo gitlab-ctl tail puma --since 1h | grep -i error
sudo gitlab-ctl tail sidekiq --since 1h | grep -i error
```

## Операции и команды

### Проверка статуса компонентов

```bash
# Общий статус
sudo gitlab-ctl status

# Статус конкретного компонента
sudo gitlab-ctl status puma
sudo gitlab-ctl status sidekiq
sudo gitlab-ctl status gitaly
sudo gitlab-ctl status postgresql
sudo gitlab-ctl status redis
sudo gitlab-ctl status nginx

# Просмотр логов в реальном времени
sudo gitlab-ctl tail puma
sudo gitlab-ctl tail sidekiq
sudo gitlab-ctl tail gitaly
```

### Проверка здоровья инстанса

```bash
# Полная проверка здоровья
sudo gitlab-rake gitlab:check SANITIZE=true

# Проверка только критичных компонентов
sudo gitlab-rake gitlab:check SANITIZE=true --skip=uploads,artifacts,builds

# Проверка миграций БД
sudo gitlab-rake gitlab:db:migrate:status

# Проверка целостности репозиториев
sudo gitlab-rake gitlab:git:fsck
```

### Управление бэкапами

```bash
# Список доступных бэкапов
ls -lh /var/opt/gitlab/backups/

# Проверка целостности бэкапа
sudo gitlab-backup list

# Восстановление конкретного бэкапа
sudo gitlab-backup restore BACKUP=1748774401_2026_06_01_19.0.0

# Удаление старых бэкапов
find /var/opt/gitlab/backups -name "*.tar" -mtime +30 -delete
```

### Ротация секретов

```bash
# Ротация всех секретов
sudo gitlab-rake gitlab:secrets:rotate

# Проверка после ротации
sudo gitlab-ctl show-secrets
sudo gitlab-rake gitlab:check SANITIZE=true
```

### Очистка

```bash
# Очистка кэша
sudo gitlab-rake cache:clear

# Очистка старых сессий
sudo gitlab-rake db:sessions:clear

# Очистка старых логов
sudo gitlab-ctl clean-log

# Перестроение индексов PostgreSQL
sudo gitlab-ctl restart postgresql
sudo gitlab-rake gitlab:db:truncate:analytics
```

## Мониторинг инстанса

### Ключевые метрики для instance administration

Мониторьте метрики, отражающие здоровье инстанса как целого:

| Метрика | Описание | Алерт |
|:---|:---|:---|
| `gitlab_rails_queue_duration_seconds` | Задержка обработки Rails-запросов | > 2s |
| `gitlab_sidekiq_jobs_enqueued_total` | Количество задач в очереди Sidekiq | > 10000 |
| `gitlab_sidekiq_jobs_processed_total` | Количество обработанных задач | мониторинг тренда |
| `gitlab_database_connections_count` | Количество соединений с PostgreSQL | > 80% max_connections |
| `gitlab_redis_used_memory_bytes` | Использование памяти Valkey/Redis | > 80% maxmemory |
| `gitlab_gitaly_request_duration_seconds` | Задержка Gitaly-запросов | > 1s (p95) |
| `node_memory_MemAvailable_bytes` | Доступная память на узле | < 10% |
| `node_disk_io_time_weighted_seconds` | Задержка дисковых операций | > 50ms |
| `node_cpu_seconds_total` | Загрузка CPU | > 80% |

### Prometheus-алерты

```yaml
groups:
  - name: gitlab_instance
    rules:
      - alert: GitLabHighLatency
        expr: histogram_quantile(0.95, rate(gitlab_rails_queue_duration_seconds_bucket[5m])) > 2
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "GitLab p95 latency выше 2s"
          description: "Задержка {{ $value }}s на {{ $labels.instance }}"

      - alert: GitLabSidekiqQueueBacklog
        expr: gitlab_sidekiq_jobs_enqueued_total > 10000
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "Sidekiq queue backlog > 10000"
          description: "{{ $value }} задач в очереди. Проверьте производительность БД и Sidekiq."

      - alert: GitLabDatabaseConnectionsHigh
        expr: gitlab_database_connections_count / on(instance) gitlab_database_max_connections > 0.8
        for: 5m
        labels:
          severity: critical
        annotations:
          summary: "PostgreSQL connections > 80%"
          description: "{{ $value | humanizePercentage }} на {{ $labels.instance }}"

      - alert: GitLabGitalyHighLatency
        expr: histogram_quantile(0.95, rate(gitlab_gitaly_request_duration_seconds_bucket[5m])) > 1
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "Gitaly p95 latency выше 1s"
          description: "Задержка Gitaly {{ $value }}s. Проверьте диски и сеть."
```

### Логирование

* **Централизованное логирование:** направляйте логи всех узлов в Elasticsearch/OpenSearch или Loki.
* **Retention:** храните логи минимум 30 дней для операций, 90 дней для compliance.
* **Аудит:** включите audit logging для критичных операций (admin changes, member management, permission changes).
* **Мониторинг логов:** настройте алерты на повторяющиеся ошибки в логах Puma, Sidekiq, PostgreSQL.

## Типичные ошибки и решения

| Симптом | Причина | Решение |
|:---|:---|:---|
| `gitlab-secrets.json` потерян | Нет бэкапа секретов | Восстановите из offsite-копии. Без него восстановление невозможно. |
| 502 Bad Gateway | Puma не отвечает | Проверьте `gitlab-ctl status puma`. Увеличьте `puma['worker_processes']`. |
| 504 Gateway Timeout | Workhorse таймаут | Увеличьте `workhorse['api_queue_duration']` в `gitlab.rb`. |
| Бэкап не восстанавливается | Бэкап повреждён | Регулярно тестируйте restore. Проверяйте sha256sum. |
| Sidekiq queue растёт | Медленная БД или недостаточная параллельность | Увеличьте `sidekiq['max_concurrency']`. Проверьте логи. |
| Gitaly таймауты | Медленный диск | Используйте SSD/NVMe с IOPS > 3000. |
| PostgreSQL connection limit | Исчерпан лимит | Увеличьте `max_connections` или оптимизируйте запросы. |
| Valkey memory overflow | Исчерпан лимит памяти | Увеличьте `maxmemory` или настройте eviction policy. |
| `gitlab:check:repos` не найдена | Устаревшая rake-задача | Используйте `gitlab-rake gitlab:git:fsck`. |
| Обновление падает на миграциях | Несовместимость версий | Откатитесь на предыдущую версию. Проверьте Upgrade Paths. |
| Docker volume не монтируется | Неправильный bind mount | Проверьте SELinux/AppArmor и права на каталог. |
| Helm релиз не обновляется | Невозможный upgrade path | Проверьте `helm history` и compatibility matrix. |
| `gitlab-secrets:check` падает | Повреждённый файл | Восстановите из бэкапа или создайте новый инстанс. |
| Низкая производительность после restore | Неверные права на файлы | Выполните `gitlab-ctl reconfigure` и проверьте ownership. |
| PostgreSQL replication lag | Сетевая задержка или перегрузка | Используйте dedicated VLAN и мониторьте `pg_stat_replication`. |

## Лучшие практики

### Бэкап

* **Регулярность:** автоматический бэкап минимум раз в сутки (cron/systemd timer).
* **Тестирование:** DR drill минимум раз в квартал. Автоматизируйте smoke-проверку после restore.
* **Шифрование:** шифруйте offsite-бэкапы GPG/cosign. Храните оффлайн-ключ отдельно.
* **Ротация:** храните 7–30 последних копий. Удаляйте старые через `find -mtime +N -delete`.
* **Иммутабельность:** WORM/append-only на уровне storage. Подпись бэкапов GPG/cosign.
* **Секреты:** всегда бэкапите `gitlab-secrets.json` отдельно от основного бэкапа. Без него восстановление невозможно.
* **Верификация:** после создания бэкапа проверяйте контрольные суммы и возможность restore в staging.

### Обновление и обслуживание

* Процедуры обновления (standard, ZDU, blue-green, Docker, Helm), maintenance mode и rollback описаны в [Обновление и обслуживание GitLab](./gitlab_upgrades_and_maintenance.md).

### Безопасность

* **gitlab-secrets.json:** защищайте файл (chmod 600, owned root:root). Храните в зашифрованном хранилище.
* **SELinux/AppArmor:** используйте встроенные профили безопасности.
* **Firewall:** ограничьте порты (22/2222 SSH, 80/443 HTTP, 8065/8075 если нужно).
* **Fail2ban:** настройте для защиты от brute-force атак.
* **Обновления:** применяйте security patches своевременно.
* **Аудит:** включите audit logging для критичных операций (admin, member changes, permissions).

### Производительность

* **SSD/NVMe:** обязательны для Gitaly и PostgreSQL.
* **Память:** выделяйте достаточно RAM для Puma, Sidekiq, PostgreSQL shared_buffers.
* **Мониторинг:** настройте алерты на критичные метрики (очередь Sidekiq, задержка Gitaly, соединения PostgreSQL).
* **Сеть:** изолированные подсети для management, application, database, storage. Задержка < 2 ms между компонентами.
* **NTP:** синхронизация времени на всех узлах (разница < 100 ms).

### HA и Disaster Recovery

* **RTO/RPO:** определите целевые показатели для инстанса. RTO < 4h, RPO < 24h для большинства production.
* **DR Drill:** проводите минимум раз в квартал. Документируйте результаты.
* **Multi-site:** для территориально распределённых команд используйте GitLab Geo (read-only зеркала).
* **PostgreSQL HA:** используйте Patroni + Consul для автоматического failover.
* **Valkey HA:** используйте sentinel или cluster mode для высокодоступности кэша.
* **Иммутабельные бэкапы:** WORM/append-only на уровне storage для защиты от ransomware.

## Граничные случаи и ограничения

### Self-Managed vs GitLab.com

| Аспект | Self-Managed | GitLab.com |
|:---|:---|:---|
| Конфигурация gitlab.rb | Полный доступ | Ограничена UI/Settings |
| Rake-задачи | Все доступны | Часть недоступна |
| Бэкап | Ваша ответственность | Встроен (premium) |
| Сеть | Ваша инфраструктура | SaaS |
| SLA | Определяете вы | GitLab SLA |

### Версионные ограничения

* GitLab поддерживает только прямые обновления на одну major-версию. Нельзя обновить с 16.0 на 18.0 напрямую.
* PostgreSQL 17 обязателен для GitLab 19.0+. PostgreSQL 16 и ниже не поддерживаются.
* Valkey 7.2+ или Redis 7.2+ обязательны для GitLab 19.0+. Redis 6 удалён.
* Gitaly Cluster с RAFT в Kubernetes имеет статус beta начиная с GitLab 19.1. Для production используйте VM.

### Смешанные окружения

* **Air-gapped:** требуется локальный registry для GitLab packages и container images. Все обновления скачиваются заранее.
* **Гетерогенная сеть:** между Rails и PostgreSQL/Gitaly/Valkey задержка должна быть < 2 ms. Используйте dedicated VLAN.
* **Гетерогенное хранилище:** для offsite-бэкапов допускаются медленные носители (NAS, tape), но для оперативного восстановления требуются SSD/NVMe.
* **Микросервисная архитектура:** при выносе компонентов на отдельные узлы используйте service discovery (Consul) и circuit breaker.

## Дополнительная информация

### Связанные темы

* **[Архитектура GitLab](../Concepts/gitlab_platform_architecture.md)** — общая архитектура и компоненты
* **[Обновление и обслуживание GitLab](./gitlab_upgrades_and_maintenance.md)** — zero-downtime обновления, blue-green, maintenance
* **[Управление базами данных GitLab](./gitlab_database_management.md)** — PostgreSQL и Valkey/Redis
* **[Администрирование GitLab в масштабе](./gitlab_administration_at_scale.md)** — распределённые архитектуры и масштабирование
* **[Capacity Planning для GitLab CI/CD](./gitlab_capacity_planning.md)** — планирование мощности CI/CD инфраструктуры
* **[Внешняя аутентификация GitLab](./gitlab_external_auth.md)** — LDAP, SAML, OIDC
* **[Мониторинг и метрики GitLab CI/CD](./monitoring_and_metrics.md)** — Prometheus, Grafana, алертинг
* **[Geo: архитектура и эксплуатация](./gitlab_geo_deep_dive.md)** — территориально распределённые инстансы
* **[Gitaly: глубокая диагностика](./gitlab_gitaly_deep_dive.md)** — Git-хранилище, Praefect, RAFT

### Важные замечания

* **Гео-репликация:** для территориально распределённых команд используйте GitLab Geo (read-only зеркала).
* **Gitaly Cluster:** для HA Git-данных используйте Gitaly Cluster с RAFT-репликацией (только на VM, не в Kubernetes).
* **PostgreSQL HA:** используйте Patroni + Consul для автоматического failover.
* **Valkey:** начиная с GitLab 19.0, поддержка Redis 6 удалена. Используйте Valkey 7.2+ или Redis 7.2+.
* **Выбор редакции:** сравните CE и EE в **[Выборе редакции GitLab для production](./gitlab_edition_selection.md)**.
* **Иммутабельные бэкапы:** WORM/append-only на уровне storage защищает от ransomware и случайного удаления.
* **DR Drill:** проводите минимум раз в квартал. Документируйте RTO/RPO и результаты.
* **Обновления:** следуйте официальным путям обновления. Не пропускайте major-версии.
