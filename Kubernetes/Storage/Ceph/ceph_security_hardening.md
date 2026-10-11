# Безопасность и hardening Ceph

Руководство по защите кластера Ceph в продакшен-средах: аутентификация, авторизация, шифрование, аудит и сетевой perimeter. Документ актуален для версий **Squid (19.x)**, **Tentacle (20.x)** и **Umbrella (21.x)**.

> **Границы документа:** общее управление ключами CephX описано в [Операциях Ceph](./Administration/operations.md#9-управление-ключами-доступа-cephx); интеграция с Kubernetes — в [PV/PVC Scenarios](../pv_and_pvc_scenarios.md); бэкап — в [Резервном копировании и DR](./ceph_backup_and_dr.md).

## Определения

**CephX** — встроенная аутентификация Ceph, основанная на симметричных ключах (shared secret). Аутентифицирует соединения между клиентами и демонами, но **не шифрует** данные на диске и не защищает трафик от перехвата.

**Messenger v2.1** — современный протокол связи Ceph (с v16+). Поддерживает режимы `crc` (целостность) и `secure` (шифрование AES-GCM). Работает по порту 3300 (v2.1) вместо устаревшего 6789 (v1).

**Encryption at Rest** — шифрование данных на физических носителях. В Ceph реализуется на уровне блокового устройства (dm-crypt/LUKS) или через RBD encryption (LUKS2 на уровне образа).

**RBAC (Role-Based Access Control)** — разграничение прав через CephX caps. Каждый клиент получает минимально необходимые права на конкретные пулы/сервисы.

**Audit Log** — журнал операций кластера, записываемый в `ceph log`. Включает аутентификационные события, изменения конфигурации, административные команды.

## Базовые концепции

### Модель безопасности Ceph

```
┌─────────────────────────────────────────────────────────────┐
│  Безопасность Ceph                                           │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  1. Authentication (CephX)                                   │
│     └── Кто ты? (client.admin, client.rbd, client.cephfs)    │
│                                                             │
│  2. Authorization (Caps)                                     │
│     └── Что можно? (mon, osd, mgr, mds, rgw)                │
│                                                             │
│  3. Encryption in Transit (Messenger v2.1)                   │
│     └── Защита от перехвата (AES-GCM / CRC)                  │
│                                                             │
│  4. Encryption at Rest                                      │
│     └── Шифрование дисков (dm-crypt, LUKS, RBD encryption)  │
│                                                             │
│  5. Network Perimeter                                       │
│     └── Firewall, segmentation, private cluster network      │
│                                                             │
│  6. Audit Logging                                           │
│     └── Кто, что, когда (ceph log audit)                    │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

### CephX: аутентификация и авторизация

CephX использует symmetric key cryptography:
1. Клиент отправляет username на MON.
2. MON генерирует challenge (nonce).
3. Клиент шифрует challenge своим secret key.
4. MON проверяет расшифровку.
5. Если успешно — выдает session key для дальнейших операций.

**Caps (Capabilities)** — права доступа, привязанные к клиенту:

| Сервис | Права | Пример |
|--------|-------|--------|
| `mon` | `r`, `w`, `rw`, `x` (command) | `mon 'allow r'` |
| `osd` | `r`, `w`, `rw`, `x`, `profile *` | `osd 'profile rbd pool=volumes'` |
| `mgr` | `r`, `w`, `rw`, `x` | `mgr 'allow r'` |
| `mds` | `r`, `w`, `rw`, `x` | `mds 'allow r'` |
| `rgw` | `read`, `write`, `read-write` | `rgw 'allow *'` |

## Практические сценарии

### 1. Настройка Messenger v2.1 и шифрование трафика

```bash
# Проверка текущего протокола
ceph config get mon ms_client_mode
# → should be "crc" or "secure"

# Включение secure mode (AES-GCM) для всех демонов
ceph config set global ms_client_mode secure
ceph config set global ms_bind_ipv4 true

# Для конкретного хоста
ceph config set mon host-a ms_client_mode secure

# Проверка портов
ss -tlnp | grep -E '3300|6789'
```

**Рекомендации:**
- `secure` — для untrusted сетей (между дата-центрами, публичные сети).
- `crc` — для доверенных внутренних сетей (в пределах одного ЦОД).

### 2. Firewall и сетевой perimeter

```bash
# Минимальные порты (UDP/TCP)
# MON: 3300 (v2.1), 6789 (v1, legacy)
# OSD: 6800-7300 (range)
# MGR: 6800-7300 (range), 9283 (prometheus)
# MDS: 6800-7300 (range)
# RGW: 7480 (default), 443 (HTTPS)

# firewalld пример
firewall-cmd --permanent --add-port=3300/tcp
firewall-cmd --permanent --add-port=6800-7300/tcp
firewall-cmd --permanent --add-port=9283/tcp
firewall-cmd --permanent --add-port=7480/tcp
firewall-cmd --permanent --add-rich-rule='rule family="ipv4" source address="10.0.0.0/24" port protocol="tcp" port="3300" accept'
firewall-cmd --reload

# Проверка
firewall-cmd --list-all
```

**Сетевая сегментация:**
- Public network (clients, MON, MGR, Dashboard) — отдельный VLAN.
- Cluster network (OSD replication, backfill) — выделенный интерфейс, 10/25/40/100 GbE.
- Запретить доступ к cluster network извне.

### 3. Encryption at Rest

#### 3.1 Шифрование дисков на хостах (dm-crypt/LUKS)

```bash
# На хосте перед созданием OSD
cryptsetup luksFormat /dev/sdb
cryptsetup open /dev/sdb ceph-osd-0
ceph-volume lvm create --data /dev/mapper/ceph-osd-0
```

#### 3.2 RBD encryption (LUKS2 на уровне образа)

```bash
# Создание зашифрованного образа
rbd encryption format kube/encrypted-image luks1

# Подключение с указанием passphrase
rbd map kube/encrypted-image --encryption-format luks1
```

**Рекомендации:**
- Для bare-metal: dm-crypt на уровне дисков (производительность ~5-10% overhead на современных CPU с AES-NI).
- Для виртуализации: RBD encryption или шифрование на уровне гипервизора.
- Ключи шифрования хранятся отдельно от бэкапов.

### 4. CephX: advanced topics

#### 4.1 Принцип минимальных привилегий

```bash
# Плохо: широкие права
ceph auth get-or-create client.rbd mon 'allow rw' osd 'allow *'

# Хорошо: минимальные права
ceph auth get-or-create client.rbd \
  mon 'profile rbd' \
  osd 'profile rbd pool=volumes' \
  mgr 'allow r'
```

#### 4.2 Ротация ключей

```bash
# Список ключей с сроком действия
ceph auth list

# Ротация: пересоздание ключа с теми же caps
ceph auth get-or-create client.rbd -o client.rbd.new.keyring \
  mon 'profile rbd' \
  osd 'profile rbd pool=volumes'

# Удаление старого ключа
ceph auth rm client.rbd
mv client.rbd.new.keyring client.rbd.keyring
```

#### 4.3 Временные ключи (Temporary authorization)

```bash
# Создание ключа с истечением срока
ceph auth add client.temp \
  mon 'allow r' \
  osd 'allow r pool=data' \
  mgr 'allow r' \
  -i /dev/stdin <<EOF
[client.temp]
key = AQ...
expire_time = 2026-10-01 00:00:00
EOF
```

### 5. Audit logging

```bash
# Включение аудита
ceph config set global audit true

# Просмотр аудит-логов
ceph log last 100 audit

# Фильтрация по пользователю
ceph log last 100 audit | grep client.admin

# Настройка ротации логов
ceph config set global log_max_recent 10000
ceph config set global log_to_file true
```

**Что логируется:**
- Аутентификационные события (успешные/неуспешные)
- Изменения конфигурации (`ceph config set`)
- Создание/удаление пулов
- Изменения CRUSH map
- Ротация ключей

### 6. Segregation of Duties

```bash
# Разделение ролей в кластере
# 1. Cluster Administrator (client.admin)
ceph auth get client.admin

# 2. Pool Operator (ограниченный доступ к пулам)
ceph auth get-or-create client.pool-ops \
  mon 'profile rbd' \
  osd 'allow rw pool=*' \
  mgr 'allow r'

# 3. Read-only Monitor
ceph auth get-or-create client.mon-read \
  mon 'allow r' \
  osd 'allow r' \
  mgr 'allow r'

# 4. RGW User (S3 access)
ceph auth get-or-create client.rgw-user \
  mon 'allow r' \
  osd 'allow r' \
  rgw 'allow *'
```

### 7. Обнаружение вторжений (Intrusion Detection)

```bash
# Проверка подозрительных ключей
ceph auth list | grep -E 'AQ[0-9A-Za-z+/]{20,}'

# Мониторинг неудачных аутентификаций
ceph log last 1000 | grep -i "auth.*denied"

# Проверка изменений в crushmap
ceph osd getcrushmap -o /tmp/current.bin
diff /backup/ceph/crushmap-2026-09-29.bin /tmp/current.bin

# Проверка подозрительных демонов
ceph orch ps --format json | jq '.[] | select(.status != "running")'
```

## Лучшие практики

### Аутентификация

1. **Никогда не храните ключи в plain text** в репозиториях/скриптах. Используйте Kubernetes Secrets или внешние KMS.
2. **Ротация ключей** — минимум раз в 90 дней для сервисных аккаунтов.
3. **Принцип минимальных привилегий** — каждый клиент получает только необходимые права на конкретные пулы.
4. **Разделение ролей** — отдельные ключи для администрирования, операций и read-only доступа.

### Шифрование

1. **Messenger v2.1 secure mode** для untrusted сетей.
2. **dm-crypt/LUKS** на уровне дисков для физических серверов.
3. **RBD encryption** для Kubernetes workloads с чувствительными данными.
4. **Ключи шифрования** — отдельное хранилище, ротация, доступ только для DBA.

### Мониторинг

1. **Аудит включен** на всех production кластерах.
2. **Алерты на неудачные аутентификации** — `ceph log last 1000 audit | grep denied`.
3. **Контроль изменений crushmap** — compare с последним бэкапом.
4. **Мониторинг доступных demones** — `ceph orch ps` в Prometheus.

### Резервное копирование

1. **Бэкап auth-экспорта** — `ceph auth export > ceph-auth-$(date +%F).export`.
2. **Бэкап crushmap** — `ceph osd getcrushmap -o crushmap-$(date +%F).bin`.
3. **Бэкап config db** — `ceph config dump -f json-pretty > ceph-config-$(date +%F).json`.

## Дополнительная информация

### См. также

- [Операции Ceph](./Administration/operations.md) — управление ключами CephX
- [Мониторинг Ceph](./Administration/monitoring.md) — audit log, алертинг
- [Резервное копирование и DR](./ceph_backup_and_dr.md) — бэкап состояния кластера
- [Сетевая архитектура](./ceph_networking.md) — firewall, сегментация

### Официальные ресурсы

- [Ceph Security Guide](https://docs.ceph.com/en/latest/security/) — официальное руководство по безопасности
- [CephX Authentication](https://docs.ceph.com/en/latest/rados/configuration/auth-config-ref/) — конфигурация аутентификации
- [Ceph Messenger v2.1](https://docs.ceph.com/en/latest/rados/configuration/ms-config-ref/) — конфигурация протокола связи
