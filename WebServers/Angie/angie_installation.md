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
    Следуйте SSoT-руководству: **[Установка Docker на Ubuntu](../../Docker/docker_install_ubuntu.md)**.

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
- [Мониторинг Angie: Console Light](./angie_monitoring/angie_monitoring_console.md)
