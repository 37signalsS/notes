# Определения

**Autofs** — сервис в Linux для монтирования файловых систем по требованию. Автоматически монтирует ресурс при первом обращении и отмонтирует после заданного периода бездействия.

> **Статус:** Autofs 5.x активно поддерживается. Рекомендуется для сложных сценариев: NFS (Network File System), гетерогенные среды, интеграция с NIS (Network Information Service) или LDAP (Lightweight Directory Access Protocol). Для простых случаев предпочтительнее [systemd automount](./systemd_mount.md).

# Основные концепции

## Архитектура

Работа `autofs` управляется двумя типами файлов:

1. **Главный файл конфигурации (`/etc/auto.master`)** — определяет корневые точки монтирования и указывает файлы карт.
2. **Файлы карт (например, `/etc/auto.direct`)** — перечисляют конкретные точки монтирования, опции и источники.

## Сравнение: Autofs vs Systemd automount

| Критерий | Autofs | Systemd automount |
| :--- | :--- | :--- |
| Сложность настройки | Выше (два файла конфигурации) | Ниже (юниты systemd) |
| NFS-шары | Рекомендуется | Подходит |
| Отладка | `automount -f -v` | `journalctl -u` |
| Интеграция с systemd | Ограниченная | Нативная |
| Desktop-среды | Не рекомендуется | Предпочтительно |
| Сложные сценарии | Рекомендуется (NIS, LDAP) | Ограничено |

## Ограничения и известные проблемы

| Проблема | Решение |
| :--- | :--- |
| Сессии SSH (Secure Shell) через FUSE (Filesystem in Userspace) | Может не работать |
| FUSE + util-linux | Проблемы с размонтированием |
| Пароли в открытом виде | Использовать credentials-файлы |
| Блокировка при потере соединения | Использовать мягкие маунты (`soft`) |

# Практические сценарии

## Сценарий 1: Монтирование локального раздела

### 1. Установка

```bash
sudo apt update
sudo apt install autofs
```

### 2. Конфигурация `/etc/auto.master`

Добавьте строку в `/etc/auto.master`. Использование `/-` позволяет задавать абсолютные пути в файле карты.

```text
# /etc/auto.master
# <точка монтирования>  <файл карты>      <опции>
/-                      /etc/auto.direct  --timeout=60
```

`--timeout=60` — отмонтирование через 60 секунд бездействия.

### 3. Создание файла карты `/etc/auto.direct`

```text
# /etc/auto.direct
# <полный_путь>  <опции_монтирования>  <источник>
/mnt/data         -fstype=ext4,rw       :/dev/disk/by-uuid/a1b2c3d4-e5f6-7890
```

**Синтаксис:** опции (`-fstype=...`) начинаются с дефиса, источник (`:/dev/...`) — с двоеточия.

### 4. Перезапуск сервиса

```bash
sudo systemctl enable --now autofs
```

При первом обращении к `/mnt/data` autofs автоматически смонтирует указанный раздел.

## Сценарий 2: Монтирование домашних директорий по NFS

Востребован в корпоративных средах, где домашние директории пользователей хранятся на центральном NFS-сервере и должны быть доступны на любом рабочем месте.

### 1. Установка

```bash
# RHEL/CentOS
sudo yum install -y autofs

# Debian/Ubuntu
sudo apt install -y autofs
```

### 2. Настройка `/etc/auto.master`

```text
# /etc/auto.master
/home /etc/auto.home --timeout=300
```

### 3. Настройка `/etc/auto.home`

Используются подстановочные символы: `*` — любой username, `&` — подставляет имя пользователя.

```text
# /etc/auto.home
* -rw,sync,soft,intr server.example.com:/home/&
```

### 4. Применение конфигурации

```bash
sudo systemctl restart autofs
```

При обращении к `/home/username` autofs смонтирует `server.example.com:/home/username`.

## Сценарий 3: Интеграция с FreeIPA/LDAP

В инфраструктурах с центральным сервером идентификации FreeIPA (Identity, Policy, Audit) или LDAP в сочетании с Kerberos обеспечивается аутентификация, NFS хранит домашние директории, а autofs монтирует их при первом обращении.

### Настройка клиента FreeIPA

```bash
sudo yum install -y freeipa-client
sudo ipa-client-install --enable-dns-updates
```

Здесь DNS (Domain Name System) используется для автоматического поиска серверов. После настройки клиент получает список пользователей с сервера, autofs обеспечивает монтирование их домашних директорий.

## Отладка

```bash
systemctl status autofs        # статус сервиса
automount -f -v                # verbose-режим
automount -f --debug           # полная отладка
journalctl -u autofs -f        # логи сервиса
```

# Дополнительная информация

### Связанные темы

* **[NFS (Network File System)](../../../Networking/Services/nfs/index.md)** — основной протокол для Autofs
* **[Systemd mount units](./systemd_mount.md)** — современная альтернатива
* **[Файл /etc/fstab](../fstab.md)** — статическое монтирование
