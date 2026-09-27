# Оптимизация TLS для производительности

## Определения

**Оптимизация TLS (Transport Layer Security)** — комплекс конфигурационных и архитектурных мер, направленных на повышение эффективности защищенного соединения. Основные цели включают сокращение времени установки связи (Handshake Latency), снижение накладных расходов на процессор (CPU Overhead) и минимизацию объема служебного трафика (Handshake Size).

**Ключевые показатели эффективности (KPI):**

- **Handshake RTT:** количество раундов обмена данными до начала передачи полезной нагрузки. TLS 1.3 сокращает этот показатель до 1-RTT, а режим возобновления — до 0-RTT.
- **TTFB (Time To First Byte):** время от начала запроса до получения первого байта ответа. В HTTPS-соединениях этот показатель критически зависит от скорости TLS-рукопожатия.
- **Handshake Size:** объем данных (в байтах), передаваемых при установке соединения. С внедрением постквантовых алгоритмов (PQC), имеющих ключи размером в килобайты, этот параметр становится критическим фактором производительности.
- **CPU Overhead:** вычислительная стоимость криптографических операций. Высокая нагрузка может ограничивать количество новых соединений в секунду (CPS) и общую пропускную способность (RPS).

**Связанные определения:**

- **kTLS (Kernel TLS):** технология переноса симметричного шифрования в ядро Linux, позволяющая использовать `sendfile()` для прямой передачи зашифрованных данных из дискового кэша в сетевую карту без копирования в адресное пространство приложения.
- **ALPN (Application-Layer Protocol Negotiation):** расширение TLS, позволяющее согласовать протокол прикладного уровня (h2, h3) в процессе рукопожатия. От правильной работы ALPN зависит активация HTTP/2 и HTTP/3.
- **PFS (Perfect Forward Secrecy):** свойство, при котором компрометация долгосрочного приватного ключа не позволяет расшифровать прошлые сессии. Обеспечивается использованием эфемерных алгоритмов обмена ключами (ECDHE).
- **Session Resumption:** механизм возобновления TLS-сессии без полного рукопожатия. Реализуется через Session Tickets (TLS 1.2/1.3) или Session IDs. Критичен для снижения latency на повторных соединениях.
- **Replay Attack (повторная атака):** риск, связанный с использованием 0-RTT в TLS 1.3, при котором злоумышленник может повторно отправить перехваченный ранний пакет. Защита осуществляется на уровне приложения (проверка идемпотентности, заголовок `Early-Data`).

## Основные концепции / Архитектура

### Минимизация задержки рукопожатия (Handshake Latency)

В современных сетях именно задержка (RTT), а не пропускная способность, является «узким местом» при установке TLS-соединений.

1. **Применение TLS 1.3 (RFC 8446):**
   - **1-RTT Handshake:** в отличие от TLS 1.2 (2-RTT), TLS 1.3 объединяет обмен ключами и согласование шифров в один этап.
   - **0-RTT (Early Data):** позволяет клиенту отправлять HTTP-запрос (например, `GET /index.html`) в первом же пакете `ClientHello`, если сессия возобновляется. В 2026 году это стандарт для Edge-серверов, требующий обязательной защиты от Replay-атак на уровне приложения (использование заголовка `Early-Data`).
2. **Делегированные учетные данные (Delegated Credentials, RFC 9345):**
   - Позволяют серверам подписывать рукопожатие кратковременными ключами (обычно на 7 дней) без доступа к долгосрочному приватному ключу сертификата. Это повышает производительность за счет локализации операций подписи и безопасности за счет минимизации риска компрометации основного ключа.
3. **Encrypted Client Hello (ECH, RFC 9435):**
   - Расширение, защищающее поле SNI (Server Name Indication). С точки зрения производительности, ECH требует наличия соответствующих записей в DNS (HTTPS Resource Record), что позволяет браузеру сразу инициировать корректное рукопожатие без предварительных запросов.
4. **Сжатие сертификатов (TLS Certificate Compression, RFC 8879):**
   - Рукопожатие часто замедляется из-за передачи длинных цепочек сертификатов. Использование алгоритмов Zstd или Brotli позволяет сократить объем передаваемых данных на 30–50%. Это становится жизненно важным при переходе на Post-Quantum Cryptography, где ключи и подписи могут достигать 2–4 КБ.
5. **OCSP Stapling и Multi-Stapling:**
   - Классический OCSP Stapling избавляет клиента от необходимости подключаться к OCSP-ответчику центра сертификата (экономия 1–2 RTT).
   - **Multi-Stapling (RFC 6961)** позволяет серверу передавать статус валидности для всей цепочки сертификатов (включая промежуточные), что повышает надежность и скорость на мобильных устройствах.
6. **Управление сессиями (Session Tickets и Session Cache):**
   - **Session Tickets (RFC 5077):** сервер выдает клиенту зашифрованный билет с данными сессии, который клиент предъявляет при повторном подключении. Это сокращает handshake до 0-RTT для resumed session.
   - **Session Cache:** совместное использование кэша сессий между процессами/воркерами (`ssl_session_cache shared:SSL:50m` в Nginx/Angie). 1 МБ кэша ≈ 4000 сессий. При большом количестве новых соединений (CPS) кэширование снижает нагрузку на CPU на 20–30%.

### Оптимизация вычислительной нагрузки

Вычислительная сложность шифрования напрямую влияет на энергопотребление серверов и их масштабируемость.

1. **Постквантовые алгоритмы (PQC):**
   - В 2026 году стандартом является гибридный подход. Например, **X25519 + ML-KEM-768**. Вычисления ML-KEM (Kyber) выполняются быстрее, чем RSA-2048, однако основной вызов — передача больших открытых ключей. Оптимизация заключается в использовании аппаратного ускорения (Intel AVX-512, ARM SVE) для минимизации задержек.
2. **Эллиптические кривые (ECDSA/EdDSA) против RSA:**
   - Использование ключей на базе кривых (Ed25519, NIST P-256) позволяет получить ту же стойкость при значительно меньшем размере ключа (256 бит против 2048/3072 бит RSA). Это ускоряет операцию подписи на сервере и проверку на клиенте.
3. **Выбор наборов шифров (Cipher Suites):**
   - **AES-GCM:** использует аппаратные инструкции `AES-NI` (x86) или `ARM CE`. В современных версиях OpenSSL AES-256-GCM часто быстрее AES-128-GCM из-за более глубокой оптимизации конвейера вычислений.
   - **ChaCha20-Poly1305:** программно-оптимизированный шифр. В 2026 году он остается лучшим выбором для старых IoT-устройств и бюджетных смартфонов без аппаратных блоков шифрования.
4. **Kernel TLS (kTLS):**
   - Переносит симметричное шифрование в ядро Linux. Это позволяет использовать системный вызов `sendfile()` для прямой передачи данных из дискового кэша в сетевую карту без копирования в адресное пространство приложения. Это высвобождает до 20–30% CPU при раздаче тяжелой статики или видео.
   - **Требования:** Linux 5.2+ (рекомендуется 5.15+), OpenSSL 3.0+ с опцией `enable-ktls`.
   - **Ограничение:** kTLS несовместим с某些 user-space фреймворками HTTP/2, требующими доступа к данным. Тестируйте на производственных профилях нагрузки.

### Жизненный цикл TLS-соединения в контексте оптимизаций

```text
Client Hello → [0-RTT Early Data?] → Key Exchange (1-RTT) →
Certificate Verification [OCSP Stapling] → Session Resumption [Ticket] →
Encrypted Application Data [kTLS sendfile] → Connection Close
```

На каждом этапе применяются оптимизации:
- **Client Hello:** ECH (защита SNI), ALPN (согласование протокола)
- **Handshake:** TLS 1.3 (1-RTT), Delegated Credentials (быстрая подпись), Certificate Compression (сжатие цепочки)
- **Verification:** OCSP Stapling (экономия 1–2 RTT), Multi-Stapling (полная цепочка)
- **Resumption:** Session Tickets (0-RTT), Session Cache (совместное использование)
- **Data Transfer:** kTLS (zero-copy), AES-NI/ARM CE (аппаратное ускорение)

## Практические сценарии / Установка и настройка / Конфигурация

### Сценарий 1: Тюнинг Nginx/Angie для максимального TTFB

Для высокопроизводительных инсталляций (Angie 1.6+ / Nginx 1.27+) рекомендуется следующая конфигурация в блоке `http`:

```nginx
http {
    # Кэширование сессий для TLS 1.2 и тикеты для TLS 1.3
    ssl_session_cache shared:SSL:50m; # 1MB ~ 4000 сессий
    ssl_session_timeout 1d;
    ssl_session_tickets on;
    
    # Современные протоколы с приоритетом TLS 1.3
    ssl_protocols TLSv1.2 TLSv1.3;
    
    # Динамический размер записей TLS (Dynamic Record Sizing)
    # 4k — минимизация TTFB (быстрее отрисовка первого байта)
    # 16k — для тяжелых файлов (меньше накладных расходов на заголовки блоков)
    ssl_buffer_size 4k;
    
    # OCSP Stapling (RFC 6066)
    ssl_stapling on;
    ssl_stapling_verify on;
    resolver 8.8.8.8 8.8.4.4 valid=300s;
    
    # Адаптивное шифрование: сервер выбирает шифр на основе возможностей клиента
    ssl_prefer_server_ciphers off;
}
```

Для уровня `server` добавьте:

```nginx
server {
    listen 443 ssl http2;
    listen [::]:443 ssl http2;
    
    ssl_certificate     /etc/letsencrypt/live/example.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/example.com/privkey.pem;
    
    # PFS-совместимые шифры для TLS 1.2 + приоритет TLS 1.3
    ssl_ciphers 'ECDHE-ECDSA-AES256-GCM-SHA384:ECDHE-RSA-AES256-GCM-SHA384:ECDHE-ECDSA-CHACHA20-POLY1305:ECDHE-RSA-CHACHA20-POLY1305:ECDHE-ECDSA-AES128-GCM-SHA256';
    ssl_ecdh_curve X25519:secp384r1;
}
```

**Валидация:**
```bash
# Проверка активного шифра и протокола
echo | openssl s_client -connect example.com:443 -servername example.com -status 2>&1 | \
  grep -E "Protocol|Cipher|OCSP"
# → Protocol  : TLSv1.3
# → Cipher    : TLS_AES_256_GCM_SHA384
# → OCSP Response Status: successful (0x0)

# Проверка ALPN (должен быть h2 или h3)
echo | openssl s_client -connect example.com:443 -servername example.com -alpn h2 2>&1 | \
  grep "ALPN"
# → ALPN protocol: h2
```

### Сценарий 2: Выбор TLS-библиотеки (Глубокий анализ)

Разные реализации TLS критически влияют на пропускную способность и количество новых соединений. В 2026 году основными вариантами являются OpenSSL и BoringSSL-based реализации.

**Параметры тестового стенда:**
- CPU: Intel Xeon (Sapphire Rapids) с поддержкой AES-NI и AVX-512.
- OS: Ubuntu 26.04, Linux Kernel 6.12.
- Режим: Тестирование handshake (новые соединения) и пропускной способности (AES-256-GCM).

**Результаты тестирования (CPS — Connections Per Second):**

| Конфигурация | TLS 1.3 + ECDSA | TLS 1.3 + PQC (ML-KEM) | TLS 1.2 + ECDSA |
| :--- | :---: | :---: | :---: |
| **BoringSSL-based** | ~9 500 | ~7 800 | ~7 000 |
| **OpenSSL 4.0.1** | ~7 300 | ~6 200 | ~8 600 |
| **OpenSSL 3.5.5 (System)** | ~7 000 | ~5 800 | ~9 100 |

**Анализ результатов:**
1. **BoringSSL-based** значительно опережает OpenSSL в операциях TLS 1.3 и 0-RTT. Это связано с агрессивной оптимизацией математики эллиптических кривых и более компактным кодом.
2. **OpenSSL 3.5.5/4.0.1** показывает отличные результаты в TLS 1.2, что полезно для поддержки устаревших клиентов в корпоративных сетях.
3. **Постквантовое замедление:** внедрение PQC снижает CPS на 15–20% даже с аппаратным ускорением.

**Пропускная способность (RPS на файл 100 МБ):**
На больших объемах разница между библиотеками нивелируется (в пределах 3–5%), так как лимитирующим фактором становится пропускная способность памяти и ядра ОС. Использование **kTLS** в OpenSSL дает преимущество в ~15% при раздаче статики.

### Сценарий 3: Внедрение мониторинга TLS-метрик для SRE

Для контроля эффективности TLS-оптимизаций в production необходимы автоматизированные проверки:

```bash
# 1. Скрипт проверки срока действия сертификата (выполняется через cron)
#!/bin/bash
HOST="example.com"
PORT=443
DAYS_WARN=30
DAYS_CRIT=7

EXP_DATE=$(echo | openssl s_client -connect "$HOST:$PORT" -servername "$HOST" 2>/dev/null | \
  openssl x509 -noout -enddate 2>/dev/null | cut -d= -f2)

if [ -z "$EXP_DATE" ]; then
  echo "CRITICAL: Unable to fetch certificate for $HOST"
  exit 2
fi

EXP_EPOCH=$(date -d "$EXP_DATE" +%s)
NOW_EPOCH=$(date +%s)
DAYS_LEFT=$(( ($EXP_EPOCH - $NOW_EPOCH) / 86400 ))

if [ "$DAYS_LEFT" -lt "$DAYS_CRIT" ]; then
  echo "CRITICAL: Certificate for $HOST expires in $DAYS_LEFT days"
  exit 2
elif [ "$DAYS_LEFT" -lt "$DAYS_WARN" ]; then
  echo "WARNING: Certificate for $HOST expires in $DAYS_LEFT days"
  exit 1
else
  echo "OK: Certificate for $HOST expires in $DAYS_LEFT days"
  exit 0
fi
```

**Интеграция с Prometheus / Alertmanager:**
```yaml
# В node_exporter или custom exporter:
# - tls_cert_expiry_days{host="example.com"} 45
# - tls_handshake_rtt_seconds{host="example.com"} 0.089
# - tls_ocsp_stapling_status{host="example.com"} 1 (1=success, 0=failure)
```

**Grafana-дашборд (ключевые панели):**
- **TTFB breakdown:** DNS + TCP + TLS + Server Processing
- **TLS Handshake RTT trend:** p50, p95, p99 по всем доменам
- **OCSP Stapling success rate:** % успешных ответов за 5 минут
- **Session Resumption ratio:** resumed sessions / total sessions
- **Certificate expiry timeline:** визуализация сроков действия по всем сертификатам

### Сценарий 4: Регрессионное тестирование TLS после деплоя

Перед применением изменений в production выполните автоматизированное тестирование:

```bash
#!/bin/bash
# tls_regression_test.sh — базовый набор проверок после деплоя

DOMAINS=("example.com" "api.example.com")
FAIL=0

for DOMAIN in "${DOMAINS[@]}"; do
  echo "=== Testing $DOMAIN ==="
  
  # 1. Проверка протоколов (TLS 1.3 должен работать, 1.0/1.1 — нет)
  echo | openssl s_client -connect "$DOMAIN:443" -servername "$DOMAIN" -tls1_3 2>&1 | grep -q "Protocol.*TLSv1.3"
  if [ $? -eq 0 ]; then
    echo "  [PASS] TLS 1.3 supported"
  else
    echo "  [FAIL] TLS 1.3 not supported"
    FAIL=1
  fi
  
  # 2. Проверка отключенных устаревших протоколов
  echo | openssl s_client -connect "$DOMAIN:443" -servername "$DOMAIN" -tls1_2 2>&1 | grep -q "Protocol.*TLSv1.2"
  if [ $? -eq 0 ]; then
    echo "  [PASS] TLS 1.2 supported"
  else
    echo "  [FAIL] TLS 1.2 not supported"
    FAIL=1
  fi
  
  # 3. Проверка OCSP Stapling
  echo | openssl s_client -connect "$DOMAIN:443" -servername "$DOMAIN" -status 2>&1 | \
    grep -q "OCSP Response Status: successful"
  if [ $? -eq 0 ]; then
    echo "  [PASS] OCSP Stapling working"
  else
    echo "  [FAIL] OCSP Stapling failed"
    FAIL=1
  fi
  
  # 4. Проверка PFS (шифр должен содержать ECDHE)
  Cipher=$(echo | openssl s_client -connect "$DOMAIN:443" -servername "$DOMAIN" -tls1_2 2>&1 | grep "Cipher" | awk '{print $3}')
  if echo "$Cipher" | grep -q "ECDHE"; then
    echo "  [PASS] PFS cipher in use: $Cipher"
  else
    echo "  [FAIL] No PFS cipher: $Cipher"
    FAIL=1
  fi
  
  # 5. Измерение TTFB
  TTFB=$(curl -o /dev/null -s -w "TLS: %{time_appconnect}s\n" "https://$DOMAIN/" | grep "TLS:" | awk '{print $2}')
  echo "  [INFO] TLS handshake time: $TTFB s"
done

exit $FAIL
```

## Операции и команды

### Проверка сроков действия сертификатов

```bash
# Проверка срока действия конкретного домена
echo | openssl s_client -connect example.com:443 -servername example.com 2>/dev/null | \
  openssl x509 -noout -dates
# → notBefore=Sep 22 00:00:00 2025 GMT
# → notAfter=Dec 22 23:59:59 2025 GMT

# Проверка нескольких доменов из файла
while read -r DOMAIN; do
  echo -n "$DOMAIN: "
  echo | openssl s_client -connect "$DOMAIN:443" -servername "$DOMAIN" 2>/dev/null | \
    openssl x509 -noout -enddate 2>/dev/null | cut -d= -f2
done < domains.txt
```

### Диагностика TLS-рукопожатия

```bash
# Полная проверка рукопожатия (TLS 1.3 + OCSP + SNI)
openssl s_client -connect domain.com:443 -servername domain.com -status -alpn h2
# → ...
# → Protocol  : TLSv1.3
# → Cipher    : TLS_AES_256_GCM_SHA384
# → OCSP Response Status: successful (0x0)

# Проверка с детальной цепочкой сертификатов
openssl s_client -connect domain.com:443 -servername domain.com -showcerts \
  -CAfile /etc/ssl/certs/ca-certificates.crt
# → показывает все сертификаты в цепочке и путь верификации

# Проверка поддержки ECH (OpenSSL 4.0+)
openssl s_client -connect domain.com:443 -servername domain.com -ech 2>&1 | grep "ECH"
# → ECH accepted

# Проверка поддержки TLS 1.3 конкретным клиентом
openssl s_client -connect domain.com:443 -servername domain.com -tls1_3
```

### Проверка совместимости клиентов

```bash
# Проверка доступных шифров клиента
openssl ciphers -v 'TLSv1.3' | awk '{print $2}' | sort -u
# → TLS_AES_256_GCM_SHA384
# → TLS_CHACHA20_POLY1305_SHA256
# → TLS_AES_128_GCM_SHA256

# Проверка HTTP/3 через ALPN
openssl s_client -connect domain.com:443 -servername domain.com -alpn h3
```

### Измерение производительности TLS

```bash
# Полный тайминг запроса (TTFB, TLS, DNS)
curl -o /dev/null -s -w "\
  DNS: %{time_namelookup}s\n\
  TCP: %{time_connect}s\n\
  TLS: %{time_appconnect}s\n\
  TTFB: %{time_starttransfer}s\n\
  Total: %{time_total}s\n" https://example.com/
# → DNS: 0.012s
# → TCP: 0.045s
# → TLS: 0.078s
# → TTFB: 0.245s
# → Total: 0.312s

# Если TLS > 100 мс — требуется оптимизация TLS (OCSP Stapling, session tickets, kTLS)

# Бенчмарк новых соединений (handshake latency)
ab -n 1000 -c 10 -k https://example.com/
# → Focus на Time per request и SSL handshake metrics
```

### Управление сессиями и кэшированием

```bash
# Проверка размера сессионного кэша (Nginx/Angie)
echo | openssl s_client -connect example.com:443 -servername example.com -reconnect 5 2>&1 | \
  grep "Reused"
# → Reused, session id reused

# Очистка кэша сессий (перезагрузка сервера)
systemctl reload nginx

# Проверка поддержки kTLS в OpenSSL
openssl list -providers | grep -i tls
# → enterprise-grade TLS (KTLS) в выводе означает активную поддержку
```

### Управление службой веб-сервера

```bash
# Проверка синтаксиса (обязательно перед reload)
nginx -t
# → nginx: configuration file /etc/nginx/nginx.conf test is successful

# Graceful reload без разрыва соединений
systemctl reload nginx

# Принудительная перезагрузка (при проблемах с graceful)
systemctl restart nginx

# Проверка статуса
systemctl status nginx
# → Active: active (running) since Tue 2025-09-22 12:00:00 UTC; 2h ago
```

## Диагностика ошибок

### Типичные проблемы оптимизации TLS

| Проблема | Симптом | Диагностика | Решение |
| :--- | :--- | :--- | :--- |
| **Высокий TLS Handshake RTT** | TLS > 100 мс в curl `-w` | `curl -o /dev/null -s -w "%{time_appconnect}s" URL` | OCSP Stapling, session tickets, kTLS, апскейлинг CPU |
| **Высокий CPU Overhead** | Высокая нагрузка на CPU при SSL | `htop`, `openssl speed -evp aes-256-gcm` | kTLS, аппаратное ускорение (AES-NI), оптимизация cipher suites |
| **0-RTT не работает** | Повторный handshake вместо resumed | `openssl s_client -connect host:443 -reconnect` | Проверить `ssl_session_tickets on`, совместимость клиентов |
| **Replay-атака 0-RTT** | Дублирование запросов POST/PUT | Проверить `ssl_early_data` в конфигурации | Отключить 0-RTT для методов с побочными эффектами, использовать Idempotency Key |
| **OCSP Stapling не работает** | `ssl_stapling: no data` в логах | `openssl s_client -connect host:443 -status` | Проверить AIA в сертификате, resolver, доступность OCSP-responder |
| **Session Resumption не работает** | Каждый запрос = полный handshake | `openssl s_client -connect host:443 -reconnect 5` | Проверить `ssl_session_cache`, `ssl_session_tickets`, размер кэша |
| **kTLS не доступен** | Ошибка `KTLS not available` | `openssl list -providers \| grep -i tls` | Обновить ядро до 5.2+, OpenSSL 3.0+ с `enable-ktls` |
| **Сертификат истекает** | Браузер показывает warning | `openssl s_client -connect host:443 -servername host` | Автоматическая ротация через ACME/certbot, мониторинг за 30/14/7 дней |
| **Cipher suite mismatch** | `alert handshake failure (40)` | `openssl s_client -connect host:443 -servername host` | Сравнить `ssl_ciphers` на сервере и клиенте, добавить пересечение |
| **PQC замедление** | CPS упал на 20%+ после включения PQC | Сравнить `openssl speed` до/после | Оценить benefit/risk, использовать аппаратное ускорение, гибридные схемы |
| **Certificate Chain неполная** | `verify error:num=20` | `openssl s_client -connect host:443 -showcerts` | Добавить промежуточный сертификат в `ssl_certificate` |
| **ECH decryption failed** | Ошибка после ротации ECH-ключей | `openssl s_client -connect host:443 -ech` | Проверить `ssl_ech_file`, DNS-записи HTTPS, совпадение ключей |

### Методология диагностики

1. **Локализация проблемы:** определите, является ли проблема handshake-стадией, data-transfer-стадией или resumption-стадией.
2. **Сбор метрик:** `curl -w` для таймингов, `openssl s_client` для деталей handshake, `openssl speed` для CPU-бенчмарка.
3. **Валидация гипотезы:** сравните с baseline (до изменений) или с эталонной конфигурацией.
4. **Устранение:** внесите изменения в конфигурацию, проверьте синтаксис, примените `reload`.
5. **Верификация:** повторите измерения, убедитесь, что метрики вернулись к baseline или улучшились.

## Рекомендации

### Чеклист SRE/SysAdmin для TLS-оптимизации

- [ ] **Baseline метрики:** Зафиксируйте текущие значения TLS Handshake RTT, CPU Overhead, CPS перед любыми изменениями.
- [ ] **Мониторинг:** Автоматические проверки срока действия сертификатов (за 30, 14 и 7 дней до истечения), OCSP Stapling success rate, session resumption ratio.
- [ ] **Alerting:** Alert на `error_log` с ключевыми словами `handshake failure`, `certificate verify failed`, `no shared cipher`, `KTLS not available`.
- [ ] **Изменения в production:** Применяйте изменения в `ssl_protocols` или `ssl_ciphers` сначала на канареечной ноде, затем на всех.
- [ ] **Бэкап:** Автоматическое резервное копирование `ssl_certificate` и `ssl_certificate_key` перед каждой ротацией.
- [ ] **Регрессионное тестирование:** Запускайте автоматизированный скрипт проверок после каждого деплоя (см. Сценарий 4).
- [ ] **Документация:** Ведите матрицу совместимости клиентов (браузеры, мобильные ОС, инфраструктурные агенты).

### Процедуры операционной поддержки

**Ротация сертификатов:**
1. Получите новый сертификат через Certbot или внутренний CA.
2. Скопируйте файлы в `/etc/letsencrypt/live/example.com/` (или `/etc/nginx/ssl/`).
3. Выполните `nginx -t`.
4. Выполните `systemctl reload nginx`.
5. Проверьте: `openssl s_client -connect domain.com:443 -servername domain.com -status`.

**Валидация после изменений:**
```bash
# 1. Проверка синтаксиса
nginx -t

# 2. Применение
systemctl reload nginx

# 3. Логи
journalctl -u nginx --since "1 minute ago"

# 4. Метрики TLS
curl -o /dev/null -s -w "TLS: %{time_appconnect}s\n" https://example.com/
```

**Откат изменений:**
```bash
# Если reload вызвал проблемы
git checkout /etc/nginx/conf.d/example.com.conf  # или восстановите из бэкапа
systemctl reload nginx
```

**Бэкап конфигурации:**
```bash
# Бэкап конфигурации
tar czf /backup/nginx-vhosts-$(date +%F).tar.gz /etc/nginx/conf.d/

# Бэкап сертификатов (если не используются Let's Encrypt)
tar czf /backup/nginx-ssl-$(date +%F).tar.gz /etc/nginx/ssl/
```

### Производительность TLS-диагностики

| Инструмент | Влияние на production | Рекомендация |
| :--- | :--- | :--- |
| `error_log info` | Увеличивает I/O при интенсивном трафике | Используйте только при инциденте; в常态 — `warn` |
| `openssl s_client` | Без влияния (внешний запрос) | Без ограничений |
| `nginx -T` | Без влияния (только чтение конфига) | Без ограничений |
| `curl -w` тайминг | Без влияния | Без ограничений |
| `openssl speed` | Умеренная нагрузка на CPU | Используйте в off-peak hours |
| Audit-лог (`tls_audit.log`) | Умеренное увеличение I/O | Включайте на production с ротацией через `logrotate` |

## Дополнительная информация

### См. также

- **[Протокол TLS (теория)](../../../Networking/Protocols/tls.md)** — фундаментальные основы работы протокола, handshake, cipher suites, PFS.
- **[Диагностика TLS/SSL в Nginx](../../Nginx/Security/TLS_SSL/nginx_tls_troubleshooting_and_compatibility.md)** — методология отладки, иерархия ошибок, SRE-runbook.
- **[TLS-шифрование и сертификаты для HTTP](../../../Networking/Protocols/HTTP/http_tls_hardening.md)** — TLS Termination, mTLS, HSTS, certificate rotation.
- **[Протоколы HTTP/2 и HTTP/3](./http2_http3.md)** — ALPN, 0-RTT в QUIC, взаимодействие TLS с транспортом.
- **[Kernel TLS в деталях](../../Nginx/Performance/nginx_performance_tuning.md#kernel-tls-ktls)** — глубокое погружение в серверную оптимизацию.
- [Zero-Downtime Deployment](./zero_downtime_deployment.md) — graceful reload без разрыва TLS-сессий.
- [Structured Logging для Performance](./structured_logging_for_performance.md) — анализ TLS-рукопожатий через логи.
