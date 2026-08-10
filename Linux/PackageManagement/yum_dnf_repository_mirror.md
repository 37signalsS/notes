# Зеркалирование YUM/DNF-репозиториев

## Определения

Ниже приведены основные термины, используемые в процессе создания локальных копий репозиториев для систем на базе RPM (Red Hat Package Manager).

**Локальное зеркало (Local Mirror)** — полная или частичная копия удалённого репозитория пакетов, размещённая в локальной сети или на изолированном сервере. Позволяет экономить внешний трафик, ускорять установку и обеспечивать доступ к ПО в закрытых контурах (Air-Gapped).

**Репозиторий-источник (Upstream Repository)** — официальный или доверенный удалённый сервер (например, зеркала AlmaLinux, Rocky Linux или Fedora), с которым выполняется синхронизация.

**Синхронизация (Synchronization)** — процесс приведения локального зеркала в соответствие с источником. Включает загрузку новых пакетов (`.rpm`), дельта-пакетов (`.drpm`) и метаданных.

**Метаданные репозитория** — набор XML или SQLite файлов, описывающих содержимое репозитория.
- `repomd.xml` — индексный файл, содержащий хеши и пути ко всем остальным метаданным.
- `primary.xml` — список пакетов и их базовых свойств.
- `modules.yaml` — описание модульных потоков (специфично для AppStream).

---

## Основные концепции

### Назначение зеркалирования

Использование локальных зеркал для пакетных менеджеров DNF (Dandified YUM) и YUM (Yellowdog Updater, Modified) необходимо для решения следующих задач:

- **Ускорение обновлений**: Передача данных в локальной сети (1–40 Gbps) исключает задержки WAN-каналов.
- **Инфраструктура Air-Gapped**: Обеспечение работы систем в изолированных сегментах без прямого выхода в интернет.
- **Воспроизводимость (Snapshotting)**: Возможность заморозки состояния репозитория на определенную дату для обеспечения идентичности окружений разработки, тестирования и эксплуатации.

### Архитектура процесса (DNF Reposync)

В современных дистрибутивах (RHEL 8/9, Fedora) утилита `reposync` интегрирована как плагин DNF. Процесс включает:

1.  **Загрузка (reposync)**: Скачивание RPM-пакетов. Важно использовать флаг `--download-metadata` для сохранения оригинальных подписей метаданных и модульных данных.
2.  **Индексация (createrepo_c)**: Генерация файлов индексов. `createrepo_c` (реализация на C) значительно быстрее классического `createrepo` на Python.
3.  **Публикация**: Предоставление доступа по протоколу HTTP/HTTPS через Nginx или Apache.

### Особенности AppStream и модульности

Репозитории типа `AppStream` содержат метаданные модулей (`modules.yaml`).
- При использовании `dnf reposync --download-metadata` метаданные модулей копируются автоматически.
- Если метаданные создаются вручную через `createrepo_c`, модули будут потеряны, если не передать файл модулей через флаг `--package-module-dict`.

---

## Практические сценарии

### Сценарий 1: Создание зеркала AlmaLinux 9 / RHEL 9

#### 1. Подготовка инструментария

```bash
# Установка необходимых утилит и веб-сервера
sudo dnf install dnf-plugins-core createrepo_c nginx
```

#### 2. Синхронизация репозитория

```bash
# Создание структуры каталогов
sudo mkdir -p /var/www/html/repos/alma9/{baseos,appstream}

# Синхронизация BaseOS (только актуальные версии, x86_64)
sudo dnf reposync \
    --repoid=baseos \
    --download-path=/var/www/html/repos/alma9 \
    --newest-only \
    --delete \
    --download-metadata \
    --arch=x86_64
```

#### 3. Настройка публикации (Nginx)

```nginx
# /etc/nginx/conf.d/repo.conf
server {
    listen 80;
    server_name repo.local;
    root /var/www/html/repos;

    location / {
        autoindex on;        # Разрешить листинг файлов
        autoindex_exact_size off;
        autoindex_localtime on;
    }
}
```

---

### Сценарий 2: Использование зеркала на клиентах

Настройка клиента для работы с локальным источником.

```ini
# /etc/yum.repos.d/local-mirror.repo
[local-baseos]
name=Local AlmaLinux 9 BaseOS
baseurl=http://repo.local/alma9/baseos/
enabled=1
gpgcheck=1
gpgkey=http://repo.local/alma9/RPM-GPG-KEY-AlmaLinux-9

[local-appstream]
name=Local AlmaLinux 9 AppStream
baseurl=http://repo.local/alma9/appstream/
enabled=1
gpgcheck=1
gpgkey=http://repo.local/alma9/RPM-GPG-KEY-AlmaLinux-9
```

---

### Сценарий 3: Автоматизация через systemd timer

Использование таймеров обеспечивает надежное обновление по расписанию с обработкой зависимостей сервисов.

```ini
# /etc/systemd/system/repo-sync.service
[Unit]
Description=RPM Repository Synchronization Service
After=network-online.target

[Service]
Type=oneshot
User=nginx
Group=nginx
ExecStart=/usr/bin/dnf reposync --repoid=baseos --download-path=/var/www/html/repos/alma9 --newest-only --delete --download-metadata
ExecStart=/usr/bin/dnf reposync --repoid=appstream --download-path=/var/www/html/repos/alma9 --newest-only --delete --download-metadata
# Обновление индексов только если это необходимо (инкрементально)
ExecStartPost=/usr/bin/createrepo_c --update /var/www/html/repos/alma9/baseos
ExecStartPost=/usr/bin/createrepo_c --update /var/www/html/repos/alma9/appstream

[Install]
WantedBy=multi-user.target
```

```ini
# /etc/systemd/system/repo-sync.timer
[Unit]
Description=Run RPM Repo Sync Daily

[Timer]
OnCalendar=*-*-* 03:00:00
Persistent=true

[Install]
WantedBy=timers.target
```

---

## Дополнительная информация

### Требования к дисковому пространству (актуально на 2025 г.)

| Репозиторий | Объем (Full) | Объем (Newest Only) | Примечание |
| :--- | :--- | :--- | :--- |
| **AlmaLinux 9 BaseOS** | ~20 GB | ~8 GB | Основные пакеты ОС |
| **AlmaLinux 9 AppStream** | ~70 GB | ~25 GB | Модули и приложения |
| **Fedora 41 Everything** | ~400 GB | ~150 GB | Огромное количество пакетов |
| **EPEL 9** | ~45 GB | ~15 GB | Дополнительные пакеты |

### Рекомендации по эксплуатации

1.  **GPG-верификация**: Никогда не отключайте `gpgcheck`. Скопируйте GPG-ключи на сервер зеркала и указывайте путь к ним в `gpgkey` (через HTTP или локально).
2.  **Синхронизация RHEL**: Для зеркалирования официального RHEL требуется подписка. Выполняйте `reposync` на хосте, зарегистрированном через `subscription-manager`.
3.  **Архитектуры**: Используйте флаг `--arch`, чтобы не выкачивать пакеты для `i686` или `s390x`, если они не используются в вашей инфраструктуре.
4.  **Delta RPM**: Если клиенты имеют медленные каналы, убедитесь, что зеркало содержит `.drpm` файлы (требует плагина `deltarpm`).

### Устранение проблем

- **Ошибка метаданных AppStream**: Если после синхронизации `dnf module list` пуст, значит метаданные модулей не были загружены. Проверьте наличие каталога `repodata` и используйте `--download-metadata`.
- **Место на диске**: Репозитории постоянно растут. Рекомендуется выделять под зеркало отдельный LVM-том или раздел с файловой системой XFS/EXT4.

### Связанные документы

- **[Команды DNF](./dnf_commands/practical_scenarios.md)** — использование настроенных зеркал.
- **[Зеркалирование APT](./apt_mirror/practical_scenarios.md)** — аналогичный процесс для Debian/Ubuntu.
- **[Создание собственного репозитория](./Repository_Management/custom_repository.md)** — процедура подготовки репозитория из локальных RPM-файлов.
- **[Управление репозиториями DNF](./Repository_Management/index.md)** — общие принципы настройки источников.
- **[Операции с репозиториями](./Repository_Management/operations.md)** — управление статусом, GPG-ключами и CLI-инструментарий.
