# Логирование в Angie

## Определения

В Angie, как и в его прародителе [Nginx](../Nginx/Core/nginx_overview.md), существует два основных типа логов, критически важных для отладки, [мониторинга](./angie_monitoring/angie_monitoring_concepts.md) и анализа безопасности. В отличие от Nginx, Angie предоставляет расширенные возможности управления логами ошибок и поддержку современных форматов «из коробки»:

* **Лог доступа (`access_log`)**: Фиксирует информацию о каждом обработанном запросе клиента (HTTP) или сессии (Stream/L4).
* **Лог ошибок (`error_log`)**: Предназначен для записи информации о проблемах, возникших в процессе работы сервера, а также для диагностических сообщений.

## Базовые концепции

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

В Angie директива `error_log` значительно расширена по сравнению с классическим Nginx. Помимо уровня детализации, она поддерживает форматирование в JSON, фильтрацию сообщений и ограничение скорости записи.

```nginx
# Глобальный лог ошибок с уровнем детализации 'warn'
error_log /var/log/angie/error.log warn;

# Использование JSON-формата для лога ошибок (Angie-specific)
error_log /var/log/angie/error.log warn format=json;

# Ограничение скорости записи для предотвращения переполнения диска (Angie-specific)
# rate=10 означает не более 10 сообщений в секунду
error_log /var/log/angie/error.log warn rate=10;
```

**Уровни детализации** (от самого критичного к самому подробному): `emerg`, `alert`, `crit`, `error`, `warn`, `notice`, `info`, `debug`. 
* Для промышленной эксплуатации рекомендуется `warn` или `error`. 
* Уровень `notice` полезен для отладки модулей (например, **ACME (Automated Certificate Management Environment)**).
* Уровень `debug` требует сборки с флагом `--with-debug` и предназначен для глубокой диагностики.

**Параметр `filter` (Angie-specific):** позволяет записывать в лог только сообщения, соответствующие определенному условию или тегу.


### Логирование в модуле Stream (L4)

Для проксирования трафика на уровне **L4 (Layer 4)** (**TCP (Transmission Control Protocol)** / **UDP (User Datagram Protocol)**) логирование настраивается в блоке `stream`. В отличие от HTTP, здесь фиксируются параметры сессии, а не отдельных запросов.

```nginx
stream {
    log_format basic '$remote_addr [$time_local] '
                     '$protocol $status $bytes_sent $bytes_received '
                     '$session_time';

    access_log /var/log/angie/stream-access.log basic;
}
```

Подробнее см. в [L4 балансировка и проксирование](./l4_balancing_and_proxying.md).

### Логирование в Syslog и контейнерные среды

В современных инфраструктурах часто требуется отправка логов во внешние системы или сборщики контейнеров.

#### Логирование в стандартные потоки (Docker/Kubernetes)
Для контейнеризированных сред рекомендуется направлять логи в `stdout` и `stderr`, чтобы их мог перехватить рантайм контейнеров.
```nginx
# Перенаправление лога ошибок в stderr
error_log stderr warn;

# Перенаправление лога доступа в stdout (через символическую ссылку в официальных образах)
access_log /var/log/angie/access.log combined;
```

#### Логирование в Syslog
Angie поддерживает прямую отправку логов в **Syslog** без промежуточных файлов.
```nginx
# Пример отправки в Syslog на локальный сокет
access_log syslog:server=unix:/dev/log,facility=local7,tag=angie,severity=info combined;

# Пример отправки на удаленный сервер по UDP
error_log syslog:server=192.168.1.10:514,facility=local6,tag=angie_err warn;
```
Параметры `server`, `facility`, `tag` и `severity` позволяют гибко классифицировать сообщения на стороне приемника.

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

Для упрощения парсинга логов в автоматизированных системах (**ELK (Elasticsearch, Logstash, Kibana)**, [Loki](../../Loki/loki_overview.md)) удобно использовать формат **JSON (JavaScript Object Notation)**. В Angie рекомендуется добавлять идентификаторы запросов для сквозной трассировки.

```nginx
http {
    log_format json_logs escape=json
      '{'
        '"timestamp":"$time_iso8601",'
        '"request_id":"$request_id",'        # Уникальный ID запроса для трассировки
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

### Настройка формата времени (`time_format`)

Angie позволяет переопределять формат времени в логах с помощью директивы `time_format` (Angie-specific), что избавляет от необходимости использовать сложные конструкции с `map`.

```nginx
http {
    # Определение собственного формата времени с миллисекундами
    time_format custom_time "%Y-%m-%dT%H:%M:%S.%L%z";

    log_format timed '$remote_addr [$custom_time] "$request" $status';
    access_log /var/log/angie/access.log timed;
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

Angie может сжимать логи "на лету" перед записью, экономя дисковое пространство ценой небольшой нагрузки на **CPU (Central Processing Unit — центральный процессор)**.

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

### Ротация логов

Angie не закрывает и не переоткрывает файлы логов автоматически после их переименования или перемещения (например, внешней утилитой `logrotate`). Чтобы сервер начал писать в новый файл, ему необходимо отправить сигнал **USR1**:

```bash
# Переоткрытие файлов логов без перезагрузки конфигурации
kill -USR1 $(cat /var/run/angie.pid)
```
Это действие заставляет рабочий процесс переоткрыть все файлы логов, сохранив при этом производительность.

## См. также

* [Оптимизация производительности Angie](./High_Load/performance_optimization.md)
* [Мониторинг Angie: основные концепции](./angie_monitoring/angie_monitoring_concepts.md)
* [Руководство по безопасности Nginx — настройка логирования](../Nginx/Security/nginx_security_guide.md)
