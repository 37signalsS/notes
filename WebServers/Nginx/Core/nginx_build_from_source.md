# Сборка Nginx из исходников и динамические модули

## Определения

**Сборка из исходников** — компиляция Nginx из исходного кода с параметрами `./configure`. Используется, когда нужны нестандартные модули, оптимизация под конкретное оборудование, свежая mainline-версия или корректировка путей установки.

**Динамические модули** — `.so`-модули (`.so`), подключаемые в конфиг директивой `load_module`. Компилируются отдельно от бинарника Nginx, что позволяет добавить функциональность (GeoIP2, VTS, ModSecurity, njs, Brotli, Image-Filter) без пересборки всего сервера.

Распределённые сборки (apt/dnf) обычно включают динамические модули в отдельные пакеты (`nginx-module-*`), а официальный репозиторий nginx.org собирает модули для версии Nginx, точно совпадающей с основной.

## Основные концепции

### Жизненный цикл сборки

1. **Подготовка зависимостей** — компилятор, autoconf, PCRE, zlib, OpenSSL (для TLS).
2. **`./configure`** — обнаружение библиотек, выбор статических/динамических модулей, определение путей и флагов.
3. **`make`** — сборка.
4. **`make install`** — установка в целевой `--prefix`.

### Ключевые параметры `./configure`

| Флаг | Назначение |
| :--- | :--- |
| `--prefix=/etc/nginx` | Корневой каталог (конфиги, сайты) |
| `--with-http_ssl_module` | Статический TLS-модуль |
| `--with-stream` / `--with-stream_ssl_module` | Модуль L4 (TCP/UDP) |
| `--with-http_v2_module` | HTTP/2 |
| `--with-http_stub_status_module` | Эндпоинт stub_status |
| `--with-http_realip_module` | Переопределение реального IP клиента |
| `--add-module=/path` | Подключение статического модуля (сборка в бинарник) |
| `--add-dynamic-module=/path` | Подключение динамического модуля (`load_module`) |
| `--with-debug` | Логирование уровня debug |
| `--with-openssl=/path` | Использовать свой OpenSSL (например, патченный или новее системного) |
| `--without-http_*` | Исключить ненужные модули (уменьшение размера/риска) |

### Статические vs динамические модули

- **Статические:** встраиваются в бинарник — нет `load_module`, но «всё всегда включено».
- **Динамические:** загружаются через `load_module modules/ngx_http_*.so;` в начале `nginx.conf`. Плюс — не нужно пересобирать Nginx при добавлении нового модуля; связанность с конкретной версией — если бинарник Nginx обновился, модули нужно пересобрать (ABI-несовместимость).
- Определить, какие модули загружены/встроены: `nginx -V` показывает `configure arguments`, а `load_module` — в конфиге.

### Совместимость с дистрибутивом

Для безопасности обновлений правильнее использовать **официальные репозитории** (nginx.org) или пакеты дистрибутива. Сборка из исходников означает ручное сопровождение обновлений. Применяют её обычно для:

- свежих возможностей mainline (HTTP/3, njs, новые директивы);
- вендорных патчей (например, с TLS-форточками);
- установки в изолированные среды (appliance, специфические ОС);
- кастомизации под модуль, отсутствующий в репозитории.

## Практические сценарии

### Предварительные требования

```bash
# Debian/Ubuntu — зависимости для компиляции
sudo apt install -y build-essential libpcre3-dev libssl-dev zlib1g-dev
```

### Сценарий 1: Минимальная сборка с динамическим модулем (пример — VTS)

Скачивание исходников с nginx.org и сборка:

```bash
cd /usr/local/src
wget https://nginx.org/download/nginx-1.27.0.tar.gz
tar xzf nginx-1.27.0.tar.gz && cd nginx-1.27.0

./configure \
  --prefix=/etc/nginx \
  --sbin-path=/usr/sbin/nginx \
  --modules-path=/usr/lib/nginx/modules \
  --conf-path=/etc/nginx/nginx.conf \
  --with-http_ssl_module \
  --with-http_v2_module \
  --with-http_stub_status_module \
  --with-stream \
  --add-dynamic-module=/usr/local/src/ngx_http_vts_module-0.2.2
make -j$(nproc)
sudo make install
```

Проверка:

```bash
nginx -V
# → nginx version: nginx/1.27.0
# → configure arguments: --prefix=/etc/nginx ... --add-dynamic-module=...
ls /usr/lib/nginx/modules/
# → ngx_http_vhost_traffic_status_module.so
```

### Сценарий 2: Подключение динамического модуля через load_module

```nginx
# /etc/nginx/nginx.conf (начало, вне http/events)
load_module /usr/lib/nginx/modules/ngx_http_vhost_traffic_status_module.so;
```

Валидация:

```bash
nginx -t
# → nginx: configuration file /etc/nginx/nginx.conf test is successful
systemctl reload nginx
```

Если модуль загружен — в `nginx -V` не появится дополнительных пассяжей (динамический), но конфиг примет директивы модуля (`vhost_traffic_status_zone` и т.п.).

### Сценарий 3: Сборка системного или официального модуля без пересборки Nginx

Многие модули имеют готовые пакеты — предпочитайте их:

```bash
# Debian/Ubuntu (репозиторий nginx.org) — пример VTS/GeIP2
sudo apt install -y libnginx-mod-http-vts libnginx-mod-stream-geoip2
```

Для ручной сборки модуля (совместимая версия) — паттерн из [настройки VTS-мониторинга](../Operations/nginx_vts_monitoring_setup.md): берётся исходник **той же версии**, что и установленный Nginx, компилируется `--add-dynamic-module`, копируется в `/usr/lib/nginx/modules/`, затем `load_module` + reload.

### Сценарий 4: Компиляция с собственным OpenSSL (например, для новых cipher/TLS)

```bash
wget https://www.openssl.org/source/openssl-3.0.13.tar.gz
./configure \
  --prefix=/etc/nginx \
  --sbin-path=/usr/sbin/nginx \
  --with-http_ssl_module \
  --with-openssl=/usr/local/src/openssl-3.0.13 \
  --with-debug
make -j$(nproc) && sudo make install
```

`nginx -V` покажет `built with OpenSSL 3.0.13` — все шифры TLS 1.3 будут доступны из вашей библиотеки.

## Операции и команды

| Команда | Назначение |
| :--- | :--- |
| `nginx -V` | Версия и `configure arguments` |
| `nginx -V 2>&1 | tr ' ' '\n' | grep module` | Список встроенных модулей |
| `ls /usr/lib/nginx/modules/` | Динамические модули на диске |
| `load_module modules/...so;` | Подключение динамического модуля |
| `./configure --help` | Все доступные флаги |
| `nginx -t` / `nginx -s reload` | Валидация и применение (после установки модуля) |

## Устранение неполадок

### `undefined symbol` при load_module или отказ загрузки

**Причина:** модуль собран для другой версии/ABI Nginx.

**Решение:** пересоберите модуль с исходниками той же версии, что и установленный Nginx. Проверьте: `nginx -v` vs версия исходников модуля.

### Модуль загружен, но директивы не работают («unknown directive»)

**Причина:** `load_module` не в начале файла, либо модуль статический, а вы подключаете лишний `.so`.

**Решение:** ставьте `load_module` **до** любых других директив (вне `http`/`events`); убедитесь, что путь правильный: `nginx -t` сообщит точную ошибку.

### Не найден PCRE/OpenSSL при `./configure`

**Причина:** не установлены `-dev` пакеты.

**Решение:** `sudo apt install libpcre3-dev libssl-dev zlib1g-dev` (Debian) или соответствующие `*-devel` (RHEL).

### После `make install` не работает systemd-юнит

**Причина:** при сборке указаны нестандартные пути (`--prefix`), а юнит использует `/etc/nginx` и `/run/nginx.pid`.

**Решение:** передайте явные `--conf-path=/etc/nginx/nginx.conf`, `--pid-path=/run/nginx.pid`, `--sbin-path=/usr/sbin/nginx` и т.д., либо адаптируйте юнит под пути сборки.

## Лучшие практики

- **Предпочитайте официальные репозитории** (nginx.org) дистрибутива и пакетные модули — сборку из исходников применяйте только при реальной необходимости.
- **Версионируйте сборку:** фиксируйте версии исходников и флаги `./configure` в CI/скриптах, чтобы воспроизводить бинарник (ансибл/докер).
- **Динамические модули** — по умолчанию для сторонних дополнений; статические — для базовой функциональности.
- После сборки обязательно `nginx -t` перед reload; держите резервную копию старого бинарника.
- Для оптимизации учитывайте целевые `--with-*`/`--without-*`: не включайте лишних модулей (меньше поверхность и память).
- В контейнерных сборках собирайте модуль в отдельном stage и копируйте `.so` в конечный образ (см. [Nginx в Docker](../Scenarios/nginx_in_docker.md)).

## Дополнительная информация

### Связанные темы

- **[Настройка мониторинга Nginx с VTS-модулем](../Operations/nginx_vts_monitoring_setup.md)** — полный пример сборки динамического модуля.
- **[Установка и базовая настройка Nginx](../Core/nginx_setup.md)** — репозитории и стандартная установка.
- **[njs в Nginx](../Core/nginx_njs_module.md)** — скриптовый модуль, устанавливаемый как динамический.

### См. также

- [Обзор Nginx](../Core/nginx_overview.md) — архитектура и форки (включая OpenResty).