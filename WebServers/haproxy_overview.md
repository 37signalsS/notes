# HAProxy

## Definitions

HAProxy ([haproxy.org](https://www.haproxy.org/)) — высокопроизводительный балансировщик нагрузки и прокси-сервер для TCP/HTTP-приложений. Стандарт де-факто для распределения трафика в высоконагруженных системах. Обеспечивает отказоустойчивость, горизонтальное масштабирование и интеллектуальную маршрутизацию запросов.

## Basic Concepts

HAProxy распределяет входящие запросы между бэкенд-серверами, повышая производительность и отказоустойчивость приложений. Для обеспечения высокой доступности самого балансировщика часто используется в связке с [Keepalived](../Networking/ServicesAndTools/keepalived_overview.md).

### Архитектура и схема работы

Основные компоненты конфигурации:

- **`frontend`** — точка входа, определяет IP/порт для приёма запросов и правила маршрутизации (ACL).
- **`backend`** — группа серверов, обрабатывающих запросы.
- **`listen`** — объединяет frontend и backend (для простых конфигураций).
- **`defaults`** — параметры по умолчанию для всех секций.

Схема обработки запроса:

1. Клиент отправляет запрос на виртуальный IP-адрес, который слушает HAProxy.
2. HAProxy выступает в роли reverse proxy и принимает запрос.
3. На основе алгоритма балансировки HAProxy перенаправляет запрос на один из доступных backend-серверов.
4. Backend-сервер обрабатывает запрос и возвращает ответ через HAProxy клиенту.

### Режимы работы (mode)

| Режим | Уровень OSI | Что анализирует | Ограничения |
| :--- | :--- | :--- | :--- |
| **`mode tcp`** | L4 (транспортный) | IP, порт, SNI, TLS-рукопожатие | Не анализирует HTTP-заголовки |
| **`mode http`** | L7 (прикладной) | Заголовки, path, cookies, методы | Только HTTP/HTTPS трафик |

**Критично для ACL:** если прокси работает в `mode tcp`, правила ACL по HTTP-заголовкам, path или cookies **не сработают**, так как HAProxy не анализирует содержимое HTTP-запросов.

### Алгоритмы балансировки

Основные алгоритмы распределения нагрузки:

| Алгоритм | Описание | Сценарий |
| :--- | :--- | :--- |
| **`roundrobin`** | Запросы распределяются поочерёдно, поддержка весов | По умолчанию, подходит для большинства HTTP-приложений |
| **`leastconn`** | Запрос идёт на сервер с наименьшим числом активных соединений | Длинные TCP-сессии (БД, FTP), HTTP с переменной нагрузкой |
| **`source`** | Хеширование IP клиента → фиксированный сервер | Session affinity без cookies |
| **`uri`** | Хеширование URI → один ресурс на один сервер | Кэширование, CDN |
| **`url_param`** | Балансировка по параметру URL | Персонализированная маршрутизация |
| **`hdr`** | Хеширование HTTP-заголовка (User-Agent, Cookie) | A/B тестирование, канареечные релизы |
| **`first`** | Заполнение сервера до лимита, затем следующий | Экономия ресурсов, консолидация нагрузки |
| **`random`** | Случайный выбор сервера | Простые сценарии без требований к стейту |

Выбор алгоритма зависит от специфики приложения: для HTTP — `roundrobin` или `leastconn`, для сессионных приложений — `source` или `hdr`.

### ACL и маршрутизация

ACL — это механизм фильтрации и маршрутизации на основе условий запроса.

**Синтаксис:**

```haproxy
frontend http_frontend
    bind *:80
    mode http

    acl is_api path_beg /api
    acl blocked_ip src 10.0.0.100

    http-request deny if blocked_ip
    use_backend api_backend if is_api
    default_backend web_backend
```

**Порядок правил:** HAProxy читает конфигурацию **сверху вниз**. Если правило завершает обработку (например, `deny`), следующие правила не выполняются.

**Распространённые ошибки:**

| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| ACL не срабатывает | Неправильный `mode` (tcp вместо http) | Использовать `mode http` для L7-правил |
| Запрос уходит не в тот backend | Нарушен порядок правил | Специфичные правила размещать перед общими |
| `http-request` игнорируется | Правило после `use_backend` | `http-request` должны быть перед выбором backend |

### Health Checks

HAProxy регулярно проверяет доступность бэкендов:

- **TCP check:** проверка доступности порта
- **HTTP check:** запрос к health endpoint, проверка статуса/тела ответа
- **SSL check:** проверка SSL-сертификата бэкенда

Недоступные серверы автоматически исключаются из ротации и возвращаются при восстановлении.

## Practical Scenarios

### Базовая балансировка HTTP (L7)

```haproxy
frontend http_frontend
    bind *:80
    mode http
    default_backend http_backend

backend http_backend
    mode http
    balance leastconn
    server web01 192.168.131.33:8080 check
    server web02 192.168.131.34:8080 check
```

- `mode http` — анализ HTTP-заголовков, поддержка ACL
- `balance leastconn` — запросы на сервер с наименьшим числом сессий

### Балансировка TCP (L4)

```haproxy
frontend tcp_frontend
    bind *:8080
    mode tcp
    default_backend tcp_backend

backend tcp_backend
    mode tcp
    balance roundrobin
    server db01 192.168.131.33:5432 check
    server db02 192.168.131.34:5432 check
```

- `mode tcp` — балансировка любых TCP-протоколов (БД, SSH, VPN)
- `balance roundrobin` — поочерёдное распределение

### SSL/TLS Termination

HAProxy расшифровывает HTTPS-трафик и передаёт на бэкенды по HTTP, снимая нагрузку с серверов приложений.

```haproxy
frontend https_frontend
    bind *:443 ssl crt /etc/haproxy/certs/your_domain.pem
    mode http
    default_backend http_backend

backend http_backend
    mode http
    balance leastconn
    server web01 192.168.131.33:8080 check
    server web02 192.168.131.34:8080 check
```

- `ssl crt` — путь к PEM-файлу (сертификат + ключ)
- Трафик между HAProxy и бэкендом идёт по HTTP

### SSL/TLS Passthrough

HAProxy пробрасывает зашифрованный трафик напрямую к бэкендам без расшифровки.

```haproxy
frontend https_passthrough
    bind *:443
    mode tcp
    default_backend https_backend

backend https_backend
    mode tcp
    balance leastconn
    server web01 192.168.131.33:443 check
    server web02 192.168.131.34:443 check
```

- `mode tcp` — HAProxy не анализирует содержимое трафика
- SSL-терминирование происходит на бэкендах

### Балансировка kube-apiserver (bare-metal)

В bare-metal кластерах Kubernetes HAProxy обеспечивает отказоустойчивый доступ к API-серверу.

- **Режим:** L4 (`mode tcp`)
- **VIP:** управляется [Keepalived](../Networking/ServicesAndTools/keepalived_overview.md)
- **Порт бэкенда:** `6443` (kube-apiserver)
- **Health checks:** проверка доступности API

> Подробное руководство: [Настройка High Availability API-сервера с Keepalived и HAProxy](../Kubernetes/Installation/kubeadm/ha_concepts.md).

## Additional Information

### Ключевые особенности

- **Производительность:** однопоточная событийная модель, минимальное потребление памяти, миллионы запросов/сек
- **Надёжность:** проверенная стабильность в production-средах с критически важными нагрузками
- **Гибкость:** балансировка HTTP/HTTPS и TCP-протоколов (БД, FTP, SSH, VPN)
- **Безопасность:** защита от DDoS (лимиты соединений, таймауты), ACL-фильтрация
- **Graceful reload:** перезагрузка без потери активных соединений
- **Оптимизация:** Keep-Alive, HTTP/2 для снижения задержек
- **Мониторинг:** встроенная статистика (запросы, состояние серверов, ошибки)
- **Маршрутизация:** правила на основе заголовков, cookies, URL, IP/портов

### Сравнение с Nginx

HAProxy — специализированный балансировщик, Nginx — универсальный веб-сервер. Бесплатная HAProxy предлагает более гибкий набор алгоритмов балансировки; Nginx Plus (платная версия) — уникальные функции вроде балансировки по скорости ответа.

Подробное сравнение: [Nginx Load Balancing — Additional Info](../WebServers/Nginx/Proxy/Load_Balancing/additional_info_and_comparisons.md).
