# LDAP Troubleshooting: диагностика проблем

## Определения

**ldapsearch** — основной инструмент диагностики LDAP. Позволяет выполнять поиск, проверять bind, тестировать ACL и репликацию.

**ldapwhoami** — утилита для проверки текущей учётной записи (Bind DN) после подключения к серверу.

**ldapcompare** — утилита для проверки конкретного значения атрибута записи.

** slapcat** — оффлайн-утилита для экспорта данных из БД OpenLDAP (при остановленном slapd).

**dsconf** — CLI-утилита для управления конфигурацией 389DS (вместо ldapmodify для cn=config).

** Access Log** — лог операций клиента (bind, search, modify). В 389DS: `/var/log/dirsrv/slapd-<instance>/access`. В OpenLDAP: `/var/log/slapd-access.log`.

** Error Log** — лог ошибок сервера. В 389DS: `/var/log/dirsrv/slapd-<instance>/errors`. В OpenLDAP: `/var/log/slapd-errors.log`.

---

## Базовые концепции

### Методология диагностики

1. **Проверка доступности сервера** — резолвится ли DNS, открыт ли порт, отвечает ли `slapd`/`ns-slapd`
2. **Проверка bind** — корректны ли учётные данные, есть ли права на чтение
3. **Проверка данных** — существуют ли записи, корректны ли атрибуты
4. **Проверка ACL/ACI** — разрешает ли сервер доступ к запрошенным данным
5. **Анализ логов** — что пишет сервер в access/error логи

### Инструменты диагностики

| Инструмент | Назначение | LDAP-реализация |
|:---|:---|:---|
| `ldapsearch` | Поиск, проверка bind, тест ACL | Все |
| `ldapwhoami` | Проверка текущего Bind DN | Все |
| `ldapcompare` | Проверка значения атрибута | Все |
| `ldapmodify` | Тест записи | Все |
| `slapcat` | Оффлайн-экспорт БД | OpenLDAP |
| `dsconf` | Управление конфигурацией | 389DS |
| `dsctl` | Управление инстансом | 389DS |
| `sssctl` | Диагностика SSSD | SSSD |
| `ldbsearch` | Просмотр кэша SSSD | SSSD |

## Практические сценарии

### 1. Проверка доступности сервера

```bash
# Проверка DNS
nslookup ldap.example.com
host ldap.example.com

# Проверка порта
nc -zv ldap.example.com 389
nc -zv ldap.example.com 636

# Проверка через openssl (для LDAPS)
openssl s_client -connect ldap.example.com:636 -servername ldap.example.com

# Проверка процесса slapd
systemctl status slapd
# или для 389DS:
systemctl status dirsrv.target
```

### 2. Проверка bind (аутентификации)

```bash
# Анонимный bind
ldapwhoami -x -H ldap://ldap.example.com

# Simple bind с DN и паролем
ldapwhoami -x -H ldap://ldap.example.com \
  -D "cn=admin,dc=example,dc=com" -W

# Через LDAPS
ldapwhoami -H ldaps://ldap.example.com:636 \
  -D "cn=admin,dc=example,dc=com" -W

# Проверка через SASL (GSSAPI/Kerberos)
ldapwhoami -Y GSSAPI -H ldap://ldap.example.com
```

### 3. Проверка данных

```bash
# Поиск корневого DN (Root DSE)
ldapsearch -x -b "" -s base "(objectClass=*)"

# Поиск всех пользователей
ldapsearch -x -b "ou=people,dc=example,dc=com" "(objectClass=*)"

# Поиск конкретного пользователя
ldapsearch -x -b "dc=example,dc=com" "(uid=jdoe)" cn mail uidNumber

# Проверка наличия атрибута
ldapcompare -x -H ldap://ldap.example.com \
  -D "cn=admin,dc=example,dc=com" -W \
  "uid=jdoe,ou=people,dc=example,dc=com" mail:jdoe@example.com
```

### 4. Диагностика ACL/ACI (389DS)

```bash
# Просмотр Effective Rights (389DS)
ldapsearch -H ldap://localhost -D "cn=Directory Manager" -W \
  -b "uid=jdoe,ou=people,dc=example,dc=com" \
  "(objectClass=*)" effectiveRights

# Просмотр ACI (389DS)
dsconf -D "cn=Directory Manager" ldap://localhost aci list "dc=example,dc=com"

# Просмотр ACL (OpenLDAP)
ldapsearch -Y EXTERNAL -H ldapi:/// \
  -b "olcDatabase={1}mdb,cn=config" olcAccess
```

### 5. Диагностика репликации (389DS)

```bash
# Просмотр RUV (Replica Update Vector)
dsconf -D "cn=Directory Manager" ldap://localhost replication get-ruv \
  --suffix "dc=example,dc=com"

# Проверка статуса соглашения
dsconf -D "cn=Directory Manager" ldap://localhost repl-agmt status \
  --suffix "dc=example,dc=com" "agmt-to-ldap-02"

# Поиск ошибок репликации в логах
grep -i "repl" /var/log/dirsrv/slapd-localhost/access | tail -n 50
```

### 6. Диагностика SSSD на клиенте

```bash
# Проверка статуса домена
sudo sssctl domain-status -a

# Проверка данных пользователя
sudo sssctl user-check username

# Проверка конфигурации
sudo sssctl config-check

# Анализ логов
sudo sssctl analyze --source pam --user username

# Очистка кэша (при проблемах)
sudo sss_cache -E

# Радикальное восстановление
sudo systemctl stop sssd
sudo rm -f /var/lib/sss/db/*.ldb
sudo rm -f /var/lib/sss/mc/*
sudo systemctl start sssd
```

## Таблица типичных ошибок

### Ошибки подключения

| Ошибка | Причина | Решение |
|:---|:---|:---|
| `Can't contact LDAP server (-1)` | DNS не резолвится, порт закрыт, slapd не запущен | `nslookup`, `nc -zv`, `systemctl status slapd` |
| `Connection refused` | slapd слушает другой порт или интерфейс | Проверьте `ss -tlnp | grep 389` и конфигурацию `olcListen` |
| `Connection timed out` | Файрвол блокирует трафик | Проверьте `iptables -L -n` или `firewall-cmd --list-all` |
| `TLS handshake failed` | Неверный сертификат, CN не совпадает, CA не доверен | `openssl s_client -connect`, проверьте CN и CA |

### Ошибки аутентификации

| Ошибка | Причина | Решение |
|:---|:---|:---|
| `Invalid credentials (49)` | Неверный DN или пароль | Проверьте DN через `ldapwhoami`, сгенерируйте новый хэш `slappasswd` |
| `Inappropriate authentication (48)` | Попытка anonymous bind при его запрете | Используйте явный Bind DN |
| `Stronger authentication required (8)` | Требуется TLS для данной операции | Включите LDAPS или StartTLS |
| `Insufficient access (50)` | ACL/ACI запрещает доступ | Проверьте Effective Rights (389DS) или `olcAccess` (OpenLDAP) |

### Ошибки данных

| Ошибка | Причина | Решение |
|:---|:---|:---|
| `No such object (32)` | Запись не существует или неверный Base DN | Проверьте DN через `ldapsearch -x -b "" -s base "(objectClass=*)"` |
| `No such attribute (16)` | Запрашиваемый атрибут отсутствует в записи | Проверьте схему: `ldapsearch -b "cn=schema,cn=config" "(cn=<attr>)"` |
| `Object class violation (65)` | Нарушены MUST/MAY ограничения objectClass | Проверьте обязательные атрибуты objectClass |
| `Attribute or value exists (20)` | Дубликат уникального атрибута | Проверьте `mail`, `uid` на дубликаты |
| `Size limit exceeded (4)` | Превышен `sizelimit` сервера | Увеличьте лимит или используйте постраничную выборку (`-E pr=1000/noprint`) |

### Ошибки SSSD

| Ошибка | Причина | Решение |
|:---|:---|:---|
| `SSSD: No such entry` | Кэш устарел или DNS не резолвится | `sss_cache -E`, проверьте DNS |
| `System Error при логине` | Повреждение LDB или нехватка места | `df -h`, очистите `/var/lib/sss/db/` |
| `Groups empty` | `ldap_schema` не соответствует каталогу | Переключитесь на `rfc2307bis` или наоборот |
| `Offline login failed` | Хэши паролей не были сохранены | Включите `cache_credentials = true` |
| `TLS handshake failed` | Сертификат CA не добавлен в доверенные | Проверьте `ldap_tls_cacert` в `sssd.conf` |

## Дополнительная информация

### Централизованный сбор логов

```bash
# Сбор логов OpenLDAP в rsyslog
# /etc/rsyslog.d/ldap.conf
if $programname == 'slapd' then /var/log/ldap/ldap.log
& stop

# Сбор логов 389DS через Filebeat
# filebeat.yml
filebeat.inputs:
- type: log
  paths:
    - /var/log/dirsrv/slapd-*/access
    - /var/log/dirsrv/slapd-*/errors
  json.keys_under_root: true
```

### Полезные скрипты диагностики

```bash
#!/bin/bash
# ldap_health_check.sh -- быстрая проверка LDAP-сервера

LDAP_HOST="ldap.example.com"
LDAP_PORT="389"
BIND_DN="cn=readonly,ou=services,dc=example,dc=com"
BASE_DN="dc=example,dc=com"

echo "=== Проверка DNS ==="
nslookup $LDAP_HOST

echo "=== Проверка порта ==="
nc -zv $LDAP_HOST $LDAP_PORT

echo "=== Проверка bind ==="
ldapwhoami -x -H ldap://$LDAP_HOST -D "$BIND_DN" -W

echo "=== Проверка поиска ==="
ldapsearch -x -H ldap://$LDAP_HOST -D "$BIND_DN" -W \
  -b "$BASE_DN" -s base "(objectClass=*)" namingContexts

echo "=== Проверка пользователей ==="
ldapsearch -x -H ldap://$LDAP_HOST -D "$BIND_DN" -W \
  -b "ou=people,$BASE_DN" "(objectClass=*)" uid | wc -l
```

### См. также

- **[LDAP: основы протокола](./ldap_fundamentals.md)** — терминология
- **[389DS: Обзор](./389ds/overview.md)** — архитектура и логи 389DS
- **[389DS: Репликация](./389ds/replication.md)** — диагностика репликации
- **[LDAP + SSSD](../Linux/SystemAdministration/Users/LDAP_SSSD/operations.md)** — отладка SSSD
- **[LDAP Security Hardening](./ldap_security.md)** — настройка безопасности
