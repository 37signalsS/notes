# Минимальная продакшен-конфигурация Angie

## Определения

**Базовый продакшен-конфиг (baseline config)** — минимальный рабочий конфиг Angie для production, покрывающий: процессную модель (master/worker), надёжность логов, отдачу статики, безопасность и наблюдаемость — без избыточного тюнинга. Это "здоровая база", от которой повышаете производительность точечно.

**Тюнинг** (performance tuning) — отдельная большая тема: лимиты worker, сжатие, кэши, SSL-оптимизация. Здесь — только стартовые, безопасные значения.

## Теоретический блок

### Структура конфигурации Angie

*   **`main`** (глобальный) — `worker_processes`, `pid`, `load_module`, `user`.
*   **`events`** — модель работы с соединениями (`worker_connections`).
*   **`http`** — всё о HTTP: `server`, `location`, `upstream`, кэши, прокси, логи.
*   Каждый блок/директива компилируются в run-time; конфиг читается единожды при старте и перечитывается при reload.

### Минимальный безопасный набор для production

1.  Правильное количество worker-процессов (обычно = число CPU) играет роль для нагрузки, но для базы достаточно `auto`.
2.  `worker_connections` — сколько одновременных соединений способен обработать воркер; не завышать без расчёта лимитов ОС (`ulimit -n`).
3.  Логирование с ротацией (USR1) и без "бесконечных" файлов.
4.  Обязательные серверные блоки: `default_server`-заглушка для неизвестных Host.
5.  Статика: `sendfile`, `tcp_nopush`, разумные `expires`.
6.  Мониторинг: `status_zone` на нужных `server`.
7.  Безопасность: `server_tokens off`, лимиты запросов (по желанию), корректные права на файлы.

## Практический блок

### Сценарий 1: Базовый production-конфиг

```nginx
# /etc/angie/angie.conf
user  www-data;
worker_processes  auto;          # равно числу CPU-ядер (обычно)

error_log  /var/log/angie/error.log warn;
pid        /run/angie.pid;

events {
    worker_connections  4096;    # стартовое значение; под нагрузкой считать от ulimit
}

http {
    include       /etc/angie/mime.types;
    default_type  application/octet-stream;

    # Отдача статики
    sendfile     on;
    tcp_nopush   on;

    # Логирование
    log_format main '$remote_addr - $remote_user [$time_local] "$request" '
                    '$status $body_bytes_sent "$http_referer" '
                    '"$http_user_agent"';
    access_log  /var/log/angie/access.log main;

    # Мониторинг
    status_zone http_status;

    # Защита от раскрытия версии
    server_tokens off;

    # ---- Виртуальные хосты ----

    # Заглушка для неизвестных хостов
    server {
        listen 80 default_server;
        server_name _;
        return 444;
    }

    # Основной сайт
    server {
        listen 80;
        server_name example.com;

        root /var/www/example;
        index index.html;

        location /static/ {
            expires 30d;            # достаточно-long client-side cache
            add_header Cache-Control "public, immutable";
            access_log off;         # не шуметь в логах статикой
        }

        location / {
            try_files $uri $uri/ /index.html;
        }
    }
}
```

### Сценарий 2: Применение и первичная проверка

```bash
# Проверка синтаксиса
sudo angie -t
# → syntax is ok / test is successful

# Ротация логов (после logrotate)
sudo kill -USR1 $(cat /run/angie.pid)

# Smoke-тест отдачи
curl -sI http://localhost/ | grep -E "^(HTTP|Server)"
# → HTTP/1.1 200 OK

# Статика: кэш клиента
curl -sI http://localhost/static/app.css | grep -i cache-control
# → Cache-Control: public, immutable
```

### Сценарий 3: Проверка конфигурации перед релизом

```bash
# Полный diff того, что будет загружено
sudo angie -T > /tmp/angie_full.conf      # полный расширенный конфиг

# Поиск потенциально опасных директив
sudo angie -T | grep -n "server_tokens\|ssl_protocols\|proxy_pass"
```

## Дополнительная информация

*   **Важное**: из-за особенностей `add_header` (наследование отменяется при наличии в `location`) базовый набор security-заголовков лучше размещать на уровне `server`, а не `location`, или продублировать.
*   Для HTTPS добавьте блок 443 с сертификатом (см. [Настройка TLS в Angie](./angie_tls_setup.md) и виртуальные хосты в [angie-server-name.md](./angie-server-name.md)).
*   Расширение базовой конфигурации — сжатие, кэши, HTTP/2/3, лимиты — смотрите в [Высоконагруженные настройки Angie](./High_Load/performance_optimization.md).

## См. также

*   **[Виртуальные хосты и server_name в Angie](./angie-server-name.md)** — default_server, wildcard, regex.
*   **[Высокая нагрузка: производительность и достоверность](./High_Load/performance_optimization.md)** — тюнинг поверх базы.
*   **[Установка и базовая настройка Nginx](../Nginx/Core/nginx_setup.md)** — общий материал по базовому конфигу для Nginx-совместимых серверов.