# uWSGI, SCGI, WSGI, FastCGI: интерфейсы бэкендов

## Определения

**WSGI (Web Server Gateway Interface)** — стандартный Python-интерфейс между веб-сервером и Python-приложением (PEP 3333). Сервер передаёт `environ` (переменные запроса) и `start_response` callable.

**uWSGI** — высокопроизводительный сервер приложений, реализующий протокол `uwsgi` (не путать с WSGI). Поддерживает Python, Ruby, PHP, Go. Используется как самостоятельный сервер или за Nginx/Angie.

**SCGI (Simple Common Gateway Interface)** — упрощённая альтернатива CGI, при которой сервер передаёт запрос приложению через сокет. Менее распространён, чем FastCGI.

**FastCGI (Fast Common Gateway Interface)** — улучшенная версия CGI, при которой процесс приложения живёт между запросами. Используется для PHP-FPM, Python (flup), Ruby.

**PHP-FPM (FastCGI Process Manager)** — альтернативная реализация PHP FastCGI с управлением пулом процессов. Стандарт для продакшена с Nginx/Angie.

## Основные концепции

### Сравнение интерфейсов

| Интерфейс | Язык | Протокол | Преимущества | Недостатки |
| :--- | :--- | :--- | :--- | :--- |
| **WSGI** | Python | HTTP/socket | Стандарт, простота | Только Python |
| **uWSGI** | Python, Ruby, PHP | uwsgi (бинарный) | Высокая производительность, много опций | Сложная конфигурация |
| **FastCGI** | PHP, Python | FastCGI (бинарный) | PHP-FPM, зрелость | Устаревший |
| **SCGI** | Любой | SCGI (текстовый) | Простота | Редко используется |

### uWSGI архитектура

| Компонент | Описание |
| :--- | :--- |
| **Emperor** | Главный процесс, управляет vassal-инстансами |
| **Vassal** | Отдельный инстанс приложения (воркеры, пулы) |
| **Workers** | Процессы/потоки, обрабатывающие запросы |
| **Spooler** | Фоновая очередь для асинхронных задач |
| **Cache** | In-memory кэш (LRU) |
| **Mules** | Фоновые процессы для задач |

### PHP-FPM архитектура

| Компонент | Описание |
| :--- | :--- |
| **Master** | Главный процесс, управляет пулом |
| **Pool** | Группа воркеров (static, dynamic, ondemand) |
| **Workers** | Процессы PHP, обрабатывающие запросы |
| **Status page** | Эндпоинт `/fpm-status` для мониторинга |

## Практические сценарии

### Сценарий 1: Nginx + uWSGI

Минимальный `app.ini` и `uwsgi_pass` — в **[Nginx: интеграция с бэкендами](../../WebServers/Nginx/Core/Location/integration_examples.md)**. Полный разбор mod_wsgi — в **[Apache: интеграция Python (mod_wsgi)](../Apache/apache-python-wsgi.md)**.

### Сценарий 2: Nginx + PHP-FPM

Конфигурация `fastcgi_pass` и пула PHP-FPM — в **[Angie: FastCGI/PHP-FPM](../Angie/angie-fastcgi-php-fpm.md)**. Мониторинг `/fpm-status` — в **[PHP-FPM мониторинг](../PHP/php-fpm-monitoring.md)**.

### Сценарий 3: uWSGI Emperor + Vassals

Шаблон `emperor.ini` + `vassals/app.ini` — в официальной документации uWSGI. Для интеграции с Nginx см. сценарий 1.

### Сценарий 4: Apache + mod_wsgi

`WSGIDaemonProcess`, `WSGIScriptAlias`, пример `app.wsgi` — в **[Apache: интеграция Python (mod_wsgi)](../Apache/apache-python-wsgi.md)**.

## Лучшие практики

1. **PHP-FPM pool isolation:** создавайте отдельный pool для каждого сайта/приложения.
2. **Process management:** используйте `pm = dynamic` для средних нагрузок, `pm = ondemand` для редких запросов.
3. **Timeouts:** настраивайте `request_terminate_timeout`, `request_slowlog_timeout` в PHP-FPM.
4. **Socket vs TCP:** предпочитайте Unix-сокеты для локальной связи, TCP для распределённых сред.
5. **Monitoring:** включите status page (`/fpm-status` для PHP-FPM, `/uwsgi-stats` для uWSGI).
6. **Graceful reload:** используйте `uwsgi reload` или `systemctl reload php-fpm` для плавного перезапуска.
7. **Security:** запускайте от выделенного пользователя, без лишних прав.
8. **Resource limits:** ограничьте память (`limit-as`) и время запроса (`harakiri`).

## Граничные случаи и ограничения

1. **uWSGI сложность:** множество опций может привести к неоптимальной конфигурации. Начинайте с минимального `app.ini`.
2. **PHP-FPM max_children:** превышение лимита приводит к `502 Bad Gateway`. Мониторьте `pm.max_children`.
3. **Socket permissions:** убедитесь, что веб-сервер имеет права на сокет (`chmod-socket`, `listen.mode`).
4. **Slow requests:** медленные запросы блокируют воркеры. Настройте `request_terminate_timeout`.
5. **Memory leaks:** долгоживущие процессы потребляют память. Ограничьте `pm.max_requests`.

## Дополнительная информация

- **[PHP-FPM мониторинг](../PHP/php-fpm-monitoring.md)** — метрики, алерты, dashboards.
- **[Apache: интеграция Python (mod_wsgi)](../Apache/apache-python-wsgi.md)** — daemon-режим, uWSGI, Passenger.
- **[Nginx: FastCGI/PHP-FPM](../Nginx/Scenarios/nginx_fastcgi_php-fpm.md)** — конфигурация Nginx + PHP-FPM.
