# Gitaly: глубинное погружение

**Актуально для:** GitLab 17.x–19.x

## Определения

* **Gitaly** — Git RPC-сервис, обеспечивающий доступ к Git-репозиториям в GitLab. Все операции с файловой системой Git проходят через этот слой.
* **gRPC** — высокопроизводительный фреймворк для удалённого вызова процедур (RPC), используемый для взаимодействия компонентов GitLab с Gitaly.
* **Praefect** — прокси-слой для Gitaly Cluster, управляющий маршрутизацией запросов и репликацией.
* **Gitaly Cluster (RAFT)** — архитектура высокой доступности для Git-данных (v17+), использующая протокол консенсуса Raft.
* **Storage (Хранилище)** — логическое имя хранилища в Gitaly, отображающееся на физический путь на диске.
* **Repository (Репозиторий)** — Git-репозиторий, управляемый Gitaly.

## Основные концепции

### Архитектура Gitaly

Gitaly в GitLab состоит из трёх компонентов:

1. **Gitaly Server** — основной сервер, обрабатывающий RPC-запросы.
2. **Praefect** — прокси-слой для Gitaly Cluster (HA-режим).
3. **GitLab Shell** — компонент, обрабатывающий SSH-соединения и взаимодействующий с Gitaly.

### Поток запросов

```
Git Client → GitLab Shell → Praefect (если Cluster) → Gitaly → Disk
                                     ↓
                              Консенсус Raft (если Cluster)
```

### Режимы работы

| Режим | Описание | HA | Kubernetes |
|:---|:---|:---|:---|
| **Single Node** | Один узел Gitaly | Нет | Да |
| **Gitaly Cluster** | Несколько узлов с RAFT | Да | Нет (только VM) |

## Требования и ограничения

### Требования для запуска Gitaly

| Компонент | Требование |
|:---|:---|
| **Лицензия** | GitLab Premium или Ultimate (для Gitaly Cluster) |
| **Версия GitLab** | Одинаковая версия на всех узлах |
| **PostgreSQL** | Отдельный PostgreSQL для Praefect metadata |
| **Сеть** | Низкая задержка между узлами (<2 ms для RAFT) |
| **Диски** | SSD/NVMe с IOPS > 3000 |
| **Память** | 2–4 ГБ RAM на узел Gitaly |
| **NTP** | Синхронизация времени между всеми узлами |

### Ограничения

- **Gitaly Cluster в Kubernetes:** поддерживается только в beta начиная с GitLab 19.1; для production рекомендуется VM
- **Минимальное количество узлов:** 3 для RAFT-консенсуса (1 primary, 2 secondary)
- **Replication factor:** настраивается per virtual storage
- **Consul:** требуется для service discovery в HA-конфигурациях
- **PgBouncer:** рекомендуется для пулинга соединений Praefect → PostgreSQL

## Практические сценарии

### Сценарий 1: Настройка Single Node Gitaly

```ruby
# /etc/gitlab/gitlab.rb

# Включение Gitaly
gitaly['enable'] = true
gitaly['listen_addr'] = '0.0.0.0:8075'
gitaly['prometheus_listen_addr'] = '0.0.0.0:9236'

# Конфигурация хранилища
gitaly['configuration'] = {
  concurrency: [
    { rpc: "/gitaly.SmartHTTPService/PostReceivePack", max_per_repo: 3 },
    { rpc: "/gitaly.SmartHTTPService/PostUploadPack", max_per_repo: 10 }
  ],
  storage: [
    { name: "default", path: "/var/opt/gitlab/git-data/repositories" }
  ]
}

# Применение
sudo gitlab-ctl reconfigure
```

### Сценарий 2: Настройка Gitaly Cluster (RAFT)

```ruby
# /etc/gitlab/gitlab.rb

# Node 1
gitaly['enable'] = true
praefect['enable'] = true
praefect['configuration'] = {
  listen_addr: '0.0.0.0:2305',
  virtual_storage_name: 'default',
  nodes: [
    { host: 'gitaly-1.internal', tcp_address: 'gitaly-1.internal:2305', storage: 'default' },
    { host: 'gitaly-2.internal', tcp_address: 'gitaly-2.internal:2305', storage: 'default' },
    { host: 'gitaly-3.internal', tcp_address: 'gitaly-3.internal:2305', storage: 'default' }
  ],
  auto_create_repositories: true
}

# Применение
sudo gitlab-ctl reconfigure
```

### Сценарий 3: Мониторинг Gitaly

```bash
# 1. Проверка статуса
sudo gitlab-ctl status gitaly

# 2. Просмотр логов
sudo gitlab-ctl tail gitaly

# 3. Проверка метрик Prometheus
curl -s http://localhost:9236/metrics | grep gitaly

# 4. Проверка latency
curl -s http://localhost:9090/api/v1/query?query=gitaly_request_duration_seconds
```

### Сценарий 4: Диагностика проблем производительности

```bash
# 1. Проверка I/O диска
iostat -x 1

# 2. Проверка задержек Gitaly
sudo gitlab-ctl tail gitaly | grep -i "deadline\|timeout\|latency"

# 3. Проверка использования памяти
ps aux | grep gitaly
free -h

# 4. Проверка соединений
sudo gitlab-ctl status gitaly

# 5. Проверка метрик
curl -s http://localhost:9236/metrics | grep gitaly_latency
```

### Сценарий 5: Очистка и обслуживание репозиториев

```bash
# 1. Проверка целостности репозиториев (git fsck)
sudo gitlab-rake gitlab:git:fsck

# 2. Проверка конфигурации Gitaly
sudo gitlab-rake gitlab:gitaly:check

# 3. Очистка неиспользуемых LFS-файлов
sudo gitlab-rake gitlab:cleanup:orphan_lfs_file_references PROJECT_PATH="gitlab-org/gitlab-foss"

# 4. Удаление orphan artifact файлов (только для локального хранилища)
sudo gitlab-rake gitlab:cleanup:orphan_job_artifact_files DRY_RUN=false

# 5. Перестроение индексов (если используется OpenSearch)
# Для OpenSearch индексы перестраиваются через Admin Area → Settings → Monitoring → OpenSearch
# Или через API: curl --request POST --header "PRIVATE-TOKEN: <token>" "https://gitlab.example.com/api/v4/admin/opensearch/reindex"
```

### Сценарий 6: Внешний Gitaly на выделенном сервере

```ruby
# /etc/gitlab/gitlab.rb на GitLab Rails-ноде

# Отключить встроенный Gitaly
gitaly['enable'] = false

# Указать внешний Gitaly
gitlab_rails['gitaly_address'] = 'tcp://gitaly.internal:8075'
gitlab_rails['gitaly_token'] = 'gitaly_auth_token'
```

```ruby
# /etc/gitlab/gitlab.rb на Gitaly-ноде

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
```

```bash
# Применение на обеих нодах
sudo gitlab-ctl reconfigure

# Проверка связи
sudo gitlab-ctl show-config gitaly
git ls-remote https://gitlab.example.com/group/project.git HEAD
```

### Сценарий 7: Gitaly Cluster (Praefect) с PgBouncer и Consul

```ruby
# /etc/gitlab/gitlab.rb на Praefect-ноде

praefect['enable'] = true
praefect['listen_addr'] = '0.0.0.0:2305'
praefect['virtual_storage_name'] = 'default'
praefect['nodes'] = [
  { host: 'praefect-1.internal', tcp_address: 'praefect-1.internal:2305', storage: 'default' },
  { host: 'praefect-2.internal', tcp_address: 'praefect-2.internal:2305', storage: 'default' },
  { host: 'praefect-3.internal', tcp_address: 'praefect-3.internal:2305', storage: 'default' }
]
praefect['auto_create_repositories'] = true

# Praefect требует отдельный PostgreSQL
praefect['database_host'] = 'praefect-postgres.internal'
praefect['database_port'] = 5432
praefect['database_dbname'] = 'praefect'
praefect['database_user'] = 'praefect'
praefect['database_password'] = 'praefect_password'

# PgBouncer для пулинга соединений
praefect['pgbouncer_enabled'] = true
praefect['pgbouncer_port'] = 6432
```

```bash
# Проверка состояния реплик
sudo gitlab-rake "gitlab:praefect:replicas[project_id]"

# Проверка связности между узлами
sudo gitlab-ctl status praefect
sudo gitlab-ctl status gitaly
```

### Валидация

После каждой настройки выполните проверку:

```bash
# 1. Проверка конфигурации Gitaly
sudo gitlab-ctl show-config gitaly

# 2. Проверка статуса сервиса
sudo gitlab-ctl status gitaly

# 3. Проверка подключения к репозиторию
git ls-remote https://gitlab.example.com/group/project.git HEAD

# 4. Проверка метрик Prometheus
curl -s http://localhost:9236/metrics | grep -E "gitaly_pack_objects|gitaly_requests"

# 5. Проверка Praefect (если Cluster)
sudo gitlab-ctl status praefect
sudo gitlab-rake "gitlab:praefect:replicas[project_id]"
```

## Операции и команды

### Управление Gitaly

```bash
# Статус
sudo gitlab-ctl status gitaly

# Запуск/остановка/перезапуск
sudo gitlab-ctl start gitaly
sudo gitlab-ctl stop gitaly
sudo gitlab-ctl restart gitaly

# Просмотр логов
sudo gitlab-ctl tail gitaly
sudo gitlab-ctl tail gitaly --lines 100

# Проверка конфигурации
sudo gitlab-ctl show-config gitaly
```

### Проверка здоровья

```bash
# Полная проверка здоровья
sudo gitlab-rake gitlab:check SANITIZE=true

# Проверка целостности репозиториев (git fsck)
sudo gitlab-rake gitlab:git:fsck

# Проверка Gitaly
sudo gitlab-rake gitlab:gitaly:check
```

### Бэкап Gitaly

```bash
# Бэкап через gitlab-backup (включает репозитории)
sudo gitlab-backup create

# Ручной бэкап Git-репозиториев
sudo tar czf /backup/gitlab-repositories-$(date +%Y%m%d).tar.gz -C /var/opt/gitlab/git-data repositories

# Бэкап через rsync
rsync -avz --progress gitlab.example.com:/var/opt/gitlab/git-data/ /backup/git-data/
```

### Восстановление Gitaly

```bash
# 1. Остановка GitLab
sudo gitlab-ctl stop puma
sudo gitlab-ctl stop sidekiq

# 2. Восстановление репозиториев
sudo tar xzf /backup/gitlab-repositories-20260601.tar.gz -C /var/opt/gitlab/git-data/

# 3. Установка правильных прав
sudo chown -R git:git /var/opt/gitlab/git-data/repositories
sudo chmod -R u+rwX,go-rwx /var/opt/gitlab/git-data/repositories

# 4. Запуск
sudo gitlab-ctl start
```

### Обновление Gitaly

```bash
# Для Gitaly Cluster (Praefect) порядок важен:
# 1. Обновить Gitaly-узлы
sudo apt-get update && sudo apt-get install gitlab-ee

# 2. Проверить состояние
sudo gitlab-ctl status gitaly
sudo gitlab-rake "gitlab:praefect:replicas[project_id]"

# 3. Обновить Praefect-узлы
sudo apt-get update && sudo apt-get install gitlab-ee

# 4. Проверить миграции Praefect
sudo -u git -- /opt/gitlab/embedded/bin/praefect -config /var/opt/gitlab/praefect/config.toml sql-migrate-status

# 5. Запустить Praefect
sudo gitlab-ctl start praefect
```

## Типичные ошибки и решения

| Симптом | Причина | Решение |
|:---|:---|:---|
| `rpc error: code = DeadlineExceeded` | Таймаут Gitaly | Проверьте I/O диска, увеличьте таймауты |
| `Gitaly is unreachable` | Gitaly не отвечает | Проверьте статус: `gitlab-ctl status gitaly` |
| Gitaly OOMKilled | Недостаток памяти | Увеличьте память или уменьшите concurrency |
| Медленные Git-операции | Медленный диск | Используйте SSD/NVMe с IOPS > 3000 |
| Ошибки доступа к репозиторию | Неверные права | Проверьте `chown -R git:git /var/opt/gitlab/git-data` |
| Gitaly Cluster: split brain | Проблемы с сетью | Проверьте связность между узлами |
| `Praefect: repository not found` | Репозиторий не реплицирован | Проверьте `gitlab:praefect:replicas`, убедитесь что репликация завершена |
| `Praefect: primary node down` | Отказ первичного Gitaly узла | RAFT автоматически promotes secondary; проверьте логи Praefect |
| `gitaly_pack_objects_queued` растёт | Превышен лимит concurrency | Увеличьте `max_per_repo` или добавьте узлы |
| `JWT token expired` | Расхождение времени | Настройте NTP на всех узлах |
| `Consul: service not found` | Consul не работает | Проверьте `consul status`, firewall между узлами |

### Диагностические команды

```bash
# Проверка здоровья Gitaly
sudo gitlab-ctl status gitaly
sudo gitlab-rake gitlab:gitaly:check

# Проверка Praefect
sudo gitlab-ctl status praefect
sudo gitlab-rake "gitlab:praefect:replicas[project_id]"

# Проверка метрик Prometheus
curl -s http://localhost:9236/metrics | grep -E "gitaly_pack_objects|gitaly_requests"

# Проверка I/O диска
iostat -x 1

# Проверка задержек сети между узлами
ping -c 10 gitaly-1.internal
mtr --report gitaly-1.internal

# Проверка PostgreSQL репликации (для Praefect)
sudo gitlab-ctl pg-check

# Просмотр логов
sudo gitlab-ctl tail gitaly
sudo gitlab-ctl tail praefect
```

## Лучшие практики

### Производительность

* **SSD/NVMe:** обязательны для Gitaly. HDD приводит к таймаутам.
* **IOPS:** целевое значение > 3000 IOPS.
* **Память:** выделяйте достаточно RAM (обычно 2–4 ГБ на узел).
* **Кэширование:** используйте page cache ОС для часто используемых репозиториев.
* **Concurrency limiting:** настройте `max_per_repo` для высоконагруженных репозиториев.
* **Timeouts:** увеличьте `upload_pack_negotiation` до 10m для больших репозиториев.

### HA и масштабирование

* **Gitaly Cluster:** для production используйте Cluster с RAFT (3+ узла).
* **Правило 3 узлов:** минимальное количество для RAFT-консенсуса.
* **VM:** Gitaly Cluster работает только на виртуальных машинах, не в Kubernetes (кроме beta в 19.1).
* **Virtual Storage:** используйте отдельные virtual storages для разных групп проектов при необходимости.
* **Replication factor:** настройте per storage (2 для стандартных, 3 для критичных).

### Безопасность

* **Изоляция:** размещайте Gitaly в отдельной подсети.
* **Аутентификация:** используйте TLS для RPC-соединений.
* **Auth token:** настройте `auth_token` для Gitaly и `PRAEFECT_INTERNAL_TOKEN`/`PRAEFECT_EXTERNAL_TOKEN` для Praefect.
* **Права доступа:** ограничьте доступ к порту 8075 (Gitaly) и 2305 (Praefect).
* **NTP:** синхронизируйте время на всех узлах для предотвращения JWT-ошибок.
* **Secrets:** храните `gitlab-secrets.json` в защищённом месте; при потере требуется перенастройка кластера.

### Резервное копирование и DR

* **Snapshot-бэкапы:** создавайте снимки всех узлов Gitaly одновременно.
* **Praefect metadata:** бэкап базы данных Praefect отдельно.
* **Тестирование восстановления:** проверяйте restore не реже 1 раза в квартал.
* **Документирование RTO/RPO:** для Gitaly Cluster RPO ≈ 0 (синхронная репликация записей), RTO зависит от автоматического failover.

## Граничные случаи и ограничения

### Self-Managed vs GitLab.com

| Аспект | Self-Managed | GitLab.com |
|:---|:---|:---|
| **Gitaly Cluster** | Да (Premium/Ultimate) | Да (SaaS) |
| **Кастомизация** | Полная | Ограничена |
| **Выделенные диски** | Да | Нет |
| **Consul/PgBouncer** | Да | Нет |

### Версионные ограничения

- Все узлы Gitaly Cluster должны иметь **одинаковую версию GitLab**.
- При обновлении Gitaly Cluster: обновляйте Gitaly узлы первыми, затем Praefect.
- Gitaly Cluster (Praefect) в Kubernetes: beta начиная с 19.1; не рекомендуется для production.
- Elasticsearch deprecated; используется OpenSearch. Не используйте rake-задачи с префиксом `elastic`.

### Смешанные окружения

- **Air-gapped:** предварительно загрузите пакеты GitLab и Gitaly на все узлы.
- **Гетерогенная сеть:** задержка между узлами должна быть <2 ms; при больших задержках используйте Geo вместо Cluster.
- **Разные ОС:** проверяйте compatibility locale для избежания corruption индексов.

## Дополнительная информация

### Связанные темы

* **[Архитектура GitLab](../Concepts/gitlab_platform_architecture.md)** — общая архитектура и компоненты
* **[Управление инстансом GitLab](./gitlab_instance_administration.md)** — бэкап, восстановление, обновление
* **[Управление базами данных GitLab](./gitlab_database_management.md)** — PostgreSQL и Valkey/Redis
* **[Gitaly Documentation](https://docs.gitlab.com/administration/operations/gitaly.html)** — официальная документация

### Мониторинг

Критичные метрики Gitaly (верифицированные):

| Метрика | Тип | Описание | Порог |
|:---|:---|:---|:---|
| `gitaly_pack_objects_served_bytes_total` | Counter | Общий объём данных pack-objects, отданных клиентам | Мониторинг тренда |
| `gitaly_pack_objects_in_progress` | Gauge | Количество параллельных процессов pack-objects | Мониторинг |
| `gitaly_pack_objects_queued` | Gauge | Запросы, ожидающие pack-objects из-за лимита concurrency | Должно быть ≈0 |
| `gitaly_request_duration_seconds` | Histogram | Время обработки RPC-запроса | p95 < 1s |
| `gitaly_connections` | Gauge | Активные соединения | Мониторинг |

**Алерты Prometheus:**
```yaml
groups:
  - name: gitaly
    rules:
      - alert: GitalyHighLatency
        expr: histogram_quantile(0.95, rate(gitaly_request_duration_seconds_bucket[5m])) > 1
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "Gitaly p95 latency выше 1s"
          description: "Задержка Gitaly {{ $value }}s на {{ $labels.instance }}"

      - alert: GitalyPackObjectsQueued
        expr: gitaly_pack_objects_queued > 0
        for: 2m
        labels:
          severity: warning
        annotations:
          summary: "Gitaly: запросы в очереди pack-objects"
          description: "{{ $value }} запросов ожидают обработки. Увеличьте concurrency или добавьте узлы."

      - alert: GitalyDown
        expr: up{job="gitaly"} == 0
        for: 1m
        labels:
          severity: critical
        annotations:
          summary: "Gitaly недоступен"
          description: "Gitaly на {{ $labels.instance }} недоступен более 1 минуты."
```

Для Gitaly Cluster (Praefect) дополнительно мониторьте:
- `praefect_replica_lag_seconds` — задержка репликации
- `praefect_replica_states` — состояние реплик (healthy/unhealthy)
- `praefect_assignments_total` — количество переназначений репозиториев
