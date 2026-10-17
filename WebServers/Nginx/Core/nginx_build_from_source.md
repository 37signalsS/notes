# Сборка Nginx из исходного кода и управление динамическими модулями

**Актуально для:** Nginx 1.26.x (Stable) / 1.27.x (Mainline)

---

## Определения

**Сборка из исходного кода (Build from source)** — процесс компиляции исполняемого бинарного файла веб-сервера Nginx и его модулей из исходного кода C с помощью компилятора (GCC или Clang) и внутренней сборочной системы Nginx (`./configure` и `make`). Применяется в production-окружениях системными администраторами и инженерами SRE, когда дистрибутивные пакеты не содержат необходимых модулей, содержат устаревшие версии библиотек, либо когда требуется тонкая оптимизация и аппаратный hardening под конкретную архитектуру процессора.

**Динамический модуль (Dynamic Module, DSO)** — модуль Nginx, скомпилированный в виде разделяемого объекта ELF (`.so`) отдельно от основного исполняемого файла сервера. Загружается в память мастер-процесса во время запуска или перечитывания конфигурации с помощью директивы верхнего уровня `load_module`.

**Статический модуль (Static Module)** — модуль Nginx, исходный код которого компилируется и компонуется непосредственно в бинарный файл `nginx` на этапе сборки через параметр `--add-module=<путь>`. Не требует директивы `load_module`, не может быть выгружен или заменен без полной перекомпиляции и замены бинарного файла.

**ABI (Application Binary Interface) и `NGX_MODULE_SIGNATURE`** — бинарный интерфейс и контрольная сигнатура Nginx, гарантирующие совместимость структур данных (`ngx_http_request_t`, пулов памяти, контекстов) между ядром сервера и динамическими модулями. Сигнатура вычисляется на этапе компиляции на основе версии Nginx, разрядности системы и включенных базовых подсистем.

**`--with-compat`** — специальный флаг конфигуратора Nginx, резервирующий смещения и выравнивания в ключевых внутренних C-структурах ядра. Обеспечивает двоичную совместимость динамических модулей со стандартными бинарными сборками Nginx той же версии без необходимости полного совпадения второстепенных флагов компиляции.

**Zero-Downtime Binary Upgrade (`SIGUSR2`)** — механизм бесшовной замены исполняемого файла Nginx в оперативной памяти без разрыва активных клиентских соединений и без простоя сервиса. Реализуется через системный вызов `execve()` и передачу слушающих файловых дескрипторов сокетов новому мастер-процессу.

**FHS (Filesystem Hierarchy Standard)** — стандарт иерархии файловой системы Linux, регламентирующий размещение исполняемых файлов в `/usr/sbin`, конфигураций в `/etc/nginx`, разделяемых библиотек в `/usr/lib/nginx/modules`, временных файлов кэша в `/var/cache/nginx`, а журналов — в `/var/log/nginx`.

---

## Основные концепции и архитектура

### Архитектура сборочной системы Nginx

В отличие от многих открытых C-проектов (например, Apache HTTP Server), Nginx **не использует** GNU Autotools (`autoconf`, `automake`, `libtool`) или CMake. Сборочная система Nginx полностью написана на стандартных POSIX shell-скриптах и сосредоточена в каталоге `auto/`:

```
nginx-source/
├── auto/
│   ├── configure          # Входная точка проверки параметров и библиотек
│   ├── options            # Разбор ключей CLI и установка сборочных переменных
│   ├── cc/                # Детектирование компилятора (gcc, clang) и генерация CFLAGS
│   ├── os/                # Проверка системных вызовов ОС (Linux epoll, sendfile, eventfd)
│   ├── modules            # Формирование списка статических и динамических модулей
│   └── lib/               # Проверка зависимостей (PCRE2, OpenSSL, zlib, libxslt, etc.)
├── src/                   # Исходный код ядра и стандартных модулей
└── configure              # Скрипт-обертка верхнего уровня (вызывает auto/configure)
```

**Жизненный цикл сборки:**
1. **Генерация сборочного дерева (`./configure`):** скрипт тестирует компилятор и заголовочные файлы ОС, компилируя минимальные проверочные программы. По итогам создается каталог `objs/`:
   - `objs/Makefile` — итоговые директивы сборки для `make`.
   - `objs/ngx_modules.c` — сгенерированный C-файл, объявляющий глобальный массив указателей `ngx_modules[]`, определяющий строгий порядок вызова обработчиков статических модулей.
   - `objs/ngx_auto_config.h` и `objs/ngx_auto_headers.h` — макросы доступных системных вызовов ядра Linux.
2. **Компиляция (`make`):** параллельная трансляция исходного кода ядра и модулей в объектные файлы (`.o`) и компоновка итогового ELF-бинарника `objs/nginx` (а также разделяемых библиотек `objs/*.so` для динамических модулей).
3. **Установка (`make install`):** копирование бинарного файла, модулей, базовой конфигурации и man-страниц в целевые каталоги операционной системы в соответствии с переданными путями.

### Механика динамических модулей и контроль бинарной совместимости (ABI)

Динамический модуль Nginx компилируется как разделяемый объект ELF со следующей структурой:

```
[ ngx_http_vhost_traffic_status_module.so ]
     │
     ├── ngx_module_t (структура метаданных модуля)
     │     ├── ngx_uint_t ctx_index / index
     │     ├── ngx_uint_t version (версия Nginx)
     │     ├── void *ctx (контекст: команды конфигурации)
     │     ├── ngx_command_t *commands (директивы для nginx.conf)
     │     └── const char *signature (строка NGX_MODULE_SIGNATURE)
     └── Скомпилированный C-код модуля
```

При выполнении директивы `load_module` мастер-процесс Nginx вызывает системный вызов `dlopen()` и считывает структуру `ngx_module_t`. До инициализации модуля Nginx выполняет строгую проверку:

1. **Версия сервера:** номер версии Nginx, зашитый в модуль при компиляции, обязан строго совпадать с версией исполняемого бинарника `nginx`.
2. **Контрольная сигнатура (`NGX_MODULE_SIGNATURE`):** строка бинарной совместимости. Если бинарник Nginx скомпилирован с флагом `--with-debug` или `--with-threads`, а модуль — без них, бинарные смещения полей структур данных не совпадут. В этом случае Nginx немедленно завершает работу с фатальной ошибкой:
   ```text
   nginx: [emerg] module "..." is not binary compatible in /etc/nginx/nginx.conf:1
   ```
3. **Роль флага `--with-compat`:** добавляет в C-структуры ядра резервные поля-заполнители (`padding`). Это позволяет модулям, собранным с `--with-compat`, безопасно работать с официальными дистрибутивными сборками Nginx, даже если второстепенные опции сборки слегка отличаются.

### Сравнительный анализ: статические и динамические модули

| Характеристика | Статический модуль (`--add-module`) | Динамический модуль (`--add-dynamic-module`) |
|---|---|---|
| **Способ интеграции** | Влинковывается в бинарник `nginx` | Компилируется в `.so`, загружается через `load_module` |
| **Скорость вызова** | Прямой вызов функций без оверхеда | Минимальный оверхед через таблицу PLT/GOT |
| **Потребление RAM** | Код модуля всегда находится в памяти процесса | Модуль загружается в память только при наличии `load_module` |
| **Обновление модуля** | Требует полной перекомпиляции и замены бинарника | Требует сборки только файла `.so` с флагом `--with-compat` |
| **Связанность с версией** | Неотделим от конкретного исполняемого файла | Жестко привязан к версии Nginx и сигнатуре ABI |
| **Рекомендация SRE** | Модули ядра, критичные к производительности (TLS, HTTP/2, Stream) | Сторонние расширения (VTS, GeoIP2, ModSecurity, njs, Brotli) |

### Стандарты размещения каталогов (FHS)

По умолчанию при запуске `./configure` без параметров Nginx устанавливается в самодостаточный каталог `/usr/local/nginx`, что нарушает стандарты современных Linux-систем и усложняет автоматизацию (systemd, logrotate, мониторинг).

В корпоративной среде DevOps/SRE сборку конфигурируют в строгом соответствии с FHS:

| Параметр `./configure` | Значение по FHS | Назначение |
|---|---|---|
| `--prefix=` | `/etc/nginx` | Базовый каталог конфигурации |
| `--sbin-path=` | `/usr/sbin/nginx` | Исполняемый бинарный файл сервера |
| `--modules-path=` | `/usr/lib/nginx/modules` | Каталог скомпилированных динамических модулей (`.so`) |
| `--conf-path=` | `/etc/nginx/nginx.conf` | Главный файл конфигурации |
| `--error-log-path=` | `/var/log/nginx/error.log` | Основной журнал ошибок |
| `--http-log-path=` | `/var/log/nginx/access.log` | Основной журнал обращений |
| `--pid-path=` | `/run/nginx.pid` | PID-файл мастер-процесса (в `tmpfs`) |
| `--lock-path=` | `/run/lock/nginx.lock` | Файл межпроцессных блокировок |
| `--http-client-body-temp-path=` | `/var/cache/nginx/client_temp` | Буферизация тел клиентских запросов |
| `--http-proxy-temp-path=` | `/var/cache/nginx/proxy_temp` | Буферизация ответов проксируемых бэкендов |
| `--http-fastcgi-temp-path=` | `/var/cache/nginx/fastcgi_temp` | Временные файлы FastCGI (PHP-FPM) |
| `--http-uwsgi-temp-path=` | `/var/cache/nginx/uwsgi_temp` | Временные файлы uWSGI (Python) |
| `--http-scgi-temp-path=` | `/var/cache/nginx/scgi_temp` | Временные файлы SCGI |
| `--user=` / `--group=` | `nginx` / `nginx` | Непривилегированный пользователь для worker-процессов |

### Hardening бинарника: флаги компилятора и линковщика

Сборка веб-сервера, выходящего в публичную сеть, требует включения механизмов защиты операционной системы от эксплуатации уязвимостей переполнения буфера (ROP-цепочки, повреждение стека):

- **`-fstack-protector-strong`**: размещение защитных канареек («canary») на стеке функций.
- **`-Wp,-D_FORTIFY_SOURCE=2`**: динамическая проверка переполнения функций работы с памятью (`memcpy`, `strcpy`, `sprintf`).
- **`-fPIE` / `-pie` (Position Independent Executable)**: полная рандомизация адресного пространства бинарника в связке с ASLR ядра Linux.
- **`-Wl,-z,relro -Wl,-z,now` (Full RELRO)**: перевод таблицы линковщика GOT (Global Offset Table) в режим Read-Only после загрузки программы, предотвращая ее перезапись эксплойтами.

---

## Практические сценарии

### Сценарий 1: Подготовка окружения и зависимостей ОС

Перед компиляцией необходимо подготовить сборочный тулчейн, заголовочные файлы библиотек, системного пользователя и структуру каталогов кэша.

#### Для дистрибутивов Debian / Ubuntu (22.04 / 24.04 LTS):

```bash
# Обновление индексов пакетов
sudo apt-get update

# Установка сборочного тулчейна и заголовочных файлов библиотек
sudo apt-get install -y --no-install-recommends \
  build-essential \
  libpcre2-dev \
  zlib1g-dev \
  libssl-dev \
  libxml2-dev \
  libxslt1-dev \
  libgd-dev \
  wget \
  curl \
  gnupg \
  ca-certificates
# → Setting up build-essential ...
# → Setting up libpcre2-dev:amd64 ...
# → Setting up libssl-dev:amd64 ...
```

> [!IMPORTANT]
> В современных версиях Nginx (начиная с 1.21.5) библиотека PCRE v1 объявлена устаревшей. Всегда используйте современную библиотеку PCRE2 (`libpcre2-dev` для Debian/Ubuntu или `pcre2-devel` для RHEL).

#### Для дистрибутивов RHEL / AlmaLinux / Rocky Linux 9:

```bash
# Установка группы инструментов разработки и библиотек
sudo dnf groupinstall -y "Development Tools"
sudo dnf install -y \
  pcre2-devel \
  zlib-devel \
  openssl-devel \
  libxml2-devel \
  libxslt-devel \
  gd-devel \
  which \
  wget
# → Installed: gcc, make, pcre2-devel, openssl-devel
```

#### Создание системного пользователя и каталогов кэша:

```bash
# Создание системной группы и пользователя без права входа в оболочку
sudo groupadd --system nginx 2>/dev/null || true
sudo useradd --system -d /var/cache/nginx -s /sbin/nologin -g nginx nginx 2>/dev/null || true

# Создание каталогов FHS с правильными правами доступа
sudo mkdir -p /etc/nginx/conf.d \
  /usr/lib/nginx/modules \
  /var/log/nginx \
  /var/cache/nginx/{client_temp,proxy_temp,fastcgi_temp,uwsgi_temp,scgi_temp}

# Установка прав: доступ к каталогам кэша только пользователю nginx
sudo chown -R nginx:nginx /var/cache/nginx
sudo chmod 700 /var/cache/nginx /var/cache/nginx/*
sudo chown -R root:nginx /var/log/nginx
sudo chmod 750 /var/log/nginx
```

---

### Сценарий 2: Полноценная production-сборка Nginx из исходников

Сборка чистого, производительного бинарника Nginx с поддержкой TLS 1.3, HTTP/2, потоков (`threads`), совместимости модулей (`--with-compat`) и FHS-путей.

```bash
# 1. Переход в каталог исходных кодов
cd /usr/local/src

# 2. Загрузка исходников актуальной стабильной версии
export NGINX_VER="1.26.2"
wget https://nginx.org/download/nginx-${NGINX_VER}.tar.gz
wget https://nginx.org/download/nginx-${NGINX_VER}.tar.gz.asc

# 3. Распаковка архива
tar -xzf nginx-${NGINX_VER}.tar.gz
cd nginx-${NGINX_VER}

# 4. Конфигурация с production-флагами и hardening
./configure \
  --prefix=/etc/nginx \
  --sbin-path=/usr/sbin/nginx \
  --modules-path=/usr/lib/nginx/modules \
  --conf-path=/etc/nginx/nginx.conf \
  --error-log-path=/var/log/nginx/error.log \
  --http-log-path=/var/log/nginx/access.log \
  --pid-path=/run/nginx.pid \
  --lock-path=/run/lock/nginx.lock \
  --user=nginx \
  --group=nginx \
  --build="Custom-Prod-Build" \
  --http-client-body-temp-path=/var/cache/nginx/client_temp \
  --http-proxy-temp-path=/var/cache/nginx/proxy_temp \
  --http-fastcgi-temp-path=/var/cache/nginx/fastcgi_temp \
  --http-uwsgi-temp-path=/var/cache/nginx/uwsgi_temp \
  --http-scgi-temp-path=/var/cache/nginx/scgi_temp \
  --with-compat \
  --with-file-aio \
  --with-threads \
  --with-http_ssl_module \
  --with-http_v2_module \
  --with-http_realip_module \
  --with-http_addition_module \
  --with-http_sub_module \
  --with-http_dav_module \
  --with-http_flv_module \
  --with-http_mp4_module \
  --with-http_gunzip_module \
  --with-http_gzip_static_module \
  --with-http_random_index_module \
  --with-http_secure_link_module \
  --with-http_stub_status_module \
  --with-http_auth_request_module \
  --with-http_slice_module \
  --with-pcre-jit \
  --with-stream \
  --with-stream_ssl_module \
  --with-stream_ssl_preread_module \
  --with-stream_realip_module \
  --with-cc-opt='-O2 -g -pipe -Wall -Wp,-D_FORTIFY_SOURCE=2 -fexceptions -fstack-protector-strong --param=ssp-buffer-size=4 -grecord-gcc-switches -m64 -mtune=generic -Werror=format-security -fPIE' \
  --with-ld-opt='-Wl,-z,relro -Wl,-z,now -pie'
# → Configuration summary
# →   + using system PCRE2 library
# →   + using system OpenSSL library
# →   + using system zlib library

# 5. Параллельная компиляция
make -j$(nproc)
# → objs/nginx is built

# 6. Установка бинарника и файлов в систему
sudo make install
```

#### Проверка установленного бинарника:

```bash
/usr/sbin/nginx -V
# → nginx version: nginx/1.26.2 (Custom-Prod-Build)
# → built by gcc 11.4.0 (Ubuntu 11.4.0-1ubuntu1~22.04) 
# → built with OpenSSL 3.0.2 15 Mar 2022
# → TLS SNI support enabled
# → configure arguments: --prefix=/etc/nginx --sbin-path=/usr/sbin/nginx ...
```

---

### Сценарий 3: Сборка стороннего динамического модуля (Stand-alone модуль)

Частая задача SRE — добавить сторонний модуль (например, `ngx_http_vhost_traffic_status_module` или `headers-more-nginx-module`) к уже установленному серверу Nginx без полной перекомпиляции и без изменения основного бинарного файла.

#### Алгоритм сборки stand-alone модуля:

```bash
# 1. Определение точной версии и аргументов работающего Nginx
export NGINX_VER=$(nginx -v 2>&1 | awk -F'/' '{print $2}')
echo "Установленная версия Nginx: ${NGINX_VER}"
# → Установленная версия Nginx: 1.26.2

# 2. Загрузка исходников ТОЧНО ТАКОЙ ЖЕ версии Nginx
cd /usr/local/src
wget -qO- https://nginx.org/download/nginx-${NGINX_VER}.tar.gz | tar -xz

# 3. Загрузка исходников стороннего модуля (пример: headers-more-nginx-module)
git clone https://github.com/openresty/headers-more-nginx-module.git

# 4. Переход в каталог исходников Nginx
cd nginx-${NGINX_VER}

# 5. Конфигурация ТОЛЬКО для динамического модуля с флагом --with-compat
./configure --with-compat --add-dynamic-module=/usr/local/src/headers-more-nginx-module
# → Configuration summary ...

# 6. Компиляция ТОЛЬКО модулей (таргет make modules, не собирает весь nginx!)
make modules
# → cc ... -o objs/ngx_http_headers_more_filter_module.so

# 7. Копирование полученного .so в системную директорию модулей
sudo cp objs/ngx_http_headers_more_filter_module.so /usr/lib/nginx/modules/
sudo chmod 755 /usr/lib/nginx/modules/ngx_http_headers_more_filter_module.so
ls -la /usr/lib/nginx/modules/
# → -rwxr-xr-x 1 root root 89240 ngx_http_headers_more_filter_module.so
```

#### Подключение и проверка в `nginx.conf`:

Добавьте директиву `load_module` на самый верхний уровень файла `/etc/nginx/nginx.conf` (до блоков `events` и `http`):

```nginx
# /etc/nginx/nginx.conf
load_module /usr/lib/nginx/modules/ngx_http_headers_more_filter_module.so;

user nginx;
worker_processes auto;
pid /run/nginx.pid;

events {
    worker_connections 1024;
}

http {
    # Использование директив скомпилированного модуля
    more_set_headers "Server: SecureProxy";
    more_clear_headers "X-Powered-By";

    include /etc/nginx/conf.d/*.conf;
}
```

Проверка конфигурации и применение:

```bash
sudo nginx -t
# → nginx: the configuration file /etc/nginx/nginx.conf syntax is ok
# → nginx: configuration file /etc/nginx/nginx.conf test is successful

sudo systemctl reload nginx
# → Процесс успешно применил конфигурацию с новым модулем
```

---

### Сценарий 4: Статическая компиляция с изолированной версией OpenSSL

Если в LTS-дистрибутиве установлена устаревшая библиотека OpenSSL, либо требуются специфические алгоритмы шифрования или новейшие патчи TLS, Nginx позволяет встроить исходники OpenSSL напрямую.

Особенность Nginx: скрипт `auto/configure` сам настраивает и собирает OpenSSL во время общего `make`. Компилировать OpenSSL заранее **не нужно**.

```bash
cd /usr/local/src

# 1. Загрузка исходников OpenSSL (например, 3.3.2)
wget https://github.com/openssl/openssl/releases/download/openssl-3.3.2/openssl-3.3.2.tar.gz
tar -xzf openssl-3.3.2.tar.gz

# 2. Конфигурация Nginx с указанием пути к исходному коду OpenSSL
cd /usr/local/src/nginx-1.26.2

./configure \
  --prefix=/etc/nginx \
  --sbin-path=/usr/sbin/nginx \
  --with-http_ssl_module \
  --with-http_v2_module \
  --with-openssl=/usr/local/src/openssl-3.3.2 \
  --with-openssl-opt="no-ssl3 no-weak-ssl-ciphers enable-ec_nistp_64_gcc_128"
# → Configuration summary
# →   + OpenSSL library is to be built from sources: /usr/local/src/openssl-3.3.2

# 3. Сборка (Nginx сначала соберет libssl/libcrypto, затем слинкует бинарник)
make -j$(nproc)
sudo make install
```

#### Проверка статической линковки OpenSSL:

```bash
/usr/sbin/nginx -V
# → nginx version: nginx/1.26.2
# → built with OpenSSL 3.3.2 3 Sep 2024

ldd /usr/sbin/nginx | grep -E "ssl|crypto"
# → Вывод пуст (библиотеки OpenSSL статически вкомпилированы внутрь бинарника Nginx)
```

---

### Сценарий 5: Интеграция с systemd и ротация логов (Logrotate)

Сборка из исходников не создает сервисных юнитов и правил ротации логов. Их необходимо развернуть вручную.

#### 1. Создание systemd unit-файла:

Создайте файл `/etc/systemd/system/nginx.service`:

```ini
[Unit]
Description=The NGINX HTTP and reverse proxy server (Source Build)
After=syslog.target network-online.target remote-fs.target nss-lookup.target
Wants=network-online.target

[Service]
Type=forking
PIDFile=/run/nginx.pid
ExecStartPre=/usr/sbin/nginx -t -q -g 'daemon on; master_process on;'
ExecStart=/usr/sbin/nginx -g 'daemon on; master_process on;'
ExecReload=/usr/sbin/nginx -t -q -g 'daemon on; master_process on;'
ExecReload=/bin/kill -s HUP $MAINPID
ExecStop=/bin/kill -s QUIT $MAINPID
TimeoutStopSec=5s
KillMode=mixed
PrivateTmp=true
LimitNOFILE=65536

[Install]
WantedBy=multi-user.target
```

Активация и запуск:

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now nginx
sudo systemctl status nginx
# → Active: active (running) since Thu 2026-10-15; Main PID: 24150 (nginx)
```

#### 2. Настройка ротации журналов (`/etc/logrotate.d/nginx`):

При ротации логов мастер-процессу Nginx отправляется сигнал `USR1` (`SIGUSR1`), заставляющий переоткрыть дескрипторы файлов логов без блокировки или перезапуска:

```text
/var/log/nginx/*.log {
    daily
    missingok
    rotate 14
    compress
    delaycompress
    notifempty
    create 0640 nginx nginx
    sharedscripts
    prerotate
        if [ -d /etc/logrotate.d/httpd-prerotate ]; then \
            run-parts /etc/logrotate.d/httpd-prerotate; \
        fi \
    endscript
    postrotate
        invoke-rc.d nginx rotate >/dev/null 2>&1 || true
        [ -s /run/nginx.pid ] && kill -USR1 `cat /run/nginx.pid`
    endscript
}
```

Тестирование правила ротации в dry-run режиме:

```bash
sudo logrotate -d /etc/logrotate.d/nginx
# → reading config file /etc/logrotate.d/nginx
# → rotating pattern: /var/log/nginx/*.log after 1 days
```

---

### Сценарий 6: Процедура Zero-Downtime обновления бинарника на лету (SRE Runbook)

Когда Nginx собран из исходников, обновление на новую версию (например, с `1.26.2` на `1.28.0` для устранения CVE) выполняется **без разрыва текущих TCP-сессий** клиентов с помощью сигналов `SIGUSR2`, `SIGWINCH` и `SIGQUIT`.

```
Фаза 1: Обычная работа
[Master (PID: 1000)] ───► [Worker 1] [Worker 2]

Фаза 2: kill -USR2 1000 (Старый мастер переименовывает PID в .oldbin и запускает новый бинарник)
[Master (PID: 1000)] ───► [Worker 1] [Worker 2]
     │
     └── forks ──► [Master (PID: 2000, new)] ───► [Worker 3 (new)] [Worker 4 (new)]

Фаза 3: kill -WINCH 1000 (Старые воркеры плавно завершают работу)
[Master (PID: 1000)] (воркеры остановлены)
[Master (PID: 2000, new)] ───► [Worker 3] [Worker 4]

Фаза 4: kill -QUIT 1000 (Старый мастер завершается, новый мастер управляет сервером)
[Master (PID: 2000, new)] ───► [Worker 3] [Worker 4]
```

#### Пошаговый SRE Runbook:

```bash
# Шаг 1. Скомпилировать новую версию в отдельном каталоге
cd /usr/local/src/nginx-1.28.0
./configure --prefix=/etc/nginx --sbin-path=/usr/sbin/nginx ...
make -j$(nproc)

# Шаг 2. Проверить синтаксис конфига новым бинарником до замены
./objs/nginx -t -c /etc/nginx/nginx.conf
# → nginx: the configuration file /etc/nginx/nginx.conf syntax is ok

# Шаг 3. Заменить исполняемый файл на диске с сохранением резервной копии
sudo cp /usr/sbin/nginx /usr/sbin/nginx.backup
sudo cp -f ./objs/nginx /usr/sbin/nginx

# Шаг 4. Отправить сигнал USR2 старому мастер-процессу
OLD_PID=$(cat /run/nginx.pid)
sudo kill -USR2 ${OLD_PID}

# Шаг 5. Проверить появление файла .oldbin и запуск двух master-процессов
ls -la /run/nginx.pid*
# → -rw-r--r-- 1 root root 5 /run/nginx.pid        # PID нового мастера
# → -rw-r--r-- 1 root root 5 /run/nginx.pid.oldbin # PID старого мастера

ps aux | grep nginx | grep master
# → root  1000  0.0  0.1  nginx: master process /usr/sbin/nginx (старый)
# → root  2000  0.0  0.1  nginx: master process /usr/sbin/nginx (новый)

# Шаг 6. Плавный вывод старых воркеров из обслуживания (сигнал WINCH)
sudo kill -WINCH $(cat /run/nginx.pid.oldbin)

# Проверка: старые воркеры закрылись, новые воркеры обрабатывают соединения
ps aux | grep "nginx: worker"
# → nginx  2001  nginx: worker process (принадлежит новому мастеру)

# Шаг 7а. УСПЕХ: завершение старого мастера (сигнал QUIT)
sudo kill -QUIT $(cat /run/nginx.pid.oldbin)
# → Старый мастер завершен, файл /run/nginx.pid.oldbin удален
```

#### Сценарий экстренного отката (Rollback), если в новой версии обнаружен сбой:

Если после шага 6 новые воркеры работают некорректно:

```bash
# 1. Возвращаем старые воркеры в работу (сигнал HUP старому мастеру)
sudo kill -HUP $(cat /run/nginx.pid.oldbin)

# 2. Немедленно останавливаем новый мастер и его воркеры
sudo kill -TERM $(cat /run/nginx.pid)

# 3. Возвращаем прежний бинарник из бэкапа
sudo cp -f /usr/sbin/nginx.backup /usr/sbin/nginx
```

---

## Операции и команды

| Команда | Описание и контекст |
|---|---|
| `/usr/sbin/nginx -v` | Вывод только версии Nginx (`# → nginx version: nginx/1.26.2`) |
| `/usr/sbin/nginx -V` | Полный вывод версии, сборочных флагов и параметров компиляции |
| `/usr/sbin/nginx -V 2>&1 \| tr ' ' '\n' \| grep module` | Быстрый парсинг всех статически вкомпилированных модулей |
| `/usr/sbin/nginx -t` | Валидация синтаксиса `nginx.conf` и проверка доступности файлов модулей |
| `/usr/sbin/nginx -T` | Вывод всей собранной конфигурации со всеми `include` в stdout |
| `make modules` | Компиляция только динамических модулей без сборки ядра сервера |
| `ldd /usr/sbin/nginx` | Анализ динамических разделяемых библиотек бинарника |
| `strings <mod>.so \| grep NGX_MODULE_SIGNATURE` | Просмотр ABI-сигнатуры скомпилированного динамического модуля |
| `kill -HUP $(cat /run/nginx.pid)` | Graceful reload конфигурации (перечитывание `nginx.conf`) |
| `kill -USR1 $(cat /run/nginx.pid)` | Переоткрытие файлов журналов (используется logrotate) |
| `kill -USR2 $(cat /run/nginx.pid)` | Запуск нового бинарника Nginx на лету (Zero-Downtime Upgrade) |
| `kill -WINCH $(cat /run/nginx.pid.oldbin)` | Остановка рабочих процессов старого мастера при апгрейде |
| `kill -QUIT $(cat /run/nginx.pid)` | Graceful shutdown: плавное завершение после отдачи всех запросов |

---

## Устранение неполадок

### 1. Ошибка `[emerg] module "..." is not binary compatible`

**Симптом:** при запуске `nginx -t` или релоаде возникает ошибка:
```text
nginx: [emerg] module "/usr/lib/nginx/modules/ngx_http_vts_module.so" is not binary compatible in /etc/nginx/nginx.conf:1
```

**Причина:** несовпадение ABI-сигнатуры `NGX_MODULE_SIGNATURE` модуля и бинарника Nginx. Модуль собран для другой версии Nginx, либо отличаются параметры компиляции (`--with-debug`, `--with-threads`, разрядность ОС).

**Диагностика:**
```bash
# Сравнение версий
nginx -v
# → nginx version: nginx/1.26.2

strings /usr/lib/nginx/modules/ngx_http_vts_module.so | grep -E "1\.[0-9]+\.[0-9]+"
# → 1.24.0 (модуль собран для старой версии!)
```

**Решение:**
1. Загрузите исходники Nginx **в точности той же версии**, что и работающий сервер (`1.26.2`).
2. Скомпилируйте модуль с флагом `--with-compat`:
   ```bash
   ./configure --with-compat --add-dynamic-module=/path/to/module
   make modules
   sudo cp objs/*.so /usr/lib/nginx/modules/
   ```

---

### 2. Ошибка `undefined symbol: ... in ...so` при `load_module`

**Симптом:**
```text
nginx: [emerg] dlopen() "/usr/lib/nginx/modules/ngx_http_brotli_filter_module.so" failed: 
/usr/lib/nginx/modules/ngx_http_brotli_filter_module.so: undefined symbol: BrotliEncoderCompressStream in /etc/nginx/nginx.conf:2
```

**Причина:** модуль зависит от системной разделяемой библиотеки (например, `libbrotlienc`), которая не была прилинкована при компиляции или отсутствует в системе.

**Диагностика:**
```bash
ldd -r /usr/lib/nginx/modules/ngx_http_brotli_filter_module.so
# → undefined symbol: BrotliEncoderCompressStream
```

**Решение:**
1. Установите недостающие библиотеки (`sudo apt-get install -y libbrotli-dev` или `sudo dnf install -y brotli-devel`).
2. При компиляции модуля передайте линковщику флаг явного связывания:
   ```bash
   ./configure --with-compat --add-dynamic-module=/path/to/brotli --with-ld-opt="-lbrotlienc -lbrotlidec"
   make modules
   ```

---

### 3. Ошибка `[emerg] "load_module" directive is not allowed here`

**Симптом:**
```text
nginx: [emerg] "load_module" directive is not allowed here in /etc/nginx/nginx.conf:15
```

**Причина:** директива `load_module` помещена внутрь контекста `http { ... }`, `events { ... }` или `stream { ... }`.

**Решение:** директивы `load_module` обязаны находиться в глобальном контексте файла `nginx.conf` (в самом начале файла, до открытия любых фигурных скобок).

---

### 4. Ошибка `./configure: error: the HTTP rewrite module requires the PCRE library`

**Симптом:** на этапе конфигурации скрипт прерывается:
```text
./configure: error: the HTTP rewrite module requires the PCRE library.
You can either disable the module by using --without-http_rewrite_module
option, or install the PCRE library into the system, or build the PCRE library
statically from the source with nginx by using --with-pcre=<path> option.
```

**Причина:** в системе отсутствуют заголовочные файлы PCRE2, либо ошибочно установлен устаревший PCRE v1.

**Решение:**
- Debian/Ubuntu: `sudo apt-get install -y libpcre2-dev`
- RHEL/AlmaLinux: `sudo dnf install -y pcre2-devel`

---

### 5. `kill -USR2` не создает новый master-процесс

**Симптом:** после отправки `kill -USR2` новый процесс не появляется, в `error.log` запись:
```text
[crit] 1000#0: rename() "/run/nginx.pid" to "/run/nginx.pid.oldbin" failed (17: File exists)
```

**Причина:** остался зависший файл `/run/nginx.pid.oldbin` от предыдущей незавершенной попытки обновления.

**Решение:**
1. Проверьте, существует ли старый мастер: `ps aux | grep nginx`.
2. Если старый мастер отсутствует, удалите зависший файл вручную:
   ```bash
   sudo rm -f /run/nginx.pid.oldbin
   ```
3. Повторите отправку сигнала `kill -USR2 $(cat /run/nginx.pid)`.

---

## Лучшие практики

1. **Создание дистрибутивных пакетов вместо прямого `make install`:**
   Вместо выполнения `make install` непосредственно на боевых серверах используйте утилиту `fpm` или сборочные правила `dpkg-buildpackage` / `rpmbuild`. Установка через `.deb` / `.rpm` пакеты гарантирует чистое удаление, аудит контрольных сумм в `dpkg -V` / `rpm -V` и легкий откат версий через штатные репозитории.

2. **Фиксация и версионирование параметров сборки (Reproducible Builds):**
   Всегда сохраняйте команду `./configure` со всеми аргументами в виде shell-скрипта (например, `build-nginx.sh`) в Git-репозитории инфраструктуры. Сборка Nginx должна быть детерминированной и воспроизводимой на любом CI/CD-раннере.

3. **Обязательное использование `--with-compat`:**
   Всегда включайте `--with-compat` как при сборке основного бинарника Nginx, так и при компиляции любых сторонних динамических модулей. Это защищает инфраструктуру от фрагментации ABI.

4. **Минимизация поверхности атаки (Attack Surface Reduction):**
   Отключайте неиспользуемые протоколы и парсеры на этапе сборки:
   - Если сервер работает только как обратный прокси, отключите модули прямого доступа к файловой системе: `--without-http_autoindex_module`, `--without-http_ssi_module`, `--without-http_userid_module`.
   - Это снижает размер бинарника в памяти и исключает векторы атак через уязвимости в неиспользуемом коде.

5. **Безопасность прав доступа (Least Privilege):**
   - Бинарный файл `/usr/sbin/nginx` должен принадлежать `root:root` и иметь права `0755`.
   - Файлы конфигурации в `/etc/nginx` должны принадлежать `root:root` с правами `0644` (каталоги `0755`).
   - Каталоги временного кэша (`/var/cache/nginx/*`) должны принадлежать пользователю `nginx:nginx` с правами `0700`.
   - Запрещено запускать master-процесс под непривилегированным пользователем, если требуются привилегированные порты (80, 443) без capabilities (`CAP_NET_BIND_SERVICE`).

---

## Дополнительная информация

### Связанные материалы в базе знаний

- **[Установка и базовая настройка Nginx](../Core/nginx_setup.md)** — пакетная установка из репозиториев nginx.org, базовые директивы конфигурации.
- **[Обзор Nginx](../Core/nginx_overview.md)** — архитектура мастер- и воркер-процессов, модель обработки событий epoll, сигналы ОС.
- **[Настройка мониторинга Nginx с VTS-модулем](../Operations/nginx_vts_monitoring_setup.md)** — практическое применение динамического модуля сбора метрик Prometheus.
- **[Диагностика и устранение неисправностей Nginx](../Operations/nginx_troubleshooting.md)** — системная методология диагностики ошибок 502/504, анализа логов и сетевых сокетов.
- **[Сжатие в Nginx: Gzip, Brotli и Zstandard](../Performance/nginx_compression.md)** — настройка динамических модулей алгоритмов сжатия.
- **[Модуль njs в Nginx](../Core/nginx_njs_module.md)** — компиляция и использование скриптового движка Nginx JavaScript.
- **[Сборка Apache из исходного кода](../../Apache/apache-install-from-source.md)** — альтернативный пайплайн компиляции веб-сервера Apache с утилитой `apxs`.
- **[Развертывание без простоя (Zero-Downtime Deployment)](../../Concepts/web_performance/zero_downtime_deployment.md)** — концепции бесшовного обновления сетевых сервисов.

### Официальная документация и внешние источники

- [Официальное руководство Nginx: Building NGINX from Sources](https://nginx.org/en/docs/configure.html) — полный перечень всех доступных параметров и модулей `./configure`.
- [Официальное руководство: Compiling Dynamic Modules](https://www.nginx.com/resources/wiki/extending/converting/) — архитектура преобразования модулей в динамические.
- [Руководство Nginx: Upgrading Executable on the Fly](https://nginx.org/en/docs/control.html#upgrade) — официальный протокол обновления бинарного файла на лету.