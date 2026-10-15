# Apache: Сборка из исходного кода, apxs и мульти-инстанс

**Актуально для:** Apache HTTP Server 2.4.x (проверено на 2.4.69, APR 1.7.6, APR-util 1.6.5)

---

## Определения

**Сборка из исходного кода (Build from source)** — процесс трансляции исходных кодов Apache HTTP Server (httpd) и связанных библиотек в исполняемые бинарные файлы с помощью сборочной цепочки GCC/Clang, утилит GNU Autotools (`./configure`) и `make`. Применяется в production-окружениях, когда версии пакетов дистрибутива не содержат критических багфиксов или патчей безопасности, требуется нестандартный набор модулей, строгая статическая линковка или оптимизация под архитектуру процессора.

**APR (Apache Portable Runtime)** — библиотека системного уровня (`libapr`), предоставляющая кроссплатформенный программный интерфейс (API) к низкоуровневым функциям операционной системы: управление процессами и потоками, сокетами, пулами памяти (`apr_pool_t`), атомарными операциями и блокировками. Apache 2.4 жестко опирается на APR как на слой аппаратной и системной абстракции.

**APR-util** — библиотека сервисных утилит для APR (`libaprutil`), реализующая структуры данных (хэш-таблицы, очереди), криптографические функции, работу с базами данных (DBD) и парсинг XML.

**apxs (APache eXtenSion tool)** — утилита (Perl-скрипт и обвязка над компилятором), поставляемая вместе с Apache, предназначенная для компиляции сторонних C-модулей в динамические разделяемые объекты (DSO, `.so`) вне основного дерева исходного кода и их автоматической интеграции в файл конфигурации `httpd.conf`.

**DSO (Dynamic Shared Object)** — модули Apache, скомпилированные в виде разделяемых библиотек (`.so`) и загружаемые в адресное пространство процесса во время запуска или перезагрузки через директиву `LoadModule`. Противопоставляются статическим модулям, вкомпилированным напрямую в исполняемый бинарник `httpd`.

**MPM (Multi-Processing Module)** — модули архитектуры многопроцессорной обработки (`event`, `worker`, `prefork`), определяющие сетевую модель сервера, распределение сетевых соединений между процессами и потоками ядра. Тип MPM по умолчанию фиксируется на этапе сборки флагом `--with-mpm`.

**Мульти-инстанс (Multi-instance deployment)** — запуск нескольких независимых экземпляров веб-сервера Apache на одном физическом или виртуальном хосте с использованием общего исполняемого бинарного файла, но с раздельной конфигурацией, портами прослушивания, файлами блокировок, сокетами и журналами событий.

**`httpd -f <путь>`** — флаг запуска демона Apache с альтернативным абсолютным или относительным путем к главному конфигурационному файлу вместо стандартного `conf/httpd.conf`.

**`httpd -D <переменная>`** — передача именованного параметра времени выполнения; в связке с блоками `<IfDefine Переменная>` активирует или отключает изолированные фрагменты конфигурации без правки файлов.

---

## Основные концепции и архитектура

### Зачем собирать вручную в DevOps/SRE-практике

| Причина | Инженерный контекст | Альтернатива в дистрибутиве |
|---|---|---|
| **Устранение 0-day уязвимостей** | Срочное применение CVE-патчей до выпуска официального обновления в репозитории LTS-дистрибутива (Debian, RHEL, Ubuntu). | Ожидание бэкпортов вендора |
| **Кастомные и сторонние модули** | Включение модулей, отсутствующих в стандартных пакетах (`mod_maxminddb`, кастомные WAF/авторизационные фильтры). | Сборка отдельного `.so` через `apxs` к пакетной версии |
| **Минимизация поверхности атаки** | Полное отключение неиспользуемых модулей и функционала (`--disable-cgi`, `--disable-status`, `--disable-autoindex`). | Отключение через `LoadModule` (библиотека остается на диске) |
| **Изоляция окружения (Single-Directory Prefix)** | Установка всего стека в автономный каталог (`/opt/httpd`), не конфликтующий с системными пакетными менеджерами. | Пакеты ОС, разбросанные по `/usr`, `/etc`, `/var` |
| **Тонкая компиляторная оптимизация** | Использование флагов архитектуры `-march=native`, PGO (Profile-Guided Optimization) и LTO (Link-Time Optimization). | Универсальные generic x86_64 сборки |

> [!WARNING]
> Ручная сборка перекладывает ответственность за отслеживание CVE, доставку патчей, совместимость ABI и ротацию библиотек с мейнтейнеров дистрибутива на команду эксплуатации (DevOps/SRE).

### Архитектура каталогов при сборке

При компиляции через параметр `--prefix` Apache формирует самодостаточную иерархию:

```
/opt/httpd/
├── bin/            # Исполняемые файлы: httpd, apachectl, apxs, rotatelogs, htpasswd
├── build/          # Сборочные правила libtool, makefile-шаблоны и config_vars.mk
├── cgi-bin/        # Стандартные CGI-скрипты (отключаются при hardening)
├── conf/           # Главный конфиг httpd.conf, подкаталоги extra/ и mime.types
├── error/          # Локализованные страницы системных ошибок
├── htdocs/         # Стандартный корневой каталог контента (DocumentRoot)
├── icons/          # Пиктограммы для mod_autoindex
├── include/        # Заголовочные файлы C (.h) для разработки и сборки модулей
├── lib/            # Скомпилированные APR/APR-util библиотеки (при bundled-сборке)
├── logs/           # Стандартные журналы access_log, error_log, httpd.pid
└── modules/        # Скомпилированные разделяемые библиотеки (.so)
```

### Модели включения библиотек: Bundled APR vs Системный APR

Apache 2.4 требует библиотеки APR версии не ниже 1.5.0 (рекомендуется 1.7.x) и APR-util 1.6.x. Существуют два подхода к связыванию зависимостей:

1. **Системные зависимости (System-wide):**
   - Используются пакеты `apr-devel` / `libapr1-dev` из репозиториев ОС.
   - **Плюсы:** Быстрая сборка, автоматические обновления библиотек через `apt`/`dnf`.
   - **Минусы:** Версия APR в LTS-дистрибутивах может содержать старые баги сетевых поллеров (epoll/kqueue) или не поддерживать современные вызовы ядра.
2. **Встроенный исходный код (Bundled APR в `srclib/`):**
   - Исходники APR и APR-util загружаются непосредственно в каталог `httpd-2.4.x/srclib/apr` и `httpd-2.4.x/srclib/apr-util`.
   - Запуск с флагом `--with-included-apr` компилирует библиотеки синхронно с веб-сервером и связывает их статически либо размещает внутри `--prefix`.
   - **Плюсы:** Полная изоляция от системных версий, отсутствие конфликтов с системным софтом.
   - **Минусы:** Увеличение времени сборки.

### Конвейер сборки и механизм `config.nice`

Процесс сборки разделен на три этапа:
1. **Конфигурация (`./configure`):** утилита Autotools анализирует сборочное окружение, проверяет компилятор, библиотеки, генерирует `Makefile` и файл `config.nice`. Файл `config.nice` сохраняет точные параметры и флаги запуска `./configure`, позволяя повторить компиляцию идентично командой `./config.nice`.
2. **Компиляция (`make`):** сборка исходного кода в объектные файлы и разделяемые библиотеки параллельно на всех ядрах процессора (`make -j$(nproc)`).
3. **Инсталляция (`make install`):** копирование артефактов в целевую директорию `--prefix`.

### Ключевые флаги `./configure`

| Флаг | Назначение | SRE-рекомендация |
|---|---|---|
| `--prefix=/opt/httpd` | Базовый каталог установки сервера | Задавать изолированный путь вне системных `/usr` |
| `--with-mpm=event` | Выбор модуля многопроцессорной обработки по умолчанию | Всегда `event` для современных высоконагруженных систем |
| `--enable-mpms-shared=all` | Сборка всех MPM в виде DSO-модулей | Позволяет переключать MPM в `httpd.conf` без перекомпиляции |
| `--enable-mods-shared=most` | Сборка большинства базовых модулей в виде `.so` | Оптимальный баланс между гибкостью и размером |
| `--enable-so` | Активация механизма динамической загрузки DSO | Обязательно (нужно для `apxs` и `LoadModule`) |
| `--enable-ssl` | Поддержка протоколов TLS/SSL (`mod_ssl`) | Обязательно при терминации TLS на Apache |
| `--enable-http2` | Поддержка протокола HTTP/2 (`mod_http2`) | Требует библиотеку `libnghttp2` |
| `--enable-brotli` | Поддержка сжатия Brotli (`mod_brotli`) | Требует библиотеку `libbrotli` |
| `--with-pcre` | Путь к утилите `pcre2-config` | Apache 2.4.53+ требует современную библиотеку PCRE2 |
| `--with-included-apr` | Использование встроенных в `srclib` исходников APR | Для воспроизводимых герметичных сборок |
| `--enable-pie` | Компиляция бинарника как Position Independent Executable | Харденинг: предотвращает эксплуатацию ROP-цепочек через ASLR |
| `--disable-version` | Исключение устаревших или неиспользуемых модулей | Снижает footprint и риски безопасности |

### Как устроен `apxs`

Утилита `apxs` автоматизирует компиляцию C-файлов внешнего модуля:
1. Считывает сборочные параметры Apache из `/opt/httpd/build/config_vars.mk` (включая путь к `include`, флаги компилятора `CFLAGS` и библиотеки APR).
2. Вызывает системный компилятор `gcc` через обертку `libtool`.
3. Собирает разделяемую библиотеку `mod_name.so`.
4. Копирует `.so` в директорию `/opt/httpd/modules/`.
5. При наличии флага `-a` парсит главный `httpd.conf` и добавляет директиву:
   ```apacheconf
   LoadModule name_module modules/mod_name.so
   ```

### Архитектура мульти-инстанса

При запуске нескольких инстансов на базе одного исполняемого файла каждый экземпляр должен обладать гарантированной изоляцией на уровне ресурсов операционной системы:

```
                            [ Единый бинарник: /opt/httpd/bin/httpd ]
                                      │                     │
                     ┌────────────────┴────────┐   ┌────────┴────────────────┐
                     ▼                         ▼   ▼                         ▼
            [ Инстанс A (prod-api) ]                  [ Инстанс B (internal-admin) ]
            - Config: /etc/httpd-a.conf               - Config: /etc/httpd-b.conf
            - Listen: 0.0.0.0:8080                    - Listen: 127.0.0.1:8443
            - RuntimeDir: /run/httpd-a                - RuntimeDir: /run/httpd-b
            - PidFile: /run/httpd-a/httpd.pid         - PidFile: /run/httpd-b/httpd.pid
            - Logs: /var/log/httpd-a/                 - Logs: /var/log/httpd-b/
            - Mutex: /run/httpd-a/mutex               - Mutex: /run/httpd-b/mutex
```

Для исключения взаимных блокировок между процессами инстансов обязательны к разведению директивы:
- `Listen`: уникальные IP/порты.
- `DefaultRuntimeDir`: путь для размещения разделяемой памяти и сокетов (например, сокетов `cgid`).
- `PidFile`: уникальный PID-файл мастер-процесса.
- `Mutex`: префикс блокировок в shared memory (`Mutex default:/run/httpd-instance/`).
- `ErrorLog` и `CustomLog`: раздельные файлы журналов.

---

## Практические сценарии

### Сценарий 1: Подготовка окружения и зависимостей ОС

Перед сборкой устанавливаются средства компиляции и заголовочные файлы библиотек.

**Для семейств RHEL / AlmaLinux / Rocky Linux 9:**

```bash
# Установка базового набора компиляторов и dev-пакетов
sudo dnf install -y gcc gcc-c++ make autoconf libtool which \
  pcre2-devel openssl-devel libxml2-devel expat-devel \
  libnghttp2-devel brotli-devel zlib-devel

# Создание сервисного пользователя без оболочки входа
sudo useradd -r -s /sbin/nologin -d /opt/httpd -c "Apache HTTP Server" apache
# → useradd: user 'apache' created
```

**Для семейств Debian / Ubuntu 22.04/24.04:**

```bash
# Установка сборочной цепочки и заголовков библиотек
sudo apt update && sudo apt install -y build-essential autoconf libtool \
  libpcre2-dev libssl-dev libxml2-dev libexpat1-dev \
  libnghttp2-dev libbrotli-dev zlib1g-dev curl ca-certificates

# Создание сервисного пользователя
sudo useradd -r -s /usr/sbin/nologin -d /opt/httpd -c "Apache HTTP Server" apache
# → useradd: user 'apache' created
```

---

### Сценарий 2: Полнофункциональная сборка Apache 2.4.69 с Bundled APR и HTTP/2

Сценарий обеспечивает автономную и воспроизводимую сборку с проверкой криптографических контрольных сумм.

```bash
# 1. Подготовка рабочего каталога для исходников
sudo mkdir -p /usr/local/src/apache-build
sudo chown -R "$USER":"$USER" /usr/local/src/apache-build
cd /usr/local/src/apache-build

# 2. Загрузка исходников Apache, APR и APR-util
curl -LO https://dlcdn.apache.org/httpd/httpd-2.4.69.tar.gz
curl -LO https://dlcdn.apache.org/httpd/httpd-2.4.69.tar.gz.sha256
curl -LO https://dlcdn.apache.org/apr/apr-1.7.6.tar.gz
curl -LO https://dlcdn.apache.org/apr/apr-util-1.6.5.tar.gz

# 3. Валидация контрольной суммы архива httpd
sha256sum -c httpd-2.4.69.tar.gz.sha256
# → httpd-2.4.69.tar.gz: OK

# 4. Распаковка архива сервера
tar -xzf httpd-2.4.69.tar.gz
cd httpd-2.4.69

# 5. Интеграция Bundled APR и APR-util в каталог srclib (без суффиксов версий!)
tar -xzf ../apr-1.7.6.tar.gz -C srclib/
mv srclib/apr-1.7.6 srclib/apr

tar -xzf ../apr-util-1.6.5.tar.gz -C srclib/
mv srclib/apr-util-1.6.5 srclib/apr-util

# 6. Задание флагов безопасности компилятора (Hardening CFLAGS/LDFLAGS)
export CFLAGS="-O2 -g -pipe -Wall -Wp,-D_FORTIFY_SOURCE=2 -fexceptions -fstack-protector-strong --param=ssp-buffer-size=4 -grecord-gcc-switches -m64 -mtune=generic"
export LDFLAGS="-Wl,-z,relro -Wl,-z,now"

# 7. Конфигурация сборочного процесса
./configure \
  --prefix=/opt/httpd \
  --enable-so \
  --enable-mods-shared=most \
  --enable-mpms-shared=all \
  --with-mpm=event \
  --enable-ssl \
  --enable-http2 \
  --enable-brotli \
  --enable-deflate \
  --enable-pie \
  --with-included-apr \
  --with-pcre \
  --disable-autoindex \
  --disable-status \
  --disable-userdir
# → Configuring Apache HTTP Server...
# → Selected MPM: event
# → ...
# → config.status: creating Makefile

# 8. Компиляция на всех доступных ядрах CPU
make -j"$(nproc)"
# → make[1]: Leaving directory '/usr/local/src/apache-build/httpd-2.4.69'

# 9. Установка в каталог /opt/httpd
sudo make install
# → make[1]: Leaving directory '/usr/local/src/apache-build/httpd-2.4.69'
# → make install ok

# 10. Назначение базовых прав доступа
sudo chown -R root:root /opt/httpd
sudo chown -R apache:apache /opt/httpd/logs
sudo chmod 750 /opt/httpd/logs
```

**Валидация сборки:**

```bash
# Проверка версии, параметров компиляции и MPM
/opt/httpd/bin/httpd -V
# → Server version: Apache/2.4.69 (Unix)
# → Server built:   Oct 14 2026 19:10:00
# → Server's Module Magic Number: 20120211:133
# → Server MPM:     event
# → Architecture:   64-bit
# → Server compiled with....
# →  -D HTTPD_ROOT="/opt/httpd"
# →  -D SERVER_CONFIG_FILE="conf/httpd.conf"

# Проверка загруженных модулей
/opt/httpd/bin/httpd -M | grep -E 'mpm|ssl|http2'
# → mpm_event_module (shared)
# → ssl_module (shared)
# → http2_module (shared)

# Проверка синтаксиса дефолтной конфигурации
/opt/httpd/bin/httpd -t
# → Syntax OK
```

---

### Сценарий 3: Сборка и интеграция стороннего C-модуля через `apxs`

Практический пример сборки внешнего модуля ограничения частоты запросов `mod_evasive` для защиты от DoS-атак.

```bash
# 1. Проверка работоспособности apxs и соответствия компилятора
/opt/httpd/bin/apxs -q CC
# → gcc
/opt/httpd/bin/apxs -q TARGET
# → httpd

# 2. Клонирование исходного кода модуля
cd /usr/local/src
git clone https://github.com/shivaas/mod_evasive.git
cd mod_evasive

# 3. Компиляция, установка и автоматическое включение через apxs
# Флаги:
# -c: компиляция исходных файлов (.c) в разделяемый объект
# -i: копирование скомпилированного mod_evasive24.so в /opt/httpd/modules/
# -a: автоматическое добавление LoadModule в /opt/httpd/conf/httpd.conf
sudo /opt/httpd/bin/apxs -i -a -c mod_evasive24.c
# → /opt/httpd/build/libtool --silent --mode=compile gcc ... -c -o mod_evasive24.lo mod_evasive24.c
# → /opt/httpd/build/libtool --silent --mode=link gcc ... -o mod_evasive24.la -rpath /opt/httpd/modules
# → [activating module `evasive24' in /opt/httpd/conf/httpd.conf]

# 4. Проверка появления директивы LoadModule в конфигурации
grep -i "mod_evasive24" /opt/httpd/conf/httpd.conf
# → LoadModule evasive24_module modules/mod_evasive24.so

# 5. Проверка видимости модуля ядром Apache
/opt/httpd/bin/httpd -M | grep evasive
# → evasive24_module (shared)
```

---

### Сценарий 4: Создание production-ready hardened systemd-сервиса

Для самосборного Apache в production создается systemd-юнит с жесткой изоляцией на базе Linux-неймспейсов и cgroups.

```ini
# /etc/systemd/system/httpd.service
[Unit]
Description=Apache HTTP Server (Source Build /opt/httpd)
After=network.target remote-fs.target nss-lookup.target
Documentation=https://httpd.apache.org/docs/2.4/

[Service]
Type=simple
ExecStart=/opt/httpd/bin/httpd -k start -DFOREGROUND -f /opt/httpd/conf/httpd.conf
ExecReload=/opt/httpd/bin/httpd -k graceful -f /opt/httpd/conf/httpd.conf
ExecStop=/opt/httpd/bin/httpd -k graceful-stop -f /opt/httpd/conf/httpd.conf
KillMode=mixed
TimeoutStopSec=60s
Restart=on-failure
RestartSec=5s

# Системные лимиты для высоконагруженного веб-сервера
LimitNOFILE=65535
LimitNPROC=32768

# Песочница systemd (Sandboxing)
User=root
Group=root
ProtectSystem=full
ProtectHome=true
PrivateTmp=true
ProtectKernelTunables=true
ProtectKernelModules=true
ProtectControlGroups=true
NoNewPrivileges=true
CapabilityBoundingSet=CAP_NET_BIND_SERVICE CAP_SETUID CAP_SETGID
AmbientCapabilities=CAP_NET_BIND_SERVICE

# Каталоги для runtime-данных (создаются автоматически systemd)
RuntimeDirectory=httpd
RuntimeDirectoryMode=0755

[Install]
WantedBy=multi-user.target
```

**Активация и запуск:**

```bash
# Перечитывание конфигурации systemd и включение автозапуска
sudo systemctl daemon-reload
sudo systemctl enable --now httpd.service
# → Created symlink /etc/systemd/system/multi-user.target.wants/httpd.service ...

# Проверка статуса
sudo systemctl status httpd.service --no-pager
# → Active: active (running)

# Проверка прослушиваемых портов
ss -tlpn | grep httpd
# → LISTEN 0 511 *:80 *:* users:(("httpd",pid=...,fd=4))
```

---

### Сценарий 5: Развёртывание мульти-инстанса через systemd template (`httpd@.service`)

Для независимого управления несколькими инстансами (например, `api` и `internal`) на одном сервере применяется шаблонный юнит systemd.

```ini
# /etc/systemd/system/httpd@.service
[Unit]
Description=Apache HTTP Server Instance (%i)
After=network.target remote-fs.target nss-lookup.target
PartOf=httpd.target

[Service]
Type=simple
Environment=INSTANCE_NAME=%i
ExecStartPre=/opt/httpd/bin/httpd -t -f /etc/httpd-instances/%i/httpd.conf
ExecStart=/opt/httpd/bin/httpd -f /etc/httpd-instances/%i/httpd.conf -DFOREGROUND
ExecReload=/opt/httpd/bin/httpd -f /etc/httpd-instances/%i/httpd.conf -k graceful
ExecStop=/opt/httpd/bin/httpd -f /etc/httpd-instances/%i/httpd.conf -k graceful-stop
KillMode=mixed
TimeoutStopSec=30s
Restart=on-failure
RestartSec=5s

LimitNOFILE=65535
PrivateTmp=true
ProtectSystem=full
ProtectHome=true

# Каталог /run/httpd-instances/%i создается systemd автоматически
RuntimeDirectory=httpd-instances/%i
RuntimeDirectoryMode=0750
User=apache
Group=apache

[Install]
WantedBy=multi-user.target
```

**Подготовка конфигурации первого инстанса (`api` на порту 8081):**

```bash
# 1. Создание каталогов инстанса
sudo mkdir -p /etc/httpd-instances/api /var/log/httpd-instances/api
sudo chown -R apache:apache /var/log/httpd-instances/api

# 2. Создание изолированного конфигурационного файла
sudo tee /etc/httpd-instances/api/httpd.conf <<'EOF'
ServerRoot "/opt/httpd"
DefaultRuntimeDir "/run/httpd-instances/api"
PidFile "/run/httpd-instances/api/httpd.pid"
Mutex default:/run/httpd-instances/api/mutex

User apache
Group apache

Listen 0.0.0.0:8081

LoadModule mpm_event_module modules/mod_mpm_event.so
LoadModule authz_core_module modules/mod_authz_core.so
LoadModule log_config_module modules/mod_log_config.so
LoadModule unixd_module modules/mod_unixd.so

ErrorLog "/var/log/httpd-instances/api/error.log"
LogLevel warn

LogFormat "%h %l %u %t \"%r\" %>s %b" common
CustomLog "/var/log/httpd-instances/api/access.log" common

DocumentRoot "/var/www/api"
<Directory "/var/www/api">
    Require all granted
</Directory>
EOF

# 3. Подготовка тестового контента
sudo mkdir -p /var/www/api
echo "Instance API (Port 8081)" | sudo tee /var/www/api/index.html
```

**Подготовка конфигурации второго инстанса (`internal` на порту 8082):**

```bash
# 1. Создание каталогов второго инстанса
sudo mkdir -p /etc/httpd-instances/internal /var/log/httpd-instances/internal
sudo chown -R apache:apache /var/log/httpd-instances/internal

# 2. Создание изолированного конфига
sudo sed 's/8081/8082/g; s/\/api/\/internal/g' /etc/httpd-instances/api/httpd.conf | \
  sudo tee /etc/httpd-instances/internal/httpd.conf > /dev/null

# 3. Подготовка тестового контента
sudo mkdir -p /var/www/internal
echo "Instance Internal (Port 8082)" | sudo tee /var/www/internal/index.html
```

**Запуск и проверка изоляции инстансов:**

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now httpd@api
sudo systemctl enable --now httpd@internal

# Проверка прослушивания портов
ss -tlpn | grep -E '8081|8082'
# → LISTEN 0 511 0.0.0.0:8081 0.0.0.0:* users:(("httpd",pid=...,fd=3))
# → LISTEN 0 511 0.0.0.0:8082 0.0.0.0:* users:(("httpd",pid=...,fd=3))

# Валидация независимых HTTP-ответов
curl -s http://127.0.0.1:8081
# → Instance API (Port 8081)
curl -s http://127.0.0.1:8082
# → Instance Internal (Port 8082)
```

---

### Сценарий 6: Процедура бесшовного обновления (Zero-Downtime Upgrade) и отката

Для обновления самосборного веб-сервера без простоя сервиса используется версионирование каталогов через символические ссылки:

```
/opt/httpd -> /opt/httpd-2.4.69  (текущий рабочий симлинк)
/opt/httpd-2.4.68/               (предыдущая версия для мгновенного отката)
/opt/httpd-2.4.69/               (новая скомпилированная версия)
```

**Шаги обновления:**

```bash
# 1. Сборка новой версии в изолированный префикс с номером релиза
cd /usr/local/src/apache-build/httpd-2.4.69
./configure --prefix=/opt/httpd-2.4.69 ... # аналогично Сценарию 2
make -j"$(nproc)" && sudo make install

# 2. Копирование рабочих файлов конфигурации
sudo cp -a /opt/httpd/conf/* /opt/httpd-2.4.69/conf/

# 3. Валидация синтаксиса новым бинарником
/opt/httpd-2.4.69/bin/httpd -t -f /opt/httpd-2.4.69/conf/httpd.conf
# → Syntax OK

# 4. Атомарное переключение символической ссылки
sudo ln -sfn /opt/httpd-2.4.69 /opt/httpd.new && sudo mv -Tf /opt/httpd.new /opt/httpd

# 5. Плавная перезагрузка демона без сброса активных клиентских соединений
sudo systemctl reload httpd.service

# 6. Проверка версии работающего мастера
/opt/httpd/bin/httpd -v
# → Server version: Apache/2.4.69 (Unix)
```

**Процедура мгновенного отката (Rollback) при возникновении сбоев:**

```bash
# Возврат симлинка на проверенную стабильную сборку
sudo ln -sfn /opt/httpd-2.4.68 /opt/httpd.rollback && sudo mv -Tf /opt/httpd.rollback /opt/httpd
sudo systemctl reload httpd.service
```

---

### Сценарий 7: Настройка контекстов SELinux для нестандартного каталога `/opt/httpd`

В дистрибутивах RHEL/AlmaLinux/Rocky принудительный режим SELinux (`Enforcing`) блокирует запуск бинарников и чтение файлов из директорий, отличных от `/usr/sbin/httpd` и `/var/www`.

```bash
# 1. Проверка текущего статуса SELinux
getenforce
# → Enforcing

# 2. Установка утилиты semanage (если отсутствует)
sudo dnf install -y policycoreutils-python-utils

# 3. Регистрация постоянных правил меток контекста безопасности
sudo semanage fcontext -a -t httpd_exec_t '/opt/httpd(/.*)?/bin/httpd'
sudo semanage fcontext -a -t httpd_config_t '/opt/httpd(/.*)?/conf(/.*)?'
sudo semanage fcontext -a -t httpd_log_t '/opt/httpd(/.*)?/logs(/.*)?'
sudo semanage fcontext -a -t httpd_sys_content_t '/opt/httpd(/.*)?/htdocs(/.*)?'
sudo semanage fcontext -a -t httpd_var_run_t '/run/httpd(-instances/.*)?'

# 4. Рекурсивное применение контекстов к файловой системе
sudo restorecon -Rv /opt/httpd
# → Relabeled /opt/httpd/bin/httpd from unconfined_u:object_r:usr_t:s0 to unconfined_u:object_r:httpd_exec_t:s0

# 5. Разрешение нестандартных портов инстансов (например, 8081 и 8082) в SELinux
sudo semanage port -a -t http_port_t -p tcp 8081
sudo semanage port -a -t http_port_t -p tcp 8082
# → semanage: port added
```

---

## Операции и команды

| Команда | Назначение | Пример ожидаемого вывода |
|---|---|---|
| `/opt/httpd/bin/httpd -V` | Полная сводка параметров сборки, флагов компиляции и путей | `Server version: Apache/2.4.69 (Unix)`<br>`Server MPM: event` |
| `/opt/httpd/bin/httpd -v` | Краткая строка версии сервера | `Server version: Apache/2.4.69 (Unix)` |
| `/opt/httpd/bin/httpd -M` | Список всех загруженных статических и shared-модулей | `loaded modules:`<br>`ssl_module (shared)` |
| `/opt/httpd/bin/httpd -l` | Список только скомпилированных статически модулей | `Compiled in modules:`<br>`core.c`<br>`http_core.c` |
| `/opt/httpd/bin/httpd -t` | Проверка синтаксиса дефолтной конфигурации | `Syntax OK` |
| `/opt/httpd/bin/httpd -t -f <файл>` | Проверка синтаксиса альтернативного конфига | `Syntax OK` |
| `/opt/httpd/bin/httpd -S` | Проверка виртуальных хостов, портов и совпадений имен | `VirtualHost configuration:`<br>`*:8081 api.domain` |
| `/opt/httpd/bin/apachectl graceful` | Плавная перечитка конфига без разрыва TCP-соединений | `# → код возврата 0` |
| `/opt/httpd/bin/apxs -q <переменная>` | Запрос сборочных флагов Apache (`PREFIX`, `CC`, `CFLAGS`) | `/opt/httpd` |
| `/opt/httpd/bin/apxs -i -a -c mod.c` | Компиляция, инсталляция и включение внешнего C-модуля | `chmod 755 .../mod.so` |

---

## Типичные ошибки и диагностика

| Симптом / Ошибка | Первопричина | Метод диагностики | Способ устранения |
|---|---|---|---|
| `configure: error: APR not found` | Отсутствуют системные библиотеки APR/APR-util либо повреждены их пути | Проверить наличие `apr-1-config` в `PATH`:<br>`which apr-1-config` | Установить `apr-devel` / `libapr1-dev` либо загрузить APR в `srclib/apr` и передать `--with-included-apr`. |
| `fatal error: pcre2.h: No such file or directory` | В системе установлена устаревшая библиотека PCRE 8.x вместо PCRE2 | `pcre2-config --version` | Установить пакет `pcre2-devel` (RHEL) или `libpcre2-dev` (Debian). Передать `--with-pcre`. |
| `configure: error: ... mod_http2 has been requested but can not be built` | Отсутствует библиотека `libnghttp2` для HTTP/2 | `pkg-config --modversion libnghttp2` | Установить `libnghttp2-devel` (RHEL) или `libnghttp2-dev` (Debian). |
| `configure: error: Bundled APR requested, but not found in srclib/` | Каталоги в `srclib/` названы с номерами версий (`apr-1.7.6`) | Проверить имена:<br>`ls -d srclib/apr*` | Переименовать каталоги строго в `srclib/apr` и `srclib/apr-util`. |
| `(98)Address already in use: AH00072: make_sock: could not bind to address` | Порт инстанса уже занят другим процессом или дублируется директива `Listen` | Найти процесс:<br>`ss -tlpn \| grep <порт>` | Изменить порт в директиве `Listen` конфликтующего инстанса либо завершить старый процесс. |
| `AH00058: Error retrieving pid file` / `Unable to open logs` | У сервисного пользователя `apache` нет прав на запись в целевой каталог | `namei -l /opt/httpd/logs`<br>`ls -ld /run/httpd` | Назначить владельца: `chown -R apache:apache /opt/httpd/logs`. В systemd использовать директиву `RuntimeDirectory`. |
| `(28)No space left on device: AH00020: Configuration Failed: ... System mutex lock error` | Коллизия файлов мьютексов shared memory между несколькими инстансами | `ipcs -s`<br>`ls -la /run/httpd*/mutex*` | Развести инстансы: задать уникальные пути в директиве `Mutex default:/run/httpd-instance-%i/`. |
| Ошибка запуска systemd: `status=203/EXEC` | Неверный путь к бинарнику `httpd` либо блокировка SELinux | `journalctl -u httpd.service -e`<br>`ausearch -m avc -ts recent` | Исправить путь `ExecStart`. Применить верный контекст `restorecon -v /opt/httpd/bin/httpd`. |
| `apxs: command not found` | Каталог `bin/` не добавлен в системную переменную `PATH` | `echo $PATH` | Использовать абсолютный путь `/opt/httpd/bin/apxs` либо добавить путь в `/etc/profile.d/httpd.sh`. |

---

## Лучшие практики

1. **Принцип минимализма модулей:** При компиляции отключать неиспользуемые модули (`--disable-cgi`, `--disable-status`, `--disable-autoindex`, `--disable-userdir`). Меньше скомпилированного кода — меньше потенциальных векторов атак и ниже потребление оперативной памяти.
2. **Воспроизводимость сборок:** Всегда сохранять сгенерированный файл `/opt/httpd/build/config.nice`. Это гарантирует возможность собрать идентичный бинарник при плановом обновлении версии или миграции на новый сервер.
3. **Изоляция через префиксы и симлинки:** Устанавливать сборки в версионированные пути (`/opt/httpd-2.4.69`), используя символическую ссылку `/opt/httpd` для переключения. Это делает обновления и откаты атомарными и предсказуемыми.
4. **Харденинг компилятора:** Использовать флаги `-D_FORTIFY_SOURCE=2`, `-fstack-protector-strong`, Full RELRO (`-Wl,-z,relro,-z,now`) и PIE (`--enable-pie`).
5. **Изоляция служб systemd:** Никогда не запускать рабочие процессы Apache под пользователем `root`. В systemd-юните обязательно включать механизмы sandboxing (`ProtectSystem=full`, `ProtectHome=true`, `PrivateTmp=true`, фильтрацию прав через `CapabilityBoundingSet`).
6. **Полная деинсталляция (Clean Uninstall):** Поскольку в исходном коде Apache цель `make uninstall` не всегда удаляет все установленные файлы, корректный процесс очистки выполняется по шагам:
   ```bash
   # Остановка и отключение служб
   sudo systemctl disable --now httpd.service httpd@*
   sudo rm -f /etc/systemd/system/httpd.service /etc/systemd/system/httpd@.service
   sudo systemctl daemon-reload

   # Удаление установленных каталогов
   sudo rm -rf /opt/httpd /opt/httpd-* /etc/httpd-instances /var/log/httpd-instances /run/httpd*

   # Удаление сервисного пользователя (при необходимости)
   sudo userdel -r apache
   ```

---

## Дополнительная информация

### См. также

*   [Обзор Apache](./apache_overview.md) — базовая архитектура, дерево директив и жизненный цикл запросов.
*   [Харденинг и безопасность Apache](./apache_hardening.md) — системная изоляция, конфигурация mod_security и заголовков безопасности.
*   [Оптимизация производительности Apache](./apache_performance_tuning.md) — настройка параметров MPM event, тюнинг сокетов и сетевого стека Linux.
*   [Контейнеризация Apache](./apache-in-docker.md) — создание воспроизводимых контейнеров на базе Docker.
*   [Сборка Nginx из исходного кода](../Nginx/Core/nginx_build_from_source.md) — альтернативный пайплайн компиляции высокопроизводительного обратного прокси.