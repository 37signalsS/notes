# FTP-серверы: Сравнение vsftpd, ProFTPD и Pure-FTPd

---

## Определения

**vsftpd (Very Secure FTP Daemon)** — высокопроизводительный и безопасный FTP-сервер, ориентированный на защиту от эксплойтов. Стандарт для Debian/Ubuntu.

**ProFTPD** — модульный FTP-сервер с гибкой конфигурацией, поддержкой LDAP, SQL, TLS и расширяемой архитектурой через модули.

**Pure-FTPd** — легковесный FTP-сервер с фокусом на простоту и безопасность. Поддерживает виртуальных пользователей, LDAP, MySQL и TLS.

**FTP-сервер** — демон, обрабатывающий запросы на передачу файлов по протоколу FTP/FTPS. Основные функции: аутентификация, авторизация, передача данных, безопасность.

---

## Основные концепции

### Сравнительная таблица

| Характеристика | vsftpd | ProFTPD | Pure-FTPd |
| :--- | :--- | :--- | :--- |
| **Производительность** | Высокая | Средняя | Высокая |
| **Безопасность** | Отличная (ограниченные привилегии) | Хорошая (модульная) | Хорошая (простота) |
| **Конфигурация** | Одиночный файл | Модульная | Модульная |
| **LDAP/AD** | Через PAM | Встроенный модуль | Встроенный модуль |
| **SQL-аутентификация** | Через PAM | Встроенный модуль | Встроенный модуль |
| **Виртуальные пользователи** | Да (guest_enable) | Да (SQL/LDAP) | Да (LDAP/MySQL) |
| **TLS/SSL** | Да | Да | Да |
| **Chroot** | Встроенный | Встроенный | Встроенный |
| **Ограничение скорости** | Да | Да | Да |
| **Сетевые подключения** | Ограниченные | Расширяемые | Расширяемые |
| **Логирование** | xferlog, syslog | Syslog, SQL | Syslog, SQL |
| **Пакеты** | Основной в большинстве Дистрибутивов | Доступен в большинстве | Доступен в большинстве |
| **Поддержка** | Активная | Активная | Активная |

### Критерии выбора

**Выбирайте vsftpd, если:**
- Нужна максимальная безопасность
- Используете Debian/Ubuntu (установлен по умолчанию)
- Требуется простая конфигурация
- Не нужна интеграция с LDAP/SQL напрямую

**Выбирайте ProFTPD, если:**
- Нужна интеграция с LDAP/Active Directory
- Требуется гибкая модульная архитектура
- Нужна интеграция с SQL для аутентификации
- Планируется использование расширенных модулей (mod_sftp, mod_tls)

**Выбирайте Pure-FTPd, если:**
- Нужна простота настройки
- Требуется встроенная поддержка LDAP/MySQL
- Важна минимальная потребление ресурсов
- Нужна автоматическая генерация сертификатов

### Архитектурные различия

**vsftpd:**
- Монолитная архитектура
- Минимальная зависимость от внешних библиотек
- Фокус на безопасности через изоляцию процессов
- Ограниченные возможности расширения

**ProFTPD:**
- Модульная архитектура
- Поддержка DSO (Dynamic Shared Objects)
- Гибкая система конфигурации через `<IfModule>`
- Возможность расширения через собственные модули

**Pure-FTPd:**
- Легковесная архитектура
- Минимальные зависимости
- Встроенная поддержка виртуальных пользователей
- Автоматическое управление сертификатами

---

## Практические сценарии

### 1. Установка и базовая настройка

#### vsftpd (уже установлен)

```bash
# Проверка установки
dpkg -l | grep vsftpd
# → ii  vsftpd 3.0.3-13build1 amd64 ... Very Secure FTP Daemon

# Конфигурация
sudo vim /etc/vsftpd.conf
# → См. vsftpd_setup.md для полной настройки
```

#### ProFTPD

```bash
# Установка
sudo apt update
sudo apt install proftpd-basic -y

# Конфигурация
sudo vim /etc/proftpd/proftpd.conf

# Базовые настройки
ServerName "ProFTPD Server"
ServerType standalone
DefaultServer on

# Порт
Port 21

# Безопасность
User nobody
Group nogroup
Umask 022
MaxClients 50
MaxClientsPerHost 5
MaxClientsPerUser 5
MaxIdentLookups 10
ServerIdent on "FTP Server Ready"

# TLS
<IfModule mod_tls.c>
    TLSEngine on
    TLSLog /var/log/proftpd/tls.log
    TLSRequired on
    TLSRSACertificateFile /etc/ssl/certs/proftpd.pem
    TLSRSACertificateKeyFile /etc/ssl/private/proftpd.key
    TLSOptions NoSessionReuseRequired
    TLSProtocol TLSv1.2 TLSv1.3
</IfModule>

# Chroot
DefaultRoot ~
AllowOverride off

# Запуск
sudo systemctl enable --now proftpd
```

#### Pure-FTPd

```bash
# Установка
sudo apt update
sudo apt install pure-ftpd-common pure-ftpd -y

# Конфигурация через файл-флаги
sudo ln -s /etc/pure-ftpd/conf/TLS /etc/pure-ftpd/auth/TLS
echo 1 | sudo tee /etc/pure-ftpd/conf/TLS

# Сертификаты
sudo mkdir -p /etc/ssl/private
sudo openssl req -new -x509 -days 365 -nodes \
  -out /etc/ssl/certs/pure-ftpd.pem \
  -keyout /etc/ssl/private/pure-ftpd.key \
  -subj "/C=RU/ST=Moscow/L=Moscow/O=DevOps/CN=pure-ftpd.local"

# Запуск
sudo systemctl enable --now pure-ftpd
```

### 2. Интеграция с LDAP

#### vsftpd (через PAM)

```bash
# /etc/pam.d/vsftpd.virtual
auth required pam_ldap.so
account required pam_ldap.so

# /etc/libnss-ldap.conf
base dc=example,dc=com
uri ldap://ldap.example.com
ldap_version 3
pam_filter objectclass=posixAccount
pam_login_attribute uid
pam_member_attribute memberUid
```

#### ProFTPD (встроенный модуль)

```apache
# /etc/proftpd/proftpd.conf
<IfModule mod_ldap.c>
    LDAPServer ldap.example.com
    LDAPBase DC=example,DC=com
    LDAPBindDN "cn=ldap-admin,dc=example,dc=com"
    LDAPBindPassword "ldap-password"
    LDAPUsers "(&(objectClass=posixAccount)(uid=%u))"
    LDAPSearchScope "one"
    LDAPUseTLS on
</IfModule>
```

#### Pure-FTPd (встроенный)

```bash
# Включение LDAP
echo 1 | sudo tee /etc/pure-ftpd/conf/LDAP

# Конфигурация LDAP
sudo vim /etc/pure-ftpd/conf/LDAPConfigFile
# → /etc/pure-ftpd/ldap.conf

# /etc/pure-ftpd/ldap.conf
LDAPServer ldap.example.com
LDAPBase DC=example,DC=com
LDAPBindDN cn=ldap-admin,dc=example,dc=com
LDAPBindPassword ldap-password
LDAPFilter (&(objectClass=posixAccount)(uid=$M))
LDAPVersion 3
```

### 3. Интеграция с SQL (MySQL/PostgreSQL)

#### ProFTPD

```apache
# /etc/proftpd/proftpd.conf
<IfModule mod_sql.c>
    SQLBackend mysql
    SQLAuthTypes Backend Crypt
    SQLConnectInfo ftpdb@localhost ftpuser ftppass
    SQLUserInfo ftpusers userid passwd uid gid homedir shell
    SQLMinID 500
    SQLNegativeCache on
    SQLHomedirOnDemand on
</IfModule>
```

#### Pure-FTPd

```bash
# Включение MySQL
echo 1 | sudo tee /etc/pure-ftpd/conf/MySQLConfigFile

# /etc/pure-ftpd/conf/MySQLConfigFile
# → /etc/pure-ftpd/mysql.conf

# /etc/pure-ftpd/mysql.conf
MySQLServer localhost
MySQLPort 3306
MySQLUser ftpuser
MySQLPassword ftppass
MySQLDatabase ftpdb
MySQLCrypt MD5
MySQLGetPW SELECT password FROM users WHERE user="\L"
MySQLGetUID SELECT uid FROM users WHERE user="\L"
MySQLGetGID SELECT gid FROM users WHERE user="\L"
MySQLGetDir SELECT homedir FROM users WHERE user="\L"
```

---

## Дополнительная информация

### Миграция между серверами

1. **Бэкап конфигурации:** Сохраните текущие конфиги и БД пользователей.
2. **Установка нового сервера:** Установите целевой FTP-сервер.
3. **Конвертация пользователей:** Используйте скрипты для миграции (например, `pure-authd` для перевода пользователей).
4. **Тестирование:** Проверьте доступность файлов и прав.
5. **Переключение:** Обновите DNS или балансировщик.

### Производительность

| Параметр | vsftpd | ProFTPD | Pure-FTPd |
| :--- | :--- | :--- | :--- |
| **Соединений/сек** | ~1000 | ~500 | ~800 |
| **Потребление памяти** | Низкое | Среднее | Низкое |
| **CPU** | Низкий | Средний | Низкий |
| **Безопасность** | Максимальная | Высокая | Высокая |

### Интервью-вопросы

**Q: Какой FTP-сервер выбрать для production?**
A: vsftpd — для максимальной безопасности и простоты. ProFTPD — при необходимости LDAP/SQL интеграции. Pure-FTPd — для легковесных решений.

**Q: Как обеспечить высокую доступность FTP?**
A: Используйте Keepalived + HAProxy или DNS round-robin с несколькими серверами.

**Q: Какой протокол безопаснее: FTPS или SFTP?**
A: SFTP (один порт, шифрование по умолчанию). FTPS требует отдельного порта для данных.

### Связанные темы

- **[vsftpd: настройка](./vsftpd_setup.md)** — детальная настройка vsftpd
- **[SFTP vs FTPS](#sftp-vs-ftps)** — сравнение протоколов шифрования
- **[LDAP: интеграция](./ftp_ldap_integration.md)** — настройка LDAP для FTP
- **[Docker: FTP](./ftp_docker.md)** — контейнеризация FTP-сервера
