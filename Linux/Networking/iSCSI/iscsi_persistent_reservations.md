# iSCSI: SCSI-3 Persistent Reservations

Руководство по настройке и использованию SCSI-3 Persistent Reservations (PR) для координации доступа к iSCSI LUN несколькими инициаторами.

## Определения

| Термин | Описание |
| :--- | :--- |
| **SCSI-3 PR (Persistent Reservations)** | Механизм блокировки доступа к LUN на уровне SCSI-протокола. Позволяет нескольким инициаторам безопасно совместно использовать один LUN, гарантируя, что только один хост выполняет запись в определённый момент. |
| **Registration** | Регистрация инициатора в PR-списке LUN. Каждый инициатор получает уникальный **PR Key** (8 байт), который используется для всех последующих операций. |
| **Reservation** | Резервирование LUN для зарегистрированного инициатора. Другие инициаторы не могут выполнять операции записи до снятия резервирования. |
| **Preempt** | Принудительное изъятие резервирования у другого инициатора. Используется при failover: новый мастер забирает LUN у старого. |
| **Holder (Владелец)** | Инициатор,拥有ующий текущее резервирование LUN. Единственный, кто может выполнять запись. |
| **sg_persist** | Утилита командной строки из пакета `sg3_utils` для управления SCSI-3 PR. |
| **Move (Перемещение)** | Операция передачи регистрации из одного инициатора в другой (используется при миграции сессий). |

## Зачем нужен SCSI-3 PR

### Проблема: одновременная запись без PR

Когда два или более инициатора подключены к одному LUN без PR, каждый видит устройство как своё. Параллельная запись приводит к:

- **Повреждению данных:** Два хоста пишут в одни и те же блоки без синхронизации
- **Потере целостности ФС:** Файловая система на каждом хосте считает себя единственным владельцем
- **Reservation Conflict:** При попытке записи возникает SCSI-ошибка `Reservation Conflict` (Sense Key 0x0E)

### Решение: PR как аппаратный мьютекс

SCSI-3 PR работает как распределённая блокировка на уровне оборудования:

```text
┌─────────────────────────────────────────────────────────────┐
│                     iSCSI LUN (500 GB)                      │
├─────────────────────────────────────────────────────────────┤
│  PR-список (аппаратный на массиве/таргете):                 │
│  ┌─────────────────────────────────────────────────────┐    │
│  │ Registration: iqn...:node01  Key=0xABC1  ← Master  │    │
│  │ Registration: iqn...:node02  Key=0xDEF2  ← Standby │    │
│  │ Reservation: Holder=node01   Type=Write Exclusive   │    │
│  └─────────────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────────────┘

node01: ✅ Может писать (является Holder)
node02: ❌ Получит Reservation Conflict при попытке записи
```

## Типы резервирований (Reservation Types)

| Тип | Код | Описание | Применение |
| :--- | :--- | :--- | :--- |
| **Write Exclusive** | `0x01` | Только один инициатор может писать. Остальные — только чтение. | Single-writer ( 기본) |
| **Write Exclusive, Registrants Only** | `0x03` | Только зарегистрированные инициаторы могут писать. Незарегистрированные — нет доступа. | Кластеры с несколькими узлами |
| **Exclusive Access** | `0x05` | Только один инициатор имеет полный доступ (чтение + запись). | Монопольный доступ |
| **Exclusive Access, Registrants Only** | `0x06` | Зарегистрированные инициаторы имеют полный доступ. | Кластеры с failover |
| **Write Exclusive, All Registrants** | `0x07` | Все зарегистрированные инициаторы могут писать одновременно. | Балансировка нагрузки (редко) |
| **Exclusive Access, All Registrants** | `0x08` | Все зарегистрированные инициаторы имеют полный доступ. | Мульти-мастер (редко) |

**Рекомендация для iSCSI-кластеров:** `Write Exclusive, Registrants Only` (0x03) или `Exclusive Access, Registrants Only` (0x06).

## Операции SCSI-3 PR

### Полный цикл операций

```text
1. REGISTER     — Инициатор регистрируется в PR-списке LUN
                   (получает PR Key, связанный с его IQN)
2. RESERVE      — Инициатор резервирует LUN для себя
                   (становится Holder)
3. I/O          — Holder выполняет операции чтения/записи
4. RELEASE      — Holder снимает резервирование
5. PREEMPT      — Другой инициатор принудительно забирает LUN
                   (при failover)
6. CLEAR        — Полная очистка всех PR-записей
                   (опасно, используется при восстановлении)
```

### Детали операций

| Операция | Описание | Когда использовать |
| :--- | :--- | :--- |
| **Register** | Добавить инициатора в PR-список с новым ключом | При первом подключении к LUN |
| **Register with existing key** | Обновить существующую регистрацию | После ребута инициатора |
| **Unregister** | Удалить инициатора из PR-списка | При отключении от LUN |
| **Reserve** | Зарезервировать LUN для зарегистрированного инициатора | При захвате мастерства |
| **Release** | Снять резервирование (но регистрация остаётся) | При плановом отключении |
| **Preempt** | Принудительно забрать LUN у текущего Holder | При failover |
| **Preempt and Abort** | Забрать LUN и отменить все команды предыдущего Holder | При аварийном failover |
| **Clear** | Удалить все регистрации и резервирования | Только при восстановлении после сбоя |

## Практические сценарии

### Сценарий 1: Проверка текущих PR на LUN

```bash
# Просмотр всех PR-записей на LUN
sudo sg_persist -r /dev/sda

# Пример вывода:
# PR Generation=0x5, Reservation follows
#   Key=0xABCDEF0123456789  scope=LU  type=Write Exclusive, Registrants Only
# intl_0 svc_action=0x0  (there are 1 registered reservation keys)
#   0xABCDEF0123456789  (_initiator: iqn.2026-07.com.example:node01)
```

### Сценарий 2: Регистрация и резервирование (активный узел)

```bash
# 1. Генерация уникального PR Key (8 байт)
PR_KEY=$(printf "0x%016x" $((RANDOM * RANDOM)))
echo "PR Key: $PR_KEY"
# → PR Key: 0x1A2B3C4D5E6F7A8B

# 2. Регистрация в PR-списке LUN
sudo sg_persist -s -I 0x$PR_KEY /dev/sda
# → Registers with its company=0x0, service_action=0x1 (SPC2), pr_type=0, scope=0

# 3. Резервирование LUN (Write Exclusive, Registrants Only)
sudo sg_persist -W -T 5 -K 0x$PR_KEY /dev/sda
# → Reserves with its company=0x0, service_action=0x0 (Write Exclusive, Registrants Only), scope=0

# 4. Проверка результата
sudo sg_persist -r /dev/sda
# → Reservation follows: Key=0x1A2B3C4D5E6F7A8B, type=Write Exclusive, Registrants Only
```

### Сценарий 3: Failover — Preempt на другом узле

Когда активный узел (node01) недоступен, резервный (node02) должен забрать LUN:

```bash
# На node02: регистрация (если ещё не зарегистрирован)
sudo sg_persist -s -I 0x$PR_KEY /dev/sda

# Preempt: забрать LUN у node01
sudo sg_persist --preempt --abort -T 5 \
  -K 0x$PR_KEY -I 0xOLD_KEY_NODE01 /dev/sda
# → Preempts with its company=0x0, service_action=0x6 (Preempt and Abort)
# Все команды node01 отменены, node02 становится Holder

# Проверка
sudo sg_persist -r /dev/sda
# → Reservation follows: Key=0x$PR_KEY (node02), type=Write Exclusive, Registrants Only
```

### Сценарий 4: Автоматизация PR для Pacemaker (Resource Agent)

Pacemaker использует OCF-агент `pr` для автоматического управления PR:

```bash
# Создание ресурса PR в Pacemaker
sudo pcs resource create iscsi_pr ocf:heartbeat:pr \
  path="/dev/sda" \
  reservations_key="0x1A2B3C4D5E6F7A8B" \
  reservations_type="5" \
  op monitor interval="30s" timeout="20s"

# Привязка PR к IP и файловой системе
sudo pcs constraint colocation add iscsi_pr with VIP INFINITY
sudo pcs constraint order VIP then iscsi_pr
```

### Сценарий 5: Ручное управление через targetcli (LIO)

```bash
# На стороне target: настройка PR для конкретного LUN
sudo targetcli
/iscsi/iqn.2026-07.com.example:storage.target01/tpg1/luns/lun0 \
  set attribute reservation_type=pr

# Просмотр PR-состояния
cat /sys/kernel/config/target/iscsi/*/tpg1/luns/*/pr/res_aptpl_metadata
```

### Сценарий 6: Полная очистка PR (восстановление)

```bash
# ⚠️ ОПАСНО: Удаляет ВСЕ регистрации и резервирования
# Использовать только при восстановлении после сбоя

# На всех инициаторах: отмонтировать ФС
sudo umount /mnt/data

# На одном из инициаторов: полная очистка
sudo sg_persist -C /dev/sda
# → Clear with its company=0x0, service_action=0x0

# Проверка
sudo sg_persist -r /dev/sda
# → No reservations or registrations

# Регистрация заново
sudo sg_persist -s -I 0x$PR_KEY /dev/sda
sudo sg_persist -W -T 5 -K 0x$PR_KEY /dev/sda
```

## Интеграция с кластерными ФС

### GFS2 + SCSI-3 PR

GFS2 требует DLM (Distributed Lock Manager) для координации доступа. DLM работает поверх PR:

```bash
# Настройка DLM
sudo systemctl enable --now dlm

# Создание кластерной ФС
sudo mkfs.gfs2 -p lock_dlm -t mycluster:myfs /dev/sda myfs

# Монтирование
sudo mount -o noatime /dev/sda /mnt/gfs2
```

### OCFS2 + SCSI-3 PR

OCFS2 также использует DLM, но с другим механизмом блокировок:

```bash
# Настройка o2cb кластера
sudo o2cb init-cluster mycluster
sudo o2cb heartbeat-start mycluster

# Создание кластерной ФС
sudo mkfs.ocfs2 -b 4K -C 32K -N 4 -L myfs /dev/sda

# Монтирование
sudo mount -o noatime,cluster_stack=o2cb /dev/sda /mnt/ocfs2
```

## Диагностика проблем

### Типичные ошибки

| Симптом | Причина | Решение |
| :--- | :--- | :--- |
| `Reservation Conflict` | Два инициатора пытаются писать без PR | Настроить PR: `sg_persist -s -I <KEY>` + `sg_persist -W -T 5 -K <KEY>` |
| `sg_persist: Unable to read reserve` | PR не настроены на target | `targetcli .../luns/lun0 set attribute reservation_type=pr` |
| `Preempt failed` | Ключ инициатора не зарегистрирован | Сначала выполнить `sg_persist -s -I <KEY>` |
| `Clear не помогает` | PR хранятся на уровне массива, а не ядра | Выполнить Clear на массиве (hardware-level) |
| Failover не работает | PR Key не сохранён между ребутами | Использовать статический PR Key в конфиге кластера |

### Проверка PR через sysfs (LIO)

```bash
# Просмотр PR-состояния на target
cat /sys/kernel/config/target/iscsi/*/tpg1/luns/*/pr/res_aptpl_metadata

# Просмотр всех registrations
ls /sys/kernel/config/target/iscsi/*/tpg1/luns/*/pr/

# Состояние rtpg (Report Target Port Groups)
cat /sys/kernel/config/target/iscsi/*/tpg1/luns/*/alua_tg_pt_state
```

### Сравнение PR и флагов TPG

| Механизм | Уровень | Управление | Ограничения |
| :--- | :--- | :--- | :--- |
| **SCSI-3 PR** | LUN (аппаратный) | `sg_persist` / Pacemaker | Требует поддержки массивом/таргетом |
| **TPG attributes** | TPG (-targetcli) | `targetcli` | Только управление доступом к TPG |
| **LUN Masking** | LUN (logical) | `targetcli` / array mgmt | Определяет видимость LUN, не порядок записи |

## См. также

- **[Основные концепции iSCSI](./iscsi_concepts.md)** — архитектура протокола
- **[Настройка iSCSI Target](./iscsi_target_setup.md)** — настройка LIO и PR на сервере
- **[Кластерные ФС поверх iSCSI](./iscsi_cluster_fs.md)** — GFS2/OCFS2 с DLM
- **[iSCSI + Pacemaker HA](./iscsi_ha_pacemaker.md)** — автоматизация failover с PR
- **[Диагностика iSCSI](./iscsi_diagnostics.md)** — разбор ошибок Reservation Conflict
