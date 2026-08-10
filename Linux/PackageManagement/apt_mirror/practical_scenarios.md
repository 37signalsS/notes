# Зеркалирование APT: Практические сценарии

## Определения

Определения терминов (Aptly, Snapshot, Upstream, DEB822) приведены в документе **[Определения](./definitions.md)**. Система APT является основным инструментом управления пакетами в дистрибутивах на базе Debian и Ubuntu.

---

## Основные концепции

Обзор архитектуры, сравнение инструментов и жизненный цикл зеркала доступны в файле **[Основные понятия](./basic_concepts.md)**.

---

## Практические сценарии

### Сценарий 1: Создание зеркала с помощью aptly (рекомендуется)

`aptly` — современный стандарт для управления зеркалами. Он поддерживает снимки (Snapshots), что позволяет фиксировать состояние репозитория и безопасно тестировать обновления.

#### Шаг 1: Установка и инициализация
```bash
sudo apt update && sudo apt install aptly

# Конфигурация по умолчанию хранится в ~/.aptly.conf.
# Основные данные (пакеты и БД) — в директории ~/.aptly/
```

#### Шаг 2: Создание зеркала
На примере **Ubuntu 24.04 (Noble Numbat)**:
```bash
# Добавление зеркала (только метаданные)
aptly mirror create noble-main http://archive.ubuntu.com/ubuntu/ noble main restricted universe multiverse

# Импорт GPG-ключа репозитория (необходим для проверки подлинности)
# Для Ubuntu:
gpg --no-default-keyring --keyring /usr/share/keyrings/ubuntu-archive-keyring.gpg --export | aptly keyring add -

# Обновление зеркала (загрузка пакетов — может занять много времени)
aptly mirror update noble-main
```

#### Шаг 3: Фиксация состояния (Snapshot)
Снимки позволяют гарантировать, что все клиенты видят одну и ту же версию пакетов.
```bash
# Создание снимка из зеркала
aptly snapshot create noble-main-snap-$(date +%F) from mirror noble-main
```

#### Шаг 4: Публикация и раздача
```bash
# Публикация снимка
aptly publish snapshot -distribution="noble" noble-main-snap-2026-07-27

# По умолчанию aptly запускает собственный HTTP-сервер для быстрой проверки:
# aptly serve
```

#### Шаг 5: Настройка клиента (Формат DEB822)
В современных ОС (Ubuntu 24.04+) рекомендуется использовать формат `.sources`.

1. Экспортируйте ключ для клиента:
```bash
aptly keyring export > /etc/apt/keyrings/local-mirror.gpg
```

2. Создайте файл `/etc/apt/sources.list.d/local-mirror.sources`:
```text
Types: deb
URIs: http://mirror.local/ubuntu
Suites: noble
Components: main restricted universe multiverse
Signed-By: /etc/apt/keyrings/local-mirror.gpg
```

---

### Сценарий 2: Использование apt-mirror (Classic)

Классический инструмент для синхронизации «один-в-один». Подходит для простых задач, где не требуется управление снимками.

#### Шаг 1: Настройка конфигурации
```bash
sudo tee /etc/apt/mirror.list << 'EOF'
set base_path    /var/spool/apt-mirror
set nthreads     20
set _tilde       0

# Репозитории для зеркалирования
deb http://archive.ubuntu.com/ubuntu noble main restricted universe multiverse
deb http://archive.ubuntu.com/ubuntu noble-updates main restricted universe multiverse
deb http://security.ubuntu.com/ubuntu noble-security main restricted universe multiverse

# Очистка старых пакетов
clean http://archive.ubuntu.com/ubuntu
clean http://security.ubuntu.com/ubuntu
EOF
```

#### Шаг 2: Синхронизация
```bash
sudo apt-mirror
```

#### Шаг 3: Настройка Nginx для раздачи
Создайте конфигурацию в `/etc/nginx/sites-available/apt-mirror`:
```nginx
server {
    listen 80;
    server_name mirror.local;

    location /ubuntu {
        alias /var/spool/apt-mirror/mirror/archive.ubuntu.com/ubuntu;
        autoindex on;
    }
}
```

---

### Сценарий 3: Работа в изолированной сети (Air-Gapped)

Сценарий «Sneakernet» — перенос обновлений на физическом носителе.

#### Шаг 1: Подготовка на машине с интернетом
Синхронизируйте зеркало и упакуйте данные:
```bash
# Для aptly (рекомендуется использовать rsync для синхронизации каталога ~/.aptly)
rsync -avz ~/.aptly /mnt/external-disk/aptly_backup/
```

#### Шаг 2: Развертывание в изолированном контуре
1. Подключите диск и восстановите данные.
2. Зарегистрируйте зеркало в локальной инсталляции `aptly`:
```bash
aptly db recover
```
3. Опубликуйте зеркало и настройте Nginx аналогично Сценарию 2.

---

## Дополнительная информация

### Автоматизация через systemd
Использование таймеров systemd надежнее, чем классический `cron`.

```ini
# /etc/systemd/system/aptly-sync.service
[Unit]
Description=Update aptly mirror and publish
After=network.target

[Service]
Type=oneshot
ExecStart=/usr/bin/aptly mirror update noble-main
ExecStartPost=/usr/bin/aptly snapshot create noble-snap-latest from mirror noble-main
ExecStartPost=/usr/bin/aptly publish switch noble noble-snap-latest
```

### Связанные документы
- **[Дополнительная информация](./additional_info.md)** — расчет дискового пространства, мониторинг и решение проблем.
- **[Приватный APT-репозиторий](../deb_private_apt_repository_reprepro/practical_scenarios.md)** — создание и подпись собственных пакетов.
- **[Nginx: Настройка репозитория](../../../WebServers/Nginx/Scenarios/secure_apt_repository_guide.md)** — конфигурация безопасной раздачи через mTLS.
- **[Управление репозиториями DEB](../deb_repositories_sources_list.md)** — подробнее о форматах `sources.list` и DEB822.
