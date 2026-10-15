# Оптимизация TLS для производительности

**Актуально для:** TLS 1.2 / TLS 1.3 (RFC 5246, RFC 8446) / Linux Kernel 5.15+ / 6.x / OpenSSL 3.0+, 3.3+, 3.4+, BoringSSL / Nginx 1.26+, Angie 1.8+ / 1.12.x / HAProxy 2.8+, 3.0+

Фундаментальные основы криптографического протокола и структуры рукопожатия представлены в руководстве [Протокол TLS — системный обзор](../../../Networking/Protocols/tls.md), устройство открытых ключей и центров сертификации — в документе [Инфраструктура открытых ключей (PKI)](../../../Security/Concepts/pki_overview.md), а специфика транспортных протоколов нового поколения — в статье [Протоколы HTTP/2 и HTTP/3 в веб-производительности](./http2_http3.md). Конфигурация виртуальных хостов и параметры безопасности веб-серверов подробно разобраны в статьях [Глобальные параметры TLS в Nginx](../../Nginx/Security/TLS_SSL/nginx_tls_global_parameters.md) и [Настройка TLS в Angie](../../Angie/angie_tls_setup.md).

---

## Определения

**Оптимизация TLS (Transport Layer Security)** — комплекс архитектурных, системных и конфигурационных мер, направленных на минимизацию задержки установки защищенного соединения (Handshake Latency), снижение накладных расходов на процессор (CPU Overhead) и максимизацию пропускной способности при передаче прикладного трафика (Throughput).

**Ключевые метрики производительности TLS:**

- **Handshake RTT (Round Trip Time):** количество сетевых круговых задержек между клиентом и сервером до завершения согласования криптографических параметров и начала передачи первого байта прикладных данных. TLS 1.2 требует 2-RTT, TLS 1.3 — 1-RTT, а режим возобновления сессий 0-RTT позволяет передавать полезную нагрузку в первом же пакете.
- **TTFB (Time To First Byte):** время от момента отправки запроса клиентом до получения первого байта ответа сервера. В HTTPS-трафике задержка TLS-рукопожатия составляет до 30–60% от суммарного значения TTFB при первом обращении клиента.
- **Handshake Size (Размер служебных данных):** суммарный объем данных в байтах, передаваемых на этапе установки сессии (цепочки сертификатов, расширения SNI/ALPN, открытые ключи обмена). Превышение размера рукопожатия над начальным окном перегрузки TCP (`initcwnd`) приводит к вынужденным задержкам передачи.
- **CPS (Connections Per Second):** предельное количество новых TLS-рукопожатий, которое сервер способен обработать в секунду при заданной утилизации CPU. Лимитируется вычислительной сложностью асимметричной криптографии (ECDSA/RSA/PQC).
- **RPS (Requests Per Second):** количество обрабатываемых HTTP-запросов в секунду в рамках уже установленных (keepalive или resumed) TLS-сессий. Лимитируется скоростью симметричного шифрования (AES-GCM, ChaCha20-Poly1305) и системными вызовами ядра.

**Специализированные термины:**

- **Dynamic Record Sizing (Динамический размер записей TLS):** механизм адаптивного изменения размера TLS-кадров (Record Layer). Начальные данные передаются компактными блоками (1.4–4 КБ), помещающимися в стандартный сегмент TCP MSS для ускорения первого рендеринга, а последующий объемный поток объединяется в максимальные блоки по 16 КБ для снижения накладных расходов процессора.
- **kTLS (Kernel TLS):** механизм ядра Linux (начиная с ветки 5.10+ в связке с OpenSSL 3.0+), переносящий операции симметричного шифрования и дешифрования данных TLS (Data Plane) из адресного пространства пользователя в сетевой стек ядра. Обеспечивает прямую передачу зашифрованных страниц памяти из Page Cache в сетевую карту через системный вызов `sendfile(2)` без промежуточного копирования (Zero-Copy).
- **STEK (Session Ticket Encryption Key):** симметричный секретный ключ (48 или 80 байт), используемый сервером для зашифрования и валидации сессионных билетов (Session Tickets, RFC 5077). В многоузловых кластерах синхронизация STEK критически необходима для корректного возобновления сессий между разными физическими серверами.
- **Dual-Certificate Architecture (Архитектура двойных сертификатов):** одновременное подключение к виртуальному хосту сертификатов двух типов — современного компактного ECDSA (P-256) и универсального RSA (2048/3072 бит). Сервер автоматически отдает легковесный ECDSA-сертификат клиентам с поддержкой эллиптических кривых и использует RSA только как fallback для устаревших систем.
- **Certificate Compression (Сжатие сертификатов, RFC 8879):** согласование сжатия цепочек сертификатов на этапе рукопожатия с помощью алгоритмов Zstandard (`zstd`) или Brotli (`br`). Уменьшает размер сообщения `Certificate` на 30–50%, предотвращая фрагментацию пакетов на транспортном уровне.
- **OCSP Stapling (RFC 6066, RFC 6961):** механизм прикрепления подписанного центром сертификации OCSP-ответа о валидности сертификата к серверному ответу `ServerHello`. Избавляет клиента от блокирующего сетевого запроса к OCSP-респондеру центра сертификации (экономия 1–2 RTT).
- **0-RTT Early Data (RFC 8446):** механизм TLS 1.3, позволяющий отправлять прикладной HTTP-запрос вместе с пакетом `ClientHello` при возобновлении сессии. Создает риск атак повторного воспроизведения (Replay Attacks), поэтому в production требует строгой изоляции только для безопасных идемпотентных запросов (GET, HEAD).
- **ALPN (Application-Layer Protocol Negotiation, RFC 7301):** расширение TLS для согласования протокола прикладного уровня (`h2`, `h3`, `http/1.1`) в процессе рукопожатия без дополнительных сетевых раундов.
- **PFS (Perfect Forward Secrecy):** криптографическое свойство, гарантирующее, что компрометация долгосрочного приватного ключа сервера не позволит расшифровать ранее записанный трафик. Достигается использованием эфемерных протоколов обмена ключами (ECDHE).
- **Hybrid PQC (Постквантовая криптография):** комбинированные алгоритмы согласования ключей (например, `X25519MLKEM768`), объединяющие классическую эллиптическую криптографию X25519 и стандартизированный NIST алгоритм ML-KEM-768 (FIPS 203) для защиты от атак отложенной дешифрации «Harvest Now, Decrypt Later».

---

## Архитектура и базовые концепции

### Анатомия задержки TLS-рукопожатия (Handshake Latency)

В глобальных сетях именно круговая сетевая задержка (RTT), а не пропускная способность канала, выступает главным сдерживающим фактором загрузки веб-ресурсов.

```
TLS 1.2 (2-RTT):
Client                                               Server
  | ─── TCP SYN ──────────────────────────────────────> |
  | <── TCP SYN+ACK ─────────────────────────────────── | (1 RTT - TCP)
  | ─── TCP ACK + ClientHello ────────────────────────> |
  | <── ServerHello + Certificate + ServerKeyExchange ─ | (2 RTT - TLS Setup)
  | ─── ClientKeyExchange + [ChangeCipherSpec] + Fin ─> |
  | <── [ChangeCipherSpec] + Finished ───────────────── | (3 RTT - TLS Complete)
  | ─── HTTP GET (Application Data) ──────────────────> |
  | <── HTTP 200 OK ─────────────────────────────────── |

TLS 1.3 Full Handshake (1-RTT):
Client                                               Server
  | ─── TCP SYN ──────────────────────────────────────> |
  | <── TCP SYN+ACK ─────────────────────────────────── | (1 RTT - TCP)
  | ─── TCP ACK + ClientHello [Key Share, ALPN] ──────> |
  | <── ServerHello [Key Share] + EncryptedExt + Cert ─ | (2 RTT - TLS Complete)
  | ─── Finished + HTTP GET (Application Data) ───────> |
  | <── HTTP 200 OK ─────────────────────────────────── |

TLS 1.3 Resumption (0-RTT Early Data):
Client                                               Server
  | ─── TCP SYN ──────────────────────────────────────> |
  | <── TCP SYN+ACK ─────────────────────────────────── | (1 RTT - TCP)
  | ─── TCP ACK + ClientHello [Ticket] + HTTP GET ────> | (0-RTT TLS Data!)
  | <── ServerHello + Finished + HTTP 200 OK ────────── |
```

**Ключевые оптимизации этапа рукопожатия:**
1. **Переход на TLS 1.3:** Сокращает время установки соединения ровно в два раза по сравнению с TLS 1.2 за счет совмещения этапа обмена открытыми ключами Diffie-Hellman с первым же пакетом `ClientHello`.
2. **Устранение блокировки TCP initcwnd:** При установке TCP-соединения размер начального окна перегрузки в Linux по умолчанию равен `initcwnd 10` (примерно 14 600 байт). Если суммарный объем пакетов сервера (`ServerHello`, цепочка сертификатов, OCSP Stapling, параметры шифрования) превышает 14 КБ, передача разбивается на дополнительные сетевые раунды, увеличивая handshake latency еще на 1 RTT.

### Механика Dynamic Record Sizing (Адаптивный размер TLS-записей)

Протокол TLS инкапсулирует данные в блоки — записи (Records) размером до 16 384 байт. Клиент не может расшифровать или передать браузерному движку ни одного байта полезной нагрузки до тех пор, пока запись не получена целиком и для нее не проверена контрольная сумма MAC (или тег аутентификации AEAD).

```
Фиксированный буфер 16 КБ (ssl_buffer_size 16k):
[ 16 KB TLS Record ] ───> Разбивается на 11-12 TCP-пакетов (MSS 1460 B)
Если пакет #3 потерян в сети:
Браузер ожидает ретрансмита ───> Задержка рендеринга всего блока ───> Рост TTFB и LCP!

Динамический буфер (Dynamic Record Sizing / ssl_dyn_rec):
Соединение только открыто (TCP Slow Start):
├── Запись 1: 1369 байт ──> Помещается ровно в 1 TCP-пакет (Мгновенный парсинг HTML!)
├── Запись 2: 1369 байт ──> Помещается ровно в 1 TCP-пакет (Быстрый старт CSS/JS!)
Порог пакетов пройден (TCP окно выросло, риска задержек нет):
└── Запись N: 16 384 байта ──> Максимальная утилизация канала и минимум накладных расходов CPU
```

- В стандартном **Nginx** директива `ssl_buffer_size 4k;` устанавливает компромиссный статический размер записи (4 КБ вместо 16 КБ), что уменьшает задержку доставки первого байта на мобильных сетях.
- В сервере **Angie** доступен встроенный механизм динамического размера буфера (`ssl_dyn_rec`), который автоматически начинает с маленьких записей и увеличивает их по мере заполнения окна TCP.

### Возобновление сессий в распределенной инфраструктуре (Session Resumption)

Повторное полное рукопожатие на каждое новое соединение приводит к паразитной утилизации CPU и дополнительным задержкам. Существует два механизма возобновления сессий:

```
┌────────────────────────────────────────────────────────────────────────┐
│                        Session ID (RFC 5246)                           │
│ - Сервер сохраняет криптографическое состояние в Shared Memory         │
│ - Клиент передает 32-байтный Session ID                                │
│ - Ограничение: сессия привязана к памяти конкретного инстанса сервера   │
└──────────────────────────────────┬─────────────────────────────────────┘
                                   │
┌──────────────────────────────────▼─────────────────────────────────────┐
│                       Session Ticket (RFC 5077)                        │
│ - Сервер шифрует состояние сессии симметричным ключом STEK             │
│ - Зашифрованный тикет хранится на стороне клиента                      │
│ - Сервер не тратит оперативную память на хранение сессий               │
│ - Обязательное условие для кластера: синхронизация STEK между серверами│
└────────────────────────────────────────────────────────────────────────┘
```

**Проблема кластеризации и асимметричной маршрутизации:**
Если перед пулом веб-серверов работает балансировщик L4 (ECMP, IPVS, HAProxy в режиме TCP), повторные запросы клиента попадают на разные серверные ноды. Если серверы генерируют ключи шифрования билетов случайно при старте процесса:
- Запрос возобновления сессии на ноде B с билетом, выданным нодой A, завершится ошибкой расшифровки тикета.
- Сервер выполнит деградацию до полного рукопожатия (Fallback to Full Handshake).
- Результат: потеря преимуществ 0-RTT/1-RTT возобновления, всплески утилизации CPU на воркерах.
- **Решение для SRE:** Централизованная генерация и регулярная ротация файлов ключей STEK с распространением на все узлы кластера.

### Архитектура Kernel TLS (kTLS) и Zero-Copy

В классической схеме веб-сервер считывает статический файл с диска в адресное пространство процесса (user-space), выполняет шифрование библиотекой OpenSSL и отправляет зашифрованный буфер обратно в ядро через системный вызов `write()`:

```
Классический TLS в пространстве пользователя (User-space TLS):
Диск / Page Cache ──(1. Чтение в память)──> User Space (Nginx/OpenSSL)
                                                    │ (2. Шифрование CPU)
Сетевая карта <──(4. DMA-передача)── Socket Buffer <──(3. Копирование в ядро)

Kernel TLS (kTLS) с вызовом sendfile():
Диск / Page Cache ────────────────(1. sendfile zero-copy)────────────────┐
                                                                         ▼
Сетевая карта <──(3. Аппаратный DMA)── [ Ядро Linux: Шифрование AES-NI ]
```

**Механика работы kTLS:**
1. OpenSSL в пользовательском пространстве выполняет только начальное рукопожатие (Handshake) и обмен ключами.
2. После согласования симметричных ключей сокет переводится в режим kTLS с помощью системного вызова `setsockopt(fd, SOL_TLS, TLS_TX, ...)`.
3. Приложение вызывает системный вызов `sendfile(sock, file_fd, ...)`. Ядро Linux считывает страницы памяти напрямую из Page Cache, на лету выполняет симметричное шифрование (AES-GCM-128/256 или ChaCha20-Poly1305) силами процессорных инструкций `AES-NI` и формирует сетевые кадры.
4. Данные не копируются в пространство пользователя, что высвобождает до 25–35% ресурсов процессора и снижает нагрузку на шину памяти при раздаче медиафайлов и статического контента.

### Вычислительная стоимость криптографических примитивов

| Алгоритм | Назначение | Аппаратное ускорение | Влияние на CPU | Размер ключа / подписи | Рекомендация SRE |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **ECDSA (secp256r1)** | Аутентификация | Аппаратные инструкции P-256 | Минимальное (~0.05 мс) | Ключ: 256 бит, Подпись: ~70 байт | **Основной выбор** для всех публичных сервисов |
| **RSA-2048** | Аутентификация | Ограниченное (AVX2/AVX-512) | Высокое (~0.8–1.2 мс) | Ключ: 2048 бит, Подпись: 256 байт | Только как fallback-сертификат для старых клиентов |
| **AES-256-GCM** | Симметричное шифрование | `AES-NI`, `PCLMULQDQ`, ARM CE | Минимальное (до 8–12 ГБ/с на ядро) | Ключ: 256 бит | **Стандарт де-факто** для серверного оборудования x86_64/ARM64 |
| **ChaCha20-Poly1305** | Симметричное шифрование | Векторные инструкции SIMD/NEON | Низкое на процессорах без AES-NI | Ключ: 256 бит | Оптимален для мобильных/встраиваемых платформ без аппаратного AES |
| **X25519** | Обмен ключами (ECDHE) | Скалярное умножение SIMD | Экстремально быстрое (~0.03 мс) | Публичный ключ: 32 байта | Базовая кривая по умолчанию для TLS 1.3 |
| **X25519MLKEM768** | Гибридный обмен PQC | AVX-512 / ARM Neon | Умеренное (+15–20% к CPS) | Публичный ключ: ~1200 байт | Внедрение для защиты от атак отложенного анализа |

---

## Практические сценарии и конфигурация

### Сценарий 1: Высокопроизводительная конфигурация Nginx / Angie для минимального TTFB

Конфигурация оптимизирует все этапы установки соединения: активацию TLS 1.3, гибридные двойные сертификаты (ECDSA + RSA), динамические буферы, надежное кэширование сессий и асинхронный OCSP Stapling.

#### Глобальный уровень (`/etc/nginx/nginx.conf` или `/etc/angie/angie.conf`)

```nginx
http {
    # Включение kTLS на уровне ядра ОС и библиотеки OpenSSL
    ssl_conf_command Options +KTLS;

    # Кэш сессий в разделяемой памяти: 50 МБ (~200 000 сессий)
    ssl_session_cache shared:SSL:50m;
    ssl_session_timeout 1d;

    # Включение билетов сессий с распределенными ключами
    ssl_session_tickets on;
    ssl_session_ticket_key /etc/nginx/ssl/ticket_current.key;
    ssl_session_ticket_key /etc/nginx/ssl/ticket_previous.key;

    # Современные протоколы: полный отказ от TLS 1.0 и TLS 1.1
    ssl_protocols TLSv1.2 TLSv1.3;

    # Приоритет клиента для TLS 1.3 (выбор эффективного аппаратного шифра)
    ssl_prefer_server_ciphers off;

    # Оптимальные наборы шифров для TLS 1.2 с поддержкой PFS
    ssl_ciphers 'ECDHE-ECDSA-AES256-GCM-SHA384:ECDHE-RSA-AES256-GCM-SHA384:ECDHE-ECDSA-CHACHA20-POLY1305:ECDHE-RSA-CHACHA20-POLY1305:ECDHE-ECDSA-AES128-GCM-SHA256:ECDHE-RSA-AES128-GCM-SHA256';

    # Быстрые эллиптические кривые (X25519 в приоритете)
    ssl_ecdh_curve X25519:secp384r1;

    # Оптимизация размера TLS-записи для быстрого TTFB
    # В Nginx: статический размер буфера 4 КБ
    ssl_buffer_size 4k;
    
    # В сервере Angie: динамический адаптивный буфер (раскомментировать при использовании Angie)
    # ssl_dyn_rec on;
    # ssl_dyn_rec_size_lo 1369;
    # ssl_dyn_rec_size_hi 4096;
    # ssl_dyn_rec_threshold 40;

    # Автономный OCSP Stapling с валидацией цепочки
    ssl_stapling on;
    ssl_stapling_verify on;
    resolver 127.0.0.1 1.1.1.1 valid=300s ipv6=off;
    resolver_timeout 3s;

    # Zero-copy передача статики
    sendfile on;
    tcp_nopush on;
    tcp_nodelay on;
}
```

#### Уровень виртуального хоста (`/etc/nginx/conf.d/example.com.conf`)

```nginx
server {
    listen 443 ssl http2;
    listen [::]:443 ssl http2;
    server_name example.com www.example.com;

    # 1. Основной высокопроизводительный сертификат ECDSA (P-256)
    ssl_certificate     /etc/ssl/certs/example.com_ecc.fullchain.pem;
    ssl_certificate_key /etc/ssl/private/example.com_ecc.key;

    # 2. Fallback-сертификат RSA-2048 для устаревших клиентов
    ssl_certificate     /etc/ssl/certs/example.com_rsa.fullchain.pem;
    ssl_certificate_key /etc/ssl/private/example.com_rsa.key;

    # Файл доверенных корневых и промежуточных сертификатов для OCSP Stapling
    ssl_trusted_certificate /etc/ssl/certs/example.com_trusted.pem;

    # Включение 0-RTT Early Data (TLS 1.3)
    ssl_early_data on;

    # Защита от Replay-атак: передача статуса в upstream
    location / {
        proxy_pass http://backend_pool;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;

        # Передача заголовка Early-Data приложению
        proxy_set_header Early-Data $ssl_early_data;

        # Блокировка потенциально опасных неидемпотентных запросов при 0-RTT
        if ($ssl_early_data = "1") {
            set $early_risk "${request_method}";
        }
        if ($early_risk ~* "^(POST|PUT|DELETE|PATCH)$") {
            return 425; # 425 Too Early (клиент обязан повторить запрос после полного рукопожатия)
        }
    }
}
```

**Валидация примененных настроек:**
```bash
# 1. Проверка синтаксиса перед перезагрузкой
nginx -t
# → nginx: the configuration file /etc/nginx/nginx.conf syntax is ok
# → nginx: configuration file /etc/nginx/nginx.conf test is successful

# 2. Перезагрузка сервиса без разрыва соединений
systemctl reload nginx

# 3. Верификация активного протокола, шифра и статуса OCSP Stapling
echo | openssl s_client -connect example.com:443 -servername example.com -status 2>&1 | \
  grep -E "Protocol|Cipher|OCSP Response Status"
# → Protocol  : TLSv1.3
# → Cipher    : TLS_AES_256_GCM_SHA384
# → OCSP Response Status: successful (0x0)
```

---

### Сценарий 2: Централизованная ротация Session Ticket ключей (STEK) в кластере

Для предотвращения деградации сессий в горизонтально масштабируемом пуле серверов настраивается автоматизированный пайплайн генерации и ротации STEK-ключей.

```
┌────────────────────────────────────────────────────────┐
│                   Контрольный узел                     │
│  Генерация нового 80-байтного ключа каждые 12 часов    │
│  openssl rand 80 > /var/run/stek/ticket_new.key        │
└──────────────────────────┬─────────────────────────────┘
                           │ Безопасный транспорт (Ansible / SCP / SSH)
            ┌──────────────┴──────────────┐
            ▼                             ▼
┌───────────────────────────┐ ┌───────────────────────────┐
│ Серверная нода #01        │ │ Серверная нода #02        │
│ ticket_current.key (новый)│ │ ticket_current.key (новый)│
│ ticket_previous.key (стар)│ │ ticket_previous.key (стар)│
│ systemctl reload nginx    │ │ systemctl reload nginx    │
└───────────────────────────┘ └───────────────────────────┘
```

#### Скрипт автоматической ротации (`/usr/local/bin/rotate_stek_keys.sh`)

```bash
#!/usr/bin/env bash
set -euo pipefail

SSL_DIR="/etc/nginx/ssl"
CURRENT_KEY="${SSL_DIR}/ticket_current.key"
PREVIOUS_KEY="${SSL_DIR}/ticket_previous.key"
BACKUP_KEY="${SSL_DIR}/ticket_backup.key"

# 1. Проверка наличия текущего ключа; если отсутствует — генерируем базовый
if [[ ! -f "${CURRENT_KEY}" ]]; then
    echo "[INFO] Инициализация первичного STEK-ключа..."
    openssl rand 80 > "${CURRENT_KEY}"
    chmod 600 "${CURRENT_KEY}"
fi

# 2. Ротация: текущий становится предыдущим, генерируется новый 80-байтный ключ
# 80 байт для OpenSSL 3: 16 байт имя ключа + 32 байта шифрование AES-256 + 32 байта HMAC-SHA256
if [[ -f "${PREVIOUS_KEY}" ]]; then
    cp -f "${PREVIOUS_KEY}" "${BACKUP_KEY}"
fi

cp -f "${CURRENT_KEY}" "${PREVIOUS_KEY}"
openssl rand 80 > "${CURRENT_KEY}.tmp"
chmod 600 "${CURRENT_KEY}.tmp"
mv -f "${CURRENT_KEY}.tmp" "${CURRENT_KEY}"

# 3. Валидация и перезагрузка веб-сервера
if nginx -t > /dev/null 2>&1; then
    systemctl reload nginx
    echo "[SUCCESS] Ключи STEK успешно обновлены и Nginx перезагружен."
else
    echo "[CRITICAL] Ошибка конфигурации Nginx! Откат ключей..."
    cp -f "${PREVIOUS_KEY}" "${CURRENT_KEY}"
    systemctl reload nginx
    exit 1
fi
```

#### Проверка корректности работы Session Resumption

```bash
# Тест повторного использования сессии (Session Resumption)
echo | openssl s_client -connect example.com:443 -servername example.com -reconnect 2>&1 | \
  grep -E "Reused|New, TLSv1.3"
# → Reused, TLSv1.3, Cipher is TLS_AES_256_GCM_SHA384
```

---

### Сценарий 3: Развертывание и валидация Kernel TLS (kTLS) в Linux

Перенос криптографических операций в ядро операционной системы для раздачи объемных статических ассетов и медиаданных.

#### 1. Проверка поддержки ядром и загрузка модуля

```bash
# Проверка наличия опций компиляции в текущем ядре
grep -E "CONFIG_TLS(=| )" /boot/config-$(uname -r)
# → CONFIG_TLS=m
# → CONFIG_TLS_DEVICE=y

# Ручная загрузка модуля ядра
modprobe tls

# Проверка факта загрузки модуля
lsmod | grep tls
# → tls                   131072  0

# Фиксация автозагрузки модуля при старте ОС
echo "tls" > /etc/modules-load.d/tls.conf
```

#### 2. Проверка аппаратного ускорения сетевой карты (kTLSO)

Если сервер оснащен высокоскоростными сетевыми адаптерами (например, Mellanox ConnectX-6 или Chelsio) с поддержкой TLS Device Offload:

```bash
# Проверка доступности аппаратного оффлоада
ethtool -k eth0 | grep tls
# → tls-hw-tx-offload: on
# → tls-hw-rx-offload: on

# Включение оффлоада в случае статуса off
ethtool -K eth0 tls-hw-tx-offload on tls-hw-rx-offload on
```

#### 3. Активация kTLS в конфигурации OpenSSL

В файле `/etc/ssl/openssl.cnf` в секции `system_default_sect`:

```ini
[system_default_sect]
CipherString = DEFAULT:@SECLEVEL=2
Options = +KTLS
```

#### 4. Диагностика активности kTLS на работающем сокете

```bash
# Проверка сетевых сокетов с флагом tls через утилиту ss
ss -ti '( sport = :443 )' | grep -i tls
# → tls: tx/rx version: TLSv1.3 cipher: AES-GCM-256
```

---

### Сценарий 4: Оптимизация TLS-терминации на балансировщике HAProxy

В архитектурах, где HAProxy используется в качестве фронтенд-терминатора TLS перед пулом бэкендов, ключевое значение имеет тюнинг буферов и кэша сессий.

#### Конфигурация `/etc/haproxy/haproxy.cfg`

```haproxy
global
    # Ограничение размера записи TLS для снижения задержки первого байта
    tune.ssl.maxrecord 1400

    # Размер кэша сессий TLS (количество записей сессий)
    tune.ssl.cachesize 200000

    # Время жизни сессии в кэше (24 часа)
    tune.ssl.lifetime 86400

    # Размер параметров Диффи-Хеллмана
    tune.ssl.default-dh-param 2048

    # Базовые криптографические параметры
    ssl-default-bind-options ssl-min-ver TLSv1.2 no-tls-tickets
    ssl-default-bind-ciphersuites TLS_AES_256_GCM_SHA384:TLS_CHACHA20_POLY1305_SHA256:TLS_AES_128_GCM_SHA256
    ssl-default-bind-ciphers ECDHE-ECDSA-AES256-GCM-SHA384:ECDHE-RSA-AES256-GCM-SHA384:ECDHE-ECDSA-CHACHA20-POLY1305

frontend https_front
    mode http
    # Двойные сертификаты: HAProxy автоматически выбирает crt.ecdsa или crt.rsa
    bind :443 ssl crt /etc/haproxy/certs/example.com.pem alpn h2,http/1.1
    
    http-response set-header Strict-Transport-Security "max-age=31536000; includeSubDomains; preload"
    default_backend app_servers

backend app_servers
    mode http
    balance roundrobin
    server node1 10.0.1.11:8080 check
    server node2 10.0.1.12:8080 check
```

**Диагностика кэша HAProxy через Runtime API:**
```bash
echo "show info" | socat /var/run/haproxy.sock stdio | grep -i ssl
# → SslBackendKeyRate: 0
# → SslFrontendKeyRate: 42
# → SslRate: 120
# → SslCacheLookups: 450210
# → SslCacheMisses: 89100
```

---

### Сценарий 5: Мониторинг производительности TLS и Alertmanager для SRE

Контроль задержки рукопожатия и сроков действия сертификатов в стеке Prometheus + Blackbox Exporter.

#### 1. Конфигурация Blackbox Exporter (`/etc/prometheus/blackbox.yml`)

```yaml
modules:
  https_tls_opt:
    prober: http
    timeout: 5s
    http:
      valid_http_versions: ["HTTP/1.1", "HTTP/2"]
      valid_status_codes: [200, 301, 302]
      method: GET
      fail_if_ssl: false
      fail_if_not_ssl: true
      tls_config:
        insecure_skip_verify: false
        min_version: "TLS12"
```

#### 2. Правила алертов Prometheus Alertmanager (`/etc/prometheus/rules/tls_alerts.yml`)

```yaml
groups:
  - name: TLSPerformanceAndExpiry
    rules:
      - alert: TLSCertificateExpiringSoon
        expr: (probe_ssl_earliest_cert_expiry - time()) / 86400 < 14
        for: 1h
        labels:
          severity: warning
        annotations:
          summary: "Сертификат на хосте {{ $labels.instance }} истекает менее чем через 14 дней."
          description: "Осталось дней: {{ $value | printf \"%.1f\" }}. Проверьте автоматизацию ACME/Certbot."

      - alert: TLSCertificateCriticalExpiry
        expr: (probe_ssl_earliest_cert_expiry - time()) / 86400 < 3
        for: 15m
        labels:
          severity: critical
        annotations:
          summary: "Критический срок действия сертификата на хосте {{ $labels.instance }}!"
          description: "Осталось менее 3 дней ({{ $value | printf \"%.1f\" }} дн.). Необходима срочная ручная ротация."

      - alert: TLSHighHandshakeLatency
        expr: probe_tls_handshake_seconds > 0.150
        for: 10m
        labels:
          severity: warning
        annotations:
          summary: "Высокая задержка TLS-рукопожатия на {{ $labels.instance }}"
          description: "Задержка TLS Handshake превышает 150 мс (текущее: {{ $value | printf \"%.3f\" }} с). Проверьте OCSP Stapling и нагрузку на CPU."

      - alert: TLSOCSPStaplingFailure
        expr: probe_ssl_ocsp_stapled == 0
        for: 30m
        labels:
          severity: warning
        annotations:
          summary: "OCSP Stapling не активен на {{ $labels.instance }}"
          description: "Сервер перестал отдавать OCSP-ответ. Проверьте доступность резолвера и статус OCSP-респондера центра сертификации."
```

---

## Операции и команды

### Сводная таблица диагностических команд

| Задача | Утилита / Команда | Диагностический вывод / Ожидаемый результат |
| :--- | :--- | :--- |
| **Детализация рукопожатия** | `openssl s_client -connect host:443 -servername host -status -alpn h2` | Проверка протокола, шифра, цепочки и статуса OCSP |
| **Измерение таймингов фаз** | `curl -o /dev/null -s -w "@curl-format.txt" https://host/` | Декомпозиция DNS, TCP, TLS (`time_appconnect`) и TTFB |
| **Проверка kTLS сокета** | `ss -ti '( sport = :443 )'` | Наличие атрибута `tls: tx/rx` в выводе параметров TCP |
| **Тест Session Resumption** | `openssl s_client -connect host:443 -reconnect 3` | Строка `Reused, session id reused` или `New, TLSv1.3` |
| **Тестирование 0-RTT** | `openssl s_client -connect host:443 -early_data data.txt` | Подтверждение `Early data was accepted` |
| **Бенчмарк криптографии** | `openssl speed -evp aes-256-gcm chacha20-poly1305` | Сравнение пропускной способности шифров на CPU (Байт/с) |
| **Проверка цепочки X.509** | `openssl verify -CAfile chain.pem server.crt` | Статус `server.crt: OK` |

---

### Детальная диагностика параметров и таймингов

#### 1. Декомпозиция времени сетевого соединения через `curl`

Создайте шаблон форматирования `/tmp/curl_timing.txt`:

```text
       DNS Lookup:  %{time_namelookup}s\n
      TCP Connect:  %{time_connect}s\n
    TLS Handshake:  %{time_appconnect}s\n
   Server Process:  %{time_starttransfer}s\n
       Total Time:  %{time_total}s\n
```

Выполнение замера:

```bash
curl -o /dev/null -s -w "@/tmp/curl_timing.txt" https://example.com/
# →        DNS Lookup:  0.008s
# →       TCP Connect:  0.024s
# →     TLS Handshake:  0.052s
# →    Server Process:  0.098s
# →        Total Time:  0.134s
```
*Интерпретация SRE:* Чистое время TLS-рукопожатия равно `time_appconnect` минус `time_connect` ($0.052 - 0.024 = 0.028$ с). Если эта дельта превышает 1 RTT, сервер не использует TLS 1.3 или задерживает ответ из-за генерации ключей / блокировки OCSP.

#### 2. Проверка производительности шифрования на сервере

```bash
# Бенчмарк аппаратных инструкций AES-NI против ChaCha20
openssl speed -evp aes-256-gcm chacha20-poly1305
# → The 'numbers' are in 1000s of bytes per second processed.
# → type             16 bytes     64 bytes    256 bytes   1024 bytes   8192 bytes  16384 bytes
# → aes-256-gcm     1245000k     3420000k     6890000k     9810000k    11200000k    11450000k
# → chacha20-poly   450000k      890000k     1820000k     2450000k     2890000k     2910000k
```
*Вывод:* На оборудовании с поддержкой `AES-NI` шифр `AES-256-GCM` обрабатывает более 11 ГБ/с на ядро, опережая программный `ChaCha20` почти в 4 раза.

#### 3. Нагрузочный бенчмарк TLS Handshake CPS через `h2load`

```bash
# Проверка предельного количества рукопожатий в секунду без повторного использования сессий
h2load -n 10000 -c 100 -m 1 --h1 https://example.com/
# → finished in 2.12s, 4716.98 req/s, 4716.98 conn/s
# → time for handshake: min 18.2ms, max 84.1ms, mean 21.2ms
```

---

## Диагностика ошибок и устранение неисправностей

### Матрица инцидентов и проблем производительности TLS

| Симптом / Ошибка | Первопричина | Метод диагностики | Способ устранения |
| :--- | :--- | :--- | :--- |
| **Высокий Handshake RTT (>150 мс)** | Отсутствие OCSP Stapling; сервер запрашивает внешний CA при каждом соединении | `curl -w "%{time_appconnect}s"` и `openssl s_client -status` | Включить `ssl_stapling on;`, указать локальный резолвер `resolver 127.0.0.1 valid=300s;` |
| **Деградация до полного рукопожатия в кластере** | Рассинхронизация ключей STEK (`ssl_session_ticket_key`) между нодами | Проверить чексуммы файлов ключей: `sha256sum /etc/nginx/ssl/ticket_*.key` на всех хостах | Настроить единый скрипт ротации ключей STEK с рассылкой по кластеру |
| **Всплеск нагрузки на CPU при атаке/трафике** | Доминирование медленных RSA-2048/4096 рукопожатий | Анализ вызовов: `perf top` (функции `rsa_pkcs1_sign` или `bn_mul`) | Перевести виртуальные хосты на сертификаты ECDSA (P-256); включить сессионный кэш |
| **Ошибка 425 Too Early** | Клиент отправил неидемпотентный запрос в 0-RTT Early Data, отклоненный сервером | Проверка переменной `$ssl_early_data` в `access_log` | Ограничить 0-RTT на клиенте только для запросов GET/HEAD; настроить приложение |
| **Падение RPS при раздаче статики с kTLS** | Динамическое сжатие (gzip/brotli on the fly) отключает kTLS и `sendfile` | Проверка флагов сокета: `ss -ti` не показывает `tls` | Использовать статическое предварительное сжатие (`gzip_static on;`, `brotli_static on;`) |
| **Лог: `ssl_stapling: no data`** | Локальный DNS-резолвер не отвечает или в сертификате отсутствует URL OCSP (AIA) | `openssl x509 -in cert.pem -noout -ocsp_uri` | Проверить наличие секции AIA в сертификате; скорректировать директиву `resolver` |
| **`verify error:num=20:unable to get local issuer certificate`** | Неполная цепочка сертификатов в `ssl_certificate` (пропущен промежуточный CA) | `openssl s_client -connect host:443 -showcerts` | Объединить конечный сертификат и промежуточные CA в единый `fullchain.pem` |
| **`alert handshake failure (40)`** | Несовпадение поддерживаемых наборов шифров или версий TLS между клиентом и сервером | `openssl ciphers -v` на сервере и `ssldump` трафика | Добавить в `ssl_ciphers` шифры AES128-GCM и проверить поддержку TLSv1.2 |
| **Рост Handshake Size из-за PQC** | Фрагментация TCP-пакетов при передаче больших открытых ключей ML-KEM-768 | `tcpdump -nn -i eth0 port 443` — проверка флагов фрагментации IP | Включить Certificate Compression (RFC 8879); увеличить MTU в локальных сегментах |

---

## Рекомендации и лучшие практики

### Чеклист SRE / SysAdmin по TLS-оптимизации

#### 1. Базовые архитектурные политики
- [ ] **Отказ от устаревших протоколов:** Запретить TLS 1.0 и TLS 1.1 на уровне всех виртуальных хостов. Использовать только TLS 1.2 и TLS 1.3.
- [ ] **ECDSA как стандарт:** Выпускать первичные сертификаты на эллиптических кривых P-256 (ECDSA). Подключать RSA-2048 только при подтвержденной потребности поддержки устаревших клиентов.
- [ ] **PFS (Perfect Forward Secrecy):** Использовать исключительно эфемерные кривые Диффи-Хеллмана (`X25519`, `secp384r1`).

#### 2. Оптимизация сети и операционной системы
- [ ] **Активация kTLS:** Загрузить модуль ядра `tls` и разрешить `+KTLS` в конфигурации OpenSSL и веб-сервера для статических нагрузок.
- [ ] **Тюнинг буфера записей:** Установить `ssl_buffer_size 4k;` в Nginx или настроить `ssl_dyn_rec on;` в сервере Angie.
- [ ] **Автономный OCSP Stapling:** Настроить `ssl_stapling on;` и `ssl_stapling_verify on;` с указанием локального надежного DNS-резолвера со временем ответа < 5 мс.
- [ ] **Сжатие статики:** Сочетать kTLS с предварительно сжатыми файлами (`gzip_static on;`, `brotli_static on;`, `zstd_static on;`) для исключения накладных расходов CPU на динамическое сжатие.

#### 3. Кластерные регламенты и безопасность
- [ ] **Синхронизация STEK:** Организовать защищенную репликацию ключей шифрования сессионных билетов между всеми нодами кластера с ротацией каждые 12–24 часа.
- [ ] **Изоляция 0-RTT:** Настроить проверку заголовка `$ssl_early_data` с принудительным возвратом HTTP 425 для неидемпотентных запросов (POST, PUT, DELETE).
- [ ] **Zero-Downtime Reload:** Все изменения криптографических параметров применять исключительно через `systemctl reload` после валидации конфигурации (`nginx -t`).

---

### Анализ влияния инструментов диагностики на Production

| Инструмент | Утилизация CPU | Нагрузка на I/O диска | Влияние на сеть | Рекомендация к применению |
| :--- | :--- | :--- | :--- | :--- |
| `openssl s_client` | Пренебрежимо мала | Отсутствует | 1 тестовое соединение | Безопасно для регулярного мониторинга и ручной проверки |
| `curl -w` тайминг | Пренебрежимо мала | Отсутствует | 1 стандартный HTTP-запрос | Рекомендуется для непрерывных health-check проверок |
| `openssl speed` | **100% одного ядра CPU** | Отсутствует | Отсутствует | Запускать **только** на staging-нодах или в регламентные окна обслуживания |
| `h2load` / `wrk` | Высокая на клиенте и сервере | Низкая | Высокая утилизация канала | Строго в рамках контролируемого нагрузочного тестирования |
| `tcpdump / ssldump` | Умеренная (до 5–10% CPU) | Высокая при записи в файл | Возможны потери пакетов при перегрузке | Применять кратковременно с точными фильтрами по IP/порту |
| `error_log debug` | **Критическая (+50-80% CPU)** | **Экстремальный I/O** | Замедление обработки запросов | **Запрещено** на production; использовать уровень `warn` или `info` |

---

## Дополнительная информация

### См. также (Внутренние материалы базы знаний)

- **[Протокол TLS — системный обзор](../../../Networking/Protocols/tls.md)** — архитектура рукопожатия, шифронаборы, математические основы криптографии и формат X.509.
- **[Инфраструктура открытых ключей (PKI)](../../../Security/Concepts/pki_overview.md)** — центры сертификации, списки отзыва CRL, протокол OCSP и выпуск сертификатов.
- **[Протоколы HTTP/2 и HTTP/3 в веб-производительности](./http2_http3.md)** — интеграция TLS с транспортом QUIC, ALPN-согласование, устранение Head-of-Line blocking.
- **[Глобальные параметры TLS в Nginx](../../Nginx/Security/TLS_SSL/nginx_tls_global_parameters.md)** — полный справочник директив уровня `http` и организация shared memory.
- **[Настройка TLS в Angie](../../Angie/angie_tls_setup.md)** — реализация `quic_bpf`, in-memory кэш сертификатов и встроенный ACME-модуль.
- **[Диагностика TLS/SSL в Nginx](../../Nginx/Security/TLS_SSL/nginx_tls_troubleshooting_and_compatibility.md)** — регламенты локализации инцидентов и матрица совместимости клиентов.
- **[Компрессия контента на веб-сервере](./server_compression.md)** — взаимодействие статического сжатия с механизмом Zero-Copy и kTLS.
- **[Аппаратный оффлоад сетевого стека Linux](../../../Linux/Networking/Concepts/offloading.md)** — архитектура kTLSO, segmentation offload и драйверы NIC.
- **[Развертывание без простоя сервиса](./zero_downtime_deployment.md)** — архитектура бесшовной перезагрузки воркеров без сброса активных сессий.
- **[Структурированное логирование для производительности](./structured_logging_for_performance.md)** — агрегация метрик TLS handshake latency и кодов ответов в логах.

### Нормативные документы и спецификации

- **RFC 8446:** The Transport Layer Security (TLS) Protocol Version 1.3
- **RFC 5246:** The Transport Layer Security (TLS) Protocol Version 1.2
- **RFC 6066:** Transport Layer Security (TLS) Extensions: Extension Definitions (SNI, OCSP Stapling)
- **RFC 5077:** Transport Layer Security (TLS) Session Resumption without Server-Side State (Session Tickets)
- **RFC 8879:** TLS Certificate Compression (Zstandard, Brotli)
- **RFC 7301:** Transport Layer Security (TLS) Application-Layer Protocol Negotiation Extension (ALPN)
- **RFC 8446 / Early Data:** 0-RTT Considerations and Replay Mitigation in TLS 1.3
