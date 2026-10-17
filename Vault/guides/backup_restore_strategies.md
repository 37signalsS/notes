# Стратегии резервного копирования и восстановления Vault

**Актуально для:** Vault 2.x (latest 2.1.2, Oct 2026; примеры — образ `hashicorp/vault:2.1.x`); Snapshot save/restore/inspect/load/unload (OSS); DR Replication, `snapshot load` + `vault recover` (Enterprise); для Consul-бэкенда — `consul snapshot` (см. `vault_with_consul_backend.md`).

## Определения

**RPO (Recovery Point Objective)** — максимально допустимая потеря данных при восстановлении. Например, RPO 1 час означает, что при сбое можно потерять до 1 часа данных.

**RTO (Recovery Time Objective)** — максимально допустимое время восстановления сервиса. Например, RTO 4 часа означает, что сервис должен быть восстановлен в течение 4 часов.

**Snapshot** — моментальный снимок состояния Raft-хранилища (секреты, политики, конфигурация, audit-логи и т. п.). В Vault snapshot сохраняется в виде файла `.snap` и является *point-in-time* — снимок отражает состояние на момент `snapshot save`.

**3-2-1 Backup Rule** — правило резервного копирования: 3 копии данных, на 2 разных носителях, 1 копия в off-site хранилище.

**Immutable Backup** — неизменяемая резервная копия, защищённая от удаления или изменения (WORM — Write Once Read Many).

**Disaster Recovery (DR)** — процесс восстановления после катастрофического сбоя (потеря дата-центра, повреждение данных).

**Point-in-Time Recovery (PITR)** — восстановление состояния на конкретный момент времени. *Важно:* в Vault 2.x OSS snapshots являются точечными по своей природе (момент `save`), но **не существует флага `snapshot restore` для выбора произвольной метки времени**; point-in-time восстановление отдельных секретов доступно только в Enterprise через `snapshot load` + `vault recover` (см. [Сценарий 7](#сценарий-7-восстановление-отдельных-секретов-enterprise)).

## Основные концепции

### Требования к бэкенду

Snapshot save/restore/inspect/load/unload поддерживаются **только при использовании Raft как `storage` (integrated storage)**. Если Raft применяется лишь как `ha_storage` (в связке с Consul или другим бэкендом), snapshot не создать — снимок нужно делать у соответствующего бэкенда (например, `consul snapshot save`).

### Кворум Raft

Для кластера из `n` узлов кворум составляет `(n+1)/2`. Потеря более половины узлов (например, 2 из 3) приводит к потере кворума: кластер не выбирает лидера и перестаёт обслужвать read/write-запросы. Восстановление — через snapshot (если есть) или ручную правку `peers.json`.

### Типы резервного копирования

| Тип | Описание | RPO | RTO | Использование |
| :--- | :--- | :--- | :--- | :--- |
| **Snapshot** | Точечный снимок Raft-хранилища | Низкий (минуты) | Низкий (минуты) | Production (OSS) |
| **Automated snapshots** | Плановые снимки в local/SSH-хранилище (Enterprise) | Низкий | Низкий | Production (Enterprise) |
| **DR Replication** | Репликация на DR Secondary + promote | Минимальный | Минимальный | Critical (Enterprise) |

### Стратегии восстановления

| Стратегия | Описание | RTO | Сложность |
| :--- | :--- | :--- | :--- |
| **Восстановление на том же узле** | Restore из snapshot на текущем сервере | Низкий | Низкая |
| **Восстановление на новом узле** | Restore на другом сервере в кластере | Средний | Средняя |
| **Восстановление после потери кворума** | Restore или ручная правка `peers.json` | Средний | Средняя |
| **DR Replication** | Переключение на DR Secondary кластер | Минимальный | Высокая |

## Практические сценарии

### Предпосылки

- Использование **Raft как `storage`** (integrated storage), а не `ha_storage`-only (см. `concepts.md`).
- Доступ к **root-токену** или capability `sudo` на пути `sys/storage/raft/snapshot-save`.
- **Unseal Keys / Recovery Keys** доступны и хранятся вне Vault (1Password, KMS-wrapped, бумажный backup).
- Кластер Vault **online** (для `save`/`inspect`); для `restore` — остановлен либо sealed.
- (Enterprise) действующая лицензия; (OSS) планируйте discrete recovery через `snapshot load`+`vault recover` только для чрезвычайных случаев, т.к. это восстанавливает *на сервере*.

### Сценарий 1: Создание и хранение snapshot

#### Создание snapshot

```bash
# Создание snapshot Raft-хранилища (требует root-токен или capability sudo)
export VAULT_ADDR=https://vault.example.com:8200
export VAULT_TOKEN=<root_or_sudo_token>
vault operator raft snapshot save /opt/vault/backups/vault-$(date +%Y%m%d-%H%M).snap

# Проверка целостности snapshot
vault operator raft snapshot inspect /opt/vault/backups/vault-$(date +%Y%m%d-%H%M).snap
# → Key              Value
# → ---              -----
# → ID               bolt-snapshot
# → Size             93290
# → Index            8957
# → Term             11
# → Version          1
```

> `snapshot save` направляется на лидера; snapshot отражает состояние на момент завершения save, а не на момент начала.

#### Планирование snapshot через cron

```bash
# /etc/cron.d/vault-backup  (от имени пользователя vault; $VAULT_TOKEN задаётся в systemd-EnvironmentFile)
SHELL=/bin/bash
0 2 * * * vault operator raft snapshot save /opt/vault/backups/vault-$(date +\%Y\%m\%d-\%H%M).snap && \
         find /opt/vault/backups -name "vault-*.snap" -mtime +7 -delete
```

#### Хранение snapshot (off-site, без облака)

```bash
# Копия на удалённый хост по SSH (off-site)
rsync -avz -e ssh /opt/vault/backups/ backup@bk-host:/vault-backups/

# Или через rclone (generic s3/ssh/fs)
rclone copy /opt/vault/backups/ backup-remote:vault/
```

### Сценарий 2: Восстановление из snapshot

#### Восстановление на том же сервере

```bash
# 1. Остановка Vault
sudo systemctl stop vault

# 2. Перемещение (а не удаление) текущих данных
mv /opt/vault/data /opt/vault/data.old

# 3. Восстановление из snapshot
vault operator raft snapshot restore -force /opt/vault/backups/vault-20260924-0200.snap
# → Restore not completed on return: команда принимает snapshot и заканчивает в фоне
#   (дождитесь в логах: "post-unseal setup complete" + "vault is unsealed")

# 4. Запуск Vault
sudo systemctl start vault

# 5. Распечатывание (Shamir) — либо auto-unseal
vault operator unseal <key_1>
vault operator unseal <key_2>
vault operator unseal <key_3>
```

#### Восстановление на новом сервере

```bash
# 1. Установка Vault на новом сервере (таже версии, что и источник)
sudo apt install vault

# 2. Копирование snapshot на новый сервер
scp /opt/vault/backups/vault-20260924-0200.snap user@new-server:/opt/vault/backups/

# 3. Конфигурация, аналогичная исходной (те же node_id/api_addr)
sudo cp /etc/vault.d/vault.hcl /etc/vault.d/vault.hcl.backup

# 4. Восстановление
sudo systemctl stop vault
vault operator raft snapshot restore -force /opt/vault/backups/vault-20260924-0200.snap
sudo systemctl start vault

# 5. Распечатывание
vault operator unseal <key_1>
vault operator unseal <key_2>
vault operator unseal <key_3>

# 6. Проверка кластера
vault operator raft list-peers
# → только восстановленный узел (leader), фолловеры присоединяются по retry_join
```

### Сценарий 3: Восстановление после потери кворума

```bash
# 1. Диагностика. При потере кворума логи содержат:
#    "storage.raft: failed to contact quorum of nodes, stepping down"
#    "core: leadership lost, stopping active operation"
#    → кластер не обслуживает read/write; запросы, требующие лидера, падают с таймаутом
vault operator raft list-peers
# → (переадресация на лидера) Error making API request: rpc error: code = Unavailable ...

# Вариант 1: восстановление из snapshot (если snapshot есть)
vault operator raft snapshot restore -force /opt/vault/backups/vault-latest.snap

# Вариант 2: ручная правка peers.json (без snapshot)
# 1. Остановка Vault
sudo systemctl stop vault

# 2. Редактирование /opt/vault/data/raft/peers.json
#    Оставить только живые узлы, удалить unreachable.

# 3. Запуск и распечатывание
sudo systemctl start vault
vault operator unseal <key_1>
vault operator unseal <key_2>
vault operator unseal <key_3>

# 4. Проверка
vault operator raft list-peers
# → один leader в кластере (quorum of one)
```

> Формула кворума `(n+1)/2`: чтобы восстановить 3-узловый кластер из 1 живого, используйте peers.json (см. официальный туториал *Recover from lost quorum*).

### Сценарий 4: DR Replication (Enterprise)

Настройка DR Replication подробно описана в **[Производительность и репликация](./performance_and_replication.md#сценарий-4-dr-replication-enterprise)**.

Кратко: на DR Primary включите DR (`sys/replication/dr/primary/enable`), сгенерируйте bootstrap token (`sys/replication/dr/primary/secondary-token id=dr-secondary`), передайте его на DR Secondary и выполните enable с `token=`. Для promote используется `dr_operation_token` (генерируется через `sys/replication/dr/secondary/generate-operation-token/attempt`).

> DR Secondary хранит реплику данных; при потере Primary promote делает Secondary активным. Требуется лицензия Enterprise.

### Сценарий 5: Точечные снимки и восстановление на момент снятия

В каждый момент `snapshot save` фиксирует состояние хранилища. Это и есть point-in-time обеспась в 2.x OSS:

```bash
# Снимок за 2026-09-24 02:00 восстанавливает состояние именно на этот момент:
vault operator raft snapshot restore -force /opt/vault/backups/vault-20260924-0200.snap
```

**Ограничение 2.x OSS:** НЕ существует флага `snapshot restore <file> -recovery-timestamp=<ts>` для восстановления на произвольную метку времени. Чтобы достичь более частых точек восстановления, делайте снимки чаще (cron каждые 15–30 мин). Точечное восстановление *отдельного* секрета — только Enterprise (Сценарий 7).

### Сценарий 6: Тестирование восстановления

Регулярно тестируйте restore на выделенном стенде (не на prod):

```bash
#!/bin/bash
# test-restore.sh

# 1. Создание тестового snapshot
vault operator raft snapshot save /tmp/test-restore.snap

# 2. Восстановление на тестовом сервере
vault operator raft snapshot restore -force /tmp/test-restore.snap

# 3. Проверка
vault status
vault operator raft list-peers
vault kv get secret/myapp/config

# 4. Очистка
rm /tmp/test-restore.snap
```

### Сценарий 7: Восстановление отдельных секретов (Enterprise)

Discete secret recovery позволяет вытащить один секрет из snapshot без полного restore:

```bash
# 1. Загрузка snapshot (Enterprise; кластер остаётся в продукции)
vault operator raft snapshot load /opt/vault/backups/vault-20260924-0200.snap
# → Key           Value
# → ---          -----
# → snapshot_id  e57cd0cf-c3fa-4e5e-96ea-4a68fa8f3269

# 2. Восстановление конкретного секрета (перезапишет путь)
vault recover -snapshot-id=e57cd0cf-c3fa-4e5e-96ea-4a68fa8f3269 secret/myapp/config

# 3. Выгрузка snapshot (авто-выгрузка через 72 ч, либо вручную)
vault operator raft snapshot unload e57cd0cf-c3fa-4e5e-96ea-4a68fa8f3269
```

> Требуется Enterprise. Поддерживаются пути `kv (v1)`, `cubbyhole`, `ssh /config/ca`, `databases /static-roles/:role_name` и др. (полный список — в оф. документации *Manage snapshots → Recover a secret*). `snapshot load` работает только на лидере того же кластера с теми же unseal-ключами.

## Диагностика и типичные ошибки

| Проблема / Симптом | Причина | Решение |
| :--- | :--- | :--- |
| `Error reading system status: context deadline exceeded` | Потеря кворума / нет лидера. | Восстановление из snapshot или правка `peers.json` (Сценарий 3). |
| `snapshot restore` не завершается сразу | Команда принимает snapshot и восстанавливает в фоне. | Дождитесь в логах `post-unseal setup complete` и `vault is unsealed`; проверьте `vault operator raft list-peers`. |
| Ошибки таймаута при `snapshot save`/`restore` больших файлов | Превышен `VAULT_CLIENT_TIMEOUT` / `http_read_timeout`. | `export VAULT_CLIENT_TIMEOUT=30m`; `http_read_timeout = "30m"` в listener; для API — `/sys/storage/raft/snapshot-force`. |
| `snapshot inspect` не выводит `Entries`/`Last Modified` | Таков реальный формат вывода (см. Сценарий 1). | Смотрите поля `Index`/`Term`/`Version` и таблицу ключей. |
| Restore в кластер с другими unseal-ключами | Key mismatch отклоняет restore. | Используйте `-force` (`snapshot restore -force`) или API `/sys/storage/raft/snapshot-force`. |
| `snapshot save` → `Snapshot is not supported when Raft is used only for ha_storage` | Raft используется как `ha_storage`, а не как `storage`. | Перейдите на Raft как основной `storage`, либо бэкапьте основной бэкенд (Consul). |
| Снимок не восстанавливает токены lease | Snapshots не включают runtime-lease TTL; lease восстанавливаются, но andстраячаются. | После restore проверьте истечение lease и при необходимости выполните re-login. |

## Ограничения

- **ha_storage-only:** если Raft — только HA (`-ha_storage`), `snapshot save` недоступен; бэкапьте основной бэкенд.
- **OSS vs Enterprise:** автоматизированные снимки в local/SSH-хранилище, DR Replication, discrete secret recovery (`snapshot load` + `vault recover`) — Enterprise.
- **Размер/время:** большие snapshot (>10 ГБ) долго save/restore; планируйте окно обслуживания и повышенный таймаут.
- **Совместимость:** snapshot версии Vault обычно восстанавливается на той же/более новой версии; при major upgrade проверяйте release notes.
- **Plugins/Artifacts:** внешние плагины и их артефакакты НЕ входят в snapshot — храните манифесты плагинов отдельно.

## Лучшие практики

1. **3-2-1 правило:** 3 копии, на 2 носителя, 1 off-site (удалённый хост по SSH/rsync, а не облако).
2. **Автоматизация:** регулярный `snapshot save` через cron (или авто-снапшоты в Enterprise).
3. **Шифрование:** шифруйте snapshot при хранении (GPG, age) — снимок содержит все секреты.
4. **Тестирование:** регулярно тестируйте restore на выделенном стенде (Сценарий 6).
5. **Off-site:** храните копию в отдельном дата-центре / на удалённом хосте; проверяйте доступ к SSH/rsync-хранилищу.
6. **RTO/RPO:** определите RTO и RPO для каждого типа сбоя; частота снимков ≤ RPO.
7. **Документация:** документируйте процедуры restore + доступ к unseal-ключам и root-токену.
8. **Retention:** удаляйте старые snapshot (`find -mtime +N -delete`); храните минимум один «golden» snapshot после крупного изменения.
9. **Мониторинг:** алерты на сбой cron-задачи, рост размера snapshot, доступность off-site-копии.

## Дополнительная информация

*   **[Обзор HashiCorp Vault](../overview.md)** — архитектура и ключевые преимущества.
*   **[Основные концепции Vault](../concepts.md)** — Raft, Seal/Unseal, HA.
*   **[Установка Vault](./vault_installation.md)** — DR checklist, troubleshooting.
*   **[Производительность и репликация](./performance_and_replication.md)** — DR Replication.
*   **[Zero Trust](../zero_trust.md)** — роль бэкапов в архитектуре нулевого доверя.
*   [Vault — управление snapshot (оф.)](https://developer.hashicorp.com/vault/docs/sysadmin/snapshots)
*   [vault operator raft snapshot — CLI (оф.)](https://developer.hashicorp.com/vault/docs/commands/operator/raft)
*   [Recover from lost quorum (оф. туториал)](https://developer.hashicorp.com/vault/tutorials/raft/raft-lost-quorum)
*   [Restore a snapshot (оф.)](https://developer.hashicorp.com/vault/docs/sysadmin/snapshots/restore)
