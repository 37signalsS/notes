# TLS: продвинутые темы для веб-серверов

**Актуально для:** Nginx 1.26.x / Angie 1.8.x / HAProxy 3.0.x / Apache 2.4.62+ / OpenSSL 3.0–3.4 / Linux Kernel 5.15+ (6.x)

Спецификация криптографического протокола, фазы рукопожатия и форматы X.509 детально изложены в руководстве [Протокол TLS — системный обзор](../../Networking/Protocols/tls.md). Вопросы веб-производительности, RTT и бенчмаркинга рассмотрены в статье [Оптимизация TLS для производительности](./web_performance/tls_optimization.md), а архитектурные схемы терминации — в [SSL/TLS Termination: паттерны и production-сценарии](../../Networking/Protocols/ssl_tls_termination.md). Директивы виртуальных хостов приведены в руководствах [Глобальные параметры TLS в Nginx](../Nginx/Security/TLS_SSL/nginx_tls_global_parameters.md) и [Настройка TLS в Angie](../Angie/angie_tls_setup.md).

---

## 1. Определения

**TLS Advanced в веб-серверах** — комплекс низкоуровневых архитектурных и конфигурационных механизмов подсистемы TLS веб-серверов и обратных прокси (Nginx, Angie, HAProxy, Apache HTTPD), предназначенных для оптимизации повторных подключений, аппаратного ускорения криптографии, изоляции сетевого периметра и организации защищенной взаимной аутентификации в bare-metal и виртуализированных средах.

**Session Resumption (Возобновление сессий)** — механизм повторного использования ранее согласованных криптографических параметров (мастер-ключа и параметров шифрования) между клиентом и веб-сервером, исключающий фазу ресурсоемкой асимметричной криптографии:
- **Session ID (RFC 5246):** stateful-подход, при котором сервер сохраняет состояние криптосессии в оперативной памяти (`ssl_session_cache`), а клиенту передает 32-байтный идентификатор.
- **Session Tickets (RFC 5077 для TLS 1.2, RFC 8446 для TLS 1.3):** stateless-подход, при котором сервер сериализует состояние сессии, шифрует его симметричным ключом (STEK) и отправляет клиенту в виде непрозрачного билета (ticket). Сервер не расходует память на хранение сессий.

**STEK (Session Ticket Encryption Key)** — симметричный криптографический ключ веб-сервера (длиной 48 байт для связки AES-128-CBC + HMAC-SHA256 или 80 байт для AES-256-CBC + HMAC-SHA384), используемый для шифрования, дешифрования и контроля целостности сессионных билетов.

**TLS 1.3 0-RTT Early Data (RFC 8446, RFC 8470)** — возможность клиента передавать полезную нагрузку прикладного уровня (HTTP-запрос) непосредственно в первом сетевом пакете вместе с `ClientHello` при возобновлении сессии через Pre-Shared Key (PSK). Экономит 1 RTT задержки установки соединения.

**Replay Attack (Атака повторного воспроизведения)** — перехват сетевым злоумышленником пакета с 0-RTT Early Data и его повторная отправка на целевой веб-сервер. Если запрос содержал неидемпотентную операцию (оплата, изменение пароля, создание сущности), она будет выполнена сервером повторно без ведома клиента.

**Kernel TLS (kTLS)** — механизм ядра Linux (подсистема `AF_ALG`/`TCP_ULP` "tls"), переносящий операции симметричного шифрования и дешифрования потоковых данных TLS (Record Layer) из адресного пространства пользователя в сетевой стек ядра. Позволяет веб-серверу использовать прямой системный вызов `sendfile(2)` (Zero-Copy) для передачи статических файлов по HTTPS без промежуточного копирования страниц памяти в user-space.

**Dual-Certificate Deployment (Двойные сертификаты)** — одновременное подключение к одному виртуальному хосту сертификатов двух стандартов: легковесного ECDSA (на базе эллиптической кривой P-256 / secp256r1) и классического RSA (2048/3072 бит). Веб-сервер динамически отдает клиенту оптимальный тип сертификата на основе расширения `signature_algorithms` в `ClientHello`.

**Strict SNI & Default Server Isolation** — архитектурный паттерн отсечения сетевого мусора и сканеров уязвимостей: разрыв TLS-рукопожатия (`ssl_reject_handshake on;` в Nginx/Angie, `strict-sni` в HAProxy) для запросов, не содержащих расширение Server Name Indication (SNI) или обращающихся к незарегистрированным именам хостов и прямым IP-адресам.

**mTLS (Mutual TLS)** — двусторонняя криптографическая проверка подлинности, при которой не только сервер предъявляет сертификат клиенту, но и клиент обязан предоставить валидный X.509-сертификат, подписанный доверенным Certificate Authority (CA), с обязательной проверкой актуальности по спискам отзыва (CRL).

**TLS False Start (RFC 7918)** — исторический механизм оптимизации TLS 1.2, позволявший клиенту начать передачу зашифрованных прикладных данных сразу после отправки `ClientKeyExchange`, не дожидаясь ответного пакета `Finished` от сервера. Требовал обязательной поддержки Perfect Forward Secrecy (ECDHE) и согласования протокола через ALPN/NPN. В современных стеках с TLS 1.3 вытеснен штатными механизмами 1-RTT и 0-RTT.

---

## 2. Базовые концепции и архитектура

### Архитектура возобновления сессий: Session ID vs Session Tickets

При первичном TLS-рукопожатии сервер и клиент выполняют ресурсоемкие операции асимметричной криптографии (ECDHE генерация общих секретов, валидация цифровых подписей сертификата). Для повторных соединений применяются механизмы возобновления:

```
Stateful Resumption (Session ID, TLS 1.2):
Client                                               Server
  | ─── ClientHello [SessionID = XYZ] ──────────────> | (Поиск в ssl_session_cache)
  | <── ServerHello [SessionID = XYZ] ─────────────── | (Найден: восстанавливаем мастер-ключ)
  | <── [ChangeCipherSpec] + Finished ─────────────── | (1 RTT вместо 2 RTT)
  | ─── [ChangeCipherSpec] + Finished + HTTP GET ───> |

Stateless Resumption (Session Tickets, TLS 1.2 / TLS 1.3):
Client                                               Server
  | ─── ClientHello [Ticket = {Encrypted State}] ───> | (Дешифрование билета ключом STEK)
  | <── ServerHello [NewTicket] + Finished ────────── | (Ключи восстановлены, память не занята)
  | ─── Finished + HTTP GET ────────────────────────> |
```

#### Структура сессионного билета (STEK)
Сессионный билет OpenSSL/Nginx (RFC 5077) содержит следующие бинарные поля:
1. **Key Name (16 байт):** уникальный идентификатор ключа STEK, позволяющий серверу мгновенно определить, какой именно ключ из списка сконфигурированных использовать для дешифрования.
2. **IV (Initialization Vector, 16 байт):** вектор инициализации для режима шифрования AES-CBC / AES-GCM.
3. **Encrypted State (переменная длина):** сериализованное состояние сессии (версия TLS, выбранный cipher suite, мастер-секрет, параметры клиента), зашифрованное алгоритмом AES-128 или AES-256.
4. **HMAC (16 или 32 байта):** имитовставка (HMAC-SHA256 или HMAC-SHA384), защищающая билет от модификации.

```
┌─────────────────┬─────────────────┬───────────────────────────────┬─────────────────┐
│ Key Name (16 B) │   IV (16 B)     │ Encrypted State (AES-128/256) │ HMAC (16/32 B)  │
└─────────────────┴─────────────────┴───────────────────────────────┴─────────────────┘
```

#### Проблема кластерной балансировки и синхронизации STEK
В высоконагруженных bare-metal инфраструктурах входящий трафик распределяется балансировщиком L4 (Keepalived / IPVS / HAProxy TCP mode) по нескольким веб-серверам (Nginx/Angie). 
- Если каждый узел Nginx генерирует ключ билетов сессий автоматически при старте в оперативной памяти (поведение по умолчанию при отсутствии директивы `ssl_session_ticket_key`), то клиент, получивший билет на Ноде 1, при следующем запросе попадает на Ноду 2.
- Нода 2 не может расшифровать чужой билет и инициирует **полное TLS-рукопожатие (Full Handshake)**.
- Это нивелирует пользу от Session Resumption и вызывает паразитный всплеск утилизации CPU.
- **Инженерное решение:** Централизованная генерация бинарного файла STEK и его синхронизация между всеми узлами кластера с периодической ротацией.

### TLS 1.3 0-RTT Early Data и архитектурная защита от Replay-атак

Механизм 0-RTT позволяет клиенту передать тело HTTP-запроса в первом же пакете вместе с `ClientHello`.

```
Обычное рукопожатие TLS 1.3:
Client ──────── TCP SYN ───────> Server
Client <────── TCP SYN+ACK ───── Server
Client ─── ClientHello + Keys ──> Server
Client <── ServerHello + Keys ── Server (1 RTT задержки до отправки данных)
Client ─── HTTP GET /api ───────> Server

TLS 1.3 0-RTT Resumption:
Client ──────── TCP SYN ───────> Server
Client <────── TCP SYN+ACK ───── Server
Client ─── ClientHello + PSK ───> Server
          [0-RTT: HTTP GET /api]          (0 RTT: Данные отправлены сразу!)
Client <── ServerHello + 200 OK ─ Server
```

#### Вектор уязвимости Replay Attack
Криптографические ключи 0-RTT (Early Data Secret) вычисляются на основе статического PSK из сессионного билета до того, как сервер подтвердил актуальность рукопожатия через эфемерный обмен ключами Diffie-Hellman.
1. Пассивный сетевой перехватчик записывает пакет `ClientHello` + зашифрованные данные 0-RTT.
2. Злоумышленник отправляет точную копию этого пакета на тот же сервер спустя 10 минут (или на соседний сервер кластера с тем же STEK).
3. Сервер успешно расшифровывает запрос и передает его в бэкенд на исполнение.
4. Если запрос был `POST /api/v1/payment/transfer`, операция будет исполнена дважды.

#### Защитные барьеры веб-сервера (RFC 8470)
Для безопасного использования 0-RTT на уровне SRE/DevOps архитектуры внедряется эшелонированная защита:
- **Ограничение методов:** веб-сервер принудительно разрешает Early Data исключительно для безопасных идемпотентных методов (`GET`, `HEAD`, `OPTIONS`).
- **Заголовок `Early-Data: 1`:** веб-сервер информирует приложение о том, что запрос пришел в фазе 0-RTT (через `$ssl_early_data`).
- **HTTP 425 (Too Early):** если клиент отправляет опасный запрос через Early Data, прокси или бэкенд возвращает статус `425 Too Early`. Клиент обязан автоматически повторить запрос в рамках уже установленного безопасного 1-RTT соединения.

### Архитектура Kernel TLS (kTLS) в Linux

В классической модели HTTPS-сервера передача статического файла с диска клиенту выглядит следующим образом:
1. Веб-сервер читает файл из дискового кэша ядра в user-space буфер процесса через системный вызов `read(2)`.
2. Библиотека OpenSSL шифрует данные в оперативной памяти процесса.
3. Веб-сервер отправляет зашифрованный буфер обратно в ядро через `write(2)` / `send(2)`.
4. Сетевой стек ядра передает пакеты в драйвер сетевой карты (NIC).

Это приводит к двойному копированию данных в оперативной памяти и постоянным контекстным переключениям процессора (Context Switches).

```
Классический TLS (User-Space Crypto):
[ Диск ] ──read()──> [ Page Cache ] ──copy──> [ Nginx Buffer ]
                                                     │
                                             (OpenSSL Crypto)
                                                     ▼
[ Сетевая карта ] <──send()── [ Socket Buffer ] <──copy──┘

Kernel TLS (kTLS + sendfile Zero-Copy):
                      ┌── Рукопожатие: OpenSSL (User-Space) ──┐
                      ▼                                       ▼
[ Диск ] ──DMA──> [ Page Cache ] ─── sendfile() Zero-Copy ───> [ Ядро Linux (kTLS Crypto) ] ──DMA──> [ NIC ]
```

При активации **kTLS**:
1. Рукопожатие, согласование ключей и взаимная аутентификация выполняются в user-space библиотекой OpenSSL.
2. После завершения handshake OpenSSL передает ключи симметричного шифрования (AES-GCM / ChaCha20-Poly1305) в сокет ядра через системный вызов `setsockopt(..., SOL_TCP, TCP_ULP, "tls", ...)`.
3. При отправке статики Nginx вызывает системный вызов `sendfile(2)`.
4. Ядро Linux берет страницы напрямую из Page Cache, шифрует их на лету с использованием инструкций процессора (AES-NI / AVX-512) или сетевой карты (TLS Hardware Offload) и передает в сетевой интерфейс. Копирование в user-space отсутствует.

### Архитектура Dual-Certificate: ECDSA и RSA

| Параметр | ECDSA (P-256 / secp256r1) | RSA (2048 бит) | RSA (4096 бит) |
| :--- | :--- | :--- | :--- |
| **Длина ключа** | 256 бит | 2048 бит | 4096 бит |
| **Криптостойкость** | 128 бит безопасности | 112 бит безопасности | 128 бит безопасности |
| **Размер сертификата** | ~700–900 байт | ~1500–2000 байт | ~2500–3500 байт |
| **Скорость генерации подписи** | Высокая (~25 000 sign/s) | Низкая (~2 000 sign/s) | Критически низкая (~350 sign/s) |
| **Скорость проверки подписи** | Средняя (~10 000 verify/s) | Очень высокая (~40 000 verify/s) | Средняя (~8 000 verify/s) |
| **Совместимость с legacy** | Современные клиенты (2015+) | Полная обратная совместимость | Полная обратная совместимость |

При одновременной настройке ECDSA и RSA в Nginx/Angie:
1. Клиент присылает `ClientHello`, где в расширении `signature_algorithms` перечислены поддерживаемые типы подписей (например, `ecdsa_secp256r1_sha256` и `rsa_pss_rsae_sha256`).
2. Веб-сервер проверяет свои сертификаты. Если клиент поддерживает ECDSA, сервер отдает компактный ECDSA-сертификат.
3. Если клиент устарел и не поддерживает эллиптические кривые, сервер отдает RSA-сертификат.
4. В результате современные клиенты получают ускорение установки сессии (сертификат помещается в один TCP-сегмент без фрагментации), а устаревшие устройства не получают ошибок подключения.

---

## 3. Практические сценарии и конфигурация

### Сценарий 1: Production-конфигурация Nginx/Angie со всеми расширенными опциями

Конфигурация включает: TLS 1.2/1.3, HTTP/2 (современный синтаксис Nginx 1.25.1+ / Angie 1.8+), двойные сертификаты (ECDSA + RSA), ротацию двух ключей сессионных билетов, включение kTLS, фильтрацию 0-RTT Early Data через `map` и изоляцию невалидных запросов через `ssl_reject_handshake`.

```nginx
# /etc/nginx/nginx.conf (уровень http)

http {
    include       /etc/nginx/mime.types;
    default_type  application/octet-stream;

    # 1. kTLS (Zero-Copy шифрование в ядре)
    # Для классического Nginx с OpenSSL 3.0+:
    ssl_conf_command Options KTLS;
    sendfile on;
    tcp_nopush on;
    tcp_nodelay on;

    # Для Angie (нативная директива):
    # ssl_ktls on;

    # 2. Глобальные протоколы и наборы шифров
    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_prefer_server_ciphers off; # В TLS 1.3 клиент выбирает cipher, для TLS 1.2 OpenSSL балансирует
    ssl_ciphers 'ECDHE-ECDSA-AES128-GCM-SHA256:ECDHE-RSA-AES128-GCM-SHA256:ECDHE-ECDSA-AES256-GCM-SHA384:ECDHE-RSA-AES256-GCM-SHA384:ECDHE-ECDSA-CHACHA20-POLY1305:ECDHE-RSA-CHACHA20-POLY1305';

    # 3. Session Resumption (Кэш в памяти + Session Tickets)
    # 20 МБ разделяемой памяти вмещает около 80 000 сессий
    ssl_session_cache shared:SSL_GLOBAL:20m;
    ssl_session_timeout 1d;
    ssl_session_tickets on;

    # Подключение двух ключей STEK:
    # Первый ключ — для шифрования новых и дешифрования старых билетов
    # Второй ключ — исключительно для дешифрования билетов предыдущей эпохи
    ssl_session_ticket_key /etc/nginx/ssl/tickets/ticket_current.key;
    ssl_session_ticket_key /etc/nginx/ssl/tickets/ticket_previous.key;

    # 4. OCSP Stapling для ускорения валидации
    ssl_stapling on;
    ssl_stapling_verify on;
    resolver 127.0.0.1 1.1.1.1 valid=300s ipv6=off;
    resolver_timeout 5s;

    # 5. Защитная мапа для 0-RTT Early Data (RFC 8470)
    # Если запрос пришел в Early Data ($ssl_early_data = "1") И метод не является безопасным,
    # мы отклоняем его статусом 425 Too Early.
    map $ssl_early_data$request_method $deny_0rtt_mutation {
        "~^1(POST|PUT|DELETE|PATCH)$" 1;
        default 0;
    }

    # Сервер по умолчанию: блокировка сканеров и утечки SNI
    server {
        listen 443 ssl default_server;
        listen [::]:443 ssl default_server;
        server_name _;

        # Разрыв рукопожатия без отдачи сертификата
        ssl_reject_handshake on;
    }

    # Основной рабочий виртуальный хост
    server {
        listen 443 ssl;
        listen [::]:443 ssl;
        http2 on; # Современный синтаксис Nginx 1.25.1+ и Angie
        server_name api.corp.internal;

        # Двойные сертификаты: ECDSA (быстрый) + RSA (совместимый)
        ssl_certificate         /etc/ssl/certs/api.corp.internal.ecdsa.crt;
        ssl_certificate_key     /etc/ssl/private/api.corp.internal.ecdsa.key;
        ssl_certificate         /etc/ssl/certs/api.corp.internal.rsa.crt;
        ssl_certificate_key     /etc/ssl/private/api.corp.internal.rsa.key;

        # Включение 0-RTT
        ssl_early_data on;

        # HSTS (2 года с субдоменами)
        add_header Strict-Transport-Security "max-age=63072000; includeSubDomains" always;
        add_header X-Content-Type-Options "nosniff" always;
        add_header X-Frame-Options "DENY" always;

        location / {
            # Проверка Replay-атаки на неидемпотентные методы
            if ($deny_0rtt_mutation) {
                return 425; # RFC 8470: клиент обязан повторить запрос после полного handshake
            }

            proxy_pass http://backend_cluster;
            proxy_set_header Host $host;
            proxy_set_header X-Real-IP $remote_addr;
            proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
            proxy_set_header X-Forwarded-Proto $scheme;

            # Передача флага Early-Data бэкенду
            proxy_set_header Early-Data $ssl_early_data;
        }

        # Отдача тяжелой статики через kTLS Zero-Copy
        location /static/ {
            alias /var/www/static/;
            expires 30d;
            add_header Cache-Control "public, no-transform";
            sendfile on;
            tcp_nopush on;
        }
    }
}
```

### Сценарий 2: Централизованная ротация и синхронизация Session Ticket Keys (STEK)

Ключ билетов сессий — строго 80 байт (AES-256) или 48 байт (AES-128) случайных бинарных данных. Использование командной подстановки `$()` и команды `echo` повреждает бинарные данные из-за удаления нулевых байтов и добавления байта перевода строки (`0x0A`).

Скрипт выполняет корректную ротацию с сохранением текущего и предыдущего ключей:

```bash
#!/usr/bin/env bash
# /usr/local/bin/rotate-session-tickets.sh
# Выполняется по cron/systemd-timer каждые 12 часов на мастере

set -euo pipefail

KEY_DIR="/etc/nginx/ssl/tickets"
CURRENT_KEY="${KEY_DIR}/ticket_current.key"
PREVIOUS_KEY="${KEY_DIR}/ticket_previous.key"
NEW_KEY="${KEY_DIR}/ticket_new.key"

# 1. Генерация ровно 80 байт криптографически стойких случайных данных
# 16 байт (имя) + 32 байта (AES-256) + 32 байта (HMAC-SHA256) = 80 байт
umask 077
openssl rand 80 > "${NEW_KEY}"

# 2. Проверка точного размера файла в байтах
KEY_SIZE=$(wc -c < "${NEW_KEY}")
if [ "${KEY_SIZE}" -ne 80 ]; then
    echo "ERROR: Неверный размер сгенерированного ключа: ${KEY_SIZE} байт (ожидается 80)" >&2
    rm -f "${NEW_KEY}"
    exit 1
fi

# 3. Бесшовная ротация файлов
if [ -f "${CURRENT_KEY}" ]; then
    mv -f "${CURRENT_KEY}" "${PREVIOUS_KEY}"
fi
mv -f "${NEW_KEY}" "${CURRENT_KEY}"

# Выставление прав доступа
chown -R root:root "${KEY_DIR}"
chmod 600 "${KEY_DIR}"/ticket_*.key

# 4. Проверка синтаксиса и graceful reload веб-сервера
nginx -t && systemctl reload nginx

echo "[$(date -Iseconds)] STEK успешно ротирован. Current: $(sha256sum ${CURRENT_KEY} | cut -d' ' -f1)"
```

#### Кластерная синхронизация через Ansible / Rsync
Для парка серверов за балансировщиком Keepalived / HAProxy мастер-нода генерирует ключ и безопасно раскладывает его по остальным узлам:

```bash
# Пример синхронизации ключей по SSH перед перезагрузкой
CLUSTER_NODES=("web-node-02.corp" "web-node-03.corp" "web-node-04.corp")

for NODE in "${CLUSTER_NODES[@]}"; do
    rsync -aq -e "ssh -o BatchMode=yes" "${KEY_DIR}/ticket_"*.key "root@${NODE}:${KEY_DIR}/"
    ssh "${NODE}" "chmod 600 ${KEY_DIR}/ticket_*.key && nginx -t && systemctl reload nginx"
done
```

### Сценарий 3: Активация и диагностика Kernel TLS (kTLS) на Linux

Подготовка хоста для работы с kTLS (ядро Linux 5.15+ / 6.x и OpenSSL 3.0+):

#### 1. Загрузка модуля ядра Linux
```bash
# Проверка наличия модуля kTLS в ядре
modinfo tls

# Ручная загрузка модуля
modprobe tls

# Закрепление автоматической загрузки при старте ОС
echo "tls" > /etc/modules-load.d/tls.conf
```

#### 2. Проверка поддержки kTLS в OpenSSL
Проверьте, что установленная библиотека OpenSSL скомпилирована с флагом `enable-ktls`:
```bash
openssl version -a | grep -i ktls
# → compiler: ... -DOPENSSL_KTLS ...
```

Если глобальный OpenSSL требует явной директивы, в `/etc/ssl/openssl.cnf` добавляется:
```ini
[openssl_init]
ssl_conf = ssl_sect

[ssl_sect]
system_default = system_default_sect

[system_default_sect]
Options = KTLS
```

В конфигурации Nginx активируется:
```nginx
ssl_conf_command Options KTLS;
sendfile on;
tcp_nopush on;
```

### Сценарий 4: Двусторонний mTLS с проверкой списков отзыва (CRL)

Взаимная аутентификация микросервисов или административных рабочих мест с проверкой клиентских сертификатов и безопасным пробросом метаданных:

```nginx
# /etc/nginx/conf.d/mtls_protected_service.conf

server {
    listen 443 ssl;
    server_name m2m.corp.internal;

    ssl_certificate     /etc/ssl/certs/m2m.corp.internal.crt;
    ssl_certificate_key /etc/ssl/private/m2m.corp.internal.key;
    ssl_protocols       TLSv1.3;

    # 1. Корневой CA для валидации клиентских сертификатов
    ssl_client_certificate /etc/nginx/ssl/internal_ca.crt;

    # 2. Режим проверки: 'on' требует сертификат обязательно
    ssl_verify_client on;
    ssl_verify_depth 2;

    # 3. Список отозванных сертификатов (CRL)
    ssl_crl /etc/nginx/ssl/ca_crl.pem;

    location / {
        # Защита от подделки заголовков со стороны клиентов:
        # Очищаем входящие пользовательские заголовки перед отправкой бэкенду
        proxy_set_header X-Client-DN "";
        proxy_set_header X-Client-Serial "";
        proxy_set_header X-Client-Verify "";

        # Передача подтвержденных криптографических атрибутов
        proxy_set_header X-Client-DN $ssl_client_s_dn;
        proxy_set_header X-Client-Issuer $ssl_client_i_dn;
        proxy_set_header X-Client-Serial $ssl_client_serial;
        proxy_set_header X-Client-Fingerprint $ssl_client_fingerprint;
        proxy_set_header X-Client-Verify $ssl_client_verify;

        proxy_pass http://internal_api_upstream;
    }
}
```

#### Автоматическое обновление CRL через systemd-timer
CRL имеет ограниченный срок действия (`Next Update`). При его истечении OpenSSL блокирует все подключения. Скрипт автоматического обновления:

```bash
#!/usr/bin/env bash
# /usr/local/bin/update-ca-crl.sh
set -euo pipefail

CRL_URL="http://ca.corp.internal/pki/internal_ca.crl"
TEMP_CRL="/tmp/new_crl.pem"
TARGET_CRL="/etc/nginx/ssl/ca_crl.pem"

# Скачивание и конвертация из DER в PEM (если CA отдает DER)
curl -fsSL "${CRL_URL}" | openssl crl -inform DER -outform PEM -out "${TEMP_CRL}"

# Проверка валидности структуры CRL
if openssl crl -in "${TEMP_CRL}" -noout 2>/dev/null; then
    mv -f "${TEMP_CRL}" "${TARGET_CRL}"
    chmod 644 "${TARGET_CRL}"
    # Nginx перечитывает CRL только при reload
    systemctl reload nginx
    echo "[$(date -Iseconds)] CRL успешно обновлен."
else
    echo "ERROR: Получен невалидный CRL файл" >&2
    rm -f "${TEMP_CRL}"
    exit 1
fi
```

### Сценарий 5: Продвинутая конфигурация TLS в HAProxy

HAProxy выступает высокопроизводительным L7-терминатором TLS с поддержкой динамических сертификатов, строгой изоляции SNI и Session Tickets:

```haproxy
# /etc/haproxy/haproxy.cfg

global
    log /dev/log local0 info
    # Выделение памяти под SSL-кэш (в количестве сессий)
    tune.ssl.cachesize 100000
    tune.ssl.lifetime 86400
    tune.ssl.default-dh-param 2048

    # Список ключей STEK для stateless возобновления (формат: 48 байт в base64 на строку)
    # Первый ключ — шифрование/дешифрование, остальные — дешифрование
    ssl-server-verify required

frontend fe_https
    # bind с поддержкой каталога двойных сертификатов (.ecdsa и .rsa в одной папке),
    # строгим SNI (отказ клиентам без SNI) и согласованием ALPN
    bind :443 ssl crt /etc/haproxy/certs/ strict-sni alpn h2,http/1.1 tls-ticket-keys /etc/haproxy/ssl/tickets.key

    mode http
    option httplog

    # Проверка клиентского сертификата для внутренней зоны (опциональный mTLS)
    # bind :443 ssl crt ... ca-file /etc/haproxy/ssl/internal_ca.crt verify optional crl-file /etc/haproxy/ssl/crl.pem

    # HSTS заголовок
    http-response set-header Strict-Transport-Security "max-age=63072000; includeSubDomains; preload"

    # Передача TLS-метаданных бэкендам
    http-request set-header X-Forwarded-Proto https
    http-request set-header X-SSL-Client-Verify %[ssl_c_verify]
    http-request set-header X-SSL-Client-DN %[ssl_c_s_dn]

    default_backend be_app_servers

backend be_app_servers
    mode http
    balance roundrobin
    cookie SRVNAME insert indirect nocache
    server app01 10.0.1.11:8080 check cookie app01
    server app02 10.0.1.12:8080 check cookie app02
```

### Сценарий 6: Продвинутая конфигурация Apache HTTPD (mod_ssl)

Конфигурация модуля `mod_ssl` в Apache 2.4.62+ с изоляцией хостов, двойными сертификатами и сессионным кэшем:

```apache
# /etc/apache2/mods-available/ssl.conf (глобальный контекст)

SSLRandomSeed startup builtin
SSLRandomSeed connect builtin

# Глобальный разделяемый кэш сессий (shmcb = high performance shared memory cyclic buffer)
SSLSessionCache         shmcb:/run/apache2/ssl_gcache_data(512000)
SSLSessionCacheTimeout  86400

# Включение Session Tickets
SSLSessionTickets       on
SSLSessionTicketKeyFile /etc/apache2/ssl/ticket.key

# Ограничение версий и шифров
SSLProtocol             all -SSLv3 -TLSv1 -TLSv1.1
SSLCipherSuite          HIGH:!aNULL:!MD5:!3DES:!CAMELLIA
SSLHonorCipherOrder     off

# Строгая проверка SNI (сброс соединений к незарегистрированным хостам)
SSLStrictSNIVHostCheck  on

# /etc/apache2/sites-available/api_corp.conf (контекст vhost)
<VirtualHost *:443>
    ServerName api.corp.internal

    SSLEngine on

    # Двойные сертификаты (Apache 2.4.8+ поддерживает парные директивы)
    # Сертификат 1: ECDSA
    SSLCertificateFile    /etc/ssl/certs/api.corp.internal.ecdsa.crt
    SSLCertificateKeyFile /etc/ssl/private/api.corp.internal.ecdsa.key

    # Сертификат 2: RSA (fallback)
    SSLCertificateFile    /etc/ssl/certs/api.corp.internal.rsa.crt
    SSLCertificateKeyFile /etc/ssl/private/api.corp.internal.rsa.key

    # Протоколы прикладного уровня ALPN
    Protocols h2 http/1.1

    Header always set Strict-Transport-Security "max-age=63072000"

    ProxyPass / http://127.0.0.1:8080/
    ProxyPassReverse / http://127.0.0.1:8080/
</VirtualHost>
```

---

## 4. Операции и команды валидации

### 1. Проверка возобновления сессий (Session ID и Session Ticket)

Команда `-reconnect` заставляет `openssl s_client` выполнить 5 повторных подключений к тому же серверу с использованием кэшированного идентификатора сессии:

```bash
# Тестирование повторного использования сессии (Session Resumption)
openssl s_client -connect api.corp.internal:443 -servername api.corp.internal -reconnect 2>&1 | grep -E "Reused|Session-ID|TLS session ticket"
# → Reused, TLSv1.3, Cipher is TLS_AES_128_GCM_SHA256
# → Reused, TLSv1.3, Cipher is TLS_AES_128_GCM_SHA256
# → Reused, TLSv1.3, Cipher is TLS_AES_128_GCM_SHA256
```

Сохранение и повторное использование билета сессии в TLS 1.3:
```bash
# 1. Первое подключение: сохраняем сессионный билет в файл
echo | openssl s_client -connect api.corp.internal:443 -servername api.corp.internal -tls1_3 -sess_out /tmp/session.pem > /dev/null 2>&1

# 2. Второе подключение: восстанавливаем сессию из билета
openssl s_client -connect api.corp.internal:443 -servername api.corp.internal -tls1_3 -sess_in /tmp/session.pem 2>&1 | grep "Reused"
# → Reused, TLSv1.3, Cipher is TLS_AES_128_GCM_SHA256
```

### 2. Тестирование 0-RTT Early Data через curl

Для тестирования 0-RTT формируется бинарный файл запроса, который curl отправляет при наличии сохраненной сессии:

```bash
# 1. Первое подключение: получаем сессионный тикет
curl -Iv --tlsv1.3 --sessionid /tmp/curl_session https://api.corp.internal/healthz > /dev/null 2>&1

# 2. Формируем тело Early Data (идемпотентный GET)
printf "GET /healthz HTTP/1.1\r\nHost: api.corp.internal\r\nUser-Agent: curl-0rtt-test\r\n\r\n" > /tmp/early_data.bin

# 3. Отправка 0-RTT Early Data через curl (версия 7.61+)
curl -Iv --tlsv1.3 --early-data /tmp/early_data.bin https://api.corp.internal/healthz 2>&1 | grep -i -E "early|0-rtt|200 ok"
# → * Connected to api.corp.internal (10.0.1.10) port 443
# → * TLS 1.3: 0-RTT early data sent
# → < HTTP/1.1 200 OK
```

### 3. Диагностика kTLS в ядре Linux

Проверка активности аппаратного/программного шифрования в стеке Linux:

```bash
# 1. Проверка системной статистики kTLS
cat /proc/net/tls_stat
# → TlsTxSw: 148923
# → TlsRxSw: 0
# → TlsTxDevice: 0
# → TlsRxDevice: 0

# 2. Проверка активных сокетов веб-сервера через утилиту ss
# Наличие флагов tls-tx или tls-rx указывает на перенос шифрования в ядро
ss -t -i 'sport = :443' | grep -i "tls"
# → tls-tx:AES-GCM-128/1.3 tls-rx:none
```

### 4. Тестирование сброса рукопожатия при Strict SNI (`ssl_reject_handshake`)

Проверка поведения сервера по умолчанию при сканировании или отсутствии SNI:

```bash
# 1. Обращение без SNI (напрямую по IP-адресу)
openssl s_client -connect 10.0.1.10:443 2>&1 | grep -i -E "error|alert"
# → 140321200:error:14094458:SSL routines:ssl3_read_bytes:tlsv1 unrecognized name:../ssl/record/rec_layer_s3.c:1544:SSL alert number 112

# 2. Обращение с неизвестным доменом (отсутствующим в server_name)
openssl s_client -connect 10.0.1.10:443 -servername unknown.domain.corp 2>&1 | grep -i -E "error|alert"
# → 140321200:error:14094458:SSL routines:ssl3_read_bytes:tlsv1 unrecognized name:SSL alert number 112
```

### 5. Проверка согласования Dual-Certificate (ECDSA vs RSA)

Принудительное указание клиентом поддерживаемых алгоритмов подписи:

```bash
# Запрос с поддержкой ECDSA
openssl s_client -connect api.corp.internal:443 -servername api.corp.internal -sigalgs "ECDSA+SHA256" 2>&1 | grep -E "Server public key|Peer signature type"
# → Server public key is 256 bit EC
# → Peer signature type: ECDSA

# Запрос только с поддержкой RSA (симуляция устаревшего клиента)
openssl s_client -connect api.corp.internal:443 -servername api.corp.internal -sigalgs "RSA+SHA256" 2>&1 | grep -E "Server public key|Peer signature type"
# → Server public key is 2048 bit RSA
# → Peer signature type: RSA-PSS
```

### 6. Валидация mTLS соединения

```bash
# Успешная авторизация с клиентским сертификатом
curl -sS --cert /etc/ssl/client/client.crt --key /etc/ssl/client/client.key --cacert /etc/ssl/certs/ca.crt https://m2m.corp.internal/api/v1/status
# → {"status":"authenticated","subject":"CN=microservice-billing"}

# Ошибка при отсутствии клиентского сертификата
curl -sS --cacert /etc/ssl/certs/ca.crt https://m2m.corp.internal/api/v1/status
# → <html><head><title>400 No required SSL certificate was sent</title></head>...
```

---

## 5. Устранение неполадок (Troubleshooting)

| Симптом / Ошибка | Первопричина | Метод диагностики | Инженерное решение |
| :--- | :--- | :--- | :--- |
| **`Reused: No` при повторных подключениях в кластере** | Рассинхронизация ключей STEK (`ssl_session_ticket_key`) между серверами за балансировщиком нагрузки. | `for host in node01 node02; do ssh $host sha256sum /etc/nginx/ssl/tickets/ticket_current.key; done` — чексуммы различаются. | Настроить централизованный скрипт ротации ключей STEK с рассылкой по узлам кластера и вызовом `systemctl reload nginx`. |
| **`invalid ticket key size in ...` при reload Nginx** | Размер файла ключа не равен строго 48 или 80 байтам (например, добавлен `\n` из-за генерации через `echo` или текстовый редактор). | `wc -c /etc/nginx/ssl/tickets/ticket_current.key`<br># → 81 (или 49) | Генерировать бинарный ключ напрямую без утилит форматирования: `openssl rand 80 > ticket_current.key`. |
| **Дублирование транзакций / Replay Attack в 0-RTT** | Включена директива `ssl_early_data on;` без фильтрации методов, бэкенд не валидирует заголовок `Early-Data`. | Поиск мутирующих запросов в логах:<br>`awk '$request ~ /POST|PUT/ && $ssl_early_data == "1"' /var/log/nginx/access.log` | Настроить `map $ssl_early_data$request_method` с принудительным возвратом HTTP 425 для мутирующих методов. |
| **kTLS не ускоряет передачу, в `/proc/net/tls_stat` нули** | Модуль `tls` не загружен в ядро, либо согласован шифр, не поддерживаемый аппаратным/ядерным kTLS. | `lsmod \| grep tls`<br>`ss -ti 'sport = :443' \| grep tls` | Выполнить `modprobe tls`, закрепить в `/etc/modules-load.d/tls.conf`. Убедиться в использовании OpenSSL 3.0+ и шифров `TLS_AES_128_GCM_SHA256` или `TLS_AES_256_GCM_SHA384`. |
| **Циклический возврат ошибки `425 Too Early`** | Клиент отправляет запрос через Early Data, прокси отклоняет его статусом 425, но клиентское ПО не реализует механизм повторной отправки (RFC 8470). | Просмотр заголовков ответа через `curl -I` и логов приложения. | Отключить `ssl_early_data` для данного API-эндпоинта либо обновить клиентскую библиотеку до поддержки RFC 8470. |
| **`SSL_ERROR_UNRECOGNIZED_NAME_ALERT` (112) у легитимных клиентов** | Сработала директива `ssl_reject_handshake on;` из-за отсутствия SNI у старого клиента или внутренней системы мониторинга. | `openssl s_client -connect host:443` (без `-servername`). | Добавить отправку SNI в проверки здоровья L4/L7 балансировщика, либо завести выделенный `server` блок для IP-адреса healthcheck. |
| **`400 Bad Request: SSL certificate error` при валидном mTLS** | Истек срок действия списка отзыва (`ssl_crl`) — параметр `Next Update` находится в прошлом. | `openssl crl -in /etc/nginx/ssl/ca_crl.pem -text -noout \| grep "Next Update"` | Настроить регулярный systemd-timer для скачивания свежего CRL из PKI и выполнения graceful reload веб-сервера. |
| **Веб-сервер отдает RSA-сертификат современным клиентам** | Некорректный порядок директив сертификатов либо в `ssl_ciphers` отсутствуют шифры на базе ECDSA. | `openssl s_client -connect host:443 -servername host -tls1_3 2>&1 \| grep "Server public key"` | Прописать путь к ECDSA-сертификату первым в конфигурации виртуального хоста; убедиться в наличии шифров `ECDHE-ECDSA-*`. |
| **`session id context uninitialized` в логах Nginx** | Не настроен контекст идентификатора сессии при использовании клиентских сертификатов и кэша сессий. | `grep "session id context" /var/log/nginx/error.log` | Добавить директиву `ssl_session_cache` на уровне `http` или явно задать `ssl_session_timeout`. |

---

## 6. Лучшие практики

### 1. Безопасность криптографических ключей STEK
- **Жизненный цикл ключей:** Ротируйте ключи сессионных билетов каждые 12–24 часа. Слишком долгая жизнь STEK нарушает свойство Perfect Forward Secrecy: если ключ билетов скомпрометирован, злоумышленник может расшифровать весь сохраненный трафик возобновленных сессий за этот период.
- **Хранение в RAM:** В средах с высокими требованиями к безопасности размещайте директорию `/etc/nginx/ssl/tickets/` на файловой системе `tmpfs` (в оперативной памяти), чтобы исключить сохранение бинарных ключей на твердотельных накопителях (SSD/NVMe).
- **Плавный переход:** Всегда конфигурируйте два ключа (`ticket_current.key` и `ticket_previous.key`). Это исключает сброс сессий активных пользователей в момент ротации.

### 2. Принцип безопасного использования 0-RTT Early Data
- **Изоляция мутирующих эндпоинтов:** Никогда не включайте 0-RTT глобально для всего приложения. Разрешайте 0-RTT исключительно на CDN- или Edge-уровне для тяжелых GET-запросов (карточки товаров, статические страницы, поисковые выборки).
- **Применение RFC 8470:** Всегда пробрасывайте заголовок `proxy_set_header Early-Data $ssl_early_data;` на бэкенд, чтобы бизнес-логика приложения могла гарантированно отказать в выполнении мутирующей операции при случайном попадании запроса в 0-RTT.

### 3. Оптимизация оперативной памяти под кэш сессий
- **Расчет памяти:** При объеме `ssl_session_cache shared:SSL:20m` сервер резервирует 20 МБ в разделяемой памяти (shared memory). Каждый 1 МБ вмещает приблизительно 4 000 TLS-сессий. 20 МБ достаточно для поддержания ~80 000 параллельных сессий.
- **Таймаут:** Значение `ssl_session_timeout 1d;` оптимально для мобильных клиентов и браузеров, снижая нагрузку на CPU от повторных рукопожатий в течение суток.

### 4. Эксплуатационные требования к bare-metal окружению (DevOps/SRE)
- **Аппаратные инструкции:** Убедитесь, что процессор хоста поддерживает расширения `aes` и `pclmulqdq` (`grep -E "aes|pclmulqdq" /proc/cpuinfo`). Это снижает нагрузку на вычисление AES-GCM до минимума.
- **Защита от сканеров периметра:** Конфигурация `ssl_reject_handshake on;` на виртуальном сервере по умолчанию является обязательным отраслевым стандартом. Она скрывает доменные имена и сертификаты инфраструктуры от сетевых сканеров (Shodan, Censys, masscan), сканирующих IP-диапазоны дата-центра.
- **Мониторинг метрик:** Отслеживайте количество возобновленных сессий и сбросов через модули метрик Nginx (`nginx-module-vts` / Angie console / Prometheus exporter). Падение процента `ssl_handshake_reused` ниже 60% сигнализирует о сбое синхронизации STEK между узлами.

---

## 7. Граничные случаи и ограничения

1. **Несовместимость kTLS с пользовательскими фильтрами контента:** Если Nginx выполняет модификацию тела ответа (модули `sub_filter`, `image_filter`, gzip-сжатие на лету), данные обязаны находиться в user-space памяти. В этом случае вызов `sendfile(2)` с kTLS не применяется, и веб-сервер возвращается к классическому шифрованию в user-space.
2. **Ограничения 0-RTT в гетерогенных кластерах:** При балансировке 0-RTT между серверами невозможно гарантировать строгую защиту от Replay-атак без распределенного высокоскоростного кэша уже использованных тикетов (Single-Use Tickets). Поэтому отказ от выполнения мутирующих методов (возврат HTTP 425) является единственно надежной мерой.
3. **Размер списков отзыва (CRL):** При хранении в CRL десятков тысяч отозванных клиентских сертификатов файл может достигать десятков мегабайт. Nginx считывает CRL целиком в оперативную память при старте/reload. Парсинг огромного CRL увеличивает время перезагрузки воркеров и потребление RAM.
4. **Утрата сессий при падении процесса без STEK:** Использование только `ssl_session_cache` без билетов сессий приводит к тому, что при перезапуске рабочего процесса или рестарте демона все клиенты вынуждены проходить полное рукопожатие.
5. **TLS False Start в современных окружениях:** В стеках на базе TLS 1.3 директивы или тюнинг TLS False Start больше не имеют практического смысла, так как штатное рукопожатие TLS 1.3 завершается за 1 RTT без компромиссов в безопасности.

---

## 8. Дополнительная информация

- **[Обзор TLS/SSL в Nginx](../Nginx/Security/TLS_SSL/nginx_tls_ssl_overview.md)** — архитектурные уровни TLS, жизненный цикл соединений и базовые параметры.
- **[Глобальные параметры TLS в Nginx](../Nginx/Security/TLS_SSL/nginx_tls_global_parameters.md)** — детальный справочник директив `ssl_*` уровня `http`.
- **[Настройка виртуальных хостов TLS в Nginx](../Nginx/Security/TLS_SSL/nginx_tls_virtual_host_config.md)** — практические сценарии настройки блоков `server`.
- **[Настройка TLS в Angie](../Angie/angie_tls_setup.md)** — нативная поддержка kTLS, ACME, HTTP/3 (QUIC) и eBPF-маршрутизация.
- **[Взаимная аутентификация TLS (mTLS) в Nginx](../Nginx/Security/TLS_SSL/nginx_mtls_configuration.md)** — пошаговое развертывание mTLS с проверкой сертификатов.
- **[Оптимизация TLS для производительности](./web_performance/tls_optimization.md)** — метрики RTT/TTFB, динамический размер записей, бенчмарки и тюнинг сетевого стека.
- **[Протокол TLS — системный обзор](../../Networking/Protocols/tls.md)** — спецификации протоколов TLS 1.2 и TLS 1.3, форматы сообщений и криптография.
- **[SSL/TLS Termination: паттерны и production-сценарии](../../Networking/Protocols/ssl_tls_termination.md)** — архитектурные схемы Edge, Re-encryption и Passthrough.
- **[TLS-шифрование и сертификаты для HTTP](../../Networking/Protocols/HTTP/http_tls_hardening.md)** — hardening конфигураций, cipher suites и HSTS.
- **[Диагностика SSL/TLS сертификатов](../../Security/Tools/ssl_certificate_diagnostics.md)** — отладка цепочек сертификатов, валидация через OpenSSL и анализ ошибок.
