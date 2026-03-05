# Зеркалирование APT: Практические сценарии

## Сценарий 1: Создание зеркала для APT (Debian/Ubuntu)

### Шаг 1: Установка

```bash
sudo apt update
sudo apt install apt-mirror apache2
```

### Шаг 2: Настройка `apt-mirror`

Конфигурационный файл `/etc/apt/mirror.list` определяет скачиваемые репозитории, компоненты и архитектуры.

**Пример конфигурации для Ubuntu 22.04 (Jammy Jellyfish):**

```bash
sudo tee /etc/apt/mirror.list << 'EOF'
############# config ##################
# Базовый путь для хранения всех файлов зеркала
set base_path    /var/spool/apt-mirror

# Путь к зеркалу (пакеты)
# set mirror_path  $base_path/mirror

# Путь для временных файлов
# set skel_path    $base_path/skel

# Путь для логов и переменных данных
# set var_path     $base_path/var

# Количество потоков для одновременной загрузки
set nthreads     20

# Обработка символа '~' в версиях пакетов
set _tilde       0

############# end config ##############

# Репозитории для зеркалирования
# Формат: deb <URL> <дистрибутив> <компоненты>

# Основные репозитории
deb http://archive.ubuntu.com/ubuntu jammy main restricted universe multiverse
deb http://archive.ubuntu.com/ubuntu jammy-updates main restricted universe multiverse
deb http://archive.ubuntu.com/ubuntu jammy-backports main restricted universe multiverse

# Репозиторий безопасности
deb http://security.ubuntu.com/ubuntu jammy-security main restricted universe multiverse

# Исходные коды (опционально, требует deb-src)
# deb-src http://archive.ubuntu.com/ubuntu jammy main restricted universe multiverse

# Очистка устаревших пакетов
clean http://archive.ubuntu.com/ubuntu
clean http://security.ubuntu.com/ubuntu
EOF
```

**Для Debian 12 (Bookworm):**

```bash
sudo tee /etc/apt/mirror.list << 'EOF'
set base_path    /var/spool/apt-mirror
set nthreads     20

deb http://deb.debian.org/debian bookworm main contrib non-free non-free-firmware
deb http://deb.debian.org/debian bookworm-updates main contrib non-free non-free-firmware
deb http://security.debian.org/debian-security bookworm-security main contrib non-free non-free-firmware

clean http://deb.debian.org/debian
clean http://security.debian.org/debian-security
EOF
```

### Шаг 3: Синхронизация

```bash
# Первый запуск (может занять длительное время)
sudo apt-mirror

# Проверка результата
ls -la /var/spool/apt-mirror/mirror/

# Размер зеркала
du -sh /var/spool/apt-mirror/
```

**Время синхронизации:**

- **Первая синхронизация:** 1-4 часа (зависит от скорости интернета и размера репо)
- **Последующие обновления:** 10-30 минут

### Шаг 4: Публикация через веб-сервер

**Nginx:**

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

    # Кэширование для клиентов
    location ~* \.(deb|gz|xml)$ {
        expires 1h;
        add_header Cache-Control "public, must-revalidate";
    }
}
EOF

sudo ln -s /etc/nginx/sites-available/repo /etc/nginx/sites-enabled/repo
sudo nginx -t && sudo systemctl reload nginx
```

**Apache:**

```bash
# Включить модуль автоиндекса
sudo a2enmod autoindex

# Создать символическую ссылку
sudo ln -s /var/spool/apt-mirror/mirror/archive.ubuntu.com/ubuntu /var/www/html/ubuntu

# Перезапустить Apache
sudo systemctl reload apache2
```

### Шаг 5: Настройка клиентов

На клиентских машинах отредактировать `/etc/apt/sources.list`:

```bash
# /etc/apt/sources.list
deb http://mirror.local/ubuntu jammy main restricted universe multiverse
deb http://mirror.local/ubuntu jammy-updates main restricted universe multiverse
deb http://mirror.local/ubuntu jammy-security main restricted universe multiverse
deb http://mirror.local/ubuntu jammy-backports main restricted universe multiverse
```

Или создать отдельный файл:

```bash
echo "deb http://mirror.local/ubuntu jammy main restricted universe multiverse" | \
    sudo tee /etc/apt/sources.list.d/local-mirror.list

sudo apt update
```

### Шаг 6: Автоматизация обновлений

**Cron (ежедневное обновление):**

```bash
# /etc/cron.daily/apt-mirror
#!/bin/bash
/usr/bin/apt-mirror > /var/log/apt-mirror.log 2>&1
```

```bash
sudo chmod +x /etc/cron.daily/apt-mirror
```

**Systemd timer:**

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

## Сценарий 2: Зеркалирование для изолированной сети (Air-Gapped)

### Шаг 1: Подготовка съёмного носителя

```bash
# На машине с интернетом
sudo apt-mirror

# Копирование на внешний диск
EXTERNAL_DISK="/mnt/external-drive"
sudo rsync -av /var/spool/apt-mirror/ $EXTERNAL_DISK/apt-mirror/
```

### Шаг 2: Развёртывание в изолированной сети

```bash
# На машине в изолированной сети
EXTERNAL_DISK="/mnt/external-drive"
sudo mkdir -p /var/www/html/offline-repo
sudo rsync -av $EXTERNAL_DISK/apt-mirror/ /var/www/html/offline-repo/

# Настройка веб-сервера (как выше)
```

### Шаг 3: Использование без веб-сервера (локальный путь)

```bash
# /etc/apt/sources.list.d/offline.list
deb file:///var/www/html/offline-repo/ubuntu jammy main restricted universe multiverse

sudo apt update
```

---

## Связанные документы

- **[Определения](./definitions.md)** — базовые термины
- **[Основные понятия](./basic_concepts.md)** — назначение, архитектура, инструменты
- **[Дополнительная информация](./additional_info.md)** — оптимизация, мониторинг, проблемы

---

*Этот файл является частью декомпозированной документации. Исходный файл: [apt_repository_mirror.md](../apt_repository_mirror.md)*
