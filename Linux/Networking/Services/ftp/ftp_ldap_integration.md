# FTP: Интеграция с LDAP/Active Directory

---

## Определения

**LDAP (Lightweight Directory Access Directory Protocol)** — протокол доступа к распределённым информационным службам (RFC 4511). Используется для централизованного управления пользователями, группами и ресурсами в корпоративных сетях.

**Active Directory (AD)** — служба каталогов Microsoft, реализующая протоколы LDAP, Kerberos и DNS. Предоставляет централизованное управление учётными записями и политиками безопасности.

**SSSD (System Security Services Daemon)** — демон, обеспечивающий доступ к удалённым каталогам (LDAP, AD) и аутентификацию пользователей в Linux. Кэширует учётные данные для работы в офлайн-режиме.

**Winbind** — компонент Samba, обеспечивающий интеграцию Linux с Active Directory и маппинг SID ↔ UID/GID.

**PAM (Pluggable Authentication Modules)** — модульная система аутентификации в Linux, позволяющая подключать различные методы проверки подлинности.

---

## Основные концепции

### Архитектура интеграции

```
FTP-сервер → PAM/LDAP-модуль → LDAP/AD сервер
     ↓
  SSSD/Winbind (кэширование)
     ↓
  Локальные пользователи (UID/GID маппинг)
```

### Схемы аутентификации

| Схема | Описание | Безопасность |
| :--- | :--- | :--- |
| **PAM + LDAP** | Через `pam_ldap.so` | Средняя ( depends on LDAP config) |
| **SSSD** | Через `pam_sss.so` | Высокая (кэширование, offline) |
| **ProFTPD модуль** | Встроенный `mod_ldap` | Высокая |
| **Pure-FTPd** | Встроенная LDAP-поддержка | Высокая |
| **Winbind** | Через `pam_winbind.so` | Высокая (для AD) |

### Схемы данных

**OpenLDAP (inetOrgPerson + POSIX):**
```
ou=people,dc=example,dc=com
├── uid=jdoe
│   ├── objectClass: inetOrgPerson, posixAccount, shadowAccount
│   ├── uid: jdoe
│   ├── cn: John Doe
│   ├── userPassword: {SSHA}...
│   ├── uidNumber: 10001
│   ├── gidNumber: 10001
│   ├── homeDirectory: /home/jdoe
│   └── loginShell: /bin/bash
```

**Active Directory:**
```
CN=Users,DC=example,DC=com
├── CN=jdoe
│   ├── objectClass: user, posixAccount
│   ├── sAMAccountName: jdoe
│   ├── userPrincipalName: jdoe@example.com
│   ├── uidNumber: 10001
│   ├── gidNumber: 10001
│   ├── homeDirectory: /home/jdoe
│   └── loginShell: /bin/bash
```

### Маппинг пользователей

**UID/GID:**
- LDAP: `uidNumber` → Linux: `uid`
- LDAP: `gidNumber` → Linux: `gid`
- AD: `uidNumber` → Linux: `uid` (через nss-winbind или SSSD)

**Домашняя директория:**
- Генерируется через `pam_mkhomedir.so` при первом входе
- Или создаётся заранее через скрипт

---

## Практические сценарии

### 1. vsftpd + PAM + LDAP

#### Установка зависимостей

```bash
sudo apt update
sudo apt install vsftpd libpam-ldap ldap-utils -y
```

#### Конфигурация PAM

```bash
# /etc/pam.d/vsftpd
# Аутентификация через LDAP
auth    required    pam_ldap.so
account required    pam_ldap.so

# Опционально: создание домашней директории
# session optional    pam_mkhomedir.so skel=/etc/skel umask=077
```

#### Конфигурация LDAP-клиента

```bash
# /etc/libnss-ldap.conf (или /etc/ldap.conf)
base dc=example,dc=com
uri ldap://ldap.example.com
ldap_version 3
binddn cn=readonly,dc=example,dc=com
bindpw readonly-password
scope sub

# Фильтры поиска
pam_filter objectclass=posixAccount
pam_login_attribute uid
pam_member_attribute memberUid

# TLS
ssl start_tls
tls_cacertfile /etc/ssl/certs/ca-certificates.crt

# Маппинг
pam_uid_attribute uidNumber
pam_gid_attribute gidNumber
pam_home_directory homeDirectory
pam_shell loginShell
```

#### Конфигурация NSS

```bash
# /etc/nsswitch.conf
passwd:         files ldap
group:          files ldap
shadow:         files ldap

# Проверка
getent passwd jdoe
# → jdoe:*:10001:10001:John Doe:/home/jdoe:/bin/bash
```

#### Конфигурация vsftpd

```bash
# /etc/vsftpd.conf
listen=YES
anonymous_enable=NO
local_enable=YES
write_enable=YES

# Члены группы ftpusers получают доступ
userlist_enable=YES
userlist_file=/etc/vsftpd/user_list
userlist_deny=NO

# Члены группы ftpusers получают доступ
userlist_enable=YES
userlist_file=/etc/vsftpd/user_list
userlist_deny=NO

# Ограничение доступа
chroot_local_user=YES
allow_writeable_chroot=YES
```

#### Создание пользователей в LDAP

```bash
# LDIF-файл для добавления пользователя
cat > /tmp/user.ldif << EOF
dn: uid=jdoe,ou=people,dc=example,dc=com
objectClass: inetOrgPerson
objectClass: posixAccount
objectClass: shadowAccount
uid: jdoe
cn: John Doe
sn: Doe
userPassword: {SSHA}hash
uidNumber: 10001
gidNumber: 10001
homeDirectory: /home/jdoe
loginShell: /bin/bash
EOF

# Добавление в LDAP
ldapadd -x -D "cn=admin,dc=example,dc=com" -W -f /tmp/user.ldif
```

### 2. vsftpd + SSSD (рекомендуется)

#### Установка

```bash
sudo apt install vsftpd sssd sssd-ldap sssd-tools -y
```

#### Конфигурация SSSD

```bash
# /etc/sssd/sssd.conf
[sssd]
domains = example.com
services = nss, pam

[domain/example.com]
id_provider = ldap
auth_provider = ldap
access_provider = ldap

ldap_uri = ldap://ldap.example.com
ldap_search_base = dc=example,dc=com
ldap_default_bind_dn = cn=readonly,dc=example,dc=com
ldap_default_authtok = readonly-password
ldap_id_use_start_tls = true
ldap_tls_reqcert = demand
ldap_tls_cacert = /etc/ssl/certs/ca-certificates.crt

# Кэширование
cache_credentials = true
entry_cache_timeout = 300

# Маппинг
ldap_user_object_class = posixAccount
ldap_user_uid_number = uidNumber
ldap_user_gid_number = gidNumber
ldap_user_home_directory = homeDirectory
ldap_user_shell = loginShell

# Группы
ldap_group_object_class = posixGroup
ldap_group_gid_number = gidNumber
ldap_group_member = memberUid
```

#### Настройка прав

```bash
sudo chmod 600 /etc/sssd/sssd.conf
sudo chown root:root /etc/sssd/sssd.conf
sudo systemctl enable --now sssd
```

#### Конфигурация PAM

```bash
# /etc/pam.d/vsftpd
auth    required    pam_sss.so
account required    pam_sss.so
```

### 3. ProFTPD + LDAP (встроенный модуль)

```apache
# /etc/proftpd/proftpd.conf
<IfModule mod_ldap.c>
    # Подключение к LDAP
    LDAPServer ldap.example.com
    LDAPPort 389
    LDAPBindDN "cn=readonly,dc=example,dc=com"
    LDAPBindPassword "readonly-password"
    LDAPUseTLS on
    LDAPTLSCACertificateFile /etc/ssl/certs/ca-certificates.crt
    
    # Поиск пользователей
    LDAPBase "dc=example,dc=com"
    LDAPSearchScope "one"
    LDAPUsers "(&(objectClass=posixAccount)(uid=%u))"
    
    # Маппинг атрибутов
    LDAPAliasAttribute "cn"
    LDAPUIDAttribute "uidNumber"
    LDAPGIDAttribute "gidNumber"
    LDAPHomedirAttribute "homeDirectory"
    LDAPShellAttribute "loginShell"
    
    # Группы
    LDAPGroupBase "ou=groups,dc=example,dc=com"
    LDAPGroupSearchScope "one"
    LDAPGroupFilter "(&(objectClass=posixGroup)(memberUid=%u))"
    LDAPGroupGIDAttribute "gidNumber"
</IfModule>

# Ограничение доступа по группе
<Limit LOGIN>
    Require group ftp-users
</Limit>
```

### 4. Pure-FTPd + LDAP

```bash
# Включение LDAP
echo 1 | sudo tee /etc/pure-ftpd/conf/LDAP
echo 1 | sudo tee /etc/pure-ftpd/conf/ChrootEveryone

# Конфигурация LDAP
sudo vim /etc/pure-ftpd/conf/LDAPConfigFile
# → /etc/pure-ftpd/ldap.conf
```

```bash
# /etc/pure-ftpd/ldap.conf
LDAPServer ldap.example.com
LDAPPort 389
LDAPBase dc=example,dc=com
LDAPBindDN cn=readonly,dc=example,dc=com
LDAPBindPassword readonly-password
LDAPVersion 3
LDAPUseTLS yes

# Фильтры
LDAPFilter (&(objectClass=posixAccount)(uid=$M))
LDAPGetHomeDir homeDirectory
LDAPGetUID uidNumber
LDAPGetGID gidNumber
LDAPGetShell loginShell
```

---

## Дополнительная информация

### Диагностика

```bash
# Проверка LDAP-запроса
ldapsearch -x -H ldap://ldap.example.com \
  -D "cn=readonly,dc=example,dc=com" \
  -W \
  -b "ou=people,dc=example,dc=com" \
  "(uid=jdoe)"

# Проверка PAM
pamtester vsftpd jdoe authenticate

# Проверка SSSD
sss_cache -E
getent passwd jdoe
id jdoe

# Логи
sudo tail -f /var/log/auth.log | grep -i "pam\|ldap\|sssd"
sudo journalctl -u vsftpd -f
```

### Частые ошибки

| Симптом | Причина | Решение |
| :--- | :--- | :--- |
| **530 Login incorrect** | LDAP-запрос не возвращает пользователя | Проверьте фильтр `pam_filter` и атрибуты |
| **Home directory does not exist** | Директория не создана | Включите `pam_mkhomedir.so` |
| **Permission denied** | Неверные права на chroot | Проверьте `allow_writeable_chroot=YES` |
| **LDAP connection refused** | Неверный URI или порт | Проверьте `ldap_uri` и доступность LDAP |
| **TLS handshake failed** | Проблемы с сертификатом | Проверьте `ldap_tls_cacert` |

### Безопасность

1. **Шифрование:** Всегда используйте TLS для LDAP-соединения.
2. **Readonly-пользователь:** Используйте отдельного пользователя для чтения LDAP.
3. **Ограничение доступа:** Настройте ACL в LDAP для ограничения видимости.
4. **Кэширование:** Включите кэширование в SSSD для офлайн-работы.
5. **Бэкап:** Регулярно бэкапируйте конфигурацию SSSD/Winbind.

### Связанные темы

- **[LDAP: 389 Directory Server](../../../LDAP/389ds/overview.md)** — настройка LDAP-сервера
- **[FreeIPA: overview](../../../LDAP/FreeIPA/freeipa_overview.md)** — интеграция с FreeIPA
- **[SSH: LDAP-аутентификация](../../Security/ssh/server/ssh_authentication.md)** — настройка SSH для LDAP-пользователей
- **[vsftpd: настройка](./vsftpd_setup.md)** — базовая конфигурация vsftpd
