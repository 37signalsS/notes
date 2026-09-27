# LDAP Performance Tuning

## Определения

**Performance Tuning** — процесс оптимизации конфигурации и ресурсов LDAP-сервера для достижения максимальной пропускной способности и минимальной задержки ответов.

**Full Table Scan** — операция поиска без использования индексов, при которой сервер проверяет каждую запись в БД. Приводит к резкому снижению производительности при росте объёма данных.

**Index** — вспомогательная структура данных, ускоряющая поиск по определённому атрибуту. Типы: `eq` (точное совпадение), `sub` (подстрока), `pres` (наличие атрибута).

**Cache Hit Ratio** — процент запросов, обслуженных из кэша без обращения к диску. Целевое значение: выше 85% для entry cache, выше 95% для DB cache.

**Entry Cache** — кэш десериализованных записей LDAP в оперативной памяти.

**DB Cache** — кэш страниц базы данных LMDB/MDB в оперативной памяти.

**Sizelimit** — максимальное количество записей, возвращаемых одним LDAP-поиском.

**Timelimit** — максимальное время выполнения одного LDAP-запроса в секундах.

**Paged Results** — механизм постраничной выборки результатов поиска для обработки больших каталогов без превышения sizelimit.

---

## Базовые концепции

### Иерархия производительности

```text
[ Приложение (клиент) ]
        |
        v
[ Сеть (латентность, пропускная способность) ]
        |
        v
[ LDAP-сервер (slapd / ns-slapd) ]
  +-- Индексы (eq, sub, pres)
  +-- Entry Cache (LRU)
  +-- DB Cache (LMDB pages)
  +-- Дисковая подсистема (SSD/NVMe)
```

### Ключевые факторы влияния

| Фактор | Влияние | Приоритет |
|:---|:---|:---|
| **Индексы** | Отсутствие индекса = full scan | Критический |
| **Кэш** | Низкий hit ratio = частые обращения к диску | Высокий |
| **Диск** | Медленный диск = bottleneck для записи и индексации | Высокий |
| **Сеть** | Латентность > 5ms между репликами | Средний |
| **Память** | LMDB использует mmap; нехватка RAM = swap | Высокий |
| **Конфигурация** | sizelimit, timelimit, количество потоков | Средний |

### Методология анализа

1. **Измерение baseline** — зафиксировать текущие метрики
2. **Поиск bottleneck** — определить узкое место (CPU, RAM, disk, network)
3. **Оптимизация** — внести изменения в порядке приоритета
4. **Валидация** — проверить улучшение и отсутствие регрессий
5. **Мониторинг** — настроить алерты на ключевые метрики

---

## Практические сценарии

### 1. Анализ неиндексированных поисков

Неиндексированные поиски — самая частая причина проблем с производительностью.

**389DS:**

```bash
# Подсчет неиндексированных поисков (notes=U в access log)
grep "notes=U" /var/log/dirsrv/slapd-localhost/access | wc -l

# Какие атрибуты без индексов
grep "notes=U" /var/log/dirsrv/slapd-localhost/access | \
  awk '{for(i=1;i<=NF;i++) if($i ~ /^filter=/) print $i}' | \
  sort | uniq -c | sort -rn | head -20
```

**OpenLDAP:**

```bash
# Включение логирования неиндексированных операций
ldapmodify -Y EXTERNAL -H ldapi:/// <<EOF
dn: olcDatabase={-1}frontend,cn=config
changetype: modify
replace: olcLogLevel
olcLogLevel: stats
EOF

# Анализ логов
grep "unindexed" /var/log/slapd-access.log
```

**Создание индекса для проблемного атрибута (389DS):**

```bash
dsconf -D "cn=Directory Manager" ldap://localhost backend index set \
  --suffix "dc=example,dc=com" \
  --attr employeeNumber --type eq

# Переиндексация (выполнять в часы низкой нагрузки)
dsconf -D "cn=Directory Manager" ldap://localhost backend index reindex \
  --suffix "dc=example,dc=com" userRoot
```

### 2. Минимальный набор индексов

| Атрибут | Тип индекса | Причина |
|:---|:---|:---|
| `objectClass` | `eq` | Фильтрация по классу объектов |
| `uid` | `eq,sub` | Поиск пользователей по логину |
| `cn` | `eq,sub` | Поиск по имени |
| `mail` | `eq,sub` | Поиск по email |
| `sn` | `eq,sub` | Поиск по фамилии |
| `memberOf` | `eq` | Определение групповых членств |
| `entryUUID` | `eq` | Уникальный идентификатор |
| `gidNumber` | `eq` | POSIX-группы |
| `uidNumber` | `eq` | POSIX-пользователи |

**Индексы, которые НЕ нужно создавать:**
- `sub` на атрибутах с низкой кардинальностью
- `approx` (почти никогда не используется)
- Избыточные индексы (если поиск по атрибуту не выполняется)

**Проверка индексов (389DS):**

```bash
dsconf -D "cn=Directory Manager" ldap://localhost backend index list \
  --suffix "dc=example,dc=com" userRoot

# Проверка размера индексов
du -sh /var/lib/dirsrv/slapd-localhost/db/userRoot/*.db
```

### 3. Настройка кэширования

**389DS (LMDB):**

```bash
# Просмотр текущего использования кэша
dsctl localhost memusage

# Автоматическая настройка кэша (% от RAM)
dsconf -D "cn=Directory Manager" ldap://localhost config replace \
  nsslapd-cache-autosize=25

# Ручная настройка (в байтах)
dsconf -D "cn=Directory Manager" ldap://localhost config replace \
  nsslapd-cachememsize=4294967296

# Проверка hit ratio
dsctl localhost monitor | grep -i cache
```

**OpenLDAP (MDB):**

```bash
# Максимальный размер БД (должен быть меньше PV на 10-20%)
ldapmodify -Y EXTERNAL -H ldapi:/// <<EOF
dn: olcDatabase={1}mdb,cn=config
changetype: modify
replace: olcDbMaxSize
olcDbMaxSize: 10737418240
EOF
```

**Целевые значения hit ratio:**

| Кэш | Минимум | Рекомендуется |
|:---|:---|:---|
| Entry Cache | > 85% | > 95% |
| DB Cache | > 90% | > 98% |
| DN Cache | > 85% | > 95% |

### 4. Оптимизация дисковой подсистемы

```bash
# Проверка IOPS и latency
iostat -x 1 10

# Целевые значения:
# %util < 70%
# await < 5ms (для SSD)
# r_await < 2ms, w_await < 3ms

# Отключение atime
# /etc/fstab:
/dev/sdb1 /var/lib/ldap ext4 noatime,nodiratime 0 2

# Проверка I/O планировщика
cat /sys/block/sda/queue/scheduler
# Для SSD: mq-deadline или none (NVMe)
```

**Рекомендации по хранилищу:**
- **Локальный SSD/NVMe** — обязательно для production
- **NFS/SMB** — недопустимы для файлов БД (блокировки LMDB)
- **RAID 10** — рекомендуется для бэкенда
- **Отдельный диск** для логов при высокой нагрузке

### 5. Настройка sizelimit и timelimit

**389DS:**

```bash
dsconf -D "cn=Directory Manager" ldap://localhost config replace \
  nsslapd-sizelimit=5000 \
  nsslapd-pagedsizelimit=5000 \
  nsslapd-timelimit=3600
```

**OpenLDAP:**

```bash
ldapmodify -Y EXTERNAL -H ldapi:/// <<EOF
dn: olcDatabase={1}mdb,cn=config
changetype: modify
replace: olcSizeLimit
olcSizeLimit: 5000
EOF
```

### 6. Оптимизация потоков

**389DS:**

```bash
dsconf -D "cn=Directory Manager" ldap://localhost config replace \
  nsslapd-threadnum=32
```

**OpenLDAP:**

```bash
ldapmodify -Y EXTERNAL -H ldapi:/// <<EOF
dn: cn=config
changetype: modify
replace: olcThreadPoolMax
olcThreadPoolMax: 32
EOF
```

### 7. Анализ через access log

```bash
# 389DS: поиск медленных операций (>100ms)
grep "etime=1" /var/log/dirsrv/slapd-localhost/access | \
  awk -F'etime=' '{print $2}' | cut -d' ' -f1 | sort -rn | head -20

# Подсчет операций по типу
grep -o "op=[0-9]*" /var/log/dirsrv/slapd-localhost/access | \
  awk -F'=' '{print $2}' | sort | uniq -c | sort -rn

# Поиск запросов с большим количеством результатов
grep "nentries=" /var/log/dirsrv/slapd-localhost/access | \
  awk -F'nentries=' '{print $2}' | cut -d' ' -f1 | sort -rn | head -20
```

### 8. Бенчмаркинг LDAP-сервера

```bash
# ldapsearch benchmark (1000 запросов)
time for i in $(seq 1 1000); do
  ldapsearch -x -H ldap://localhost \
    -D "cn=readonly,ou=services,dc=example,dc=com" -W \
    -b "ou=people,dc=example,dc=com" "(uid=user$i)" cn mail 2>/dev/null
done

# Замер времени одного запроса
ldapsearch -x -H ldap://localhost \
  -D "cn=readonly,ou=services,dc=example,dc=com" -W \
  -b "ou=people,dc=example,dc=com" "(objectClass=*)" cn mail \
  -E pr=100/noprint 2>&1 | grep "time"
```

## Дополнительная информация

### Чеклист оптимизации перед запуском в production

```text
[ ] Все атрибуты в фильтрах поиска имеют индексы eq
[ ] Entry cache hit ratio > 85%
[ ] DB cache hit ratio > 90%
[ ] Диск SSD/NVMe, noatime в fstab
[ ] sizelimit настроен (не 500 по умолчанию)
[ ] timelimit настроен
[ ] Количество потоков оптимизировано
[ ] Репликация идет по выделенному интерфейсу/VLAN
[ ] NTP синхронизирован на всех узлах
[ ] ulimit nofile >= 65535
[ ] vm.max_map_count увеличен (для LMDB)
```

### Частые ошибки

| Ошибка | Причина | Решение |
|:---|:---|:---|
| `notes=U` в access log | Отсутствует индекс | Создайте индекс для атрибута в фильтре |
| Entry cache hit ratio < 85% | Мало RAM или неправильный cache-autosize | Увеличьте nsslapd-cachememsize |
| Высокий `iowait` | Медленный диск или нет индексов | SSD + проверка индексов |
| `Size limit exceeded` | Маленький sizelimit | Увеличьте nsslapd-sizelimit |
| Медленная репликация | Латентность сети > 5ms | Выделенный VLAN для репликации |
| `MMAP: Map failed` | Недостаточно виртуальной памяти | Увеличьте vm.max_map_count |

### См. также

- **[LDAP: основы протокола](./ldap_fundamentals.md)** — терминология и структура DIT
- **[LDAP мониторинг](./ldap_monitoring.md)** — метрики и алерты
- **[LDAP Troubleshooting](./ldap_troubleshooting.md)** — диагностика проблем
- **[389DS: Обзор](./389ds/overview.md)** — архитектура и LMDB
- **[OpenLDAP: установка](./openldap_basics.md)** — настройка cn=config
- **[LDAP: планирование ёмкости](./ldap_capacity_planning.md)** — sizing, формулы расчёта RAM/CPU/disk
- **[LDAP: продвинутые операции](./ldap_advanced_operations.md)** — rate limiting, connection pooling
