# Samba: Настройка сервера

## Установка

```bash
# Debian/Ubuntu
sudo apt-get update
sudo apt-get install -y samba

# RHEL/CentOS
sudo yum install -y samba samba-common samba-client
```

## Настройка гостевого (анонимного) доступа

### Шаг 1: Создание директории

```bash
sudo mkdir -p /srv/samba/public
sudo chown -R nobody:nogroup /srv/samba/public/
sudo chmod -R 0775 /srv/samba/public/
```

### Шаг 2: Конфигурация (`/etc/samba/smb.conf`)

```ini
[global]
   workgroup = WORKGROUP
   server string = Samba Server
   netbios name = smb-server
   security = user
   map to guest = bad user
   server min protocol = SMB3
   load printers = no
   disable spoolss = yes

[Public]
   comment = Public Share
   path = /srv/samba/public
   browsable = yes
   writable = yes
   guest ok = yes
   read only = no
```

### Шаг 3: Проверка и запуск

```bash
testparm  # Проверка конфигурации

sudo systemctl enable --now smb
sudo systemctl enable --now nmb
```

## Настройка доступа по паролю

### Шаг 1: Создание пользователя

```bash
# Создание системного пользователя
sudo useradd --no-create-home --shell /usr/sbin/nologin smbuser

# Установка пароля Samba (отдельная база паролей)
sudo smbpasswd -a smbuser
```

### Шаг 2: Создание ресурса

```bash
sudo mkdir -p /srv/samba/private
sudo chown -R smbuser:smbuser /srv/samba/private/
sudo chmod -R 0770 /srv/samba/private/
```

### Шаг 3: Добавление шары в конфигурацию

```ini
[Private]
   comment = Private Share
   path = /srv/samba/private
   valid users = smbuser
   guest ok = no
   writable = yes
   browsable = yes
```

Перезапустите Samba: `sudo systemctl restart smb nmb`.

## Структура `/etc/samba/smb.conf`

### Секции

| Секция | Описание |
| :--- | :--- |
| `[global]` | Параметры Samba, значения по умолчанию |
| `[homes]` | Автоматический доступ к домашним директориям |
| `[printers]` | Доступ к принтерам |
| **Именованные** | Конкретные общие ресурсы |

### Основные параметры секций

| Параметр | Описание |
| :--- | :--- |
| `path` | Путь к директории |
| `browseable` | Показывать в списке доступных |
| `writable` / `read only` | Разрешена ли запись |
| `valid users` | Список пользователей (группы с `@`) |
| `guest ok` | Разрешить гостевой доступ |
| `inherit ACLs` | Наследование ACL родительской директории |

### Переменные

| Переменная | Описание |
| :--- | :--- |
| `%s` | Имя секции |
| `%u` | Имя пользователя |
| `%w` | Имя рабочей группы |
| `%d` | ID пользователя (UID) |

## Монтирование SMB на клиенте Linux

### Временное монтирование

```bash
# Гостевой доступ
sudo mount -t cifs //smb-server/Public /mnt/samba -o guest

# С паролем
sudo mount -t cifs //smb-server/Private /mnt/private -o username=smbuser
```

### Постоянное монтирование (`/etc/fstab`)

```bash
# Создание файла с учётными данными
sudo mkdir -p /root/.smb
sudo tee /root/.smb/credentials <<EOF
username=smbuser
password=secretpassword
EOF
sudo chmod 600 /root/.smb/credentials
```

```ini
# /etc/fstab
//smb-server/private /mnt/samba cifs credentials=/root/.smb/credentials,uid=1000,gid=1000,file_mode=0755,dir_mode=0755,nofail 0 0
```

## Связанные документы

- [Базовые концепции](./samba_basics.md)
- [Безопасность](./samba_security.md) — шифрование, VFS модули
- [AD-интеграция](./samba_ad.md) — домен, winbind
- [Монтирование в fstab](../../../FileSystems/mounting/fstab.md)
