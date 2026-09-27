# Анализ HTTPS-трафика в Wireshark

> **См. также:** [Методы расшифровки TLS](./tls_decryption_methods.md) — настройка `SSLKEYLOGFILE` и DSB. [Анализ HTTP/2 и gRPC](./http2_grpc_analysis.md) — бинарные фреймы HTTP/2 поверх TLS. [Протокол TLS](../../Protocols/tls.md) — теория шифрования и хендшейка.

## Определения

**HTTPS (HTTP over TLS)** — защищённый протокол прикладного уровня, инкапсулирующий HTTP-сообщения внутрь TLS-сессии. Обеспечивает конфиденциальность, целостность и аутентификацию через шифрование на транспортном уровне.

**TLS Record Layer (Уровень записей TLS)** — базовый фрейм протокола TLS, инкапсулирующий данные приложений. Каждая TLS-запись содержит: `Content Type` (Handshake/Application Data/Alert), `Version` (например, TLS 1.2) и `Length` полезной нагрузки.

**SNI (Server Name Indication)** — расширение TLS (RFC 6066), передающее имя целевого хоста в открытом виде внутри ClientHello. Позволяет обслуживать несколько доменов на одном IP-адресе. Фильтр Wireshark: `tls.handshake.extensions_server_name`.

**Application Data Protocol** — поле в расширениях TLS ALPN (Application-Layer Protocol Negotiation), указывающее протокол прикладного уровня (например, `http/1.1`, `h2`, `h3`).

## Основные концепции

### Стек протоколов HTTPS в Wireshark

HTTPS-трафик имеет строгую иерархию инкапсуляции. В Wireshark это отображается как дерево протоколов:

```
Frame (Ethernet / Wi-Fi)
└── IP (src / dst)
    └── TCP (srcport / dstport)
        └── TLS Record Layer
            └── Application Data (зашифрованный HTTP)
```

**Ключевые признаки HTTPS в Wireshark:**
- **Порт назначения:** 443/TCP (стандартный порт HTTPS)
- **TLS Content Type:** `Handshake` (установка соединения) или `Application Data` (передача данных)
- **ALPN:** Поле `Application Data Protocol` в расширениях TLS указывает версию HTTP (`http/1.1`, `h2`)

### Структура TLS Record Layer

На уровне записей TLS Wireshark отображает:
- **Content Type:** `Application Data` (0x17) — данные приложений
- **Version:** версия TLS (например, TLS 1.2). Важно: версия на этом уровне отражает формат записи, а не negotiated-версию; для TLS 1.3 часто показывается TLS 1.2
- **Length:** длина полезной нагрузки в байтах
- **Encrypted Data:** зашифрованные данные, которые Wireshark показывает в hex/ASCII до применения ключей расшифровки

### SNI и фильтрация HTTPS-соединений

Для поиска конкретного HTTPS-соединения по имени сервера используйте фильтр по расширению SNI:

```bash
# Фильтр по SNI (имя сервера в ClientHello)
tls.handshake.extensions_server_name == "networkskurs.ru"
```

Wireshark отобразит все пакеты ClientHello, содержащие указанное имя сервера. Это быстрее и точнее, чем фильтрация по IP-адресу, особенно при shared hosting.

### Порт 443 и инкапсуляция

HTTPS использует порт 443/TCP. В деталях пакета:
- `tcp.dstport == 443` — соединение к HTTPS-серверу
- `tcp.srcport` — ephemeral-порт, назначенный ОС браузеру

## Практические сценарии

### Сценарий 1: Поиск и фильтрация HTTPS-соединения

**Задача:** Найти в дампе соединение с конкретным HTTPS-сервером.

**Шаги:**
1. Запустите Wireshark и откройте дамп или начните захват.
2. Примените фильтр по SNI:
   ```bash
   tls.handshake.extensions_server_name == "example.com"
   ```
3. Найдите пакет `Client Hello` с нужным именем сервера.
4. Для отслеживания всего потока: правый клик на пакете → **Follow → TLS Stream**.

**Ожидаемый результат:**
- В списке пакетов появятся TLS Handshake пакеты (ClientHello, ServerHello, Certificate, Finished)
- После handshake пакеты с типом `Application Data`

### Сценарий 2: Расшифровка HTTPS и просмотр HTTP-запросов

**Задача:** Увидеть HTTP-запросы и ответы внутри зашифрованного TLS-трафика.

**Предварительные требования:**
- Настроен `SSLKEYLOGFILE` в браузере (Chrome/Firefox)
- В Wireshark указан путь к файлу ключей: `Edit → Preferences → Protocols → TLS → (Pre)-Master-Secret log filename`

**Шаги:**
1. Запустите браузер с экспортом ключей:
   ```bash
   export SSLKEYLOGFILE=~/tls-keys.log
   google-chrome --user-data-dir=/tmp/debug
   ```
2. Откройте HTTPS-сайт в браузере.
3. В Wireshark найдите TLS-соединение и примените фильтр:
   ```bash
   tls.handshake.extensions_server_name == "example.com"
   ```
4. Дождитесь расшифровки. В нижней панели `Packet Details` появится вкладка **Decrypted TLS**.
5. Внутри `Decrypted TLS` разверните `Hypertext Transfer Protocol` для просмотра HTTP-запроса/ответа.

**Ожидаемый результат:**
- Вместо `Application Data` видны HTTP-заголовки и тело
- Для HTTP/1.1 запрос выглядит как обычный текстовый HTTP:
  ```http
  GET / HTTP/1.1
  Host: example.com
  User-Agent: Mozilla/5.0 ...
  Accept: text/html,application/xhtml+xml ...
  ```

### Сценарий 3: Анализ структуры HTTP-пакета внутри TLS

**Задача:** Понять, как HTTP-сообщение вложено в TLS Record Layer.

**Шаги:**
1. Найдите зашифрованный пакет `Application Data` HTTPS-соединения.
2. Разверните `Transport Layer Security` в деталях пакета:
   - `Record Layer`: версия TLS, тип `Application Data`, длина
   - `Encrypted Application Data`: зашифрованный payload
3. После расшифровки внутри `Decrypted TLS` появится:
   - `Hypertext Transfer Protocol`
     - `GET / HTTP/1.1`
     - `Host: example.com`
     - `User-Agent: ...`
4. Продолжайте разворачивать стек:
   - `Secure Sockets Layer` → `Transport Layer Security` → `Hypertext Transfer Protocol`

**Ожидаемый результат:**
- Понимание того, что HTTP-запрос не передаётся "напрямую" в TCP, а инкапсулируется в TLS Record Layer
- Возможность увидеть все HTTP-заголовки при наличии ключей расшифровки

### Сценарий 4: Отличие HTTPS от HTTP в Wireshark

**Задача:** Сравнить HTTP и HTTPS на уровне захвата.

**Шаги:**
1. Захватите HTTP-трафик (порт 80):
   ```bash
   tcp.port == 80
   ```
2. Захватите HTTPS-трафик (порт 443):
   ```bash
   tcp.port == 443
   ```
3. Сравните структуру пакетов:
   - **HTTP:** Внутри TCP сразу виден `Hypertext Transfer Protocol`
   - **HTTPS:** Внутри TCP находится `TLS Record Layer`, а HTTP виден только после расшифровки

**Ожидаемый результат:**
- Понимание разницы: HTTP передаётся открытым текстом, HTTPS — зашифрованными TLS-записями
- Для HTTPS без ключей видна только метаинформация TLS (версия, длина, ALPN)

### Сценарий 5: Пошаговый разбор TLS 1.3 handshake в Wireshark

**Задача:** Визуально разобрать полный цикл установки TLS 1.3-соединения на примере реального захвата и научиться идентифицировать каждое сообщение рукопожатия в деталях пакета.

**Особенность:** В отличие от расшифровки, этот сценарий не требует `SSLKEYLOGFILE`. TLS 1.3 handshake почти полностью зашифрован после `ServerHello`, но начальные сообщения (`ClientHello`, `ServerHello`, `Certificate`, `Finished`) остаются открытыми для анализа структуры.

**Шаги:**

1. **Захват и фильтрация:**
   - Запустите захват в Wireshark и откройте HTTPS-сайт (например, `https://networkskurs.ru`).
   - Примените фильтр по SNI:
     ```bash
     tls.handshake.extensions_server_name == "networkskurs.ru"
     ```
   - Если домен размещён на shared hosting (GitHub Pages, Cloudflare) и имеет несколько A/AAAA-записей, переберите все IP-адреса или используйте фильтр по SNI — он точнее, чем `ip.addr`.

2. **Отслеживание потока:**
   - Найдите первый пакет `Client Hello` (тип Handshake = 1).
   - Правый клик → **Follow → TLS Stream**. Закройте само окно TLS Stream, оставив только отфильтрованные пакеты — так удобнее работать с отдельными сообщениями.

3. **Анализ ClientHello:**

   Разверните `Transport Layer Security` в деталях пакета:

   - **Record Layer (уровень записей TLS):**
     - `Content Type: Handshake (0x16)` — тип содержимого: сообщение рукопожатия.
     - `Version: TLS 1.0 (0x0301)` — **устаревшее поле** (legacy version). В нём всегда указывается 0x0301 (TLS 1.0) независимо от реальной версии; реальная версия согласовывается через расширение `Supported Versions`.
     - `Length` — длина полезной нагрузки.

   - **Handshake Protocol: Client Hello (0x01):**
     - `Client Version: TLS 1.2 (0x0303)` — тоже устаревшее поле, его игнорируют в пользу расширения `Supported Versions`.
     - **Supported Versions Extension:** клиент объявляет поддержку `TLS 1.3` и `TLS 1.2`. Сервер выберет максимальную общую версию.
     - **Cipher Suites:** список наборов шифров, которые поддерживает клиент. В TLS 1.3 это обязательные AEAD-шифры (например, `TLS_AES_128_GCM_SHA256`, `TLS_AES_256_GCM_SHA384`, `TLS_CHACHA20_POLY1305_SHA256`) и, для совместимости, шифры TLS 1.2.
     - **Server Name Indication (SNI):** `extensions_server_name = networkskurs.ru` — имя целевого хоста. Необходимо при shared hosting, когда несколько доменов обслуживаются с одного IP.
     - **Key Share:** параметры для обмена ключами. В TLS 1.3 клиент отправляет их сразу в `ClientHello` (1-RTT handshake). В примере:
       - `x25519` — стандартная эллиптическая кривая (ECDHE).
       - `x25519_kyber768` — **гибридный** алгоритм: X25519 + ML-KEM-768 (постквантовый). Это соответствует современным требованиям 2025–2026 годов.

4. **Анализ ServerHello:**

   Разверните детали пакета:

   - **Record Layer:**
     - `Content Type: Handshake`
     - `Version: TLS 1.2 (legacy)` — снова устаревшее поле.
     - `Supported Versions Extension: TLS 1.3` — сервер выбрал современную версию.

   - **Handshake Protocol: Server Hello:**
     - `Cipher Suite: TLS_AES_128_GCM_SHA256` — сервер выбрал конкретный шифр из предложенных клиентом.
     - **Key Share:** ответ сервера на предложение клиента. В примере сервер выбрал гибридный вариант `x25519_kyber768` и отправил свои параметры. После этого обе стороны могут вычислить общий секрет для симметричного шифрования.

5. **Change Cipher Spec:**

   После `ServerHello` сервер отправляет `Change Cipher Spec` — это сигнал, что все последующие сообщения будут зашифрованы. К этому моменту обе стороны уже вычислили сессионный ключ:
   - Клиент получил `key_share` от сервера → вычислил общий секрет.
   - Сервер получил `key_share` от клиента ранее → тоже вычислил секрет.

6. **Encrypted Extensions + Certificate:**

   В TLS 1.3 сообщения после `ChangeCipherSpec` инкапсулируются в зашифрованные записи. В Wireshark без ключей они отображаются как `Application Data` или `Encrypted Extensions`. Если у вас есть ключи расшифровки, разверните `Decrypted TLS`:

   - **Certificate:** цепочка сертификатов сервера.
     - **Leaf Certificate:** сертификат для `networkskurs.ru`, выдан Let's Encrypt.
     - **Intermediate Certificate:** сертификат самого удостоверяющего центра (Let's Encrypt Authority X4), подписанный корневым CA.
     - **Проверка цепочки:** клиент отслеживает путь доверия от leaf → intermediate → Root CA (уже в доверенном хранилище ОС).

   > **Важно:** В Wireshark проверьте поле `Subject Public Key Info` — там хранится открытый ключ сервера (в примере RSA). Именно он используется для проверки подписи в `CertificateVerify`.

7. **Certificate Verify:**

   Сервер доказывает владение закрытым ключом сертификата, подписывая хэш всех сообщений handshake своим приватным ключом. В Wireshark это сообщение видно как `Certificate Verify` до шифрования остальных данных. Если подпись не совпадает — соединение прерывается.

8. **Finished (сервер):**

   Сервер отправляет MAC (message authentication code) всего процесса handshake. Это хэш от всех предыдущих сообщений рукопожатия. Цель — подтвердить целостность: ни одно сообщение не было изменено в пути.

9. **New Session Ticket:**

   После завершения handshake сервер может передать `New Session Ticket` — зашифрованный тикет, который клиент сохраняет для быстрого возобновления сессии в течение срока действия тикета (в примере — 1 день). При повторном подключении клиент может использовать этот тикет для 0-RTT или 1-RTT возобновления, минуя полный рукопожатие.

   > **Примечание:** Возобновление через session ticket снижает задержку, но создаёт риск атак повторного воспроизведения (replay attacks). Используйте 0-RTT только для идемпотентных запросов (GET).

10. **Change Cipher Spec + Finished (клиент):**

    Клиент отправляет своё `Change Cipher Spec` (теперь он тоже шифрует данные) и `Finished` — аналогичный MAC для подтверждения целостности с его стороны. После этого handshake завершён, начинается передача `Application Data`.

11. **Верификация в браузере:**

    Откройте инструменты разработчика (F12) → **Конфиденциальность и безопасность** → **Безопасность**:
    - Убедитесь, что соединение помечено как безопасное.
    - Проверьте протокол: `TLS 1.3`.
    - Проверьте алгоритм обмена ключами: `ECDHE` (в примере — гибридный `x25519_kyber768`).
    - Проверьте шифр: `AES_128_GCM` (или другой, выбранный в handshake).
    - Просмотрите сертификат: издатель, срок действия, открытый ключ.

    Эти параметры должны совпадать с тем, что вы видели в Wireshark.

**Ожидаемый результат:**
- Вы можете идентифицировать все сообщения TLS 1.3 handshake в дампе.
- Вы понимаете, зачем нужно каждое сообщение и как оно выглядит в деталях пакета Wireshark.
- Вы можете сопоставить параметры handshake (версия, шифр, SNI, цепочку сертификатов) с данными браузера.

## Команды и фильтры

| Задача | Фильтр / команда Wireshark | Результат |
| :--- | :--- | :--- |
| **Поиск HTTPS по SNI** | `tls.handshake.extensions_server_name == "example.com"` | Все ClientHello для домена |
| **Только TLS Handshake** | `tls.handshake.type == 1 \|\| tls.handshake.type == 2` | Client/Server Hello |
| **Только Application Data** | `tls.record.content_type == 23` | Зашифрованные данные приложений |
| **Поиск по порту 443** | `tcp.dstport == 443` | Все соединения к HTTPS-серверам |
| **Расшифровка через CLI** | `tshark -r capture.pcap -o tls.keylog_file:~/tls-keys.log -Y "http"` | HTTP-запросы/ответы |
| **Слежение за TLS-потоком** | GUI: правый клик → Follow → TLS Stream | Целостный HTTP-обмен |
| **Фильтр HTTP в расшифрованном** | `http.request \|\| http.response` | Видимые после расшифровки HTTP |

## Типичные ошибки

| Ошибка | Причина | Решение |
| :--- | :--- | :--- |
| `TLS, Application Data` без расшифровки | Нет ключей или неправильный файл | Проверить путь к `SSLKEYLOGFILE`, перезапустить браузер |
| `Decrypted TLS` не появляется | Ключи не совпадают с сессией | Перезапустить захват с новым `SSLKEYLOGFILE` |
| `No decryption keys available` | TLS 1.3 с PQC, Wireshark устарел | Обновить Wireshark до 4.4+ |
| Не виден SNI в ClientHello | ECH (Encrypted Client Hello) включён | Включить расшифровку ECH в настройках TLS |
| HTTP-фильтры не работают | Трафик не расшифрован или это HTTP/2 | Использовать `http2` вместо `http`, проверить ключи |

## Лучшие практики

1. **Всегда используйте SNI для фильтрации.** Фильтрация по IP менее надёжна при shared hosting и CDN, где один IP обслуживает множество доменов.
2. **Сохраняйте дамп в `.pcapng`.** Формат поддерживает метаданные и встроенные секреты (DSB), что упрощает совместную работу.
3. **Настраивайте `SSLKEYLOGFILE` до начала захвата.** Ключи экспортируются только для новых TLS-сессий; уже установленные соединения не получить ретроспективно.
4. **Для HTTP/2 используйте фильтр `http2`.** Стандартный фильтр `http` работает только для HTTP/1.x. HTTP/2 требует отдельного диссектора.
5. **Проверяйте ALPN.** Поле `Application Data Protocol` в расширениях TLS показывает, какой протокол был согласован (HTTP/1.1, h2, h3). Это помогает понять, какие фильтры применять.

## Дополнительная информация

### Связь с другими протоколами

HTTPS — это не отдельный протокол, а комбинация HTTP + TLS. В Wireshark это означает:
- **Для HTTP/1.1:** После расшифровки применяется диссектор `http`
- **Для HTTP/2:** После расшифровки применяется диссектор `http2` (фреймы HEADERS/DATA)
- **Для HTTP/3 (QUIC):** Применяется диссектор `quic`, работает поверх UDP

### Визуализация в Wireshark

В левой панели `Packet Details` HTTPS-трафик выглядит так:
```
Frame 123: 74 bytes on wire (592 bits), 74 bytes captured (592 bits)
Ethernet II, Src: ..., Dst: ...
Internet Protocol Version 4, Src: 192.168.1.10, Dst: 93.184.216.34
Transmission Control Protocol, Src Port: 54321, Dst Port: 443, Seq: 1, Len: 30
Transport Layer Security
    Record Layer: Application Data
        Application Data Protocol: http/1.1
    [Decrypted] Hypertext Transfer Protocol
        GET / HTTP/1.1
        Host: networkskurs.ru
        User-Agent: Mozilla/5.0 ...
```

### Первоисточники

- **RFC 8446:** The Transport Layer Security (TLS) Protocol Version 1.3
- **RFC 6066:** Transport Layer Security (TLS) Extensions: SNI и ALPN
- **RFC 9110–9114:** HTTP Semantics, Caching, HTTP/1.1, HTTP/2, HTTP/3
