# Зеркалирование APT: Практические сценарии

## Определения

Определения терминов приведены в документе **[Определения](./definitions.md)**. Система APT является основным инструментом управления пакетами в дистрибутивах на базе Debian и Ubuntu.

---

## Основные концепции

Обзор архитектуры, инструменты и принципы работы доступны в файле **[Основные понятия](./basic_concepts.md)**.

---

## Практические сценарии

### Сценарий 1: Создание зеркала с помощью aptly (рекомендуется)

`aptly` является современным стандартом для управления зеркалами благодаря поддержке снимков (Snapshots) и возможности публикации нескольких версий репозитория.

#### Шаг 1: Установка и инициализация
```bash
sudo apt update && sudo apt install aptly

# Создание конфигурационного файла ~/.aptly.conf (опционально)
# По умолчанию данные хранятся в ~/.aptly
```

#### Шаг 2: Создание зеркала
Пример для **Ubuntu 24.04 (Noble Numbat)**:
```bash
# Добавление зеркала
aptly mirror create noble-main http://archive.ubuntu.com/ubuntu/ noble main restricted universe multiverse

# Обновление зеркала (загрузка пакетов)
aptly mirror update noble-main
```

#### Шаг 3: Создание снимка и публикация
Снимки обеспечивают стабильность: клиенты не увидят изменений, пока вы не обновите публикацию новым снимком.
```bash
# Создание снимка из зеркала
aptly snapshot create noble-main-snap-2026-07-27 from mirror noble-main

# Публикация снимка
aptly publish snapshot -distribution="noble" noble-main-snap-2026-07-27
```

#### Шаг 4: Настройка клиента (DEB822)
В современных версиях Ubuntu (24.04+) рекомендуется использовать формат `.sources` (DEB822).

Создайте файл `/etc/apt/sources.list.d/local-mirror.sources`:
```text
Types: deb
URIs: http://mirror.local/noble
Suites: noble
Components: main restricted universe multiverse
Signed-By: /usr/share/keyrings/local-mirror-archive-keyring.gpg
```

---

### Сценарий 2: Использование apt-mirror (legacy)

Классический способ «один-в-один». Подходит для простых задач без необходимости управления версиями.

#### Шаг 1: Настройка `mirror.list`
Пример для **Ubuntu 24.04**:
```bash
sudo tee /etc/apt/mirror.list << 'EOF'
set base_path    /var/spool/apt-mirror
set nthreads     20
set _tilde       0

deb http://archive.ubuntu.com/ubuntu noble main restricted universe multiverse
deb http://archive.ubuntu.com/ubuntu noble-updates main restricted universe multiverse
deb http://security.ubuntu.com/ubuntu noble-security main restricted universe multiverse

clean http://archive.ubuntu.com/ubuntu
clean http://security.ubuntu.com/ubuntu
EOF
```

#### Шаг 2: Синхронизация и раздача
```bash
sudo apt-mirror

# Публикация через Nginx
sudo ln -s /var/spool/apt-mirror/mirror/archive.ubuntu.com/ubuntu /var/www/html/ubuntu
```

---

### Сценарий 3: Работа в изолированной сети (Air-Gapped)

#### Шаг 1: Подготовка данных
На машине с доступом в интернет выполните синхронизацию и упакуйте данные:
```bash
# Для aptly (экспорт базы и пакетов)
tar -cvzf aptly_data.tar.gz ~/.aptly

# Для apt-mirror (копирование через rsync)
rsync -av /var/spool/apt-mirror/ /mnt/external-disk/apt-mirror/
```

#### Шаг 2: Развёртывание
В изолированном контуре разверните данные и настройте веб-сервер для раздачи статики.

---

## Дополнительная информация

### Автоматизация
Для ежедневного обновления зеркала используйте таймеры systemd:

```ini
# /etc/systemd/system/aptly-sync.service
[Unit]
Description=Update aptly mirror and publish
[Service]
Type=oneshot
ExecStart=/usr/bin/aptly mirror update noble-main
ExecStartPost=/usr/bin/aptly snapshot create noble-snap-$(date +%%Y%%m%%d) from mirror noble-main
ExecStartPost=/usr/bin/aptly publish switch noble noble-snap-$(date +%%Y%%m%%d)
```

### Связанные документы
- **[Дополнительная информация](./additional_info.md)** — расчет места и решение проблем.
- **[Приватный APT-репозиторий](../deb_private_apt_repository_reprepro/practical_scenarios.md)** — создание собственных пакетов.
- **[Nginx: Настройка репозитория](../../WebServers/Nginx/Scenarios/secure_apt_repository_guide.md)** — конфигурация веб-сервера.
