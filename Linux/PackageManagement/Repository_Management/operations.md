# Операции с репозиториями DNF

## Определения

**Операции с репозиториями** — просмотр, добавление, импорт GPG-ключей и проверка подписей пакетов.

> **Навигация:** [Главная Repository Management](./index.md) | [Создание репозитория](./custom_repository.md)

---

## Practical Scenarios

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

---

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

---

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

---

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

---

## Additional Information

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

- **[Обзор управления пакетами](../linux_package_management_overview.md)** — базовые концепции
- **[Команды DNF](./dnf_commands.md)** — полный справочник по DNF
