# Maintenance-режим в Nginx

## Определения

**Maintenance-режим** — управляемая временная выключение доступа к сервису веб-сервером, при котором вместо обычного контента или прокси-ответа клиент получает заранее подготовленную страницу с информацией о технических работах. В отличие от пассивных ошибок (502, 504), maintenance-режим включается **сознательно и планируемо** администратором.

**Файл-флаг (Flag file)** — файл на файловой системе, наличие или отсутствие которого определяет состояние maintenance-режима. Это простой механизм переключения, не требующий изменения конфигурации Nginx.

**Конфигурационный include** — механизм подключения внешнего файла конфигурации директивой `include`, позволяющий динамически менять поведение Nginx без перезаписи основного конфига. Подробнее о механизме `include` в **[Установка и базовая настройка Nginx](../Core/nginx_setup.md)**.

## Базовые концепции

### Зачем нужен maintenance-режим

Существует два типичных сценария применения:

1. **Плановые работы.** Сервису известно заранее о предстоящем даунтайме (например, с 20:00). Включив maintenance-режим, администратор гарантирует, что все клиенты получат единообразную информационную страницу с указанием времени завершения вместо того, чтобы видели случайные 500/502/504 ошибки.

2. **Инцидент в продакшене.** Сервис частично или полностью упал. Инженеры решают проблему, а клиенты в это время видят непредсказуемые таймауты и ошибки. Включив maintenance-режим, команда создаёт для пользователей спокойную, предсказуемую картину, пока проблема не будет решена.

### Почему возвращать HTTP 503, а не 200

Даже при том, что клиент получает полностью работающую HTML-страницу, сервер должен возвращать код **503 Service Unavailable**. Вот почему:

1. **SEO и индексация.** Код 503 не индексируется поисковиками (Google, Bing). Если бы возвращался `200 OK`, поисковый робот мог бы индексировать содержимое maintenance-страницы и запомнить её вместо реального контента сайта. Подробнее о семантике 503 в **[HTTP-коды ответа](../../Networking/Protocols/HTTP/http_status_codes.md)**.

2. **Поведение клиентских библиотек и балансировщиков.** Внешние балансировщики (AWS NLB, Cloud Load Balancer) и HTTP-клиенты могут использовать код ошибки для принятия решений о переключении на резервный бэкенд. Возвращая `503`, вы сигнализируете, что проблема временная.

3. **Заголовок `Retry-After`.** Спецификация RFC 9110 требует, чтобы ответ 503 мог включать заголовок `Retry-After`, указывающий клиенту, через сколько секунд (или в какой момент времени) можно повторить запрос. Это помогает избежать **thundering herd** — массового одновременного повторения запросов всех клиентов ровно в момент завершения работ.

4. **Кэширование.** Клиентские браузеры и промежуточные кэши могут сохранить maintenance-страницу, если отсутствуют директивы запрета кэширования. Это приведёт к тому, что после завершения работы пользователи продолжат видеть заглушку из кэша.

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
2. Блок `location = /maintenance.html` использует `internal;`, чтобы страница была **недоступна напрямую** клиентом (подробнее о `internal` в **[Внутренняя маршрутизация Nginx](../Core/Location/internal_routing.md)**). Любая попытка запросить `GET /maintenance.html` вернёт `404 Not Found`.
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

### Сценарий 4: Maintenance-страница с динамическим временем

Чтобы не править `maintenance.html` при каждом включении, используйте переменные Nginx и файл с параметрами:

```nginx
# /etc/nginx/maintenance/maintenance.conf
return 503;

# /etc/nginx/maintenance/config.conf — параметры (можно менять без reload)
# reload_end_time 22:00

server {
    location = /maintenance.html {
        internal;
        root /etc/nginx/maintenance;
        # Подстановка времени из переменной
        sub_filter '__END_TIME__' '22:00 МСК';
        sub_filter_once off;
        add_header Cache-Control "no-store" always;
        add_header Retry-After "3600" always;
    }

    location / {
        include /etc/nginx/maintenance/maintenance_current.conf;
        proxy_pass http://127.0.0.1:3000;
    }
}
```

## Дополнительная информация

### Troubleshooting

| Проблема | Возможная причина | Решение |
| :--- | :--- | :--- |
| `500 Internal Server Error` после enable | Синтаксическая ошибка в `maintenance_on.conf` | Проверьте: `nginx -t`; убедитесь, что файл содержит только `return 503;` |
| Страница maintenance отображается, но с кодом 200 | `error_page` не срабатывает | Проверьте, что `return 503;` находится **перед** `proxy_pass`, и `error_page 503` описан в блоке `server` |
| Браузер кэширует maintenance-страницу | Отсутствуют заголовки `Cache-Control` | Добавьте `add_header Cache-Control "no-store, no-cache, must-revalidate" always;` в `location = /maintenance.html` |
| Прямой доступ к `/maintenance.html` работает | Директива `internal` отсутствует | Добавьте `internal;` в блок `location = /maintenance.html` |
| `retry-after` не передаётся в ответе | `add_header` без `always` для статуса 503 | Используйте `add_header Retry-After "3600" always;` — модификатор `always` гарантирует отдачу заголовка для всех кодов ответа |

### Лучшие практики

- **Всегда используйте `nginx -t` перед `reload`.** Ошибка в синтаксисе не сломает работающий Nginx, но `reload` с ошибкой приведёт к падению всех новых соединений.
- **Не вставляйте `return 503;` после `proxy_pass`.** Директива `return` должна стоять раньше `proxy_pass` в блоке `location`, иначе `proxy_pass` выполнится первым.
- **Для высоконагруженных сайтов** вместо `return 503;` в `location` используйте именованную локацию с `add_header`, чтобы добавить `Retry-After` и `Cache-Control` централизованно — аналогично паттерну в **[Load Shedding](../../CI-CD/Core_Concepts/load_shedding.md)**.
- **Не храните `maintenance.html` на CDN.** CDN может кэшировать страницу с ошибкой. Используйте `Cache-Control: no-store` и при необходимости очищайте кэш через API CDN.
- **Используйте `graceful reload` (HUP),** а не `restart`. Перезагрузка через `systemctl restart nginx` разрывает активные соединения. `reload` плавно переводит воркеры в новый конфиг.

### Связанные темы

- **[Внутренняя маршрутизация Nginx](../Core/Location/internal_routing.md)** — `error_page`, `internal`, именованные локации.
- **[Обработка ошибок бэкенда (Load Balancing)](../Proxy/Load_Balancing/practical_configuration.md)** — `proxy_intercept_errors` и кастомные страницы ошибок.
- **[HTTP-коды ответа](../../Networking/Protocols/HTTP/http_status_codes.md)** — семантика 503 и требования к `Retry-After`.
- **[Rate Limiting и circuit breakers](../../Networking/Protocols/HTTP/http_rate_limiting_circuit_breakers.md)** — сценарий с `Retry-After` при перегрузке.
- **[Load Shedding](../../CI-CD/Core_Concepts/load_shedding.md)** — `return 503` с `Retry-After` при исчерпании ёмкости.
