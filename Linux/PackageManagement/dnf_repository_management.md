# Управление репозиториями в DNF

## Определения

**Репозиторий DNF** — сервер или локальный каталог, содержащий RPM-пакеты и метаданные в формате, совместимом с DNF/YUM. Конфигурируется через файлы в `/etc/yum.repos.d/`.

**GPG-ключ репозитория** — криптографический ключ для проверки подлинности пакетов. Гарантирует, что пакеты не были изменены и подписаны доверенным источником.

**Металink/Mirrorlist** — механизм динамического выбора зеркала для загрузки пакетов, обеспечивающий отказоустойчивость и балансировку нагрузки.

## Основные понятия

### Структура файла репозитория

Файлы репозиториев имеют формат INI с расширением `.repo` в директории `/etc/yum.repos.d/`.

```ini
[repo_id]                    # Уникальный идентификатор репозитория
name=Human-Readable Name     # Человекочитаемое имя
baseurl=http://...           # Прямой URL репозитория
mirrorlist=http://...        # URL списка зеркал (альтернатива baseurl)
metalink=https://...         # URL metalink (предпочтительно для Fedora)
enabled=1                    # Включен (1) или выключен (0)
gpgcheck=1                   # Проверка GPG-подписи (1 - вкл, 0 - выкл)
gpgkey=file:///...           # URL или путь к публичному GPG-ключу
repo_gpgcheck=0              # Проверка подписи метаданных (1 - вкл)
type=rpm-md                  # Тип репозитория (rpm-md, rpm, yum)
priority=50                  # Приоритет (требуется плагин versionlock, меньше = выше)
cost=1000                    # Стоимость (для выбора между зеркалами)
includepkgs=package1,package2  # Включить только указанные пакеты
exclude=package3,package4    # Исключить указанные пакеты
```

### Приоритеты репозиториев

| Параметр | Значение | Назначение |
| :--- | :--- | :--- |
| `priority` | 1-99 | Приоритет репозитория (1 — наивысший) |
| `cost` | 1+ | Стоимость пакета из репозитория (меньше = лучше) |
| `enabled` | 0/1 | Включен ли репозиторий по умолчанию |

**Важно:** Для работы приоритетов требуется плагин `dnf-plugin-priorities` или `yum-plugin-priorities`.

## Практические сценарии

### Просмотр репозиториев

```bash
# Список включённых репозиториев
dnf repolist

# Список всех репозиториев (включая отключенные)
dnf repolist all

# Подробная информация о репозитории
dnf repoinfo <repo_id>

# Показать конфигурацию репозитория
dnf config-manager --dump

# Включить репозиторий
sudo dnf config-manager --set-enabled <repo_id>

# Отключить репозиторий
sudo dnf config-manager --set-disabled <repo_id>
```

### Добавление репозитория

#### Способ 1: Через config-manager (рекомендуемый)

```bash
# Добавить репозиторий по URL .repo файла
sudo dnf config-manager --add-repo https://example.com/repo.repo

# Добавить репозиторий с указанием параметров
sudo dnf config-manager --add-repo http://example.com/repo
sudo dnf config-manager --save --setopt=<repo_id>.gpgcheck=1
```

#### Способ 2: Ручное создание файла

```bash
# Создать файл /etc/yum.repos.d/example.repo
sudo tee /etc/yum.repos.d/example.repo << 'EOF'
[example]
name=Example Repository
baseurl=https://repo.example.com/centos/$releasever/os/$basearch/
gpgcheck=1
gpgkey=https://repo.example.com/RPM-GPG-KEY-example
enabled=1
EOF

# Обновить кэш метаданных
sudo dnf makecache
```

#### Способ 3: Использование готовых репозиториев

```bash
# EPEL (Extra Packages for Enterprise Linux)
sudo dnf install epel-release

# RPM Fusion (для Fedora)
sudo dnf install https://mirrors.rpmfusion.org/free/fedora/rpmfusion-free-release-$(rpm -E %fedora).noarch.rpm
sudo dnf install https://mirrors.rpmfusion.org/nonfree/fedora/rpmfusion-nonfree-release-$(rpm -E %fedora).noarch.rpm

# Google Chrome
sudo dnf install https://dl.google.com/linux/chrome/rpm/stable/x86_64/Packages/g/google-chrome-stable_current_x86_64.rpm

# Docker
sudo dnf config-manager --add-repo https://download.docker.com/linux/centos/docker-ce.repo
```

### Импорт GPG-ключей

```bash
# Импортировать ключ из файла
sudo rpm --import /path/to/gpg-key.pub

# Импортировать ключ из URL
sudo rpm --import https://example.com/gpg-key.pub

# Импортировать ключ для конкретного репозитория
sudo rpm --import https://repo.example.com/RPM-GPG-KEY-example

# Показать импортированные ключи
rpm -qa gpg-pubkey*

# Детали конкретного ключа
rpm -qi gpg-pubkey-<key_id>

# Удалить ключ (если требуется)
sudo rpm -e gpg-pubkey-<key_id>
```

### Проверка подписей пакетов

```bash
# Проверить подпись установленного пакета
rpm -V <package_name>

# Проверить подпись .rpm файла
rpm -K <package_name.rpm>

# Вывод:
# digests signatures OK — подпись валидна
# NOT FOUND — подпись отсутствует
# NOT OK — подпись невалидна (опасно!)
```

### Создание локального репозитория

#### Шаг 1: Установка инструментов

```bash
sudo dnf install yum-utils createrepo_c httpd
```

#### Шаг 2: Синхронизация с удалённым репозиторием

```bash
# Создать директорию для зеркала
sudo mkdir -p /var/www/html/yum

# Синхронизировать репозиторий (пример для base)
sudo reposync --gpgcheck -l --repoid=base --download-path=/var/www/html/yum

# Для нескольких репозиториев
sudo reposync --gpgcheck -l -p /var/www/html/yum
```

#### Шаг 3: Создание метаданных

```bash
# Создать метаданные для DNF/YUM
sudo createrepo_c /var/www/html/yum/base

# Обновить метаданные после добавления пакетов
sudo createrepo_c --update /var/www/html/yum/base

# Полная пересоздание метаданных
sudo createrepo_c --cleanup --update /var/www/html/yum/base
```

#### Шаг 4: Публикация через HTTP

```bash
# Настроить SELinux для HTTP-доступа (если включён)
sudo setsebool -P httpd_can_network_connect 1
sudo semanage fcontext -a -t httpd_sys_content_t "/var/www/html/yum(/.*)?"
sudo restorecon -Rv /var/www/html/yum

# Включить и запустить httpd
sudo systemctl enable --now httpd

# Открыть порт в firewall
sudo firewall-cmd --permanent --add-service=http
sudo firewall-cmd --reload
```

#### Шаг 5: Конфигурация клиентов

Создать файл `/etc/yum.repos.d/local-mirror.repo` на клиентских машинах:

```ini
[local-base]
name=Local Base Mirror
baseurl=http://mirror.local/yum/base/
gpgcheck=0
enabled=1
```

### Создание собственного репозитория с пакетами

#### Шаг 1: Подготовка структуры

```bash
# Создать директорию репозитория
mkdir -p ~/my-repo/{packages,metadata}

# Поместить .rpm пакеты в директорию
cp *.rpm ~/my-repo/packages/
```

#### Шаг 2: Создание метаданных

```bash
cd ~/my-repo/packages

# Создать метаданные
createrepo_c .

# Результат:
# repodata/repomd.xml    # Основной файл метаданных
# repodata/*-primary.xml # Информация о пакетах
# repodata/*-filelists.xml # Списки файлов
# repodata/*-other.xml   # Дополнительная информация
```

#### Шаг 3: Подпись репозитория (опционально)

```bash
# Создать GPG-ключ
gpg --gen-key

# Экспорт публичного ключа
gpg --export -a "Your Name" > ~/my-repo/RPM-GPG-KEY-myrepo

# Подпись пакетов
for pkg in *.rpm; do
    rpm --addsign "$pkg"
done

# Подпись метаданных
signrepo --gpg-key "Your Name" ~/my-repo/packages/
```

#### Шаг 4: Публикация

```bash
# Копирование в веб-директорию
sudo cp -r ~/my-repo/packages /var/www/html/my-repo
sudo cp ~/my-repo/RPM-GPG-KEY-myrepo /var/www/html/my-repo/

# Обновление метаданных после изменений
createrepo_c --update /var/www/html/my-repo
```

## Дополнительная информация

### Переменные в URL репозиториев

| Переменная | Значение | Пример |
| :--- | :--- | :--- |
| `$releasever` | Версия дистрибутива | `8`, `9`, `38` |
| `$basearch` | Архитектура | `x86_64`, `aarch64`, `ppc64le` |
| `$arch` | Архитектура (альтернатива) | `x86_64`, `noarch` |
| `$contentdir` | Директория контента | `centos`, `fedora` |

### Типовые проблемы и решения

| Проблема | Решение |
| :--- | :--- |
| **GPG check failed** | `sudo rpm --import <key_url>` |
| **Cannot retrieve metalink** | Проверить DNS, firewall, доступность URL |
| **Repository not found** | Проверить путь в `baseurl`, наличие метаданных |
| **404 Not Found** | Актуализировать `$releasever`, проверить структуру |
| **Медленная загрузка** | Использовать `mirrorlist` вместо `baseurl` |

### Безопасность репозиториев

1. **Всегда включайте `gpgcheck=1`** для официальных репозиториев
2. **Импортируйте ключи только из доверенных источников**
3. **Используйте HTTPS** для `baseurl` и `gpgkey` при возможности
4. **Регулярно обновляйте метаданные** (`dnf makecache`)
5. **Проверяйте подписи пакетов** перед установкой из сторонних источников

### Связанные темы

* **[Обзор управления пакетами](./linux_package_management_overview.md)** — базовые концепции
* **[Команды DNF](./dnf_commands.md)** — полный справочник по DNF
* **[Локальное зеркало репозитория](./local_repository_mirror.md)** — создание зеркал для YUM/DNF
* **[База данных пакетов](./package_database.md)** — история транзакций и восстановление
* **[Сборка пакетов](./package_building.md)** — создание собственных RPM-пакетов
