# Географическая фильтрация и модуль GeoIP2 в Nginx

**Актуально для:** Nginx 1.26+ / 1.28+, ngx_http_geoip2_module 3.4+, libmaxminddb 1.7+

## Определения

**`ngx_http_geoip2_module`** — сторонний динамический модуль Nginx, созданный для интеграции с библиотекой `libmaxminddb` и базами данных MaxMind GeoIP2 / GeoLite2 в бинарном формате `.mmdb`. Позволяет определять страну, город, координаты, почтовый индекс и автономную систему (ASN) клиента по его IP-адресу.

**MaxMind GeoLite2 / GeoIP2** — отраслевой стандарт баз данных соответствия IP-адресов географическим локациям. GeoLite2 — бесплатная распространяемая версия с еженедельным обновлением; GeoIP2 — коммерческая база повышенной точности.

**Формат `.mmdb` (MaxMind DB)** — оптимизированный бинарный формат баз данных со структурой двоичного дерева (radix tree), обеспечивающий поиск IP-адреса за константное время $O(1)$ без накладных расходов традиционных реляционных СУБД.

**`libmaxminddb`** — высокопроизводительная библиотека на языке Си, предоставляющая C API для чтения файлов `.mmdb` с отображением файла в виртуальную память через системный вызов `mmap()`.

**`geoipupdate`** — официальная консольная утилита MaxMind для автоматического скачивания и обновления баз данных GeoLite2/GeoIP2 по расписанию через cron или systemd-таймеры.

**ASN (Autonomous System Number)** — номер автономной системы интернет-провайдера или дата-центра. Фильтрация по ASN позволяет блокировать трафик целых хостинг-провайдеров и облачных ферм ботов (например, DigitalOcean, OVH, Hetzner), откуда часто исходят атаки.

**Real-IP привязка** — механизм передачи реального адреса клиента из заголовков `X-Forwarded-For` или `X-Real-IP` в модуль GeoIP2, предотвращающий ложное определение геолокации по IP-адресу промежуточного балансировщика, CDN или прокси.

---

## Архитектура и основные концепции

### Принцип работы модуля и структура MMDB

Модуль `ngx_http_geoip2_module` кардинально отличается от устаревшего встроенного модуля `ngx_http_geoip_module` (работавшего со старым форматом GeoIP Legacy `.dat`, поддержка которого прекращена в 2018 году):

1. **Отображение в память (`mmap`):** При старте Nginx модуль открывает файл базы данных `.mmdb` и отображает его в адресное пространство процесса через вызов ядра `mmap()`. Это позволяет нескольким воркерам Nginx совместно использовать одну область оперативной памяти без дублирования данных.
2. **Атомарный поиск:** Для каждого входящего запроса модуль извлекает IP-адрес клиента (по умолчанию `$remote_addr`, либо реальный адрес после обработки модулем `ngx_http_realip_module`), выполняет быстрый бинарный поиск по дереву префиксов и сохраняет запрошенные метаданные в строковые переменные Nginx.
3. **Безопасная ротация:** Файлы баз данных `.mmdb` нельзя перезаписывать «на месте» (in-place) во время работы Nginx, так как усечение файла приводит к падению воркеров с ошибкой `SIGBUS`. Обновление должно выполняться атомарным перемещением нового файла (`mv`).

```text
Входящий HTTP-запрос
         ↓
[ ngx_http_realip_module ] ──► Преобразует X-Forwarded-For в доверенный $remote_addr
         ↓
[ ngx_http_geoip2_module ] ──► mmap(/var/lib/GeoIP/GeoLite2-Country.mmdb)
         ↓
Извлечение ISO-кода ($geoip2_data_country_code = "RU", "DE", "CN")
         ↓
[ Директива map ]          ──► $access_allowed (1 / 0)
         ↓
[ Блок location ]          ──► if ($access_allowed = 0) { return 403; }
```

---

## Практические сценарии

### Сценарий 1: Установка модуля и настройка автоматического обновления баз

#### 1. Установка зависимостей на Debian / Ubuntu

```bash
# 1. Установка библиотеки libmaxminddb и утилиты обновления
sudo apt update
sudo apt install -y libmaxminddb0 libmaxminddb-dev mmdb-bin geoipupdate

# 2. Установка динамического модуля для официального Nginx
# Если Nginx установлен из официального репозитория nginx.org:
sudo apt install -y nginx-module-geoip2
```

#### 2. Регистрация и настройка `/etc/GeoIP.conf`

Для загрузки бесплатных баз GeoLite2 требуется бесплатный аккаунт на [MaxMind.com](https://www.maxmind.com) и генерация лицензионного ключа (Account ID и License Key):

```ini
# /etc/GeoIP.conf
AccountID 123456
LicenseKey a1b2c3d4e5f6g7h8
EditionIDs GeoLite2-Country GeoLite2-City GeoLite2-ASN
```

#### 3. Первичная загрузка и настройка systemd timer

```bash
# Запуск утилиты скачивания баз
sudo geoipupdate -v
# → /var/lib/GeoIP/GeoLite2-Country.mmdb updated
# → /var/lib/GeoIP/GeoLite2-City.mmdb updated
# → /var/lib/GeoIP/GeoLite2-ASN.mmdb updated

# Включение еженедельного таймера автоматического обновления
sudo systemctl enable --now geoipupdate.timer
sudo systemctl status geoipupdate.timer
# → Active: active (waiting)
```

---

### Сценарий 2: Блокировка стран по черному списку с возвратом 403 Forbidden

Задача: Заблокировать доступ к публичному веб-сайту для стран с аномальной вредоносной активностью или ограничениями комплаенса.

Конфигурация `/etc/nginx/conf.d/geoip_blacklist.conf`:

```nginx
# Подключение динамического модуля в начале /etc/nginx/nginx.conf (в контексте main):
# load_module modules/ngx_http_geoip2_module.so;

# 1. Чтение базы стран и связывание переменной
geoip2 /var/lib/GeoIP/GeoLite2-Country.mmdb {
    auto_reload 15m;
    $geoip2_data_country_code default=XX country iso_code;
    $geoip2_data_country_name country names en;
}

# 2. Черный список стран (0 - разрешено, 1 - заблокировано)
# XX - неизвестная страна / локальная сеть (RFC 1918)
map $geoip2_data_country_code $is_blocked_country {
    default 0;
    CN      1; # Китай
    IR      1; # Иран
    KP      1; # Северная Корея
}

server {
    listen 443 ssl;
    server_name public.example.corp;

    ssl_certificate     /etc/ssl/certs/public.crt;
    ssl_certificate_key /etc/ssl/private/public.key;

    # Глобальная блокировка для всего виртуального хоста
    if ($is_blocked_country) {
        return 403 "Access denied from your region\n";
    }

    location / {
        proxy_pass http://backend_cluster;
        proxy_set_header Host $host;
        proxy_set_header X-Country-Code $geoip2_data_country_code;
    }
}
```

---

### Сценарий 3: Ограничение доступа к панели управления (`/admin`) по белому списку стран

Задача: Разрешить доступ к административному интерфейсу только сотрудникам, находящимся в Российской Федерации (`RU`) и Казахстане (`KZ`), а также локальным подсетям офиса (`XX`).

Конфигурация `/etc/nginx/conf.d/admin_whitelist.conf`:

```nginx
# Белый список стран для доступа к служебным ресурсам
map $geoip2_data_country_code $admin_access_allowed {
    default 0;
    RU      1; # Россия
    KZ      1; # Казахстан
    BY      1; # Беларусь
    XX      1; # Локальные корпоративные адреса (10.0.0.0/8, 192.168.0.0/16)
}

server {
    listen 443 ssl;
    server_name portal.corp.example;

    ssl_certificate     /etc/ssl/certs/portal.crt;
    ssl_certificate_key /etc/ssl/private/portal.key;

    # Публичная часть портала доступна отовсюду
    location / {
        proxy_pass http://backend_portal;
    }

    # Защищенный административный раздел
    location /admin/ {
        if ($admin_access_allowed = 0) {
            return 403;
        }

        # Дополнительная защита базовой аутентификацией
        auth_basic "Restricted Admin Area";
        auth_basic_user_file /etc/nginx/.htpasswd;

        proxy_pass http://backend_portal;
    }
}
```

---

### Сценарий 4: Гео-фильтрация за внешним балансировщиком или CDN (Real-IP)

Критически важный сценарий: если перед Nginx стоит балансировщик (HAProxy, Keepalived, Cloudflare или корпоративный WAF), значение `$remote_addr` будет содержать IP-адрес этого прокси. В результате все клиенты получат код страны дата-центра прокси.

Для корректной работы GeoIP2 необходимо сначала включить модуль `ngx_http_realip_module`.

Конфигурация `/etc/nginx/conf.d/geoip_realip.conf`:

```nginx
# Доверенные прокси-серверы и балансировщики
set_real_ip_from 192.168.1.0/24;
set_real_ip_from 10.0.0.100;

# Заголовок, из которого извлекается реальный IP клиента
real_ip_header X-Forwarded-For;
real_ip_recursive on;

# Чтение базы данных GeoIP2 с явным указанием переменной $remote_addr
# После работы real_ip $remote_addr содержит реальный адрес клиента
geoip2 /var/lib/GeoIP/GeoLite2-Country.mmdb {
    auto_reload 30m;
    $geoip2_data_country_code default=XX source=$remote_addr country iso_code;
}

# Отдельная база автономных систем для блокировки хостинг-ботов
geoip2 /var/lib/GeoIP/GeoLite2-ASN.mmdb {
    auto_reload 30m;
    $geoip2_data_asn default=0 autonomous_system_number;
    $geoip2_data_as_org default=Unknown autonomous_system_organization;
}

# Блокировка дата-центров, часто используемых ботнетами
map $geoip2_data_asn $is_hosting_provider {
    default 0;
    14061   1; # DigitalOcean
    16276   1; # OVH
    24940   1; # Hetzner
}

server {
    listen 80;
    server_name api.example.corp;

    location / {
        if ($is_hosting_provider) {
            return 429 "Automated requests from cloud providers are prohibited\n";
        }

        proxy_pass http://backend_api;
    }
}
```

---

## Операции и команды

### 1. Проверка информации по IP через утилиту `mmdblookup`

Консольная утилита пакета `mmdb-bin` позволяет моментально проверить, какие данные вернет база по конкретному IP-адресу:

```bash
# Проверка страны для публичного DNS-адреса (например, 8.8.8.8)
mmdblookup --file /var/lib/GeoIP/GeoLite2-Country.mmdb --ip 8.8.8.8 country iso_code
# → "US" <utf8_string>

# Проверка автономной системы (ASN)
mmdblookup --file /var/lib/GeoIP/GeoLite2-ASN.mmdb --ip 8.8.8.8 autonomous_system_organization
# → "GOOGLE" <utf8_string>

# Проверка локального адреса RFC 1918 (должен вернуть ошибку отсутствия записи)
mmdblookup --file /var/lib/GeoIP/GeoLite2-Country.mmdb --ip 192.168.1.1 country iso_code
# → Error: The address 192.168.1.1 is not in the database.
```

### 2. Тестирование блокировки Nginx через curl с подменой Real-IP

```bash
# Тест 1: Запрос с реального внешнего IP США (разрешен)
curl -s -i -H "X-Forwarded-For: 8.8.8.8" https://public.example.corp/
# → HTTP/1.1 200 OK

# Тест 2: Запрос с китайского IP (например, 114.114.114.114 - блокируется)
curl -s -i -H "X-Forwarded-For: 114.114.114.114" https://public.example.corp/
# → HTTP/1.1 403 Forbidden
# → Access denied from your region
```

### 3. Ручное обновление баз данных и проверка статуса таймера

```bash
# Принудительный запуск обновления базы
sudo geoipupdate -v
# → GeoIP.conf: Reading configuration file...
# → Database /var/lib/GeoIP/GeoLite2-Country.mmdb is up to date

# Проверка журнала таймера в systemd
journalctl -u geoipupdate.service -n 20 --no-pager
```

---

## Устранение неполадок

| Код ошибки / Симптом | Причина проблемы | Диагностика | Решение |
| :--- | :--- | :--- | :--- |
| `nginx: [emerg] unknown directive "geoip2"` | Не загружен динамический модуль `ngx_http_geoip2_module.so`. | Проверить наличие `load_module` в первой строке `/etc/nginx/nginx.conf`. | Добавить `load_module modules/ngx_http_geoip2_module.so;` в глобальный контекст `main`. |
| Переменная `$geoip2_data_country_code` возвращает `XX` для всех клиентов | 1. Запросы идут через балансировщик, возвращается локальный IP.<br>2. Запросы исходят из локальной сети (10.0.0.0/8, 192.168.0.0/16). | Вывести значение `$remote_addr` и `$geoip2_data_country_code` в заголовок ответа или `access.log`. | Настроить блок `set_real_ip_from` и `real_ip_header X-Forwarded-For;`. |
| Ошибка ядра `SIGBUS` и падение рабочих процессов Nginx (worker crash) | Файл `.mmdb` был перезаписан «на месте» утилитой или скриптом во время чтения воркерами через `mmap`. | `dmesg \| grep -E 'nginx.*segfault\|SIGBUS'` | Использовать только атомарное обновление файлов: `mv new.mmdb current.mmdb` (утилита `geoipupdate` делает это автоматически). |
| База данных не обновляется по таймеру | Ошибка в `/etc/GeoIP.conf` (неверный AccountID или истекший LicenseKey). | Запустить `geoipupdate -v` вручную и проанализировать HTTP-ответ сервера MaxMind. | Сгенерировать новый License Key в панели MaxMind и обновить `/etc/GeoIP.conf`. |

---

## Рекомендации и лучшие практики (Production & SRE)

1. **Всегда задавайте значение по умолчанию (`default=XX`):** Если IP-адрес клиента отсутствует в базе данных (локальные сети RFC 1918, loopback, новые диапазоны адресов), модуль присвоит переменной значение по умолчанию. Без `default` переменная останется пустой (`""`), что может привести к непредсказуемой логике в директивах `map`.
2. **Не используйте GeoIP как единственную меру защиты:** Геолокация легко обходится с помощью прокси-серверов, VPN и Tor. Используйте Geo-блокировку для отсечения массового автоматизированного сканирования, но не полагайтесь на нее для защиты от таргетированных атак.
3. **Используйте параметр `auto_reload`:** Директива `auto_reload 15m;` внутри блока `geoip2` предписывает Nginx периодически проверять дату модификации файла `.mmdb` на диске и перечитывать его без необходимости выполнять `nginx -s reload`.
4. **Комбинируйте фильтрацию по стране и ASN:** Блокировка ASN хостинг-провайдеров (`DigitalOcean`, `Hetzner`, `AWS`) на чувствительных эндпоинтах авторизации отсекает до 80% ботнетов, использующих арендованные VPS для перебора паролей.

---

## Дополнительная информация

### Связанные темы в базе знаний

- [Безопасность веб-сервера Nginx и Angie](nginx_security_guide.md) — многоуровневая архитектура защиты, rate limiting и security headers.
- [Фильтрация GeoIP в nftables](../../Linux/Networking/Settings/tools/nftables/geoip_filtering.md) — отбрасывание нежелательного гео-трафика на уровне ядра Linux до попадания в веб-сервер.
- [Контроль доступа в Angie](../Angie/angie_access_control.md) — синтаксис директивы `geoip2` и списки доступа в сервере Angie.
- [Анализ журналов веб-сервера Nginx](../Operations/nginx_log_analysis.md) — обогащение журналов доступа кодами стран и интеграция с GoAccess.

### Официальная документация и репозитории

- [Репозиторий ngx_http_geoip2_module на GitHub](https://github.com/leev/ngx_http_geoip2_module)
- [Официальная документация MaxMind GeoIP2 / GeoLite2](https://dev.maxmind.com/geoip/)
- [Утилита geoipupdate на GitHub](https://github.com/maxmind/geoipupdate)
