# Samba: общий доступ к файлам для Windows-сетей

## Определения

**Samba** — программный комплекс, реализующий протокол **SMB/CIFS** (Server Message Block / Common Internet File System). Позволяет Unix-подобным системам (включая Linux) предоставлять общий доступ к файлам и принтерам для клиентов Windows, а также функционировать в качестве члена домена Active Directory.

**NetBIOS** — протокол, используемый Samba для обнаружения и разрешения имен в сетях Windows.

## Базовые концепции

* **`smbd`**: Демон, отвечающий за файловые ресурсы, аутентификацию и авторизацию.
* **`nmbd`**: Демон, отвечающий за разрешение имён NetBIOS.

### Безопасность протокола SMB

* **Уязвимости протокола:** Устаревшие версии (SMBv1) содержат критические уязвимости (например, использованные в атаке WannaCry).
* **Неправильная конфигурация:** Публично доступные ресурсы без аутентификации могут привести к утечке данных.

**Рекомендации по безопасности:**

* Отключать SMBv1, использовать версии SMBv3+ с поддержкой шифрования.
* Тщательно настраивать права доступа.
* Ограничивать доступ с помощью файрвола. См. [Настройка файрвола в Linux: iptables и nftables](../Settings/linux_firewall_management.md).

## Практические сценарии

### 1. Установка Samba

* **Debian/Ubuntu:**

    ```bash
    sudo apt-get update
    sudo apt-get install -y samba
    ```

* **RHEL/CentOS:**

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
# Установка правильного контекста для директории (временное решение)
sudo chcon -t samba_share_t /srv/samba/public/

# Постоянное решение - использование semanage
sudo semanage fcontext -a -t samba_share_t '/srv/samba/public(/.*)?'
sudo restorecon -Rv /srv/samba/public/

# Разрешение доступа к домашним директориям (если нужно)
sudo setsebool -P samba_enable_home_dirs on
```

Подробнее об управлении SELinux см. [SELinux (Security-Enhanced Linux): Управление и Практика](../../Security/Mechanisms/SELinux.md).

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

# Установка пароля Samba для пользователя (хранится отдельно от системного)
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

### 4. Структура конфигурации `/etc/samba/smb.conf`

Файл состоит из **секций**, заключённых в квадратные скобки:

* **`[global]`**: Параметры, относящиеся к самой Samba, и значения по умолчанию для всех остальных секций.
* **`[homes]`**: Особая секция для автоматического предоставления доступа к домашним директориям пользователей. При подключении пользователя секция автоматически применяется для его имени.
    - При подключении пользователя `user1` создаётся виртуальная секция `[user1]` с параметрами из `[homes]`.
    - Переменная `%s` подставляется имя пользователя.
    - По умолчанию `browseable = no`, но для аутентифицированного пользователя становится `yes` — он видит только свою домашнюю директорию.
* **`[printers]`**: Секция для настройки доступа к принтерам.
* **Именованные секции**: Определяют конкретные общие ресурсы (шары).

#### Основные параметры секций

| Параметр | Описание |
| :--- | :--- |
| `path` | Путь к директории, которую предоставляем в общий доступ. |
| `browseable` | Показывать ли ресурс в списке доступных (аналог `showmount` в NFS). |
| `writable` / `read only` | Разрешена ли запись. |
| `valid users` | Список пользователей и групп, которым разрешён доступ. Группы указываются с префиксом `@` (например, `@developers`). |
| `read list` | Список пользователей с доступом только на чтение. |
| `write list` | Список пользователей с доступом на запись (важно, если `read only = yes`). |
| `inherit ACLs` | Наследование ACL родительской директории для новых файлов (аналог `setfacl -d`). |
| `comment` | Описание ресурса, видимое клиентам. |

#### Переменные в конфигурации

В секциях можно использовать переменные:

* `%s` — имя секции (или имя пользователя для `[homes]`).
* `%u` — имя пользователя.
* `%w` — имя рабочей группы.
* `%d` — ID пользователя (UID).

### 5. Монтирование SMB-ресурсов в Linux

Для монтирования SMB-ресурсов используется пакет `cifs-utils`.

#### Опции монтирования

| Опция | Описание |
| :--- | :--- |
| `username` | Имя пользователя на SMB-сервере. |
| `password` | Пароль пользователя (небезопасно указывать в fstab). |
| `credentials` | Путь к файлу с логином и паролем. |
| `uid` | Локальный UID, от имени которого будут отображаться файлы. |
| `gid` | Локальный GID, от имени которого будут отображаться файлы. |
| `file_mode` | Прада доступа к файлам (например, `0755`). |
| `dir_mode` | Права доступа к директориям (например, `0755`). |
| `nounix` | Отключить поддержку UNIX-атрибутов (по умолчанию в современных версиях). |

#### Безопасное монтирование с использованием credentials

Создайте файл с учётными данными:

```bash
# /root/.smbcredentials
username=smbuser
password=secretpassword
```

Защитите файл:

```bash
sudo chmod 600 /root/.smbcredentials
```

Запись в `/etc/fstab`:

```ini
//smb-server/private /mnt/samba cifs credentials=/root/.smbcredentials,uid=1000,gid=1000,file_mode=0755,dir_mode=0755,nofail 0 0
```

### 6. Различия в правах доступа: NFS vs SMB

Принципы работы прав доступа в SMB отличаются от NFS:

1. **Двухуровневая модель**:
   - **Клиентская сторона**: Сначала проверяются локальные права на стороне клиента (основанные на `uid`/`gid` в опциях монтирования).
   - **Серверная сторона**: Затем проверяются права пользователя, от имени которого выполнено подключение (параметр `username` или `credentials`).

2. **UNIX-права vs Windows-права**:
   - В NFS используются UNIX-овые UID/GID.
   - В SMB права более близки к Windows-стилю. Стандартные команды `chmod`, `chown` на клиенте **не работают** для изменения прав на удалённом сервере.

3. **Опция `nounix`**:
   - Современные версии SMB (3.x) по умолчанию не поддерживают полную передачу UNIX-атрибутов между клиентом и сервером. Опция `nounix` явно отключает эту поддержку.

## Дополнительная информация

### Пользователи Samba

Samba использует собственную базу паролей (`/var/lib/samba/private/smbpasswd`). Пароли системных пользователей Linux не используются напрямую. Утилита `smbpasswd` управляет этой базой:

* `smbpasswd -a [user]`: Добавление пользователя и установка пароля.
* `smbpasswd -x [user]`: Удаление пользователя из базы Samba.
* `smbpasswd -e [user]`: Активация пользователя.
* `smbpasswd -d [user]`: Деактивация пользователя.

### Уровни безопасности (`security`)

* **`security = user`**: Стандартный режим. Клиент предоставляет имя пользователя и пароль.
* **`security = ads`**: Интеграция Samba в домен Active Directory. Samba выступает членом домена, аутентификация через Kerberos. Требует сложной настройки.

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

### Тестирование с помощью `smbclient`

Утилита `smbclient` позволяет подключиться к SMB-серверу в интерактивном режиме, напоминающем FTP-клиент.

```bash
# Просмотр доступных шар без аутентификации
smbclient -L //smb-server -U%

# Подключение от имени пользователя
smbclient //smb-server/Private -U smbuser
```

### Сравнение с NFS

| Характеристика | NFS | SMB |
| :--- | :--- | :--- |
| Основное применение | UNIX/Linux среды | Windows среды, кросс-платформенный обмен |
| Права доступа | UNIX UID/GID | Windows ACL + UNIX-стиль (с ограничениями) |
| Аутентификация | Обычно на основе IP или Kerberos | Пользователи Samba, домен AD |
| Протокол | RPC, порт 2049 (NFSv4) | TCP 445 (SMB 3.x), NetBIOS |

Подробнее о NFS см. [NFS (Network File System)](nfs.md).
