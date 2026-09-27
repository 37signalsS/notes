# Установка Angie

## Определения

**Angie** — современный высокопроизводительный веб-сервер, форк Nginx, разработанный для расширения функциональности при сохранении полной обратной совместимости. Продукт включен в реестр российского ПО и оптимизирован для работы в высоконагруженных системах и импортозамещающих инфраструктурах.

**Angie Pro** — коммерческая версия веб-сервера, предоставляющая расширенные возможности: активные проверки состояния (Active Health Checks), динамическое управление апстримами через API и расширенную статистику.

## Базовые концепции

### Методы развертывания
Развертывание Angie адаптировано под различные сценарии эксплуатации:

1.  **Официальные репозитории:** Рекомендуемый метод для серверных ОС (AlmaLinux, Ubuntu, Debian), а также специализированных российских дистрибутивов (**Astra Linux**, **ALT Linux**, **РЕД ОС**). Обеспечивает легкое управление обновлениями.
2.  **Контейнеризация (Docker):** Использование официальных образов в реестре `docker.angie.software`. Оптимально для CI/CD и микросервисов.
3.  **Сборка из исходных кодов:** Необходима для кастомных конфигураций (например, использование ГОСТ-шифрования, специфических модулей или оптимизации под конкретную архитектуру процессора).

### Принципы именования и путей
Пакеты Angie используют собственные пути, отличные от стандартного Nginx, что позволяет проводить параллельную установку для тестов:
*   Конфигурация: `/etc/angie/`
*   Логи: `/var/log/angie/`
*   Бинарный файл: `/usr/sbin/angie`

## Практические сценарии

### Сценарий 1: Установка на RHEL-совместимые системы (AlmaLinux, RedOS)

1.  **Настройка репозитория:**
    Создайте файл `/etc/yum.repos.d/angie.repo`:
    ```ini
    [angie]
    name=angie
    baseurl=https://download.angie.software/angie/el/$releasever/$basearch/
    gpgcheck=1
    gpgkey=https://angie.software/keys/angie-signing-key.gpg.asc
    enabled=1
    ```

2.  **Установка и запуск:**
    ```bash
    sudo dnf install -y angie
    sudo systemctl enable --now angie
    ```

3.  **SELinux (при необходимости):**
    Разрешите Angie устанавливать сетевые соединения (актуально для reverse proxy):
    ```bash
    sudo setsebool -P httpd_can_network_connect 1
    ```

### Сценарий 2: Установка на Ubuntu и Debian

Для современных систем рекомендуется использовать директорию `/usr/share/keyrings/` для хранения GPG-ключей.

1.  **Подготовка и импорт ключа:**
    ```bash
    sudo apt update && sudo apt install -y ca-certificates curl gnupg2 lsb-release
    
    curl -fsSL https://angie.software/keys/angie-signing.gpg | sudo gpg --dearmor -o /usr/share/keyrings/angie-archive-keyring.gpg
    ```

2.  **Добавление репозитория:**
    ```bash
    echo "deb [signed-by=/usr/share/keyrings/angie-archive-keyring.gpg] https://download.angie.software/angie/$(. /etc/os-release && echo "$ID/$VERSION_ID $VERSION_CODENAME") main" \
    | sudo tee /etc/apt/sources.list.d/angie.list > /dev/null
    ```

3.  **Установка:**
    ```bash
    sudo apt update && sudo apt install -y angie
    ```

### Сценарий 3: Установка на российские ОС (Astra Linux, ALT Linux)

#### Astra Linux (Special Edition)
Установка может потребовать проверки подписей в соответствии с режимом безопасности (МРД/МРК).
1.  Используйте инструкции для Debian, подставляя кодовое имя версии (например, `1.7` или `1.8`).
2.  В системах с замкнутой программной средой установите пакет `angie-digsig-key` для верификации.

#### ALT Linux
Angie включен в официальные репозитории (Сизиф, p10, p11).
```bash
sudo apt-get update
sudo apt-get install -y angie
```

### Сценарий 4: Развертывание в Docker

1.  **Установка Docker:**
    Следуйте руководству: **[Установка Docker на Ubuntu](../../Docker/docker_install_ubuntu.md)**.

2.  **Извлечение дефолтной конфигурации:**
    Перед запуском рекомендуется скопировать стандартный конфиг для последующего монтирования.
    ```bash
    mkdir -p ~/angie_config
    docker run --rm --entrypoint cat docker.angie.software/angie:latest /etc/angie/angie.conf > ~/angie_config/angie.conf
    ```

3.  **Запуск постоянного контейнера:**
    ```bash
    docker run -d --name angie \
      -p 80:80 -p 443:443 \
      -v ~/angie_html:/usr/share/nginx/html:ro \
      -v ~/angie_config/angie.conf:/etc/angie/angie.conf:ro \
      --restart always \
      docker.angie.software/angie:latest
    ```

### Сценарий 5: Установка коммерческой версии (Angie Pro)

Требует лицензионных файлов `angie-repo.crt` и `angie-repo.key`.

1.  **Настройка аутентификации (Debian/Ubuntu):**
    Разместите ключи в `/etc/ssl/angie/` (права `600`) и настройте `apt`:
    ```bash
    # /etc/apt/apt.conf.d/90angie-pro
    Acquire::https::download.angie.software {
        Verify-Peer "true";
        Verify-Host "true";
        Ssl-Certificate "/etc/ssl/angie/angie-repo.crt";
        Ssl-Key "/etc/ssl/angie/angie-repo.key";
    };
    ```

2.  **Установка пакета:**
    ```bash
    sudo apt update && sudo apt install -y angie-pro
    ```

### Сценарий 6: Сборка из исходных кодов (Advanced)

Необходима для тонкого тюнинга или использования сторонних библиотек (BoringSSL, QuicTLS).

#### 1. Подготовка зависимостей

**Метод А: Через официальный репозиторий (Рекомендуемый)**
Автоматически устанавливает всё необходимое для сборки текущей версии.
```bash
# Включите deb-src в /etc/apt/sources.list.d/angie.list
sudo sed -i 's/^deb /deb-src /' /etc/apt/sources.list.d/angie.list
sudo apt update
sudo apt build-dep angie
```

**Метод Б: Ручная установка (Минимальный набор)**
```bash
sudo apt install build-essential libpcre3-dev zlib1g-dev libssl-dev libxml2-dev libxslt1-dev libgd-dev libgeoip-dev
```

#### 2. Конфигурация (`configure`)

Рекомендуется использовать аргументы стандартного пакета как базу:
```bash
# Просмотр текущих аргументов
angie -V 2>&1 | grep "configure arguments"

# Запуск конфигурации
./configure --with-openssl=/path/to/openssl-src \
            --with-http_v3_module \
            --prefix=/etc/angie \
            --sbin-path=/usr/sbin/angie \
            --conf-path=/etc/angie/angie.conf \
            --error-log-path=/var/log/angie/error.log \
            --http-log-path=/var/log/angie/access.log
```

#### 3. Сборка сторонних модулей (на примере Brotli)

```bash
# Сборка библиотеки-зависимости
git clone --recursive https://github.com/google/ngx_brotli
cd ngx_brotli/deps/brotli
mkdir out && cd out
cmake -DCMAKE_BUILD_TYPE=Release ..
make && make install
cd ../../../..

# Сборка Angie с модулем
./configure --add-module=../ngx_brotli
make -j$(nproc)
```

#### 4. Упаковка и установка

**CheckInstall (быстрый DEB/RPM пакет):**
Позволяет системе видеть установку в пакетном менеджере, что упрощает удаление.
```bash
sudo apt install checkinstall
sudo checkinstall --pkgname=angie-custom --pkgversion=1.x.x
```

**Сборка из Source-пакета (Полноценный метод):**
Гарантирует наличие всех системных юнитов и прав доступа.
```bash
apt source angie
cd angie-1.x.x
# Добавьте свои параметры в debian/rules
dpkg-buildpackage -b -us -uc
```

## Операции и команды

### Верификация установки

После установки всегда выполняйте проверку целостности:

```bash
# Проверка версии и модулей
angie -V
# → angie version: angie/1.12.2 (nginx/1.27.3)

# Проверка синтаксиса конфигурации
sudo angie -t
# → angie: the configuration file /etc/angie/angie.conf syntax is ok
# → angie: configuration file /etc/angie/angie.conf test is successful

# Проверка статуса системной службы
sudo systemctl status angie
# → Active: active (running) since ...

# Проверка что бинарный файл из пакета Angie, а не Nginx
ls -la /usr/sbin/angie
# → -rwxr-xr-x 1 root root ... /usr/sbin/angie
```

### Управление репозиториями

```bash
# Просмотр настроенных репозиториев (DNF)
sudo dnf repolist all | grep angie
# → angie                      Angie repo          enabled:  1

# Просмотр настроенных репозиториев (APT)
grep -r "download.angie.software" /etc/apt/sources.list.d/
# → /etc/apt/sources.list.d/angie.list:deb [signed-by=...] https://download.angie.software/angie/...

# Проверка GPG-ключа репозитория
rpm -q gpg-pubkey --qf "%{name}-%{version}\n" | grep angie
# → angie-software-2023-xxxxxxxx

# Удаление репозитория (APT)
sudo rm /etc/apt/sources.list.d/angie.list
sudo rm /usr/share/keyrings/angie-archive-keyring.gpg
sudo apt update
```

### Управление пакетами и версиями

```bash
# Просмотр информации об установленном пакете
sudo dnf info angie
# → Name         : angie
# → Version      : 1.12.2-1
# → Release      : el9

# Проверка целостности пакета (RPM)
sudo rpm -V angie
# → (нет вывода = файлы не изменены)

# Блокировка версии (защита от нежелательных обновлений)
# APT
sudo apt-mark hold angie

# DNF (требует python3-dnf-plugin-versionlock)
sudo dnf versionlock add angie

# Снятие блокировки
sudo apt-mark unhold angie
sudo dnf versionlock delete angie

# Просмотр заблокированных пакетов
sudo apt-mark showhold
sudo dnf versionlock list
```

### Удаление и откат

```bash
# Остановка и удаление пакета (APT)
sudo systemctl stop angie
sudo apt purge -y angie angie-module-*

# Остановка и удаление пакета (DNF)
sudo systemctl stop angie
sudo dnf remove -y angie

# Удаление конфигурационных файлов (очистка)
sudo rm -rf /etc/angie /var/log/angie /var/lib/angie

# Откат на предыдущую версию (с метаданными DNF)
sudo dnf history list angie
# →  35 | install angie-1.12.2-1.el9 | 2026-09-20
sudo dnf history rollback 34
```

## Устранение неисправностей

### GPG-ключ: ошибка подписи или "NO_PUBKEY"

**Симптомы:** `apt update` или `dnf install` завершается ошибкой:
```
The following signatures couldn't be verified because the public key is not available: NO_PUBKEY ABCD1234
```

**Диагностика и решение:**
```bash
# Повторный импорт ключа (APT)
curl -fsSL https://angie.software/keys/angie-signing.gpg | sudo gpg --dearmor -o /usr/share/keyrings/angie-archive-keyring.gpg

# Импорт в RPM базе (DNF)
sudo rpm --import https://angie.software/keys/angie-signing-key.gpg.asc

# Проверка наличия ключа
gpg --list-keys --keyring /usr/share/keyrings/angie-archive-keyring.gpg
rpm -q gpg-pubkey | grep angie
```

### Репозиторий недоступен (404, таймаут, SSL)

**Симптомы:** `apt update` или `dnf check-update` не может подключиться к `download.angie.software`.

**Диагностика и решение:**
```bash
# Проверка доступности репозитория
curl -I https://download.angie.software/angie/el/9/x86_64/
# → HTTP/2 200

# Проверка DNS
dig download.angie.software
host download.angie.software

# Проверка SSL-сертификата репозитория
openssl s_client -connect download.angie.software:443 -servername download.angie.software < /dev/null 2>/dev/null | openssl x509 -noout -dates

# Если используется корпоративный прокси
export https_proxy=http://proxy.corp:8080
sudo apt update
```

### Пакет `angie` не найден в репозитории

**Симптомы:** `No package angie available` после настройки репозитория.

**Диагностика и решение:**
```bash
# Проверка что репозиторий включен (не disabled)
grep -r "enabled" /etc/yum.repos.d/angie.repo /etc/apt/sources.list.d/angie.list

# Очистка кэша и повторное обновление
sudo apt clean && sudo apt update
sudo dnf clean all && sudo dnf makecache

# Проверка архитектуры (x86_64, aarch64)
uname -m
# → x86_64

# Прямой поиск пакета в репозитории
curl -s https://download.angie.software/angie/el/9/x86_64/ | grep angie
# → angie-1.12.2-1.el9.x86_64.rpm
```

### Конфликт портов при первом запуске

**Симптомы:** `systemctl status angie` показывает ошибку:
```
angie.service: Failed to start Angie HTTP Server.
bind() failed (98: Address already in use)
```

**Диагностика и решение:**
```bash
# Поиск процесса, занимающего порт 80/443
sudo ss -tlnp | grep -E ':(80|443)'
# → LISTEN 0 128 0.0.0.0:80  ... users:(("nginx",pid=1234,fd=6))

# Проверка конфликтов с Nginx
sudo systemctl status nginx
sudo systemctl stop nginx
sudo systemctl disable nginx

# Изменение портов в /etc/angie/angie.conf при необходимости
sed -i 's/listen 80/listen 8080/' /etc/angie/conf.d/default.conf
sudo systemctl restart angie
```

### Ошибки прав доступа на конфигурацию и логи

**Симптомы:** `angie -t` или `systemctl start angie` возвращает:
```
[emerg] open() "/etc/angie/angie.conf" failed (13: Permission denied)
```

**Диагностика и решение:**
```bash
# Проверка прав на /etc/angie/
ls -la /etc/angie/
# → drwxr-xr-x  root root  ... /etc/angie/

# Проверка SELinux-контекста (если применимо)
ls -laZ /etc/angie/angie.conf
# → system_u:object_r:httpd_config_t:s0 /etc/angie/angie.conf

# Восстановление стандартного контекста
sudo restorecon -Rv /etc/angie/

# Проверка прав на директорию логов
sudo mkdir -p /var/log/angie
sudo chown -R angie:angie /var/log/angie
sudo chmod 755 /var/log/angie
```

### SELinux блокирует сетевые соединения Angie

**Симптомы:** Бэкенды недоступны, `ausearch` показывает отказы:
```
type=AVC msg=audit(...): avc:  denied  { name_connect } for  pid=1234 comm="angie"
```

**Диагностика и решение:**
```bash
# Проверка логов SELinux
sudo ausearch -m avc -ts recent | grep angie
sudo sealert -a /var/log/audit/audit.log

# Разрешение исходящих соединений (reverse proxy)
sudo setsebool -P httpd_can_network_connect 1

# Разрешение подключения к конкретному порту
sudo semanage port -a -t http_port_t -p tcp 8080

# Проверка текущих boolean
sudo getsebool -a | grep httpd
# → httpd_can_network_connect --> off
```

### Пакет `angie-pro` не устанавливается или не активируется

**Симптомы:** `apt install angie-pro` завершается ошибкой аутентификации или пакет не найден.

**Диагностика и решение:**
```bash
# Проверка наличия лицензионных файлов
ls -la /etc/ssl/angie/angie-repo.crt /etc/ssl/angie/angie-repo.key
# → -rw-r----- 1 root root ... angie-repo.crt

# Проверка прав на ключи (должны быть 600)
sudo chmod 600 /etc/ssl/angie/angie-repo.crt /etc/ssl/angie/angie-repo.key

# Проверка конфигурации APT для PRO
cat /etc/apt/apt.conf.d/90angie-pro
# → Acquire::https::download.angie.software { Verify-Peer "true"; ... };

# Проверка подлинности сертификата
openssl s_client -connect download.angie.software:443 \
  -cert /etc/ssl/angie/angie-repo.crt \
  -key /etc/ssl/angie/angie-repo.key < /dev/null 2>/dev/null | openssl x509 -noout -subject
```

## Лучшие практики

### Верификация репозитория

Всегда проверяйте источник пакета перед установкой в production:
*   Используйте официальный домен `download.angie.software`
*   Проверяйте fingerprints GPG-ключа на официальном сайте
*   В изолированных контурах (замкнутый контур) зеркалируйте репозиторий на внутренний Nexus/Artifactory

### Блокировка версий в production

На production-серверах предотвращайте автоматические обновления:
```bash
# APT
sudo apt-mark hold angie angie-module-*

# DNF
sudo dnf versionlock add angie
```
Планируйте обновления вручную в окно технического обслуживания.

### Проверка после установки

Автоматизируйте проверку в CI/CD или post-install скрипте:
```bash
#!/bin/bash
set -e

# Проверка что установлен именно Angie, а не Nginx
if ! command -v angie &>/dev/null; then
    echo "FAIL: angie not found"
    exit 1
fi

# Проверка версии
angie -v | grep -q "angie/" || { echo "FAIL: not Angie binary"; exit 1; }

# Проверка синтаксиса
sudo angie -t

# Проверка что сервис активен
sudo systemctl is-active --quiet angie || { echo "FAIL: angie not running"; exit 1; }

echo "OK: Angie installed and running"
```

### Параллельная установка Angie и Nginx

Из-за разделения путей (`/etc/angie/` vs `/etc/nginx/`) возможна параллельная установка. Это полезно для canary-тестирования:
*   Установите Angie без включения автозагрузки: `sudo systemctl disable angie`
*   Запускайте нужный сервис явно: `sudo systemctl start angie` или `sudo systemctl start nginx`
*   Используйте разные порты для одновременной работы: Angie на `80`, Nginx на `8080`

### Минимальный набор модулей

Избегайте установки всех доступных модулей по умолчанию. Устанавливайте только необходимое:
*   `angie-module-brotli` — только если требуется сжатие Brotli
*   `angie-module-image-filter` — только для трансформации изображений
*   Каждый модуль добавляет поверхность атаки и потребление памяти

### Изоляция путей и пользователя

*   Никогда не запускайте Angie от `root` в production. Используйте отдельного непривилегированного пользователя.
*   Проверьте права на `/etc/angie/` (владелец `root`, права `755`) — конфиги не должны быть записываемыми веб-сервером.
*   Логи должны находиться на отдельном разделе или в `tmpfs` при высокой нагрузке для снижения I/O.

### Жёсткая изоляция через systemd

Системный юнит по умолчанию недостаточно изолирован. Добавьте drop-in для усиления (полный разбор директив — в [Безопасность systemd](../../Linux/Security/Concepts/systemd_security.md)):

```bash
sudo systemctl edit angie
```

```ini
[Service]
ProtectSystem=strict
PrivateTmp=true
NoNewPrivileges=true
PrivateDevices=true
ProtectKernelTunables=true
ProtectKernelModules=true
ProtectControlGroups=true
RestrictAddressFamilies=AF_INET AF_INET6 AF_UNIX
CapabilityBoundingSet=CAP_NET_BIND_SERVICE CAP_NET_BROADCAST CAP_NET_ADMIN
LimitNOFILE=1000000
```

Проверка применённых ограничений:

```bash
sudo systemctl show angie -p ProtectSystem -p NoNewPrivileges -p CapabilityBoundingSet
```

**Важно:** `ProtectSystem=strict` делает корневую ФС доступной только для чтения — убедитесь, что пути кэша (`proxy_cache_path`), `client_body_temp_path` и логи доступны для записи через `ReadWritePaths=` или находятся вне защищённых директорий.

### Документирование изменений

*   Фиксируйте версию пакета (`angie -v`) в системе контроля версий конфигурации.
*   При обновлении создавайте бэкап: `cp /etc/angie/angie.conf /etc/angie/angie.conf.bak.$(date +%Y%m%d%H%M%S)`
*   Ведите changelog обновлений в `/var/log/angie/CHANGELOG` или в Git.

## Дополнительная информация

### Верификация установки
После установки всегда выполняйте проверку:
*   `angie -V` — проверка версии и модулей.
*   `angie -t` — проверка синтаксиса конфигурации.
*   `systemctl status angie` — статус системной службы.

### Управление обновлениями
Для предотвращения нежелательных обновлений на production-серверах:
*   **APT:** `sudo apt-mark hold angie`
*   **DNF:** `sudo dnf versionlock add angie` (требует `python3-dnf-plugin-versionlock`).

### Динамические модули
Angie поддерживает установку модулей в виде отдельных пакетов `angie-module-`.
```bash
# Установка модуля Brotli
sudo apt install angie-module-brotli

# Подключение в /etc/angie/angie.conf
load_module modules/ngx_http_brotli_filter_module.so;
```

## См. также

- [Обзор возможностей Angie](./angie_overview.md)
- [Миграция с Nginx на Angie](./migration_from_nginx.md)
- [Настройка TLS в Angie](./angie_tls_setup.md)
