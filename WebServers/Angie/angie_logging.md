# Логирование в Angie

## Определения

В Angie, как и в его прародителе [Nginx](../Nginx/Core/nginx_overview.md), существует два основных типа логов, критически важных для отладки, [мониторинга](./angie_monitoring.md) и анализа безопасности:

* **Лог доступа (`access_log`)**: Записывает информацию о каждом обработанном запросе клиента.
* **Лог ошибок (`error_log`)**: Предназначен для записи информации о проблемах, возникших в процессе работы сервера.

## Основные концепции

### Лог доступа (`access_log`)

`access_log` записывает информацию о каждом запросе клиента после его обработки. Лог определяется директивой `access_log`, которую можно размещать на уровнях `http`, `server` или `location`. Определение на вложенном уровне отменяет логирование с более высокого.

```nginx
# Запись лога в файл с использованием стандартного формата combined
access_log /var/log/angie/access.log combined;

# Отключение логирования для статических файлов
location /static/ {
    access_log off;
}
```

### Лог ошибок (`error_log`)

Формат `error_log` не настраивается, но можно управлять уровнем его детализации.

```nginx
# Глобальный лог ошибок с уровнем детализации 'warn'
error_log /var/log/angie/error.log warn;
```

**Уровни детализации** (от самого критичного к самому подробному): `emerg`, `alert`, `crit`, `error`, `warn`, `notice`, `info`, `debug`. Для обычной работы рекомендуется `warn` или `error`. Уровень `notice` полезен для отладки модулей (например, ACME), а `debug` — для глубокой диагностики.

## Практические сценарии

### Пользовательские форматы лога (`log_format`)

Для детального анализа стандартных форматов (`combined`) может быть недостаточно. Angie позволяет определять собственные форматы с помощью директивы `log_format`.

**Пример: Расширенный формат для анализа `upstream`**

```nginx
http {
    log_format extended '$remote_addr - $remote_user [$time_local] "$request" '
                      '$status $body_bytes_sent "$http_referer" '
                      '"$http_user_agent" "$http_x_forwarded_for" '
                      'rt=$request_time ua="$upstream_addr" '
                      'us="$upstream_status" ut="$upstream_response_time" '
                      'cs=$upstream_cache_status';

    access_log /var/log/angie/access.log extended;
}
```

Ключевые переменные для анализа [проксируемых серверов](./angie_reverse_proxy.md):

* `$request_time`: Полное время обработки запроса.
* `$upstream_addr`: Адрес `upstream` сервера.
* `$upstream_status`: HTTP-статус ответа от `upstream`.
* `$upstream_response_time`: Время ответа от `upstream`.
* `$upstream_cache_status`: Статус кэша (`HIT`, `MISS`, `EXPIRED`).

### Логирование в формате JSON

Для упрощения парсинга логов в автоматизированных системах ([ELK](../../ELK_Stack/elk_stack_overview.md), [Loki](../../Loki/loki_overview.md)) удобно использовать формат JSON.

```nginx
http {
    log_format json_logs escape=json
      '{'
        '"timestamp":"$time_iso8601",'
        '"client_ip":"$remote_addr",'
        '"request":"$request",'
        '"status":$status,'
        '"body_bytes":$body_bytes_sent,'
        '"path":"$uri",'
        '"upstream_addr":"$upstream_addr",'
        '"upstream_status":"$upstream_status",'
        '"upstream_time":"$upstream_response_time",'
        '"request_time":"$request_time"'
      '}';

    access_log /var/log/angie/json_access.log json_logs;
}
```

### Условное логирование

Иногда требуется логировать не все запросы. Это можно сделать с помощью директивы `map`.

**Пример: Логировать только редиректы (3xx ответы)**

```nginx
http {
    # 1. Создаем переменную $loggable, равную 1 для 3xx статусов
    map $status $loggable {
        ~^3  1;
        default 0;
    }
}

server {
    # 2. Используем переменную для условного логирования
    access_log /var/log/angie/redirects.log combined if=$loggable;
}
```

## Дополнительная информация

### Оптимизация производительности логирования

При высоких нагрузках запись логов на диск может стать узким местом.

#### Буферизация (`buffer`)

Запись в лог происходит порциями, что снижает количество операций дискового ввода-вывода.

```nginx
access_log /var/log/angie/access.log extended buffer=32k flush=5s;
```

* `buffer=32k`: Размер буфера.
* `flush=5s`: Принудительный сброс буфера на диск по истечении времени.

#### Сжатие (`gzip`)

Angie может сжимать логи "на лету" перед записью, экономя дисковое пространство ценой небольшой нагрузки на CPU.

```nginx
# Сжатие автоматически включает буферизацию
access_log /var/log/angie/access.log.gz extended gzip=1;
```

* `gzip=1`: Уровень сжатия (рекомендуется 1-3).

#### Кэширование дескрипторов файлов (`open_log_file_cache`)

Для систем с большим количеством файлов логов эта директива кэширует открытые файловые дескрипторы, сокращая системные вызовы.

```nginx
open_log_file_cache max=1000 inactive=20s min_uses=2 valid=1m;
```
