# vsftpd: Настройка FTPS и виртуальных пользователей

## Определения

**vsftpd (Very Secure FTP Daemon)** — быстрый и безопасный FTP-сервер для Unix-подобных систем.

**FTPS (FTP over SSL/TLS)** — расширение протокола FTP, использующее шифрование TLS для защиты передаваемых данных и учетных записей.

**Виртуальные пользователи** — метод управления доступом, при котором пользователи не имеют реальных учетных записей в операционной системе (не присутствуют в `/etc/passwd`). Их данные (логин/пароль) хранятся во внешнем источнике — базе данных или текстовом файле. Это значительно повышает безопасность, так как виртуальные пользователи не могут получить доступ к shell или другим системным ресурсам.

---

## Практические сценарии

### Настройка FTPS с виртуальными пользователями (Ubuntu/Debian)

Сценарий описывает быструю настройку защищенного FTP-сервера с изоляцией пользователей в их домашних директориях.

#### Шаг 1. Установка компонентов

```bash
sudo apt update
sudo apt install vsftpd db-util -y
```

`db-util` используется для создания базы данных пользователей из текстового файла.

#### Шаг 2. Конфигурация сервера

Отредактируйте основной конфигурационный файл `/etc/vsftpd.conf`. Перед внесением изменений рекомендуется сделать резервную копию:

```bash
sudo cp /etc/vsftpd.conf /etc/vsftpd.conf.bak
sudo nano /etc/vsftpd.conf
```

**Пример безопасной конфигурации:**

```ini
# Режим работы
listen=YES
anonymous_enable=NO
local_enable=YES

# Поддержка виртуальных пользователей
guest_enable=YES
guest_username=vsftpd
virtual_use_local_privs=YES
pam_service_name=vsftpd.virtual

# Директории пользователей
# %USER% заменяется на имя пользователя при входе
user_sub_token=$USER
local_root=/home/vsftpd/$USER

# Изоляция (chroot)
chroot_local_user=YES
allow_writeable_chroot=YES

# Логирование
xferlog_enable=YES
log_ftp_protocol=YES
xferlog_file=/var/log/vsftpd.log
vsftpd_log_file=/var/log/vsftpd.log
xferlog_std_format=NO

# Настройка портов
connect_from_port_20=YES
# Диапазон портов для пассивного режима (необходим для работы через NAT/Firewall)
pasv_enable=YES
pasv_min_port=35100
pasv_max_port=35109

# Права на файлы
local_umask=077

# Настройки SSL/TLS (FTPS)
ssl_enable=YES
allow_anon_ssl=NO
force_local_data_ssl=YES
force_local_logins_ssl=YES
require_ssl_reuse=NO
ssl_tlsv12=YES
rsa_cert_file=/etc/ssl/certs/vsftpd.pem
rsa_private_key_file=/etc/ssl/private/vsftpd.key
```

#### Шаг 3. Подготовка SSL-сертификата

Для тестирования можно сгенерировать самоподписанный сертификат:

```bash
sudo openssl req -new -x509 -days 365 -nodes \
  -out /etc/ssl/certs/vsftpd.pem \
  -keyout /etc/ssl/private/vsftpd.key \
  -subj "/C=RU/ST=Moscow/L=Moscow/O=DevOps/OU=IT/CN=vsftpd.server"
```

#### Шаг 4. Настройка виртуальных пользователей

1.  **Создание базы данных:**
    Создайте файл `/etc/vsftpd/virtual_users.txt` с парами логин/пароль (на отдельных строках):
    ```text
    user1
    password123
    ```
    Преобразуйте его в бинарную базу данных и установите права:
    ```bash
    sudo mkdir -p /etc/vsftpd
    sudo db_load -T -t hash -f /etc/vsftpd/virtual_users.txt /etc/vsftpd/virtual_users.db
    sudo chmod 600 /etc/vsftpd/virtual_users.db
    ```

2.  **Настройка PAM:**
    Создайте файл `/etc/pam.d/vsftpd.virtual`, чтобы vsftpd знал, как проверять пароли:
    ```bash
    auth required pam_userdb.so db=/etc/vsftpd/virtual_users
    account required pam_userdb.so db=/etc/vsftpd/virtual_users
    ```

3.  **Системный пользователь и директории:**
    Создайте непривилегированного пользователя, от имени которого будут работать виртуальные аккаунты, и подготовьте их каталоги:
    ```bash
    sudo useradd -d /home/vsftpd -s /usr/sbin/nologin -M vsftpd
    sudo mkdir -p /home/vsftpd/user1
    sudo chown -R vsftpd:vsftpd /home/vsftpd/user1
    ```

#### Шаг 5. Запуск и проверка

```bash
sudo systemctl restart vsftpd
```

Для подключения используйте клиенты с поддержкой FTPS (например, FileZilla или WinSCP). В настройках выберите протокол **FTP** и шифрование **Require explicit FTP over TLS**.

---

## Дополнительная информация

### Безопасность

- **Использование SFTP:** Протокол SFTP (SSH File Transfer Protocol) технически не связан с FTP и работает через SSH (порт 22). Он считается более современным и простым в настройке, так как не требует открытия динамического диапазона портов.
- **Firewall:** Если сервер находится за NAT или защищен `ufw/iptables`, необходимо разрешить порты 21 (управляющий) и диапазон `pasv_min_port` - `pasv_max_port`.

### Связанные темы

- **[Прикладной уровень (L7): FTP](../../Networking/OSI_TCP_IP_Model/application_layer.md#основные-протоколы-прикладного-уровня)** — теоретические основы протокола.
- **[Ограничение сервисов (chroot)](../../Linux/Core/chroot.md#3-области-применения)** — механизмы изоляции в Linux.
- **[TCP Wrappers](../../Linux/Networking/tcp_wrappers.md)** — фильтрация доступа к vsftpd по IP.
