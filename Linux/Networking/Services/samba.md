# Samba: общий доступ к файлам для Windows-сетей

## Определения

*   **Samba** — это программный комплекс, который реализует протокол **SMB/CIFS** (Server Message Block / Common Internet File System). Он позволяет Unix-подобным системам (включая Linux) предоставлять общий доступ к файлам и принтерам для клиентов Windows, а также выступать членом домена Active Directory.
*   **NetBIOS** — протокол, который Samba использует для обнаружения и разрешения имен в сетях Windows (например, чтобы ваш сервер был виден в "Сетевом окружении").

## Базовые концепции

Samba состоит из двух основных демонов:
-   **`smbd`**: Основной демон, отвечающий за файловые ресурсы, аутентификацию и авторизацию.
-   **`nmbd`**: Отвечает за разрешение имён NetBIOS.

### Безопасность SMB/Samba

Протокол SMB является частым вектором атак.
-   **Уязвимости протокола:** Старые версии (SMBv1) имеют критические уязвимости (например, использованные в атаке WannaCry).
-   **Неправильная конфигурация:** Публично доступные ресурсы без аутентификации могут привести к утечке данных.

**Рекомендации по безопасности:**
-   Отключать SMBv1 и использовать только современные версии (SMBv3+), поддерживающие шифрование.
-   Тщательно настраивать права доступа.
-   Ограничивать доступ с помощью файрвола. См. [[Настройка файрвола в Linux: iptables и nftables|../Settings/linux_firewall_management.md]].

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

Этот пример показывает, как создать публичную папку без пароля.

#### Шаг 1: Создание директории
```bash
sudo mkdir -p /srv/samba/public
# Устанавливаем владельца nobody:nogroup, от имени которого будет работать гостевой доступ
sudo chown -R nobody:nogroup /srv/samba/public/
sudo chmod -R 0775 /srv/samba/public/
```

#### Шаг 2: Настройка SELinux и Firewall (для CentOS/RHEL)
**SELinux** по умолчанию блокирует доступ Samba к директориям.
```bash
# Устанавливаем правильный контекст для директории
sudo chcon -t samba_share_t /srv/samba/public/
```
Подробнее об управлении SELinux см. [[Управление SELinux|../../Security/selinux_management.md]].

**Firewall:**
```bash
# Для firewalld
sudo firewall-cmd --permanent --add-service=samba
sudo firewall-cmd --reload
```

#### Шаг 3: Конфигурация Samba (`/etc/samba/smb.conf`)

```ini
# /etc/samba/smb.conf

[global]
   workgroup = WORKGROUP
   server string = Samba Server
   netbios name = smb-server
   security = user
   # Сопоставляет неудачную попытку входа с гостевой учетной записью
   map to guest = bad user
   # Отключаем печать
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
# Проверить конфигурацию на ошибки
testparm

# Запустить и добавить службы в автозагрузку
sudo systemctl enable --now smb
sudo systemctl enable --now nmb
```

### 3. Настройка ресурса с доступом по паролю

#### Шаг 1: Создание пользователя

Сначала создается системный пользователь Linux, а затем для него устанавливается пароль Samba.

```bash
# Создаем пользователя без домашней директории и без возможности входа в систему
sudo useradd --no-create-home --shell /usr/sbin/nologin smbuser

# Устанавливаем для него пароль Samba (будет храниться отдельно)
sudo smbpasswd -a smbuser
```

#### Шаг 2: Создание и настройка ресурса

```bash
sudo mkdir -p /srv/samba/private
sudo chown -R smbuser:smbuser /srv/samba/private/
sudo chmod -R 0770 /srv/samba/private/
```

Добавляем в `/etc/samba/smb.conf`:
```ini
[Private]
   comment = Private Share
   path = /srv/samba/private
   # Список пользователей, которым разрешен доступ
   valid users = smbuser
   guest ok = no
   writable = yes
   browsable = yes
```
После этого перезапустите Samba: `sudo systemctl restart smb nmb`.

## Дополнительная информация

### Пользователи Samba

Samba ведет собственную базу паролей (`/var/lib/samba/private/smbpasswd`). Пароли системных пользователей Linux не используются напрямую. Утилита `smbpasswd` управляет этой базой:
-   `smbpasswd -a [user]`: Добавить пользователя и установить ему пароль.
-   `smbpasswd -x [user]`: Удалить пользователя из базы Samba.
-   `smbpasswd -e [user]`: Активировать пользователя.
-   `smbpasswd -d [user]`: Деактивировать пользователя.

### Уровни безопасности (`security`)

-   **`security = user`**: Стандартный и наиболее распространенный режим. Клиент должен предоставить имя пользователя и пароль.
-   **`security = ads`**: Используется для интеграции Samba в домен Active Directory. Samba выступает в роли члена домена, а аутентификация происходит через Kerberos. Требует более сложной настройки.

### Клиентский доступ из Linux

Для доступа к ресурсам Samba с другого Linux-компьютера используется пакет `cifs-utils`.

```bash
# Установка
sudo apt-get install -y cifs-utils

# Временное монтирование
sudo mount -t cifs //smb-server/Public /mnt/samba -o guest

# Монтирование с паролем
sudo mount -t cifs //smb-server/Private /mnt/private -o username=smbuser,password=...
```
