# Создание собственных RPM-репозиториев

## Определения

**Собственный репозиторий** — локальный или внутренний репозиторий с кастомными RPM-пакетами, созданный для распространения собственного ПО внутри организации.

**Метаданные репозитория** — файлы в директории `repodata/`, описывающие содержимое репозитория (repomd.xml, primary.xml, filelists.xml, other.xml).

**GPG-подпись репозитория** — криптографическая подпись пакетов и метаданных для проверки целостности и аутентичности.

## Основные понятия

### Отличие от зеркалирования

| Аспект | Зеркалирование | Создание собственного репозитория |
| :--- | :--- | :--- |
| **Цель** | Копирование внешнего репозитория | Распространение собственных пакетов |
| **Источник** | Внешний upstream-репозиторий | Собственные .rpm пакеты |
| **Инструменты** | `reposync` + `createrepo_c` | `createrepo_c` + `rpmsign` |
| **SSoT** | [yum_dnf_repository_mirror.md](../../yum_dnf_repository_mirror.md) | Данный файл |

### Структура репозитория

```
my-repo/
├── packages/           # .rpm файлы
│   ├── app-1.0-1.el9.x86_64.rpm
│   ├── lib-2.3-1.el9.x86_64.rpm
│   └── repodata/       # Автоматически создаётся createrepo_c
│       ├── repomd.xml
│       ├── *-primary.xml
│       ├── *-filelists.xml
│       └── *-other.xml
├── RPM-GPG-KEY-myrepo  # Публичный GPG-ключ
└── metadata/           # Дополнительная документация
```

### Инструменты

| Инструмент | Назначение |
| :--- | :--- |
| `createrepo_c` | Создание и обновление метаданных репозитория |
| `rpm --addsign` | Подпись RPM-пакетов GPG-ключом |
| `signrepo` | Подпись метаданных репозитория |
| `gpg` | Генерация и управление GPG-ключами |

## Практические сценарии

### Сценарий 1: Создание репозитория с собственными пакетами

#### Шаг 1: Подготовка структуры

```bash
mkdir -p ~/my-repo/{packages,metadata}
cp *.rpm ~/my-repo/packages/
```

#### Шаг 2: Создание метаданных

```bash
cd ~/my-repo/packages

# Инициализация репозитория
createrepo_c .

# Обновление после добавления новых пакетов
createrepo_c --update .

# Полная пересоздание с очисткой устаревших записей
createrepo_c --cleanup --update .
```

**Результат:** директория `repodata/` с файлами метаданных.

#### Шаг 3: Публикация через HTTP

```bash
# Копирование в веб-директорию
sudo cp -r ~/my-repo/packages /var/www/html/my-repo

# SELinux (если включён)
sudo semanage fcontext -a -t httpd_sys_content_t "/var/www/html/my-repo(/.*)?"
sudo restorecon -Rv /var/www/html/my-repo

# Запуск веб-сервера
sudo systemctl enable --now httpd
sudo firewall-cmd --permanent --add-service=http
sudo firewall-cmd --reload
```

#### Шаг 4: Настройка клиентов

Создать файл `/etc/yum.repos.d/my-repo.repo`:

```ini
[my-custom-repo]
name=My Custom Repository
baseurl=http://repo-server.local/my-repo/
gpgcheck=1
gpgkey=http://repo-server.local/my-repo/RPM-GPG-KEY-myrepo
enabled=1
```

```bash
# Проверка на клиенте
sudo dnf makecache
sudo dnf repolist
```

---

### Сценарий 2: GPG-подпись репозитория

#### Шаг 1: Генерация GPG-ключа

```bash
gpg --full-generate-key
# Выбрать: RSA (4096), без срока действия
# Указать: имя и email
```

#### Шаг 2: Экспорт публичного ключа

```bash
gpg --export -a "Your Name <email@example.com>" > ~/my-repo/RPM-GPG-KEY-myrepo
```

#### Шаг 3: Подпись пакетов

```bash
# Настройка rpm для использования ключа
# Создать ~/.rpmmacros:
%_gpg_name Your Name <email@example.com>

# Подпись всех пакетов
cd ~/my-repo/packages
for pkg in *.rpm; do
    rpm --addsign "$pkg"
done

# Проверка подписи
rpm -K app-1.0-1.el9.x86_64.rpm
```

#### Шаг 4: Подпись метаданных

```bash
signrepo --gpg-key "Your Name <email@example.com>" ~/my-repo/packages/
```

---

### Сценарий 3: Автоматизация обновления репозитория

#### Cron-скрипт для обновления

```bash
# /etc/cron.daily/repo-update
#!/bin/bash
REPO_DIR="/var/www/html/my-repo"
LOG_FILE="/var/log/repo-update.log"

echo "=== Repo Update: $(date) ===" >> "$LOG_FILE"

# Обновление метаданных
createrepo_c --update "$REPO_DIR" >> "$LOG_FILE" 2>&1

# Проверка результата
if [ $? -eq 0 ]; then
    echo "SUCCESS" >> "$LOG_FILE"
else
    echo "FAILED" >> "$LOG_FILE"
    mail -s "Repo Update Failed" admin@example.com < "$LOG_FILE"
fi
```

```bash
sudo chmod +x /etc/cron.daily/repo-update
```

## Дополнительная информация

### Связанные темы

- **[Зеркалирование YUM/DNF](../../yum_dnf_repository_mirror.md)** — полное руководство по зеркалированию внешних репозиториев
- **[Команды DNF](../../dnf_commands/definitions.md)** — управление пакетами через DNF
- **[Обзор управления пакетами](../../linux_package_management_overview.md)** — базовые концепции
