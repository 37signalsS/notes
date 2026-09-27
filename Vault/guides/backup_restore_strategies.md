# Стратегии резервного копирования и восстановления Vault

## Определения

**RPO (Recovery Point Objective)** — максимально допустимая потеря данных при восстановлении. Например, RPO 1 час означает, что при сбое можно потерять до 1 часа данных.

**RTO (Recovery Time Objective)** — максимально допустимое время восстановления сервиса. Например, RTO 4 часа означает, что сервис должен быть восстановлен в течение 4 часов.

**Snapshot** — моментальный снимок состояния Vault (все секреты, политики, конфигурация). В Vault snapshot сохраняется в виде файла.

**3-2-1 Backup Rule** — правило резервного копирования: 3 копии данных, на 2 разных носителях, 1 копия в off-site хранилище.

**Immutable Backup** — неизменяемая резервная копия, защищённая от удаления или изменения (WORM — Write Once Read Many).

**Disaster Recovery (DR)** — процесс восстановления после катастрофического сбоя (потеря дата-центра, повреждение данных).

**Point-in-Time Recovery** — восстановление состояния Vault на конкретный момент времени.

## Основные концепции

### Типы резервного копирования

| Тип | Описание | RPO | RTO | Использование |
| :--- | :--- | :--- | :--- | :--- |
| **Snapshot** | Моментальный снимок Raft-хранилища | Низкий (минуты) | Низкий (минуты) | Production |
| **Continuous Backup** | Непрерывное репликация | Минимальный | Минимальный | Critical production |
| **Periodic Backup** | Плановые бэкапы по расписанию | Средний (часы) | Средний (часы) | Standard production |

### Стратегии восстановления

| Стратегия | Описание | RTO | Сложность |
| :--- | :--- | :--- | :--- |
| **Восстановление на том же узле** | Восстановление из snapshot на текущем сервере | Низкий | Низкая |
| **Восстановление на новом узле** | Восстановление на другом сервере в кластере | Средний | Средняя |
| **Восстановление в новом кластере** | Полное восстановление в отдельном кластере | Высокий | Высокая |
| **DR Replication** | Переключение на DR Secondary кластер | Минимальный | Высокая |

## Практические сценарии

### Сценарий 1: Создание и хранение snapshot

#### Создание snapshot

```bash
# Создание snapshot Raft-хранилища
vault operator raft snapshot save /opt/vault/backups/vault-$(date +%Y%m%d-%H%M).snap

# Проверка целостности snapshot
vault operator raft snapshot inspect /opt/vault/backups/vault-$(date +%Y%m%d-%H%M).snap
# → Snapshot valid: true
# → Entries: 1523
# → Last Modified: 2026-09-24T10:00:00Z
```

#### Планирование snapshot через cron

```bash
# /etc/cron.d/vault-backup
0 2 * * * vault operator raft snapshot save /opt/vault/backups/vault-$(date +\%Y\%m\%d).snap
0 2 * * * find /opt/vault/backups -name "vault-*.snap" -mtime +7 -delete
```

#### Хранение snapshot

```bash
# Копирование в S3 (или другое объектное хранилище)
aws s3 cp /opt/vault/backups/vault-$(date +%Y%m%d).snap s3://vault-backups/

# Или через rclone
rclone copy /opt/vault/backups/ backup-remote:vault/
```

### Сценарий 2: Восстановление из snapshot

#### Восстановление на том же сервере

```bash
# 1. Остановка Vault
sudo systemctl stop vault

# 2. Удаление текущих данных (или перемещение)
mv /opt/vault/data /opt/vault/data.old

# 3. Восстановление из snapshot
vault operator raft snapshot restore /opt/vault/backups/vault-20230924.snap

# 4. Запуск Vault
sudo systemctl start vault

# 5. Распечатывание
vault operator unseal <key_1>
vault operator unseal <key_2>
vault operator unseal <key_3>
```

#### Восстановление на новом сервере

```bash
# 1. Установка Vault на новом сервере
sudo apt install vault

# 2. Копирование snapshot
scp /opt/vault/backups/vault-20230924.snap user@new-server:/opt/vault/backups/

# 3. Настройка конфигурации (аналогичной исходной)
sudo cp /etc/vault.d/vault.hcl /etc/vault.d/vault.hcl.backup

# 4. Восстановление
sudo systemctl stop vault
vault operator raft snapshot restore /opt/vault/backups/vault-20230924.snap
sudo systemctl start vault

# 5. Распечатывание
vault operator unseal <key_1>
vault operator unseal <key_2>
vault operator unseal <key_3>
```

### Сценарий 3: Восстановление после потери кворума

```bash
# Проверка статуса
vault status
# → Error: cluster has lost quorum

# Вариант 1: восстановление из snapshot
vault operator raft snapshot restore /opt/vault/backups/vault-latest.snap

# Вариант 2: ручная правка peers.json
# 1. Остановка Vault
sudo systemctl stop vault

# 2. Редактирование /opt/vault/data/raft/peers.json
# Удалить недоступные узлы, оставить только доступные

# 3. Запуск и распечатывание
sudo systemctl start vault
vault operator unseal <key_1>
vault operator unseal <key_2>
vault operator unseal <key_3>
```

### Сценарий 4: DR Replication (Enterprise)

```bash
# Настройка DR Primary
vault write -f sys/replication/dr/primary/enable

# Настройка DR Secondary
vault write -f sys/replication/dr/secondary/enable \
    primary_api_addr="https://vault-primary.example.com:8200"

# Аварийное восстановление через DR Secondary
vault write -f sys/replication/dr/secondary/promote
# → Success! Data written to: sys/replication/dr/secondary/promote

# После promote: DR Secondary становится активным
vault read sys/replication/dr/status
# → state | active
```

### Сценарий 5: Point-in-Time Recovery

```bash
# Восстановление на конкретный момент времени
# (требуется Enterprise с Persistent WAL)

# 1. Остановка Vault
sudo systemctl stop vault

# 2. Восстановление с указанием времени
vault operator raft snapshot restore \
    /opt/vault/backups/vault-20230924.snap \
    -recovery-timestamp="2026-09-24T12:00:00Z"

# 3. Запуск Vault
sudo systemctl start vault
```

### Сценарий 6: Тестирование восстановления

Регулярно тестируйте процесс восстановления:

```bash
#!/bin/bash
# test-restore.sh

# 1. Создание тестового snapshot
vault operator raft snapshot save /tmp/test-restore.snap

# 2. Восстановление на тестовом сервере
vault operator raft snapshot restore /tmp/test-restore.snap

# 3. Проверка
vault status
vault kv get secret/myapp/config

# 4. Очистка
rm /tmp/test-restore.snap
```

### Сценарий 7: Восстановление отдельных секретов

```bash
# Просмотр snapshot без распечатывания
vault operator raft snapshot inspect /opt/vault/backups/vault-20230924.snap

# Экспорт конкретного секрета (Enterprise)
vault operator raft snapshot export /opt/vault/backups/vault-20230924.snap \
    -path=secret/data/myapp/config \
    -output=/tmp/myapp-config.json

# Или через API
vault read -format=json secret/myapp/config | jq '.data.data' > myapp-config-backup.json
```

## Лучшие практики

1. **3-2-1 правило:** 3 копии, на 2 носителях, 1 off-site.
2. **Автоматизация:** Настройте автоматическое создание snapshot через cron.
3. **Шифрование:** Шифруйте snapshot при хранении (GPG, age).
4. **Тестирование:** Регулярно тестируйте процесс восстановления.
5. **Off-site:** Храните копии в отдельном дата-центре или облаке.
6. **Документация:** Документируйте процедуры восстановления.
7. **RTO/RPO:** Определите RTO и RPO для каждого типа сбоя.

## Ограничения и известные проблемы

- **Raft snapshot:** Содержит все данные Vault (секреты, политики, конфигурацию). Храните в защищённом месте.
- **Consul snapshot:** При использовании Consul бэкенда бэкапите и Consul.
- **Enterprise функции:** Point-in-Time Recovery и Secret Recovery доступны только в Enterprise.
- **Размер snapshot:** Большие snapshot (>10 GB) могут долго восстанавливаться.
- **Совместимость:** Snapshot версии Vault должен совпадать с версией восстановления.

## Дополнительная информация

*   **[Обзор HashiCorp Vault](../overview.md)** — архитектура и хранение.
*   **[Основные концепции Vault](../concepts.md)** — Raft, Seal/Unseal.
*   **[Установка Vault](../guides/vault_installation.md)** — стратегии бэкапов.
*   **[Производительность и репликация](./performance_and_replication.md)** — DR Replication.
*   **[Zero Trust](../zero_trust.md)** — роль бэкапов в архитектуре нулевого доверия.
*   [Официальная документация по бэкапам](https://developer.hashicorp.com/vault/docs/enterprise/backup-restore)
