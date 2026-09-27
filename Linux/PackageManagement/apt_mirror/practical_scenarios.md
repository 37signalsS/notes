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

**Ожидаемый результат:**
```text
# aptly --version
aptly 1.5.0
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

**Ожидаемый результат:**
```text
# aptly mirror list
Mirror noble-main []: http://archive.ubuntu.com/ubuntu/ noble main restricted universe multiverse
...
Downloading http://archive.ubuntu.com/ubuntu/dists/noble/Release to /tmp/aptly-tmp-.../noble/Release
...
```

#### Шаг 3: Фиксация состояния (Snapshot)

Снимки позволяют гарантировать, что все клиенты видят одну и ту же версию пакетов.
```bash
# Создание снимка из зеркала
aptly snapshot create noble-main-snap-$(date +%F) from mirror noble-main
```

**Ожидаемый результат:**
```text
# aptly snapshot list
Snapshots:
 * noble-main-snap-2026-09-13 [noble-main]: 45234 packages
```

#### Шаг 4: Публикация и раздача

```bash
# Публикация снимка
aptly publish snapshot -distribution="noble" noble-main-snap-2026-09-13

# По умолчанию aptly запускает собственный HTTP-сервер для быстрой проверки:
# aptly serve
```

**Ожидаемый результат:**
```text
# aptly publish list
Repository: noble [noble]
  Distribution: noble
  Snapshot: noble-main-snap-2026-09-13
  Prefix: /
  Storage: local
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

3. Проверьте работу:
```bash
apt-get update
apt-get install --dry-run curl
```

**Ожидаемый результат:**
```text
# apt-get update
Hit:1 http://mirror.local/ubuntu noble InRelease
...
Reading package lists... Done

# apt-get install --dry-run curl
NOTE: This is only a simulation!
apt-get needs root privileges for real execution.
Keep also in mind that locking is deactivated,
so don't depend on the relevance to the real current situation!
0 upgraded, 0 newly installed, 0 to remove and 0 not upgraded.
```

#### Валидация и проверка

```bash
# Проверка целостности опубликованных индексов
grep -c '^Package:' /var/www/html/ubuntu/dists/noble/main/binary-amd64/Packages

# Проверка доступности зеркала
curl -sI http://mirror.local/ubuntu/dists/noble/Release | head -5
```

#### Типичные проблемы

| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| **GPG: NO_PUBKEY** | Ключ не добавлен в keyring клиента. | Выполните шаг экспорта ключа на сервере зеркала. |
| **404 на Packages.gz** | Архитектура не включена в зеркало. | Проверьте `dpkg --print-architecture` и архитектуру в конфигурации зеркала. |
| **DB is locked** | Аварийное завершение процесса. | Убедитесь, что процессы aptly не запущены, и удалите `~/.aptly/db/LOCK`. |

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

**Ожидаемый результат:**
```text
# cat /etc/apt/mirror.list | head -10
set base_path    /var/spool/apt-mirror
set nthreads     20
...
```

#### Шаг 2: Синхронизация

```bash
sudo apt-mirror
```

**Ожидаемый результат:**
```text
# sudo apt-mirror
Processing indexes: [R] main [R] restricted [R] universe [R] multiverse
...
Downloading: http://archive.ubuntu.com/ubuntu/pool/main/a/apt/apt_2.6.0_amd64.deb
...
```

#### Шаг 3: Настройка Nginx для раздачи

Создайте конфигурацию в `/etc/nginx/sites-available/apt-mirror`:
```nginx
server {
    listen 80;
    server_name mirror.local;

    location /ubuntu {
        alias /var/spool/apt-mirror/mirror/archive.ubuntu.com/ubuntu;
        autoindex off;
    }
}
```

**Ожидаемый результат:**
```text
# curl -sI http://mirror.local/ubuntu/dists/noble/Release | head -5
HTTP/1.1 200 OK
Server: nginx/1.24.0
...
```

#### Валидация

```bash
# Проверка количества пакетов
grep -c '^Package:' /var/spool/apt-mirror/mirror/archive.ubuntu.com/ubuntu/dists/noble/main/binary-amd64/Packages

# Проверка freshness индексов
stat -c %y /var/spool/apt-mirror/mirror/archive.ubuntu.com/ubuntu/dists/noble/InRelease
```

#### Типичные проблемы

| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| **Hash Sum mismatch** | Индексы upstream обновились во время скачивания. | Запустите синхронизацию повторно. На клиенте можно отключить PDiffs: `Acquire::PDiffs "false";`. |
| **No space left on device** | Исчерпание инодов. | Проверьте `df -i`. Очистите старые пакеты или увеличьте inode ratio. |
| **Слишком медленная синхронизация** | Низкая пропускная способность или большая задержка. | Увеличьте `nthreads` или установите `set bandwidth_limit`. |

---

### Сценарий 3: Работа в изолированной сети (Air-Gapped)

Сценарий «Sneakernet» — перенос обновлений на физическом носителе.

#### Шаг 1: Подготовка на машине с интернетом

Синхронизируйте зеркало и упакуйте данные:
```bash
# Для aptly (рекомендуется использовать rsync для синхронизации каталога ~/.aptly)
rsync -avz ~/.aptly /mnt/external-disk/aptly_backup/
```

**Ожидаемый результат:**
```text
sending incremental file list
./
...
sent 1,234,567 bytes  received 123 bytes  2,469,380.00 bytes/sec
total size is 10,234,567  speedup is 8.29
```

#### Шаг 2: Развертывание в изолированном контуре

1. Подключите диск и восстановите данные.
2. Зарегистрируйте зеркало в локальной инсталляции `aptly`:
```bash
aptly db recover
```
3. Опубликуйте зеркало и настройте Nginx аналогично Сценарию 2.

#### Шаг 3: Обновление изолированного зеркала

Для периодического обновления используйте ту же схему:
1. На машине с интернетом: обновите зеркало, создайте snapshot.
2. Упакуйте изменённые данные через `rsync --link-dest` для экономии места:
```bash
rsync -avz --link-dest=/mnt/external-disk/aptly_backup_latest ~/.aptly /mnt/external-disk/aptly_backup_new
```
3. Перенесите носитель в изолированный контур и замените каталог.

#### Валидация

```bash
# На изолированном сервере
aptly repo list
aptly publish list
curl -sI http://localhost/ubuntu/dists/noble/Release | grep "200 OK"
```

#### Типичные проблемы

| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| **aptly db recover завершается с ошибкой** | База была повреждена при извлечении диска. | Восстановите из предыдущего бэкапа. Включите journaling на файловой системе. |
| **Не хватает места на носителе** | Первое копирование полное, последующие инкрементальные. | Используйте `rsync --link-dest` для дедупликации. |
| **Клиенты не видят новые пакеты** | Забыли перепубликовать snapshot после обновления. | Выполните `aptly publish switch` или обновите симлинк. |

---

### Сценарий 4: Каскадное зеркалирование (Multi-tier)

В распределённых сетях используется схема **Master-Slave**:
- **Master Mirror**: Единственная точка выхода в интернет, синхронизируется с upstream.
- **Regional Mirrors**: Синхронизируются с Master-зеркалом по локальным или выделенным каналам, обслуживая региональные сегменты сети.

#### Шаг 1: Настройка Master Mirror

```bash
# На master-сервере: настройте aptly аналогично Сценарию 1
aptly mirror create noble-main http://archive.ubuntu.com/ubuntu/ noble main restricted universe multiverse
aptly mirror update noble-main
aptly snapshot create noble-main-snap from mirror noble-main
aptly publish snapshot -distribution="noble" noble-main-snap /repo/noble
```

#### Шаг 2: Настройка Regional Mirror

```bash
# На regional-сервере: импортируйте зеркало с master
rsync -avz --delete master.internal:/repo/noble/ /repo/noble/

# Или с использованием aptly API для инкрементального обновления
aptly mirror create noble-main http://master.internal/repo/noble noble main restricted universe multiverse
aptly mirror update noble-main
```

#### Шаг 3: Балансировка нагрузки на клиентах

Настройте DNS Round-Robin или используйте L7-балансировщик (см. Сценарий 7).

#### Валидация

```bash
# На master
aptly publish list

# На regional
curl -sI http://regional.internal/ubuntu/dists/noble/Release | grep "200 OK"

# Проверка синхронизации
diff <(curl -s http://master.internal/ubuntu/dists/noble/Release) <(curl -s http://regional.internal/ubuntu/dists/noble/Release)
```

#### Типичные проблемы

| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| **Regional mirror отстаёт от master** | rsync запущен редко или с ошибками. | Настройте systemd timer с оповещением при сбое. |
| **Разные пакеты на regional и master** | Неполный rsync или прерывание. | Используйте `rsync --checksum` для проверки или `--delete` для синхронизации. |

---

### Сценарий 5: Кэширующий прокси apt-cacher-ng

Для средних сетей (<50 серверов), где полное зеркало избыточно, используйте кэширующий прокси.

#### Шаг 1: Установка и конфигурация

```bash
sudo apt install apt-cacher-ng
```

Конфигурация по умолчанию: `/etc/apt-cacher-ng/acng.conf`.

#### Шаг 2: Настройка клиентов

```bash
# Создание файла /etc/apt/apt.conf.d/99proxy
Acquire::http::Proxy "http://apt-cache.internal:3142";
```

#### Шаг 3: Предзагрузка кэша

```bash
# На прокси-сервере: предзагрузка популярных пакетов
sudo -u apt-cacher-ng /usr/lib/apt-cacher-ng/acngtool preload http://archive.ubuntu.com/ubuntu/dists/noble/main/binary-amd64/Packages.gz
```

#### Валидация

```bash
# Проверка кэша
curl -s http://apt-cache.internal:3142/acng-report.html | head -20

# Проверка hit ratio
grep -o 'Hits: [0-9]*' /var/log/apt-cacher-ng/apt-cacher.log | tail -1
```

#### Типичные проблемы

| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| **Клиенты игнорируют прокси** | Неправильная конфигурация apt.conf.d. | Проверьте `apt-config dump | grep -i proxy`. |
| **Низкий hit ratio** | Кэш слишком мал или неправильные настройки. | Увеличьте `MaxPackages` и `MaxFileSize` в acng.conf. |

---

### Сценарий 6: Частичное зеркалирование с debmirror

Для создания зеркала со сложной фильтрацией пакетов (по зависимостям, секциям) используйте `debmirror`.

#### Шаг 1: Установка

```bash
sudo apt install debmirror
```

#### Шаг 2: Создание конфигурации

```bash
sudo tee /etc/debmirror.conf << 'EOF'
set base_path /var/spool/debmirror
set nthreads 20
set download_queues 3

# Фильтры
set filterpolicy default
set filter  install status
set filter  status
set filter  origin
EOF
```

#### Шаг 3: Синхронизация с фильтрацией

```bash
sudo debmirror --verbose \
  --host=archive.ubuntu.com \
  --root=/ubuntu \
  --dist=noble \
  --arch=amd64 \
  --section=main,restricted \
  --passive \
  /var/spool/debmirror/ubuntu
```

#### Валидация

```bash
# Проверка количества пакетов
find /var/spool/debmirror/ubuntu/pool -name '*.deb' | wc -l

# Проверка индексов
grep -c '^Package:' /var/spool/debmirror/ubuntu/dists/noble/main/binary-amd64/Packages
```

#### Типичные проблемы

| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| **Отсутствуют нужные пакеты** | Слишком строгий фильтр. | Проверьте `--section` и `--arch`. |
| **Слишком медленно** | Мало потоков. | Увеличьте `--nthreads`. |

---

### Сценарий 7: Публикация через HAProxy с health checks

Для инфраструктур с 100+ серверов используйте L7-балансировщик с health checks.

#### Шаг 1: Конфигурация HAProxy

```text
# /etc/haproxy/haproxy.cfg
frontend apt_frontend
    bind *:80
    default_backend apt_backend

backend apt_backend
    balance roundrobin
    option httpchk GET /ubuntu/dists/noble/Release
    server mirror-01 10.0.1.10:80 check fall 3 rise 2
    server mirror-02 10.0.1.20:80 check fall 3 rise 2
```

#### Шаг 2: Применение конфигурации

```bash
sudo systemctl reload haproxy
```

#### Шаг 3: Настройка клиентов

```text
# /etc/apt/sources.list.d/local-mirror.sources
Types: deb
URIs: http://haproxy.internal/ubuntu
Suites: noble
Components: main restricted universe multiverse
Signed-By: /etc/apt/keyrings/local-mirror.gpg
```

#### Валидация

```bash
# Проверка статуса backend
echo "show stat" | socat /var/run/haproxy.sock stdio | grep apt_backend

# Проверка доступности
curl -sI http://haproxy.internal/ubuntu/dists/noble/Release | grep "200 OK"
```

#### Типичные проблемы

| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| **Клиенты получают 503** | Все бэкенды unhealthy. | Проверьте `curl` с бэкендов и настройки `httpchk`. |
| **Медленный failover** | Большой `fall` или `inter`. | Уменьшите `fall` до 2–3 проверок. |

---

### Сценарий 8: Использование apt-offline для air-gapped обновления отдельных пакетов

Когда полное зеркало недоступно, используйте `apt-offline` для загрузки отдельных пакетов.

#### Шаг 1: Генерация сигнатуры на изолированной машине

```bash
sudo apt install apt-offline
apt-offline set ~/apt-offline.sig --update --upgrade --install-packages vim curl
```

#### Шаг 2: Скачивание пакетов на машине с интернетом

```bash
apt-offline get ~/apt-offline.sig --bundle ~/apt-offline.zip
```

#### Шаг 3: Установка на изолированной машине

```bash
apt-offline install ~/apt-offline.zip
```

#### Валидация

```bash
# Проверка установки
dpkg -l vim curl | grep '^ii'
```

#### Типичные проблемы

| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| **Signature mismatch** | Файл изменён при переносе. | Проверьте целостность носителя (`sha256sum`). |
| **Зависимости не загружаются** | Сигнатура создана без флага `--install-packages`. | Пересоздайте сигнатуру с указанием пакетов. |

---

### Сценарий 9: Настройка APT Pinning для приоритизации локального зеркала

Используйте `preferences` для управления приоритетами источников. Подробное руководство по настройке Pinning, включая примеры конфигурации и отладку, см. в документе **[Apt Pinning](../deb_apt_pinning.md)**.

---

### Сценарий 10: Автоматическая верификация целостности зеркала

Настройте регулярные проверки, чтобы убедиться, что зеркало соответствует upstream.

#### Шаг 1: Создание скрипта проверки

```bash
#!/bin/bash
# /usr/local/bin/apt-mirror-verify.sh
set -euo pipefail

LOCAL_RELEASE="/var/www/html/ubuntu/dists/noble/Release"
UPSTREAM_RELEASE="http://archive.ubuntu.com/ubuntu/dists/noble/Release"

# Проверка доступности
if ! curl -sfI "$UPSTREAM_RELEASE" >/dev/null; then
    echo "ERROR: upstream unreachable"
    exit 1
fi

# Сравнение хэш-сумм Release файлов
LOCAL_HASH=$(grep '^SHA256:' "$LOCAL_RELEASE" | head -1 | awk '{print $2}')
UPSTREAM_HASH=$(curl -s "$UPSTREAM_RELEASE" | grep '^SHA256:' | head -1 | awk '{print $2}')

if [ "$LOCAL_HASH" != "$UPSTREAM_HASH" ]; then
    echo "ERROR: Release hash mismatch"
    exit 1
fi

# Проверка количества пакетов
LOCAL_COUNT=$(grep -c '^Package:' /var/www/html/ubuntu/dists/noble/main/binary-amd64/Packages)
UPSTREAM_COUNT=$(curl -s http://archive.ubuntu.com/ubuntu/dists/noble/main/binary-amd64/Packages.gz | zgrep -c '^Package:')

if [ "$LOCAL_COUNT" -lt "$UPSTREAM_COUNT" ]; then
    echo "ERROR: package count mismatch (local=$LOCAL_COUNT, upstream=$UPSTREAM_COUNT)"
    exit 1
fi

echo "OK: mirror is consistent"
```

#### Шаг 2: Настройка systemd timer

```ini
# /etc/systemd/system/apt-mirror-verify.service
[Unit]
Description=Verify APT mirror integrity

[Service]
Type=oneshot
ExecStart=/usr/local/bin/apt-mirror-verify.sh
```

```ini
# /etc/systemd/system/apt-mirror-verify.timer
[Unit]
Description=Run mirror verification daily

[Timer]
OnCalendar=daily
Persistent=true

[Install]
WantedBy=timers.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now apt-mirror-verify.timer
```

#### Валидация

```bash
# Ручной запуск
sudo systemctl start apt-mirror-verify.service
sudo systemctl status apt-mirror-verify.service

# Проверка логов
journalctl -u apt-mirror-verify -n 20
```

#### Типичные проблемы

| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| **False positive: hash mismatch** | Upstream обновил Release во время проверки. | Запускайте проверку после завершения синхронизации. |
| **Скрипт зависает** | upstream не отвечает. | Добавьте `timeout` в `curl`. |

---

### Сценарий 11: Откат (Rollback) после проблемного обновления

Если обновление зеркала привело к проблемам (сломанные пакеты, несовместимость), используйте snapshot для быстрого отката.

#### Шаг 1: Определение проблемного snapshot

```bash
# Просмотр списка snapshot
aptly snapshot list

# Проверка, какой snapshot был опубликован
aptly publish list
```

#### Шаг 2: Откат на предыдущий snapshot

```bash
# Переключение на предыдущий snapshot
aptly publish switch noble noble-main-snap-2026-09-12
```

**Ожидаемый результат:**
```text
# aptly publish list
Repository: noble [noble]
  Distribution: noble
  Snapshot: noble-main-snap-2026-09-12
```

#### Шаг 3: Удаление проблемного snapshot

```bash
aptly snapshot drop noble-main-snap-2026-09-13
aptly db cleanup
```

#### Валидация

```bash
# Проверка, что клиенты получают старые пакеты
apt-get install --dry-run vim
apt-cache policy vim
```

#### Типичные проблемы

| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| **Откат не помогает** | Проблема не в пакетах, а в конфигурации. | Проверьте конфигурацию Nginx/aptly. |
| **Потерян предыдущий snapshot** | Не было резервного snapshot. | Настройте автоматическое создание snapshot перед обновлением (см. additional_info). |

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
- **[Apt Pinning](../deb_apt_pinning.md)** — управление приоритетами источников.
