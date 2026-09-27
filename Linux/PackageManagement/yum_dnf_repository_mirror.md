# Зеркалирование YUM/DNF-репозиториев

## Определения

Ниже приведены основные термины, используемые в процессе создания локальных копий репозиториев для систем на базе RPM (Red Hat Package Manager).

**Локальное зеркало (Local Mirror)** — полная или частичная копия удалённого репозитория пакетов, размещённая в локальной сети или на изолированном сервере. Позволяет экономить внешний трафик, ускорять установку и обеспечивать доступ к ПО в закрытых контурах (Air-Gapped).

**Репозиторий-источник (Upstream Repository)** — официальный или доверенный удалённый сервер (например, зеркала AlmaLinux, Rocky Linux или Fedora), с которым выполняется синхронизация.

**Синхронизация (Synchronization)** — процесс приведения локального зеркала в соответствие с источником. Включает загрузку новых пакетов (`.rpm`), дельта-пакетов (`.drpm`) и метаданных.

**Метаданные репозитория** — набор файлов, описывающих содержимое репозитория. В современных дистрибутивах (DNF 4+) метаданные хранятся в формате SQLite, в устаревших — в XML.
- `repomd.xml` — индексный файл, содержащий хеши и пути ко всем остальным метаданным.
- `primary.xml` / `primary.sqlite` — список пакетов и их базовых свойств (имя, версия, архитектура, зависимости).
- `filelists.xml` / `filelists.sqlite` — списки файлов, входящих в каждый пакет.
- `other.xml` — changelog и другая дополнительная информация.
- `comps.xml` — описание логических групп пакетов (например, "Development Tools").
- `modules.yaml` — описание модульных потоков (специфично для AppStream).
- `updateinfo.xml` — информация об обновлениях безопасности и исправлениях (errata).

**Дельта-пакет (Delta RPM / DRPM)** — сжатый пакет, содержащий только изменения между двумя версиями пакета. Позволяет сократить объём загрузки на 60–90% при обновлении небольших исправлений. Требует плагина `deltarpm` на стороне клиента. В DNF 5 поддержка DRPM удалена из соображений производительности.

**Модульный поток (Module Stream)** — версия пакета или набора пакетов в репозитории AppStream. Например, `nodejs:18` и `nodejs:20` — разные потоки одного модуля. Клиент может активировать только один поток за раз.

**GPG-подпись репозитория** — цифровая подпись файла `repomd.xml` (обычно `repomd.xml.asc`). Гарантирует, что метаданные не были подменены в пути от источника до клиента. Включает `repo_gpgcheck` (проверка подписи метаданных) и `gpgcheck` (проверка подписи каждого `.rpm`).

**Reposync** — плагин DNF для односторонней синхронизации репозитория. Поддерживает фильтрацию по архитектуре, пакетам, группам, загрузку дельта-пакетов и инкрементальное обновление.

**Createrepo_c** — утилита для генерации файлов метаданных (`repodata/`) в локальном каталоге. Реализация на C, совместимая с форматом DNF 4/5 и поддерживающая сжатие Zstd.

**Metalsink / Mirrorlist** — механизмы динамического выбора зеркал.
- **Mirrorlist**: Возвращает простой список URL зеркал.
- **Metalink**: Возвращает XML-файл с метаданными о зеркалах, включая контрольные суммы и приоритеты, что обеспечивает более надёжный выбор.

**Snapshot** — неизменяемая копия репозитория, зафиксированная в определённый момент времени. Используется для обеспечения воспроизводимости сборок и аудита изменений.

---

## Основные концепции

### Назначение зеркалирования

Использование локальных зеркал для пакетных менеджеров DNF (Dandified YUM) и YUM (Yellowdog Updater, Modified) необходимо для решения следующих задач:

- **Ускорение обновлений**: Передача данных в локальной сети (1–40 Gbps) исключает задержки WAN-каналов.
- **Инфраструктура Air-Gapped**: Обеспечение работы систем в изолированных сегментах без прямого выхода в интернет.
- **Воспроизводимость (Snapshotting)**: Возможность заморозки состояния репозитория на определённую дату для обеспечения идентичности окружений разработки, тестирования и эксплуатации.
- **Снижение нагрузки на upstream**: Собственное зеркало уменьшает количество запросов к публичным серверам (например, mirrors.fedoraproject.org).

### Архитектура процесса (DNF Reposync)

В современных дистрибутивах (RHEL 8/9, Fedora 35+) утилита `reposync` интегрирована как плагин DNF. Процесс включает:

1.  **Загрузка (reposync)**: Скачивание RPM-пакетов и метаданных. Важно использовать флаг `--download-metadata` для сохранения оригинальных подписей метаданных и модульных данных. Флаг `--downloadcomps` загружает файл групп `comps.xml`.
2.  **Индексация (createrepo_c)**: Генерация файлов индексов. `createrepo_c` (реализация на C) значительно быстрее классического `createrepo` на Python. Современные версии используют сжатие Zstd по умолчанию.
3.  **Публикация**: Предоставление доступа по протоколу HTTP/HTTPS через Nginx, Apache или Caddy. Рекомендуется HTTPS с валидным сертификатом для production.

### Метаданные репозитория

DNF работает с кэшем метаданных в `/var/cache/dnf/<repo_id>*/`. При первом обращении к репозиторию DNF скачивает `repomd.xml`, проверяет его подпись (`repo_gpgcheck`), затем загружает остальные индексы.

В DNF 4+ метаданные преобразуются в SQLite-базу (`primary.sqlite`, `filelists.sqlite`, `other.sqlite`) для ускорения поиска. YUM использовал только XML, что требовало полной загрузки файлов в память.

**Ключевые флаги reposync для метаданных:**
- `--download-metadata`: Копирует `repodata/` из источника, сохраняя оригинальные подписи.
- `--downloadcomps`: Загружает `comps.xml` для поддержки `dnf group install`.
- `--delete-after`: Удаляет RPM-файлы после индексации (экономит место на диске, если не требуется хранить пакеты).

### Особенности AppStream и модульности

Репозитории типа `AppStream` содержат метаданные модулей (`modules.yaml` или `modules.yaml.zstd`).
- При использовании `dnf reposync --download-metadata` метаданные модулей копируются автоматически.
- Если метаданные создаются вручную через `createrepo_c`, модули будут потеряны, если не передать файл модулей через флаг `--package-module-dict`.
- Для поддержки модулей в кастомном репозитории используйте команду `modifyrepo_c --mdtype=modules modules.yaml /var/www/html/repo/x86_64/repodata/`.

### Безопасность и аутентификация

Целостность зеркала обеспечивается на двух уровнях:
1. **GPG-подпись метаданных** (`repo_gpgcheck=1`): Проверяет подпись `repomd.xml`. Защищает от подмены списка пакетов.
2. **GPG-подпись пакетов** (`gpgcheck=1`): Проверяет подпись каждого `.rpm` перед установкой.

Для подписания кастомного репозитория:
```bash
# Подпись индекса репозитория
gpg --detach-sign --armor repodata/repomd.xml

# Подпись пакетов (опционально)
rpmsign --addsign /var/www/html/repo/x86_64/Packages/*.rpm
```

### Оптимизация хранилища

Для больших зеркал (десятки/сотни GB) используйте:
- **Жёсткие ссылки (hardlinks)**: `reposync` автоматически использует hardlinks при повторной синхронизации с `--delete`, экономя место.
- **Zstd-сжатие метаданных**: `createrepo_c --general-compress-type zstd` даёт лучшее сжатие по сравнению с xz/gzip.
- **Zchunk-дельты метаданных**: `createrepo_c --zchunk` создаёт дельта-файлы для индексов, что ускоряет обновление клиентов.
- **Отдельный раздел**: Выделяйте под зеркало отдельный LVM-том или раздел с XFS/EXT4 для предотвращения остановки сервисов при заполнении диска.

---

## Практические сценарии

### Сценарий 1: Создание полного зеркала AlmaLinux 9 / RHEL 9

#### 1. Подготовка инструментария

```bash
# Установка необходимых утилит и веб-сервера
sudo dnf install dnf-plugins-core createrepo_c nginx
```

#### 2. Синхронизация репозитория

```bash
# Создание структуры каталогов
sudo mkdir -p /var/www/html/repos/alma9/{baseos,appstream}

# Синхронизация BaseOS (только актуальные версии, x86_64)
sudo dnf reposync \
    --repoid=baseos \
    --download-path=/var/www/html/repos/alma9 \
    --newest-only \
    --delete \
    --download-metadata \
    --arch=x86_64

# Синхронизация AppStream с группами и модулями
sudo dnf reposync \
    --repoid=appstream \
    --download-path=/var/www/html/repos/alma9 \
    --newest-only \
    --delete \
    --download-metadata \
    --downloadcomps \
    --arch=x86_64
```

#### 3. Индексация и подпись

```bash
# Генерация/обновление индексов (Zstd + группы)
sudo createrepo_c \
    --update \
    --general-compress-type zstd \
    --groupfile /var/www/html/repos/alma9/appstream/comps.xml \
    /var/www/html/repos/alma9/baseos

sudo createrepo_c \
    --update \
    --general-compress-type zstd \
    --groupfile /var/www/html/repos/alma9/appstream/comps.xml \
    /var/www/html/repos/alma9/appstream

# Подпись индексов (если требуется для клиентов с repo_gpgcheck)
cd /var/www/html/repos/alma9/baseos && gpg --detach-sign --armor repodata/repomd.xml
cd /var/www/html/repos/alma9/appstream && gpg --detach-sign --armor repodata/repomd.xml
```

#### 4. Настройка публикации (Nginx)

```nginx
# /etc/nginx/conf.d/repo.conf
server {
    listen 80;
    server_name repo.internal.local;
    root /var/www/html/repos;

    location / {
        autoindex on;        # Разрешить листинг файлов
        autoindex_exact_size off;
        autoindex_localtime on;
    }
}
```

---

### Сценарий 2: Создание частичного зеркала (фильтрация)

Для экономии дискового пространства зеркалируйте только нужные архитектуры или группы пакетов.

```bash
# Синхронизация только архитектуры x86_64, без i686 и aarch64
sudo dnf reposync \
    --repoid=baseos \
    --download-path=/var/www/html/repos/alma9 \
    --newest-only \
    --delete \
    --download-metadata \
    --arch=x86_64

# Исключение определённых пакетов (например, ядер для несуществующих конфигураций)
sudo dnf reposync \
    --repoid=baseos \
    --download-path=/var/www/html/repos/alma9 \
    --newest-only \
    --delete \
    --download-metadata \
    --exclude="kernel-debug*"

# Синхронизация только определённых групп (требует --downloadcomps)
sudo dnf reposync \
    --repoid=appstream \
    --download-path=/var/www/html/repos/alma9 \
    --newest-only \
    --delete \
    --download-metadata \
    --downloadcomps \
    --arch=x86_64
# После синхронизации удалите ненужные пакеты, не входящие в требуемые группы
```

---

### Сценарий 3: Зеркало только обновлений безопасности

Для создания облегчённого зеркала с исправлениями CVE используйте фильтрацию по репозиториям.

```bash
# Создание отдельного каталога для security-updates
sudo mkdir -p /var/www/html/repos/alma9/security

# Синхронизация репозитория обновлений (не BaseOS/AppStream)
sudo dnf reposync \
    --repoid=almalinux-baseos-updates \
    --download-path=/var/www/html/repos/alma9/security \
    --newest-only \
    --delete \
    --download-metadata \
    --arch=x86_64

sudo dnf reposync \
    --repoid=almalinux-appstream-updates \
    --download-path=/var/www/html/repos/alma9/security \
    --newest-only \
    --delete \
    --download-metadata \
    --downloadcomps \
    --arch=x86_64

# Индексация
sudo createrepo_c --update /var/www/html/repos/alma9/security
```

---

### Сценарий 4: Использование зеркала на клиентах

Настройка клиента для работы с локальным источником.

```ini
# /etc/yum.repos.d/local-mirror.repo
[local-baseos]
name=Local AlmaLinux 9 BaseOS
baseurl=http://repo.internal.local/alma9/baseos/
enabled=1
gpgcheck=1
gpgkey=http://repo.internal.local/alma9/RPM-GPG-KEY-AlmaLinux-9

[local-appstream]
name=Local AlmaLinux 9 AppStream
baseurl=http://repo.internal.local/alma9/appstream/
enabled=1
gpgcheck=1
gpgkey=http://repo.internal.local/alma9/RPM-GPG-KEY-AlmaLinux-9
priority=1

# Отключение upstream при использовании только локального зеркала
[almalinux-baseos]
name=AlmaLinux BaseOS
baseurl=https://repo.almalinux.org/almalinux/9/BaseOS/$basearch/os/
enabled=0

[almalinux-appstream]
name=AlmaLinux AppStream
baseurl=https://repo.almalinux.org/almalinux/9/AppStream/$basearch/os/
enabled=0
```

**Валидация клиента:**
```bash
# Проверка конфигурации
sudo dnf repolist

# Обновление только из локального зеркала
sudo dnf upgrade --disablerepo="*" --enablerepo="local-baseos,local-appstream"

# Проверка доступности конкретного пакета
dnf list nginx --disablerepo="*" --enablerepo="local-baseos,local-appstream"
```

---

### Сценарий 5: Автоматизация через systemd timer

Использование таймеров обеспечивает надёжное обновление по расписанию с обработкой зависимостей сервисов.

```ini
# /etc/systemd/system/repo-sync.service
[Unit]
Description=RPM Repository Synchronization Service
After=network-online.target
Wants=network-online.target

[Service]
Type=oneshot
User=nginx
Group=nginx
ExecStartPre=/usr/bin/dnf makecache --timer
ExecStart=/usr/bin/dnf reposync --repoid=baseos --download-path=/var/www/html/repos/alma9 --newest-only --delete --download-metadata --downloadcomps
ExecStart=/usr/bin/dnf reposync --repoid=appstream --download-path=/var/www/html/repos/alma9 --newest-only --delete --download-metadata --downloadcomps
# Обновление индексов только если это необходимо (инкрементально)
ExecStartPost=/usr/bin/createrepo_c --update --general-compress-type zstd /var/www/html/repos/alma9/baseos
ExecStartPost=/usr/bin/createrepo_c --update --general-compress-type zstd /var/www/html/repos/alma9/appstream

[Install]
WantedBy=multi-user.target
```

```ini
# /etc/systemd/system/repo-sync.timer
[Unit]
Description=Run RPM Repo Sync Daily
Requires=repo-sync.service

[Timer]
OnCalendar=*-*-* 03:00:00
Persistent=true

[Install]
WantedBy=timers.target
```

**Управление:**
```bash
# Активация таймера
sudo systemctl daemon-reload
sudo systemctl enable --now repo-sync.timer

# Проверка статуса
sudo systemctl list-timers repo-sync.timer

# Принудительный запуск
sudo systemctl start repo-sync.service
```

---

### Сценарий 6: Проверка целостности зеркала

Для уверенности, что зеркало не повреждено и полностью соответствует источнику, используйте следующие методы.

```bash
# 1. Проверка наличия repomd.xml и подписи
curl -s http://repo.internal.local/alma9/baseos/repodata/repomd.xml | head
gpg --verify repodata/repomd.xml.asc repodata/repomd.xml

# 2. Проверка на отсутствие битых ссылок в индексах
sudo dnf repoclosure --repoid=local-baseos --repofrompath="local-baseos,http://repo.internal.local/alma9/baseos/"

# 3. Проверка целостности метаданных
sudo dnf check-update --disablerepo="*" --enablerepo="local-baseos,local-appstream"

# 4. Сравнение количества пакетов с upstream
echo "Local baseos packages:"
curl -s http://repo.internal.local/alma9/baseos/repodata/primary.xml.gz | gunzip -c | grep -c "<package>"
echo "Upstream baseos packages:"
curl -s https://repo.almalinux.org/almalinux/9/BaseOS/x86_64/os/repodata/primary.xml.gz | gunzip -c | grep -c "<package>"

# 5. Проверка контрольных sums пакетов (сравнение с upstream)
sudo dnf repoquery --disablerepo="*" --enablerepo="local-baseos" --queryformat "%{name}-%{epoch}:%{version}-%{release}.%{arch} %{pkgid}\n" > /tmp/local-pkgs.txt
curl -s https://repo.almalinux.org/almalinux/9/BaseOS/x86_64/os/repodata/primary.xml.gz | gunzip -c | grep -oP 'pkgid="[^"]+"' | sed 's/pkgid="//;s/"$//' | sort > /tmp/upstream-pkgs.txt
diff /tmp/local-pkgs.txt /tmp/upstream-pkgs.txt
```

---

### Сценарий 7: Зеркало через корпоративный прокси

Для серверов без прямого выхода в интернет настройте прокси для `reposync`.

```bash
# Экспорт переменных прокси для текущей сессии
export http_proxy=http://proxy.internal.local:3128
export https_proxy=http://proxy.internal.local:3128
export no_proxy=localhost,127.0.0.1,.internal.local

# Синхронизация с использованием прокси
sudo -E dnf reposync \
    --repoid=baseos \
    --download-path=/var/www/html/repos/alma9 \
    --newest-only \
    --delete \
    --download-metadata \
    --arch=x86_64

# Для постоянной настройки добавьте в /etc/dnf/dnf.conf
sudo tee -a /etc/dnf/dnf.conf <<EOF

[main]
proxy=http://proxy.internal.local:3128
proxy_username=
proxy_password=
EOF
```

**Serving via HTTPS (Nginx + Let's Encrypt или самоподписанный CA):**
```bash
# Самоподписанный CA для внутреннего использования
openssl req -x509 -newkey rsa:4096 -keyout /etc/ssl/private/mirror.key -out /etc/ssl/certs/mirror.crt -days 3650 -nodes

# Nginx конфигурация с HTTPS
cat <<EOF | sudo tee /etc/nginx/conf.d/repo-ssl.conf
server {
    listen 443 ssl http2;
    server_name repo.internal.local;

    ssl_certificate /etc/ssl/certs/mirror.crt;
    ssl_certificate_key /etc/ssl/private/mirror.key;

    root /var/www/html/repos;

    location / {
        autoindex on;
        autoindex_exact_size off;
        autoindex_localtime on;
    }
}
EOF

# Распространение CA-корня на клиенты
sudo cp /etc/ssl/certs/mirror.crt /var/www/html/repos/RPM-GPG-KEY-mirror-ca
```

---

### Сценарий 8: Восстановление после сбоя синхронизации

`reposync` может прерваться из-за проблем с сетью, нехватки диска или прерывания процесса.

```bash
# 1. Проверка места на диске
df -h /var/www/html/repos
du -sh /var/www/html/repos/*

# 2. Проверка блокировок DNF
sudo rm -f /var/cache/dnf/*/*.lock
sudo rm -f /var/lib/dnf/*.lock

# 3. Очистка неполной синхронизации
sudo dnf reposync \
    --repoid=baseos \
    --download-path=/var/www/html/repos/alma9 \
    --newest-only \
    --delete \
    --download-metadata \
    --arch=x86_64 \
    --download-metadata

# 4. Перестроение индексов с нуля (если метаданные повреждены)
sudo rm -rf /var/www/html/repos/alma9/baseos/repodata
sudo createrepo_c --general-compress-type zstd /var/www/html/repos/alma9/baseos

# 5. Проверка целостности после восстановления
sudo dnf repoclosure --repofrompath="local-baseos,http://repo.internal.local/alma9/baseos/" --repoid=local-baseos
```

---

### Сценарий 9: Использование жёстких ссылок для экономии места

При синхронизации нескольких репозиториев (BaseOS + AppStream + EPEL) пакеты часто дублируются. Используйте общий пул.

```bash
# Создание общего пула
sudo mkdir -p /var/www/html/repos/pool

# Синхронизация с использованием пула
sudo dnf reposync \
    --repoid=baseos \
    --download-path=/var/www/html/repos/alma9 \
    --newest-only \
    --delete \
    --download-metadata \
    --arch=x86_64 \
    --download-metadata

# Перемещение пакетов в пул и создание жёстких ссылок
find /var/www/html/repos/alma9 -name "*.rpm" -exec mv -t /var/www/html/repos/pool {} +
# createrepo_c автоматически создаст hardlinks при использовании --update

# Проверка экономии места
df -h /var/www/html/repos
```

---

### Сценарий 10: Создание снапшота репозитория

Для воспроизводимых сборок зафиксируйте состояние зеркала.

```bash
# Создание директории снапшота с жёсткими ссылками
SNAPSHOT_DIR="/var/www/html/repos/snapshots/2025-09-13"
sudo mkdir -p "$SNAPSHOT_DIR"

# Использование rsnapshot или cp -al для создания копии
sudo cp -al /var/www/html/repos/alma9/* "$SNAPSHOT_DIR/"

# Подпись снапшота
cd "$SNAPSHOT_DIR/baseos" && gpg --detach-sign --armor repodata/repomd.xml
cd "$SNAPSHOT_DIR/appstream" && gpg --detach-sign --armor repodata/repomd.xml

# Клиентский .repo файл для конкретного снапшота
cat <<EOF | sudo tee /etc/yum.repos.d/snapshot.repo
[snapshot-baseos]
name=AlmaLinux 9 BaseOS Snapshot 2025-09-13
baseurl=http://repo.internal.local/snapshots/2025-09-13/baseos/
enabled=1
gpgcheck=1
gpgkey=http://repo.internal.local/alma9/RPM-GPG-KEY-AlmaLinux-9

[snapshot-appstream]
name=AlmaLinux 9 AppStream Snapshot 2025-09-13
baseurl=http://repo.internal.local/snapshots/2025-09-13/appstream/
enabled=1
gpgcheck=1
gpgkey=http://repo.internal.local/alma9/RPM-GPG-KEY-AlmaLinux-9
EOF
```

---

## Дополнительная информация

### Требования к дисковому пространству (актуально на 2025 г.)

| Репозиторий | Объем (Full) | Объем (Newest Only) | Примечание |
| :--- | :--- | :--- | :--- |
| **AlmaLinux 9 BaseOS** | ~20 GB | ~8 GB | Основные пакеты ОС |
| **AlmaLinux 9 AppStream** | ~70 GB | ~25 GB | Модули и приложения |
| **Fedora 41 Everything** | ~400 GB | ~150 GB | Огромное количество пакетов |
| **EPEL 9** | ~45 GB | ~15 GB | Дополнительные пакеты |

### Рекомендации по эксплуатации

1.  **GPG-верификация**: Никогда не отключайте `gpgcheck` и `repo_gpgcheck`. Скопируйте GPG-ключи на сервер зеркала и указывайте путь к ним в `gpgkey` (через HTTP или локально). Подписывайте `repomd.xml` через `gpg --detach-sign --armor`.
2.  **Синхронизация RHEL**: Для зеркалирования официального RHEL требуется подписка. Выполняйте `reposync` на хосте, зарегистрированном через `subscription-manager`.
3.  **Архитектуры**: Используйте флаг `--arch`, чтобы не выкачивать пакеты для `i686` или `s390x`, если они не используются в вашей инфраструктуре.
4.  **Delta RPM**: Если клиенты имеют медленные каналы, убедитесь, что зеркало содержит `.drpm` файлы (требует плагина `deltarpm` на клиенте). В DNF 5 DRPM не поддерживается.
5.  **Жёсткие ссылки**: При использовании `--delete` reposync автоматически переиспользует существующие пакеты через hardlinks, что экономит место при синхронизации нескольких репозиториев.
6.  **Кэширование заголовков (headers)**: На клиентах настройте `metadata_expire=7d` в `.repo` файле, чтобы не запрашивать `repomd.xml` при каждом `dnf` вызове.
7.  **Мониторинг места**: Настройте alerting на пороговое значение использования диска (например, 80%) для директории зеркала.

### Устранение проблем

- **Ошибка метаданных AppStream**: Если после синхронизации `dnf module list` пуст, значит метаданные модулей не были загружены. Проверьте наличие каталога `repodata` и используйте `--download-metadata --downloadcomps`.
- **Место на диске**: Репозитории постоянно растут. Рекомендуется выделять под зеркало отдельный LVM-том или раздел с файловой системой XFS/EXT4. Используйте `--newest-only` и `--delete` для ограничения объёма.
- **GPG check FAILED**: Убедитесь, что ключ импортирован на клиенте: `sudo rpm --import /etc/pki/rpm-gpg/RPM-GPG-KEY-AlmaLinux-9`. Проверьте, что `repo_gpgcheck` включён на сервере и клиенте.
- **Failed to download metadata for repo**: Проверьте `dnf repolist`, настройки сети, `baseurl` в `.repo` файле. Убедитесь, что веб-сервер отдаёт файлы с корректными MIME-типами.
- **Reposync прерывается**: Проверьте блокировки `/var/cache/dnf/*/*.lock` и `/var/lib/dnf/*.lock`. Убедитесь, что есть достаточно места на диске. Повторите синхронизацию — `reposync` продолжит с места разрыва.
- **dnf repoclosure показывает неудовлетворённые зависимости**: Это может быть связано с частичным зеркалом (отсутствуют некоторые зависимости из других репозиториев). Используйте `--includepkgs` или зеркалируйте все required репозитории.

### Мониторинг и алертинг

Для production-инфраструктуры настройте мониторинг доступности и свежести зеркала.

```bash
# Проверка доступности зеркала
curl -s -o /dev/null -w "%{http_code}" http://repo.internal.local/alma9/baseos/repodata/repomd.xml
# → 200

# Проверка свежести метаданных
find /var/www/html/repos/alma9 -name "repomd.xml" -exec stat -c "%Y %n" {} \;
# Сравните с текущим временем: date +%s

# Экспорт метрик для Prometheus (node_exporter textfile collector)
cat <<EOF > /var/lib/node_exporter/repo-mirror.prom
# HELP repo_mirror_last_sync_timestamp Время последней успешной синхронизации (unix timestamp)
# TYPE repo_mirror_last_sync_timestamp gauge
repo_mirror_last_sync_timestamp $(date +%s)

# HELP repo_mirror_size_bytes Размер зеркала в байтах
# TYPE repo_mirror_size_bytes gauge
repo_mirror_size_bytes $(du -sb /var/www/html/repos/alma9 | cut -f1)
EOF

# Проверка через systemd-сервис
sudo systemctl status repo-sync.service
journalctl -u repo-sync.service --since "1 hour ago"
```

### Связанные документы

- **[Команды DNF](./dnf_commands/practical_scenarios.md)** — использование настроенных зеркал.
- **[Зеркалирование APT](./apt_mirror/practical_scenarios.md)** — аналогичный процесс для Debian/Ubuntu.
- **[Создание собственного репозитория](./Repository_Management/custom_repository.md)** — процедура подготовки репозитория из локальных RPM-файлов.
- **[Управление репозиториями DNF](./Repository_Management/index.md)** — общие принципы настройки источников.
- **[Операции с репозиториями](./Repository_Management/operations.md)** — управление статусом, GPG-ключами и CLI-инструментарий.
- **[Продвинутые возможности DNF](./dnf_commands/additional_info.md)** — стратегии кэширования, модульность, dry-run транзакции.
