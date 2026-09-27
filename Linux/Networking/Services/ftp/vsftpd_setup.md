# vsftpd: Настройка FTPS и виртуальных пользователей

---

## Определения

**vsftpd (Very Secure FTP Daemon)** — производительный и безопасный FTP-сервер для Unix-подобных систем, ориентированный на защиту от эксплойтов и высокую скорость работы.

**FTPS (FTP over SSL/TLS)** — расширение протокола FTP, использующее шифрование TLS (Transport Layer Security) для защиты управляющего соединения и канала передачи данных.

**Виртуальные пользователи** — метод аутентификации, при котором учетные данные хранятся во внешнем источнике (БД, файл), а не в системном `/etc/passwd`. Это исключает возможность получения shell-доступа и ограничивает пользователя только FTP-сервисом.

---

## Основные концепции

### Архитектура vsftpd

vsftpd поддерживает три режима работы:

- **Standalone (рекомендуется для production):** vsftpd запускается как независимый демон, управляемый systemd. Это наиболее гибкий режим, позволяющий использовать все возможности (виртуальные пользователи, TLS, лимиты).
- **inetd/xinetd (legacy):** Супер-сервер запускает vsftpd при каждом подключении. Менее производителен, но удобен для низконагруженных сервисов.
- **Systemd socket activation:** Современный аналог inetd. Systemd слушает порт 21 и запускает vsftpd по требованию. Позволяет гранулярно управлять ресурсами через юниты systemd.

Для production-сред используется standalone-режим с systemd-юнитом `vsftpd.service`.

### Режимы передачи данных

FTP использует два раздельных соединения: управляющее (порт 21) и соединение данных (порт 20 в активном режиме или динамический порт в пассивном).

- **Активный режим:** Клиент сообщает серверу свой IP и порт через команду `PORT`, и сервер инициирует соединение со своего порта 20 на порт клиента. Часто блокируется клиентскими файрволами и NAT.
- **Пассивный режим (рекомендуется):** Клиент отправляет команду `PASV`, сервер открывает динамический порт и сообщает его клиенту. Клиент инициирует соединение. Требует открытия диапазона портов (`pasv_min_port` / `pasv_max_port`) на стороне сервера.

### Безопасность FTPS

- **Explicit FTPS (явный):** Клиент подключается к стандартному порту 21 и запрашивает переход на шифрование командой `AUTH TLS`. Это наиболее гибкий и современный метод.
- **Implicit FTPS (неявный):** Соединение шифруется сразу при установке (обычно порт 990). Считается устаревшим, так как требует отдельного порта для каждой службы, vsftpd по умолчанию ориентирован на явный режим.
- **SSL Reuse:** Требование использовать одну и ту же TLS-сессию для управляющего соединения и канала данных. Это защищает от атак подмены сессии (Session Hijacking). Некоторые старые клиенты не поддерживают это, что требует `require_ssl_reuse=NO`.

### Ключевые директивы vsftpd.conf (справочник SRE)

Директивы сгруппированы по области ответственности. Полный список доступен в `man 5 vsftpd.conf`.

**Аутентификация и пользователи:**
- `guest_enable=YES` — активирует режим гостевой аутентификации для виртуальных пользователей.
- `guest_username=vsftpd` — системный аккаунт, от имени которого работают виртуальные пользователи.
- `pam_service_name=vsftpd.virtual` — PAM-сервис для аутентификации виртуальных пользователей.
- `userlist_enable=YES/NO` — включает проверку файла пользовательского листа.
- `userlist_deny=YES/NO` — если YES, пользователи в `userlist_file` запрещены; если NO, только они разрешены.
- `userlist_file=/etc/vsftpd/user_list` — файл со списком пользователей.
- `user_config_dir=/etc/vsftpd/user_conf_dir` — директория с индивидуальными конфигами пользователей (имя файла = логин).

**Изоляция и безопасность:**
- `chroot_local_user=YES` — изолирует каждого локального пользователя в его домашней директории.
- `allow_writeable_chroot=YES` — разрешает запись в chroot (противоположность поведения по умолчанию, требующего не-доступной для записи корневой директории).
- `secure_chroot_dir=/var/run/vsftpd/empty` — пустая не-доступная для записи директория, используемая vsftpd для безопасности chroot. Должна существовать и быть пустой.
- `hide_ids=YES` — скрывает реальные UID/GID в листингах (все файлы показываются от владельца `ftp`).
- `nopriv_user=nobody` — пользователь, от имени которого vsftpd работает с непривилегированными операциями.

**Передача данных:**
- `write_enable=YES` — разрешает команды записи (STOR, DELE, RNFR, RNTO, MKD, RMD).
- `file_open_mode=0666` — маска прав для создаваемых файлов (в сочетании с `local_umask`).
- `local_umask=022` — umask для локальных пользователей.
- `ascii_upload_enable=YES/NO` — разрешает ASCII-загрузку (может быть эксплойтом через CRLF инъекции).
- `ascii_download_enable=YES/NO` — разрешает ASCII-выгрузку.
- `use_sendfile=YES` — использует системный вызов sendfile для эффективности (может конфликтовать с SELinux на некоторых версиях).

**Ограничения и защита от DoS:**
- `max_clients=N` — общее число одновременных подключений.
- `max_per_ip=N` — лимит подключений с одного IP-адреса.
- `local_max_rate=байт/сек` — ограничение скорости для авторизованных пользователей.
- `anon_max_rate=байт/сек` — ограничение скорости для анонимных пользователей.
- `connect_timeout=секунды` — таймаут установки соединения.
- `idle_session_timeout=секунды` — таймаут бездействия управляющего соединения.
- `data_connection_timeout=секунды` — таймаут бездействия соединения данных.
- `cmds_allowed=STOR,RETR,...` — разрешенные команды (whitelist).
- `cmds_denied=...` — запрещенные команды (blacklist).

**Логирование:**
- `xferlog_enable=YES` — включает логирование передач в стандартный xferlog-формат.
- `vsftpd_log_file=/var/log/vsftpd.log` — файл логов vsftpd.
- `log_ftp_protocol=YES/NO` — логирует все FTP-команды и ответы (для отладки).
- `debug_ssl=YES` — включает детальную отладочную информацию по TLS.

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

Создадим самоподписанный сертификат сроком на один год. Для production используйте CA-подписанные сертификаты (Let's Encrypt, corporate CA).

```bash
sudo openssl req -new -x509 -days 365 -nodes \
  -out /etc/ssl/certs/vsftpd.pem \
  -keyout /etc/ssl/private/vsftpd.key \
  -subj "/C=RU/ST=Moscow/L=Moscow/O=DevOps/OU=IT/CN=vsftpd.local"
# → Generated /etc/ssl/certs/vsftpd.pem and /etc/ssl/private/vsftpd.key

# Права на ключ:
sudo chmod 600 /etc/ssl/private/vsftpd.key
sudo chown root:root /etc/ssl/certs/vsftpd.pem /etc/ssl/private/vsftpd.key
```

#### Шаг 2.1. Интеграция с Let's Encrypt (certbot)

Для production-сред рекомендуется использовать certbot:

```bash
sudo apt install certbot -y

# Standalone режим (требует остановки vsftpd на время валидации):
sudo systemctl stop vsftpd
sudo certbot certonly --standalone -d ftp.example.com
# → Congratulations! Your certificate and chain have been saved at:
#   /etc/letsencrypt/live/ftp.example.com/fullchain.pem
#   /etc/letsencrypt/live/ftp.example.com/privkey.pem

# Hook для автоматического перезапуска vsftpd после обновления:
cat <<'EOF' | sudo tee /etc/letsencrypt/renewal-hooks/deploy/vsftpd-reload.sh
#!/bin/bash
systemctl reload vsftpd
EOF
sudo chmod +x /etc/letsencrypt/renewal-hooks/deploy/vsftpd-reload.sh

# Или используйте webroot, если nginx/apache слушает порт 80:
sudo certbot certonly --webroot -w /var/www/html -d ftp.example.com
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
listen_port=21
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
secure_chroot_dir=/var/run/vsftpd/empty
hide_ids=YES
nopriv_user=nobody

# Пассивный режим (обязателен для работы через NAT)
pasv_enable=YES
pasv_min_port=40000
pasv_max_port=40100
# Если сервер за NAT, укажите внешний IP:
# pasv_address=EXTERNAL_IP

# Настройки SSL/TLS (только современные протоколы)
ssl_enable=YES
allow_anon_ssl=NO
force_local_data_ssl=YES
force_local_logins_ssl=YES
ssl_tlsv1_2=YES
ssl_tlsv1_3=YES
# Отключите, если клиент выдает ошибку "GnuTLS error -110"
require_ssl_reuse=NO
rsa_cert_file=/etc/ssl/certs/vsftpd.pem
rsa_private_key_file=/etc/ssl/private/vsftpd.key

# Таймауты
idle_session_timeout=300
data_connection_timeout=120
connect_timeout=60

# Логирование
xferlog_enable=YES
vsftpd_log_file=/var/log/vsftpd.log
log_ftp_protocol=NO
```

#### Шаг 4.1. Secure chroot directory

vsftpd требует пустую директорию для безопасной работы chroot. Создайте её:
```bash
sudo mkdir -p /var/run/vsftpd/empty
sudo chown root:root /var/run/vsftpd/empty
sudo chmod 755 /var/run/vsftpd/empty
```

#### Шаг 4.2. Ограничение пользователей через userlist

Чтобы запретить системным пользователям доступ к FTP:
```bash
echo "root" | sudo tee -a /etc/vsftpd/user_list
echo "daemon" | sudo tee -a /etc/vsftpd/user_list

# В vsftpd.conf:
# userlist_enable=YES
# userlist_deny=YES
```

#### Шаг 4.3. Настройка banner

```bash
echo "Authorized access only. All activity is logged." | sudo tee /etc/vsftpd/banner.txt

# В vsftpd.conf:
# ftpd_banner=/etc/vsftpd/banner.txt
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

**Пример с lftp (вариант 1 — самоподписанный сертификат):**
```bash
lftp -u ftpuser1,securepassword1 -e "set ftp:ssl-force true; set ssl:verify-certificate no; ls; quit" localhost
# → drwxr-xr-x    2 1001     1001         4096 Jul 24 12:00 .
```

**Пример с lftp (вариант 2 — CA-подписанный сертификат):**
```bash
lftp -u ftpuser1,securepassword1 -e "set ftp:ssl-force true; ls; quit" ftp.example.com
# → соединение с проверкой сертификата
```

**Проверка TLS через openssl:**
```bash
openssl s_client -connect localhost:21 -starttls ftp
# → Проверьте строку "SSL-Session:" и сертификат
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
3.  **SELinux troubleshooting:** Для диагностики отказов используйте `audit2why` и `audit2allow`:
    ```bash
    sudo ausearch -m avc -ts recent | audit2why
    sudo ausearch -m avc -ts recent | audit2allow -M myvsftpd
    sudo semodule -i myvsftpd.pp
    ```

### Устранение неполадок

- **Ошибка 500 OOPS (chroot):** Если `allow_writeable_chroot=YES` не помогает, проверьте права на корневую директорию пользователя — она не должна быть доступна на запись, если эта опция выключена. Также убедитесь, что `secure_chroot_dir` существует и пуста.
- **Ошибка "GnuTLS error -110":** Часто связана с несовместимостью SSL Reuse. Установите `require_ssl_reuse=NO`.
- **Ошибка "Could not bind listening IPv4 socket":** Порт 21 уже занят другим процессом (возможно, предыдущий экземпляр vsftpd). Остановите его: `sudo systemctl stop vsftpd` и убедитесь, что порт свободен: `ss -tlnp | grep :21`.
- **Пассивный режим не работает за NAT:** Убедитесь, что диапазон портов открыт на фаирволе и указан `pasv_address` с внешним IP. Проверьте: `sudo iptables -L -n` или `sudo ss -tlnp | grep vsftpd`.
- **Логи:** При возникновении проблем всегда проверяйте `/var/log/vsftpd.log` и системный журнал `journalctl -u vsftpd`.

### Производительность и лимиты

Для защиты от злоупотреблений и оптимизации ресурсов добавьте в `vsftpd.conf`:
- `max_clients=50` — общее число одновременных подключений.
- `max_per_ip=5` — лимит подключений с одного IP-адреса.
- `local_max_rate=500000` — ограничение скорости передачи (байт/сек) для авторизованных пользователей.
- `connect_timeout=60` — таймаут ожидания ответа от клиента.
- `idle_session_timeout=300` — таймаут неактивного управляющего соединения.
- `data_connection_timeout=120` — таймаут неактивного соединения данных.

### DoS-защита

- Используйте `max_clients` и `max_per_ip` для ограничения числа соединений.
- Настройте файрвол для rate-limiting на порту 21 (например, `iptables -A INPUT -p tcp --dport 21 -m limit --limit 30/minute`).
- Используйте `fail2ban` для блокировки IP при подборе паролей (мониторинг `/var/log/vsftpd.log`).

### ASCII-режим и безопасность

ASCII-режим (команды `TYPE A`) преобразует переносы строк (CRLF ↔ LF). Это может привести к эксплойтам, если клиент отправит специально crafted данные. Рекомендации:
- Отключите `ascii_upload_enable=NO` и `ascii_download_enable=NO`, если клиенты не требуют ASCII.
- Никогда не используйте ASCII-режим для бинарных файлов (программы, архивы, образы).

### Мониторинг и логирование

- **Systemd:** Для просмотра последних событий используйте `sudo journalctl -u vsftpd -f`.
- **Текущие сессии:** Команда `ss -tnp | grep vsftpd` покажет активные TCP-соединения с PID.
- **Процессы:** Команда `ps aux | grep vsftpd` покажет процессы для каждого активного пользователя.
- **Логи xferlog:** При `xferlog_enable=YES` логи пишутся в `/var/log/xferlog` (совместимый с wu-ftpd формат). Используйте `log_ftp_protocol=YES` для отладки FTP-команд.
- **Внешний мониторинг:** Можно использовать `prometheus-vsftpd-exporter` для сбора метрик о количестве пользователей и объеме трафика.

### Автоматизация (Ansible пример)

```yaml
- name: Install vsftpd
  apt:
    name: vsftpd,db-util
    state: present

- name: Generate self-signed cert
  openssl_certificate:
    path: /etc/ssl/certs/vsftpd.pem
    privatekey_path: /etc/ssl/private/vsftpd.key
    provider: selfsigned
    common_name: "{{ inventory_hostname }}"

- name: Create virtual user DB
  copy:
    content: |
      ftpuser1
      {{ ftpuser1_password }}
    dest: /etc/vsftpd/virtual_users.txt

- name: Load Berkeley DB
  command: db_load -T -t hash -f /etc/vsftpd/virtual_users.txt /etc/vsftpd/virtual_users.db

- name: Template vsftpd.conf
  template:
    src: vsftpd.conf.j2
    dest: /etc/vsftpd.conf
  notify: restart vsftpd

- name: Ensure vsftpd running
  systemd:
    name: vsftpd
    state: started
    enabled: yes
```

### Безопасность

- **SFTP vs FTPS:** Рекомендуется использовать **SFTP** (SSH File Transfer Protocol), так как он требует только один порт (22) и изначально более защищен. FTPS используется при необходимости строгой совместимости с FTP-инфраструктурой. Настройка SFTP с chroot описана в [SSH: Access Control](../../Security/ssh/server/ssh_access_control.md).
- **Защита от перебора (Brute-force):** Рекомендуется настроить `fail2ban` для мониторинга `/var/log/vsftpd.log`.
- **Проверка сертификатов:** В production всегда используйте CA-подписанные сертификаты и включайте проверку на стороне клиента (`ssl:verify-certificate yes` в lftp). Никогда не используйте `set ssl:verify-certificate no` в production.

### Бэкап и восстановление

```bash
# Бэкап БД виртуальных пользователей:
sudo cp /etc/vsftpd/virtual_users.db /backup/vsftpd/virtual_users.db.$(date +%Y%m%d)
sudo cp /etc/vsftpd/virtual_users.txt /backup/vsftpd/virtual_users.txt.$(date +%Y%m%d)

# Восстановление:
sudo cp /backup/vsftpd/virtual_users.txt /etc/vsftpd/
sudo db_load -T -t hash -f /etc/vsftpd/virtual_users.txt /etc/vsftpd/virtual_users.db
sudo chmod 600 /etc/vsftpd/virtual_users.db
sudo systemctl restart vsftpd
```

### Связанные темы

- **[Прикладной уровень (L7): FTP](../../../Networking/OSI_TCP_IP_Model/application_layer.md#таблица-основных-протоколов)** — теоретические основы протокола.
- **[Ограничение сервисов (chroot)](../../../Linux/Core/chroot.md#5-изоляция-сервисов-ftp-dns-web)** — механизмы изоляции в Linux.
- **[TCP Wrappers](../../../Linux/Networking/tcp_wrappers.md)** — фильтрация доступа к vsftpd по IP.
- **[SELinux: основы](../../../Linux/Security/Mechanisms/SELinux.md)** — управление политиками доступа.
- **[FTP-серверы: Сравнение](./ftp_server_comparison.md)** — сравнение vsftpd, ProFTPD и Pure-FTPd.
- **[FTP: Интеграция с LDAP](./ftp_ldap_integration.md)** — настройка LDAP/AD аутентификации.
- **[FTP в Docker](./ftp_docker.md)** — контейнеризация FTP-сервера.
- **[FTP: Высокая доступность](./ftp_high_availability.md)** — HA с Keepalived и HAProxy.
- **[FTP: Мониторинг](./ftp_monitoring.md)** — Prometheus, Loki, Grafana.
- **[WebDAV: Обзор](../webdav/webdav_overview.md)** — альтернатива FTP для веб-приложений.
