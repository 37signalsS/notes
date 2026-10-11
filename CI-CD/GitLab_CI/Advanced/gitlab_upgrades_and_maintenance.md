# Обновление и обслуживание GitLab

**Актуально для:** GitLab 17.x–19.x (Omnibus, Docker, Helm)

## Определения

* **Zero-Downtime Upgrade (ZDU)** — обновление инстанса GitLab без остановки обслуживания пользователей. Достигается за счёт поочерёдного вывода Rails-нод в maintenance mode или blue-green деплоя.
* **Blue-Green Deployment** — стратегия развёртывания, при которой параллельно работают две версии инстанса (старая и новая), а трафик переключается атомарно.
* **Maintenance Mode (Режим обслуживания)** — состояние, при котором GitLab отклоняет входящие запросы, позволяя выполнять операции без риска повреждения данных.
* **Upgrade Path (Путь обновления)** — последовательность версий, разрешённая для обновления. GitLab поддерживает только прямые обновления на одну major-версию.
* **Rolling Upgrade** — поэтапное обновление узлов в кластере без остановки всего сервиса.
* **Canary Upgrade** — обновление небольшой части инфраструктуры для проверки совместимости перед массовым rollout.
* **Patch Version** — версия вида `X.Y.Z`, где `Z` исправляет баги и security issues без изменения API.
* **Major Version** — версия вида `X.0`, содержащая breaking changes и новые функции.
* **DR Drill (Тренировка восстановления)** — плановое упражнение по восстановлению инстанса из бэкапа в изолированной среде.
* **RTO/RPO** — Recovery Time Objective (максимальное время простоя) и Recovery Point Objective (максимальная потеря данных).

## Предварительные требования

### Железо и ОС

| Компонент | Требование |
|:---|:---|
| CPU | 4+ vCPU (рекомендуется 8+ для production HA). |
| RAM | 16+ ГБ (рекомендуется 32+ ГБ). |
| Диск | 50+ ГБ SSD для `/var/opt/gitlab`. Логи в `/var/log/gitlab/`. |
| ОС | Linux с systemd (Rocky Linux 9, AlmaLinux 9, Ubuntu 22.04/24.04 LTS). |

### Программное обеспечение

| Компонент | Версия | Примечание |
|:---|:---|:---|
| GitLab | 17.x–19.x | Omnibus, Docker или Helm |
| PostgreSQL | 15+ (GitLab 18.x), 17+ (GitLab 19.0) | HA требует Patroni + Consul |
| Valkey/Redis | Valkey 7.2+ или Redis 7.2+ | Redis 6 удалён в GitLab 19.0 |

### Сеть

| Порт/Протокол | Назначение |
|:---|:---|
| 80/443 | HTTP/HTTPS |
| 2222 | SSH (Git over SSH) |
| 6379 | Valkey/Redis |
| 5432 | PostgreSQL |
| 8080 | Health-check сервер (readiness/liveness) |
| 9090 | Prometheus (опционально) |

### Права

Требуется доступ `root` или `sudo` для управления сервисами и применения `gitlab-ctl reconfigure`. Для API-вызовов необходим токен администратора (`PRIVATE-TOKEN` с правами `api` и `admin`).

## Основные концепции

### Жизненный цикл обновления GitLab

Управление жизненным циклом GitLab следует циклическому процессу:

1. **Планирование** — выбор версии, проверка compatibility matrix, оценка рисков, определение maintenance window.
2. **Бэкап** — создание полной резервной копии всех критичных данных, включая `gitlab-secrets.json`.
3. **Тестирование** — проверка обновления в staging-окружении.
4. **Обновление** — применение обновления в production.
5. **Валидация** — проверка работоспособности после обновления.
6. **Мониторинг** — наблюдение за метриками в течение 24–72 часов.

### Совместимость версий

GitLab имеет строгие правила обновления:

* **Patch-обновления** (`X.Y.Z` → `X.Y.Z+1`) — разрешены без ограничений.
* **Minor-обновления** (`X.Y` → `X.Y+1`) — разрешены, если промежуточные версии не пропущены.
* **Major-обновления** (`X` → `X+1`) — требуют прохождения через все intermediate версии.
* **Пропуск версий** — не поддерживается. Нельзя обновить с 16.0 на 18.0 напрямую.

### Стратегии обновления

| Стратегия | Downtime | Риск | Применение |
|:---|:---|:---|:---|
| **Standard Upgrade** | Да (минимальный) | Средний | Single Node, <1000 пользователей |
| **Zero-Downtime Upgrade** | Нет | Средний | HA, production с strict SLA |
| **Blue-Green Upgrade** | Нет | Низкий | Enterprise, critical workloads |
| **Canary Upgrade** | Нет | Низкий | Large scale, >5000 пользователей |
| **Rolling Upgrade** | Нет | Средний | Distributed, Kubernetes |

### Изменения в версиях GitLab 17.x–19.x

| Версия | Критические изменения |
|:---|:---|
| **17.0** | Минимальная версия PostgreSQL повышена до 15. Gitaly Cluster (RAFT) становится GA. |
| **17.3** | Введение GitLab CI/CD Components Catalog (GA). |
| **18.0** | Удаление legacy-интеграций Kubernetes на базе сертификатов. Обязательное использование GitLab Agent (KAS). |
| **18.11** | Миграция на ClickHouse для аналитики (опционально). |
| **19.0** | Минимальная версия PostgreSQL повышена до 17. Поддержка Redis 6 удалена; Valkey 7.2+ или Redis 7.2+ обязательны. Envoy Gateway становится стандартом для Helm Chart. |

## Практические сценарии

### Сценарий 1: Стандартное обновление (Single Node)

```bash
# 1. Проверка текущей версии и окружения
sudo gitlab-rake gitlab:env:info
sudo gitlab-ctl status

# 2. Проверка доступных обновлений
sudo apt update  # Debian/Ubuntu
# ИЛИ
sudo yum check-update  # RHEL/CentOS

# 3. Создание полного бэкапа
sudo gitlab-backup create CRON=1
sudo cp /etc/gitlab/gitlab-secrets.json /backup/secrets-$(date +%Y%m%d).json

# 4. Проверка совместимости
# - PostgreSQL версия
sudo gitlab-psql -c "SELECT version();"
# - Valkey/Redis версия
sudo gitlab-redis-cli INFO server | grep redis_version

# 5. Обновление пакетов
sudo apt install gitlab-ce  # Debian/Ubuntu
# ИЛИ
sudo yum install gitlab-ce  # RHEL/CentOS

# 6. Выполнение миграций и применение конфигурации
sudo gitlab-ctl reconfigure

# 7. Проверка статуса
sudo gitlab-ctl status
sudo gitlab-rake gitlab:check SANITIZE=true

# 8. Мониторинг в течение 24 часов
sudo gitlab-ctl tail
```

**Валидация:**
- `gitlab-ctl status` показывает все сервисы в состоянии `run`.
- `gitlab-rake gitlab:check SANITIZE=true` завершается с `Check complete: passed`.
- API `/-/ready` возвращает HTTP `200`.
- Нет ошибок в логах Puma, Sidekiq, PostgreSQL в течение 1 часа.

### Сценарий 2: Zero-Downtime Upgrade (HA)

```bash
# 1. Подготовка
# - Убедиться, что балансировщик настроен на graceful drain
# - Проверить, что все компоненты в состоянии healthy
sudo gitlab-ctl status
curl -s http://localhost:8080/-/ready

# 2. Бэкап
sudo gitlab-backup create CRON=1
sudo cp /etc/gitlab/gitlab-secrets.json /backup/secrets-$(date +%Y%m%d).json

# 3. Перевод Rails-нод в режим обслуживания поочерёдно
# На каждой Rails-ноде:
sudo gitlab-rake gitlab:maintenance:on

# 4. Обновление ноды
sudo apt install gitlab-ce
sudo gitlab-ctl reconfigure

# 5. Проверка ноды
sudo gitlab-ctl status
sudo gitlab-rake gitlab:check SANITIZE=true

# 6. Вывод из режима обслуживания
sudo gitlab-rake gitlab:maintenance:off

# 7. Повторить для следующей ноды
# Важно: обновлять ноды последовательно, а не одновременно

# 8. Проверка всего кластера
curl -s http://gitlab.example.com/-/ready
curl -s http://gitlab.example.com/-/health
```

**Валидация:**
- Каждая нода возвращает HTTP `200` на `/-/ready` после вывода из maintenance mode.
- Балансировщик распределяет трафик без ошибок 502/503.
- Пользователи не отмечают прерываний сервиса.

### Сценарий 3: Blue-Green Upgrade

```bash
# 1. Подготовка green-окружения
# - Развертывание новой версии GitLab на отдельном хосте/кластере
# - Настройка раздельного балансировщика или DNS

# 2. Синхронизация данных
# - Репликация БД (PostgreSQL streaming replication)
# - Репликация репозиториев (Gitaly Cluster или rsync)
# - Синхронизация LFS-объектов и артефактов

# 3. Проверка green-окружения
curl -s http://gitlab-green.example.com/-/ready
sudo gitlab-rake gitlab:check SANITIZE=true

# 4. Переключение трафика
# - Обновление DNS (снижение TTL до 60s перед началом)
# - Или переключение балансировщика

# 5. Мониторинг green-окружения
# - Проверка метрик Puma, Sidekiq, Gitaly
# - Проверка очередей Sidekiq
# - Проверка задержек Git-операций

# 6. Отключение blue-окружения (после stabilisation period)
# - Оставить blue в hot-standby на 24–48 часов
# - После успешной валидации — остановка blue
```

**Валидация:**
- Green-окружение возвращает HTTP `200` на readiness endpoint.
- Все пользовательские операции (CI/CD, MR, issues) работают корректно.
- Метрики Sidekiq и Gitaly в пределах нормы.

### Сценарий 4: Обновление Docker-инстанса

```bash
# 1. Остановка контейнера
docker stop gitlab

# 2. Бэкап volumes
docker run --rm \
  -v gitlab_config:/source \
  -v /backup:/backup \
  alpine tar czf /backup/gitlab-config.tar.gz -C /source .

docker run --rm \
  -v gitlab_data:/source \
  -v /backup:/backup \
  alpine tar czf /backup/gitlab-data.tar.gz -C /source .

# 3. Обновление образа
docker pull gitlab/gitlab-ce:19.0.0

# 4. Запуск с новой версией
docker run -d \
  --hostname gitlab.example.com \
  --env GITLAB_OMNIBUS_CONFIG="..." \
  -p 443:443 -p 80:80 -p 2222:22 \
  --volume /srv/gitlab/config:/etc/gitlab \
  --volume /srv/gitlab/logs:/var/log/gitlab \
  --volume /srv/gitlab/data:/var/opt/gitlab \
  --restart always \
  --name gitlab \
  gitlab/gitlab-ce:19.0.0

# 5. Проверка
docker logs gitlab
curl http://localhost:8080/-/ready
```

**Валидация:**
- Контейнер запущен: `docker ps | grep gitlab`.
- Логи `/var/log/gitlab` содержат `gitlab Reconfigured!` и `Starting Puma`.
- `/-/ready` возвращает HTTP `200`.

### Сценарий 5: Обновление Helm-инсталляции (Kubernetes)

```bash
# 1. Бэкап
kubectl get secret gitlab-secrets -o yaml > /backup/gitlab-secrets-$(date +%Y%m%d).yaml
kubectl exec -it gitlab-postgresql-0 -- pg_dump -U postgres gitlabhq_production > /backup/gitlab-db-$(date +%Y%m%d).sql

# 2. Обновление Helm-релиза
helm repo update gitlab
helm upgrade gitlab gitlab/gitlab \
  --values values.yaml \
  --version 7.0.0 \
  --namespace gitlab

# 3. Мониторинг rollout
kubectl rollout status deployment/gitlab-webservice-default -n gitlab
kubectl rollout status statefulset/gitlab-postgresql -n gitlab
kubectl rollout status statefulset/gitlab-redis -n gitlab

# 4. Проверка
kubectl get pods -n gitlab
kubectl exec -it gitlab-webservice-default-0 -- curl -s http://localhost:8080/-/ready
```

**Валидация:**
- Все pods в статусе `Running` и `Ready`.
- Helm-релиз обновлён: `helm list -n gitlab`.
- `/-/ready` возвращает HTTP `200`.

### Сценарий 6: Обновление GitLab Runner

```bash
# 1. Проверка текущей версии
gitlab-runner --version

# 2. Остановка Runner
sudo gitlab-runner stop

# 3. Обновление пакета
sudo apt install gitlab-runner  # Debian/Ubuntu
# ИЛИ
sudo yum install gitlab-runner  # RHEL/CentOS

# 4. Запуск Runner
sudo gitlab-runner start

# 5. Проверка
sudo gitlab-runner verify
gitlab-runner --version
```

**Валидация:**
- `gitlab-runner verify` показывает всех Runner'ов в статусе `online`.
- Runner виден в Admin Area → CI/CD → Runners.

### Сценарий 7: Откат после неудачного обновления

```bash
# 1. Остановка сервисов
sudo gitlab-ctl stop puma
sudo gitlab-ctl stop sidekiq

# 2. Восстановление предыдущей конфигурации
sudo cp /backup/gitlab-config-20260601.rb /etc/gitlab/gitlab.rb
sudo cp /backup/gitlab-secrets-20260601.json /etc/gitlab/gitlab-secrets.json

# 3. Откат пакетов (Debian/Ubuntu)
sudo apt install gitlab-ce=19.0.0-previous

# 4. Применение конфигурации
sudo gitlab-ctl reconfigure

# 5. Восстановление БД из бэкапа (если миграции сломаны)
sudo gitlab-ctl stop postgresql
sudo gitlab-ctl start postgresql
sudo gitlab-backup restore BACKUP=1748774401_2026_06_01_19.0.0

# 6. Запуск
sudo gitlab-ctl start

# 7. Проверка
sudo gitlab-ctl status
sudo gitlab-rake gitlab:check SANITIZE=true
```

**Валидация:**
- Старая версия запущена: `gitlab-rake gitlab:env:info | grep "Current Version"`.
- Все сервисы в состоянии `run`.
- Данные целостны: проверка нескольких проектов и репозиториев.

### Сценарий 8: Maintenance Mode и Rolling Upgrade в HA

```bash
# 1. Создание maintenance window
# - Уведомить пользователей за 24 часа
# - Запланировать в нерабочее время
# - Подготовить бэкап

# 2. Бэкап
sudo gitlab-backup create CRON=1
sudo cp /etc/gitlab/gitlab-secrets.json /backup/secrets-$(date +%Y%m%d).json

# 3. Перевод в режим обслуживания на одной ноде
sudo gitlab-rake gitlab:maintenance:on

# 4. Обновление ноды
sudo apt install gitlab-ce
sudo gitlab-ctl reconfigure

# 5. Проверка ноды
sudo gitlab-ctl status
sudo gitlab-rake gitlab:check SANITIZE=true

# 6. Вывод из режима обслуживания
sudo gitlab-rake gitlab:maintenance:off

# 7. Повторить для следующей ноды
# Важно: обновлять ноды последовательно, а не одновременно
```

**Валидация:**
- При включённом maintenance mode API возвращает HTTP `503`.
- После вывода из режима нода возвращает HTTP `200` на `/-/ready`.
- Общая производительность кластера не страдает.

## Операции и команды

### Проверка статуса и здоровья

```bash
# Общий статус компонентов
sudo gitlab-ctl status

# Проверка здоровья
sudo gitlab-rake gitlab:check SANITIZE=true

# Проверка миграций БД
sudo gitlab-rake gitlab:db:migrate:status

# Проверка целостности репозиториев
sudo gitlab-rake gitlab:git:fsck

# Проверка готовности
curl -s http://localhost:8080/-/ready
curl -s http://localhost:8080/-/health
```

### Управление режимом обслуживания

```bash
# Включение режима обслуживания
sudo gitlab-rake gitlab:maintenance:on

# Проверка
curl -I https://gitlab.example.com/users/sign_in
# → HTTP/2 503

# Выключение режима обслуживания
sudo gitlab-rake gitlab:maintenance:off
```

### Управление бэкапами

```bash
# Полный бэкап
sudo gitlab-backup create CRON=1

# Выборочный бэкап
sudo gitlab-backup create SKIP=tar,repositories,uploads,builds,artifacts,pages,lfs,terraform_state,registry,packages,ci_secure_files,agent_plan_content,external_diffs

# Список бэкапов
sudo gitlab-backup list

# Восстановление
sudo gitlab-ctl stop puma
sudo gitlab-ctl stop sidekiq
sudo gitlab-backup restore BACKUP=1748774401_2026_06_01_19.0.0
sudo gitlab-ctl start
```

## Типичные ошибки и решения

| Симптом | Причина | Решение | Диагностика |
|:---|:---|:---|:---|
| `409 Conflict` при обновлении | Миграции БД ещё выполняются | Дождитесь завершения миграций, проверьте `gitlab-ctl status` | Логи PostgreSQL, `gitlab-rake gitlab:db:migrate:status` |
| `PG::ConnectionBad` | PostgreSQL не отвечает | Проверьте статус: `gitlab-ctl status postgresql` | `gitlab-ctl tail postgresql --since 1h` |
| Sidekiq queue растёт после обновления | Долгие миграции или индексы | Проверьте логи Sidekiq, убедитесь что миграции завершены | `gitlab-rake sidekiq:queues` |
| 502 Bad Gateway | Puma не отвечает | Проверьте `gitlab-ctl status puma`, увеличьте `puma['worker_processes']` | `gitlab-ctl tail puma --since 1h` |
| Gitaly таймауты | Медленный диск | Используйте SSD/NVMe с IOPS > 3000 | `gitlab-ctl tail gitaly --since 1h` |
| Бэкап не восстанавливается | Бэкап повреждён | Регулярно тестируйте restore, проверяйте sha256sum | `gitlab-backup list` |
| Valkey memory overflow | Исчерпан лимит памяти | Увеличьте `maxmemory` или настройте eviction policy | `gitlab-redis-cli INFO memory` |
| Maintenance mode не отключается | Блокировка в БД или зависший процесс | Проверьте `gitlab-ctl status`, при необходимости перезапустите Puma | `gitlab-rails runner` для проверки состояния |
| Helm релиз не обновляется | Невозможный upgrade path | Проверьте `helm history` и compatibility matrix | `helm history gitlab -n gitlab` |
| Docker volume не монтируется | Неправильный bind mount | Проверьте SELinux/AppArmor и права на каталог | `docker inspect gitlab` |
| Обновление падает на миграциях | Несовместимость версий | Откатитесь на предыдущую версию. Проверьте Upgrade Paths | Логи `/var/log/gitlab/migration` |

## Лучшие практики

### Планирование обновлений

* **Upgrade Path:** строго следуйте официальным путям обновления. Не пропускайте major-версии.
* **Staging:** всегда тестируйте обновление в staging-окружении перед production.
* **Бэкап:** создавайте полный бэкап перед каждым обновлением.
* **Совместимость:** проверьте PostgreSQL, Valkey/Redis и ОС-пакеты перед обновлением.
* **Change Management:** все production-обновления через maintenance window с утверждением.
* **Rollback plan:** имейте готовый план отката и протестируйте его в staging.

### Zero-Downtime обновления

* **Sequential update:** обновляйте Rails-ноды последовательно, а не одновременно.
* **Health checks:** убедитесь, что нода healthy перед выводом из обслуживания.
* **Graceful drain:** настройте балансировщик на graceful drain перед обновлением.
* **Monitoring:** наблюдайте за метриками после вывода каждой ноды.

### Blue-Green deployments

* **Data sync:** убедитесь, что БД и репозитории синхронизированы перед переключением.
* **DNS TTL:** снизьте TTL до 60s за 24 часа до обновления.
* **Hot standby:** оставляйте blue-окружение в hot-standby на 24–48 часов.
* **Rollback plan:** имейте готовый план отката на blue-окружение.

### Мониторинг после обновления

* **24-hour watch:** наблюдайте за метриками минимум 24 часа после обновления.
* **Key metrics:** Puma latency, Sidekiq queue size, Gitaly latency, PostgreSQL connections.
* **Logs:** мониторьте логи на ошибки и предупреждения.
* **User feedback:** отслеживайте репорты пользователей о необычном поведении.

### Бэкап и восстановление

* **3-2-1 strategy:** 3 копии, 2 носителя, 1 offsite.
* **Regular testing:** DR drill минимум раз в квартал.
* **Encryption:** шифруйте offsite-бэкапы GPG/cosign.
* **Immutable backups:** WORM/append-only на уровне storage.
* **Secrets backup:** всегда бэкапите `gitlab-secrets.json` отдельно.

### Восстановление (Cleanup)

```bash
# Откат изменений конфигурации
sudo cp /etc/gitlab/gitlab.rb.bak /etc/gitlab/gitlab.rb
sudo cp /backup/gitlab-secrets-20260601.json /etc/gitlab/gitlab-secrets.json
sudo gitlab-ctl reconfigure
sudo gitlab-ctl restart sidekiq
sudo gitlab-ctl restart puma

# Если нужно откатить пакет
sudo apt install gitlab-ce=<предыдущая_версия>
sudo gitlab-ctl reconfigure
```

## Пограничные случаи

### Высоконагруженные инстансы (>10 000 пользователей)

* Используйте Blue-Green или Canary стратегию вместо прямого обновления.
* Настройте maintenance window длительностью не более 30 минут на ноду.
* Используйте внешний балансировщик с health checks.
* Мониторьте метрики Sidekiq, Gitaly и PostgreSQL в реальном времени.

### Ограничения соединений PostgreSQL

PostgreSQL может исчерпать лимит соединений во время миграций. Используйте PgBouncer:

```ruby
# /etc/gitlab/gitlab.rb
postgresql['max_connections'] = 200
pgbouncer['enable'] = true
pgbouncer['port'] = 6432
```

### Проблемы с памятью Ruby

Ruby GC может работать inefficiently при большом количестве потоков. Рекомендации:
* Используйте `RUBY_GC_HEAP_GROWTH_FACTOR` для настройки роста кучи.
* Ограничьте `concurrency` до 25 на процесс при RAM < 32 ГБ.
* Включите `sidekiq['memory_killer']` для предотвращения OOM Killer ядра.

### Резкое наполнение очередей после рестарта

При рестарте Sidekiq все запланированные задачи (Scheduled Set) могут одновременно попасть в очереди. Для смягчения:
* Используйте `sidekiq['interval'] = 5` для уменьшения интервала поллинга scheduled jobs.
* Убедитесь, что количество процессов после рестарта соответствует `queue_groups`.

### Air-gapped окружения

* Загрузите все пакеты и container images заранее в локальный registry.
* Используйте `GITLAB_OMNIBUS_CONFIG` для предконфигурации.
* Проверьте Upgrade Paths заранее — в air-gapped окружении нет доступа к репозиториям.

## Дополнительная информация

### Связанные темы

* **[Архитектура GitLab](../Concepts/gitlab_platform_architecture.md)** — общая архитектура и компоненты
* **[Управление инстансом GitLab](./gitlab_instance_administration.md)** — бэкап, восстановление, управление секретами
* **[Управление базами данных GitLab](./gitlab_database_management.md)** — PostgreSQL и Valkey/Redis
* **[Администрирование GitLab в масштабе](./gitlab_administration_at_scale.md)** — распределённые архитектуры
* **[Мониторинг и метрики GitLab](./monitoring_and_metrics.md)** — Prometheus, Grafana, алертинг

### Полезные ссылки

* [GitLab Upgrade Paths](https://docs.gitlab.com/ee/update/index.html#upgrade-paths)
* [GitLab Zero-Downtime Upgrades](https://docs.gitlab.com/ee/update/zero_downtime.html)
* [GitLab Backup and Restore](https://docs.gitlab.com/ee/raketasks/backup_restore.html)
* [GitLab High Availability](https://docs.gitlab.com/ee/administration/high_availability/)
* [GitLab Maintenance Mode](https://docs.gitlab.com/ee/administration/raketasks/maintenance.html)
