# OpenLDAP: установка, конфигурация и управление

## Определения

**OpenLDAP** — свободная реализация LDAP-сервера, разрабатываемая проектом OpenLDAP Foundation. Основной демон — `slapd` (Standalone LDAP Daemon). Актуальная версия — 2.6+ (2.4 — EOL с февраля 2022).

**slapd** — основной процесс OpenLDAP, обрабатывающий LDAP-запросы. Конфигурация хранится в `cn=config` (OLC — OpenLDAP Configuration) в формате LDIF.

**cn=config (OLC)** — динамическая конфигурация OpenLDAP, доступная как LDAP-дерево. Позволяет менять настройки без перезапуска сервера через `ldapmodify`.

**MDB (Memory-Mapped Database)** — движок хранения данных в OpenLDAP 2.6+ (единственный поддерживаемый). Использует memory-mapped файлы для высокой производительности чтения.

**slapcat / slapadd** — утилиты для оффлайн-экспорта/импорта данных (при остановленном `slapd`).

**ldapsearch / ldapadd / ldapmodify / ldapdelete** — стандартные утилиты клиента OpenLDAP для работы с данными по сети.

**ppolicy overlay** — модуль политики паролей: сложность, история, ротация, блокировка.

**syncprov overlay** — модуль репликации, предоставляющий данные потребителям через Syncrepl.

**ACL (Access Control List)** — правила управления доступа в OpenLDAP, задаваемые через `olcAccess` в `cn=config`.

---

## Базовые концепции

### Два режима конфигурации

| Режим | Описание | Рекомендация |
|:---|:---|:---|
| **slapd.conf** | Статический текстовый файл (устаревший) | Только для legacy-систем |
| **cn=config (OLC)** | Динамическая конфигурация в LDIF | Рекомендуется для новых развертываний |

### Структура cn=config

```text
cn=config
+-- cn=schema                  (загруженные схемы)
+-- olcDatabase={-1}frontend   (фронтенд)
+-- olcDatabase={0}config      (конфигурационная БД)
+-- olcDatabase={1}mdb         (основная БД данных)
    +-- olcSuffix: dc=example,dc=com
    +-- olcRootDN: cn=admin,dc=example,dc=com
    +-- olcRootPW: {SSHA}...
    +-- olcDbDirectory: /var/lib/ldap
    +-- olcDbMaxSize: 1073741824
    +-- olcAccess: to * by ... read
    +-- olcDbIndex: ...
```

### Файловая структура

| Путь | Назначение |
|:---|:---|
| `/etc/openldap/slapd.d/` | Конфигурация cn=config (LDIF-файлы) |
| `/var/lib/ldap/` | Файлы данных (MDB) |
| `/var/run/openldap/` | PID-файл, сокет |
| `/etc/openldap/schema/` | Стандартные схемы |
| `/etc/openldap/ldap.conf` | Конфигурация клиентских утилит |

### Ключевые файлы конфигурации клиента

**`/etc/openldap/ldap.conf`** (или `/etc/ldap/ldap.conf` на Debian/Ubuntu):

```text
BASE    dc=example,dc=com
URI     ldap://ldap.example.com
TLS_CACERT      /etc/openldap/certs/ca.crt
TLS_REQCERT     demand
```

## Практические сценарии

### 1. Установка OpenLDAP (RHEL/Rocky/AlmaLinux)

```bash
# Установка сервера и клиентских утилит
sudo dnf install openldap-servers openldap-clients -y

# Копирование базового конфигурационного файла MDB
sudo cp /usr/share/openldap-servers/DB_CONFIG.example /var/lib/ldap/DB_CONFIG
sudo chown ldap:ldap /var/lib/ldap/DB_CONFIG
```

### 2. Установка OpenLDAP (Debian/Ubuntu)

```bash
# Установка сервера и клиентских утилит
sudo apt update && sudo apt install slapd ldap-utils -y

# Интерактивная первоначальная настройка
sudo dpkg-reconfigure slapd
```

### 3. Добавление стандартных схем

```bash
sudo ldapadd -Y EXTERNAL -H ldapi:/// -f /etc/openldap/schema/cosine.ldif
sudo ldapadd -Y EXTERNAL -H ldapi:/// -f /etc/openldap/schema/inetorgperson.ldif
sudo ldapadd -Y EXTERNAL -H ldapi:/// -f /etc/openldap/schema/nis.ldif
```

### 4. Настройка корневого суффикса

```bash
# Пример LDIF для ldapmodify:
# dn: olcDatabase={1}mdb,cn=config
# changetype: modify
# add: olcSuffix
# olcSuffix: dc=example,dc=com
# -
# add: olcRootDN
# olcRootDN: cn=admin,dc=example,dc=com
# -
# add: olcRootPW
# olcRootPW: {SSHA}your_hash_here
```

### 5. Создание базовой структуры DIT

```bash
# Создание LDIF-файла base.ldif
ldapadd -x -D "cn=admin,dc=example,dc=com" -W -f /tmp/base.ldif
```

Пример содержимого base.ldif:

```text
dn: dc=example,dc=com
objectClass: top
objectClass: dcObject
objectClass: organization
o: Example Inc.
dc: example

dn: ou=people,dc=example,dc=com
objectClass: organizationalUnit
ou: people

dn: ou=groups,dc=example,dc=com
objectClass: organizationalUnit
ou: groups

dn: ou=services,dc=example,dc=com
objectClass: organizationalUnit
ou: services
```

### 6. Создание пользователя

```bash
# Генерация хэша пароля
slappasswd -s "UserPassword123"

# Добавление через ldapadd
ldapadd -x -D "cn=admin,dc=example,dc=com" -W -f /tmp/user.ldif
```

Пример user.ldif:

```text
dn: uid=jdoe,ou=people,dc=example,dc=com
objectClass: inetOrgPerson
objectClass: posixAccount
uid: jdoe
cn: John Doe
sn: Doe
uidNumber: 10000
gidNumber: 10000
homeDirectory: /home/jdoe
loginShell: /bin/bash
userPassword: {SSHA}hash_here
```

### 7. Настройка TLS/SSL

```bash
# Генерация самоподписанного сертификата
openssl req -new -x509 -nodes -days 3650 \
  -newkey rsa:2048 -keyout /etc/openldap/certs/ldap.key \
  -out /etc/openldap/certs/ldap.crt \
  -subj "/CN=ldap.example.com"

# Запуск slapd с TLS
slapd -h "ldap:/// ldaps:/// ldapi:///" -u ldap -g ldap
```

### 8. Настройка ACL (права доступа)

```bash
ldapmodify -Y EXTERNAL -H ldapi:///
```

Пример ACL:

```text
dn: olcDatabase={1}mdb,cn=config
changetype: modify
replace: olcAccess
olcAccess: {0}to attrs=userPassword
  by self write
  by anonymous auth
  by dn="cn=admin,dc=example,dc=com" write
  by * none
olcAccess: {1}to *
  by dn="cn=admin,dc=example,dc=com" write
  by self read
  by * read
```

### 9. Настройка ppolicy (политика паролей)

```bash
# Включение модуля
ldapmodify -Y EXTERNAL -H ldapi:/// <<EOF
dn: cn=module{0},cn=config
changetype: modify
add: olcModuleLoad
olcModuleLoad: ppolicy.la
EOF

# Включение ppolicy overlay
ldapadd -x -D "cn=admin,dc=example,dc=com" -W <<EOF
dn: olcOverlay=ppolicy,olcDatabase={1}mdb,cn=config
objectClass: olcOverlayConfig
objectClass: olcPPolicyConfig
olcOverlay: ppolicy
olcPPolicyDefault: cn=default,ou=policies,dc=example,dc=com
olcPPolicyHashCleartext: TRUE
olcPPolicyUseLockout: TRUE
EOF
```

### 10. Базовые команды управления

```bash
# Поиск всех пользователей
ldapsearch -x -b "ou=people,dc=example,dc=com" "(objectClass=posixAccount)" uid cn

# Проверка работоспособности (Root DSE)
ldapsearch -x -b "" -s base "(objectClass=*)" namingContexts

# Оффлайн-экспорт (требует остановки slapd)
slapcat -b "dc=example,dc=com" -l /backup/ldap.ldif

# Оффлайн-импорт
slapadd -b "dc=example,dc=com" -l /backup/ldap.ldif
```

## Дополнительная информация

### Типичные ошибки

| Ошибка | Причина | Решение |
|:---|:---|:---|
| `slapd не стартует` | Ошибки в cn=config | Проверьте `/var/log/messages` или `journalctl -u slapd` |
| `TLS handshake failed` | Неверные сертификаты | Проверьте CN в сертификате и права доступа |
| `Access denied` | ACL блокирует доступ | Проверьте `olcAccess` через `ldapsearch` |
| `Size limit exceeded` | Превышен sizelimit | Увеличьте `olcSizeLimit` |
| `No such object` | Неверный Base DN | Проверьте DN через `ldapsearch -x -b "" -s base "(objectClass=*)"` |

### Рекомендации для production

- Запускайте `slapd` от пользователя `ldap` (не root)
- Используйте TLS (LDAPS или StartTLS)
- Отключите анонимный bind
- Настройте `ppolicy` для паролей
- Регулярно выполняйте `slapcat` для бэкапа
- Мониторинг через `openldap_exporter` + Prometheus
- Используйте `cn=config` вместо `slapd.conf`

### См. также

- **[LDAP: основы протокола](./ldap_fundamentals.md)** — терминология и структура DIT
- **[OpenLDAP в Kubernetes](./openldap_kubernetes.md)** — Helm-чарт и StatefulSet
- **[389 Directory Server](./389ds/overview.md)** — сравнение с альтернативой
- **[LDAP + SSSD](../Linux/SystemAdministration/Users/LDAP_SSSD/index.md)** — интеграция с Linux
- **[LDAP Security Hardening](./ldap_security.md)** — настройка безопасности
