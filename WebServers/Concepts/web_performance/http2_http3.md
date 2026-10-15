# Протоколы HTTP/2 и HTTP/3 в веб-производительности

**Актуально для:** HTTP/2 (RFC 9113), HTTP/3 (RFC 9114), Linux Kernel 5.15+ / 6.x, Nginx 1.26+, Angie 1.8+

Полное сравнение версий протоколов доступно в руководстве [эволюция HTTP](../../../Networking/Protocols/HTTP/http_versions.md), детали настройки серверов — в статье [конфигурация HTTP/2 и HTTP/3 в Nginx/Angie](../../Nginx/Performance/nginx_http_versions.md), а углубленный разбор оптимизации транспорта — в документе [оптимизация производительности HTTP](../../../Networking/Protocols/HTTP/http_protocols_optimization.md).

## Определения

**HTTP/2 (Hypertext Transfer Protocol Version 2)** — бинарная версия протокола HTTP (RFC 9113), основанная на мультиплексировании независимых двунаправленных потоков данных в рамках единого TCP-соединения. Вводит фреймирование данных и сжатие заголовков (HPACK). В веб-браузерах поддерживается исключительно поверх зашифрованного транспортного уровня TLS (согласование через ALPN `h2`).

**HTTP/3 (Hypertext Transfer Protocol Version 3)** — версия прикладного протокола HTTP на базе транспорта **QUIC** (RFC 9114), функционирующая поверх протокола UDP. Заменяет связку TCP+TLS монолитным стеком QUIC со встроенным шифрованием TLS 1.3, собственным механизмом подтверждения доставки, контролем перегрузок и независимой обработкой потоков.

**QUIC (Quick UDP Internet Connections)** — транспортный протокол транспортного уровня поверх UDP (RFC 9000), объединяющий мультиплексирование потоков без взаимной блокировки, управление перегрузками (BBRv3, NewReno, CUBIC, RFC 9002) и криптографическую защиту TLS 1.3 (RFC 9001).

**HPACK (Header Compression for HTTP/2)** — алгоритм сжатия метаданных заголовков для HTTP/2 (RFC 7541). Использует предварительно согласованный статический словарь (61 запись) и динамический контекстно-зависимый словарь, синхронизируемый между клиентом и сервером в рамках установленного TCP-соединения.

**QPACK (Header Compression for HTTP/3)** — алгоритм сжатия заголовков (RFC 9204), спроектированный для работы в условиях неупорядоченной доставки пакетов в транспорте QUIC. Для предотвращения блокировок декодера использует отдельные служебные потоки (Encoder/Decoder Control Streams).

**ALPN (Application-Layer Protocol Negotiation)** — расширение протокола TLS (RFC 7301), позволяющее клиенту и серверу безопасно согласовать протокол прикладного уровня (`h2`, `h3`, `http/1.1`) на этапе начального TLS-рукопожатия без дополнительных круговых задержек (RTT).

**Head-of-Line Blocking (HOL, Блокировка начала очереди)** — задержка обработки пакетов данных из-за ожидания доставки или обработки предыдущего пакета в очереди:
- В **HTTP/1.1** HOL присутствует на прикладном уровне (запросы в одном TCP-соединении обрабатываются строго последовательно).
- В **HTTP/2** устранена на уровне HTTP-потоков, но сохраняется на уровне транспорта TCP: потеря одного IP-пакета с сегментом TCP останавливает передачу всех мультиплексированных потоков соединения до получения повторного сегмента.
- В **HTTP/3 (QUIC)** полностью устранена: потоки логически изолированы, и потеря UDP-датаграммы блокирует только тот конкретный поток, фрагмент которого был утерян.

**0-RTT (Zero Round Trip Time / Early Data)** — режим быстрого возобновления защищенного сеанса в TLS 1.3 и QUIC (RFC 9001). Позволяет клиенту отправить полезную нагрузку первого HTTP-запроса одновременно с пакетом инициализации сессии. Создает архитектурную уязвимость перед **Replay-атаками** (повторными атаками воспроизведения), поэтому применим исключительно для безопасных идемпотентных запросов (GET, HEAD).

**Connection Migration (Миграция соединения)** — механизм протокола QUIC, позволяющий сохранять открытую сессию и непрерывную передачу данных при смене сетевого интерфейса или IP-адреса клиента (например, переход между Wi-Fi и сотовой сетью). Идентификация сессии базируется на **Connection ID (CID)**, а не на стандартном сетевом сокете 4-tuple.

**Alt-Svc (Alternative Services)** — спецификация и одноименный HTTP-заголовок ответа (RFC 7838), с помощью которого веб-сервер уведомляет клиента о возможности подключения по альтернативному протоколу, хосту или порту (например, анонсирование доступности HTTP/3 на UDP-порту 443 с указанием времени кэширования `ma`).

**GSO (Generic Segmentation Offload) и GRO (Generic Receive Offload)** — сетевые механизмы ядра Linux и сетевой карты (NIC), агрегирующие множество мелких пакетов в крупные блоки (до 64 КБ) для снижения частоты системных вызовов и снижения нагрузки на CPU при передаче и приеме высокоскоростного UDP-трафика QUIC.

**eBPF quic_bpf** — архитектурное решение на базе расширенных фильтров пакетов ядра Linux (`SO_ATTACH_REUSEPORT_EBPF`), обеспечивающее маршрутизацию входящих UDP-пакетов QUIC к правильному процессу воркера веб-сервера по значению Connection ID (CID), предотвращая сброс соединений при `reload` конфигурации.

## Основные концепции

### Техническое сравнение протоколов

| Характеристика | HTTP/1.1 | HTTP/2 | HTTP/3 |
| :--- | :--- | :--- | :--- |
| **Транспортный уровень** | TCP (RFC 9293) | TCP (RFC 9293) | **QUIC (UDP, RFC 9000)** |
| **Уровень шифрования** | Опциональный TLS 1.2/1.3 | Опциональный по RFC, де-факто обязательный TLS 1.2+ в браузерах | **Встроенный TLS 1.3 (RFC 9001)** — незашифрованный режим не предусмотрен |
| **Стек надежности и потерь** | Ядро ОС (TCP Stack) | Ядро ОС (TCP Stack) | **User-space QUIC Stack** (или специализированный модуль сервера) |
| **Устранение HOL-блокировки** | Отсутствует | На уровне HTTP-запросов (сохраняется на уровне TCP) | **Полное устранение** (независимые потоки QUIC) |
| **Идентификация сессии** | 4-tuple (Src IP, Src Port, Dst IP, Dst Port) | 4-tuple (Src IP, Src Port, Dst IP, Dst Port) | **Connection ID (CID)** — 64/128-битные идентификаторы клиента и сервера |
| **Сжатие метаданных** | Отсутствует (текстовые заголовки) | **HPACK** (RFC 7541, статический + динамический словарь) | **QPACK** (RFC 9204, потокобезопасный словарь) |
| **Схема приоритизации** | Отсутствует | Деревья зависимостей и веса потоков | **Extensible Prioritization** (RFC 9218: `u=0..7`, `i`) |
| **Задержка рукопожатия** | 1–2 RTT (TCP + TLS) | 2–3 RTT (TCP SYN + TLS Handshake) | **1 RTT** (совмещенный QUIC+TLS) или **0-RTT** (Early Data) |
| **Миграция соединения** | Нет (разрыв TCP при смене IP/интерфейса) | Нет (разрыв TCP) | **Да** (Connection Migration через Path Validation) |
| **Алгоритмы перегрузки** | Ядерные TCP CUBIC, BBRv1–v3, Reno | Ядерные TCP CUBIC, BBRv1–v3, Reno | **User-space BBRv3, CUBIC, NewReno** (RFC 9002) |
| **Формат фреймирования** | Текстовый поток | Бинарные фреймы (HEADERS, DATA, SETTINGS, RST_STREAM) | Бинарные фреймы QUIC/HTTP3 (HEADERS, DATA, CANCEL_PUSH) |
| **Нормативные RFC** | RFC 9110, RFC 9112 | RFC 9113 | RFC 9114, RFC 9000, RFC 9001, RFC 9002 |

### Архитектура QUIC и User-space стек

В отличие от HTTP/1.1 и HTTP/2, где сборка сегментов TCP, управление окном перегрузки и повторные передачи реализованы внутри подсистемы сетевого стека ядра Linux, в HTTP/3 подавляющее большинство реализаций QUIC функционирует в пространстве пользователя (**User-space**):

```
+-------------------------------------------------------------------+
|                           HTTP/3                                  |
|                 (QPACK, Фреймирование, RFC 9114)                  |
+-------------------------------------------------------------------+
|                        QUIC (RFC 9000)                            |
|       (Потоки, Flow Control, Congestion Control BBRv3/CUBIC)      |
+-------------------------------------------------------------------+
|                        TLS 1.3 (RFC 9001)                         |
|                    (Криптографическая защита)                     |
+===================================================================+  --- Граница User-space / Kernel
|                     UDP Сокеты (sendmsg / recvmsg)                |
+-------------------------------------------------------------------+
|                 Сетевой стек Linux (GSO, GRO, eBPF)               |
+-------------------------------------------------------------------+
|                         Сетевой адаптер (NIC)                     |
+-------------------------------------------------------------------+
```

**Особенности и системные издержки User-space стека:**
1. **Нагрузка на CPU:** Обработка отдельных UDP-дейтаграмм через системные вызовы `sendmsg`/`recvmsg` требует частого переключения контекста между ядром и процессом веб-сервера. Нагрузка на CPU при одинаковом объеме переданных данных в HTTP/3 в 2–3 раза превышает показатели HTTP/2 при использовании стандартных сокетов.
2. **Generic Segmentation Offload (UDP GSO):** Позволяет веб-серверу передавать пачку UDP-датаграмм ядру за один системный вызов `sendmsg()` с флагом `UDP_SEGMENT`. Ядро или сетевая карта делит большой буфер на пакеты размера MTU непосредственно перед отправкой.
3. **Generic Receive Offload (UDP GRO):** Объединяет цепочку входящих UDP-пакетов одного соединения в единый крупный буфер (skb) на уровне драйвера сетевой карты, минимизируя прерывания ядра.
4. **Kernel TLS (kTLS):** Переносит симметричное шифрование/дешифрование (AES-GCM, ChaCha20-Poly1305) в ядро Linux. Это позволяет веб-серверу применять нулевое копирование через системный вызов `sendfile()`, отправляя данные прямо из дискового page cache в сокет.
5. **eBPF-диспетчеризация (`quic_bpf`):** При использовании `SO_REUSEPORT` входящие UDP-пакеты распределяются ядром по хэшу 4-tuple. При миграции клиента на новый IP или при перезагрузке сервера (`nginx -s reload`, появление новых PID воркеров) пакеты начинают попадать в сокеты других воркеров, вызывая массовый сброс сессий. Программа eBPF читает байты Connection ID (DCID) из заголовка QUIC и направляет пакет ровно в тот сокет воркера, который создал сессию.

### Влияние на производительность и задержки

#### 1. Устранение TCP Head-of-Line Blocking в сетях с потерями
В HTTP/2 все параллельные потоки упакованы в один TCP-поток байт. Если на физическом канале теряется хотя бы один IP-пакет:
- Стек TCP на стороне получателя приостанавливает передачу всех последующих полученных байт приложению до тех пор, пока отправитель не перешлет утерянный сегмент (Retransmission).
- Даже если потерянный пакет содержал фрагмент фонового изображения, браузер не может обработать прибывшие следом байты критического CSS или HTML.
- В HTTP/3 каждый поток независим: потеря датаграммы с данными потока №4 не задерживает доставку и разбор потоков №2, №6 и №8. При потерях пакетов 1–3% выигрыш по времени загрузки страницы достигает 30–50%.

#### 2. Миграция соединений (Connection Migration)
При перемещении устройства пользователя между сетями (смена вышки сотовой связи, переход с мобильного интернета LTE на офисный Wi-Fi):
- Соединение TCP разрывается из-за смены IP-адреса и порта (нарушение 4-tuple), требуя повторного TCP SYN-ACK и TLS Handshake (потеря от 150 до 400 мс).
- В QUIC клиент отправляет датаграмму с нового IP с тем же **Destination Connection ID (DCID)**.
- Сервер инициирует процедуру **Path Validation** (отправка криптографического вызова `PATH_CHALLENGE` и получение `PATH_RESPONSE`), чтобы предотвратить атаки спуфинга и амплификации, после чего прозрачно продолжает передачу незавершенных HTTP-запросов.

#### 3. 0-RTT Early Data и безопасность
- В режиме 0-RTT клиент использует параметры предыдущей сессии (Session Ticket) и отправляет первый HTTP-запрос (например, `GET /api/v1/config`) внутри первого пакета `Initial`/`0-RTT`.
- **Риск Replay-атак:** Промежуточный злоумышленник может перехватить датаграмму 0-RTT и отправить ее повторно на сервер. Если запрос изменяет состояние (`POST /transfer`, `PUT /update`), операция выполнится дважды.
- **Инженерное правило:** 0-RTT разрешается строго для идемпотентных методов (`GET`, `HEAD`) с обязательной валидацией срока жизни тикетов и проверкой заголовка `$ssl_early_data` в веб-сервере.

#### 4. Защита от UDP Amplification (quic_retry)
Поскольку протокол UDP уязвим к подмене IP-адреса источника, атакующий может направить запрос с поддельным IP жертвы, вызвав отправку большого ответа от сервера. Директива `quic_retry on;` принуждает сервер отправлять клиенту криптографический маркер (`Retry packet`) без выделения памяти под сессию. Полноценное соединение создается только после подтверждения клиентом владения IP-адресом.

### Приоритизация ресурсов (RFC 9218)

Сложная модель приоритетов HTTP/2 с деревьями зависимостей потоков (Dependency Trees) и весами показала плохую совместимость между различными браузерами и серверами. Спецификация **RFC 9218 (Extensible Prioritization Scheme for HTTP)** стандартизировала универсальный механизм управления приоритетами:

Заголовок запроса `Priority`:
```http
Priority: u=1, i
```

Параметры схемы:
- **`u` (Urgency):** Целое число от 0 до 7, определяющее срочность ресурса:
  - `u=0`: Критические блокирующие ресурсы (главный HTML-документ, критический CSS в `<head>`).
  - `u=1`: Критические скрипты JS, необходимые для первоначального рендеринга.
  - `u=2` – `u=3`: Видимые изображения первого экрана (Hero image), шрифты.
  - `u=4` – `u=5`: Асинхронные скрипты, неблокирующие стили.
  - `u=6` – `u=7`: Фоновые запросы телеметрии, предзагрузка (`prefetch`), аналитика.
- **`i` (Incremental):** Булев флаг (`i` или `i=?1`). Показывает, может ли клиент эффективно обрабатывать ресурс по мере поступления фрагментов (потоковое видео, прогрессивные изображения) или ресурс требует полной загрузки перед обработкой (JS-бандл).

### Обнаружение HTTP/3 и стратегия отката (Fallback)

Поскольку протокол UDP на порт 443 может блокироваться корпоративными брандмауэрами, антивирусами или устаревшим сетевым оборудованием провайдеров, первоначальный доступ к веб-ресурсу всегда проектируется с гарантированным откатом на TCP (HTTP/2 или HTTP/1.1):

1. **Заголовок `Alt-Svc` (RFC 7838):**
   При первом запросе по TCP веб-сервер возвращает заголовок:
   ```http
   Alt-Svc: h3=":443"; ma=86400; persist=1
   ```
   Клиент кэширует эту запись на срок `ma` (max-age в секундах) и все последующие сессии инициирует параллельно по UDP/QUIC.
2. **DNS HTTPS Resource Record (RFC 9460):**
   Позволяет клиенту узнать о поддержке HTTP/3 еще до выполнения первого сетевого запроса к веб-серверу через DNS-запрос типа `HTTPS` (тип 65):
   ```dns
   example.com. 300 IN HTTPS 1 . alpn="h3,h2" port=443
   ```
3. **Happy Eyeballs v2 для транспорта:**
   Клиент пытается установить QUIC-соединение поверх UDP. Если в течение заданного таймаута (обычно 200–300 мс) рукопожатие не завершается или приходит ошибка ICMP «Destination Unreachable / Port Unreachable», клиент без разрыва пользовательского опыта продолжает передачу через проверенное TCP-соединение.

### Влияние на Core Web Vitals

| Метрика | Порог (Good) | Влияние HTTP/2 | Влияние HTTP/3 |
| :--- | :--- | :--- | :--- |
| **LCP (Largest Contentful Paint)** | $\le$ 2.5 с | Мультиплексирование устраняет конкуренцию за сокеты; сжатие HPACK экономит полосу пропускания. | Отсутствие TCP HOL-блокировки и алгоритм BBRv3 ускоряют доставку LCP-ресурса (Hero Image/баннер) на 25–45% при потерях пакетов. |
| **INP (Interaction to Next Paint)** | $\le$ 200 мс | RFC 9218 гарантирует быструю доставку критического JS без задержки из-за фоновых запросов. | Быстрая доставка интерактивных скриптов даже в момент переключения сети смартфона (Connection Migration). |
| **CLS (Cumulative Layout Shift)** | $\le$ 0.1 | 103 Early Hints позволяет браузеру запросить шрифты и стили до получения основного HTML. | Минимизация задержек при повторных переходах за счет 0-RTT предотвращает сдвиги макета из-за FOUT (Flash of Unstyled Text). |

## Практические сценарии

### Сценарий 1: Валидация поддержки HTTP/2 и HTTP/3 в продакшене

**Цель:** Проверить корректность публикации веб-сервера, прохождение UDP-пакетов через сетевой экран и согласование протоколов по ALPN.

**Предварительные требования:**
- Установленные утилиты: `curl` (сборка с поддержкой HTTP/3, проверить через `curl -V | grep -o 'HTTP3'`), `openssl` версии 3.0+, `iproute2` (`ss`).
- Доступность проверяемого хоста по доменному имени.

**Пошаговое выполнение:**

1. Проверить прослушивание портов 443 TCP и UDP на целевом веб-сервере:
   ```bash
   ss -tulpn | grep :443
   # → tcp   LISTEN 0      511   0.0.0.0:443   0.0.0.0:*   users:(("nginx",pid=1234,fd=6))
   # → udp   UNCONN 0      0     0.0.0.0:443   0.0.0.0:*   users:(("nginx",pid=1234,fd=8))
   ```

2. Проверить TLS-рукопожатие и согласование ALPN `h2` по протоколу TCP:
   ```bash
   openssl s_client -connect example.com:443 -servername example.com -alpn h2 -brief
   # → Protocol version: TLSv1.3
   # → Ciphersuite: TLS_AES_256_GCM_SHA384
   # → ALPN protocol: h2
   # → Verification: OK
   ```

3. Проверить наличие и корректность заголовка `Alt-Svc` в ответе HTTP/2:
   ```bash
   curl -sI --http2 https://example.com/ | grep -i alt-svc
   # → alt-svc: h3=":443"; ma=86400
   ```

4. Выполнить непосредственный запрос по протоколу HTTP/3:
   ```bash
   curl --http3 -v -o /dev/null https://example.com/
   # → * Connected to example.com (203.0.113.10) port 443
   # → * using HTTP/3
   # → * [HTTP/3] [0] OPENED stream for https://example.com/
   # → < HTTP/3 200
   # → < alt-svc: h3=":443"; ma=86400
   ```

**Валидация:**
Запрос возвращает код `HTTP/3 200`. Если curl выдает `Failed to connect to ... port 443: Connection refused` или зависает по таймауту — проверьте настройки iptables/nftables и политики безопасности промежуточных шлюзов.

---

### Сценарий 2: Системный тюнинг Linux под высоконагруженный QUIC/UDP

**Цель:** Устранить потери пакетов из-за переполнения очередей сокетов (`UdpRcvbufErrors`) и снизить нагрузку на CPU при обработке сотен тысяч QUIC-сессий.

**Предварительные требования:**
- Ядро Linux версии 5.15+ (рекомендуется 6.1+ / 6.6+ LTS).
- Права суперпользователя (`root`).

**Пошаговое выполнение:**

1. Создать файл конфигурации параметров ядра для сетевого стека:
   ```bash
   cat << 'EOF' | sudo tee /etc/sysctl.d/99-quic-performance.conf
   # Максимальный размер буферов приема и отправки сокетов (16 МБ)
   net.core.rmem_max = 16777216
   net.core.wmem_max = 16777216

   # Буферы по умолчанию (256 КБ)
   net.core.rmem_default = 262144
   net.core.wmem_default = 262144

   # Очередь входящих пакетов сетевой карты
   net.core.netdev_max_backlog = 16384

   # Лимит полуоткрытых TCP-соединений
   net.core.somaxconn = 65535

   # Диапазон локальных портов для исходящих сессий
   net.ipv4.ip_local_port_range = 1024 65535

   # Алгоритм контроля перегрузок TCP (BBRv3 или BBR)
   net.core.default_qdisc = fq
   net.ipv4.tcp_congestion_control = bbr
   EOF
   ```

2. Применить параметры без перезагрузки сервера:
   ```bash
   sudo sysctl --system
   # → * Applying /etc/sysctl.d/99-quic-performance.conf ...
   # → net.core.rmem_max = 16777216
   # → net.core.wmem_max = 16777216
   # → net.core.netdev_max_backlog = 16384
   # → net.core.somaxconn = 65535
   # → net.core.default_qdisc = fq
   # → net.ipv4.tcp_congestion_control = bbr
   ```

3. Увеличить размер аппаратного кольцевого буфера сетевой карты (Ring Buffer) для предотвращения сброса пакетов на физическом уровне (замените `eth0` на имя внешнего интерфейса):
   ```bash
   sudo ethtool -G eth0 rx 4096 tx 4096
   # → Current hardware settings applied
   ```

4. Включить аппаратные offload-механизмы для UDP (GRO):
   ```bash
   sudo ethtool -K eth0 rx-gro-list on 2>/dev/null || sudo ethtool -K eth0 rx on
   # → Actual changes: rx-gro-list: on
   ```

**Валидация:**
Проверить отсутствие ошибок переполнения буфера UDP в системе:
```bash
nstat -az | grep -E "UdpRcvbufErrors|UdpInErrors"
# → UdpInErrors                     0                   0.0
# → UdpRcvbufErrors                 0                   0.0
```

**Очистка и откат:**
Для возврата к исходным параметрам удалите конфигурационный файл и примените дефолтные настройки:
```bash
sudo rm -f /etc/sysctl.d/99-quic-performance.conf
sudo sysctl -w net.core.rmem_max=212992
sudo sysctl -w net.core.wmem_max=212992
sudo sysctl -w net.core.netdev_max_backlog=1000
sudo ethtool -G eth0 rx 1024 tx 1024
```

---

### Сценарий 3: Защита веб-сервера от атак HTTP/2 Rapid Reset и флуда

**Цель:** Настроить лимиты обработки потоков и защиту от атак сброса потоков (CVE-2023-44487 Rapid Reset) и флуда бинарными заголовками (HPACK Bomb).

**Предварительные требования:**
- Веб-сервер Nginx 1.25.1+ или Angie 1.4+.

**Пошаговое выполнение:**

1. Настроить параметры виртуального хоста с безопасными ограничениями HTTP/2:
   ```nginx
   # /etc/nginx/conf.d/vhost_hardened_h2.conf
   limit_req_zone $binary_remote_addr zone=h2_req_limit:20m rate=100r/s;

   server {
       listen 443 ssl;
       listen [::]:443 ssl;
       server_name example.com;

       # Современный синтаксис HTTP/2 (Nginx 1.25.1+, Angie)
       http2 on;

       ssl_certificate /etc/ssl/certs/example.com.crt;
       ssl_certificate_key /etc/ssl/private/example.com.key;
       ssl_protocols TLSv1.2 TLSv1.3;

       # Ограничение числа параллельных потоков на одно TCP-соединение (защита от исчерпания памяти)
       http2_max_concurrent_streams 128;

       # Максимальное количество запросов в одном мультиплексированном соединении до принудительной ротации
       http2_max_requests 10000;

       # Ограничение размера буфера для чтения заголовков (защита от HPACK Bomb)
       http2_recv_buffer_size 512k;
       http2_chunk_size 8k;

       # Защита от Rapid Reset: ограничение частоты запросов
       limit_req zone=h2_req_limit burst=200 nodelay;

       location / {
           root /var/www/html;
           index index.html;
       }
   }
   ```

2. Проверить синтаксис и применить конфигурацию:
   ```bash
   sudo nginx -t
   # → nginx: the configuration file /etc/nginx/nginx.conf syntax is ok
   # → nginx: configuration file /etc/nginx/nginx.conf test is successful
   sudo systemctl reload nginx
   ```

**Валидация:**
Сгенерировать тестовую нагрузку мультиплексированных запросов через `h2load`:
```bash
h2load -n 1000 -c 10 -m 50 https://example.com/
# → finished in 120.35ms, 8309.10 req/s, 2.34MB/s
# → requests: 1000 total, 1000 started, 1000 done, 1000 succeeded, 0 failed, 0 errored
```

---

### Сценарий 4: Настройка eBPF (`quic_bpf`) для бесшовного reload HTTP/3

**Цель:** Обеспечить нулевой сброс клиентских HTTP/3 сессий при перезагрузке веб-сервера (`reload`).

**Предварительные требования:**
- Ядро Linux 5.7+ с поддержкой `BPF` (`CONFIG_BPF=y`, `CONFIG_BPF_SYSCALL=y`).
- Веб-сервер Angie (или Nginx с модулем `ngx_http_v3_module` и eBPF поддержкой).
- Наличие Linux-capabilities `CAP_BPF` и `CAP_NET_ADMIN` у процесса мастера веб-сервера.

**Пошаговое выполнение:**

1. Настроить блок конфигурации веб-сервера с включенным eBPF роутингом:
   ```nginx
   # /etc/angie/http.d/http3_ebpf.conf
   server {
       # Порт TCP для HTTP/1.1 и HTTP/2
       listen 443 ssl;
       listen [::]:443 ssl;
       http2 on;

       # Порт UDP для HTTP/3 с поддержкой reuseport
       listen 443 quic reuseport rcvbuf=4m sndbuf=4m;
       listen [::]:443 quic reuseport rcvbuf=4m sndbuf=4m;

       server_name example.com;

       ssl_certificate /etc/ssl/certs/example.com.crt;
       ssl_certificate_key /etc/ssl/private/example.com.key;
       ssl_protocols TLSv1.3;

       # Включение eBPF программы для маршрутизации UDP по CID
       quic_bpf on;

       # Generic Segmentation Offload для UDP
       quic_gso on;

       # Защита от UDP Amplification
       quic_retry on;

       # Анонсирование HTTP/3 для клиентов
       add_header Alt-Svc 'h3=":443"; ma=86400; persist=1' always;

       location / {
           root /var/www/html;
           index index.html;
       }
   }
   ```

2. Проверить синтаксис и запустить веб-сервер:
   ```bash
   sudo angie -t
   # → angie: the configuration file /etc/angie/angie.conf syntax is ok
   # → angie: configuration file /etc/angie/angie.conf test is successful
   sudo systemctl restart angie
   ```

3. Проверить загрузку программы eBPF в ядро:
   ```bash
   sudo bpftool prog show | grep -i -E "reuseport|quic"
   # → 142: sk_reuseport  name quic_bpf_select  tag a1b2c3d4e5f6  gpl
   ```

4. Выполнить проверку сохранения сессий:
   - Запустить непрерывную передачу крупного файла по HTTP/3 клиентом:
     ```bash
     curl --http3 -o /dev/null https://example.com/large_payload.bin &
     ```
   - В момент активной передачи выполнить мягкую перезагрузку сервиса:
     ```bash
     sudo systemctl reload angie
     ```

**Валидация:**
В файле `/var/log/angie/error.log` отсутствуют записи `quic connection closed during reload`, и передача файла завершается без ошибок со статусом завершения 0.

---

### Сценарий 5: Эмуляция потерь пакетов и оценка устойчивости протоколов

**Цель:** Практически подтвердить устойчивость протокола HTTP/3 в условиях нестабильного канала связи по сравнению с HTTP/2.

**Предварительные требования:**
- Утилита `tc` (`iproute2`) для эмуляции сетевых аномалий (NetEm).
- Утилита `curl` с поддержкой `--http2` и `--http3`.

**Пошаговое выполнение:**

1. Замерить базовое время передачи тестового объекта (1 МБ) по HTTP/2 и HTTP/3 в идеальной сети:
   ```bash
   curl -s -o /dev/null -w "HTTP/2 Total: %{time_total}s | TTFB: %{time_starttransfer}s\n" --http2 https://example.com/1mb.dat
   # → HTTP/2 Total: 0.145s | TTFB: 0.042s

   curl -s -o /dev/null -w "HTTP/3 Total: %{time_total}s | TTFB: %{time_starttransfer}s\n" --http3 https://example.com/1mb.dat
   # → HTTP/3 Total: 0.141s | TTFB: 0.038s
   ```

2. Включить искусственную потерю 5% пакетов на сетевом интерфейсе сервера (`eth0`):
   ```bash
   sudo tc qdisc add dev eth0 root netem loss 5%
   ```

3. Повторить замеры на канале с потерями:
   ```bash
   curl -s -o /dev/null -w "HTTP/2 Total: %{time_total}s | TTFB: %{time_starttransfer}s\n" --http2 https://example.com/1mb.dat
   # → HTTP/2 Total: 1.284s | TTFB: 0.285s

   curl -s -o /dev/null -w "HTTP/3 Total: %{time_total}s | TTFB: %{time_starttransfer}s\n" --http3 https://example.com/1mb.dat
   # → HTTP/3 Total: 0.395s | TTFB: 0.075s
   ```

**Валидация:**
В условиях 5% потерь пакетов протокол HTTP/3 сохраняет низкий TTFB и опережает HTTP/2 более чем в 3 раза за счет отсутствия TCP Head-of-Line блокировки.

**Очистка (Revert):**
Обязательно удалить правило NetEm после проведения тестов:
```bash
sudo tc qdisc del dev eth0 root
tc qdisc show dev eth0
# → qdisc fq_codel 0: root refcnt 2 limit 10240p flows 1024 ...
```

---

### Сценарий 6: Бенчмаркинг и нагрузочное тестирование протоколов

**Цель:** Измерить пропускную способность (RPS) и квантили задержек при мультиплексировании запросов.

**Предварительные требования:**
- Утилита `h2load` из состава пакета `nghttp2-client` (сборка с поддержкой QUIC/HTTP3).

**Пошаговое выполнение:**

1. Нагрузочный тест HTTP/2 (10 000 запросов, 50 одновременных клиентов, по 20 мультиплексированных стримов):
   ```bash
   h2load -n 10000 -c 50 -m 20 --h2 https://example.com/
   # → finished in 1.45s, 6896.55 req/s, 14.82MB/s
   # → requests: 10000 total, 10000 started, 10000 done, 10000 succeeded, 0 failed, 0 errored
   # → status codes: 10000 2xx, 0 3xx, 0 4xx, 0 5xx
   # → time for request: 
   # →   min: 1.20ms, max: 48.50ms, mean: 6.80ms, sd: 3.10ms
   # → time to first byte:
   # →   min: 3.40ms, max: 28.10ms, mean: 7.20ms, sd: 2.90ms
   ```

2. Нагрузочный тест HTTP/3 в идентичных условиях нагрузки:
   ```bash
   h2load -n 10000 -c 50 -m 20 --h3 https://example.com/
   # → finished in 1.18s, 8474.58 req/s, 18.21MB/s
   # → requests: 10000 total, 10000 started, 10000 done, 10000 succeeded, 0 failed, 0 errored
   # → status codes: 10000 2xx, 0 3xx, 0 4xx, 0 5xx
   # → time for request: 
   # →   min: 0.95ms, max: 32.10ms, mean: 5.40ms, sd: 2.40ms
   # → time to first byte:
   # →   min: 2.10ms, max: 18.30ms, mean: 5.10ms, sd: 1.80ms
   ```

**Валидация:**
Анализ процентилей задержек: HTTP/3 демонстрирует более низкую стандартную девиацию (sd) и меньший средний TTFB при высокой плотности параллельных потоков.

## Операции и команды

### Проверка модулей и сборки веб-серверов

| Команда | Назначение | Ожидаемый результат |
| :--- | :--- | :--- |
| `nginx -V 2>&1 \| grep -o 'http_v2_module'` | Проверка сборки модуля HTTP/2 в Nginx | `http_v2_module` |
| `nginx -V 2>&1 \| grep -o 'http_v3_module'` | Проверка сборки модуля HTTP/3 в Nginx | `http_v3_module` |
| `angie -V 2>&1 \| grep -o 'quic'` | Проверка встроенной поддержки QUIC в Angie | `quic` |
| `openssl version` | Проверка версии криптографической библиотеки | `OpenSSL 3.0.13 30 Jan 2024` (или 3.2+) |
| `curl -V \| grep -E "HTTP2\|HTTP3"` | Проверка протоколов в утилите curl | `Features: ... HTTP2 HTTP3 ...` |

### Сетевая диагностика сокетов

| Команда | Назначение | Ожидаемый результат |
| :--- | :--- | :--- |
| `ss -tnp \| grep :443` | Активные входящие TCP-соединения (HTTP/1.1, HTTP/2) | `LISTEN 0 511 0.0.0.0:443 ... users:(("nginx",pid=1234,fd=6))` |
| `ss -ulpn \| grep :443` | Слушающий UDP-сокет HTTP/3 | `UNCONN 0 0 0.0.0.0:443 ... users:(("nginx",pid=1234,fd=8))` |
| `ss -u -a \| grep :443` | Все активные QUIC-сессии клиентов | `udp UNCONN 0 0 192.0.2.1:443 198.51.100.5:54321` |
| `nstat -az \| grep Udp` | Системные счетчики UDP-стека ядра | `UdpInDatagrams`, `UdpNoPorts`, `UdpRcvbufErrors` |

### Диагностика протоколов и таймингов

```bash
# Детальный замер фаз установки соединения (DNS, TCP, TLS, TTFB, Total)
curl -o /dev/null -s -w "\
DNS Lookup:        %{time_namelookup}s\n\
TCP Connect:       %{time_connect}s\n\
TLS Handshake:     %{time_appconnect}s\n\
Pre-transfer:      %{time_pretransfer}s\n\
TTFB:              %{time_starttransfer}s\n\
Total Time:        %{time_total}s\n\
Protocol Negotiated: %{http_version}\n" https://example.com/
# → DNS Lookup:        0.004s
# → TCP Connect:       0.021s
# → TLS Handshake:     0.045s
# → Pre-transfer:      0.046s
# → TTFB:              0.089s
# → Total Time:        0.112s
# → Protocol Negotiated: 2
```

### Проверка MTU и запрета фрагментации (PLPMTUD)

```bash
# Проверка прохождения пакетов QUIC без IP-фрагментации (требуется размер пакета >= 1280 байт)
# Размер полезной нагрузки ICMP = 1472 байт (1472 + 8 байт ICMP + 20 байт IP = 1500 MTU)
ping -M do -s 1400 -c 3 example.com
# → 1408 bytes from example.com: icmp_seq=1 ttl=56 time=24.1 ms

# Если ping выдает ошибку: "Frag needed and DF set (mtu = 1420)", проверьте MTU на интерфейсе:
ip link show eth0 | grep -o 'mtu [0-9]*'
# → mtu 1500
```

## Мониторинг и алертинг

### Ключевые метрики для SRE

| Метрика / Индикатор | Тип | Целевой порог (SLO) | Инженерный смысл |
| :--- | :--- | :--- | :--- |
| **HTTP/3 Adoption Ratio** | Gauge / Ratio | > 50–70% (для браузерного трафика) | Доля трафика по UDP. Падение указывает на блокировку порта 443/UDP у провайдеров. |
| **TTFB (Time to First Byte)** | Histogram | p75 $\le$ 200 мс, p99 $\le$ 500 мс | Скорость генерации первого байта ответа сервером. |
| **UDP InErrors / Drop Rate** | Counter | 0 ошибок в минуту | Сброс входящих датаграмм ядра из-за нехватки `rmem_max` или очереди `netdev_max_backlog`. |
| **HTTP/2 Stream Reset Rate** | Rate | < 1% от общего числа запросов | Всплеск фреймов `RST_STREAM` сигнализирует об атаке Rapid Reset или ошибках клиентов. |
| **0-RTT Replay Rejection** | Counter | Мониторинг динамики | Число запросов Early Data, отклоненных сервером из-за устаревших тикетов. |

### Конфигурация структурированного логирования

Для точного расчета метрик на стороне Elasticsearch / Loki / Vector настраивается формат access-лога в формате JSON:

```nginx
# /etc/nginx/conf.d/logging_perf.conf
log_format json_perf escape=json '{'
    '"timestamp":"$time_iso8601",'
    '"remote_addr":"$remote_addr",'
    '"protocol":"$server_protocol",'
    '"alpn":"$ssl_alpn",'
    '"early_data":"$ssl_early_data",'
    '"status":$status,'
    '"bytes_sent":$bytes_sent,'
    '"request_time":$request_time,'
    '"upstream_response_time":"$upstream_response_time",'
    '"pipe":"$pipe",'
    '"connection_requests":$connection_requests'
'}';

access_log /var/log/nginx/access_perf.json json_perf buffer=64k flush=5s;
```

### Метрики Prometheus и правила алертов

Сбор метрик сетевого стека узла осуществляется через `node_exporter`, метрик веб-сервера — через модуль Prometheus (например, Angie Prometheus metrics или `nginx-prometheus-exporter`).

```yaml
# /etc/prometheus/rules/web_performance_alerts.yml
groups:
  - name: WebPerformanceAlerts
    rules:
      # Расчет доли HTTP/3 трафика
      - record: job:http3_adoption_ratio
        expr: >
          sum(rate(nginx_http_requests_total{server_protocol="HTTP/3.0"}[5m]))
          /
          sum(rate(nginx_http_requests_total[5m]))

      # Алерт: Резкое падение adoption HTTP/3 (блокировка UDP на периметре)
      - alert: HTTP3AdoptionDrop
        expr: job:http3_adoption_ratio < 0.20 and sum(rate(nginx_http_requests_total[5m])) > 50
        for: 15m
        labels:
          severity: warning
        annotations:
          summary: "Критическое падение трафика HTTP/3"
          description: "Доля HTTP/3 трафика упала ниже 20% (текущее значение: {{ $value | humanizePercentage }}). Возможна блокировка UDP 443 на внешнем firewall."

      # Алерт: Сброс UDP пакетов из-за переполнения очередей ядра
      - alert: LinuxUDPPacketReceiveDrops
        expr: rate(node_netstat_Udp_RcvbufErrors[2m]) > 5
        for: 2m
        labels:
          severity: critical
        annotations:
          summary: "Переполнение буфера UDP сокетов на хосте {{ $labels.instance }}"
          description: "Ядро сбрасывает {{ $value }} UDP-пакетов в секунду. Требуется увеличить net.core.rmem_max и rcvbuf в конфигурации веб-сервера."

      # Алерт: Аномальный всплеск HTTP/2 сбросов потоков (Rapid Reset)
      - alert: HTTP2RapidResetDetected
        expr: rate(nginx_http2_reset_streams_total[1m]) / rate(nginx_http_requests_total{server_protocol="HTTP/2.0"}[1m]) > 0.15
        for: 1m
        labels:
          severity: critical
        annotations:
          summary: "Обнаружена потенциальная атака HTTP/2 Rapid Reset"
          description: "Более 15% потоков HTTP/2 принудительно сбрасываются клиентами через RST_STREAM."
```

## Диагностика ошибок

| Проблема | Диагностические признаки | Первопричина | Инженерное решение |
| :--- | :--- | :--- | :--- |
| **HTTP/3 недоступен, curl зависает** | `curl --http3` завершается по таймауту; `ss -ulpn` показывает открытый порт. | Брандмауэр хоста (iptables/nftables) или внешний шлюз блокирует UDP 443. | Открыть входящий порт: `sudo iptables -A INPUT -p udp --dport 443 -j ACCEPT` или `sudo ufw allow 443/udp`. |
| **Потери UDP-пакетов при высокой нагрузке** | Растет счетчик `UdpRcvbufErrors` в `nstat -az`; падение пропускной способности. | Переполнение системного буфера сокета из-за низкого значения `net.core.rmem_max`. | Выставить `net.core.rmem_max = 16777216` в `/etc/sysctl.conf`; добавить параметр `rcvbuf=4m` в директиву `listen ... quic`. |
| **Сброс сессий HTTP/3 при `systemctl reload`** | Всплеск ошибок 502/соединение разорвано у клиентов при ротации воркеров. | Отсутствует eBPF-диспетчеризация пакетов по Connection ID. | Включить директиву `quic_bpf on;` (требует Linux Kernel 5.7+ и прав `CAP_BPF` / `CAP_NET_ADMIN`). |
| **Предупреждение: `http2` parameter is deprecated** | В логе ошибок Nginx: `[warn] the "http2" parameter of the "listen" directive is deprecated`. | Использование устаревшего синтаксиса `listen 443 ssl http2;` в Nginx 1.25.1+. | Заменить на отдельную директиву `http2 on;` внутри блока `server {}` или `http {}`. |
| **Разрыв сессий при передаче крупных пакетов (MTU Blackholing)** | Рукопожатие QUIC проходит, но передача данных зависает на этапе отдачи ответа. | Размер UDP-датаграммы превышает Path MTU, а пакеты ICMP `Frag Needed` фильтруются сетью. | Настроить MTU на сетевом интерфейсе (1500 или 1420 для туннелей GRE/WireGuard); убедиться, что ICMP Type 3 Code 4 не заблокирован. |
| **HTTP/2 Rapid Reset (высокая загрузка CPU)** | Процессы воркеров утилизируют 100% CPU при умеренном объеме переданного трафика. | Атака CVE-2023-44487: клиент непрерывно шлет `HEADERS` с последующим `RST_STREAM`. | Обновить сервер до версии с патчем; настроить `http2_max_concurrent_streams 128;` и модуль `limit_req`. |
| **Отказ 0-RTT рукопожатия** | Заголовок `$ssl_early_data` содержит `rejected` или пуст. | Срок действия Session Ticket истек, изменился ключ шифрования тикетов (`ssl_session_ticket_key`). | Настроить синхронизацию ключей тикетов между нодами кластера; проверить директиву `ssl_session_timeout`. |
| **Атака HPACK Bomb** | Быстрое исчерпание оперативной памяти воркерами при получении HTTP/2 заголовков. | Злоумышленник заполняет динамическую таблицу HPACK циклическими сжатыми ссылками. | Задать жесткие лимиты: `http2_recv_buffer_size 256k;`, `large_client_header_buffers 4 16k;`. |

## Рекомендации

### Базовые правила

1. **Включайте HTTP/2 на всех защищенных веб-серверах:** Современный синтаксис для Nginx 1.25.1+ и Angie — директива `http2 on;` в блоке `server` совместно с `listen 443 ssl;`.
2. **Анонсируйте HTTP/3 через `Alt-Svc` с валидным сроком:** Используйте `add_header Alt-Svc 'h3=":443"; ma=86400; persist=1' always;`. Не завышайте `ma` более чем на 7 дней во избежание проблем при аварийном выводе UDP-стека из эксплуатации.
3. **Откажитесь от Server Push в пользу 103 Early Hints:** Механизм HTTP/2 Server Push официально признан неэффективным и удален из спецификации HTTP/3. Для опережающей загрузки CSS/JS используйте статус `103 Early Hints` (RFC 8297).
4. **Устраняйте Domain Sharding:** Разделение статических ресурсов по субдоменам (`static1.`, `static2.`) — устаревший антипаттерн HTTP/1.1. В HTTP/2 и HTTP/3 все ресурсы отдаются с единого домена, что позволяет использовать преимущества единого окна перегрузки и сжатия HPACK/QPACK.
5. **Ограничивайте 0-RTT только безопасными методами:** При включении `ssl_early_data on;` проксируйте к бэкенду только запросы `GET` и `HEAD`, проверяя переменную `$ssl_early_data`.

### Инженерные рекомендации для DevOps / SRE / SysAdmin

*   **Контроль файрволов для UDP 443:** Убедитесь, что все промежуточные L4-балансировщики (HAProxy, IPVS, Keepalived), аппаратные экраны и облачные группы безопасности явно пропускают протокол `UDP` на порт 443.
*   **Использование eBPF для отказоустойчивости QUIC:** На production-серверах под управлением Linux Kernel 5.7+ всегда включайте `quic_bpf on;`. Это предотвращает обрыв сотен тысяч соединений пользователей при плановом `systemctl reload`.
*   **Активация аппаратного UDP GSO:** Директива `quic_gso on;` снижает потребление процессорного времени при отдаче трафика QUIC на 15–25%.
*   **Тюнинг сетевых буферов ядра:** Обязательно увеличивайте параметры `net.core.rmem_max` и `net.core.wmem_max` до 16 МБ (`16777216`), а в веб-сервере задавайте буферы сокета `rcvbuf=4m sndbuf=4m`.
*   **Внедрение контроля перегрузок BBRv3 / BBR:** Включайте ядерную очередь `fq` (`net.core.default_qdisc = fq`) и алгоритм перегрузок BBR (`net.ipv4.tcp_congestion_control = bbr`).
*   **Алертинг на аномалии L4/L7:** Настройте мониторинг ошибок `node_netstat_Udp_RcvbufErrors` и отслеживайте процентное соотношение протоколов `$server_protocol` в Prometheus. Резкое падение HTTP/3 сигнализирует о сетевой деградации или проблемах с сертификатами.

## Дополнительная информация

### RFC и спецификации

| RFC | Наименование спецификации | Роль в стеке протоколов |
| :--- | :--- | :--- |
| **RFC 9110** | HTTP Semantics | Базовая семантика методов, статусов, заголовков (общая для всех версий) |
| **RFC 9112** | HTTP/1.1 Specification | Текстовый формат HTTP/1.1 |
| **RFC 9113** | HTTP/2 Specification | Бинарное фреймирование и мультиплексирование TCP |
| **RFC 9114** | HTTP/3 Specification | Прикладной уровень HTTP поверх QUIC |
| **RFC 9000** | QUIC: A UDP-Based Multiplexed and Secure Transport | Спецификация транспортного протокола QUIC |
| **RFC 9001** | Using TLS to Secure QUIC | Интеграция TLS 1.3 в протокол QUIC |
| **RFC 9002** | QUIC Loss Detection and Congestion Control | Механизмы детекции потерь и контроль перегрузки |
| **RFC 9204** | QPACK: Field Compression for HTTP/3 | Сжатие метаданных в независимых потоках |
| **RFC 7541** | HPACK: Header Compression for HTTP/2 | Сжатие заголовков HTTP/2 |
| **RFC 9218** | Extensible Prioritization Scheme for HTTP | Стандарт приоритизации потоков (`Priority: u=.., i`) |
| **RFC 7838** | HTTP Alternative Services (Alt-Svc) | Механизм переключения на альтернативные транспорты |
| **RFC 8297** | An HTTP Status Code for Indicating Hints (103) | Стандарт Early Hints для ускоренной загрузки |
| **RFC 8899** | Packetization Layer Path MTU Discovery (PLPMTUD) | Алгоритм обнаружения MTU без фрагментации пакетов |
| **RFC 9460** | Service Binding and Parameter Specification (HTTPS DNS) | Анонсирование HTTP/3 через DNS HTTPS Resource Records |

### Граничные случаи и эксплуатационные ограничения

1. **Проблема User-space обработки UDP и нагрузка на CPU:** Процесс обработки протокола QUIC в пространстве пользователя потребляет существенно больше CPU, чем обработка TCP, так как TCP оптимизирован аппаратными разгрузками ядра (TSO/LSO). При планировании мощностей под HTTP/3 закладывайте запас по процессорным ядрам на 20–30%.
2. **Корпоративные сети и глубокая фильтрация пакетов (DPI):** Корпоративные прокси и брандмауэры нередко полностью блокируют исходящий UDP-трафик, пропуская только DNS (порт 53). Веб-архитектура обязана поддерживать параллельный стек TCP/HTTP/2, чтобы клиенты из таких сетей прозрачно обслуживались без задержек и сбоев.
3. **PMTUD Blackholing:** Если на маршруте между клиентом и сервером блокируются пакеты ICMP «Destination Unreachable / Fragmentation Needed», а MTU канала меньше 1500 (например, при туннелировании PPPoE/VPN/VXLAN), крупные QUIC-датаграммы отбрасываются. Клиент успешно завершает рукопожатие, но не может получить тело ответа. Проблема диагностируется снижением MTU и настройкой PLPMTUD (RFC 8899).
4. **NAT Rebinding и таймауты трансляции:** Маршрутизаторы NAT обычно удаляют состояние трансляции UDP-портов через 30–60 секунд бездействия (в отличие от TCP, где таймаут составляет часы). Для предотвращения сброса соединения при длительном простое сервер и клиент должны отправлять управляющие фреймы `PING` с интервалом не реже 20–25 секунд.
5. **Мультиплексирование gRPC:** Сервисы gRPC на базе HTTP/2 критичны к настройке управления потоком (Flow Control). При передаче больших объемов данных по одному соединению переполнение окна `SETTINGS_INITIAL_WINDOW_SIZE` блокирует все остальные RPC-вызовы. Рекомендуется настраивать пул из нескольких HTTP/2 соединений для высоконагруженных межсервисных взаимодействий.

### Связанные разделы

- [Обзор производительности веб-приложений](./overview.md) — фундаментальные основы, критический путь рендеринга (CRP).
- [Ключевые метрики Web Vitals](./web_vitals.md) — детальный разбор метрик LCP, INP, CLS, TTFB.
- [Тестирование производительности](./testing_principles.md) — методология RUM, синтетические тесты.
- [Лучшие практики оптимизации](./best_practices.md) — комплексное руководство по ускорению веб-ресурсов.
- [Сжатие контента на веб-сервере](./server_compression.md) — Brotli, Gzip, Zstandard.
- [Оптимизация TLS для производительности](./tls_optimization.md) — session tickets, kTLS, 0-RTT Early Data.
- [Инструменты анализа (DevTools, PageSpeed)](./chrome_devtools.md) — аудит профилей загрузки и трассировка.
- [Конфигурация HTTP/2 и HTTP/3 в Nginx/Angie](../../Nginx/Performance/nginx_http_versions.md) — серверные директивы и компиляция.
- [Оптимизация производительности HTTP](../../../Networking/Protocols/HTTP/http_protocols_optimization.md) — транспортные механизмы, BBRv3, L4S.
- [Настройка TLS в Angie](../../Angie/angie_tls_setup.md) — HTTP/3, kTLS, ACME, QUIC eBPF.
- [Zero-Downtime Deployment](./zero_downtime_deployment.md) — бесшовная перезагрузка и сохранение сессий.
- [Structured Logging для Performance](./structured_logging_for_performance.md) — анализ сетевых задержек по логам.
