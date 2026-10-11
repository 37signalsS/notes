# Резервное копирование и восстановление (DR)

**Актуально для:** Consul 2.0.x / 1.22.x / 1.21.x / 1.20.x / 1.19.x

## Определения

**Disaster Recovery (DR)** в Consul — это совокупность процессов и инструментов, направленных на минимизацию времени простоя и предотвращение потерь данных при катастрофических сбоях: потеря всех серверов, повреждение дисков, человеческая ошибка. Основным механизмом защиты является **Snapshot** — атомарный снимок состояния кластера, включающий KV, ACL, каталог сервисов, подготовленные запросы (prepared queries) и сессии.

## Как это работает

Snapshot создается на уровне Raft-консенсуса. Когда выполняется `consul snapshot save`, лидер кластера формирует атомарную точку восстановления (FSM snapshot) на основе текущего зафиксированного индекса лога. Процесс:

1. Сервер-лидер записывает временный файл снапшота в `data_dir` (по умолчанию `/opt/consul/data`).
2. После завершения записи временный файл отправляется CLI-клиенту и удаляется с сервера.
3. Размер снапшота пропорционален объему состояния кластера; при больших объемах операция создает дополнительную нагрузку на дисковую подсистему.

**Ограничения:**
- Снапшот не защищает от потери данных, записанных после момента создания копии.
- Восстановление (`consul snapshot restore`) требует, чтобы новый кластер работал под той же версией Consul, что и исходный.
- Операция restore — низкоуровневая Raft-команда, не предназначенная для работы в деградированном кластере с отказавшими серверами.
- При включенных ACL для создания снапшота требуется токен с правами `management`.

## Предварительные требования

- **Кластер:** 3 или 5 серверов Consul для HA. Кворум: `(N/2)+1`.
- **Диск:** SSD/NVMe с задержкой `fsync` < 10ms. Raft блокируется на `fsync` при записи.
- **Сеть:** Низкая задержка между серверами (< 10ms для LAN).
- **ACL:** Включены. Для `snapshot save` и `snapshot restore` требуется токен с ACL `management`.
- **Time synchronization:** NTP/Chrony на всех серверах.
- **Хранилище:** Внешнее хранилище (NFS, NAS, S3-совместимое) для выгрузки файлов `.snap` за пределы кластера.

## Практические сценарии

### 1. Автоматизация бэкапов (Community Edition)

Поскольку в OSS-версии нет встроенного агента бэкапов, используется системный `cron` или внешний планировщик.

#### Скрипт бэкапа (`consul-backup.sh`)

```bash
#!/bin/bash
set -euo pipefail

BACKUP_DIR="/var/backups/consul"
TIMESTAMP=$(date +%Y%m%d%H%M)
FILENAME="${BACKUP_DIR}/consul-${TIMESTAMP}.snap"

# Recommended: use token file instead of inline secret
export CONSUL_HTTP_TOKEN_FILE="/etc/consul.d/backup-token"

mkdir -p "$BACKUP_DIR"

# Snapshot with -stale allows backup from any server, not only leader
consul snapshot save -stale "$FILENAME"
# → Saved and verified snapshot to index <INDEX>

# Optional: append version and datacenter to filename for traceability
# consul snapshot save -append-filename version,dc "$FILENAME"

# Cleanup old backups (older than 7 days)
find "$BACKUP_DIR" -type f -name "*.snap" -mtime +7 -delete

# Upload to external storage (example)
```

**Systemd timer alternative (recommended over cron):**

```ini
# /etc/systemd/system/consul-backup.service
[Unit]
Description=Consul snapshot backup
After=network-online.target consul.service

[Service]
Type=oneshot
User=consul
Group=consul
ExecStart=/usr/local/bin/consul-backup.sh
```

```ini
# /etc/systemd/system/consul-backup.timer
[Unit]
Description=Run Consul backup every hour

[Timer]
OnCalendar=*-*-* *:00:00
Persistent=true

[Install]
WantedBy=timers.target
```

```bash
systemctl daemon-reload
systemctl enable --now consul-backup.timer
# → Created symlink, started timer
```

### 2. Автоматизация бэкапов (Enterprise)

Consul Enterprise предоставляет `snapshot agent`, который работает как демон и берет на себя управление расписанием и ретеншеном.

```json
{
  "snapshot_agent": {
    "http_addr": "127.0.0.1:8500",
    "token": "YOUR_ACL_TOKEN",
    "snapshot": {
      "interval": "1h",
      "retain": 24
    }
  }
}
```

## Сценарии восстановления (Disaster Recovery)

### Сценарий 1: Восстановление на новом кластере (Total Loss)

Используется, если все старые серверы утеряны и развернуты новые узлы с новыми IP-адресами.

**Важно:** Новый кластер должен работать под той же версией Consul, что и кластер, из которого создавался снапшот.

#### Шаг 1: Принудительное формирование кворума (`peers.json`)

Чтобы выполнить команду `restore`, в новом кластере должен быть выбран лидер. Для этого создается файл `peers.json`.

1. Остановите Consul на всех новых серверах.
2. Узнайте ID каждого узла. Путь зависит от `data_dir` в конфигурации. По умолчанию:
   ```bash
   cat /opt/consul/data/node-id
   # → <server-uuid>
   ```
3. Создайте файл `/opt/consul/data/raft/peers.json` на одном из серверов. Используйте только выжившие/новые узлы:
   ```json
   [
     {
       "id": "UUID-1",
       "address": "10.0.1.10:8300",
       "non_voter": false
     },
     {
       "id": "UUID-2",
       "address": "10.0.1.11:8300",
       "non_voter": false
     },
     {
       "id": "UUID-3",
       "address": "10.0.1.12:8300",
       "non_voter": false
     }
   ]
   ```
4. Запустите Consul. Файл `peers.json` будет поглощен, и кластер выберет лидера.
   ```bash
   # → agent.server: found peers.json file, recovering Raft configuration...
   # → agent.server: raft recovery found new config
   # → agent.server: raft recovery deleted peers.json
   ```

#### Шаг 2: Восстановление данных

1. Выполните восстановление с помощью management-токена:
   ```bash
   export CONSUL_HTTP_TOKEN_FILE="/etc/consul.d/management-token"
   consul snapshot restore backup.snap
   # → Restored snapshot
   ```
   При включенных ACL восстановление требует токен с правами `management`. Токен из старого кластера сохраняется в снапшоте и будет восстановлен вместе с данными.

2. Проверьте результат:
   ```bash
   consul operator raft list-peers
   # → вывод таблицы с voter status, leader status

   consul kv get config/app/db_url
   # → проверка наличия данных

   consul services
   # → проверка каталога сервисов
   ```

#### Шаг 3: Очистка после восстановления

- Убедитесь, что gossip-ключ (`encrypt` в `consul.hcl`) совпадает со старым кластером. При несовпадении узлы не смогут обмениваться данными.
- Добавьте недостающие серверы через Learner role, чтобы избежать повторного потери кворума.
- Удалите тестовые снапшоты из `data_dir`, если они больше не нужны.

### Сценарий 2: Потеря кворума (Quorum Loss)

Если часть серверов жива, но их недостаточно для большинства (например, 1 из 3), кластер переходит в режим read-only для `stale` чтений.

1. Остановите выживший сервер.
2. Создайте `peers.json`, содержащий только этот один сервер, с полем `non_voter: false`.
3. Запустите его. Он станет лидером в кластере из одного узла.
   ```bash
   # → agent.server: found peers.json file, recovering Raft configuration...
   ```
4. Добавьте новые пустые серверы через Learner role. Autopilot автоматически повысит их до `voter` после синхронизации.

## Устранение неполадок

### Снапшот не создается: Permission denied

**Причина:** При включенных ACL для `snapshot save` требуется токен с правами `management`.
```bash
# Проверка прав токена
consul acl token info <TOKEN>
# → PolicyID должен содержать management права
```

### Восстановление падает с ошибкой версии

**Причина:** Новый кластер работает под другой версией Consul. Восстановление требует совпадения версий.
```bash
# Проверка версии на старом и новом кластере
consul version
# → Consul v1.22.3
```

### Низкая производительность при создании снапшота

**Причина:** Частые или большие снапшоты создают пиковую нагрузку на диск. Consul записывает временный файл в `data_dir` перед отправкой.
```bash
# Мониторинг диска
iostat -x 1 5
# → await должен оставаться < 10ms

# Увеличение порога компакции (снижает частоту снапшотов)
# server.hcl
performance {
  snapshot_threshold = 32768
}
```

### После restore серверы не образуют кворум

**Причина:** Неверный формат `peers.json` или отсутствует gossip-ключ.
```bash
# Проверка gossip-ключа
grep encrypt /etc/consul.d/consul.hcl
# → ключ должен совпадать со старым кластером

# Проверка формата peers.json
cat /opt/consul/data/raft/peers.json
# → поле non_voter: false, адрес: порт
```

## Лучшие практики

- **Снапшот перед изменениями:** Всегда делайте ручной бэкап перед обновлением версии или масштабными правками в KV.
- **Хранение ключей:** Снапшот шифрует данные внутри, но не шифрует сам файл. Для защиты используйте шифрование на уровне хранилища (GPG, LUKS, storage-level encryption).
- **Проверка бэкапов:** Периодически проверяйте валидность файлов:
  ```bash
  consul snapshot inspect backup.snap
  # → вывод размера, индекса, версии Raft
  ```
- **Версионное соответствие:** Храните снапшоты рядом с версией Consul, которой они были созданы. Восстановление на отличную версию не поддерживается.
- **Внешнее хранилище:** Выгружайте снапшоты за пределы кластера сразу после создания. Локальная копия не защищает от потери сервера.
- **Gossip Encryption:** При восстановлении на новые узлы убедитесь, что в конфиге `consul.hcl` указан тот же `encrypt` ключ, что был на старом кластере.
- **Learners при расширении:** Используйте Learner role при добавлении новых серверов после восстановления, чтобы предотвратить потерю кворума.

## Граничные случаи

- **Восстановление на новую major-версию:** Не поддерживается. Требуется совпадение версий Consul между кластерами.
- **Частые снапшоты на больших кластерах:** Могут вызывать IO-задержки и потерю лидерства. Увеличьте `snapshot_threshold` или используйте `-stale` для снижения нагрузки на лидера.
- **Снапшот при деградации кластера:** Используйте `-stale` для создания снапшота с фолловера, если лидер недоступен.
- **Enterprise Redundancy Zones:** При использовании зон избыточности `peers.json` должен учитывать распределение серверов по AZ.

## Дополнительная информация

- **[Консенсус Raft](./consul_consensus.md)** — подробнее о механизмах кворума, `peers.json` и WAL.
- **[Продуктовое развертывание](./consul-deployment.md)** — базовая конфигурация узлов, systemd, ACL bootstrap.
- **[Consul Backup Verification](./consul_backup_verification.md)** — методика проверки целостности бэкапов.
- **[Consul Upgrade и Migration](./consul_upgrade_migration.md)** — обновление кластеров без потерь.
- **[Официальная документация: Snapshots](https://developer.hashicorp.com/consul/docs/commands/snapshot)**.
- **[Официальная документация: Backup and restore](https://developer.hashicorp.com/consul/docs/manage/disaster-recovery/backup-restore)**.
