# Балансировка нагрузки HTTP в Angie

## Определения

**Балансировка нагрузки HTTP в Angie** — это процесс распределения входящего трафика уровня L7 (прикладной уровень модели OSI) между группой бэкенд-серверов.

Angie значительно расширяет возможности стандартного Nginx, предоставляя в открытой версии (OSS) функции, которые ранее были доступны только в коммерческих редакциях:
* **Активные проверки состояния (Active Health Checks)**: фоновый мониторинг бэкендов "из коробки".
* **Алгоритм Least Time (v1.12+)**: выбор сервера на основе реального времени ответа.
* **Персистентность сессий (Sticky Sessions)**: привязка клиента к серверу через Cookie, Route или метод `learn`.
* **Динамическое управление**: изменение параметров апстримов через HTTP API без перезагрузки (`reload`).

Общие принципы балансировки и базовые алгоритмы описаны в **[обзоре балансировки L7 в Nginx](../Nginx/Proxy/Load_Balancing/overview_concepts.md)**.

## Основные концепции

### Алгоритмы распределения нагрузки

Angie поддерживает все стандартные алгоритмы (Round Robin, Least Connections, IP Hash) и добавляет продвинутые механизмы.

| Метод | Версия | Описание | Особенности |
| :--- | :--- | :--- | :--- |
| **Least Time** | OSS (1.12+) | Выбор сервера с наименьшим средним временем ответа. | Параметры `header` (заголовки) или `last_byte` (весь ответ). |
| **Sticky** | OSS | Привязка клиента к серверу. | Поддерживает методы `cookie`, `route` и `learn`. |
| **Feedback** | PRO | Динамические веса на основе данных от бэкендов. | Учитывает загрузку CPU/RAM серверов приложения. |
| **Hash** | OSS | Хеширование по ключу (URI, заголовки). | Опция `consistent` для минимизации перераспределения. |

### Зоны разделяемой памяти и очереди

Для работы продвинутых функций необходимо объявить зону разделяемой памяти (`zone`), где Angie хранит состояние группы серверов в реальном времени.

* **Зона (zone)**: Обязательна для активных проверок и мониторинга.
* **Очередь (queue)** — **только в Angie PRO**: Позволяет удерживать запросы при достижении `max_conns` на всех серверах, а не сбрасывать их по 502.

```nginx
upstream app_servers {
    zone app_servers 128k;       # Хранение состояния группы
    status_zone app_status;      # Метрики для API
    
    server 10.0.0.1:8080 max_conns=100;
    server 10.0.0.2:8080 max_conns=100;
    
    # Резервирование очереди (PRO)
    # queue 500 timeout=30s;
}
```

## Практические сценарии

### 1. Настройка алгоритма Least Time (OSS 1.12+)

Алгоритм выбирает сервер не только по количеству соединений, но и по скорости обработки запросов, что критично при разнородной нагрузке или мощностях бэкендов.

```nginx
upstream fast_pool {
    zone fast_pool 64k;
    
    # Балансировка по времени получения первого байта заголовка
    least_time header;
    
    server 10.0.0.1:8080;
    server 10.0.0.2:8080;
}
```

### 2. Активные проверки состояния (Active Health Checks)

В отличие от пассивных проверок (`max_fails`), активные проверки опрашивают бэкенды независимо от клиентского трафика.

```nginx
upstream backend_pool {
    zone backend_pool 64k;
    server 10.0.0.1:8080;
    server 10.0.0.2:8080;

    # Интервал 5с, 3 ошибки = DOWN, 2 успеха = UP
    check interval=5s fall=3 rise=2;
    check_http_send "GET /health HTTP/1.1\r\nHost: api.internal\r\nConnection: close\r\n\r\n";
    check_http_expect_rescode 200;
}
```

### 3. Продвинутые Sticky Sessions: метод Learn (OSS 1.12+)

Метод `learn` позволяет Angie отслеживать существующие сессии приложения (например, `JSESSIONID`), не вставляя собственные Cookie.

```nginx
upstream stateful_app {
    zone stateful_app 256k;
    
    # Отслеживание сессии по заголовку Cookie от бэкенда
    sticky learn 
           create=$upstream_cookie_jsessionid
           lookup=$cookie_jsessionid
           zone=client_sessions:2m;
    
    server 10.0.0.1:8080;
    server 10.0.0.2:8080;
}
```

### 4. Динамическое управление и Docker Discovery

Angie 1.12+ поддерживает автоматическое обнаружение бэкендов в Docker-окружениях без перезагрузки конфигурации.

**Docker Upstream Discovery:**
```nginx
upstream docker_app {
    zone docker_app 64k;
    # Автоматическое добавление контейнеров по метке 'backend'
    upstream_discovery docker label=app-type:backend;
}
```

**Режим Drain (плавный вывод):**
Позволяет серверу доработать текущие сессии перед остановкой. Активируется через API:
```bash
curl -X PATCH -d '{"drain":true}' \
  'http://localhost:8080/api/v1/http/upstreams/docker_app/servers/0'
```

### 5. Поддержка NTLM (Angie PRO)

Для приложений Microsoft (Exchange, AD) требуется поддержание связи клиента и бэкенда через одно TCP-соединение на всех этапах аутентификации.

```nginx
upstream ntlm_backend {
    zone ntlm_backend 64k;
    server 10.0.0.1:8080;
    
    # PRO-функция для связки соединений
    # bind_conn; 
}
```

## Дополнительная информация

### См. также

* **[Обзор возможностей Angie](./angie_overview.md)** — архитектурные отличия.
* **[Мониторинг бэкендов в Angie](./angie_monitoring/angie_monitoring_concepts.md)** — использование API и консоли.
* **[Динамические апстримы и Service Discovery](./dynamic_upstreams.md)** — глубокая настройка DNS и Docker.
* **[Алгоритмы балансировки Nginx](../Nginx/Proxy/Load_Balancing/algorithms.md)** — подробный разбор Round Robin и Least Conn.
