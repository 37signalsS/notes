# LDAP: планирование ёмкости и sizing

## Определения

**Capacity Planning** — процесс определения необходимых аппаратных и программных ресурсов для обеспечения требуемой производительности и доступности LDAP-сервера в зависимости от объёма данных и нагрузки.

**Entry Size** — размер одной записи LDAP в бэкенде. Зависит от количества и типа атрибутов. Типичные значения: 0.5-4 KB для пользовательских записей, до 10 KB для записей с большими атрибутами (jpegPhoto, userCertificate).

**Working Set** — объём данных, который обрабатывается в оперативной памяти для обслуживания типичной нагрузки. Определяется количеством наиболее часто запрашиваемых записей.

**IOPS (Input/Output Operations Per Second)** — количество операций чтения/записи на диск в секунду. Критичен для write-heavy нагрузок (репликация, mass update).

**Concurrent Connections** — одновременные TCP-соединения с LDAP-сервером. Каждое соединение потребляет поток и память.

---

## Базовые концепции

### Факторы, влияющие на sizing

| Фактор | Влияние | Приоритет |
|:---|:---|:---|
| **Количество записей** | Определяет размер БД и необходимый объём RAM для кэша | Критический |
| **Количество атрибутов на запись** | Определяет средний размер записи | Высокий |
| **Частота чтения** | Определяет IOPS и размер entry cache | Высокий |
| **Частота записи** | Определяет IOPS для диска и нагрузку на репликацию | Высокий |
| **Количество клиентов** | Определяет количество соединений и потоков | Средний |
| **Использование индексов** | Отсутствие индексов = полный перебор = высокая нагрузка на CPU/диск | Критический |
| **Репликация** | Дополнительный сетевой трафик и нагрузка на запись | Средний |

### Формулы расчёта

#### Размер базы данных

```text
Размер БД (байты) = Количество записей x Средний размер записи x 1.5 (overhead)
```

Пример:
```text
50,000 записей x 2 KB x 1.5 = 150 MB (MDB)
```

#### Размер RAM для кэша

```text
RAM для entry cache = Количество записей x Средний размер записи x Cache Hit Ratio Target
RAM для DB cache = Размер БД x (1 - Cache Hit Ratio Target)
```

Пример для 50k записей (target 90% cache hit):
```text
Entry Cache = 50,000 x 2 KB x 0.9 = 90 MB
DB Cache = 150 MB x 0.1 = 15 MB
Итого: ~105 MB + overhead (~150 MB рекомендуется)
```

#### Количество потоков

```text
threads = min(2 x CPU_cores, max_connections / 4)
```

Для типичного LDAP-сервера: 8-32 потока.

#### Соединения

```text
max_connections = Количество клиентов x Среднее число соединий на клиента x 2 (запас)
```

### Типичные профили нагрузки

| Профиль | Чтения/сек | Записи/сек | Пример |
|:---|:---|:---|:---|
| **Read-Heavy** | 1,000-10,000 | 10-100 | Аутентификация через SSSD |
| **Write-Heavy** | 100-1,000 | 100-1,000 | Массовое обновление пользователей |
| **Balanced** | 500-5,000 | 50-500 | Смешанная нагрузка |
| **Replication-Heavy** | 1,000-50,000 | 1,000-10,000 | Multi-master с высокой частотой записей |

---

## Практические сценарии

### 1. Sizing для малой организации (1k-10k пользователей)

| Параметр | Рекомендация |
|:---|:---|
| **CPU** | 2 core |
| **RAM** | 2-4 GB |
| **Диск** | 20 GB SSD, RAID 1 |
| **Сеть** | 1 Gbps |
| **Топология** | Single-master + 1 replica |
| **LDAP-реализация** | OpenLDAP 2.6 или 389DS |
| **olcDbMaxSize** | 1 GB |
| **Entry Cache** | 512 MB-1 GB |
| **threads** | 8 |
| **max connections** | 256 |
| **Репликация** | Syncrepl (pull) или 389DS MMR |

```bash
# Пример конфигурации OpenLDAP для 5k пользователей
ldapmodify -Y EXTERNAL -H ldapi:/// <<EOF
dn: olcDatabase={1}mdb,cn=config
changetype: modify
replace: olcDbMaxSize
olcDbMaxSize: 1073741824
-
replace: olcDbIndex
olcDbIndex: objectClass eq
olcDbIndex: uid eq,sub
olcDbIndex: cn eq,sub
olcDbIndex: mail eq,sub
olcDbIndex: memberUid eq
olcDbIndex: entryCSN eq
olcDbIndex: entryUUID eq
EOF
```

### 2. Sizing для средней организации (10k-50k пользователей)

| Параметр | Рекомендация |
|:---|:---|
| **CPU** | 4 core |
| **RAM** | 8-16 GB |
| **Диск** | 100 GB SSD, RAID 10 |
| **Сеть** | 1 Gbps |
| **Топология** | Multi-master (2-3 узла) или Master + 2 replicas |
| **LDAP-реализация** | 389DS или OpenLDAP |
| **olcDbMaxSize** | 10 GB |
| **Entry Cache** | 4-8 GB |
| **threads** | 16 |
| **max connections** | 1024 |
| **Репликация** | 389DS MMR или Syncrepl |

```bash
# 389DS: настройка для 30k пользователей
dsconf -D "cn=Directory Manager" ldap://localhost config replace \
  nsslapd-threadnum=16 \
  nsslapd-sizelimit=5000 \
  nsslapd-timelimit=30 \
  nsslapd-maxdescriptors=4096
```

### 3. Sizing для крупной организации (50k-200k пользователей)

| Параметр | Рекомендация |
|:---|:---|
| **CPU** | 8 core |
| **RAM** | 32-64 GB |
| **Диск** | 500 GB NVMe, RAID 10 |
| **Сеть** | 10 Gbps |
| **Топология** | Multi-master (3+ узлов) + read replicas |
| **LDAP-реализация** | 389DS (recommended) |
| **olcDbMaxSize** | 100 GB |
| **Entry Cache** | 16-32 GB |
| **threads** | 32 |
| **max connections** | 4096 |
| **Репликация** | 389DS MMR с выделенным VLAN |

### 4. Sizing для very large (200k+ пользователей)

| Параметр | Рекомендация |
|:---|:---|
| **CPU** | 16 core |
| **RAM** | 64-128 GB |
| **Диск** | 1 TB NVMe, RAID 10, или несколько БД (partitioning) |
| **Сеть** | 10 Gbps |
| **Топология** | Cascading replication: master -> relay -> consumers |
| **LDAP-реализация** | 389DS |
| **Partitioning** | Разделение по suffix (ou=people, ou=groups отдельно) |

### 5. Определение размера записи (бенчмарк)

```bash
# Экспорт одной типичной записи
ldapsearch -x -H ldap://localhost \
  -D "cn=admin,dc=example,dc=com" -W \
  -b "uid=jdoe,ou=people,dc=example,dc=com" "(objectClass=*)" \
  > /tmp/sample_entry.ldif

# Размер записи в байтах
wc -c /tmp/sample_entry.ldif
# -> 1847 /tmp/sample_entry.ldif

# Средний размер 100 записей
for i in $(seq 1 100); do
  ldapsearch -x -H ldap://localhost \
    -D "cn=admin,dc=example,dc=com" -W -LLL \
    -b "ou=people,dc=example,dc=com" "(objectClass=*)" dn 2>/dev/null | wc -c
done | awk '{sum+=$1; n++} END {print "Avg entry size:", sum/n, "bytes"}'
```

### 6. Проверка текущего использования ресурсов

```bash
# Размер БД OpenLDAP
du -sh /var/lib/ldap/

# Размер БД 389DS
du -sh /var/lib/dirsrv/slapd-localhost/db/

# Количество записей
ldapsearch -x -H ldap://localhost \
  -D "cn=admin,dc=example,dc=com" -W \
  -b "dc=example,dc=com" "(objectClass=*)" dn 2>/dev/null | grep -c "^dn:"

# Текущее использование RAM (389DS)
dsconf -D "cn=Directory Manager" ldap://localhost backend monitoring list

# Текущее использование RAM (OpenLDAP)
ldapsearch -Y EXTERNAL -H ldapi:/// \
  -b "cn=monitor" "(objectClass=*)" olcDbMaxSize olcDbCurrentSize

# Мониторинг соединений
ss -tnp | grep ':389' | wc -l

# Мониторинг потоков (389DS)
dsconf -D "cn=Directory Manager" ldap://localhost config get nsslapd-threadnum
```

### 7. Правило thumb для быстрой оценки

| Параметр | 1k users | 10k users | 50k users | 100k users | 500k users |
|:---|:---|:---|:---|:---|:---|
| **RAM (min)** | 1 GB | 4 GB | 16 GB | 32 GB | 64 GB |
| **RAM (recommended)** | 2 GB | 8 GB | 32 GB | 64 GB | 128 GB |
| **Disk** | 10 GB | 50 GB | 200 GB | 500 GB | 2 TB |
| **CPU** | 1-2 | 2-4 | 4-8 | 8-16 | 16-32 |
| **LDAP servers** | 1+1 | 2+1 | 3+2 | 3+3 | 5+5 |
| **threads** | 4-8 | 8-16 | 16-32 | 32 | 32-64 |
| **maxconn** | 128 | 512 | 2048 | 4096 | 8192 |

Формат: `N+M` = N основных + M реплик.

---

## Дополнительная информация

### Факторы, не учтённые в формулах

- **Синтетические атрибуты** (memberOf, ref) увеличивают размер записи в кэше
- **Changelog** для репликации потребляет дополнительное дисковое пространство
- **Индексы** потребляют 20-50% от размера данных
- **LDIF-бэкапы** требуют отдельного дискового пространства (2x от размера БД)

### Частые ошибки sizing

| Ошибка | Последствие | Решение |
|:---|:---|:---|
| Недостаточно RAM для entry cache | Частые обращения к диску, slow queries | Увеличьте RAM или уменьшите размер кэша |
| Маленький olcDbMaxSize | Ошибка "DB is full" при росте данных | Задайте max size заранее (MDB не расширяется автоматически) |
| Недостаточно потоков | Очередь соединений, timeout | Увеличьте nsslapd-threadnum |
| HDD вместо SSD | Медленная индексация и запись | SSD/NVMe обязателен для production |

### См. также

- **[LDAP Performance Tuning](./ldap_performance_tuning.md)** — оптимизация производительности
- **[LDAP Мониторинг](./ldap_monitoring.md)** — метрики использования ресурсов
- **[389DS: Обзор](./389ds/overview.md)** — архитектура и LMDB
- **[OpenLDAP: установка](./openldap_basics.md)** — настройка cn=config
- **[LDAP Backup и Restore](./ldap_backup_restore.md)** — расчёт дискового пространства для бэкапов
- **[Concepts: Capacity Planning](../Concepts/capacity-planning.md)** — общая методология
