# Maintenance-режим в Nginx

## Определения

**Maintenance-режим** — управляемая временная остановка доступа к сервису веб-сервером, при котором вместо обычного контента или прокси-ответа клиент получает заранее подготовленную страницу с информацией о технических работах. В отличие от пассивных ошибок (502, 504), maintenance-режим включается **сознательно и планируемо** администратором.

**Файл-флаг (Flag file)** — файл на файловой системе, наличие, отсутствие или содержимое которого определяет состояние maintenance-режима. Это простой механизм переключения, не требующий изменения конфигурации Nginx.

**Конфигурационный include** — механизм подключения внешнего файла конфигурации директивой `include`, позволяющий динамически менять поведение Nginx без перезаписи основного конфига. Подробнее о механизме `include` в **[Установка и базовая настройка Nginx](../Core/nginx_setup.md)**.

**Map-директива** — директива уровня `http`, создающая переменную на основе значений других переменных или внешних файлов. Позволяет реализовать maintenance-режим без симлинков. Подробнее о `map` в **[Rewrite правила и try_files](../Core/nginx_rewrite_rules_and_try_files.md)**.

**Именованная локация (`@name`)** — блок `location`, идентифицируемый именем после символа `@`, не участвующий в стандартном сопоставлении URI и вызываемый только явно через `error_page` или `rewrite ... last`. Подробнее в **[Внутренняя маршрутизация Nginx](../Core/Location/internal_routing.md)**.

**Грациозная перезагрузка (Graceful reload)** — перезагрузка конфигурации Nginx без разрыва существующих соединений. Выполняется сигналом `HUP` (`nginx -s reload` или `systemctl reload nginx`). Воркеры завершают текущие запросы и переводятся на новый конфиг. В отличие от `restart`, graceful reload не сбрасывает соединения клиентов.

**Health check (проверка здоровья)** — автоматический запрос к бэкенду для определения его доступности. В контексте maintenance-режима health check позволяет убедиться, что сервис готов к приёму трафика перед отключением заглушки.

## Базовые концепции

### Зачем нужен maintenance-режим

Существует два типичных сценария применения:

1. **Плановые работы.** Сервису известно заранее о предстоящем даунтайме (например, с 20:00). Включив maintenance-режим, администратор гарантирует, что все клиенты получат единообразную информационную страницу с указанием времени завершения вместо того, чтобы видели случайные 500/502/504 ошибки.

2. **Инцидент в продакшене.** Сервис частично или полностью упал. Инженеры решают проблему, а клиенты в это время видят непредсказуемые таймауты и ошибки. Включив maintenance-режим, команда создаёт для пользователей спокойную, предсказуемую картину, пока проблема не будет решена.

### Почему возвращать HTTP 503, а не 200

Даже при том, что клиент получает полностью работающую HTML-страницу, сервер должен возвращать код **503 Service Unavailable**. Вот почему:

1. **SEO и индексация.** Код 503 не индексируется поисковиками (Google, Bing). Если бы возвращался `200 OK`, поисковый робот мог бы индексировать содержимое maintenance-страницы и запомнить её вместо реального контента сайта. Подробнее о семантике 503 в **[HTTP-коды ответа](../../Networking/Protocols/HTTP/http_status_codes.md)**.

2. **Поведение клиентских библиотек и балансировщиков.** Внешние балансировщики (F5 BIG-IP, HAProxy, Kemp) и HTTP-клиенты могут использовать код ошибки для принятия решений о переключении на резервный бэкенд. Возвращая `503`, вы сигнализируете, что проблема временная.

3. **Заголовок `Retry-After`.** Спецификация RFC 9110 требует, чтобы ответ 503 мог включать заголовок `Retry-After`, указывающий клиенту, через сколько секунд (или в какой момент времени) можно повторить запрос. Это помогает избежать **thundering herd** — массового одновременного повторения запросов всех клиентов ровно в момент завершения работ.

4. **Кэширование.** Клиентские браузеры и промежуточные кэши (Varnish, Nginx proxy_cache) могут сохранить maintenance-страницу, если отсутствуют директивы запрета кэширования. Это приведёт к тому, что после завершения работы пользователи продолжат видеть заглушку из кэша.

### Почему подход с `if (-f ...)` не рекомендуется

Широко распространённый, но **не рекомендуемый** подход использует директиву `if` для проверки наличия файла-флага на каждом запросе:

```nginx
location / {
    if (-f /etc/nginx/maintenance.flag) {
        return 503;
    }
    proxy_pass http://127.0.0.1:3000;
}
```

Этот подход имеет серьёзные недостатки:

- **Файловая операция на каждом запросе.** Проверка существования файла (`stat()`) выполняется при каждом HTTP-запросе. На высоконагруженных продакшенах это создаёт лишнюю нагрузку на файловую систему и может стать узким местом.

- **`if` внутри `location` — антипаттерн.** В Nginx директива `if` внутри блока `location` имеет неопределённое поведение и может конфликтовать с директивами вроде `proxy_pass`. Сообщество Nginx известно правилом **"If Is Evil"** — использовать `if` только в контексте `server` и только для `return`/`rewrite`.

- **Конфигурация перезагружается.** Любое изменение логики (например, добавление исключений) требует перезаписи конфигурационного файла и перезагрузки Nginx.

### Подход через `include` и симлинк

Рекомендуемый подход основан на динамическом переключении конфигурационного файла через симлинк. Логика проста: в обычном режиме `include` подключает пустой файл, в режиме maintenance — файл с `return 503`:

```nginx
# maintenance_off.conf — пустой файл (ничего не делает)
# maintenance_on.conf  — содержит: return 503;
```

Переключение режима не требует правки конфигурации — достаточно сменить цель симлинка и выполнить `nginx -t && systemctl reload nginx`. Подробнее о `reload` в **[Диагностика и устранение неисправностей Nginx](../Operations/nginx_troubleshooting.md)**.

### Подход через `map` и внешний файл

Альтернативный подход использует директиву `map` на уровне `http` для чтения внешнего файла-флага. Преимущество — отсутствие симлинков, управление через изменение содержимого файла. Подходит преимущественно для статических сайтов или простых прокси-конфигураций. Подробнее о `map` в **[Rewrite правила и try_files](../Core/nginx_rewrite_rules_and_try_files.md)**.

## Практические сценарии

### Сценарий 1: Реализация через include и симлинк

#### Предпосылки

- Nginx установлен и работает (подробнее в **[Установка и базовая настройка Nginx](../Core/nginx_setup.md)**).
- Есть доступ к конфигурационным файлам (обычно `/etc/nginx/`).
- Статическая страница `maintenance.html` готова к развёртыванию.

#### Пошаговая реализация

**Шаг 1. Создайте директорию для файлов maintenance:**

```bash
mkdir -p /etc/nginx/maintenance
```

**Шаг 2. Разверните страницу maintenance:**

Создайте файл `maintenance.html` с информацией о работах. Рекомендуется использовать валидный HTML5 с указанием времени окончания и контактов:

```html
<!DOCTYPE html>
<html lang="ru">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Сервис временно недоступен</title>
</head>
<body>
    <h1>Сервис временно недоступен</h1>
    <p>Проводятся технические работы. Ожидайте завершения.</p>
    <p>Ожидаемое время завершения: до 22:00 МСК.</p>
</body>
</html>
```

```bash
# Размещаем страницу на сервере
cp maintenance.html /etc/nginx/maintenance/maintenance.html
chown root:root /etc/nginx/maintenance/maintenance.html
chmod 644 /etc/nginx/maintenance/maintenance.html
```

**Шаг 3. Создайте конфигурационные файлы для включения/выключения:**

```bash
# Файл с включённым maintenance-режимом
echo 'return 503;' > /etc/nginx/maintenance/maintenance_on.conf

# Пустой файл для обычного режима
touch /etc/nginx/maintenance/maintenance_off.conf
```

**Шаг 4. Создайте симлинк-переключатель:**

```bash
ln -sfn /etc/nginx/maintenance/maintenance_off.conf /etc/nginx/maintenance/maintenance_current.conf
```

**Шаг 5. Настройте блок `server` в конфигурации Nginx:**

```nginx
server {
    listen 80;
    server_name example.com;

    # Редирект при 503 на нашу страницу
    error_page 503 /maintenance.html;

    # Внутренний location для отдачи страницы (недоступен внешне)
    location = /maintenance.html {
        internal;
        root /etc/nginx/maintenance;
        add_header Cache-Control "no-store, no-cache, must-revalidate" always;
        add_header Retry-After "3600" always;
    }

    location / {
        # Переключатель maintenance-режима
        include /etc/nginx/maintenance/maintenance_current.conf;

        proxy_pass http://127.0.0.1:3000;
    }
}
```

**Что здесь происходит:**

1. Директива `error_page 503 /maintenance.html;` указывает Nginx выполнять внутренний редирект на `/maintenance.html` при любой ошибке 503.
2. Блок `location = /maintenance.html` использует `internal;`, чтобы страница была **недоступна напрямую** клиентом (подробнее о `internal` в **[Внутренняя маршрутизация Nginx](../Core/Location/internal_routing.md)**). Начиная с Nginx 1.25.x прямой запрос возвращает `404 Not Found`; в более старых версиях мог возвращаться `403 Forbidden`.
3. Заголовки `Cache-Control` и `Retry-After` гарантируют, что браузер не кэширует страницу и знает, когда повторить запрос.
4. В `location /` директива `include` подключает текущий конфигурационный файл. В обычном режиме это пустой файл — Nginx просто продолжает выполнять `proxy_pass`. В режиме maintenance файл содержит `return 503;` — Nginx сразу возвращает 503, не достигая `proxy_pass`.

#### Включение maintenance-режима

```bash
# Переключаем симлинк на файл с return 503
ln -sfn /etc/nginx/maintenance/maintenance_on.conf /etc/nginx/maintenance/maintenance_current.conf

# Валидируем и перезагружаем
nginx -t && systemctl reload nginx
```

**Ожидаемый результат:** Любой запрос к сайту теперь возвращает `503` с HTML-страницей maintenance. Проверьте:

```bash
curl -s -o /dev/null -w "%{http_code}" http://example.com
# → 503

curl -I http://example.com
# → HTTP/1.1 503 Service Unavailable
# → Retry-After: 3600
# → Cache-Control: no-store, no-cache, must-revalidate
```

#### Отключение maintenance-режима

```bash
# Переключаем симлинк на пустой файл
ln -sfn /etc/nginx/maintenance/maintenance_off.conf /etc/nginx/maintenance/maintenance_current.conf

# Валидируем и перезагружаем
nginx -t && systemctl reload nginx
```

**Ожидаемый результат:** Запросы снова проксируются к бэкенду.

### Сценарий 2: Автоматизация переключения

Вручную каждый раз выполнять `ln -sfn` и `reload` неудобно. Автоматизируйте с помощью скрипта или systemd-юнита:

```bash
#!/bin/bash
# /usr/local/bin/nginx-maintenance.sh

MAINT_DIR="/etc/nginx/maintenance"
CURRENT_SYM="${MAINT_DIR}/maintenance_current.conf"
ON="${MAINT_DIR}/maintenance_on.conf"
OFF="${MAINT_DIR}/maintenance_off.conf"

case "$1" in
    on)
        ln -sfn "$ON" "$CURRENT_SYM"
        echo "Maintenance ON"
        ;;
    off)
        ln -sfn "$OFF" "$CURRENT_SYM"
        echo "Maintenance OFF"
        ;;
    status)
        if [ "$(readlink "$CURRENT_SYM")" = "$ON" ]; then
            echo "Maintenance: ON"
        else
            echo "Maintenance: OFF"
        fi
        ;;
    *)
        echo "Usage: $0 {on|off|status}"
        exit 1
        ;;
esac

# Валидация и перезагрузка
nginx -t && systemctl reload nginx
```

Проверьте работу:

```bash
sudo chmod +x /usr/local/bin/nginx-maintenance.sh
sudo nginx-maintenance.sh status   # → Maintenance: OFF
sudo nginx-maintenance.sh on       # → Maintenance ON
sudo nginx-maintenance.sh status   # → Maintenance: ON
sudo nginx-maintenance.sh off      # → Maintenance OFF
```

Для автоматизации через systemd создайте юнит `/etc/systemd/system/nginx-maintenance.service` и `/etc/systemd/system/nginx-maintenance.timer` для scheduled включения/выключения.

### Сценарий 3: Исключения и белый список

Иногда нужно исключить определённые пути или IP-адреса из maintenance-режима. Например, чтобы инженеры могли тестировать бэкенд, а клиенты видели заглушку:

```nginx
# /etc/nginx/maintenance/maintenance_exclude.conf — вместо maintenance_on.conf
# Если запрос не из белого списка — включаем maintenance
set $maintenance_enabled 1;

# Исключения: админка и проверка здоровья
if ($uri ~ ^/(admin|healthz|metrics)) {
    set $maintenance_enabled 0;
}

# Исключения: внутренние IP
if ($remote_addr ~ "^(10\.|192\.168\.|172\.(1[6-9]|2[0-9]|3[01])\.)") {
    set $maintenance_enabled 0;
}

if ($maintenance_enabled) {
    return 503;
}
```

> **Важно:** Использование `if` в этом сценарии ограничено директивами `set` и `return`, что безопасно. Не используйте `if` с `proxy_pass` или другими директивами внутри `location`.

### Сценарий 4: Режим обслуживания через map

Для статических сайтов или простых конфигураций удобнее использовать директиву `map` с внешним файлом-флагом. Преимущество — отсутствие симлинков и управление через изменение содержимого файла:

**Файл `/etc/nginx/maps/maintenance.flag`:**

```text
# 1 — включить режим обслуживания, 0 — отключить
1
```

**Конфигурация:**

```nginx
http {
    map $uri $maintenance_mode {
        default 0;
        include /etc/nginx/maps/maintenance.flag;
    }
}

server {
    listen 80;
    server_name example.com;

    root /var/www/site;

    error_page 503 @maintenance;

    location @maintenance {
        internal;
        root /var/www/site;
    }

    location = /maintenance.html {
        internal;
        root /var/www/site;
    }

    location / {
        if ($maintenance_mode = 1) {
            return 503;
        }
        try_files $uri $uri/ =404;
    }
}
```

**Включение/отключение:**

```bash
# Включить
echo "1" > /etc/nginx/maps/maintenance.flag
nginx -s reload

# Отключить
echo "0" > /etc/nginx/maps/maintenance.flag
nginx -s reload
```

> **Примечание:** В этом сценарии `if` используется только с `return` и переменной, установленной через `map`, что безопасно. Для прокси-конфигураций предпочтителен подход с `include` и симлинком (Сценарий 1).

### Сценарий 5: Частичный maintenance (по location)

Иногда требуется отключить только часть сайта (например, API или отдельный сервис), оставив доступной другую часть. Используйте отдельный `location` с `include`:

```nginx
server {
    listen 80;
    server_name example.com;

    root /var/www/site;

    # API в maintenance
    location /api/ {
        include /etc/nginx/maintenance/maintenance_current.conf;
        proxy_pass http://api-backend;
    }

    # Основной сайт работает штатно
    location / {
        proxy_pass http://frontend;
    }

    error_page 503 @maintenance;
    location @maintenance {
        internal;
        root /etc/nginx/maintenance;
    }
}
```

Включение maintenance только для API:

```bash
ln -sfn /etc/nginx/maintenance/maintenance_on.conf /etc/nginx/maintenance/maintenance_current.conf
nginx -t && systemctl reload nginx
```

> **Важно:** Директива `include` с `return 503` должна стоять **до** `proxy_pass` в блоке `location`, иначе `proxy_pass` выполнится первым и maintenance не активируется.

### Сценарий 6: Maintenance с проверкой здоровья бэкенда

В высоконагруженных окружениях перед отключением maintenance-режима необходимо убедиться, что бэкенд полностью готов. Интегрируйте проверку здоровья в процесс отключения:

```bash
#!/bin/bash
# /usr/local/bin/nginx-maintenance-off-with-check.sh

BACKEND="http://127.0.0.1:3000/healthz"
MAX_RETRIES=30
RETRY_INTERVAL=2

echo "Waiting for backend to become healthy..."

for i in $(seq 1 $MAX_RETRIES); do
    HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" "$BACKEND")
    if [ "$HTTP_CODE" = "200" ]; then
        echo "Backend is healthy (attempt $i/$MAX_RETRIES)"
        break
    fi
    echo "Backend not ready (HTTP $HTTP_CODE), retry $i/$MAX_RETRIES..."
    sleep $RETRY_INTERVAL
done

if [ "$HTTP_CODE" != "200" ]; then
    echo "ERROR: Backend did not become healthy in time"
    exit 1
fi

# Отключаем maintenance
ln -sfn /etc/nginx/maintenance/maintenance_off.conf /etc/nginx/maintenance/maintenance_current.conf

# Грациозная перезагрузка
nginx -t && systemctl reload nginx

echo "Maintenance disabled, backend is healthy"
```

**Ожидаемый результат:** Nginx отключает maintenance только после подтверждения готовности бэкенда. Это предотвращает всплеск 502/504 ошибок при неготовом приложении.

### Сценарий 7: Zero-downtime деплой с fallback на maintenance

При деплое нового релиза используйте maintenance-режим как fallback, если новый релиз падает сразу после старта:

```bash
#!/bin/bash
# /usr/local/bin/nginx-zero-downtime-deploy.sh

MAINT_DIR="/etc/nginx/maintenance"
DEPLOY_TIMEOUT=60

# 1. Включаем maintenance
ln -sfn "${MAINT_DIR}/maintenance_on.conf" "${MAINT_DIR}/maintenance_current.conf"
nginx -t && systemctl reload nginx
echo "Maintenance enabled"

# 2. Деплоим новый релиз (пример для systemd-сервиса)
systemctl restart myapp

# 3. Ждём готовности с таймаутом
for i in $(seq 1 $DEPLOY_TIMEOUT); do
    if curl -sf http://127.0.0.1:3000/healthz > /dev/null 2>&1; then
        echo "New release is healthy"
        break
    fi
    sleep 1
done

# 4. Проверяем результат
if ! curl -sf http://127.0.0.1:3000/healthz > /dev/null 2>&1; then
    echo "ERROR: New release failed health check, rolling back"
    systemctl restart myapp-old
    sleep 5
    # Отключаем maintenance для старого релиза
    ln -sfn "${MAINT_DIR}/maintenance_off.conf" "${MAINT_DIR}/maintenance_current.conf"
    nginx -t && systemctl reload nginx
    exit 1
fi

# 5. Отключаем maintenance
ln -sfn "${MAINT_DIR}/maintenance_off.conf" "${MAINT_DIR}/maintenance_current.conf"
nginx -t && systemctl reload nginx
echo "Deploy completed successfully"
```

## Операции и команды

### Валидация конфигурации

Перед любой перезагрузкой проверяйте синтаксис:

```bash
nginx -t
# → nginx: configuration file /etc/nginx/nginx.conf test is successful
```

### Грациозная перезагрузка

```bash
nginx -s reload
# → signal reload started
```

Или через systemd:

```bash
systemctl reload nginx
```

### Проверка статуса

```bash
# Проверка работоспособности
systemctl status nginx
# → Active: active (running)

# Проверка статуса maintenance через скрипт
/usr/local/bin/nginx-maintenance.sh status
# → Maintenance: ON/OFF
```

### Проверка HTTP-кода

```bash
# Быстрая проверка кода ответа
curl -s -o /dev/null -w "%{http_code}\n" http://example.com
# → 503

# Проверка заголовков
curl -I http://example.com
# → HTTP/1.1 503 Service Unavailable
# → Retry-After: 3600
# → Cache-Control: no-store, no-cache, must-revalidate
```

### Мониторинг логов

```bash
# Поиск ошибок 503 в access log
grep " 503 " /var/log/nginx/access.log | tail -n 50

# Поиск ошибок в error log
tail -F /var/log/nginx/error.log

# Подсчёт запросов к maintenance-странице
awk '$9 == 503 {print $7}' /var/log/nginx/access.log | sort | uniq -c | sort -rn
```

### Очистка кэша после отключения maintenance

Если используется прокси-кэш, принудительно очистите устаревшие данные:

```bash
# Удаление ключей кэша для maintenance-страницы
find /var/cache/nginx -name "*maintenance*" -delete

# Полная очистка кэша (осторожно!)
rm -rf /var/cache/nginx/*
systemctl reload nginx
```

## Устранение неисправностей

| Проблема | Возможная причина | Решение |
| :--- | :--- | :--- |
| `500 Internal Server Error` после enable | Синтаксическая ошибка в `maintenance_on.conf` | Проверьте: `nginx -t`; убедитесь, что файл содержит только `return 503;` |
| Страница maintenance отображается, но с кодом 200 | `error_page` не срабатывает | Проверьте, что `return 503;` находится **перед** `proxy_pass`, и `error_page 503` описан в блоке `server` |
| Браузер кэширует maintenance-страницу | Отсутствуют заголовки `Cache-Control` | Добавьте `add_header Cache-Control "no-store, no-cache, must-revalidate" always;` в `location = /maintenance.html` |
| Прямой доступ к `/maintenance.html` работает | Директива `internal` отсутствует | Добавьте `internal;` в блок `location = /maintenance.html` |
| `retry-after` не передаётся в ответе | `add_header` без `always` для статуса 503 | Используйте `add_header Retry-After "3600" always;` — модификатор `always` гарантирует отдачу заголовка для всех кодов ответа |
| Maintenance включается/выключается, но страница не меняется | Кэш браузера или CDN | Очистите кэш браузера (Ctrl+F5), проверьте `Cache-Control`, при необходимости purge CDN |
| После отключения maintenance бэкенд возвращает 502 | Бэкенд не готов или недоступен | Проверьте `systemctl status myapp`, убедитесь что порт прослушивается, проверьте health check эндпоинт |
| Backend получает трафик во время maintenance | `return 503;` стоит после `proxy_pass` | Директива `return` должна стоять **раньше** `proxy_pass` в блоке `location` |
| `nginx -s reload` зависает | Глубокий стактрейс или заблокированные воркеры | Проверьте `systemctl status nginx`, при необходимости используйте `nginx -s quit` для graceful shutdown |
| `nginx -s reload` не применяет изменения | Симлинк не был изменён или permissions | Проверьте права на файлы в `/etc/nginx/maintenance/`, убедитесь что `nginx` может читать `maintenance_current.conf` |
| `map` не срабатывает после reload | Файл-флаг имеет неправильные права или формат | Убедитесь что `/etc/nginx/maps/maintenance.flag` читаем пользователем `nginx` и содержит только `0` или `1` |

## Лучшие практики

- **Всегда используйте `nginx -t` перед `reload`.** Ошибка в синтаксисе не сломает работающий Nginx, но `reload` с ошибкой приведёт к падению всех новых соединений.
- **Не вставляйте `return 503;` после `proxy_pass`.** Директива `return` должна стоять раньше `proxy_pass` в блоке `location`, иначе `proxy_pass` выполнится первым.
- **Для высоконагруженных сайтов** вместо `return 503;` в `location` используйте именованную локацию с `add_header`, чтобы добавить `Retry-After` и `Cache-Control` централизованно — аналогично паттерну в **[Load Shedding](../../CI-CD/Core_Concepts/load_shedding.md)**.
- **Не храните `maintenance.html` на CDN.** CDN может кэшировать страницу с ошибкой. Используйте `Cache-Control: no-store` и при необходимости очищайте кэш через API CDN.
- **Используйте `graceful reload` (HUP),** а не `restart`. Перезагрузка через `systemctl restart nginx` разрывает активные соединения. `reload` плавно переводит воркеры в новый конфиг.
- **Интегрируйте health checks.** Перед отключением maintenance-режима всегда проверяйте готовность бэкенда. Используйте endpoint `/healthz` или `/status` для автоматической проверки.
- **Документируйте процедуры.** Для каждой среды (dev, staging, prod) должен быть регламент включения/выключения maintenance с указанием ответственных, времени и способа уведомления пользователей.
- **Уведомляйте пользователей заранее.** Если работы планируются, используйте Status Page, Slack/Telegram-боты или заголовок `Retry-After` с достаточным запасом времени.
- **Настройте мониторинг на maintenance-режим.** Внесите в мониторинг (Prometheus, Grafana, Zabbix) алерт на продолжительное включение maintenance-режима. Например: `if maintenance_enabled > 30 minutes → page on-call engineer`.
- **Тестируйте откат.** Убедитесь, что процедура отключения maintenance работает за меньшее время, чем допустимый даунтайм SLO. Автоматизируйте откат при падении бэкенда после деплоя.
- **Тестируйте maintenance в staging перед продакшеном.** Убедитесь, что страница обслуживания отображается корректно на всех устройствах и браузерах, заголовки кэширования работают, а health check эндпоинт доступен.

## Связанные темы

- **[Внутренняя маршрутизация Nginx](../Core/Location/internal_routing.md)** — `error_page`, `internal`, именованные локации.
- **[Rewrite правила и try_files](../Core/nginx_rewrite_rules_and_try_files.md)** — `map` с внешним файлом, `try_files`, `rewrite`.
- **[Обработка ошибок бэкенда (Load Balancing)](../Proxy/Load_Balancing/practical_configuration.md)** — `proxy_intercept_errors` и кастомные страницы ошибок.
- **[HTTP-коды ответа](../../Networking/Protocols/HTTP/http_status_codes.md)** — семантика 503 и требования к `Retry-After`.
- **[Диагностика и устранение неисправностей Nginx](../Operations/nginx_troubleshooting.md)** — грациозная перезагрузка, анализ логов.
- **[Rate Limiting и circuit breakers](../../Networking/Protocols/HTTP/http_rate_limiting_circuit_breakers.md)** — сценарий с `Retry-After` при перегрузке.
- **[Load Shedding](../../CI-CD/Core_Concepts/load_shedding.md)** — `return 503` с `Retry-After` при исчерпании ёмкости.
