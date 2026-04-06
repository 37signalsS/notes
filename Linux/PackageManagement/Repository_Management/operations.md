# Операции с репозиториями DNF

## Определения

**Операции с репозиториями** — просмотр, добавление, удаление репозиториев, импорт GPG-ключей и проверка подписей пакетов.

## Основные понятия

### Типы операций

| Категория | Описание | Примеры команд |
| :--- | :--- | :--- |
| **Просмотр** | Получение информации о подключённых репозиториях | `dnf repolist`, `dnf repoinfo` |
| **Управление** | Включение/отключение, добавление новых | `config-manager --set-enabled`, `--add-repo` |
| **GPG-ключи** | Импорт, просмотр, удаление ключей | `rpm --import`, `rpm -qa gpg-pubkey*` |
| **Проверка подписей** | Валидация целостности пакетов | `rpm -K`, `rpm -V` |

### Методы добавления репозиториев

| Метод | Когда использовать | Преимущества |
| :--- | :--- | :--- |
| **config-manager --add-repo** | Официальные репозитории с .repo файлом | Автоматическая генерация конфига |
| **Ручное создание .repo** | Кастомные репозитории с особыми параметрами | Полный контроль над настройками |
| **Пакет release-репозитория** | Популярные сторонние репозитории (EPEL, RPM Fusion) | Автоматическая настройка GPG-ключей |

### GPG-проверка

- `gpgcheck=1` — проверяет подпись каждого пакета перед установкой
- `repo_gpgcheck=1` — проверяет подпись метаданных репозитория
- Ключи хранятся в RPM DB с префиксом `gpg-pubkey-`

## Практические сценарии

### Сценарий 1: Просмотр и управление репозиториями

```bash
# Список включённых репозиториев
dnf repolist

# Список всех репозиториев (включая отключённые)
dnf repolist all

# Подробная информация о репозитории
dnf repoinfo <repo_id>

# Показать конфигурацию всех репозиториев
dnf config-manager --dump

# Включить репозиторий
sudo dnf config-manager --set-enabled <repo_id>

# Отключить репозиторий
sudo dnf config-manager --set-disabled <repo_id>
```

---

### Сценарий 2: Добавление репозитория

#### Способ 1: Через config-manager (рекомендуемый)

```bash
# Добавить репозиторий по URL .repo файла
sudo dnf config-manager --add-repo https://example.com/repo.repo

# Добавить и настроить параметры
sudo dnf config-manager --add-repo http://example.com/repo
sudo dnf config-manager --save --setopt=<repo_id>.gpgcheck=1
```

#### Способ 2: Ручное создание файла

```bash
sudo tee /etc/yum.repos.d/example.repo << 'EOF'
[example]
name=Example Repository
baseurl=https://repo.example.com/centos/$releasever/os/$basearch/
gpgcheck=1
gpgkey=https://repo.example.com/RPM-GPG-KEY-example
enabled=1
EOF

sudo dnf makecache
```

#### Способ 3: Установка release-пакетов

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

---

### Сценарий 3: Импорт и управление GPG-ключами

```bash
# Импортировать ключ из файла
sudo rpm --import /path/to/gpg-key.pub

# Импортировать ключ из URL
sudo rpm --import https://example.com/gpg-key.pub

# Показать все импортированные ключи
rpm -qa gpg-pubkey*

# Детали конкретного ключа
rpm -qi gpg-pubkey-<key_id>

# Удалить ключ
sudo rpm -e gpg-pubkey-<key_id>
```

---

### Сценарий 4: Проверка подписей пакетов

```bash
# Проверить подпись установленного пакета
rpm -V <package_name>

# Проверить подпись .rpm файла
rpm -K <package_name.rpm>
```

**Результат проверки:**

| Статус | Значение |
| :--- | :--- |
| `digests signatures OK` | Подпись валидна |
| `NOT FOUND` | Подпись отсутствует |
| `NOT OK` | Подпись невалидна — не устанавливать |

## Дополнительная информация

### Troubleshooting

| Проблема | Решение |
| :--- | :--- |
| **GPG check failed** | Импортировать ключ: `sudo rpm --import <key_url>` |
| **Cannot retrieve metalink** | Проверить DNS, firewall, доступность URL |
| **Repository not found** | Проверить `baseurl`, наличие метаданных |
| **404 Not Found** | Актуализировать `$releasever`, проверить структуру |
| **Медленная загрузка** | Использовать `mirrorlist` вместо `baseurl` |

### Безопасность

- Всегда включать `gpgcheck=1` для официальных репозиториев
- Импортировать ключи только из доверенных источников
- Использовать HTTPS для `baseurl` и `gpgkey`
- Регулярно обновлять метаданные (`dnf makecache`)
- Проверять подписи пакетов перед установкой из сторонних источников

### Связанные темы

- **[Управление репозиториями](./index.md)** — обзор и конфигурация
- **[Создание собственного репозитория](./custom_repository.md)** — подготовка RPM-репозитория
- **[Зеркалирование YUM/DNF](../yum_dnf_repository_mirror.md)** — полное зеркалирование
- **[Обзор управления пакетами](../linux_package_management_overview.md)** — базовые концепции
