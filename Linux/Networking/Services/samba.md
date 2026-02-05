# Samba: общий доступ к файлам для Windows-сетей

## Определения

**Samba** — программный комплекс, реализующий протокол **SMB/CIFS** (Server Message Block / Common Internet File System). Позволяет Unix-подобным системам (включая Linux) предоставлять общий доступ к файлам и принтерам для клиентов Windows, а также функционировать в качестве члена домена Active Directory.

**NetBIOS** — протокол, используемый Samba для обнаружения и разрешения имен в сетях Windows.

## Базовые концепции

Samba функционирует посредством двух основных демонов:

*   **`smbd`**: Демон, отвечающий за файловые ресурсы, аутентификацию и авторизацию.
*   **`nmbd`**: Демон, отвечающий за разрешение имён NetBIOS.

### Безопасность SMB/Samba

Протокол SMB является частым вектором сетевых атак.

*   **Уязвимости протокола:** Устаревшие версии (SMBv1) содержат критические уязвимости (например, использованные в атаке WannaCry).
*   **Неправильная конфигурация:** Публично доступные ресурсы без аутентификации могут привести к утечке данных.

**Рекомендации по безопасности:**

*   Отключать SMBv1, использовать версии SMBv3+ с поддержкой шифрования.
*   Тщательно настраивать права доступа.
*   Ограничивать доступ с помощью файрвола. См. [[Настройка файрвола в Linux: iptables и nftables|../Settings/linux_firewall_management.md]].

## Практические сценарии

### 1. Установка Samba

*   **Debian/Ubuntu:**
    ```bash
    sudo apt-get update
    sudo apt-get install -y samba
    ```
*   **RHEL/CentOS:**
    ```bash
    sudo yum install -y samba samba-common samba-client
    ```

### 2. Настройка анонимного (гостевого) файлового ресурса

Пример создания публичной папки без пароля.

#### Шаг 1: Создание директории

```bash
sudo mkdir -p /srv/samba/public
# Установка владельца nobody:nogroup для гостевого доступа
sudo chown -R nobody:nogroup /srv/samba/public/
sudo chmod -R 0775 /srv/samba/public/
```

#### Шаг 2: Настройка SELinux и Firewall (для CentOS/RHEL)

**SELinux** по умолчанию блокирует доступ Samba к директориям.
```bash
# Установка правильного контекста для директории
sudo chcon -t samba_share_t /srv/samba/public/
```
Подробнее об управлении SELinux см. [[SELinux (Security-Enhanced Linux): Управление и Практика|../../Security/Mechanisms/SELinux.md]].

**Firewall:**
```bash
# Для firewalld
sudo firewall-cmd --permanent --add-service=samba
sudo firewall-cmd --reload
```

#### Шаг 3: Конфигурация Samba (`/etc/samba/smb.conf`)

Пример содержимого `/etc/samba/smb.conf`:

```ini
[global]
   workgroup = WORKGROUP
   server string = Samba Server
   netbios name = smb-server
   security = user
   map to guest = bad user # Сопоставление неудачной попытки входа с гостевой учетной записью
   load printers = no
   printing = bsd
   printcap name = /dev/null
   disable spoolss = yes

[Public]
   comment = Public Share
   path = /srv/samba/public
   browsable = yes
   writable = yes
   guest ok = yes
   read only = no
```

#### Шаг 4: Проверка и запуск

```bash
testparm # Проверка конфигурации на ошибки

sudo systemctl enable --now smb # Запуск и добавление smb в автозагрузку
sudo systemctl enable --now nmb # Запуск и добавление nmb в автозагрузку
```

### 3. Настройка ресурса с доступом по паролю

#### Шаг 1: Создание пользователя

Создание системного пользователя Linux и установка для него пароля Samba.

```bash
# Создание пользователя без домашней директории и без возможности входа
sudo useradd --no-create-home --shell /usr/sbin/nologin smbuser

# Установка пароля Samba для пользователя (хранится отдельно)
sudo smbpasswd -a smbuser
```

#### Шаг 2: Создание и настройка ресурса

```bash
sudo mkdir -p /srv/samba/private
sudo chown -R smbuser:smbuser /srv/samba/private/
sudo chmod -R 0770 /srv/samba/private/
```

Добавление конфигурации в `/etc/samba/smb.conf`:
```ini
[Private]
   comment = Private Share
   path = /srv/samba/private
   valid users = smbuser # Список пользователей, которым разрешен доступ
   guest ok = no
   writable = yes
   browsable = yes
```
После изменения конфигурации перезапустите Samba: `sudo systemctl restart smb nmb`.

## Дополнительная информация

### Пользователи Samba

Samba использует собственную базу паролей (`/var/lib/samba/private/smbpasswd`). Пароли системных пользователей Linux не используются напрямую. Утилита `smbpasswd` управляет этой базой:

*   `smbpasswd -a [user]`: Добавление пользователя и установка пароля.
*   `smbpasswd -x [user]`: Удаление пользователя из базы Samba.
*   `smbpasswd -e [user]`: Активация пользователя.
*   `smbpasswd -d [user]`: Деактивация пользователя.

### Уровни безопасности (`security`)

*   **`security = user`**: Стандартный режим. Клиент предоставляет имя пользователя и пароль.
*   **`security = ads`**: Интеграция Samba в домен Active Directory. Samba выступает членом домена, аутентификация через Kerberos. Требует сложной настройки.

### Клиентский доступ из Linux

Для доступа к ресурсам Samba с другого Linux-компьютера используется пакет `cifs-utils`.

```bash
# Установка cifs-utils
sudo apt-get install -y cifs-utils

# Временное монтирование публичного ресурса
sudo mount -t cifs //smb-server/Public /mnt/samba -o guest

# Монтирование приватного ресурса с паролем
sudo mount -t cifs //smb-server/Private /mnt/private -o username=smbuser,password=...
```