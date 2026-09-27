# Disaster Recovery и BCP для Proxmox VE

## Определения

**RPO (Recovery Point Objective)** -- максимальный объем потерянных данных, приемлемый после аварии. Определяется интервалом бэкапов. RPO = 1 час означает, что после сбоя мы теряем максимум 1 час данных.

**RTO (Recovery Time Objective)** -- максимальное время восстановления сервиса после аварии. RTO = 30 минут означает, что система должна быть восстановлена за полчаса.

**BCP (Business Continuity Plan)** -- план непрерывности бизнеса, описывающий действия при различных сценариях сбоев.

**DR Site (Disaster Recovery Site)** -- резервная площадка для развертывания критичных сервисов при недоступности основного дата-центра.

**Runbook** -- пошаговая инструкция по восстановлению конкретного сервиса при сбое. Должна быть понятна любому инженеру, включая ночные дежурные.

**Hot Standby** -- резервный сайт/сервер, постоянно синхронизирующий данные с основным и готовый к переключению за минуты.

**Cold Site** -- площадка без работающей инфраструктуры. Требует времени на развертывание (часы/дни).

## Теоретический блок

### Классификация сбоев по серьезности

| Уровень | Сценарий | RTO | RPO | Пример |
|---------|----------|-----|-----|--------|
| P0 | Полная потеря сайта | < 4 часа | < 1 час | Пожар, затопление |
| P1 | Потеря узла кластера | < 15 минут | 0 | Выход из строя сервера |
| P2 | Потеря хранилища | < 1 час | < 15 минут | Поломка дискового массива |
| P3 | Потеря VM/данных | < 30 минут | < 1 час | Ошибка конфигурации |
| P4 | Проблемы приложения | < 5 минут | 0 | Crash приложения |

### Архитектура DR для Proxmox

```
Primary Site                    DR Site
┌─────────────────────┐        ┌─────────────────────┐
│  Proxmox Cluster    │        │  Proxmox Cluster    │
│  ┌────────────────┐ │  ZFS   │  ┌────────────────┐ │
│  │ ZFS + Snapshots│─┼───────>│  │ ZFS + Snapshots│ │
│  └────────────────┘ │ Replic │  └────────────────┘ │
│  ┌────────────────┐ │        │  ┌────────────────┐ │
│  │ PBS            │ │  Sync  │  │ PBS            │ │
│  │ ( backups )    │─┼───────>│  │ ( replicas )   │ │
│  └────────────────┘ │        │  └────────────────┘ │
│  ┌────────────────┐ │        │  ┌────────────────┐ │
│  │ Ceph           │ │ Async  │  │ Ceph           │ │
│  │ ( primary )    │─┼───────>│  │ ( secondary )  │ │
│  └────────────────┘ │  DR    │  └────────────────┘ │
└─────────────────────┘        └─────────────────────┘
```

## Практические сценарии

### 1. ZFS Snapshots -- быстрые recovery points

```bash
# Создание снапшота VM
vzdump 101 --mode snapshot --compress zstd --storage local-zfs

# Автоматические снапшоты через cron (каждый час)
# /etc/cron.d/pve-snapshots
0 * * * * root vzdump 101 --mode snapshot --compress zstd --storage local-zfs --prune keep-last=24

# Создание снапшота всех VM
for vmid in $(qm list | awk 'NR>1 {print $1}'); do
    vzdump $vmid --mode snapshot --compress zstd --storage local-zfs --prune keep-last=6
done
```

### 2. ZFS Replication между узлами

```bash
# Настройка SSH-ключей для replication
ssh-keygen -t ed25519 -f /root/.ssh/id_replication -N ""
ssh-copy-id -i /root/.ssh/id_replication root@dr-node

# Создание replication job через CLI
pvesh create /nodes/primary/replication --target dr-node   --type zfs   --source "local-zfs:vm-101-disk-0"   --target "remote-zfs:vm-101-disk-0"   --schedule "*/15 * * * *"   --keep-last 10

# Просмотр replication jobs
pvesh get /nodes/primary/replication --output-format yaml

# Ручной запуск replication
pvesh run replicationjob --jobid 1

# Проверка последнего replication
journalctl -u pve-rsync --since "1 hour ago"
```

### 3. PBS -- централизованные бэкапы

```bash
# Установка PBS (отдельный сервер или VM)
apt install proxmox-backup-server

# Настройка datastore
proxmox-backup-manager datastore create primary /mnt/pbs-backup

# Добавление remote PBS в Proxmox VE
# GUI: Datacenter -> Storage -> Add -> Proxmox Backup Server
# Или CLI:
pvesm add pbs primary-pbs --server pbs.internal --username admin@pbs --password-file /etc/pbs-password --fingerprint "XX:XX:..."

# Настройка бэкапа VM на PBS
# GUI: VM -> Backup -> Add
# Или CLI:
vzdump 101 --mode snapshot --storage primary-pbs --compress zstd --prune keep-last=7,keep-daily=30,keep-monthly=12

# Автоматический бэкап через cron
# /etc/cron.d/pve-backup
30 2 * * * root vzdump 101 --mode snapshot --storage primary-pbs --compress zstd --prune keep-last=7 --mailto admin@company.com
0 3 * * * root vzdump 102 --mode snapshot --storage primary-pbs --compress zstd --prune keep-last=7 --mailto admin@company.com

# Просмотр бэкапов
proxmox-backup-manager backup-list primary

# Восстановление из PBS
qmrestore /mnt/pbs-backup/vzdump-qemu-101-*.pxar 101
```

### 4. Ceph Cross-Site Replication

```bash
# Настройка DR-кластера
# На DR-узле:
pveceph init --network 10.10.10.0/24
pveceph mon create
pveceph mgr create

# Создание CRUSH rule для DR
ceph osd crush rule create-replicated dr-rule default host dr-site

# Настройка async replication (ceph >= 16.2)
ceph osd pool create vm-data 128 128
ceph osd pool create vm-data-dr 128 128

# Включение replication
ceph df pool vm-data
rbd mirror pool enable vm-data dr-site

# Проверка статуса mirror
rbd mirror pool status vm-data
```

### 5. Сценарий: Восстановление после потери узла

```bash
# 1. Определение статуса кластера
corosync-cfgtool -s
pvecluster status

# 2. Если узел не восстанавливается -- удаление из кластьера
# На рабочем узле:
pvecm delnode dead-node

# 3. Восстановление VM с ZFS
# Если ZFS зеркалировался:
zpool import -f rpool
qmrestore /rpool/data/vm-101-disk-0 101

# 4. Восстановление VM с PBS
qmrestore /mnt/pbs-backup/vzdump-qemu-101-*.pxar 101

# 5. Проверка HA
ha-manager status
```

### 6. Сценарий: Восстановление после потери хранилища

```bash
# 1. Проверка ZFS
zpool status
zpool scrub rpool

# 2. Если ZFS pool потерян -- восстановление из снапшотов
zpool import -f rpool
zpool scrub rpool

# 3. Если Ceph -- проверка OSD
ceph osd tree
ceph health detail

# 4. Если OSD в down -- восстановление
ceph osd lost <osd-id> --yes-i-really-mean-it
ceph osd pool set vm-data min_size 1
```

### 7. Сценарий: Восстановление после потери PBS

```bash
# 1. Проверка доступности backup storage
pvesm status

# 2. Если PBS недоступен -- восстановление из ZFS snapshots
zfs list -t snapshot | grep vm-101
zfs rollback rpool/vm-101-disk-0@snap-20240101

# 3. Если PBS восстановлен -- проверка целостности бэкапов
proxmox-backup-manager verify primary

# 4. Пересинхронизация
proxmox-backup-manager sync primary
```

### 8. DR-план -- пошаговая инструкция

```bash
# DR-план для Proxmox Cluster
# Дата проверки: _______________
# Ответственный: _______________

## Шаг 1: Оценка сценария (5 мин)
echo "Проверка статуса кластера..."
corosync-cfgtool -s
pvecluster status
pvesm status

## Шаг 2: Восстановление сети (10 мин)
echo "Проверка сети..."
ip a show
ping -c 3 gateway

## Шаг 3: Восстановление хранилища (15 мин)
echo "Проверка ZFS..."
zpool status
echo "Проверка Ceph..."
ceph health detail
echo "Проверка PBS..."
pvesm status

## Шаг 4: Восстановление VM (30 мин)
echo "Восстановление критичных VM..."
qmrestore /mnt/pbs-backup/vzdump-qemu-101-*.pxar 101
qmrestore /mnt/pbs-backup/vzdump-qemu-102-*.pxar 102

## Шаг 5: Проверка сервисов (15 мин)
echo "Проверка HTTP..."
curl -s http://localhost/health
echo "Проверка БД..."
psql -h localhost -U app -d production -c "SELECT 1"

## Шаг 6: Уведомление (5 мин)
echo "Отправка уведомления..."
mail -s "DR: Services restored" admin@company.com
```

### 9. Тестирование DR-плана

```bash
# Регулярные тесты (ежемесячно)
# 1. Восстановление случайной VM
random_vmid=$(shuf -i 100-200 -n 1)
echo "Тестовое восстановление VM $random_vmid"
qmrestore /mnt/pbs-backup/vzdump-qemu-$random_vmid-*.pxar test-$random_vmid

# 2. Проверка целостности бэкапов
proxmox-backup-manager verify primary --verbose

# 3. Замер времени восстановления
start_time=$(date +%s)
qmrestore /mnt/pbs-backup/vzdump-qemu-101-*.pxar test-recovery
end_time=$(date +%s)
echo "Время восстановления: $((end_time - start_time)) секунд"

# 4. Проверка RPO/RTO
echo "RPO: Проверка интервала бэкапов"
proxmox-backup-manager backup-list primary --limit 10
echo "RTO: Замер времени восстановления"
```

## Диагностика и устранение неполадок

### Бэкап завершается с ошибкой

```bash
# Проверка логов бэкапов
journalctl -u vzdump --since "1 hour ago"

# Проверка доступности хранилища
pvesm status

# Проверка места на хранилище
df -h /mnt/pbs-backup
zfs list

# Ручной запуск с отладкой
vzdump 101 --mode snapshot --storage primary-pbs --compress zstd --debug
```

### Replication не работает

```bash
# Проверка SSH-соединения
ssh -i /root/.ssh/id_replication root@dr-node

# Проверка replication jobs
pvesh get /nodes/primary/replication --output-format yaml

# Просмотр логов replication
journalctl -u pve-rsync --since "1 hour ago"

# Ручной запуск
pvesh run replicationjob --jobid 1
```

### Восстановление PBS не удается

```bash
# Проверка fingerprint
proxmox-backup-manager cert info

# Проверка SSL сертификата
openssl s_client -connect pbs.internal:8007

# Переподключение PBS
pvesm remove primary-pbs
pvesm add pbs primary-pbs --server pbs.internal --username admin@pbs --fingerprint "XX:XX:..."
```

### 10. Сценарий: Восстановление после нестабильного обновления ядра (kernel panic)

**Ситуация**: после обновления PVE до свежей версии ядра (например, 7.0.0.3) система перестала загружаться и стабильно уходила в kernel panic. Откат на предыдущее ядро через GRUB не сработал.

**Действия**:

1. **Переустановка узла**: при невозможности загрузки единственным рабочим вариантом оказалась переустановка ноды PVE с нуля.
2. **Подключение к PBS**: после переустановки PBS был установлен отдельно, подключен существующий Datastore на NAS, и все VM/LXC восстановлены из резервных копий.
3. **Проверка**: убедитесь, что все сервисы запущены и данные целы.

```bash
# После переустановки: проверка доступности PBS
pvesm status

# Восстановление критичных VM
qmrestore /mnt/pbs-backup/vzdump-qemu-101-*.pxar 101

# Проверка целостности бэкапов на PBS
proxmox-backup-manager verify primary
```

**Вывод**: наличие протестированных резервных копий на PBS (особенно offsite на NAS) превращает потенциальную катастрофу с потерей всей инфраструктуры в формальное восстановление за несколько часов.

> **Предупреждение**: свежие сборки ядра Proxmox VE могут содержать критические ошибки, приводящие к kernel panic и невозможности загрузки. Всегда тестируйте обновления ядра на тестовом узле перед применением к production, и храните бэкапы на независимом хранилище (PBS на отдельном сервере или NAS).

## Лучшие практики

1. **3-2-1 Rule**: 3 копии данных, на 2 разных носителях, 1 offsite. PBS + ZFS snapshots + Ceph replication.

2. **RPO/RTO определение**: Для каждой VM/сервиса определите RPO/RTO. Настраивайте бэкапы и replication исходя из них.

3. **Автоматизация**: Все бэкапы и replication -- автоматизированы. Ручные операции -- только как крайняя мера.

4. **Тестирование**: Ежемесячно тестируйте восстановление из бэкапов. Без тестирования бэкап бесполезен.

5. **Документация**: DR-план должен быть в printed form и в доступном месте (не только на упавшем сервере).

6. **Offsite копии**: Минимум одна копия данных за пределами дата-центра. PBS + remote replication.

7. **Мониторинг бэкапов**: Алерты на пропущенные/неудачные бэкапы. Настройте через [Proxmox Monitoring](./proxmox_monitoring.md).

8. **Шифрование**: Включите шифрование для offsite копий (PBS client-side encryption).

9. **SLA**: Для каждого сервиса определите SLA и соответствующие RPO/RTO. Документируйте.

10. **Post-incident review**: После каждого DR-инцидента проводите ретроспективу и обновляйте план.

## Граничные случаи

- **Split-brain в кластере**: При потве связи между узлами Proxmox использует quorum. Если quorum потерян -- автоматическое отключение VM. Используйте QDevice для нечетных кластеров.

- **Размер бэкапов**: При сжатии zstd бэкапы занимают 30-50% от размера VM. Планируйте место на PBS.

- **Replication lag**: При большой нагрузке на сеть replication может отставать. Мониторьте `replication_time` в логах.

- **VM с blast-radius > 1**: Если одна VM критична для других (DB + App), восстанавливайте их вместе и проверяйте зависимости.

- **Инкрементальные бэкапы**: PBS использует инкрементальные бэкапы. Полный бэкап создается при первом запуске или по расписанию.

## Дополнительная информация

### Связанные темы

- [Proxmox Backup Server](./proxmox_backup_server.md)
- [Обзор кластеризации](./proxmox_cluster.md)
- [Мониторинг и алерты](./proxmox_monitoring.md)
- [Резервное копирование (Ansible)](../Ansible/ansible_core_concepts.md)
