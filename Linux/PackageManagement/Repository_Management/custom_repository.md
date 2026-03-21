# Создание репозиториев DNF

## Определения

**Создание репозиториев** — настройка локального зеркала или собственного репозитория с пакетами для DNF/YUM.

> **Навигация:** [Главная Repository Management](./index.md) | [Операции](./operations.md)

---

## Practical Scenarios

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

---

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

---

## Additional Information

### Связанные темы

- **[Обзор управления пакетами](../linux_package_management_overview.md)** — базовые концепции
- **[Команды DNF](../dnf_commands/definitions.md** — полный справочник по DNF
- **[Локальное зеркало репозитория](../apt_repository_mirror.md** — создание зеркал для YUM/DNF
- **[Сборка пакетов](../package_build/definitions.md)** — создание собственных RPM-пакетов
