# LDAP: продвинутые операции

## Определения

**Proxied Authorization (Proxied Auth)** -- расширение протокола LDAP, позволяющее одному DN (например, сервису) выполнять операции от имени другого DN (пользователя) без передачи пароля. Определяется в RFC 4370.

**Backend Chaining** -- механизм LDAP-сервера, который перенаправляет запросы к другому LDAP-серверу (chaining backend), если данные не найдены локально. Позволяет строить федеративные каталоги без полной репликации.

**Rate Limiting (Ограничение частоты)** -- механизм ограничения количества LDAP-запросов в единицу времени для защиты от перегрузки и DDoS-атак.

**Connection Pooling** -- пул перераспользуемых TCP-соединений на стороне клиента, устраняющий накладные расходы на создание нового соединения для каждого LDAP-запроса.

**Data Lifecycle Management** -- управление жизненным циклом данных LDAP от создания до архивации/удаления: автоматическая ротация, очистка устаревших записей, аудит.

**Split-Brain** -- состояние кластера multi-master, при котором часть серверов утратила связь и продолжила принимать изменения независимо. При восстановлении связи возникают конфликты, требующие разрешения.

---

## Базовые концепции

### Proxied Authorization vs Direct Bind

| Подход | Механизм | Преимущество | Недостаток |
|:---|:---|:---|:---|
| **Direct Bind** | Клиент передаёт DN + пароль | Просто | Пароль в каждом запросе |
| **Proxied Auth** | Сервис bind от своего DN, затем "притворяется" пользователем | Безопасно, пароль не передаётся | Сложнее настройка |

---

## Практические сценарии

### 1. Proxied Authorization (389DS)

```bash
# Включение proxied auth в 389DS
dsconf -D "cn=Directory Manager" ldap://localhost config replace \
  nsslapd-plugin-enabled=proxyperson

# Создание учётной записи сервиса с правами proxied auth
cat > /tmp/proxy-service.ldif << 'EOF'
dn: cn=proxy-service,ou=services,dc=example,dc=com
objectClass: inetOrgPerson
objectClass: posixAccount
cn: proxy-service
sn: Service
uid: proxy-service
uidNumber: 9999
gidNumber: 9999
homeDirectory: /nonexistent
userPassword: {SSHA}hash_here
EOF

ldapadd -x -H ldap://localhost \
  -D "cn=admin,dc=example,dc=com" -W -f /tmp/proxy-service.ldif

# Назначение прав proxied auth
cat > /tmp/proxy-acl.ldif << 'EOF'
dn: olcDatabase={1}mdb,cn=config
changetype: modify
add: olcAccess
olcAccess: {0}to *
  by dn="cn=proxy-service,ou=services,dc=example,dc=com" read
  by users read
  by * none
EOF

ldapmodify -Y EXTERNAL -H ldapi:/// -f /tmp/proxy-acl.ldif
```

```bash
# Использование proxied auth
ldapsearch -x -H ldap://localhost \
  -D "cn=proxy-service,ou=services,dc=example,dc=com" -W \
  -e ProxiedAuthorization \
  -b "ou=people,dc=example,dc=com" "(uid=jdoe)"
# Результат: search от имени proxy-service, но отфильтровано по правам jdoe
```

### 2. Backend Chaining (OpenLDAP)

```bash
# Настройка chaining backend (ldap-01 перенаправляет на ldap-02)
cat > /tmp/chaining.ldif << 'EOF'
dn: cn=module{0},cn=config
changetype: modify
add: olcModuleLoad
olcModuleLoad: back_ldap

dn: olcDatabase={2}ldap,cn=config
objectClass: olcDatabaseConfig
objectClass: olcLDAPConfig
olcDatabase: {2}ldap
olcDbURI: "ldap://ldap-02.example.com:389"
olcDbBindMethod: simple
olcDbBindDN: "cn=chaining,ou=services,dc=example,dc=com"
olcDbBindPW: "ChainingPassword"
olcDbReferral: "ldap://ldap-02.example.com"
olcDbChaining: on
EOF

ldapadd -Y EXTERNAL -H ldapi:/// -f /tmp/chaining.ldif
```

### 3. Rate Limiting (389DS)

```bash
# Ограничение соединений
dsconf -D "cn=Directory Manager" ldap://localhost config replace \
  nsslapd-maxthreads=32 \
  nsslapd-maxdescriptors=4096 \
  nsslapd-idletimeout=3600

# Ограничение поиска (sizelimit и timelimit)
dsconf -D "cn=Directory Manager" ldap://localhost config replace \
  nsslapd-sizelimit=5000 \
  nsslapd-timelimit=30 \
  nsslapd-pagedsizelimit=10000
```

```bash
# OpenLDAP: ограничение размера БД и соединений
ldapmodify -Y EXTERNAL -H ldapi:/// <<EOF
dn: olcDatabase={1}mdb,cn=config
changetype: modify
replace: olcSizeLimit
olcSizeLimit: 5000
-
replace: olcMaxSize
olcMaxSize: 10737418240
EOF
```

### 4. Connection Pooling (клиентская сторона, SSSD)

```bash
# /etc/sssd/sssd.conf
[domain/example.com]
# Пул соединений
ldap_uri = ldaps://ldap.example.com:636
ldap_backup_uri = ldaps://ldap-backup.example.com:636
ldap_chase_referrals = true

# Таймауты
ldap_network_timeout = 3
ldap_opt_timeout = 3
ldap_search_timeout = 10
ldap_bind_timeout = 5

# Кэширование (уменьшает количество LDAP-запросов)
cache_credentials = true
cached_auth_timeout = 300
entry_cache_timeout = 300
entry_cache_user_timeout = 300
entry_cache_group_timeout = 300

# Переподключение
ldap_conn_expire_delay = 300
ldap_idle_explicit_timeout = 600
```

### 5. Data Lifecycle Management

#### Автоматическая очистка устаревших записей (389DS)

```bash
# Включение TTL для записей
dsconf -D "cn=Directory Manager" ldap://localhost backend suffix create \
  --suffix "dc=expired,dc=example,dc=com" \
  --be-name expiredRoot

# Скрипт очистки (crab: ежедневно в 03:00)
#!/bin/bash
# /usr/local/bin/ldap-cleanup.sh

LDAP_URI="ldap://localhost"
ADMIN_DN="cn=admin,dc=example,dc=com"
ADMIN_PW="AdminPassword"
BASE_DN="ou=people,dc=example,dc=com"
CUTOFF_DATE=$(date -d "90 days ago" +%Y%m%d%H%M%S.000Z)

# Поиск записей старше 90 дней
ldapsearch -x -H $LDAP_URI -D "$ADMIN_DN" -W -LLL \
  -b "$BASE_DN" \
  "(&(objectClass=person)(modifyTimestamp<=$CUTOFF_DATE))" dn | \
while read dn; do
  echo "Removing expired: $dn"
  ldapdelete -x -H $LDAP_URI -D "$ADMIN_DN" -W "$dn"
done
```

#### Архивация в 389DS

```bash
# Экспорт записей старше 1 года
ARCHIVE_DATE=$(date -d "365 days ago" +%Y%m%d%H%M%S.000Z)

dsconf -D "cn=Directory Manager" ldap://localhost \
  backend export userRoot --ldif /archive/ldap-archive-$(date +%F).ldif \
  --filter "(&(objectClass=person)(modifyTimestamp<=$ARCHIVE_DATE))"
```

### 6. Split-Brain: разрешение конфликтов

#### Определение split-brain

```bash
# Проверка RUV на разных мастерах
# ldap-01
dsconf -D "cn=Directory Manager" ldap://ldap-01 replication get-ruv

# ldap-02
dsconf -D "cn=Directory Manager" ldap://ldap-02 replication get-ruv

# Сравнение: если CSN для Replica ID 1 значительно отстаёт на ldap-02 -- split-brain
```

#### Разрешение конфликтов

```bash
# 1. Восстановление связи между серверами
# Убедитесь, что сеть между ldap-01 и ldap-02 работает
nc -zv ldap-01.example.com 389
nc -zv ldap-02.example.com 389

# 2. Запуск репликации (если она была остановлена)
# 389DS: репликация возобновится автоматически
# Проверка:
dsconf -D "cn=Directory Manager" ldap://ldap-01 replication monitor

# 3. Если конфликты не разрешаются автоматически:
# CleanAllRUV для удаления stale Replica ID
dsconf -D "cn=Directory Manager" ldap://ldap-01 \
  replication cleanallruv --replica-id 2 --force

# 4. Полная re-sync (крайний случай)
dsconf -D "cn=Directory Manager" ldap://ldap-02 \
  replication init ldap-01 userRoot \
  --from-host="ldap-01.example.com" --from-port=389
```

---

## Дополнительная информация

### Мониторинг продвинутых операций

| Метрика | Источник | Описание |
|:---|:---|:---|
| `ldap_thread_active` | cn=monitor | Активные потоки (rate limiting) |
| `ldap_thread_waiters` | cn=monitor | Ожидающие потоки (перегрузка) |
| `ldap_operations_total` | cn=monitor | Общее количество операций |
| `ldap_chaining_result` | access log | Результаты chaining-запросов |
| `ldap_proxy_auth` | access log | Использование proxied auth |

### Типичные ошибки

| Ошибка | Причина | Решение |
|:---|:---|:---|
| `Protocol error` при proxied auth | Расширение не включено | Включите proxyperson plugin |
| `Operations Error` при chaining | Нет соединения с upstream | Проверьте сеть и Bind DN |
| `Size limit exceeded` | Маленький sizelimit | Увеличьте nsslapd-sizelimit |
| `Time limit exceeded` | Медленный запрос или индекс | Оптимизируйте запрос, добавьте индекс |
| `Unwilling to perform` | Split-brain или corrupted DB | Восстановите репликацию |

### См. также

- **[LDAP Performance Tuning](./ldap_performance_tuning.md)** -- оптимизация производительности
- **[LDAP Мониторинг](./ldap_monitoring.md)** -- метрики
- **[389DS: Репликация](./389ds/replication.md)** -- Multi-Master, RUV
- **[LDAP Troubleshooting](./ldap_troubleshooting.md)** -- диагностика
- **[LDAP: основы протокола](./ldap_fundamentals.md)** -- расширения протокола
