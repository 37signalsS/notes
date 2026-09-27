# LDAP Security Hardening

## Определения

**TLS (Transport Layer Security)** — протокол шифрования транспортного уровня. Для LDAP используется LDAPS (порт 636) или StartTLS (порт 389).

**SSF (Security Strength Factor)** — параметр безопасности, определяющий минимальный уровень шифрования. Рекомендуется SSF >= 128.

**ACL (Access Control List)** — правила управления доступа в OpenLDAP (OpenLDAP: `olcAccess` в `cn=config`).

**ACI (Access Control Instructions)** — правила управления доступа в 389DS (хранятся в атрибуте `aci` записи).

**ppolicy overlay** — модуль политики паролей: сложность, история, ротация, блокировка.

**Bind DN** — учётная запись для подключения к LDAP-серверу. Должна иметь минимальные привилегии.

**Anonymous Bind** — подключение без учётных данных. В production должно быть отключено.

**StartTLS** — расширение протокола, позволяющее установить TLS-соединение поверх незашифрованного порта 389.

---

## Базовые концепции

### Уровни безопасности LDAP

| Уровень | Описание | Рекомендация |
|:---|:---|:---|
| **Без шифрования** | LDAP (порт 389) без TLS | Запрещён в production |
| **StartTLS** | Шифрование поверх порта 389 | Приемлемо, но LDAPS предпочтительнее |
| **LDAPS** | TLS с момента установления (порт 636) | Рекомендуется |
| **SASL/GSSAPI** | Kerberos-аутентификация | Для сред с Kerberos |

### Минимальные требования безопасности

1. **Шифрование трафика** — LDAPS или StartTLS обязательно
2. **Отключение anonymous bind** — все подключения требуют аутентификации
3. **Минимальные привилегии** — Bind DN с правами только на чтение (для приложений)
4. **Политики паролей** — сложность, история, ротация, блокировка
5. **Аудит** — логирование всех операций bind и ошибок доступа

## Практические сценарии

### 1. Настройка LDAPS (OpenLDAP)

```bash
# Генерация сертификата CA и сервера
openssl req -new -x509 -nodes -days 3650 \
  -newkey rsa:4096 -keyout /etc/openldap/certs/ca.key \
  -out /etc/openldap/certs/ca.crt \
  -subj "/CN=LDAP CA"

openssl req -new -nodes -days 3650 \
  -newkey rsa:2048 -keyout /etc/openldap/certs/ldap.key \
  -out /etc/openldap/certs/ldap.csr \
  -subj "/CN=ldap.example.com"

openssl x509 -req -days 3650 \
  -in /etc/openldap/certs/ldap.csr \
  -CA /etc/openldap/certs/ca.crt \
  -CAkey /etc/openldap/certs/ca.key \
  -CAcreateserial \
  -out /etc/openldap/certs/ldap.crt

# Импорт сертификатов в cn=config
ldapmodify -Y EXTERNAL -H ldapi:/// <<EOF
dn: cn=config
changetype: modify
add: olcTLSCertificateFile
olcTLSCertificateFile: /etc/openldap/certs/ldap.crt
-
add: olcTLSCertificateKeyFile
olcTLSCertificateKeyFile: /etc/openldap/certs/ldap.key
-
add: olcTLSCACertificateFile
olcTLSCACertificateFile: /etc/openldap/certs/ca.crt
EOF

# Запуск slapd с поддержкой LDAPS
slapd -h "ldap:/// ldaps:/// ldapi:///" -u ldap -g ldap
```

### 2. Настройка LDAPS (389DS)

```bash
# Через dsconf
dsconf -D "cn=Directory Manager" ldap://localhost config replace \
  nsslapd-sslport=3636 \
  nsslapd-security: nsTLS=true

# Импорт сертификата
certutil -d /etc/dirsrv/slapd-localhost -A -n "LDAP CA" -i ca.crt -t CT,C,C
certutil -d /etc/dirsrv/slapd-localhost -A -n "LDAP Server" -i ldap.crt -t u,u,u
```

### 3. Отключение anonymous bind

**OpenLDAP:**

```bash
ldapmodify -Y EXTERNAL -H ldapi:/// <<EOF
dn: olcDatabase={1}mdb,cn=config
changetype: modify
add: olcRequires
olcRequires: authc
EOF
```

**389DS:**

```bash
dsconf -D "cn=Directory Manager" ldap://localhost config replace \
  nsslapd-allow-anonymous-access=off
```

### 4. Настройка SSF (Security Strength Factor)

**389DS:**

```bash
# Минимальный SSF для всех операций
dsconf -D "cn=Directory Manager" ldap://localhost config replace \
  nsslapd-minssf=128 \
  nsslapd-minssf-exclude-rootdn=off

# SSF в ACI (пример: требовать TLS для записи)
# aci: (version 3.0; acl "Write with TLS";
#   allow (write) userdn="ldap:///self" and ssf >= 128;)
```

**OpenLDAP:**

```bash
ldapmodify -Y EXTERNAL -H ldapi:/// <<EOF
dn: olcDatabase={-1}frontend,cn=config
changetype: modify
add: olcRequires
olcRequires: ssf=128
EOF
```

### 5. Настройка политики паролей (ppolicy)

**OpenLDAP:**

```bash
# Включение модуля
ldapmodify -Y EXTERNAL -H ldapi:/// <<EOF
dn: cn=module{0},cn=config
changetype: modify
add: olcModuleLoad
olcModuleLoad: ppolicy.la
EOF

# Создание политики по умолчанию
ldapadd -x -D "cn=admin,dc=example,dc=com" -W <<EOF
dn: ou=policies,dc=example,dc=com
objectClass: organizationalUnit
ou: policies

dn: cn=default,ou=policies,dc=example,dc=com
objectClass: pwdPolicy
objectClass: person
objectClass: top
cn: default
sn: default
pwdAttribute: userPassword
pwdMinAge: 0
pwdMaxAge: 7776000
pwdMinLength: 12
pwdInHistory: 5
pwdCheckQuality: 2
pwdMaxFailure: 5
pwdLockout: TRUE
pwdLockoutDuration: 900
pwdGraceAuthNLimit: 0
pwdFailureCountInterval: 600
pwdMustChange: FALSE
pwdAllowUserChange: TRUE
pwdSafeModify: FALSE
EOF
```

**389DS:**

```bash
# Включение Account Policy
dsconf -D "cn=Directory Manager" ldap://localhost plugin account-policy-enable enable
dsconf -D "cn=Directory Manager" ldap://localhost plugin account-policy-enable set \
  --state-attr accountStatus \
  --bind-policy-bindDN "cn=Account Policy Plugin,cn=plugins,cn=config"
```

### 6. Настройка ACL для敏感ных атрибутов

**OpenLDAP (защита userPassword):**

```bash
ldapmodify -Y EXTERNAL -H ldapi:/// <<EOF
dn: olcDatabase={1}mdb,cn=config
changetype: modify
replace: olcAccess
olcAccess: {0}to attrs=userPassword
  by self write
  by anonymous auth
  by dn="cn=admin,dc=example,dc=com" write
  by * none
olcAccess: {1}to attrs=shadowLastChange
  by self write
  by dn="cn=admin,dc=example,dc=com" write
  by * read
olcAccess: {2}to *
  by dn="cn=admin,dc=example,dc=com" write
  by self read
  by * read
EOF
```

**389DS (защита через ACI):**

```bash
# Запрет на чтение userPassword для анонимных
dsconf -D "cn=Directory Manager" ldap://localhost aci add "ou=people,dc=example,dc=com" \
  --name "Protect passwords" \
  --type "deny" \
  --permission "read" \
  --userdn "ldap:///anyone" \
  --targetattr "userPassword"
```

### 7. Ограничение Root DSE

**OpenLDAP:**

```bash
ldapmodify -Y EXTERNAL -H ldapi:/// <<EOF
dn: olcDatabase={-1}frontend,cn=config
changetype: modify
add: olcRequires
olcRequires: authc
EOF
```

**389DS:**

```bash
dsconf -D "cn=Directory Manager" ldap://localhost config replace \
  nsslapd-allow-anonymous-access=off
```

### 8. Настройка файрвола

```bash
# firewalld (RHEL/Rocky)
sudo firewall-cmd --permanent --add-service=ldap
sudo firewall-cmd --permanent --add-service=ldaps
sudo firewall-cmd --reload

# ufw (Debian/Ubuntu)
sudo ufw allow 389/tcp
sudo ufw allow 636/tcp

# iptables
sudo iptables -A INPUT -p tcp --dport 389 -s 10.0.0.0/8 -j ACCEPT
sudo iptables -A INPUT -p tcp --dport 636 -s 10.0.0.0/8 -j ACCEPT
sudo iptables -A INPUT -p tcp --dport 389 -j DROP
sudo iptables -A INPUT -p tcp --dport 636 -j DROP
```

### 9. Аудит и логирование

**389DS (включение аудита):**

```bash
dsconf -D "cn=Directory Manager" ldap://localhost config replace \
  nsslapd-auditlog-logging-enabled=on \
  nsslapd-auditlog-path=/var/log/dirsrv/slapd-localhost/audit
```

**OpenLDAP (настройка логирования):**

```bash
# Уровень логирования
ldapmodify -Y EXTERNAL -H ldapi:/// <<EOF
dn: olcDatabase={-1}frontend,cn=config
changetype: modify
add: olcLogLevel
olcLogLevel: stats acl
EOF
```

### 10. Защита от брутфорса (fail2ban)

**389DS:**

```bash
# /etc/fail2ban/filter.d/ldap.conf
[Definition]
failregex = .<SYNTAX>.*"cn=.*".*ldap://.* err=49
            .<SYNTAX>.*"cn=.*".*ldap://.* err=48
ignoreregex =

# /etc/fail2ban/jail.d/ldap.conf
[ldap]
enabled = true
port = ldap,ldaps
filter = ldap
logpath = /var/log/dirsrv/slapd-localhost/errors
maxretry = 5
bantime = 3600
findtime = 600
```

**OpenLDAP:**

```bash
# /etc/fail2ban/filter.d/slapd.conf
[Definition]
failregex = . slapd_.*conn=.* op=.* RESULT.*err=49
            . slapd_.*conn=.* op=.* RESULT.*err=48
ignoreregex =

# /etc/fail2ban/jail.d/slapd.conf
[slapd]
enabled = true
port = ldap,ldaps
filter = slapd
logpath = /var/log/slapd.log
maxretry = 5
bantime = 3600
findtime = 600
```

**Проверка:**

```bash
sudo fail2ban-client status ldap
sudo fail2ban-client set ldap unbanip 10.0.0.50
```

### 11. Автоматические сертификаты (Let's Encrypt)

**Установка и получение сертификата:**

```bash
# Установка certbot
sudo dnf install certbot -y

# Остановка LDAP перед получением сертификата
sudo systemctl stop slapd

# Получение сертификата (DNS-валидация для внутренних серверов)
sudo certbot certonly --manual --preferred-challenges dns \
  -d ldap.example.com

# Копирование сертификатов
sudo cp /etc/letsencrypt/live/ldap.example.com/fullchain.pem \
  /etc/openldap/certs/ldap.crt
sudo cp /etc/letsencrypt/live/ldap.example.com/privkey.pem \
  /etc/openldap/certs/ldap.key

# Запуск LDAP
sudo systemctl start slapd
```

**Автообновление:**

```bash
# /etc/certbot/renewal-hooks/post/restart-ldap.sh
#!/bin/bash
cp /etc/letsencrypt/live/ldap.example.com/fullchain.pem \
  /etc/openldap/certs/ldap.crt
cp /etc/letsencrypt/live/ldap.example.com/privkey.pem \
  /etc/openldap/certs/ldap.key
chown ldap:ldap /etc/openldap/certs/ldap.*
systemctl restart slapd

# Cron для автообновления
0 3 * * * certbot renew --quiet --deploy-hook /etc/certbot/renewal-hooks/post/restart-ldap.sh
```

**389DS через certbot:**

```bash
#!/bin/bash
# /etc/certbot/renewal-hooks/post/restart-389ds.sh
certutil -d /etc/dirsrv/slapd-localhost -D -n "LDAP Server"
certutil -d /etc/dirsrv/slapd-localhost -A -n "LDAP Server" \
  -i /etc/letsencrypt/live/ldap.example.com/fullchain.pem -t u,u,u
certutil -d /etc/dirsrv/slapd-localhost -A -n "LDAP Key" \
  -i /etc/letsencrypt/live/ldap.example.com/privkey.pem -t u,u,u
systemctl restart dirsrv
```

### 12. Security Hardening Checklist (полный)

```text
[ ] TLS настроен (LDAPS или StartTLS)
[ ] Anonymous bind отключен
[ ] Bind DN имеет минимальные привилегии
[ ] Политика паролей настроена (ppolicy/Account Policy)
[ ] userPassword защищен ACL/ACI
[ ] Root DSE ограничен от анонимного доступа
[ ] Файрвол ограничивает доступ по IP
[ ] Аудит включен
[ ] Логи собираются централизованно
[ ] Сертификаты имеют достаточный срок действия
[ ] Ротация сертификатов настроена (certbot)
[ ] NTP синхронизирован (для Kerberos и репликации)
[ ] fail2ban защищает от брутфорса
[ ] SSF >= 128 включен
[ ] Минимальные версии TLS (1.2+)
[ ] Старые шифры отключены (RC4, DES, 3DES)
[ ] Лимит соединений настроен
[ ] non-root UID для slapd/ns-slapd
[ ] Директория БД доступна только сервисному пользователю
[ ] Регулярный аудит ACI/ACL
```

## Дополнительная информация

### Чеклист безопасности для production

```text
[ ] TLS настроен (LDAPS или StartTLS)
[ ] Anonymous bind отключен
[ ] Bind DN имеет минимальные привилегии
[ ] Политика паролей настроена (ppolicy/Account Policy)
[ ] userPassword защищен ACL/ACI
[ ] Root DSE ограничен от анонимного доступа
[ ] Файрвол ограничивает доступ по IP
[ ] Аудит включен
[ ] Логи собираются централизованно
[ ] Сертификаты имеют достаточный срок действия
[ ] Ротация сертификатов настроена
[ ] NTP синхронизирован (для Kerberos и репликации)
```

### Соответствие стандартам

| Стандарт | Требования к LDAP |
|:---|:---|
| **SOC 2** | Шифрование транспорта, аудит доступа, контроль привилегий |
| **PCI-DSS** | TLS 1.2+, ротация паролей, логирование |
| **HIPAA** | Шифрование данных, аудит, контроль доступа |
| **ISO 27001** | Политика паролей, управление доступом, аудит |

### См. также

- **[LDAP: основы протокола](./ldap_fundamentals.md)** — терминология
- **[389DS: ACI](./389ds/aci.md)** — управление доступом в 389DS
- **[LDAP Troubleshooting](./ldap_troubleshooting.md)** — диагностика проблем
- **[LDAP + SSSD](../Linux/SystemAdministration/Users/LDAP_SSSD/index.md)** — безопасность SSSD
- **[Kerberos](../Security/Concepts/kerberos.md)** — аутентификация через Kerberos
- **[LDAP: аудит и compliance](./ldap_audit_compliance.md)** — PCI DSS, HIPAA, чеклисты
