# Зеркалирование APT: Практические сценарии

## Определения

Определения терминов приведены в документе **[Определения](./definitions.md)**. Система APT (Advanced Package Tool) является основным инструментом управления пакетами в дистрибутивах на базе Debian и Ubuntu.

## Основные концепции

Обзор архитектуры, инструменты и принципы работы доступны в файле **[Основные понятия](./basic_concepts.md)**.

---

## Практические сценарии

### Сценарий 1: Создание зеркала для APT (Debian/Ubuntu)

#### Шаг 1: Установка

Для работы потребуется пакет `apt-mirror` и веб-сервер (например, Apache или Nginx) для раздачи пакетов по протоколу HTTP (HyperText Transfer Protocol).

```bash
sudo apt update
sudo apt install apt-mirror apache2
```

#### Шаг 2: Настройка `apt-mirror`

Конфигурационный файл `/etc/apt/mirror.list` определяет скачиваемые репозитории, компоненты и архитектуры.

**Пример конфигурации для Ubuntu 22.04 (Jammy Jellyfish):**

```bash
sudo tee /etc/apt/mirror.list << 'EOF'
############# config ##################
# Базовый путь для хранения всех файлов зеркала
set base_path    /var/spool/apt-mirror

# Количество потоков для одновременной загрузки
set nthreads     20

# Обработка символа '~' в версиях пакетов
set _tilde       0
############# end config ##############

# Основные репозитории
deb http://archive.ubuntu.com/ubuntu jammy main restricted universe multiverse
deb http://archive.ubuntu.com/ubuntu jammy-updates main restricted universe multiverse
deb http://archive.ubuntu.com/ubuntu jammy-backports main restricted universe multiverse

# Репозиторий безопасности
deb http://security.ubuntu.com/ubuntu jammy-security main restricted universe multiverse

# Очистка устаревших пакетов
clean http://archive.ubuntu.com/ubuntu
clean http://security.ubuntu.com/ubuntu
EOF
```

#### Шаг 3: Синхронизация

```bash
# Первый запуск (может занять длительное время)
sudo apt-mirror

# Проверка результата
ls -la /var/spool/apt-mirror/mirror/

# Размер зеркала
du -sh /var/spool/apt-mirror/
```

#### Шаг 4: Публикация через веб-сервер (Nginx)

```bash
# Создать символическую ссылку
sudo ln -s /var/spool/apt-mirror/mirror/archive.ubuntu.com/ubuntu /var/www/html/ubuntu
sudo ln -s /var/spool/apt-mirror/mirror/security.ubuntu.com/ubuntu /var/www/html/ubuntu-security

# Конфигурация Nginx
sudo tee /etc/nginx/sites-available/repo << 'EOF'
server {
    listen 80;
    server_name mirror.local;
    root /var/www/html;

    location / {
        autoindex on;
        autoindex_format html;
        autoindex_localtime on;
    }

    location ~* \.(deb|gz|xml)$ {
        expires 1h;
        add_header Cache-Control "public, must-revalidate";
    }
}
EOF

sudo ln -s /etc/nginx/sites-available/repo /etc/nginx/sites-enabled/repo
sudo nginx -t && sudo systemctl reload nginx
```

#### Шаг 5: Настройка клиентов

На клиентских машинах отредактировать `/etc/apt/sources.list` или добавить файл в `sources.list.d`:

```bash
echo "deb http://mirror.local/ubuntu jammy main restricted universe multiverse" | \
    sudo tee /etc/apt/sources.list.d/local-mirror.list

sudo apt update
```

#### Шаг 6: Автоматизация обновлений

**Использование Systemd timer:**

```bash
# /etc/systemd/system/apt-mirror.service
[Unit]
Description=APT Mirror Sync

[Service]
Type=oneshot
ExecStart=/usr/bin/apt-mirror

# /etc/systemd/system/apt-mirror.timer
[Unit]
Description=Run apt-mirror daily

[Timer]
OnCalendar=daily
Persistent=true

[Install]
WantedBy=timers.target
```

```bash
sudo systemctl enable --now apt-mirror.timer
```

---

### Сценарий 2: Зеркалирование для изолированной сети (Air-Gapped)

#### Шаг 1: Подготовка съёмного носителя

```bash
# На машине с интернетом
sudo apt-mirror

# Копирование на внешний диск с помощью rsync
EXTERNAL_DISK="/mnt/external-drive"
sudo rsync -av /var/spool/apt-mirror/ $EXTERNAL_DISK/apt-mirror/
```

#### Шаг 2: Развёртывание в изолированной сети

```bash
# На машине в изолированной сети
EXTERNAL_DISK="/mnt/external-drive"
sudo mkdir -p /var/www/html/offline-repo
sudo rsync -av $EXTERNAL_DISK/apt-mirror/ /var/www/html/offline-repo/
```

---

## Дополнительная информация

Подробная информация об оптимизации и мониторинге приведена в документе **[Дополнительная информация](./additional_info.md)**.

### Связанные темы

- **[Приватный APT-репозиторий](../deb_private_apt_repository_reprepro/practical_scenarios.md)** — публикация внутренних .deb-пакетов.
- **[Зеркалирование YUM/DNF](../yum_dnf_repository_mirror.md)** — аналогичный процесс для RPM-экосистемы.
