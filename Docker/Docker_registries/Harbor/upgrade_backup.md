# Harbor: Обновление, бэкап и восстановление

**Актуально для:** Harbor 2.15.x

## Определения

* **Миграция (Migration)**: Процедура преобразования конфигурации `harbor.yml` и схемы БД при переходе на новую версию Harbor. Выполняется утилитой `goharbor/prepare` (режим `migrate`) до запуска новой версии.
* **data_volume**: Директория хоста (дефолт `/data`), в которой Harbor хранит все данные: БД (`/data/database`), реестр (`/data/registry`), Redis, кэш Trivy-адаптера. Переживает пересоздание контейнеров.
* **RPO/RTO**: Целевые показатели потери данных и времени восстановления. Для реестра образов типовые значения — часы (см. [DR для CI/CD](../../../CI-CD/Core_Concepts/ci_cd_backup_dr.md)).
* **Rollback**: Возврат на предыдущую версию Harbor после неудачного апгрейда — восстановление бэкапа директории установщика и БД.
* **DR Drill**: Плановая тренировка восстановления из бэкапа в изолированной среде — единственный способ проверить, что бэкап рабочий.

## Основные концепции

### Как устроен апгрейд Harbor

Апгрейд Harbor — это не «замена образов», а управляемая миграция:

1. **Остановка** текущего инстанса (`docker compose down`).
2. **Бэкап** директории установщика и `data_volume` (обязательно — миграция может изменить схему БД).
3. **Миграция `harbor.yml`** утилитой `goharbor/prepare` (режим `migrate`) — переводит параметры старого формата в новый.
4. **Установка новой версии** (`install.sh`).
5. **Миграция схемы БД** выполняется компонентом **core** при первом запуске новой версии. Если миграция не прошла — смотрите логи core.

> Внешняя PostgreSQL для Harbor 2.9+ должна быть версии **>= 12**.

### Что бэкапить (Docker Compose)

| Компонент | Расположение | Зачем |
| :--- | :--- | :--- |
| `harbor.yml` | Директория установщика | Вся конфигурация (пароли, TLS-пути, storage) |
| Директория установщика | `harbor/` | Скрипты `install.sh`, `prepare` — нужны для апгрейда и восстановления |
| `data_volume` | `/data` (дефолт) | БД, слои образов, метаданные, отчёты сканирования |
| Внешняя PostgreSQL | Сервер БД | `pg_dump` (см. [DR для CI/CD](../../../CI-CD/Core_Concepts/ci_cd_backup_dr.md)) |
| Внешний Redis | Сервер Redis | Очереди задач (допустима потеря — задачи пересоздаются) |

В Kubernetes бэкап инстанса выполняется через [Velero](../../../Kubernetes/ToolsUtilities/velero-overview.md) — документированный Harbor способ backup/restore.

## Практические сценарии

### Сценарий 1: Апгрейд Harbor (Docker Compose)

```bash
# 0. Предварительно: бэкап (см. сценарий 3)

# 1. Остановка текущего инстанса
cd harbor
sudo docker compose down

# 2. Резервная копия директории установщика и БД
sudo mv harbor /my_backup_dir/harbor
sudo cp -r /data/database /my_backup_dir/

# 3. Загрузка и распаковка новой версии (явная версия, не latest)
VERSION=v2.15.2
wget "https://github.com/goharbor/harbor/releases/download/${VERSION}/harbor-offline-installer-${VERSION}.tgz"
tar xzf harbor-offline-installer-${VERSION}.tgz

# 4. Миграция конфигурации: старый harbor.yml → новый формат
#    Утилита миграции — в образе goharbor/prepare
sudo docker pull goharbor/prepare:${VERSION}
sudo cp /my_backup_dir/harbor/harbor.yml harbor/harbor.yml
sudo docker run -it --rm -v /:/hostfs goharbor/prepare:${VERSION} migrate -i /path/to/harbor/harbor.yml
# → миграция harbor.yml в формат 2.15.x

# 5. Установка новой версии
cd harbor
sudo ./install.sh --with-trivy
# → ✔ ----Harbor has been installed and started successfully.----
```

> Схема БД и данные мигрируются компонентом core при старте. Если миграция не прошла — логи: `docker logs harbor-core` (или `/var/log/harbor/core.log`).

### Сценарий 2: Апгрейд Harbor (Helm)

```bash
# Обновление чарта до версии, соответствующей целевой версии Harbor
# (проверить соответствие: поле appVersion в https://helm.goharbor.io/index.yaml)
helm repo update
helm upgrade my-release harbor/harbor -n harbor \
  --version 1.19.2 \
  --reuse-values
# → Release "my-release" has been upgraded.
```

При апгрейде через Helm миграция схемы БД также выполняется при старте core. PVC с данными (`persistence.enabled: true`) сохраняются.

> Для Harbor 2.15.0 (charts 1.19.0) есть известная проблема: proxy cache проектов из Docker Hub не работает ([#23025](https://github.com/goharbor/harbor/issues/23025)). Исправлено в 2.15.1 / charts 1.19.1.

### Сценарий 3: Бэкап Harbor (Docker Compose)

```bash
# Полный бэкап (выполнять при остановленном Harbor для консистентности БД)
cd harbor
sudo docker compose down

BACKUP_DIR=/backup/harbor-$(date +%F)
sudo mkdir -p "$BACKUP_DIR"

# 1. Конфигурация и установщик
sudo cp harbor.yml "$BACKUP_DIR/harbor.yml"
sudo tar -czf "$BACKUP_DIR/harbor-installer.tgz" -C .. harbor

# 2. Данные реестра и БД (data_volume)
sudo tar -czf "$BACKUP_DIR/harbor-data.tgz" -C / data

# 3. Контрольная сумма
sha256sum "$BACKUP_DIR"/*.tgz > "$BACKUP_DIR/SHA256SUMS"
# → <hash>  /backup/harbor-2026-10-05/harbor-data.tgz

sudo docker compose up -d
```

Для внешней БД — `pg_dump` (пример и обоснование RPO/RTO — в [DR для CI/CD](../../../CI-CD/Core_Concepts/ci_cd_backup_dr.md), сценарий 1).

### Сценарий 4: Восстановление Harbor (Docker Compose)

```bash
# На чистом или сломанном хосте
BACKUP_DIR=/backup/harbor-2026-10-05

# 1. Распаковка установщика той же версии
tar xzf "$BACKUP_DIR/harbor-installer.tgz" -C /usr/local/
cd /usr/local/harbor

# 2. Восстановление конфигурации и данных
sudo cp "$BACKUP_DIR/harbor.yml" harbor.yml
sudo tar -xzf "$BACKUP_DIR/harbor-data.tgz" -C /

# 3. Запуск
sudo ./install.sh --with-trivy
sudo docker compose ps
# → все сервисы Up
```

### Сценарий 5: Откат апгрейда (Rollback)

```bash
# 1. Остановка новой версии
cd harbor
sudo docker compose down

# 2. Восстановление директории установщика и БД из бэкапа
sudo rm -rf /usr/local/harbor
sudo mv /my_backup_dir/harbor /usr/local/harbor
sudo rm -rf /data/database
sudo cp -r /my_backup_dir/database /data/

# 3. Запуск старой версии
cd /usr/local/harbor
sudo ./install.sh --with-trivy
```

> Откат возможен только при наличии бэкапа, сделанного **до** апгрейда. Миграция схемы БД необратима — старая версия не прочитает мигрированную БД.

### Сценарий 6: Миграция из других реестров

Перенос образов из Docker Hub, GitLab Registry, Nexus или plain Docker Registry в Harbor — через daemonless-утилиты (полное описание инструментов — в [управлении артефактами](../../../CI-CD/artifact_management.md) и [Skopeo](../../../Podman/skopeo_overview.md)). Полный runbook миграции Docker Hub → Harbor (инвентаризация через API, пилот, массовый перенос, перенос подписей, cutover, rollback) — в [migration.md](./migration.md):

```bash
# Копирование одного образа с retag (skopeo)
skopeo copy docker://registry.old.local/app:v1.0 \
  docker://harbor.corp.local/production/app:v1.0
# → Copying blob ... Copying config ... Writing manifest to image destination

# Массовая синхронизация проекта (skopeo sync)
skopeo sync --src docker --dest docker \
  registry.old.local/myproject harbor.corp.local/myproject

# Retag без перекачки слоёв (regctl, если оба реестра видят общие blobs)
regctl tag create registry.old.local/app:v1.0 harbor.corp.local/production/app:v1.0

# Проверка digest совпадает (гарантия неизменности бинарного кода)
skopeo inspect --format '{{.Digest}}' docker://registry.old.local/app:v1.0
skopeo inspect --format '{{.Digest}}' docker://harbor.corp.local/production/app:v1.0
# → sha256:<одинаковый digest>
```

> При миграции пересоберите подписи Cosign/Notation — `skopeo copy`/`sync` не копирует OCI 1.1 Referrers (аттестации, SBOM), а только sigstore-стильные `.sig`. Подписи привязаны к digest, поэтому при `--preserve-digests` их можно перенести `cosign copy` или переподписать в Harbor (подробный runbook — [migration.md](./migration.md#сценарий-4-перенос-подписей-и-аттестаций)).

### Сценарий 7: DR drill: тренировка восстановления

Плановая тренировка восстановления из бэкапа в изолированной среде — единственный способ проверить, что бэкап рабочий. Проводится по расписанию (рекомендуется — не реже раза в квартал) и после каждого значимого изменения (апгрейд, смена storage backend).

**План тренировки (Docker Compose):**

```bash
# 1. Изолированный хост/контейнер-сеть, НЕ продакшен
# 2. Восстановление из бэкапа (см. сценарий 4)
BACKUP_DIR=/backup/harbor-2026-10-05
tar xzf "$BACKUP_DIR/harbor-installer.tgz" -C /usr/local/
cd /usr/local/harbor
sudo cp "$BACKUP_DIR/harbor.yml" harbor.yml
sudo tar -xzf "$BACKUP_DIR/harbor-data.tgz" -C /
sudo ./install.sh --with-trivy

# 3. Контрольный чек-лист (тот же, что при валидации после апгрейда)
curl -sk https://harbor-drill.corp.local/api/v2.0/health
# → {"status":"healthy"}
curl -sk -u "admin:$PASS" "https://harbor-drill.corp.local/api/v2.0/projects" | jq 'length'
# → число проектов из продакшена
docker pull harbor-drill.corp.local/myproject/critical-app:v1.0
# → образ из бэкапа доступен

# 4. Проверка целостности: digest критичного образа совпадает с продакшеном
skopeo inspect --format '{{.Digest}}' docker://harbor-drill.corp.local/myproject/critical-app:v1.0
```

**Критерии успеха:** Harbor стартует, все проекты/пользователи/правила репликации на месте, критичные образы доступны по digest, подписи верифицируются (`cosign verify`). Результаты тренировки фиксируются: дата, RTO (фактическое время восстановления), обнаруженные проблемы.

**Типичные находки drill'а:** неполный бэкап (забыт `harbor.yml`), устаревший installer другой версии, нерабочие TLS-пути, потерянные робот-аккаунты.

### Сценарий 8: Бэкап и восстановление Harbor в Kubernetes (Velero)

В Kubernetes Harbor бэкапится через Velero — документированный Harbor способ backup/restore. Velero снимает PVC Harbor (registry, database, jobservice, trivy) и ресурсы Helm-релиза.

```bash
# 1. Бэкап namespace harbor (PVC + ресурсы)
velero backup create harbor-backup-$(date +%F) \
  --include-namespaces harbor \
  --snapshot-volumes=false        # PVC уже в storage классе с ретеншеном; 
                                  # для snapshot volumes — см. velero-overview.md
# → Backup request "harbor-backup-2026-10-05" processed successfully

# 2. Статус бэкапа
velero backup describe harbor-backup-2026-10-05
# → Phase: Completed

# 3. Восстановление (в тот же namespace или новый)
velero restore create harbor-restore-$(date +%F) \
  --from-backup harbor-backup-2026-10-05 \
  --include-namespaces harbor
# → Restore request "harbor-restore-2026-10-05" processed successfully

# 4. Валидация после восстановления
kubectl get pods -n harbor
curl -sk https://registry.example.com/api/v2.0/health
# → {"status":"healthy"}
```

**Особенности:**

* Внешняя PostgreSQL/Redis бэкапятся своими средствами (`pg_dump`, RDB-снапшоты) — Velero покрывает только Harbor-специфичные PVC.
* При восстановлении в новый кластер: пересоздайте внешние зависимости (БД, Redis, object storage) и секреты (`existingSecret*`) до restore.
* Установка самого Velero в air-gapped через Harbor-реестр — в [Velero: обзор](../../../Kubernetes/ToolsUtilities/velero-overview.md).
* Расписание бэкапов Velero: `velero schedule create harbor-daily --schedule="0 2 * * *" --include-namespaces harbor`.

## Валидация после апгрейда

Чек-лист (по официальной процедуре Test Harbor Upgrade):

```bash
# 1. Версия
curl -sk https://harbor.corp.local/api/v2.0/systeminfo | jq .harbor_version
# → "2.15.2"

# 2. Здоровье всех компонентов
curl -sk https://harbor.corp.local/api/v2.0/health
# → {"status":"healthy"}

# 3. Пользователи и роли (не требуется в LDAP/OIDC-режиме — пользователи во внешнем источнике)
curl -sk -u "admin:$PASS" "https://harbor.corp.local/api/v2.0/users" | jq 'length'

# 4. Метаданные: endpoints репликации, правила, лейблы, отчёты сканирования
curl -sk -u "admin:$PASS" "https://harbor.corp.local/api/v2.0/replication/registries" | jq 'length'

# 5. Storage: проверить backend через UI (Administration → Configuration → Storage) или сравнить `df -h` на хосте с размером `data_volume`

# 6. Retention policies: проверить, что retention jobservice активен (Administration → Jobs)

# 7. Scan reports: статус последнего сканирования критичного артефакта
curl -sk -u "admin:$PASS" "https://harbor.corp.local/api/v2.0/projects/production/repositories/my-artifacts/artifacts" | jq '.[0].scan_overview'

# 8. Robot-аккаунты: количество и срок действия
curl -sk -u "admin:$PASS" "https://harbor.corp.local/api/v2.0/robots" | jq '.[] | {name, expiration}'

# 9. Replication endpoints: проверить доступность и credentials через UI или curl
for reg in $(curl -sk -u "admin:$PASS" "https://harbor.corp.local/api/v2.0/replication/registries" | jq -r '.[].name'); do
  echo "=== $reg ==="
  curl -sk -u "admin:$PASS" "https://harbor.corp.local/api/v2.0/replication/executions" | jq '.[0]'
done

# 10. Smoke-тест: push/pull
docker push harbor.corp.local/myproject/verify:v1
docker pull harbor.corp.local/myproject/verify:v1
```

## Troubleshooting

| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| Миграция `harbor.yml` не прошла | Нераспознанный параметр старой версии | Проверьте вывод `prepare migrate`; вручную перенесите параметр в новый формат |
| Harbor не стартует после апгрейда | Миграция схемы БД не прошла | Логи core: `docker logs harbor-core` / `/var/log/harbor/core.log` |
| `schema mismatch` у Trivy | Базы сканера не совместимы с новой версией | Синхронизируйте базы Trivy заново (см. [оффлайн-обновление](./offline_trivy_update.md)) |
| Откат невозможен | Нет бэкапа до апгрейда | Восстановление только из бэкапа; миграция схемы необратима |
| Онлайн-установщик зависает | Нет доступа к Docker Hub | Используйте оффлайн-установщик |
| Внешняя БД отказывает при старте | PostgreSQL < 12 | Поднимите PostgreSQL >= 12 (требование Harbor 2.9+) |

## Best Practices

### Планирование апгрейда

* **Заморозка изменений (change freeze)**: за сутки до апгрейда введите change freeze — никакие push/labeling/репликации во время миграции. Это исключает конфликты БД и неконсистентные бэкапы.
* **Версионирование**: всегда используйте явные версии в командах (`VERSION=v2.15.2`, `--version 1.19.2`), никогда `latest`. Это гарантирует воспроизводимость и упрощает откат.
* **Окно обслуживания**: согласуйте окно с потребителями реестра. Учитывайте время миграции БД (большие инстансы — десятки минут) и возможный downtime.
* **skip-major запрещён**: обновляйтесь только на adjacent minor (например, 2.14.x → 2.15.x). Пропуск версий не тестируется и может сломать схему БД.

### Бэкап и верификация

* **Правило 3-2-1**: 3 копии бэкапа, 2 разных носителя, 1 копия вне хоста (NAS, S3, тайплент). Для реестра RPO целевое — часы, RTO — десятки минут.
* **Верификация бэкапа**: перед апгрейдом проверяйте целостность бэкапа:
  ```bash
  # Проверка контрольной суммы
  sha256sum -c /backup/harbor-2026-10-05/SHA256SUMS
  # → harbor-data.tgz: OK
  
  # Тест восстановления на изолированном хосте (см. сценарий 7)
  ```
* **Отдельный бэкап `harbor.yml`**: пароли, TLS-ключи, storage backend, auth mode — всё в одном файле. Без него восстановление на новом хосте невозможно.
* **Внешние зависимости**: PostgreSQL (`pg_dump`), Redis (RDB-снапшот), S3/MinIO — бэкапятся независимо. Velero покрывает только Harbor-специфичные PVC.

### Rollback readiness

* **Бэкап делается ДО остановки**: последовательность `бэкап → остановка → апгрейд`. Если бэкап после остановки — при проблеме с запуском данные уже не зафиксированы консистентно.
* **Инструкция отката в runbook**: перед каждым апгрейдом обновите сценарий 5 под текущие пути и версии.
* **Идемпотентность**: `install.sh` можно запускать многократно — он проверяет состояние. Но откат требует восстановления бэкапа, а не повторного запуска.

### DR Drill

* **Квартальная регулярность**: тренируйтесь не реже раза в квартал и после каждого значимого изменения (апгрейд, смена storage backend, миграция PostgreSQL).
* **Изолированная среда**: DR drill на production-хосте запрещён — используйте отдельный хост/кластер.
* **Критерии успеха**: Harbor стартует, все проекты/пользователи/правила репликации на месте, критичные образы доступны по digest, подписи верифицируются.
* **Фиксация результатов**: дата, RTO (фактическое время восстановления), обнаруженные проблемы — записывайте в runbook или ITSM.

### PostgreSQL и Valkey

* **Embedded PostgreSQL 18 (Harbor 2.15.2+)**: при использовании встроенной PostgreSQL чарт автоматически обновляет базу **с PostgreSQL 15 до PostgreSQL 18** через `pg_upgrade` при старте пода. Убедитесь, что бэкап БД сделан до апгрейда. Для сред с не-ASCII данными после обновления может потребоваться `reindexdb --all-databases`.
* **Внешняя PostgreSQL**: поддерживаются версии >= 12. При планировании апгрейда external PostgreSQL учитывайте, что миграция схемы Harbor не затрагивает структуру таблиц БД — только данные внутри таблиц.
* **Valkey (Harbor 2.15.2+)**: внутренний кэш-бэкенд заменён с Redis на Valkey — drop-in замена, протокол RESP совместим. При апгрейде с 2.15.1 или ниже контейнер Valkey поднимается автоматически. Внешний Redis для очередей задач по-прежнему поддерживается (Sentinel работает, Redis Cluster и TLS — нет).

### Очистка

* **Старые бэкапы**: храните не более 2–3 последних бэкапов. Старые удаляйте через `find /backup -maxdepth 1 -type d -name 'harbor-*' -mtime +30 -exec rm -rf {} +` (проверьте retention policy организаций).
* **Velero retention**: настройте TTL для бэкапов — `velero schedule create harbor-daily --schedule="0 2 * * *" --ttl 720h0m0s` (30 дней).
* **Образы установщика**: после апгрейда удаляйте старые `.tgz` установщиков — они занимают место и создают риск запуска wrong-version `prepare`.

## Граничные случаи

* **Бэкап при работающем Harbor** допустим для `data_volume` (registry и trivy-консистентны), но БД лучше снимать при остановленном инстансе или через `pg_dump` внешней БД.
* **`harbor_admin_password` из `harbor.yml` игнорируется** после первого запуска — при восстановлении на новом хосте пароль администратора берётся из восстановленной БД.
* **Версия чарта ≠ версия Harbor**: charts `1.19.x` соответствуют Harbor `2.15.x` — проверяйте `appVersion` в `index.yaml` перед апгрейдом. На момент написания актуальная пара: chart `1.19.2` → Harbor `2.15.2`.
* **PVC в Kubernetes**: при `persistence.resourcePolicy: keep` (дефолт) данные сохраняются при `helm uninstall` — при откате не удаляйте PVC.
* **Миграция подписей**: Cosign/Notation-подписи не переносятся между реестрами автоматически — переподписывайте после миграции.
* **Valkey при апгрейде с < 2.15.2**: внутренний кэш автоматически мигрирует с Redis на Valkey. Если вы использовали внешний Redis для очередей — конфигурация не меняется. Для полностью air-gapped сред убедитесь, что образ Valkey предзагружен.
* **PostgreSQL 18 embedded (Helm 2.15.2+)**: при использовании встроенной PostgreSQL чарт запускает `pg_upgrade` с 15 на 18 при старте пода. Процесс занимает время proportional размеру БД; для БД >100 ГБ увеличьте `livenessProbe.initialDelaySeconds` и `readinessProbe.initialDelaySeconds`. После апгрейда проверяете `SELECT version();` в БД.
* **Air-gapped среды**: все образы (Harbor, Trivy, Valkey/Redis) должны быть предзагружены в внутренний registry. `install.sh` и `prepare` берут образы из кэша. Используйте `--with-trivy` только если Trivy-образ тоже закэширован.
* **Большие реестры (>1 TB)**: `tar -czf /data` может занять часы. Используйте потоковый бэкап:
  ```bash
  sudo tar -czf - -C / data | pv | gzip > /backup/harbor-data-stream.tgz
  ```
  Или бэкап через `rsync` с `--progress` для мониторинга. Рекомендуется разделить `data_volume` на отдельные PVC/тома (registry, database, trivy) для параллельного бэкапа.
* **Смена storage backend при апгрейде**: переход с filesystem на S3-compatible (MinIO, Ceph, AWS S3) возможен только через миграцию данных **до** апгрейда Harbor. Порядок: `skopeo sync` → новый Harbor с S3 → cutover. Самостоятельная смена `storage_service` в `harbor.yml` на существующем инстансе не поддерживается.
* **Mixed auth mode**: при апгрейде auth mode (Database → LDAP/OIDC) делайте это **после** апгрейда, на уже работающем инстансе. См. [аутентификацию](./authentication.md#граничные-случаи).
* **Database connection loss during migration**: если БД недоступна во время миграции схемы — Harbor не стартует. Восстанавливайте связь и перезапускайте. Миграция идемпотентна: повторный запуск `install.sh` продолзит с места остановки.

## Дополнительная информация

* Официальная процедура: [Upgrade Harbor and Migrate Data](https://goharbor.io/docs/2.15.2/administration/upgrade/), [Roll Back from an Upgrade](https://goharbor.io/docs/2.15.2/administration/upgrade-rollback/), [Test Harbor Upgrade](https://goharbor.io/docs/2.15.2/administration/upgrade-test/).
* **RPO/RTO и стратегия 3-2-1** для CI/CD-инфраструктуры — [Резервное копирование и DR для CI/CD](../../../CI-CD/Core_Concepts/ci_cd_backup_dr.md).
* **Бэкап в Kubernetes через Velero** — [Velero: обзор](../../../Kubernetes/ToolsUtilities/velero-overview.md).

### Связанные документы

* **[Обзор Harbor](./overview.md)** — архитектура и компоненты.
* **[Установка Harbor](./installation.md)** — первичное развёртывание.
* **[Работа с Harbor](./usage.md)** — GC и retention (влияют на объём бэкапа).
* **[Оффлайн-обновление Trivy](./offline_trivy_update.md)** — совместимость баз после апгрейда.
* **[Harbor REST API](./api.md)** — автоматизация проверок после апгрейда.
* **[Hardening](./hardening.md)** — безопасность восстановленного инстанса.
