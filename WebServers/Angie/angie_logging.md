# Логирование в Angie

В Angie, как и в Nginx, существует два основных типа логов: лог доступа (`access_log`) и лог ошибок (`error_log`). Корректная настройка логирования критически важна для отладки, мониторинга и анализа безопасности.

## 1. Лог доступа (`access_log`)

`access_log` записывает информацию о каждом запросе клиента после его обработки.

### 1.1. Базовая настройка

Лог доступа определяется директивой `access_log`:

```nginx
# Запись лога в файл с использованием стандартного формата combined
access_log /var/log/angie/access.log combined;
```

Директиву `access_log` можно размещать на уровнях `http`, `server`, `location` и даже `if` в `location`. Важно помнить, что определение `access_log` на вложенном уровне отменяет логирование с более высокого уровня для данного запроса.

### 1.2. Пользовательские форматы лога (`log_format`)

Для более детального анализа стандартных форматов (`combined`) может быть недостаточно. Angie позволяет определять собственные форматы с помощью директивы `log_format`.

**Пример расширенного формата:**

Этот формат включает метрики, полезные при работе с `upstream` (проксируемыми) серверами.

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

Ключевые переменные для анализа `upstream`:
-   `$request_time`: Полное время обработки запроса.
-   `$upstream_addr`: Адрес `upstream` сервера.
-   `$upstream_status`: HTTP-статус ответа от `upstream`.
-   `$upstream_response_time`: Время получения ответа от `upstream`. Помогает находить медленные бэкенды.
-   `$upstream_cache_status`: Статус кэша (`HIT`, `MISS`, `EXPIRED` и т.д.).

### 1.3. Логирование в формате JSON

Для упрощения парсинга логов в автоматизированных системах (например, ELK/OpenSearch Stack, Loki, ClickHouse) удобно использовать формат JSON.

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
- `escape=json`: Экранирует символы в переменных для соответствия стандарту JSON.

### 1.4. Оптимизация производительности логирования

При высоких нагрузках запись логов на диск может стать узким местом. Angie предлагает несколько механизмов для оптимизации:

#### Буферизация (`buffer`)

Запись в лог происходит не для каждого запроса, а порциями, когда буфер заполнится. Это снижает количество операций дискового ввода-вывода.

```nginx
access_log /var/log/angie/access.log extended buffer=32k flush=5s;
```
- `buffer=32k`: Устанавливает размер буфера.
- `flush=5s`: Принудительно сбрасывает буфер на диск, если он не был заполнен в течение 5 секунд.

#### Сжатие (`gzip`)

Angie может сжимать логи "на лету" перед записью на диск. Это экономит дисковое пространство, но увеличивает нагрузку на CPU.

```nginx
# Сжатие автоматически включает буферизацию
access_log /var/log/angie/access.log.gz extended gzip=1;
```
- `gzip=1`: Уровень сжатия. Рекомендуется использовать низкие уровни (1-3) для оптимального баланса между экономией места и нагрузкой на процессор.

#### Кэширование дескрипторов файлов (`open_log_file_cache`)

Для систем с большим количеством файлов логов эта директива позволяет кэшировать открытые файловые дескрипторы, сокращая системные вызовы.

```nginx
open_log_file_cache max=1000 inactive=20s min_uses=2 valid=1m;
```

#### Отключение лога

В некоторых случаях (например, при нагрузочном тестировании или для отдачи неважной статики) логи можно отключить.

```nginx
location /static/ {
    access_log off;
}
```

### 1.5. Условное логирование

Иногда требуется логировать не все запросы, а только определенные. Это можно сделать с помощью связки директив `map` и `if`.

**Пример: логировать только редиректы (3xx ответы)**

```nginx
http {
    # ...
    # 1. Создаем переменную $loggable
    map $status $loggable {
        ~^3  1;   # Если статус начинается с "3", $loggable = 1
        default 0; # В остальных случаях $loggable = 0
    }
    # ...
}

server {
    # ...
    # 2. Используем переменную для условного логирования
    access_log /var/log/angie/redirects.log combined if=$loggable;
    # ...
}
```
Эта конфигурация будет записывать в `redirects.log` только те запросы, которые завершились HTTP-статусом 3xx.

## 2. Лог ошибок (`error_log`)

`error_log` предназначен для записи информации о проблемах, возникших в процессе работы сервера. В отличие от `access_log`, его формат не настраивается, но можно управлять уровнем детализации.

```nginx
# Глобальный лог ошибок
error_log /var/log/angie/error.log warn;
```

**Уровни детализации (от самого критичного к самому подробному):**
- `emerg`
- `alert`
- `crit`
- `error`
- `warn`
- `notice`
- `info`
- `debug`

Для обычной работы рекомендуется уровень `warn` или `error`. Уровень `notice` полезен для отладки модулей (например, ACME), а `debug` — для глубокой диагностики проблем, требующей специальной сборки Angie.

## 3. См. также

*   [Мониторинг Angie с помощью Console Lite и API](./angie_monitoring_with_console_api.md)
*   [Мониторинг Angie с помощью Prometheus и Grafana](./monitoring_with_prometheus_and_grafana.md)
*   [Настройка Angie в роли обратного HTTP-прокси](./angie_reverse_proxy.md)
