# Установка Angie

**Актуально для:** Angie 1.12.x / Angie PRO 1.12.x

## Определения

**Angie** — высокопроизводительный масштабируемый веб-сервер и обратный прокси с открытым исходным кодом, созданный как форк [Nginx](../Nginx/Core/nginx_overview.md). Разработан компанией ООО «Веб-сервер», входит в Единый реестр российского ПО (запись № 17604) и оптимизирован для работы в высоконагруженных корпоративных инфраструктурах и импортозамещающих средах.

**Angie PRO** — коммерческая редакция веб-сервера с расширенными возможностями: активный мониторинг состояния бэкендов (Active Health Checks), динамическое управление upstream-группами через REST API без перезагрузки, расширенная аналитика сессий и интеграция с российскими средствами криптографической защиты информации (СКЗИ).

**Динамические модули (DSO — Dynamic Shared Objects)** — подключаемые разделяемые библиотеки (`.so`), расширяющие базовую функциональность веб-сервера без необходимости полной пересборки бинарного файла Angie из исходных кодов.

**Замкнутая программная среда (ЗПС / CSE)** — механизм защиты операционной системы (в частности, Astra Linux Special Edition), блокирующий исполнение бинарных файлов и библиотек, не имеющих валидной цифровой подписи доверенной электронной подписью.

## Базовые концепции

### Архитектура пакетов и файловая иерархия

Пакеты Angie используют выделенные системные пути, полностью изолированные от стандартных каталогов Nginx. Это гарантирует отсутствие конфликтов файлов при параллельной установке:

| Компонент / Назначение | Путь в Angie | Путь в Nginx (для сравнения) |
|---|---|---|
| Главный конфигурационный файл | `/etc/angie/angie.conf` | `/etc/nginx/nginx.conf` |
| Каталог конфигурационных блоков | `/etc/angie/conf.d/` | `/etc/nginx/conf.d/` |
| Каталог динамических модулей | `/usr/lib/angie/modules/` | `/usr/lib/nginx/modules/` |
| Симлинк на каталог модулей | `/etc/angie/modules` | `/etc/nginx/modules` |
| Исполняемый бинарный файл | `/usr/sbin/angie` | `/usr/sbin/nginx` |
| Журналы доступа и ошибок | `/var/log/angie/` | `/var/log/nginx/` |
| Каталоги кэша и временных файлов | `/var/cache/angie/` | `/var/cache/nginx/` |
| PID-файл мастер-процесса | `/run/angie.pid` | `/run/nginx.pid` |
| Документы по умолчанию (webroot) | `/usr/share/angie/html/` | `/usr/share/nginx/html/` |
| Системный юнит systemd | `/lib/systemd/system/angie.service` | `/lib/systemd/system/nginx.service` |

### Модель безопасности и учетные записи

*   **Системный пользователь:** Пакеты Angie для Debian/Ubuntu создают учетную запись и группу `angie` (в ряде сборок под RHEL может использоваться системный пользователь `angie` или `nginx`). Рабочие процессы (worker processes) запускаются от имени этого непривилегированного пользователя.
*   **Разграничение прав:** Каталог `/etc/angie/` принадлежит пользователю `root:root` с правами `0755` (конфигурационные файлы защищены от модификации веб-сервером). Каталог `/var/log/angie/` принадлежит `angie:angie` (или `angie:adm`) с правами `0750` или `0755`.
*   **Параллельная эксплуатация:** Возможно сосуществование Angie и Nginx на одном хосте. Конфликт возникает только при попытке привязать сетевой сокет (директива `listen`) к уже занятому IP-адресу и порту.

### Архитектура репозиториев

*   **Публичный репозиторий OSS (`download.angie.software`):** Содержит бинарные пакеты Angie, официальные динамические модули и веб-консоль мониторинга `angie-console-light`. Пакеты подписываются официальным GPG-ключом ООО «Веб-сервер».
*   **Приватный репозиторий Angie PRO:** Требует взаимной аутентификации TLS (mTLS) с использованием клиентского сертификата (`angie-repo.crt`) и закрытого ключа (`angie-repo.key`), выдаваемых при оформлении лицензии.

---

## Практические сценарии

### Сценарий 1: Установка на RHEL-совместимые ОС (AlmaLinux, Rocky Linux, RED OS, CentOS)

Репозитории Angie для дистрибутивов семейства EL разделены по именам операционных систем (`almalinux`, `rocky`, `centos`, `redos`, `oracle`, `fedora`).

#### 1. Подключение официального репозитория

Создайте конфигурационный файл репозитория `/etc/yum.repos.d/angie.repo`:

```ini
[angie]
name=Angie repo
baseurl=https://download.angie.software/angie/almalinux/$releasever/
gpgcheck=1
enabled=1
gpgkey=https://angie.software/keys/angie-signing.gpg.asc
```

> **Примечание по дистрибутивам:** В строке `baseurl` укажите соответствующий каталог ОС:
> *   Для **Rocky Linux**: `https://download.angie.software/angie/rocky/$releasever/`
> *   Для **CentOS Stream**: `https://download.angie.software/angie/centos/$releasever/`
> *   Для **РЕД ОС 7 / 8**: `https://download.angie.software/angie/redos/$releasever/`
> *   Для **Oracle Linux**: `https://download.angie.software/angie/oracle/$releasever/`

#### 2. Импорт GPG-ключа и установка пакета

```bash
# Импорт публичного ключа подписи
sudo rpm --import https://angie.software/keys/angie-signing.gpg.asc

# Установка базового пакета Angie
sudo dnf install -y angie
# → Complete!

# Проверка установленной версии
angie -v
# → angie version: angie/1.12.3 (nginx/1.27.3)
```

#### 3. Настройка SELinux

В дистрибутивах с включенным SELinux (Enforcing) политика по умолчанию запрещает веб-серверу устанавливать исходящие TCP-соединения (необходимо для режима обратного прокси к бэкендам):

```bash
# Разрешить веб-серверу исходящие сетевые подключения к апстримам
sudo setsebool -P httpd_can_network_connect 1

# Разрешить веб-серверу изменять лимиты ресурсов (если настраивается высокий worker_rlimit_nofile)
sudo setsebool -P httpd_setrlimit 1

# Если Angie слушает нестандартный порт (например, 8080 или 8443)
sudo semanage port -a -t http_port_t -p tcp 8080
```

#### 4. Запуск и активация автозагрузки

```bash
sudo systemctl enable --now angie
# → Created symlink /etc/systemd/system/multi-user.target.wants/angie.service → /usr/lib/systemd/system/angie.service.

sudo systemctl status angie
# → Active: active (running) since ...
```

---

### Сценарий 2: Установка на Debian и Ubuntu

В современных версиях Debian (11, 12, 13) и Ubuntu (20.04, 22.04, 24.04, 26.04) устаревший каталог `/etc/apt/trusted.gpg.d/` заменен на изолированное хранилище ключей `/etc/apt/keyrings/` с указанием параметра `signed-by`.

#### 1. Установка вспомогательных утилит и добавление ключа

```bash
sudo apt update
sudo apt install -y ca-certificates curl gnupg lsb-release

# Создание каталога для ключей подписи
sudo install -m 0755 -d /etc/apt/keyrings

# Скачивание и сохранение бинарного ключа репозитория
curl -fsSL https://angie.software/keys/angie-signing.gpg | sudo tee /etc/apt/keyrings/angie-archive-keyring.gpg > /dev/null
sudo chmod 0644 /etc/apt/keyrings/angie-archive-keyring.gpg
```

#### 2. Добавление репозитория

```bash
# Формирование строки репозитория с привязкой к версии ОС
echo "deb [signed-by=/etc/apt/keyrings/angie-archive-keyring.gpg] https://download.angie.software/angie/$(. /etc/os-release && echo "$ID/$VERSION_ID $VERSION_CODENAME") main" \
    | sudo tee /etc/apt/sources.list.d/angie.list > /dev/null
```

> **Альтернативный формат deb822 (`/etc/apt/sources.list.d/angie.sources`):**
> ```ini
> Types: deb
> URIs: https://download.angie.software/angie/ubuntu/24.04
> Suites: noble
> Components: main
> Signed-By: /etc/apt/keyrings/angie-archive-keyring.gpg
> ```

#### 3. Установка и запуск

```bash
sudo apt update
sudo apt install -y angie

# Проверка синтаксиса конфигурации по умолчанию
sudo angie -t
# → angie: the configuration file /etc/angie/angie.conf syntax is ok
# → angie: configuration file /etc/angie/angie.conf test is successful

# Запуск и включение автозагрузки
sudo systemctl enable --now angie
```

---

### Сценарий 3: Установка на российские ОС (Astra Linux, ALT Linux, РОСА)

#### Astra Linux Special Edition (1.7, 1.8, 4.7)

В Astra Linux Special Edition используется режим замкнутой программной среды (ЗПС / CSE), требующий верификации бинарных файлов и библиотек.

1. **Импорт ключа и репозитория:**
   ```bash
   sudo apt-get update
   sudo apt-get install -y ca-certificates curl lsb-release

   sudo curl -fsSL https://angie.software/keys/angie-signing.gpg \
       -o /etc/apt/trusted.gpg.d/angie-signing.gpg

   # Определение версии Astra Linux и добавление репозитория
   echo "deb https://download.angie.software/angie/astra-se/$(egrep -o '[0-9]+\.[0-9]+' /etc/astra_version) unstable main" \
       | sudo tee /etc/apt/sources.list.d/angie.list > /dev/null
   ```

2. **Работа в режиме ЗПС (МРД / МРК):**
   Если на сервере активирован режим контроля исполнимости программ, установите пакет ключей подписи бинарных файлов:
   ```bash
   sudo apt-get update
   sudo apt-get install -y angie-digsig-key

   # Обновление initramfs для применения ключей ЗПС ядра
   sudo update-initramfs -uk all

   # Перезагрузка сервера (требуется для инициализации ключей ядра ЗПС)
   sudo reboot
   ```

3. **Установка пакета:**
   ```bash
   sudo apt-get install -y angie
   sudo systemctl enable --now angie
   ```

#### ALT Linux (10, 11, ALT SP)

В ALT Linux пакетный менеджер `APT-RPM` использует структуру `/etc/apt/vendors.list.d/` и ключевые кольца `/usr/lib/alt-gpgkeys/`.

1. **Настройка доверия ключу:**
   ```bash
   sudo mkdir -p /etc/ssl/angie/
   sudo apt-get update
   sudo apt-get install -y curl apt-https

   sudo curl -fsSL https://angie.software/keys/angie-signing.gpg -o /etc/ssl/angie/angie-signing.gpg
   sudo gpg --no-default-keyring --keyring /usr/lib/alt-gpgkeys/pubring.gpg --import /etc/ssl/angie/angie-signing.gpg

   # Регистрация поставщика в vendors.list.d
   echo 'simple-key "angie" {
       Fingerprint "EB8EAF3D4EF1B1ECF34865A2617AB978CB849A76";
       Name "Angie (Signing Key) <devops@tech.wbsrv.ru>";
   }' | sudo tee /etc/apt/vendors.list.d/angie.list > /dev/null
   ```

2. **Подключение репозитория и установка:**
   ```bash
   # Для ALT Linux 11 (x86_64 или aarch64)
   echo "rpm [angie] https://download.angie.software/angie/altlinux/11/ $(uname -m) main" \
       | sudo tee /etc/apt/sources.list.d/angie.list > /dev/null

   sudo apt-get update
   sudo apt-get install -y angie
   sudo systemctl enable --now angie
   ```

---

### Сценарий 4: Установка на Alpine Linux и FreeBSD

#### Alpine Linux (v3.21 – v3.24)

Alpine Linux использует легковесный пакетный менеджер `apk` и систему инициализации `OpenRC`.

1. **Добавление RSA-ключа и репозитория:**
   ```bash
   sudo apk update
   sudo apk add curl ca-certificates

   # Скачивание открытого RSA-ключа репозитория
   sudo curl -fsSL -o /etc/apk/keys/angie-signing.rsa https://angie.software/keys/angie-signing.rsa

   # Добавление репозитория в список источников apk
   echo "https://download.angie.software/angie/alpine/v$(egrep -o '[0-9]+\.[0-9]+' /etc/alpine-release)/main" \
       | sudo tee -a /etc/apk/repositories > /dev/null
   ```

2. **Установка и запуск службы в OpenRC:**
   ```bash
   sudo apk update
   sudo apk add angie

   # Запуск и добавление в уровень запуска default
   sudo service angie start
   sudo rc-update add angie default
   ```

#### FreeBSD (14, 15)

1. **Настройка репозитория pkg:**
   ```bash
   sudo mkdir -p /usr/local/etc/pkg/angie/ /usr/local/etc/pkg/repos/

   # Скачивание RSA-ключа
   sudo curl -fsSL -o /usr/local/etc/pkg/angie/angie-signing.rsa https://angie.software/keys/angie-signing.rsa

   # Конфигурация репозитория
   cat << 'EOF' | sudo tee /usr/local/etc/pkg/repos/angie.conf > /dev/null
   angie: {
       url: "https://download.angie.software/angie/freebsd/${VERSION_MAJOR}/${ARCH}",
       signature_type: "pubkey",
       pubkey: "/usr/local/etc/pkg/angie/angie-signing.rsa",
       enabled: yes
   }
   EOF
   ```

2. **Установка и запуск:**
   ```bash
   sudo pkg update
   sudo pkg install -y angie

   # Активация автозапуска в /etc/rc.conf и запуск службы
   sudo sysrc angie_enable=YES
   sudo service angie start
   ```

---

### Сценарий 5: Развертывание в Docker

Официальные образы Angie публикуются в реестре `docker.angie.software`. Доступны как полнофункциональные образы со всеми модулями, так и минимальные сборки.

#### 1. Извлечение дефолтной структуры конфигурации

Для стабильной эксплуатации на хосте создается каталог постоянного хранения конфигураций:

```bash
mkdir -p /opt/angie/conf.d /opt/angie/html /opt/angie/logs

# Извлечение базовой рабочей конфигурации из образа
docker run --rm --entrypoint cat docker.angie.software/angie:latest /etc/angie/angie.conf > /opt/angie/angie.conf
```

#### 2. Запуск контейнера через Docker Compose

Создайте файл `/opt/angie/docker-compose.yml`:

```yaml
services:
  angie:
    image: docker.angie.software/angie:1.12.3
    container_name: angie-production
    restart: unless-stopped
    ports:
      - "80:80"
      - "443:443"
    volumes:
      - /opt/angie/angie.conf:/etc/angie/angie.conf:ro
      - /opt/angie/conf.d:/etc/angie/conf.d:ro
      - /opt/angie/html:/usr/share/angie/html:ro
      - /opt/angie/logs:/var/log/angie
    ulimits:
      nofile:
        soft: 65535
        hard: 65535
    healthcheck:
      test: ["CMD", "angie", "-t"]
      interval: 30s
      timeout: 5s
      retries: 3
```

Запуск сервиса:
```bash
docker compose -f /opt/angie/docker-compose.yml up -d
# → Container angie-production  Started
```

---

### Сценарий 6: Установка коммерческой версии Angie PRO

Для доступа к репозиторию Angie PRO требуются лицензионные сертификат `angie-repo.crt` и приватный ключ `angie-repo.key`.

#### 1. Размещение сертификатов

```bash
sudo mkdir -p /etc/ssl/angie/
sudo cp angie-repo.crt /etc/ssl/angie/
sudo cp angie-repo.key /etc/ssl/angie/

# Строгая изоляция прав: доступ только пользователю root
sudo chmod 0600 /etc/ssl/angie/angie-repo.crt /etc/ssl/angie/angie-repo.key
sudo chown root:root /etc/ssl/angie/angie-repo.*
```

#### 2. Настройка пакетного менеджера

*   **Для Debian / Ubuntu (`/etc/apt/apt.conf.d/90angie-pro`):**
    ```apt
    Acquire::https::download.angie.software {
        Verify-Peer "true";
        Verify-Host "true";
        SslCertificate "/etc/ssl/angie/angie-repo.crt";
        SslKey "/etc/ssl/angie/angie-repo.key";
    };
    ```

*   **Для RHEL / Rocky / Alma (`/etc/yum.repos.d/angie-pro.repo`):**
    ```ini
    [angie-pro]
    name=Angie PRO repo
    baseurl=https://download.angie.software/angie-pro/almalinux/$releasever/
    gpgcheck=1
    enabled=1
    gpgkey=https://angie.software/keys/angie-signing.gpg.asc
    sslclientcert=/etc/ssl/angie/angie-repo.crt
    sslclientkey=/etc/ssl/angie/angie-repo.key
    ```

#### 3. Установка пакета

```bash
# Debian / Ubuntu
sudo apt update && sudo apt install -y angie-pro

# RHEL / AlmaLinux
sudo dnf install -y angie-pro

sudo systemctl enable --now angie
```

---

### Сценарий 7: Установка и подключение динамических модулей

Динамические модули поставляются в виде отдельных пакетов `angie-module-<имя>` и устанавливаются в `/usr/lib/angie/modules/`.

#### 1. Популярные модули

| Имя пакета | Назначение | Директива загрузки в `angie.conf` |
|---|---|---|
| `angie-module-brotli` | Сжатие контента алгоритмом Brotli | `load_module modules/ngx_http_brotli_filter_module.so;` |
| `angie-module-njs` | Обработка HTTP/Stream на JavaScript (NJS) | `load_module modules/ngx_http_js_module.so;` |
| `angie-module-wasm` | Исполнение WebAssembly-байткода | `load_module modules/ngx_http_wasm_module.so;` |
| `angie-module-image-filter` | Трансформация изображений (JPEG, PNG, WebP) | `load_module modules/ngx_http_image_filter_module.so;` |
| `angie-module-xslt` | Преобразование XML через XSLT-стили | `load_module modules/ngx_http_xslt_filter_module.so;` |
| `angie-console-light` | Встроенная веб-панель мониторинга | Не требует `load_module` (HTML/JS статика) |

#### 2. Пример установки и активации модуля Brotli

```bash
# Установка пакета модуля
sudo apt install -y angie-module-brotli
# или sudo dnf install -y angie-module-brotli

# Проверка наличия разделяемой библиотеки
ls -l /usr/lib/angie/modules/ngx_http_brotli_*.so
# → -rwxr-xr-x 1 root root ... ngx_http_brotli_filter_module.so
# → -rwxr-xr-x 1 root root ... ngx_http_brotli_static_module.so
```

Подключение в начало `/etc/angie/angie.conf` (в глобальный контекст `main` перед секцией `http`):

```nginx
# Загрузка динамических модулей
load_module modules/ngx_http_brotli_filter_module.so;
load_module modules/ngx_http_brotli_static_module.so;

user angie;
worker_processes auto;
# ...
```

Проверка конфигурации и горячая перезагрузка:
```bash
sudo angie -t
# → angie: the configuration file /etc/angie/angie.conf syntax is ok
# → angie: configuration file /etc/angie/angie.conf test is successful

sudo systemctl reload angie
```

---

### Сценарий 8: Сборка из исходных кодов (Custom Build)

Сборка из исходных кодов применяется при необходимости жесткой оптимизации под архитектуру процессора, интеграции с проприетарными библиотеками ГОСТ-криптографии или сборки статических бинарных файлов.

#### 1. Установка сборочных зависимостей

```bash
# Debian / Ubuntu
sudo apt update
sudo apt install -y build-essential libpcre2-dev zlib1g-dev libssl-dev libxml2-dev libxslt1-dev libgd-dev git

# RHEL / Rocky / AlmaLinux
sudo dnf groupinstall -y "Development Tools"
sudo dnf install -y pcre2-devel zlib-devel openssl-devel libxml2-devel libxslt-devel gd-devel
```

#### 2. Загрузка исходных кодов и конфигурирование

```bash
# Клонирование стабильного тега или ветки
git clone --depth 1 --branch 1.12.3 https://github.com/webserver-llc/angie.git
cd angie

# Запуск скрипта configure с сохранением системных путей Angie
./configure \
    --prefix=/etc/angie \
    --sbin-path=/usr/sbin/angie \
    --modules-path=/usr/lib/angie/modules \
    --conf-path=/etc/angie/angie.conf \
    --error-log-path=/var/log/angie/error.log \
    --http-log-path=/var/log/angie/access.log \
    --pid-path=/run/angie.pid \
    --lock-path=/run/lock/angie.lock \
    --user=angie \
    --group=angie \
    --with-pcre \
    --with-compat \
    --with-threads \
    --with-file-aio \
    --with-http_ssl_module \
    --with-http_v2_module \
    --with-http_v3_module \
    --with-http_realip_module \
    --with-http_addition_module \
    --with-http_sub_module \
    --with-http_dav_module \
    --with-http_flv_module \
    --with-http_mp4_module \
    --with-http_gunzip_module \
    --with-http_gzip_static_module \
    --with-http_auth_request_module \
    --with-http_random_index_module \
    --with-http_secure_link_module \
    --with-http_slice_module \
    --with-http_stub_status_module \
    --with-stream \
    --with-stream_ssl_module \
    --with-stream_realip_module \
    --with-stream_ssl_preread_module
```

#### 3. Компиляция и развертывание

```bash
# Компиляция в параллельных потоках
make -j$(nproc)

# Установка в систему
sudo make install

# Создание системного пользователя и служебных каталогов
sudo id -u angie &>/dev/null || sudo useradd -r -s /sbin/nologin -d /var/cache/angie angie
sudo mkdir -p /var/log/angie /var/cache/angie
sudo chown -R angie:angie /var/log/angie /var/cache/angie
```

#### 4. Создание системного systemd-юнита

Создайте файл `/etc/systemd/system/angie.service`:

```ini
[Unit]
Description=Angie - high performance web server
After=network.target remote-fs.target nss-lookup.target

[Service]
Type=forking
PIDFile=/run/angie.pid
ExecStartPre=/usr/sbin/angie -t -q -g 'daemon on; master_process on;'
ExecStart=/usr/sbin/angie -g 'daemon on; master_process on;'
ExecReload=/usr/sbin/angie -s reload
ExecStop=-/sbin/start-stop-daemon --quiet --stop --retry QUIT/5 --pidfile /run/angie.pid
TimeoutStopSec=5
KillMode=mixed
PrivateTmp=true

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now angie
```

---

## Операции и команды

### Верификация установки

После завершения установки выполните полную проверку целостности развернутого веб-сервера:

```bash
# Проверка версии, версии встроенного Nginx и параметров компиляции
angie -V
# → angie version: angie/1.12.3 (nginx/1.27.3)
# → built by gcc ...
# → built with OpenSSL ...
# → TLS SNI support enabled

# Валидация синтаксиса конфигурационных файлов
sudo angie -t
# → angie: the configuration file /etc/angie/angie.conf syntax is ok
# → angie: configuration file /etc/angie/angie.conf test is successful

# Проверка сетевых сокетов (сервер должен слушать ожидаемые порты)
sudo ss -tulpn | grep angie
# → tcp   LISTEN 0 511 0.0.0.0:80  0.0.0.0:* users:(("angie",pid=1234,fd=6),("angie",pid=1235,fd=6))

# Проверка процессов: один master (root) и дочерние worker (angie)
ps -eo user,group,pid,ppid,cmd | grep '[a]ngie'
# → root     root      1234      1 angie: master process /usr/sbin/angie
# → angie    angie     1235   1234 angie: worker process
```

### Управление сервисом и конфигурацией

```bash
# Плавная перезагрузка конфигурации без обрыва активных клиентских соединений
sudo systemctl reload angie
# или напрямую через сигнал мастер-процессу:
sudo angie -s reload

# Проверка дампа полной активной конфигурации (включая все include)
sudo angie -T

# Быстрая остановка (fast shutdown, SIGTERM)
sudo systemctl stop angie

# Плавная остановка с завершением обработки текущих запросов (graceful shutdown, SIGQUIT)
sudo angie -s quit
```

### Блокировка версий пакетов в production

Для защиты критических серверов от непреднамеренных мажорных обновлений пакетного менеджера:

```bash
# APT (Debian / Ubuntu): блокировка пакета angie и всех модулей
sudo apt-mark hold angie angie-module-*
# → angie set on hold.

# Проверка заблокированных пакетов
sudo apt-mark showhold
# → angie

# Снятие блокировки при запланированном обновлении
sudo apt-mark unhold angie angie-module-*

# DNF (RHEL / Rocky / AlmaLinux): требуется dnf-plugins-core
sudo dnf versionlock add angie angie-module-*
# → Adding versionlock on: angie-...

# Просмотр списка блокировок DNF
sudo dnf versionlock list

# Удаление блокировки
sudo dnf versionlock delete angie angie-module-*
```

### Ротация журналов (logrotate)

Пакетная установка автоматически разворачивает файл `/etc/logrotate.d/angie`. Проверьте его наличие и отправку сигнала `USR1`:

```bash
cat /etc/logrotate.d/angie
```

```text
/var/log/angie/*.log {
    daily
    missingok
    rotate 14
    compress
    delaycompress
    notifempty
    create 0640 angie adm
    sharedscripts
    postrotate
        if [ -f /run/angie.pid ]; then
            kill -USR1 $(cat /run/angie.pid)
        fi
    endscript
}
```

Тестирование ротации логов в режиме симуляции:
```bash
sudo logrotate -d /etc/logrotate.d/angie
# → reading config file /etc/logrotate.d/angie ...
```

### Полное удаление и откат

```bash
# Остановка сервиса
sudo systemctl stop angie

# Полное удаление пакетов (Debian/Ubuntu)
sudo apt purge -y angie angie-pro angie-module-*
# Удаление оставшихся каталогов данных и логов (при необходимости полной очистки)
sudo rm -rf /etc/angie /var/log/angie /var/cache/angie

# Полное удаление пакетов (RHEL/AlmaLinux)
sudo dnf remove -y angie angie-pro angie-module-*
sudo rm -rf /etc/angie /var/log/angie /var/cache/angie

# Откат на предыдущую транзакцию DNF
sudo dnf history list angie
# → 42 | install angie-1.12.3-1.el9 | 2026-10-14
sudo dnf history rollback 41
```

---

## Устранение неисправностей

### Ошибка верификации GPG: NO_PUBKEY или Bad Signature

**Симптомы:**
`apt update` возвращает `The following signatures couldn't be verified because the public key is not available: NO_PUBKEY ...` либо `dnf` сообщает о `GPG check FAILED`.

**Причины и диагностика:**
1. Истек или не был импортирован открытый ключ подписи.
2. Использован устаревший URL ключа (например, несуществующий `angie-signing-key.gpg.asc`).

**Решение:**
```bash
# Для Debian / Ubuntu: скачивание бинарного ключа в /etc/apt/keyrings/
sudo install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://angie.software/keys/angie-signing.gpg | sudo tee /etc/apt/keyrings/angie-archive-keyring.gpg > /dev/null
sudo chmod 0644 /etc/apt/keyrings/angie-archive-keyring.gpg

# Для RHEL / AlmaLinux: импорт ASCII-armored ключа
sudo rpm --import https://angie.software/keys/angie-signing.gpg.asc

# Проверка импортированного ключа в RPM базе
rpm -q gpg-pubkey --qf "%{name}-%{version}-%{release}: %{summary}\n" | grep -i angie
# → gpg-pubkey-...: Angie (Signing Key) <devops@tech.wbsrv.ru> public key
```

---

### Репозиторий возвращает HTTP 403 Forbidden (Angie PRO)

**Симптомы:**
При выполнении `apt update` или `dnf install angie-pro` подключение к `download.angie.software` отклоняется с кодом `403 Forbidden`.

**Причины и диагностика:**
Сервер репозитория Angie PRO требует обязательной клиентской mTLS-аутентификации. Ошибка возникает, если:
*   Сертификат `angie-repo.crt` или ключ `angie-repo.key` отсутствуют по настроенному пути.
*   Права на приватный ключ не позволяют процессу пакетного менеджера прочитать файл.
*   Истек срок действия выданного лицензионного сертификата.

**Решение:**
```bash
# 1. Проверка прав доступа (должны быть строго 0600)
sudo ls -l /etc/ssl/angie/angie-repo.*
# → -rw------- 1 root root ... /etc/ssl/angie/angie-repo.crt
# → -rw------- 1 root root ... /etc/ssl/angie/angie-repo.key

# 2. Проверка срока действия сертификата
openssl x509 -in /etc/ssl/angie/angie-repo.crt -noout -dates
# → notBefore=...
# → notAfter=...

# 3. Тестовый запрос к репозиторию с клиентским сертификатом
curl -I --cert /etc/ssl/angie/angie-repo.crt --key /etc/ssl/angie/angie-repo.key https://download.angie.software/angie-pro/
# → HTTP/2 200
```

---

### Репозиторий возвращает HTTP 404 Not Found

**Симптомы:**
Пакетный менеджер завершается ошибкой: `404 Not Found [IP: ...]`.

**Причины и диагностика:**
Неверно сформирован URL репозитория в конфигурационном файле (например, ошибочный путь `el/$releasever/` вместо конкретного дистрибутива `almalinux/$releasever/`, либо запрошена несуществующая версия ОС).

**Решение:**
1. Проверьте сформированный URL:
   ```bash
   # Вывод фактического URL репозитория
   grep -E 'baseurl|deb ' /etc/yum.repos.d/angie*.repo /etc/apt/sources.list.d/angie*.list
   ```
2. Проверьте доступность URL через curl:
   ```bash
   # Пример проверки для AlmaLinux 9
   curl -s -I https://download.angie.software/angie/almalinux/9/x86_64/ | head -n 1
   # → HTTP/2 200
   ```
3. При необходимости скорректируйте кодовое имя релиза ОС вручную (например, если используется неофициальный дериватив Ubuntu).

---

### Ошибка при старте: bind() failed (98: Address already in use)

**Симптомы:**
`systemctl status angie` переходит в состояние `failed`:
```text
angie[1234]: [emerg] bind() to 0.0.0.0:80 failed (98: Address already in use)
angie[1234]: [emerg] bind() to 0.0.0.0:443 failed (98: Address already in use)
```

**Причины и диагностика:**
Порты `80` или `443` уже заняты другим запущенным демоном (Nginx, Apache `httpd`, Caddy, Envoy).

**Решение:**
```bash
# Поиск процесса, удерживающего порт
sudo ss -tulpn | grep -E ':(80|443)\b'
# → tcp LISTEN 0 511 0.0.0.0:80 0.0.0.0:* users:(("nginx",pid=567,fd=6))

# Если выполняется миграция с Nginx:
sudo systemctl stop nginx
sudo systemctl disable nginx

# Запуск Angie
sudo systemctl start angie
```

---

### Блокировка соединений подсистемой SELinux

**Симптомы:**
Angie возвращает клиентам ошибку `502 Bad Gateway` при обращении к апстримам, в то время как сами бэкенды функционируют штатно.

**Причины и диагностика:**
Журнал аудита Linux фиксирует события `avc: denied { name_connect }`:

```bash
sudo ausearch -m avc -ts recent | grep angie
# → type=AVC msg=audit(...): avc: denied { name_connect } for pid=... comm="angie" dest=8080 scontext=system_u:system_r:httpd_t:s0 tcontext=system_u:object_r:http_port_t:s0 tclass=tcp_socket permissive=0
```

**Решение:**
```bash
# Разрешение веб-серверу исходящих сетевых подключений
sudo setsebool -P httpd_can_network_connect 1

# Если бэкенд слушает нестандартный локальный порт (например, 3000 или 9000):
sudo semanage port -a -t http_port_t -p tcp 3000
```

---

### Ошибка прав доступа: open() "/etc/angie/..." failed (13: Permission denied)

**Симптомы:**
Рабочий процесс не может открыть файл лога или конфигурации:
```text
angie: [emerg] open() "/var/log/angie/error.log" failed (13: Permission denied)
```

**Причины и диагностика:**
1. Права на каталоги не позволяют пользователю `angie` производить запись/чтение.
2. Нарушены метки контекста SELinux после ручного перемещения файлов.

**Решение:**
```bash
# Исправление владельцев и прав
sudo chown -R root:root /etc/angie/
sudo chmod 755 /etc/angie/
sudo chmod 644 /etc/angie/angie.conf /etc/angie/conf.d/*.conf

sudo mkdir -p /var/log/angie /var/cache/angie
sudo chown -R angie:angie /var/log/angie /var/cache/angie
sudo chmod 750 /var/log/angie /var/cache/angie

# Восстановление контекстов безопасности SELinux
sudo restorecon -Rv /etc/angie /var/log/angie /var/cache/angie
```

---

### Ошибка загрузки динамического модуля: module is not binary compatible

**Симптомы:**
При выполнении `angie -t` выводится ошибка:
```text
angie: [emerg] module "/usr/lib/angie/modules/ngx_http_example_module.so" is not binary compatible in /etc/angie/angie.conf:1
```

**Причины:**
Разделяемая библиотека модуля была скомпилирована под другую версию Angie или с другим набором глобальных сигнатурных флагов компиляции.

**Решение:**
1. Убедитесь, что версия установленного модуля строго совпадает с версией бинарного пакета:
   ```bash
   angie -v
   dpkg -l | grep angie-module
   # или rpm -qa | grep angie-module
   ```
2. Обновите модули из официального репозитория:
   ```bash
   sudo apt --only-upgrade install "angie-module-*"
   # или sudo dnf upgrade "angie-module-*"
   ```

---

## Лучшие практики

### 1. Усиление безопасности сервиса через systemd drop-in

Стандартный юнит `angie.service` предоставляет базовые настройки. Для production-контуров рекомендуется применить изоляцию пространства имен файловой системы, запрет повышения привилегий и ограничение системных вызовов:

Создайте drop-in конфигурацию:
```bash
sudo systemctl edit angie
```

Внесите следующий профиль изоляции:
```ini
[Service]
# Блокировка записи в системные каталоги (ФС переводится в read-only)
ProtectSystem=strict

# Разрешенные каталоги для чтения/записи веб-сервера
ReadWritePaths=/var/log/angie /var/cache/angie /run

# Изоляция временных файлов процесса в отдельном namespace
PrivateTmp=true

# Запрет дочерним процессам повышать привилегии через suid/sgid
NoNewPrivileges=true

# Отключение доступа к блочным и символьным устройствам (/dev)
PrivateDevices=true

# Защита системных параметров ядра и модулей
ProtectKernelTunables=true
ProtectKernelModules=true
ProtectControlGroups=true

# Ограничение сетевых протоколов: только IPv4, IPv6 и Unix-сокеты
RestrictAddressFamilies=AF_INET AF_INET6 AF_UNIX

# Минимально необходимый набор Linux capabilities
CapabilityBoundingSet=CAP_NET_BIND_SERVICE

# Увеличение лимита открытых файловых дескрипторов под высокую нагрузку
LimitNOFILE=1048576
```

Применение параметров:
```bash
sudo systemctl daemon-reload
sudo systemctl restart angie

# Проверка примененных параметров изоляции
sudo systemctl show angie -p ProtectSystem -p LimitNOFILE -p NoNewPrivileges
# → ProtectSystem=strict
# → LimitNOFILE=1048576
# → NoNewPrivileges=yes
```

> **Важно для SRE:** При включении `ProtectSystem=strict` любые пути к каталогам кэширования (`proxy_cache_path`), временным файлам загрузки (`client_body_temp_path`) и логам обязательно должны быть явно перечислены в параметре `ReadWritePaths=`.

---

### 2. Настройка лимитов ОС (Sysctl и Limits)

Перед запуском под нагрузкой настройте системные параметры ядра Linux:

В `/etc/security/limits.d/99-angie.conf`:
```text
angie    soft    nofile    1048576
angie    hard    nofile    1048576
```

В `/etc/sysctl.d/99-angie-network.conf`:
```ini
# Максимальный размер очереди соединений ядра
net.core.somaxconn = 65535

# Максимальное количество сокетов в состоянии TIME_WAIT
net.ipv4.tcp_max_tw_buckets = 2000000

# Диапазон динамических портов для исходящих соединений к бэкендам
net.ipv4.ip_local_port_range = 1024 65535

# Повторное использование сокетов в состоянии TIME_WAIT для исходящих подключений
net.ipv4.tcp_tw_reuse = 1
```

Применение параметров ядра:
```bash
sudo sysctl --system
```

---

### 3. Автоматизированная проверка конфигурации в CI/CD

Внедрите обязательный шаг валидации конфигурации перед ее применением на production-узлах:

```bash
#!/usr/bin/env bash
set -Eeuo pipefail

TARGET_CONF="/etc/angie/angie.conf"

echo "[INFO] Тестирование синтаксиса конфигурации Angie..."
if ! angie -t -c "$TARGET_CONF"; then
    echo "[ERROR] Ошибка в конфигурационном файле. Перезагрузка отменена." >&2
    exit 1
fi

echo "[INFO] Конфигурация корректна. Выполняется graceful reload..."
systemctl reload angie
echo "[SUCCESS] Angie успешно перезагружен."
```

---

## Дополнительная информация

### Матрица поддерживаемых ОС и платформ

| Платформа | Версии ОС | Архитектуры | Пакетный менеджер |
|---|---|---|---|
| **Ubuntu** | 22.04 LTS, 24.04 LTS, 26.04 | x86_64, aarch64 | `apt` |
| **Debian** | 11 (Bullseye), 12 (Bookworm), 13 (Trixie) | x86_64, aarch64 | `apt` |
| **AlmaLinux / Rocky Linux** | 8, 9, 10 | x86_64, aarch64 | `dnf` |
| **CentOS Stream** | 9, 10 | x86_64, aarch64 | `dnf` |
| **Astra Linux SE** | 1.7, 1.8, 4.7 | x86_64, aarch64 | `apt-get` |
| **ALT Linux** | 10, 11, ALT SP 8/10 | x86_64, aarch64 | `apt-get` (RPM) |
| **РЕД ОС** | 7, 8 | x86_64, aarch64 | `dnf` |
| **Alpine Linux** | 3.21, 3.22, 3.23, 3.24 | x86_64, aarch64 | `apk` |
| **FreeBSD** | 14, 15 | amd64, aarch64 | `pkg` |

---

## См. также

- [Обзор возможностей Angie](./angie_overview.md) — ключевые преимущества, архитектура и сравнение с Nginx
- [Миграция с Nginx на Angie](./migration_from_nginx.md) — пошаговый переход без простоя и перенос директив
- [Базовая конфигурация Angie](./angie-baseline-config.md) — эталонный production-конфиг веб-сервера
- [Настройка TLS в Angie](./angie_tls_setup.md) — параметры безопасности SSL/TLS, OCSP Stapling и HTTP/3
- [Журналирование в Angie](./angie_logging.md) — настройка access/error логов, переменных и ротации
- [Безопасность systemd](../../Linux/Security/Concepts/systemd_security.md) — детальный разбор директив изоляции сервисов
