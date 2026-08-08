# vsftpd: Настройка FTPS и виртуальных пользователей

---

## Определения

**vsftpd (Very Secure FTP Daemon)** — производительный и безопасный FTP-сервер для Unix-подобных систем, ориентированный на защиту от эксплойтов и высокую скорость работы.

**FTPS (FTP over SSL/TLS)** — расширение протокола FTP, использующее шифрование TLS (Transport Layer Security) для защиты управляющего соединения и канала передачи данных.

**Виртуальные пользователи** — метод аутентификации, при котором учетные данные хранятся во внешнем источнике (БД, файл), а не в системном `/etc/passwd`. Это исключает возможность получения shell-доступа и ограничивает пользователя только FTP-сервисом.

---

## Основные концепции

### Режимы передачи данных

FTP использует два раздельных соединения: управляющее (порт 21) и соединение данных (порт 20 в активном режиме или динамический порт в пассивном).

- **Активный режим:** Клиент сообщает серверу свой IP и порт через команду `PORT`, и сервер инициирует соединение со своего порта 20 на порт клиента. Часто блокируется клиентскими файрволами и NAT.
- **Пассивный режим (рекомендуется):** Клиент отправляет команду `PASV`, сервер открывает динамический порт и сообщает его клиенту. Клиент инициирует соединение. Требует открытия диапазона портов (`pasv_min_port` / `pasv_max_port`) на стороне сервера.

### Безопасность FTPS

- **Explicit FTPS (явный):** Клиент подключается к стандартному порту 21 и запрашивает переход на шифрование командой `AUTH TLS`. Это наиболее гибкий и современный метод.
- **Implicit FTPS (неявный):** Соединение шифруется сразу при установке (обычно порт 990). Считается устаревшим, так как требует отдельного порта для каждой службы, vsftpd по умолчанию ориентирован на явный режим.
- **SSL Reuse:** Требование использовать одну и ту же TLS-сессию для управляющего соединения и канала данных. Это защищает от атак подмены сессии (Session Hijacking). Некоторые старые клиенты не поддерживают это, что требует `require_ssl_reuse=NO`.

---

## Практические сценарии

### Развёртывание FTPS с виртуальными пользователями (Ubuntu/Debian)

Сценарий описывает настройку сервера с хранением паролей в Berkeley DB и полной изоляцией пользователей через `chroot`.

#### Шаг 1. Установка компонентов

```bash
sudo apt update
sudo apt install vsftpd db-util -y
# → success
```

#### Шаг 2. Генерация SSL-сертификата

Создадим самоподписанный сертификат сроком на один год.

```bash
sudo openssl req -new -x509 -days 365 -nodes \
  -out /etc/ssl/certs/vsftpd.pem \
  -keyout /etc/ssl/private/vsftpd.key \
  -subj "/C=RU/ST=Moscow/L=Moscow/O=DevOps/OU=IT/CN=vsftpd.local"
# → Generated /etc/ssl/certs/vsftpd.pem and /etc/ssl/private/vsftpd.key
```

#### Шаг 3. Конфигурация виртуальных пользователей

1.  **Создание базы данных:**
    Создайте текстовый файл `/etc/vsftpd/virtual_users.txt` со списком «логин — следующая строка пароль»:
    ```text
    ftpuser1
    securepassword1
    ```
    Сгенерируйте бинарную БД (Berkeley DB):
    ```bash
    sudo mkdir -p /etc/vsftpd
    sudo db_load -T -t hash -f /etc/vsftpd/virtual_users.txt /etc/vsftpd/virtual_users.db
    sudo chmod 600 /etc/vsftpd/virtual_users.db
    ```

2.  **Настройка PAM (Pluggable Authentication Modules):**
    Укажите vsftpd использовать созданную БД для проверки подлинности. Отредактируйте или создайте `/etc/pam.d/vsftpd.virtual`:
    ```bash
    auth required pam_userdb.so db=/etc/vsftpd/virtual_users
    account required pam_userdb.so db=/etc/vsftpd/virtual_users
    ```

3.  **Системный пользователь и директории:**
    Виртуальные пользователи сопоставляются с одним реальным системным аккаунтом без права входа в систему.
    ```bash
    sudo useradd -d /home/vsftpd -s /usr/sbin/nologin -M vsftpd
    sudo mkdir -p /home/vsftpd/ftpuser1
    sudo chown -R vsftpd:vsftpd /home/vsftpd/
    ```

#### Шаг 4. Настройка vsftpd.conf

Основной конфигурационный файл `/etc/vsftpd.conf`:

```ini
# Общие настройки
listen=YES
anonymous_enable=NO
local_enable=YES
write_enable=YES
local_umask=022
dirmessage_enable=YES
use_localtime=YES

# Виртуальные пользователи
guest_enable=YES
guest_username=vsftpd
virtual_use_local_privs=YES
pam_service_name=vsftpd.virtual
user_sub_token=$USER
local_root=/home/vsftpd/$USER

# Изоляция и безопасность
chroot_local_user=YES
allow_writeable_chroot=YES
hide_ids=YES

# Пассивный режим (обязателен для работы через NAT)
pasv_enable=YES
pasv_min_port=40000
pasv_max_port=40100
# Если сервер за NAT, укажите внешний IP:
# pasv_address=EXTERNAL_IP

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
log_ftp_protocol=NO
```

Перезапустите сервис:
```bash
sudo systemctl restart vsftpd
# → active (running)
```

#### Шаг 5. Настройка Firewall

**UFW (Ubuntu):**
```bash
sudo ufw allow 21/tcp
sudo ufw allow 40000:40100/tcp
sudo ufw reload
```

**Firewalld (RHEL/CentOS):**
```bash
sudo firewall-cmd --permanent --add-port=21/tcp
sudo firewall-cmd --permanent --add-port=40000-40100/tcp
sudo firewall-cmd --reload
```

### Проверка подключения

Для тестирования FTPS рекомендуется использовать консольную утилиту `lftp` или FileZilla.

**Пример с lftp:**
```bash
lftp -u ftpuser1,securepassword1 -e "set ftp:ssl-force true; set ssl:verify-certificate no; ls; quit" localhost
# → drwxr-xr-x    2 1001     1001         4096 Jul 24 12:00 .
```

---

## Дополнительная информация

### Особенности RHEL/CentOS

1.  **Пакеты:** Вместо `db-util` используется `libdb-utils`.
2.  **SELinux:** По умолчанию блокирует доступ к домашним директориям и запись.
    ```bash
    # Разрешить чтение/запись для FTP
    setsebool -P ftpd_full_access on
    # Если используются нестандартные порты
    semanage port -a -t ftp_port_t -p tcp 40000-40100
    ```

### Устранение неполадок

- **Ошибка 500 OOPS (chroot):** Если `allow_writeable_chroot=YES` не помогает, проверьте права на корневую директорию пользователя — она не должна быть доступна на запись, если эта опция выключена.
- **Ошибка "GnuTLS error -110":** Часто связана с несовместимостью SSL Reuse. Установите `require_ssl_reuse=NO`.
- **Логи:** При возникновении проблем всегда проверяйте `/var/log/vsftpd.log` и системный журнал `journalctl -u vsftpd`.

### Производительность и лимиты

Для защиты от злоупотреблений и оптимизации ресурсов добавьте в `vsftpd.conf`:
- `max_clients=50` — общее число одновременных подключений.
- `max_per_ip=5` — лимит подключений с одного IP-адреса.
- `local_max_rate=500000` — ограничение скорости передачи (байт/сек) для авторизованных пользователей.
- `connect_timeout=60` — таймаут ожидания ответа от клиента.

### Мониторинг и логирование

- **Systemd:** Для просмотра последних событий используйте `sudo journalctl -u vsftpd -f`.
- **Просмотр текущих сессий:** Команда `ps aux | grep vsftpd` покажет процессы для каждого активного пользователя.
- **Внешний мониторинг:** Можно использовать `prometheus-vsftpd-exporter` для сбора метрик о количестве пользователей и объеме трафика.

### Безопасность

- **SFTP vs FTPS:** Рекомендуется использовать **SFTP** (SSH File Transfer Protocol), так как он требует только один порт (22) и изначально более защищен. FTPS используется при необходимости строгой совместимости с FTP-инфраструктурой.
- **Защита от перебора (Brute-force):** Рекомендуется настроить `fail2ban` для мониторинга `/var/log/vsftpd.log`.

### Связанные темы

- **[Прикладной уровень (L7): FTP](../../Networking/OSI_TCP_IP_Model/application_layer.md#основные-протоколы-прикладного-уровня)** — теоретические основы протокола.
- **[Ограничение сервисов (chroot)](../../Linux/Core/chroot.md#3-области-применения)** — механизмы изоляции в Linux.
- **[TCP Wrappers](../../Linux/Networking/tcp_wrappers.md)** — фильтрация доступа к vsftpd по IP.
