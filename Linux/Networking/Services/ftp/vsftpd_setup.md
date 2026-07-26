# vsftpd: Настройка FTPS и виртуальных пользователей

| Метаданные | Значение |
| :--- | :--- |
| **Оценка надёжности** | 10 (Централизованный материал + проверенные сценарии) |
| **Актуальность** | Июль 2024 (vsftpd 3.0+) |

---

## Определения

**vsftpd (Very Secure FTP Daemon)** — производительный и безопасный FTP-сервер для Unix-подобных систем, ориентированный на защиту от эксплойтов и высокую скорость работы.

**FTPS (FTP over SSL/TLS)** — расширение протокола FTP, использующее шифрование TLS (Transport Layer Security) для защиты управляющего соединения и канала передачи данных.

**Виртуальные пользователи** — метод аутентификации, при котором учетные данные хранятся во внешнем источнике (БД, файл), а не в системном `/etc/passwd`. Это исключает возможность получения shell-доступа и ограничивает пользователя только FTP-сервисом.

---

## Основные концепции

### Режимы передачи данных
FTP использует два раздельных соединения: управляющее (порт 21) и соединение данных.
- **Активный режим:** Сервер инициирует соединение с клиентом. Часто блокируется клиентскими файрволами.
- **Пассивный режим (рекомендуется):** Клиент инициирует соединение с сервером на динамический порт. Требует открытия диапазона портов на стороне сервера.

### Безопасность FTPS
- **Explicit FTPS (явный):** Клиент подключается к порту 21 и запрашивает переход на шифрование командой `AUTH TLS`.
- **Implicit FTPS (неявный):** Соединение шифруется сразу при установке (обычно порт 990). Считается устаревшим, vsftpd по умолчанию использует явный режим.
- **SSL Reuse:** Требование использовать одну и ту же TLS-сессию для управления и данных. Повышает защиту от перехвата сессии, но может вызывать проблемы с некоторыми клиентами (требует `require_ssl_reuse=NO` в таких случаях).

---

## Практические сценарии

### Развёртывание FTPS с виртуальными пользователями (Ubuntu/Debian)

Сценарий описывает настройку сервера с хранением паролей в Berkeley DB и полной изоляцией пользователей.

#### Шаг 1. Установка компонентов

```bash
sudo apt update
sudo apt install vsftpd db-util -y
# → success
```

#### Шаг 2. Генерация SSL-сертификата

Для защиты трафика создадим самоподписанный сертификат (в production рекомендуется использовать Let's Encrypt).

```bash
sudo openssl req -new -x509 -days 365 -nodes \
  -out /etc/ssl/certs/vsftpd.pem \
  -keyout /etc/ssl/private/vsftpd.key \
  -subj "/C=RU/ST=Moscow/L=Moscow/O=DevOps/OU=IT/CN=vsftpd.local"
```

#### Шаг 3. Конфигурация виртуальных пользователей

1.  **Создание базы данных:**
    Создайте текстовый файл `/etc/vsftpd/virtual_users.txt` (доступ только root):
    ```text
    ftpuser1
    securepassword1
    ```
    Сгенерируйте бинарную БД:
    ```bash
    sudo mkdir -p /etc/vsftpd
    sudo db_load -T -t hash -f /etc/vsftpd/virtual_users.txt /etc/vsftpd/virtual_users.db
    sudo chmod 600 /etc/vsftpd/virtual_users.db
    ```

2.  **Настройка PAM:**
    Создайте файл `/etc/pam.d/vsftpd.virtual`:
    ```bash
    auth required pam_userdb.so db=/etc/vsftpd/virtual_users
    account required pam_userdb.so db=/etc/vsftpd/virtual_users
    ```

3.  **Системный пользователь:**
    Все виртуальные пользователи будут работать от имени одного системного аккаунта:
    ```bash
    sudo useradd -d /home/vsftpd -s /usr/sbin/nologin -M vsftpd
    sudo mkdir -p /home/vsftpd/ftpuser1
    sudo chown -R vsftpd:vsftpd /home/vsftpd/
    ```

#### Шаг 4. Настройка vsftpd.conf

Отредактируйте `/etc/vsftpd.conf`:

```ini
# Общие настройки
listen=YES
anonymous_enable=NO
local_enable=YES
write_enable=YES
local_umask=022

# Виртуальные пользователи
guest_enable=YES
guest_username=vsftpd
virtual_use_local_privs=YES
pam_service_name=vsftpd.virtual
user_sub_token=$USER
local_root=/home/vsftpd/$USER

# Изоляция
chroot_local_user=YES
allow_writeable_chroot=YES

# Пассивный режим (для NAT/Firewall)
pasv_enable=YES
pasv_min_port=40000
pasv_max_port=40100

# Настройки SSL/TLS
ssl_enable=YES
allow_anon_ssl=NO
force_local_data_ssl=YES
force_local_logins_ssl=YES
ssl_tlsv12=YES
ssl_tlsv13=YES
# Отключите, если клиент выдает ошибку "GnuTLS error -110"
require_ssl_reuse=NO
rsa_cert_file=/etc/ssl/certs/vsftpd.pem
rsa_private_key_file=/etc/ssl/private/vsftpd.key

# Логирование
xferlog_enable=YES
vsftpd_log_file=/var/log/vsftpd.log
```

#### Шаг 5. Настройка Firewall

**UFW:**
```bash
sudo ufw allow 21/tcp
sudo ufw allow 40000:40100/tcp
sudo ufw reload
```

**Firewalld:**
```bash
sudo firewall-cmd --permanent --add-port=21/tcp
sudo firewall-cmd --permanent --add-port=40000-40100/tcp
sudo firewall-cmd --reload
```

---

## Дополнительная информация

### Устранение неполадок

- **Ошибка 500 OOPS (chroot):** Убедитесь, что установлена директива `allow_writeable_chroot=YES`, если домашняя директория пользователя доступна на запись.
- **SELinux (RHEL/CentOS):** Если FTP не может писать файлы, проверьте булевы переменные:
  ```bash
  setsebool -P ftpd_full_access on
  ```
- **AppArmor (Ubuntu):** Если vsftpd не может прочитать файл базы данных пользователей, проверьте `/etc/apparmor.d/usr.sbin.vsftpd` или временно переведите профиль в режим обучения (`complain`).

### Безопасность

- **SFTP vs FTPS:** Рекомендуется использовать **SFTP** (через SSH), так как он проще в настройке (один порт 22) и более устойчив к проблемам с NAT. FTPS следует использовать только при наличии специфических требований к протоколу FTP.
- **Лимиты:** Используйте `max_clients` и `max_per_ip` для защиты от DoS-атак.

### Связанные темы

- **[Прикладной уровень (L7): FTP](../../Networking/OSI_TCP_IP_Model/application_layer.md#основные-протоколы-прикладного-уровня)** — теоретические основы протокола.
- **[Ограничение сервисов (chroot)](../../Linux/Core/chroot.md#3-области-применения)** — механизмы изоляции в Linux.
- **[TCP Wrappers](../../Linux/Networking/tcp_wrappers.md)** — фильтрация доступа к vsftpd по IP.
