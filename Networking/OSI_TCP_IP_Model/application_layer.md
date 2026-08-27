# Прикладной уровень (L7)

## Определения

**Прикладной уровень (Application Layer, L7)** — верхний уровень сетевых моделей [OSI](./osi_model.md) и [TCP/IP](./tcp_ip_model.md), обеспечивающий прямой интерфейс взаимодействия между программным обеспечением (приложениями) и сетевыми службами. Это единственный уровень, который напрямую работает с семантикой данных и бизнес-логикой.

- **PDU (Protocol Data Unit):** Данные (Data) / Сообщение (Message). Размер PDU на L7 не фиксирован и определяется протоколом: от 1 байта (DNS query) до десятков мегабайт (file transfer).
- **Адресация:** Идентификаторы прикладного уровня (URL, FQDN, Email, API-эндпоинты). На транспортном уровне опирается на [сетевые порты](../Concepts/network_ports.md).

> **Критическое различие:** Сетевое приложение (браузер, почтовый клиент, терминал) — это программный интерфейс, в то время как **прикладной протокол** (HTTP, SMTP, SSH) — это набор правил обмена данными, которые использует это приложение.

## Базовые концепции

### Инкапсуляция данных: прохождение через стек

```text
[HTTP GET /api/users HTTP/1.1]         ← L7: прикладной протокол
[TLS Application Data]                 ← L6: шифрование (если HTTPS)
[No explicit session layer]            ← L5: отсутствует в TCP/IP (функции L5/L6 встроены в L7/L4)
[TCP Segment: Src=49152 Dst=443]       ← L4: транспорт
[IP Packet: Src=10.0.0.1 Dst=93.184.216.34] ← L3: маршрутизация
[Ethernet Frame: MAC]                  ← L2: коммутация
[Electrical/Optical Signal]            ← L1: физическая передача
```

### Взаимодействие с соседними уровнями

```text
L7 (Прикладной)  ← Приложение формирует данные, форматирует по протоколу
       ↕
L6 (Представления) ← Шифрование (TLS), сжатие, сериализация (Protobuf, JSON)
       ↕
L5 (Сеансовый)   ← Управление сессиями (отсутствует в TCP/IP как отдельный слой)
       ↕
L4 (Транспортный) ← TCP/UDP: доставка данных между процессами
       ↕
L3 (Сетевой)     ← IP: маршрутизация пакетов
```

| Протокол L4 | Требование L7 | Примеры L7-протоколов |
| :--- | :--- | :--- |
| **[TCP](../Protocols/TCP/overview.md)** | Целостность и порядок | HTTP/1.1, HTTP/2, SSH, БД (PostgreSQL, MySQL), gRPC, AMQP |
| **[UDP](../Protocols/udp.md)** | Минимальная задержка | DNS, DHCP, VoIP (SIP/RTP), QUIC (база для HTTP/3), SNMP |

### Семантика взаимодействия

На прикладном уровне выделяют несколько паттернов обмена данными:

1.  **Запрос-ответ (Request-Response):** Клиент запрашивает ресурс, сервер отвечает (HTTP, DNS, Redis). Клиент всегда инициирует — сервер не может начать взаимодействие первым.
2.  **Стриминг (Streaming):** Непрерывная передача данных в одном или обоих направлениях (gRPC streams, WebSocket, Server-Sent Events). Используется для реалтайм-обновлений и обработки больших объёмов данных.
3.  **Издатель-подписчик (Pub/Sub):** Асинхронная передача через посредника (Kafka, MQTT, AMQP). Развязка производителя и потребителя по времени и пространству.
4.  **Full-Duplex (Двусторонний обмен):** Полноценное двунаправленное соединение без жёсткой привязки к модели «клиент-сервер» (WebSocket, gRPC bidirectional streams).
5.  **Push (Серверная инициация):** Сервер отправляет данные клиенту без предварительного запроса (Server-Sent Events, Web Push, gRPC Server Streaming).

### Типы прокси и балансировщиков L7

| Тип | Уровень | Функции | Примеры |
| :--- | :--- | :--- | :--- |
| **Forward Proxy** | L7 | Сокрытие клиента, кэширование, фильтрация | Squid, Privoxy |
| **Reverse Proxy** | L7 | Маршрутизация, терминация TLS, балансировка, WAF | Nginx, Envoy, HAProxy, Traefik |
| **API Gateway** | L7 | Аутентификация, Rate Limiting, маршрутизация API | Kong, Tyk, Apigee |
| **Service Mesh Proxy** | L7 | mTLS, observability, circuit breaking между подами | Envoy (Istio), Cilium |
| **Transparent Proxy** | L7 | Перехват трафика без изменения настроек клиента | iptables REDIRECT + Squid |

### Современные парадигмы: gRPC и HTTP/3

В современной инфраструктуре (2026+) доминируют бинарные протоколы и оптимизация задержек:

1.  **HTTP/3 (QUIC):** Работает поверх UDP, устраняет проблему блокировки начала очереди (HOL Blocking). Использует 0-RTT для мгновенной установки соединения и встроенное шифрование. Подробнее: **[Эволюция HTTP](../Protocols/HTTP/http_versions.md)**.
2.  **gRPC:** Использует Protocol Buffers (Protobuf) для компактной сериализации и HTTP/2 или HTTP/3 для транспорта. Обеспечивает строгую типизацию и двунаправленный стриминг. Подробнее: **[Обзор gRPC](../ServicesAndTools/grpc_overview.md)**.
3.  **WebSocket:** Протокол для двустороннего обмена данными поверх TCP (порт 80/443). Инициируется через HTTP Upgrade. Используется в чатах, игровых серверах, реалтайм-мониторинге.
4.  **GraphQL:** Язык запросов для API, позволяющий клиенту запрашивать только нужные поля. Решает проблему Over-fetching и Under-fetching в REST. Подробнее: **[REST API](../Protocols/HTTP/http_rest_api.md)**.

## Практические сценарии

### Инфраструктурные компоненты L7

| Компонент | Функции | Примеры |
| :--- | :--- | :--- |
| **API Gateway** | Централизованная маршрутизация, Rate Limiting, агрегация API, аутентификация | [Обзор API Gateway](../../Concepts/api_gateway_overview.md), Kong, Tyk, Apigee |
| **L7-балансировщики** | Терминация TLS, маршрутизация по Host/Path/Cookies, балансировка gRPC | [Nginx](../../WebServers/Nginx/Core/nginx_overview.md), Envoy, HAProxy, Angie |
| **Service Mesh** | mTLS, интеллектуальная маршрутизация (Canary, Blue-Green), Observability | [Service Mesh Concepts](../../Service_Mesh/service_mesh_concepts.md), Istio, Cilium (eBPF) |
| **WAF** | Глубокая инспекция трафика (DPI) для защиты от SQLi, XSS и L7 DDoS | [WAF: Межсетевой экран веб-приложений](../../Security/ApplicationSecurity/waf.md), Cloudflare |
| **CDN Edge** | Кэширование, сжатие, TLS termination, защита от DDoS | Cloudflare, Akamai, CloudFront |

### Таблица основных протоколов

| Протокол | Назначение | Стандартные порты | Транспорт (L4) | Формат данных |
| :--- | :--- | :--- | :--- | :--- |
| **[HTTP/HTTPS](../Protocols/HTTP/http_basics.md)** | Веб-трафик, REST API, JSON-RPC | 80, 443 | TCP / UDP (QUIC) | Текст (1.1) / Бинарный (2, 3) |
| **[DNS](../Protocols/DNS/dns.md)** | Разрешение имен в IP-адреса | 53, 853 (DoT) | UDP / TCP | Бинарный |
| **gRPC** | Высокопроизводительный RPC (микросервисы) | Любой | TCP / UDP | Protobuf (бинарный) |
| **WebSocket** | Двусторонний обмен в реальном времени | 80, 443 | TCP | Бинарный / Текст |
| **SSH** | Безопасное удаленное управление | 22 | TCP | Бинарный (шифрованный) |
| **TLS** | Шифрование и аутентификация | 443 (HTTPS), 853 (DoT) | TCP | Бинарный (records) |
| **[SMTP](../Protocols/smtp.md)** | Отправка почты | 25, 587, 465 | TCP | Текст (7-bit) |
| **IMAP / POP3** | Получение почты | 143, 993 / 110, 995 | TCP | Текст |
| **FTP** | Передача файлов | 20 (data), 21 (control) | TCP | Текст / Бинарный |
| **Redis** | In-memory хранилище данных (RESP) | 6379 | TCP | Текст (RESP3) / Бинарный |
| **Kafka / AMQP** | Очереди сообщений и стриминг | 9092, 5672 | TCP | Бинарный |
| **[DHCP](../Protocols/DHCP/dhcp_overview.md)** | Динамическая настройка IP узлов | 67, 68 | UDP | Бинарный |
| **SNMP** | Мониторинг и управление сетевыми устройствами | 161 (query), 162 (trap) | UDP | Бинарный (BER/ASN.1) |
| **NTP** | Синхронизация времени | 123 | UDP | Бинарный |

### Сравнение L4 vs L7 балансировки

| Характеристика | L4 (Транспортный) | L7 (Прикладной) |
| :--- | :--- | :--- |
| **Анализ** | IP, TCP/UDP порт | HTTP-заголовки, URL, Cookies, Host |
| **Производительность** | Экстремально высокая (ASIC) | Ниже (парсинг L7-данных) |
| **Терминация TLS** | Passthrough (SSL Passthrough) | Termination (SSL Offloading) |
| **Маршрутизация** | По IP:Port | По Path, Host, Header, Method |
| **Применение** | БД, DNS, Почта, базовая отказоустойчивость | Веб, API, gRPC, WebSocket |

## Наблюдаемость и безопасность L7

### Наблюдаемость (Observability)
L7 — это уровень, на котором собираются «золотые сигналы» (Golden Signals) производительности:
- **Latency (Задержка):** Время обработки запроса сервером. Измеряется от получения запроса до отправки ответа (TTFB — Time To First Byte).
- **Traffic (Трафик):** Интенсивность (RPS — запросы в секунду). Мониторинг паттернов: пиковые часы, аномалии.
- **Errors (Ошибки):** Процент ответов 4xx/5xx или gRPC error codes. Важно разделять клиентские (4xx) и серверные (5xx) ошибки.
- **Saturation (Насыщенность):** Использование ресурсов (CPU/RAM) прикладным процессом. Критические метрики: Active Connections, Queue Depth, Connection Pool Usage.

Инструменты на базе **eBPF** (например, Cilium, Hubble) позволяют получать L7-метрики без модификации кода приложения.

### Диагностика L7

```bash
# === HTTP/HTTPS ===

# Базовый тест HTTP-сервера
curl -v https://example.com

# Проверка HTTP/2 поддержки
curl -I --http2 https://example.com  # → HTTP/2 200

# Проверка HTTP/3 поддержки (требуется curl с ngtcp2)
curl -I --http3 https://example.com

# Замер времени ответа (TTFB)
curl -o /dev/null -s -w "DNS: %{time_namelookup}s\nConnect: %{time_connect}s\nTLS: %{time_appconnect}s\nTTFB: %{time_starttransfer}s\nTotal: %{time_total}s\n" https://example.com

# Проверка заголовков и HTTP-методов
curl -X OPTIONS -I https://api.example.com/users

# POST-запрос с JSON
curl -X POST https://api.example.com/users \
  -H "Content-Type: application/json" \
  -d '{"name": "test"}'

# === DNS ===

# Базовый запрос A-записи
dig example.com A

# Запрос MX-записей
dig example.com MX

# Проверка DNS через DoT (DNS over TLS)
dig @1.1.1.1 example.com TLS

# Обратный DNS-запрос (PTR)
dig -x 93.184.216.34

# Проверка DNS-резолвера
resolvectl query example.com

# === TLS/SSL ===

# Проверка TLS-соединения
openssl s_client -connect example.com:443 -servername example.com

# Проверка сертификата
openssl s_client -connect example.com:443 2>/dev/null | openssl x509 -noout -dates -subject

# Проверка поддержки ALPN
openssl s_client -connect example.com:443 -alpn h2,http/1.1

# === gRPC ===

# Вызов gRPC-сервиса (требуется grpcurl)
grpcurl -plaintext localhost:50051 list

# Вызов метода с JSON
grpcurl -plaintext -d '{"name": "test"}' localhost:50051 mypackage.MyService/MyMethod

# === Telnet / Netcat (базовая проверка порта) ===

# Проверка доступности порта
nc -zv example.com 443

# Тест SSL через netcat
echo -e "GET / HTTP/1.1\r\nHost: example.com\r\n\r\n" | nc example.com 443
```

### Безопасность

| Тип атаки | Описание | Защита |
| :--- | :--- | :--- |
| **HTTP Flood** | Имитация легитимных HTTP-запросов для исчерпания ресурсов сервера | Rate Limiting, WAF, CAPTCHA, анализ поведения |
| **Slowloris** | Медленное открытие соединений для исчерпания воркеров/коннектов | Таймауты (keepalive_timeout), rate-limiting по IP |
| **SQL Injection** | Внедрение SQL-кода через параметры запроса | Prepared Statements, WAF, валидация входных данных |
| **XSS (Cross-Site Scripting)** | Внедрение клиентского JavaScript | Content Security Policy (CSP), escaping, WAF |
| **BOLA/IDOR** | Обход авторизации через манипуляцию ID ресурсов | ABAC, валидация ownership, rate-limiting |
| **API Abuse** | Перебор, credential stuffing, mass assignment | Rate Limiting, API Keys, OAuth 2.0, request validation |

Защита на прикладном уровне требует понимания протокола (Deep Packet Inspection):
- **Инспекция TLS:** Расшифровка трафика балансировщиком для анализа угроз. Решение: TLS Termination на WAF/Reverse Proxy.
- **mTLS (Mutual TLS):** Двусторонняя проверка идентичности сервисов в рамках Zero Trust. Подробнее: **[Service Mesh Concepts](../../Service_Mesh/service_mesh_concepts.md)**.
- **Поведенческий анализ:** Выявление ботов и атак на бизнес-логику (например, перебор паролей), которые выглядят как легитимный трафик.

## Дополнительная информация

### Связь с нижними уровнями OSI

Прикладной уровень является основным потребителем сервисов нижестоящих уровней:
- **[Уровень представления (L6)](./presentation_layer.md):** Шифрование ([TLS](../Protocols/tls.md)), сжатие и кодирование. ALPN (Application-Layer Protocol Negotiation) позволяет согласовать HTTP/2 vs HTTP/1.1 в рамках TLS Handshake.
- **[Сеансовый уровень (L5)](./session_layer.md):** Управление жизненным циклом сессий и логических потоков (Streams). В TCP/IP модели функции L5 распределены между L7 (HTTP/2 streams) и L4 (TCP keepalive).
- **[Транспортный уровень (L4)](./transport_layer.md):** TCP обеспечивает надёжную доставку, UDP — минимальную задержку. Выбор транспорта определяет характеристики L7-протокола.

Подробный разбор прохождения данных через весь стек см. в статье **[Жизненный цикл веб-запроса](../Concepts/web_request_lifecycle.md)**.

### Инструменты диагностики L7

| Инструмент | Назначение | Примеры команд |
| :--- | :--- | :--- |
| `curl` | Тестирование HTTP/HTTPS, заголовков, методов | `curl -v https://example.com` |
| `dig` / `nslookup` | DNS-резолвинг, проверка записей | `dig example.com A` |
| `openssl s_client` | Проверка TLS-соединения, сертификатов | `openssl s_client -connect example.com:443` |
| `grpcurl` | Вызов gRPC-сервисов | `grpcurl -plaintext localhost:50051 list` |
| `nc` (netcat) | Проверка доступности портов | `nc -zv example.com 443` |
| `nmap` | Сканирование сервисов и версий | `nmap -sV -p 80,443 example.com` |
| `tshark` | Захват и анализ L7-трафика | `tshark -f "tcp port 443" -Y "http"` |

### См. также

- [Модель OSI](./osi_model.md) — общая структура всех уровней.
- [Модель TCP/IP](./tcp_ip_model.md) — практическая реализация стека.
- [Сетевые порты](../Concepts/network_ports.md) — адресация прикладных процессов на L4.
- [API Gateway Обзор](../../Concepts/api_gateway_overview.md) — архитектурный паттерн управления L7.
- [HTTP Load Balancing](../Protocols/HTTP/http_load_balancing.md) — алгоритмы, health checks, consistent hashing.
- [Контейнерный Networking](./container_networking.md) — CNI, Service, NetworkPolicy в контексте L7.
- [Сетевая автоматизация](../ServicesAndTools/network_automation.md) — автоматизация управления сервисами.
