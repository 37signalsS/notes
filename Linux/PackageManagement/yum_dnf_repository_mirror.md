# Зеркалирование YUM/DNF-репозиториев

## Определения

**Локальное зеркало (Local Mirror)** — полная или частичная копия удалённого репозитория пакетов (например, CentOS, RHEL, AlmaLinux), размещённая в локальной сети или на изолированном сервере.

**Репозиторий-источник (Upstream Repository)** — официальный или доверенный удалённый репозиторий, с которого синхронизируется локальное зеркало.

**Синхронизация** — процесс обновления локального зеркала до актуального состояния репозитория-источника.

**Метаданные репозитория** — служебные файлы (repomd.xml, primary.xml, filelists.xml), описывающие содержимое репозитория.

## Основные понятия

### Назначение локального зеркала

| Преимущество | Описание |
| :--- | :--- |
| **Экономия трафика** | Пакеты скачиваются из интернета однократно, затем распространяются локально |
| **Ускорение обновлений** | Установка и обновление пакетов происходят быстрее (LAN vs WAN) |
| **Работа в изолированных сетях** | Управление пакетами в сетях без доступа к интернету (air-gapped environments) |
| **Контроль версий** | Возможность заморозить версии пакетов для стабильности |
| **Кэширование** | Сохранение старых версий для отката при необходимости |

### Архитектура зеркалирования

```
┌─────────────────┐      ┌──────────────────┐      ┌─────────────────┐
│   Интернет      │─────▶│  Сервер-зеркало  │─────▶│  Клиентские     │
│   Репозитории   │      │  (reposync)      │      │  машины         │
│   (upstream)    │      │                  │      │                 │
└─────────────────┘      └──────────────────┘      └─────────────────┘
                                │
                                ▼
                         ┌──────────────────┐
                         │  Хранилище       │
                         │  /var/www/html/  │
                         │  yum/            │
                         └──────────────────┘
```

### Инструменты зеркалирования YUM/DNF

| Инструмент | Назначение |
| :--- | :--- |
| `reposync` | Синхронизация RPM-репозиториев |
| `createrepo_c` | Создание метаданных для локальных репозиториев |

## Практические сценарии

### Сценарий 1: Создание зеркала для YUM/DNF (RHEL/CentOS/AlmaLinux)

#### Шаг 1: Установка

```bash
sudo yum install yum-utils createrepo_c httpd
# или для новых версий
sudo dnf install yum-utils createrepo_c httpd
```

#### Шаг 2: Синхронизация репозитория

```bash
# Создать директорию для зеркала
sudo mkdir -p /var/www/html/yum

# Синхронизировать репозиторий base
# --gpgcheck: проверка подписей пакетов
# -l: поддержка плагинов yum
# --repoid: идентификатор репозитория
# --download-path: путь сохранения
sudo reposync --gpgcheck -l --repoid=base --download-path=/var/www/html/yum

# Для нескольких репозиториев
sudo reposync --gpgcheck -l -p /var/www/html/yum

# Синхронизация с фильтрацией по архитектуре
sudo reposync --gpgcheck -l --repoid=base --download-path=/var/www/html/yum --arch=x86_64
```

#### Шаг 3: Создание метаданных

```bash
# Создать метаданные для каждого репозитория
sudo createrepo_c /var/www/html/yum/base

# Обновить метаданные после синхронизации
sudo createrepo_c --update /var/www/html/yum/base

# Полная пересоздание метаданных
sudo createrepo_c --cleanup --update /var/www/html/yum/base
```

#### Шаг 4: Публикация через HTTP

```bash
# Настроить SELinux (если включён)
sudo setsebool -P httpd_can_network_connect 1
sudo semanage fcontext -a -t httpd_sys_content_t "/var/www/html/yum(/.*)?"
sudo restorecon -Rv /var/www/html/yum

# Включить и запустить httpd
sudo systemctl enable --now httpd

# Открыть порт в firewall
sudo firewall-cmd --permanent --add-service=http
sudo firewall-cmd --reload
```

#### Шаг 5: Настройка клиентов

Создать файл `/etc/yum.repos.d/local-mirror.repo` на клиентских машинах:

```ini
[local-base]
name=Local Base Mirror
baseurl=http://mirror.local/yum/base/
gpgcheck=0
enabled=1
priority=50

[local-updates]
name=Local Updates Mirror
baseurl=http://mirror.local/yum/updates/
gpgcheck=0
enabled=1
priority=50
```

```bash
# Очистить кэш и обновить метаданные
sudo dnf clean all
sudo dnf makecache
```

#### Шаг 6: Автоматизация обновлений

**Cron скрипт:**

```bash
# /etc/cron.daily/yum-mirror
#!/bin/bash
REPO_DIR="/var/www/html/yum"

# Синхронизация репозиториев
reposync --gpgcheck -l --repoid=base --download-path=$REPO_DIR
reposync --gpgcheck -l --repoid=updates --download-path=$REPO_DIR

# Обновление метаданных
createrepo_c --update $REPO_DIR/base
createrepo_c --update $REPO_DIR/updates
```

```bash
sudo chmod +x /etc/cron.daily/yum-mirror
```

### Сценарий 2: Зеркалирование для изолированной сети (Air-Gapped)

#### Шаг 1: Подготовка съёмного носителя

```bash
# На машине с интернетом
sudo mkdir -p /var/www/html/yum
reposync --gpgcheck -l -p /var/www/html/yum
createrepo_c /var/www/html/yum/*

# Копирование на внешний диск
EXTERNAL_DISK="/mnt/external-drive"
sudo rsync -av /var/www/html/yum/ $EXTERNAL_DISK/yum-mirror/
```

#### Шаг 2: Развёртывание в изолированной сети

```bash
# На машине в изолированной сети
EXTERNAL_DISK="/mnt/external-drive"
sudo mkdir -p /var/www/html/offline-repo
sudo rsync -av $EXTERNAL_DISK/yum-mirror/ /var/www/html/offline-repo/

# Настроить SELinux и httpd (как выше)
```

#### Шаг 3: Использование без веб-сервера (локальный путь)

```bash
# /etc/yum.repos.d/offline.repo
[local-offline]
name=Local Offline Mirror
baseurl=file:///var/www/html/offline-repo/base/
gpgcheck=0
enabled=1
priority=50

sudo dnf makecache
```

## Дополнительная информация

### Расчёт необходимого дискового пространства

| Дистрибутив | Полный размер | Частичное (base only) |
| :--- | :--- | :--- |
| **CentOS 8** | ~150 GB | ~40 GB |
| **RHEL 9** | ~180 GB | ~45 GB |
| **AlmaLinux 9** | ~170 GB | ~42 GB |

**Рекомендации:**

- Используйте отдельный раздел/диск для зеркала
- Настройте мониторинг свободного места
- Планируйте рост (добавление новых версий)

### Оптимизация зеркалирования

**Фильтрация по архитектуре:**

```bash
# Синхронизация только для x86_64
sudo reposync --gpgcheck -l --arch=x86_64 -p /var/www/html/yum

# Исключение определённых пакетов
sudo reposync --gpgcheck -l --exclude=kernel* -p /var/www/html/yum
```

**Инкрементальная синхронизация:**

```bash
# reposync по умолчанию загружает только новые пакеты
# Для принудительной проверки всех пакетов:
reposync --downloadcomps --download-metadata

# Очистка старых версий пакетов (требует дополнительного скрипта)
```

### Мониторинг и логирование

```bash
# Логирование синхронизации
#!/bin/bash
LOG_FILE="/var/log/yum-mirror.log"
echo "=== YUM Mirror Sync: $(date) ===" >> $LOG_FILE
reposync --gpgcheck -l -p /var/www/html/yum >> $LOG_FILE 2>&1
createrepo_c --update /var/www/html/yum/base >> $LOG_FILE 2>&1

# Проверка последней синхронизации
ls -la /var/www/html/yum/*/repodata/repomd.xml

# Уведомление об ошибках
if ! reposync --gpgcheck -l -p /var/www/html/yum > /var/log/yum-mirror.log 2>&1; then
    mail -s "YUM Mirror Sync Failed" admin@example.com < /var/log/yum-mirror.log
fi
```

### Проблемы и решения

| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| **Недостаточно места** | Большой размер репо | Очистить старые пакеты, увеличить диск |
| **404 ошибки** | Изменения в структуре репо | Обновить URLs в .repo файлах |
| **GPG ошибки на клиентах** | Нет ключей | Импортировать ключи репозитория (`rpm --import`) |
| **Медленная синхронизация** | Ограничения пропускной способности | Использовать `--countonly` для проверки, rsync |
| **SELinux блокирует доступ** | Неправильный контекст | `restorecon -Rv /var/www/html/yum` |

### Связанные темы

- **[Управление репозиториями APT](./apt_mirror/basic_concepts.md)** — зеркалирование DEB-репозиториев
- **[Управление DNF-репозиториями](./dnf_commands/basic_concepts.md)** — настройка репозиториев для RPM
- **[Обзор управления пакетами](./linux_package_management_overview.md)** — базовые концепции
