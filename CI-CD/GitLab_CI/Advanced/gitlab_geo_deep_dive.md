# GitLab Geo: глубинное погружение

**Актуально для:** GitLab 17.x–19.x (Premium/Ultimate)

## Определения

* **GitLab Geo** — решение для территориально распределенных команд, обеспечивающее read-only зеркала инстанса в разных регионах для ускорения Git-операций и disaster recovery.
* **Primary Node (Primary)** — основной инстанс GitLab, принимающий все write-операции.
* **Secondary Node (Secondary)** — read-only узел Geo, реплицирующий данные с Primary.
* **Push Replication** — репликация данных от Primary к Secondary (асинхронная).
* **Pull Replication** — репликация данных от Secondary к Primary (используется для selective sync).
* **Selective Sync** — механизм, позволяющий Secondary реплицировать только определённые группы/проекты.
* **Geo Log** — внутренний лог, фиксирующий события репликации и ошибки.
* **Geo Sites API** — эндпоинт для управления и мониторинга Geo-нод.
* **Conflict Resolution** — механизм разрешения конфликтов при асинхронной репликации.
* **RPO (Recovery Point Objective)** — максимально допустимая потеря данных при отказе.
* **RTO (Recovery Time Objective)** — максимально допустимое время восстановления.

## Основные концепции

### Архитектура GitLab Geo

GitLab Geo использует асинхронную push-репликацию от Primary к Secondary нодам:

```
[Primary Node (Write)]
    ↓ (Push Replication)
[Secondary Node 1 (Read-Only)] — Регион A
[Secondary Node 2 (Read-Only)] — Регион B
[Secondary Node N (Read-Only)] — Регион N
```

### Компоненты репликации

| Компонент | Описание |
|:---|:---|
| **Git Repositories** | Реплицируются через git push mirror |
| **Database** | PostgreSQL логическая репликация (publications/subscriptions) |
| **Blobs** | LFS-объекты, uploads, artifacts через object storage |
| **Registry** | Container Registry реплицируется отдельно |
| **Search Index** | Elasticsearch/OpenSearch индексы |

### Типы Secondary нод

| Тип | Описание | Использование |
|:---|:---|:---|
| **Read-Only** | Полная репликация всех проектов | Global teams, DR |
| **Selective Sync** | Репликация выборочных групп/projects | Compliance, data residency |
| **Geo Proxy** | Прокси для Git-операций без полной репликации | edge locations |

### Replication Lag

Асинхронная репликация влечёт задержку. Secondary ноды могут отставать от Primary на несколько секунд до минут в зависимости от:
- Объёма данных (репозитории, artifacts)
- Сетевой задержки между регионами
- Нагрузки на Primary
- Конфигурации `geo_repository_sync_buffer_size`

## Практические сценарии

### Сценарий 1: Установка Secondary ноды (Omnibus)

```bash
# 1. Установка GitLab Omnibus
curl -sS https://packages.gitlab.com/install/repositories/gitlab/gitlab-ee/script.deb.sh | sudo bash
sudo EXTERNAL_URL="https://geo-secondary.example.com" apt-get install gitlab-ee

# 2. Настройка Geo в /etc/gitlab/gitlab.rb
gitlab_rails['geo_node_name'] = 'Secondary US-East'
gitlab_rails['geo_node_primary_node_url'] = 'https://gitlab-primary.example.com'

# 3. Включение репликации репозиториев
gitlab_rails['gitlab_geo_repository_sync_buffer_size'] = 10_000

# 4. Настройка PostgreSQL для логической репликации
postgresql['logical_replication'] = true
postgresql['max_replication_slots'] = 10
postgresql['max_wal_senders'] = 10

# 5. Применение конфигурации
sudo gitlab-ctl reconfigure

# 6. Авторизация Secondary на Primary
# Выполняется на Primary через Admin Area → Geo → Add a secondary node
```

### Сценарий 2: Настройка Selective Sync

```ruby
# /etc/gitlab/gitlab.rb на Secondary

# Реплицировать только определённые группы
gitlab_rails['geo_repository_sync_enabled'] = true
gitlab_rails['geo_repository_sync_group_ids'] = [1, 2, 3]  # ID групп для репликации
gitlab_rails['geo_repository_sync_project_ids'] = []       # Или конкретные проекты

# Исключить чувствительные группы
gitlab_rails['geo_repository_sync_excluded_group_ids'] = [999]

# Применение
sudo gitlab-ctl reconfigure
```

### Сценарий 3: Мониторинг репликации

```bash
# 1. Проверка статуса Geo через API
curl --header "PRIVATE-TOKEN: <token>" \
  "https://gitlab.example.com/api/v4/geo/nodes"

# 2. Проверка логов репликации
sudo gitlab-ctl tail geo-logcursor

# 3. Комплексная проверка здоровья Geo-нод
sudo gitlab-rake gitlab:geo:check

# 4. Проверка статуса синхронизации
sudo gitlab-rake gitlab:geo:status

# 5. Просмотр ошибок репликации
curl --header "PRIVATE-TOKEN: <token>" \
  "https://gitlab.example.com/api/v4/geo/nodes/1/status"
```

### Сценарий 4: Failover и Disaster Recovery

```bash
# На Secondary (если Primary недоступен):

# 1. Перевод Secondary в primary (promote)
# ВНИМАНИЕ: Это действие необратимо без восстановления из бэкапа
sudo gitlab-ctl geo promote

# 2. Обновление URL нового primary
sudo gitlab-rake geo:update_primary_node_url

# 3. Обновление DNS для перенаправления трафика
# Измените A/AAAA записи для gitlab.example.com на IP нового primary

# 4. Проверка работоспособности после failover
sudo gitlab-rake gitlab:check
sudo gitlab-rake gitlab:geo:check

# На бывшем Primary (после восстановления):
# 1. Настройка как Secondary
# 2. Репликация данных с нового Primary
```

### Сценарий 6: Настройка Helm chart для Geo Secondary

```yaml
# values.yaml для Geo Secondary сайта

global:
  appConfig:
    geo:
      enabled: true
      node_name: 'Secondary US-East'
      primary_node_url: 'https://gitlab-primary.example.com'

  # Внешний URL secondary сайта
  host: geo-secondary.example.com

# Для Geo требуется внешний PostgreSQL с поддержкой логической репликации
postgresql:
  enabled: false

  # Подключение к внешнему PostgreSQL
  postgresql:
    host: 'postgres-primary.example.com'
    port: 5432
    database: 'gitlab'
    username: 'gitlab'
    password:
      secret: gitlab-geo-secrets
      key: postgresql-password

# Настройка репликации репозиториев
gitlab:
  geo:
    repository_sync_buffer_size: 10000
```

```bash
# Установка Geo Secondary через Helm
helm upgrade --install gitlab-geo gitlab/gitlab \
  -f values.yaml \
  --namespace gitlab-geo \
  --create-namespace

# Проверка статуса после установки
kubectl exec -it -n gitlab-geo $(kubectl get pods -n gitlab-geo -l app=webservice -o jsonpath='{.items[0].metadata.name}') -- sudo gitlab-rake gitlab:geo:check
```

### Сценарий 7: Настройка Object Storage для Geo

```ruby
# /etc/gitlab/gitlab.rb на Primary и Secondary

# Object Storage должен быть доступен с обоих сайтов
gitlab_rails['object_store']['enabled'] = true
gitlab_rails['object_store']['connection'] = {
  'provider' => 'AWS',
  'region' => 'us-east-1',
  'endpoint' => 'https://s3.example.com',
  'access_key_id' => 'ACCESS_KEY',
  'secret_access_key' => 'SECRET_KEY'
}

# LFS объекты
gitlab_rails['lfs_object_store_enabled'] = true
gitlab_rails['lfs_object_store_remote_directory'] = 'gitlab-lfs'

# Uploads
gitlab_rails['uploads_object_store_enabled'] = true
gitlab_rails['uploads_object_store_remote_directory'] = 'gitlab-uploads'

# Artifacts
gitlab_rails['artifacts_object_store_enabled'] = true
gitlab_rails['artifacts_object_store_remote_directory'] = 'gitlab-artifacts'

# Packages
gitlab_rails['packages_object_store_enabled'] = true
gitlab_rails['packages_object_store_remote_directory'] = 'gitlab-packages'

# Application cache (если используется S3)
gitlab_rails['object_store']['object_store_credential_path'] = '/etc/gitlab/object_store_credentials.json'
```

```bash
# Применение конфигурации
sudo gitlab-ctl reconfigure

# Проверка доступности Object Storage
sudo gitlab-rake gitlab:check
```

## Требования и ограничения

### Требования для запуска Geo

| Компонент | Требование |
|:---|:---|
| **Лицензия** | GitLab Premium или Ultimate |
| **Версия GitLab** | Одинаковая версия на Primary и Secondary |
| **PostgreSQL** | Версия с поддержкой логической репликации (10+) |
| **Сеть** | HTTPS между сайтами, PostgreSQL порт 5432 для репликации |
| **DNS** | Уникальные внешние URL для каждого сайта |
| **Object Storage** | Общий endpoint для LFS, uploads, artifacts, packages |
| **Registry** | Для Container Registry требуется отдельный PostgreSQL |

### Ограничения

- **Self-compiled installations:** Geo не поддерживается в сборках из исходников
- **Container Registry:** требует отдельный внешний PostgreSQL на каждом сайте
- **Replication lag:** асинхронная репликация, данные могут отставать на секунды-минуты
- **Read-only:** Secondary сайты полностью read-only, включая API и UI
- **Geo Proxy:** прозрачный прокси для write-операций, кроме Git fetch

## Устранение неполадок

### Типичные ошибки

| Ошибка | Причина | Решение |
|:---|:---|:---|
| `Geo node not found` | `geo_node_name` не настроен или не совпадает с записью в БД | Проверить `gitlab_rails['geo_node_name']` и запустить `gitlab-ctl reconfigure` |
| `Replication lag too high` | Недостаточная пропускная способность или высокая нагрузка | Увеличить `geo_repository_sync_buffer_size`, проверить сеть |
| `PostgreSQL replication broken` | Несовместимые версии PostgreSQL или проблемы с сетью | Проверить версии PostgreSQL, доступность порта 5432 |
| `Object Storage sync failed` | Неправильные credentials или недоступный endpoint | Проверить connectivity, IAM права, версионирование bucket |
| `Geo Log Cursor stopped` | Ошибка в событии репликации | Проверить `/var/log/gitlab/geo/geo.log`, перезапустить `geo-logcursor` |
| `JWT token expired` | Расхождение времени между сайтами | Настроить NTP синхронизацию |

### Диагностические команды

```bash
# Проверка здоровья Geo
sudo gitlab-rake gitlab:geo:check

# Проверка синхронизации
sudo gitlab-rake gitlab:geo:status

# Проверка PostgreSQL репликации на Secondary
sudo gitlab-ctl pg-check

# Проверка логов Geo Log Cursor
sudo gitlab-ctl tail geo-logcursor

# Проверка connectivity между сайтами
curl -I https://gitlab-primary.example.com/-/health
```

## Лучшие практики

### Мониторинг и наблюдаемость

```bash
# Включение Geo-специфичных метрик Prometheus
# Метрики доступны на /metrics endpoint

# Ключевые метрики для мониторинга:
# - gitlab_geo_repositories_sync_duration_seconds
# - gitlab_geo_repositories_sync_failed_total
# - gitlab_geo_repositories_sync_successful_total
# - gitlab_geo_db_replication_lag_seconds
# - geo_log_cursor_batch_size
```

**Алерты Prometheus:**
```yaml
# Высокая задержка репликации
- alert: GeoReplicationLagHigh
  expr: gitlab_geo_repositories_sync_duration_seconds > 300
  for: 5m

# Ошибки репликации репозиториев
- alert: GeoRepositorySyncFailed
  expr: rate(gitlab_geo_repositories_sync_failed_total[5m]) > 0

# Остановка Geo Log Cursor
- alert: GeoLogCursorStopped
  expr: absent(geo_log_cursor_batch_size)
```

### Резервное копирование и DR

- Регулярное тестирование процесса promote secondary → primary
- Резервное копирование `gitlab-secrets.json` на каждом сайте
- Документирование процедуры failover с указанием RTO/RPO
- Тестирование сценариев восстановления не реже 1 раза в квартал

### Сеть и безопасность

- Использовать private network/VPC peering для PostgreSQL репликации
- Никогда не exposing PostgreSQL порты в интернет
- Включить TLS между сайтами
- Разграничить доступ к Admin Area только на Primary сайте

## Граничные случаи и ограничения

### Self-Managed vs GitLab.com

| Аспект | Self-Managed | GitLab.com |
|:---|:---|:---|
| **Geo поддержка** | Да (Premium/Ultimate) | Нет |
| **Количество Secondary** | До 200 | N/A |
| **Selective Sync** | Да | Нет |
| **Geo Proxy** | Да | Нет |
| **Custom домены** | Да | Ограничено |

### Версионные ограничения

- Все сайты в Geo deployment должны иметь **одинаковую версию GitLab**
- При обновлении используйте Rolling Upgrade: обновляйте Secondary первыми, затем Primary
- После promote Secondary → Primary проверьте версию перед продолжением

### Смешанные окружения

- **Air-gapped:** требуется предварительная загрузка пакетов и Docker images на все сайты
- **Разные ОС:** проверяйте compatibility locale данных для избежания corruption индексов
- **Гетерогенная сеть:** учтите задержки при capacity planning

## Дополнительная информация

### См. также

* **[Архитектура GitLab](../../Concepts/gitlab_platform_architecture.md)** — общая архитектура инстанса
* **[Администрирование GitLab](../../Advanced/gitlab_instance_administration.md)** — бэкапы, обновления, HA
* **[Мониторинг и метрики](../../Advanced/monitoring_and_metrics.md)** — Prometheus-метрики для Geo
* **[Управление базой данных](../../Advanced/gitlab_database_management.md)** — PostgreSQL логическая репликация
* **[Capacity Planning](../../Advanced/gitlab_capacity_planning.md)** — планирование ресурсов для Geo

### Внешние ресурсы

* [GitLab Geo Documentation](https://docs.gitlab.com/ee/administration/geo/)
* [GitLab Geo Architecture](https://docs.gitlab.com/ee/administration/geo/reference_architectures.html)
* [GitLab Geo Monitoring](https://docs.gitlab.com/ee/administration/geo/monitor.html)
* [GitLab Geo Disaster Recovery](https://docs.gitlab.com/ee/administration/geo/disaster_recovery.html)
