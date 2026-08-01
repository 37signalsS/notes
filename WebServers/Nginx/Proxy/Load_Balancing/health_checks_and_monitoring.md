# Проверки состояния и мониторинг в Nginx Load Balancing

**Надёжность:** 10 (SSoT + Официальная документация Nginx 1.26 / Angie 1.12)
**Свежесть:** Июль 2026 (Актуально для Nginx 1.26+, Angie 1.12+)

## Определения

**Health Check (Проверка состояния)** — механизм, позволяющий балансировщику нагрузки определять доступность бэкенд-серверов и исключать неисправные узлы из ротации. Это фундамент высокой доступности (HA).

**Пассивная проверка (Passive Health Check)** — мониторинг на основе анализа ответов бэкенда на реальные запросы пользователей. Если сервер возвращает ошибку, он помечается как «подозрительный».

**Активная проверка (Active Health Check)** — периодическая отправка специальных запросов (проб) к бэкендам в фоновом режиме, независимо от клиентского трафика.

## Основные концепции

### Пассивная проверка (Nginx OSS / Plus / Angie)

Встроена во все версии Nginx и активна по умолчанию. Настраивается через параметры директивы `server` в блоке `upstream`.

- **`max_fails=N`**: Количество неудачных попыток за период времени, после которых сервер помечается как недоступный (по умолчанию 1).
- **`fail_timeout=T`**: Время, в течение которого должны произойти `max_fails`, и время, на которое сервер исключается из балансировки (по умолчанию 10с).

**Механизм `proxy_next_upstream`**:
Определяет, какие именно события считать «неудачной попыткой».
```nginx
location / {
    proxy_pass http://backend;
    # Передать запрос следующему серверу при ошибках или таймаутах
    proxy_next_upstream error timeout http_502 http_503 http_504;
}
```

### Активная проверка

Позволяет обнаружить сбой до того, как его заметит первый клиент.

| Решение | Директива | Особенности |
| :--- | :--- | :--- |
| **Nginx OSS** | `check` | Требует сторонний модуль (`nginx_upstream_check_module`). |
| **Angie OSS** | `check` | Встроено. Поддерживает HTTP, TCP, MySQL, FastCGI и др. |
| **Nginx Plus** | `health_check` | Нативная поддержка. Настраивается в блоке `location`. |
| **Angie PRO** | `upstream_probe` | Полный аналог Plus-функционала с расширенными тестами. |

## Практические сценарии

### 1. Активная HTTP-проверка в Angie OSS

В Angie модуль активных проверок включен по умолчанию. Проверка настраивается непосредственно в блоке `upstream`.

```nginx
upstream backend_cluster {
    zone backend_zone 64k; # Зона памяти обязательна
    server 10.0.0.1:8080;
    server 10.0.0.2:8080;

    # Интервал 5с, 2 успеха для активации, 3 сбоя для исключения
    check interval=5000 rise=2 fall=3 timeout=2000 type=http;
    
    # Что отправлять и что ожидать
    check_http_send "GET /health HTTP/1.0\r\nHost: example.com\r\n\r\n";
    check_http_expect_alive http_2xx http_3xx;
}
```

### 2. Активная проверка в Nginx Plus

Настраивается в контексте `location`, что позволяет использовать разные проверки для одной группы серверов.

```nginx
location / {
    proxy_pass http://backend_cluster;
    # Проверка каждые 5с, ожидание ответа по URI /status
    health_check interval=5s fails=3 passes=2 uri=/status match=server_ok;
}

# Определение условий "здоровья"
match server_ok {
    status 200;
    header Content-Type = text/html;
    body ~ "working";
}
```

## Мониторинг и наблюдаемость

### Использование зон статуса (`status_zone`)

В Angie и Nginx Plus можно собирать детальную статистику по трафику и ошибкам для конкретных серверов и апстримов.

```nginx
server {
    listen 80;
    status_zone web_frontend; # Метрики для этого виртуального хоста

    location /api/ {
        status_zone api_backend; # Метрики для конкретного пути
        proxy_pass http://api_upstream;
    }
}
```

### Мониторинг через API (Angie / Plus)

Angie предоставляет встроенный REST API для получения метрик в формате JSON, что исключает необходимость во внешних экспортерах.

```nginx
server {
    listen 8080;
    location /api/ {
        api /status/; # Точка доступа к метрикам
        allow 127.0.0.1;
        deny all;
    }
    
    # Визуальная панель мониторинга (Console Light в Angie)
    location = /console.html {
        root /usr/share/angie-console-light;
    }
}
```

### Интеграция с Prometheus

- **Angie**: Метрики можно получать напрямую из API или через встроенный модуль экспорта.
- **Nginx OSS**: Требуется [nginx-prometheus-exporter](../../../../Prometheus/Exporters/other_exporters.md), который парсит страницу `stub_status`.

## Дополнительная информация

### Связанные документы

- [Алгоритмы балансировки](./algorithms.md) — выбор стратегии распределения нагрузки.
- [Обзор Load Balancing в Nginx](./overview_concepts.md) — архитектурные основы балансировки.
- [Практическая конфигурация балансировки](./practical_configuration.md) — настройка upstream и proxy_pass.
- [Обзор Angie](../../../Angie/angie_overview.md) — подробнее о преимуществах форка.
