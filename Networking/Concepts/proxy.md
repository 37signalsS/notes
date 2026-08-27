# Прокси-сервер

## Определения

**Прокси-сервер** (от англ. *proxy* — «посредник») — промежуточный программный или аппаратный узел в компьютерной сети, который выступает в роли посредника между клиентом (запрашивающей стороной) и целевым сервером (ресурсом).

Прокси-серверы работают на разных уровнях модели OSI:
- **L4 (Транспортный уровень):** Работают с TCP/UDP потоками (байтовыми стримами) без анализа содержимого прикладного уровня. Примеры: HAProxy в режиме `mode tcp`, Nginx `stream`.
- **L7 (Прикладной уровень):** Понимают протоколы (HTTP, FTP, gRPC, Redis), могут анализировать и изменять заголовки, кэшировать контент и принимать решения на основе данных сеанса.

## Принципы работы

### Механизм передачи запроса

Прокси-сервер полностью разрывает сетевое соединение между клиентом и сервером:

1. **Клиент → Прокси:** Клиент устанавливает соединение с прокси-сервером и передает ему запрос (например, `GET http://example.com/`).
2. **Обработка на прокси:** 
   - **Авторизация:** Проверка прав доступа клиента (заголовки `Proxy-Authorization`).
   - **Кэширование:** Если ресурс есть в локальном кэше и он валиден, прокси возвращает ответ сразу.
   - **Модификация:** Добавление заголовков (`X-Forwarded-For`, `X-Real-IP`), изменение `User-Agent` или удаление чувствительных данных.
3. **Прокси → Сервер:** Прокси устанавливает *новое* соединение с целевым сервером от своего имени.
4. **Сервер → Прокси:** Целевой сервер обрабатывает запрос и возвращает ответ прокси-серверу.
5. **Прокси → Клиент:** Прокси анализирует ответ, может его кэшировать и передает данные клиенту по исходному соединению.

### Прозрачное проксирование (Transparent Proxying)

При прозрачном проксировании трафик перехватывается на сетевом уровне без необходимости настройки прокси в браузере или ОС клиента.

- **Реализация:** Использование `iptables` (цели `REDIRECT` или `TPROXY`) на шлюзе.
- **WCCP (Web Cache Communication Protocol):** Протокол Cisco для перенаправления трафика на кэширующие прокси-серверы.
- **Особенности:** Позволяет применять политики фильтрации и кэширования незаметно для пользователя.

### Проксирование HTTPS (Метод CONNECT)

Поскольку HTTPS-трафик зашифрован, прокси-сервер не может прочитать его содержимое без доступа к ключам. Используются два подхода:

1.  **HTTP CONNECT (Туннелирование):**
    *   Клиент отправляет: `CONNECT example.com:443 HTTP/1.1`.
    *   Прокси открывает TCP-порт на целевой сервер.
    *   Прокси возвращает `200 Connection Established`.
    *   Далее клиент и сервер выполняют TLS Handshake напрямую через прокси. Прокси видит только зашифрованный поток байтов.
2.  **SSL/TLS Termination (Перехват):**
    *   Прокси разрывает TLS-соединение. Он должен владеть сертификатом, которому доверяет клиент (часто используется в корпоративных DPI-системах для анализа трафика).

## Обработка SSL/TLS на прокси

Существует три основных сценария обработки зашифрованного трафика:

| Режим | Описание | Безопасность |
| :--- | :--- | :--- |
| **SSL Passthrough** | Прокси передает зашифрованный трафик «как есть» на бэкенд (L4). | Максимальная (прокси не видит данные). |
| **SSL Termination** | Прокси расшифровывает трафик и передает его на бэкенд в открытом виде (HTTP). | Удобно для балансировки, но трафик внутри сети не защищен. |
| **SSL Bridging (Re-encryption)** | Прокси расшифровывает трафик для анализа/модификации и снова зашифровывает перед отправкой на бэкенд. | Высокая безопасность и возможность анализа L7. |

## Классификация прокси-серверов

### По направлению трафика

| Тип | Назначение | Основная цель | Аналогия |
| :--- | :--- | :--- | :--- |
| **Прямой прокси (Forward Proxy)** | Устанавливается на стороне клиента (или в его сети). | Защита клиента, анонимность, контроль доступа сотрудников в интернет, фильтрация контента. | **Личный ассистент:** Делает заказ за вас, скрывая вашу личность от персонала ресторана. |
| **Обратный прокси (Reverse Proxy)** | Устанавливается перед серверами приложений. | Защита серверов, балансировка нагрузки, SSL-терминация, кэширование бэкенда. | **Администратор (Receptionist):** Встречает гостей и направляет их к нужному столику, скрывая кухню. |

#### Прямой прокси (Forward Proxy) в деталях

Forward Proxy выступает щитом между частной сетью и публичным интернетом.

*   **Контроль и фильтрация:** Позволяет администраторам блокировать доступ к нежелательным ресурсам (черные списки) на уровне всей компании.
*   **Безопасность:** Сканирует входящие ответы на наличие вирусов и вредоносного кода до того, как они попадут на устройства пользователей.
*   **Кэширование:** Сохраняет копии часто запрашиваемых ресурсов локально. Если несколько пользователей запрашивают один и тот же контент (например, видео-урок), прокси отдает его из кэша, экономя внешнюю полосу пропускания и ускоряя доступ.
*   **Логирование:** Аудит активности пользователей для мониторинга безопасности и соблюдения корпоративных политик.

#### Преимущества Обратного прокси (Reverse Proxy)

Использование Reverse Proxy (например, Nginx, HAProxy, Angie) дает ряд критических преимуществ:

1.  **Безопасность (Security):** Скрывает реальные IP-адреса бэкенд-серверов. Все запросы проходят через единую точку входа, где настроены WAF (Web Application Firewall) и защита от DDoS.
2.  **SSL/TLS Termination:** Прокси берет на себя ресурсоемкую расшифровку трафика. Бэкенды получают «чистый» HTTP-трафик, что снижает нагрузку на их CPU и централизует управление сертификатами.
3.  **Управление соединениями (Connection Management):** Прокси эффективно поддерживает тысячи медленных клиентских соединений (Slow Clients), передавая на бэкенд быстрые, оптимизированные запросы (Keep-alive).
4.  **Балансировка нагрузки (Load Balancing):** Распределение запросов между несколькими экземплярами приложения для повышения отказоустойчивости и производительности. Это ключевая функция обратного прокси.
5.  **Кэширование:** Прокси может отдавать статический контент (картинки, стили) и кэшировать динамические ответы бэкенда, значительно снижая нагрузку на приложение.
6.  **Интеллектуальная маршрутизация:** Маршрутизация на основе заголовков, Cookies, данных сессии или путей URL. Например, перенаправление вегетарианских запросов (по заголовку) на специализированный микросервис.

### Многослойный подход (Cloud LB + Reverse Proxy)

В современных инфраструктурах часто используется комбинация облачных балансировщиков и программных прокси для обеспечения максимальной безопасности и гибкости.

| Слой | Компонент | Роль |
| :--- | :--- | :--- |
| **Внешний (L4)** | Cloud Load Balancer (NLB/ALB) | Первая линия защиты. Принимает внешний трафик, выполняет базовую балансировку по «занятости» узлов. |
| **Внутренний (L7)** | Reverse Proxy (Ingress Controller) | Тонкая маршрутизация внутри приватной сети, SSL-терминация, проверка сессий, Sticky Sessions. |

**Преимущества такой схемы:**
*   **Инкапсуляция:** Вся внутренняя сеть (бэкенды и реверс-прокси) полностью скрыта в приватном сегменте.
*   **Гибкая логика:** Облачные LB часто ограничены простыми алгоритмами. Reverse Proxy позволяет реализовать продвинутую логику (например, сессионную привязку).

#### Практический паттерн: Nginx + Express.js
Распространенный сценарий в production-средах:
*   **Nginx (Reverse Proxy):** Обрабатывает статику, терминирует SSL, балансирует нагрузку и защищает от перегрузок.
*   **Express.js (App Server):** Занимается только динамическим контентом и бизнес-логикой.
Nginx обрабатывает конкурентные соединения гораздо эффективнее, чем Node.js, что делает систему стабильнее под высокой нагрузкой.

#### Алгоритмы балансировки трафика

*   **Round Robin (RR):** Циклический перебор серверов. Подходит для серверов с одинаковой мощностью.
*   **Least Connections:** Запрос направляется на сервер с наименьшим количеством активных соединений. Эффективно, если запросы имеют разное время выполнения.
*   **Weighted (Round Robin/Least Conn):** Учет весов серверов (мощности). Сервер с весом 2 получит в два раза больше запросов, чем с весом 1.
*   **IP Hash:** Привязка клиента к конкретному серверу на основе его IP-адреса.
*   **Sticky Sessions (Session Affinity):** Привязка клиента через Cookie. Гарантирует, что пользователь будет попадать на тот же сервер в рамках одной сессии (критично для Stateful приложений).

### По протоколам

*   **HTTP-прокси:** Работает на уровне L7. Понимает структуру HTTP-запросов.
*   **SOCKS (v4/v5):** Универсальный протокол проксирования на уровне L5.
    *   **SOCKS5:** Поддерживает IPv6, UDP и аутентификацию (в отличие от SOCKS4).
*   **CGI-прокси (Анонимайзеры):** Веб-интерфейс, позволяющий открывать страницы внутри другого сайта.

### По уровню анонимности

1.  **Прозрачный (Transparent):** Передает `X-Forwarded-For` с реальным IP клиента.
2.  **Анонимный (Anonymous):** Скрывает IP клиента, но сообщает серверу, что используется прокси (заголовок `Via`).
3.  **Искажающий (Distorting):** Передает поддельный IP клиента.
4.  **Элитный (Elite / High Anonymity):** Полностью скрывает факт использования прокси.

## Практические сценарии

### Сценарий 1: Обратный прокси с SSL-терминацией и балансировкой (Nginx)

**Предварительные требования:**
- Nginx 1.24+ (с модулем `stream` для L4 или `http` для L7)
- Два бэкенд-сервера: `192.168.1.10:8080`, `192.168.1.11:8080`
- SSL-сертификат: `/etc/nginx/ssl/example.com.crt` и `.key`

**Шаг 1: Базовая конфигурация обратного прокси (L7, HTTP/HTTPS)**

```nginx
# /etc/nginx/conf.d/example.com.conf

upstream backend_cluster {
    zone backend_zone 64k;
    server 192.168.1.10:8080 max_fails=3 fail_timeout=10s;
    server 192.168.1.11:8080 max_fails=3 fail_timeout=10s;
    keepalive 32;
}

server {
    listen 80;
    server_name example.com;
    return 301 https://$host$request_uri;
}

server {
    listen 443 ssl http2;
    server_name example.com;

    ssl_certificate /etc/nginx/ssl/example.com.crt;
    ssl_certificate /etc/nginx/ssl/example.com.key;
    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_ciphers ECDHE-ECDSA-AES128-GCM-SHA256:ECDHE-RSA-AES128-GCM-SHA256;
    ssl_prefer_server_ciphers off;
    ssl_session_cache shared:SSL:10m;
    ssl_session_timeout 10m;

    # Передача реального IP клиента бэкенду
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;

    location / {
        proxy_pass http://backend_cluster;
        proxy_http_version 1.1;
        proxy_set_header Connection "";
        
        # Таймауты
        proxy_connect_timeout 5s;
        proxy_send_timeout 60s;
        proxy_read_timeout 60s;
    }
}
```

**Шаг 2: Проверка конфигурации и перезагрузка**

```bash
# Проверка синтаксиса
sudo nginx -t
# → nginx: configuration file /etc/nginx/nginx.conf test is successful

# Перезагрузка без потери соединений
sudo systemctl reload nginx
```

**Шаг 3: Валидация**

```bash
# Проверка ответа через HTTPS
curl -I https://example.com
# → HTTP/2 200
# → Server: nginx (скрыть через proxy_hide_header)

# Проверка балансировки (логи бэкендов)
# Должны чередоваться запросы между 192.168.1.10 и 192.168.1.11

# Проверка заголовков
curl -I https://example.com | grep -E "X-Real-IP|X-Forwarded"
# → X-Real-IP: <IP клиента>
# → X-Forwarded-For: <IP клиента>
# → X-Forwarded-Proto: https
```

### Сценарий 2: Прямой прокси с авторизацией и кэшированием (Squid)

**Предварительные требования:**
- Ubuntu/Debian сервер с публичным IP
- Порт 3128 открыт для клиентов (192.168.1.0/24)

**Шаг 1: Установка Squid**

```bash
sudo apt update && sudo apt install -y squid
```

**Шаг 2: Конфигурация `/etc/squid/squid.conf`**

```bash
# Порт прокси
http_port 3128

# Локальная сеть
acl localnet src 192.168.1.0/24

# Настройка авторизации
auth_param basic program /usr/lib/squid/basic_ncsa_auth /etc/squid/passwords
auth_param basic children 5
auth_param basic realm Squid proxy-caching web server
auth_param basic credentialsttl 2 hours

acl authenticated proxy_auth REQUIRED
http_access allow authenticated localnet
http_access deny all

# Кэширование
cache_dir ufs /var/spool/squid 10000 16 256
maximum_object_size 4096 KB
minimum_object_size 0 KB
cache_swap_low 90
cache_swap_high 95

# Логирование
access_log /var/log/squid/access.log squid
```

**Шаг 3: Создание пользователя**

```bash
sudo apt install -y apache2-utils
sudo htpasswd -c /etc/squid/passwords proxyuser
# → New password: ****
# → Re-type new password: ****
# → Adding password for user proxyuser
```

**Шаг 4: Запуск и проверка**

```bash
sudo systemctl enable --now squid

# Проверка порта
ss -tlnp | grep 3128
# → LISTEN 0 128 0.0.0.0:3128 0.0.0.0:* users:(("squid",pid=1234,fd=6))

# Тест с клиента
curl -x http://proxyuser:password@proxy.example.com:3128 http://example.com
# → Должен получить контент example.com
```

**Шаг 5: Настройка клиента (Windows/Linux/macOS)**

```bash
# Переменные окружения (Linux/macOS)
export http_proxy="http://proxyuser:password@proxy.example.com:3128"
export https_proxy="http://proxyuser:password@proxy.example.com:3128"
export no_proxy="localhost,127.0.0.1,.localdomain"
```

### Сценарий 3: Балансировка L4 (TCP) с проверками здоровья (HAProxy)

**Предварительные требования:**
- HAProxy 2.8+
- Бэкенд-сервис на порту 5432 (PostgreSQL) или 3306 (MySQL)

**Шаг 1: Конфигурация `/etc/haproxy/haproxy.cfg`**

```haproxy
global
    log /dev/log local0
    maxconn 2000
    daemon

defaults
    log     global
    mode    tcp
    option  tcplog
    timeout connect 5s
    timeout client  30s
    timeout server  30s
    retries 3

frontend postgres_front
    bind *:5432
    default_backend postgres_back

backend postgres_back
    balance leastconn
    option tcp-check
    tcp-check send PING\r\n
    tcp-check expect string PONG
    
    server pg01 192.168.1.20:5432 check inter 5s fall 2 rise 3
    server pg02 192.168.1.21:5432 check inter 5s fall 2 rise 3
    server pg03 192.168.1.22:5432 check inter 5s fall 2 rise 3 backup
```

**Шаг 2: Проверка и запуск**

```bash
# Проверка конфигурации
sudo haproxy -c -f /etc/haproxy/haproxy.cfg
# → Configuration file is valid

# Запуск
sudo systemctl enable --now haproxy

# Проверка статуса
sudo systemctl status haproxy
# → Active: active (running)
```

**Шаг 3: Мониторинг через Stats Socket**

```bash
# В конфиге добавьте:
# listen stats
#     bind *:8404
#     stats enable
#     stats uri /stats
#     stats refresh 10s

curl http://localhost:8404/stats
# → Таблица с серверами, статусами (UP/DOWN), текущими сессиями
```

### Сценарий 4: Обнаружение сервисов в Docker Swarm (Traefik)

**Предварительные требования:**
- Docker Swarm инициализирован (`docker swarm init`)
- Traefik развернут как сервис

**Шаг 1: Развертывание Traefik**

```yaml
# docker-compose.traefik.yml
version: "3.8"

services:
  traefik:
    image: traefik:v3.0
    command:
      - "--api.insecure=true"
      - "--providers.docker=true"
      - "--providers.docker.swarmMode=true"
      - "--providers.docker.exposedbydefault=false"
      - "--entrypoints.web.address=:80"
      - "--entrypoints.websecure.address=:443"
      - "--certificatesresolvers.le.acme.tlschallenge=true"
      - "--certificatesresolvers.le.acme.email=admin@example.com"
      - "--certificatesresolvers.le.acme.storage=/letsencrypt/acme.json"
    ports:
      - "80:80"
      - "443:443"
      - "8080:8080"
    volumes:
      - "/var/run/docker.sock:/var/run/docker.sock:ro"
      - "letsencrypt:/letsencrypt"
    deploy:
      placement:
        constraints:
          - node.role == manager

volumes:
  letsencrypt:
```

**Шаг 2: Развертывание приложения с автоматическим проксированием**

```yaml
# docker-compose.app.yml
version: "3.8"

services:
  web:
    image: nginx:alpine
    deploy:
      replicas: 3
      labels:
        - "traefik.enable=true"
        - "traefik.http.routers.web.rule=Host(`example.com`)"
        - "traefik.http.routers.web.entrypoints=websecure"
        - "traefik.http.routers.web.tls.certresolver=le"
        - "traefik.http.services.web.loadbalancer.server.port=80"
    networks:
      - traefik-public

networks:
  traefik-public:
    external: true
```

**Шаг 3: Развертывание**

```bash
docker stack deploy -c docker-compose.traefik.yml traefik
docker stack deploy -c docker-compose.app.yml webapp

# Проверка
curl https://example.com
# → Должен вернуть ответ от одного из реплик Nginx
```

## Валидация и диагностика

### Проверка работы прокси

```bash
# 1. Проверка доступности порта
nc -zv proxy.example.com 3128
# → Connection to proxy.example.com 3128 port [tcp/*] succeeded!

# 2. Проверка через curl с заголовками
curl -v -x http://proxy.example.com:3128 http://example.com 2>&1 | grep -E "< HTTP|Via|X-Forwarded"

# 3. Проверка конфигурации Nginx
sudo nginx -t
# → syntax is ok
# → test is successful

# 4. Проверка статуса сервисов
sudo systemctl status nginx squid haproxy traefik

# 5. Проверка логов
tail -f /var/log/nginx/access.log /var/log/squid/access.log /var/log/haproxy.log
```

### Диагностика SSL/TLS

```bash
# Проверка сертификата
openssl s_client -connect example.com:443 -servername example.com </dev/null 2>/dev/null | openssl x509 -noout -dates

# Проверка поддерживаемых протоколов
nmap --script ssl-enum-ciphers -p 443 example.com

# Проверка OCSP staple
openssl s_client -connect example.com:443 -status </dev/null 2>/dev/null | grep -A 17 "OCSP response"
```

### Анализ трафика

```bash
# Перехват трафика на порту прокси
sudo tcpdump -i any port 3128 -w proxy.pcap

# Анализ в Wireshark: фильтр "tcp.port == 3128"

# Проверка соединений к бэкендам
ss -tnp | grep :8080
# → ESTAB 0 0 192.168.1.5:8080 192.168.1.10:80 users:(("nginx",pid=1234,fd=12))
```

## Устранение неполадок

### Проблема: 502 Bad Gateway

**Причины:**
- Бэкенд недоступен (отказал/не запущен)
- Таймаут соединения
- Неверный `proxy_pass`

**Диагностика:**
```bash
# Проверка доступности бэкенда
curl -v http://192.168.1.10:8080/health

# Проверка логов Nginx
tail -f /var/log/nginx/error.log
# → connect() failed (111: Connection refused) while connecting to upstream

# Проверка firewall
sudo iptables -L -n | grep 8080
```

**Решение:**
- Убедиться, что бэкенд запущен: `systemctl status app`
- Проверить `proxy_pass` на правильность IP/порта
- Увеличить `proxy_connect_timeout`

### Проблема: Клиент видит реальный IP бэкенда

**Причина:** Прокси не передает заголовки `X-Forwarded-For`/`X-Real-IP`.

**Решение:**
```nginx
# В location блоке:
proxy_set_header X-Real-IP $remote_addr;
proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
```

### Проблема: HTTPS не работает через прокси

**Причина:** Прокси не настроен для SSL-терминации или проброса CONNECT.

**Диагностика:**
```bash
# Проверка открытого порта 443
nc -zv proxy.example.com 443

# Проверка сертификата
openssl s_client -connect proxy.example.com:443
```

**Решение (Nginx):**
```nginx
server {
    listen 443 ssl;
    ssl_certificate /etc/nginx/ssl/example.com.crt;
    ssl_certificate_key /etc/nginx/ssl/example.com.key;
    
    location / {
        proxy_pass https://backend;
        proxy_ssl_server_name on;  # Для SNI
    }
}
```

### Проблема: Кэш не обновляется

**Причина:** Устаревшие заголовки `Cache-Control` или `Expires`.

**Диагностика:**
```bash
curl -I http://example.com/image.jpg | grep -i cache
# → Cache-Control: max-age=86400
# → Age: 3600
```

**Решение:**
```nginx
# Принудительная инвалидация
proxy_cache_bypass $http_cache_purge;
proxy_cache_purge $scheme$request_method$host$request_uri;

# Или настройка короткого TTL для динамического контента
location /api/ {
    proxy_cache_valid 200 302 10m;
    proxy_cache_valid 404 1m;
}
```

### Проблема: SSRF через прокси

**Причина:** Злоумышленник заставляет прокси отправить запрос во внутреннюю сеть.

**Диагностика:**
```bash
# Проверка, может ли прокси достичь внутренних адресов
curl -x http://proxy:3128 http://192.168.1.1/admin
```

**Решение:**
- Использовать белые списки доменов
- Ограничить доступ прокси к внутренним подсетям через firewall
- Настроить `squid.conf`: `acl internal dst 192.168.1.0/24; http_access deny internal`

## Лучшие практики

### Безопасность

1. **Сокрытие версии:** Отключите заголовок `Server` и `Via`.
   ```nginx
   server_tokens off;
   proxy_hide_header Server;
   ```

2. **Ограничение методов:** Разрешайте только необходимые HTTP-методы.
   ```nginx
   if ($request_method !~ ^(GET|HEAD|POST)$ ) {
       return 405;
   }
   ```

3. **Заголовки безопасности:** Добавляйте CSP, HSTS, X-Frame-Options.
   ```nginx
   add_header X-Frame-Options "SAMEORIGIN";
   add_header X-Content-Type-Options "nosniff";
   add_header Strict-Transport-Security "max-age=31536000; includeSubDomains" always;
   ```

4. **IP-фильтрация:** Ограничьте доступ к прокси доверенными подсетями.
   ```nginx
   # Для reverse proxy
   location /admin {
       allow 10.0.0.0/8;
       allow 192.168.0.0/16;
       deny all;
   }
   ```

5. **Аутентификация:** Используйте базовую аутентификацию или интеграцию с LDAP/OAuth.

### Производительность

1. **Кэширование статики:** Настройте длительный TTL для статических ресурсов.
2. **Сжатие:** Включите gzip/brotli для уменьшения размера ответов.
3. **Keep-alive:** Поддерживайте постоянные соединения к бэкендам.
   ```nginx
   upstream backend {
       server 192.168.1.10:8080;
        keepalive 32;
    }
    proxy_http_version 1.1;
    proxy_set_header Connection "";
   ```
4. **Очереди и лимиты:** Ограничьте частоту запросов (rate limiting).
   ```nginx
   limit_req_zone $binary_remote_addr zone=api:10m rate=10r/s;
   location /api/ {
       limit_req zone=api burst=20 nodelay;
   }
   ```

### Мониторинг

1. **Метрики:** Используйте Prometheus-экспортеры (nginx-vts, haproxy-exporter).
2. **Логирование:** Формат `combined` или JSON для централизованного сбора.
3. **Health Checks:** Настройте активные проверки здоровья бэкендов.
4. **Алертинг:** Оповещения при росте 5xx, задержек (P99 > 2s) или недоступности бэкендов.

### Эксплуатация

1. **Резервное копирование:** Бэкап конфигураций (`/etc/nginx/`, `/etc/haproxy/`, `/etc/squid/`).
2. **Ротация логов:** Настройте `logrotate` для предотвращения заполнения диска.
3. **Обновление:** Используйте rolling updates для минимизации простоя.
4. **Изоляция:** Разделяйте staging и production окружения разными инстансами прокси.

## Автоматическая настройка (Discovery)

Для того чтобы клиенты в больших сетях автоматически находили прокси, используются:
- **PAC (Proxy Auto-Config):** JavaScript-файл с функцией `FindProxyForURL(url, host)`, определяющей, через какой прокси идти к конкретному хосту.
- **WPAD (Web Proxy Auto-Discovery):** Метод обнаружения URL PAC-файла через DHCP или DNS (поиск хоста `wpad.domain.com`).

## Риски безопасности

*   **Open Proxy (Открытый прокси):** Неправильно настроенный прокси, доступный всему интернету. Часто используется злоумышленниками для рассылки спама и проведения атак.
*   **SSRF (Server-Side Request Forgery):** Атака, при которой злоумышленник заставляет прокси (обычно Reverse Proxy) отправить запрос во внутреннюю сеть, недоступную извне.
*   **Инъекция данных:** Модификация ответов прокси-сервером (подмена рекламы, вставка вредоносного JS-кода).

## Современные технологии

### Протокол Proxy Protocol (v1/v2)
[Proxy Protocol](../Protocols/proxy_protocol.md) позволяет передавать исходный IP клиента через цепочку L4-прокси. В отличие от заголовков HTTP, он работает на уровне TCP-соединения.

### Service Mesh и Sidecar-прокси
В микросервисных архитектурах прокси (например, **Envoy**) запускается рядом с каждым приложением.
- **Sidecar-less (Ambient Mesh):** Использование **Ztunnel** (L4 прокси на языке Rust) на каждой ноде кластера для mTLS и телеметрии без внедрения контейнеров-сайдкаров.
- **eBPF Acceleration:** Технологии вроде Cilium используют eBPF для ускорения проксирования и фильтрации трафика прямо в ядре Linux.

### Проксирование gRPC
Современные прокси (Envoy, Nginx, Traefik) поддерживают gRPC (HTTP/2), что позволяет балансировать вызовы удаленных процедур с сохранением преимуществ QoS и аутентификации.

### Проксирование WebSocket

Для поддержки WebSocket прокси должен корректно обрабатывать заголовки `Upgrade` и `Connection`:

```nginx
location /ws/ {
    proxy_pass http://backend;
    proxy_http_version 1.1;
    proxy_set_header Upgrade $http_upgrade;
    proxy_set_header Connection "upgrade";
    proxy_set_header Host $host;
    
    # Таймауты для долгих соединений
    proxy_read_timeout 3600s;
    proxy_send_timeout 3600s;
}
```

**Особенности:**
- Требует HTTP/1.1 (не работает с HTTP/1.0)
- Некоторые балансировщики требуют отдельного `map` для `Upgrade`
- Sticky Sessions обязательны, если бэкенд хранит состояние WebSocket-сессий

### Проксирование HTTP/3 (QUIC)

С версии Nginx 1.25+ поддерживается прием QUIC-соединений:

```nginx
server {
    listen 443 quic reuseport;
    listen 443 ssl;
    
    # Заголовки для миграции с HTTP/2 на HTTP/3
    add_header Alt-Svc 'h3=":443"; ma=86400';
    
    proxy_pass http://backend;
}
```

## Популярные инструменты

*   **Nginx / Angie:** Стандарт для Reverse Proxy и балансировки. [Обзор Nginx](../../WebServers/Nginx/Core/nginx_overview.md).
*   **HAProxy:** Высокопроизводительный балансировщик L4/L7. [Обзор HAProxy](../../WebServers/haproxy_overview.md).
*   **Envoy:** Cloud-native прокси, основа для Istio. [Proxy Sidecar](../../Service_Mesh/proxy_sidecar.md).
*   **Squid:** Классический Forward Proxy с мощными возможностями кэширования.
*   **Traefik:** Прокси для Docker/Kubernetes с авто-обнаружением. [Обзор Traefik](../../WebServers/Traefik/traefik_overview.md).
*   **Mitmproxy:** Интерактивный прокси для отладки HTTPS-трафика и анализа.

## Дополнительная информация

- [Сравнение Proxy и VPN](./proxy-vs-vpn.md)
- [Протокол Proxy Protocol](../Protocols/proxy_protocol.md)
- [Прозрачный прокси через NAT](./nat/transparent_proxy.md)
- [Балансировка нагрузки (Nginx)](../../WebServers/Nginx/Proxy/Load_Balancing/overview_concepts.md)
- [Прокси Sidecar: реализации и сценарии](../../Service_Mesh/proxy_sidecar.md)
- [Жизненный цикл веб-запроса](./web_request_lifecycle.md)
