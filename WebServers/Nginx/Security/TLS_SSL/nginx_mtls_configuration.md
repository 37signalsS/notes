# Настройка Mutual TLS (mTLS) в Nginx

## Определения

**Mutual TLS (mTLS)** — механизм взаимной аутентификации на транспортном уровне (L4/L7). В отличие от стандартного TLS, где только клиент проверяет подлинность сервера, mTLS требует от клиента также предъявить валидный клиентский сертификат, подписанный доверенным центром сертификации (CA). Это обеспечивает высший уровень assurance для межсервисного взаимодействия (M2M), критических API и административных панелей.

Теоретические основы и процесс рукопожатия описаны в системном документе: **[mTLS в протоколе TLS](../../../../Networking/Protocols/tls.md#сценарий-2-взаимная-аутентификация-mtls)**.

**Chain of Trust (Цепочка доверия)** — путь валидации от сертификата клиента до доверенного корневого CA. В контексте mTLS Nginx проверяет, что клиентский сертификат подписан одним из CA, указанных в `ssl_client_certificate`.

**CRL (Certificate Revocation List)** — список отозванных серийных номеров сертификатов. Используется для блокировки доступа скомпрометированных клиентов без изменения глобальной конфигурации.

**OCSP (Online Certificate Status Protocol)** — протокол онлайн-проверки статуса отдельного сертификата. В 2026 году является стандартом де-факто для мгновенного отзыва доступа, заменяя CRL в большинстве сценариев.

**EKU (Extended Key Usage)** — расширение X.509 v3, указывающее назначение сертификата. Для клиентских сертификатов обязательно наличие OID `1.3.6.1.5.5.7.3.2` (Client Authentication).

**Private CA** — внутренний центр сертификации, используемый для выпуска клиентских сертификатов. В 2026 году публичные CA (Let's Encrypt) не выпускают сертификаты с EKU Client Auth из-за политики CA/Browser Forum.

## Архитектура mTLS в Nginx

### Жизненный цикл mTLS-соединения

Nginx использует событийно-ориентированную многопроцессную архитектуру (master + worker processes). mTLS-рукопожатие выполняется в контексте воркеров:

1. **Прием соединения**: Клиент устанавливает TCP-соединение с портом, на котором настроен `listen ... ssl`.
2. **ClientHello**: Клиент отправляет поддерживаемые версии TLS, наборы шифров и SNI.
3. **CertificateRequest**: При `ssl_verify_client on` сервер запрашивает сертификат у клиента. В TLS 1.3 это сообщение шифруется, исключая пассивное выявление требуемых CA.
4. **Certificate**: Клиент отправляет свою цепочку сертификатов (Leaf + Intermediate CA).
5. **Валидация**: Nginx проверяет:
   - Подпись цепочки (`ssl_client_certificate`).
   - Глубину иерархии (`ssl_verify_depth`).
   - Статус отзыва (CRL через `ssl_crl` или OCSP через `ssl_ocsp`).
   - Срок действия.
6. **Установка сессии**: При успехе устанавливается симметричный сессионный ключ. В Nginx 1.30+ поддерживается 0-RTT Early Data для снижения задержки.
7. **Прикладной обмен**: Данные передаются через защищенный канал. При включенном kTLS шифрование выполняется в ядре Linux (Kernel 5.10+).

### Директивы конфигурации

| Директива | Уровень | Описание |
| :--- | :--- | :--- |
| `ssl_client_certificate` | `http`, `server` | Путь к PEM-файлу с доверенными сертификатами CA. Список отправляется клиенту в `CertificateRequest`. |
| `ssl_verify_client` | `http`, `server` | Режим проверки: `off`, `on`, `optional`, `optional_no_ca`. |
| `ssl_verify_depth` | `http`, `server` | Максимальная глубина проверки цепочки. Минимум `2` при использовании Intermediate CA. |
| `ssl_crl` | `http`, `server` | Путь к файлу CRL. В Nginx 1.30+ поддерживает переменные для динамического обновления без `reload`. |
| `ssl_ocsp` | `http`, `server` | Включает онлайн-проверку статуса клиентского сертификата через OCSP. |
| `ssl_ocsp_cache` | `http` | Разделяемый кэш для ответов OCSP (`shared:NAME:SIZE`). |
| `ssl_trusted_certificate` | `http`, `server` | Файл с доверенными сертификатами для проверки OCSP. Обязателен при использовании Intermediate CA. |

### Переменные mTLS для логики и бэкендов

Nginx предоставляет доступ к метаданным проверки через переменные, доступные в `proxy_set_header`, `map` и форматах логов:

| Переменная | Описание |
| :--- | :--- |
| `$ssl_client_verify` | Результат проверки: `SUCCESS`, `FAILED:reason` или `NONE`. |
| `$ssl_client_s_dn` | Полная строка Subject DN из сертификата клиента. |
| `$ssl_client_s_dn_cn` | Common Name (CN) субъекта. |
| `$ssl_client_serial` | Серийный номер сертификата (для аудита). |

## Практические сценарии и установка

### Предварительные требования

Перед настройкой mTLS убедитесь, что компоненты соответствуют стандартам 2026 года:

```bash
# Проверка версии Nginx и библиотеки OpenSSL
nginx -V 2>&1 | grep -oE 'built with OpenSSL [0-9.]+'

# Проверка поддержки TLS 1.3 (обязателен для mTLS)
nginx -V 2>&1 | grep -o 'TLSv1.3'

# Проверка поддержки kTLS в ядре (требуется ядро 5.10+)
uname -r
```

**Минимальные версии (2026):**
- **Nginx**: 1.30+ (Stable) или 1.29+ (Mainline).
- **OpenSSL**: 3.5 LTS+ (рекомендуется 4.0 для ECH).
- **Ядро Linux**: 5.10+ (для kTLS).

### Сценарий 1: Создание PKI с OpenSSL

Для внутренних сервисов рекомендуется использовать Private CA. Пример создания двухуровневой иерархии:

```bash
# 1. Создание корневого CA (Root CA)
openssl genrsa -out ca.key 4096
openssl req -x509 -new -nodes -key ca.key -sha384 -days 3650 \
  -subj "/C=RU/ST=Moscow/L=Moscow/O=Example/OU=IT/CN=Example Root CA" \
  -out ca.crt

# 2. Создание промежуточного CA (Intermediate CA)
openssl genrsa -out intermediate.key 4096
openssl req -new -key intermediate.key \
  -subj "/C=RU/ST=Moscow/L=Moscow/O=Example/OU=IT/CN=Example Intermediate CA" \
  -out intermediate.csr
openssl x509 -req -in intermediate.csr -CA ca.crt -CAkey ca.key \
  -CAcreateserial -out intermediate.crt -days 1825 -sha384 -extfile <(echo "basicConstraints=CA:TRUE,pathlen:0")

# 3. Создание клиентского сертификата (ECDSA P-384)
openssl ecparam -genkey -name secp384r1 -out client.key
openssl req -new -key client.key \
  -subj "/C=RU/ST=Moscow/L=Moscow/O=Example/OU=IT/CN=client-01" \
  -out client.csr
openssl x509 -req -in client.csr -CA intermediate.crt -CAkey intermediate.key \
  -CAcreateserial -out client.crt -days 365 -sha384 \
  -extfile <(echo "basicConstraints=CA:FALSE\nkeyUsage=digitalSignature,keyEncipherment\nextendedKeyUsage=clientAuth")

# 4. Создание CRL
openssl ca -gencrl -config <(echo "[ca]\ndefault_ca=CA_default\n[CA_default]\ncadir=.\n") \
  -out crl.pem
```

**Структура каталогов:**
```
/etc/nginx/ssl/
├── ca.crt                 # Root CA (для доверенных клиентов)
├── intermediate.crt       # Intermediate CA
├── server.crt             # Сертификат сервера
├── server.key             # Приватный ключ сервера (600)
├── client.crt             # Клиентский сертификат
├── client.key             # Клиентский ключ
└── crl.pem                # Список отозванных сертификатов
```

### Сценарий 2: Базовая защита HTTP API (Production)

Минимальный конфиг для критических сервисов с mTLS и наследованием глобальных параметров:

```nginx
server {
    listen 443 ssl http2;
    server_name api.secure-service.com;

    # Сертификат сервера
    ssl_certificate     /etc/nginx/ssl/server.fullchain.crt;
    ssl_certificate_key /etc/nginx/ssl/server.key;

    # mTLS
    ssl_client_certificate /etc/nginx/ssl/intermediate.crt;
    ssl_verify_client      on;
    ssl_verify_depth       2;

    # OCSP для клиентских сертификатов
    ssl_ocsp on;
    ssl_ocsp_cache shared:CLIENT_OCSP:20m;
    resolver 1.1.1.1 8.8.8.8 valid=300s;
    resolver_timeout 5s;

    location / {
        proxy_pass http://internal_app;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;

        # Передача метаданных mTLS в бэкенд
        proxy_set_header X-mTLS-Status  $ssl_client_verify;
        proxy_set_header X-mTLS-User    $ssl_client_s_dn_cn;
        proxy_set_header X-mTLS-Serial  $ssl_client_serial;
    }
}
```

### Сценарий 3: mTLS в модуле Stream (L4)

Защита произвольного TCP-трафика (PostgreSQL, MySQL, Redis) на уровне L4:

```nginx
stream {
    server {
        listen 5432 ssl;
        proxy_pass postgres_backend;

        ssl_certificate     /etc/nginx/ssl/db_proxy.crt;
        ssl_certificate_key /etc/nginx/ssl/db_proxy.key;

        ssl_client_certificate /etc/nginx/ssl/intermediate.crt;
        ssl_verify_client      on;
        ssl_verify_depth       2;

        ssl_crl /etc/nginx/ssl/crl.pem;
        ssl_ocsp on;
        resolver 1.1.1.1 valid=300s;
    }
}
```

### Сценарий 4: Динамическая проверка отзыва через OCSP

В 2026 году OCSP является стандартом для мгновенной блокировки доступа. Nginx кэширует ответы OCSP, снижая нагрузку на CA:

```nginx
http {
    # Глобальный кэш OCSP для клиентских сертификатов
    ssl_ocsp_cache shared:CLIENT_OCSP:20m;

    server {
        listen 443 ssl http2;
        server_name secure.example.com;

        ssl_client_certificate /etc/nginx/ssl/intermediate.crt;
        ssl_verify_client      on;
        ssl_verify_depth       2;

        # OCSP Stapling для клиентских сертификатов
        ssl_ocsp on;
        ssl_ocsp_responder http://ocsp.example.com:80;

        # Резолвер обязателен для связи с OCSP-резолвером CA
        resolver 10.0.0.1 8.8.8.8 valid=300s;
        resolver_timeout 5s;

        location / {
            proxy_pass http://backend;
        }
    }
}
```

### Сценарий 5: Разрешение конфликта mTLS и Health Checks

При `ssl_verify_client on` локальные проверки (health checks от балансировщика, `curl` внутри контейнера) завершаются ошибкой, так как не имеют клиентского сертификата.

**Решение**: Выделение отдельного слушателя (listener) без mTLS, ограниченного `localhost`:

```nginx
# Внутренний порт для Health Checks (доступен только с localhost)
server {
    listen 127.0.0.1:8080;
    server_name localhost;

    location /healthz {
        access_log off;
        return 200 "healthy\n";
    }
}

# Внешний HTTPS порт с mTLS
server {
    listen 443 ssl http2;
    server_name api.example.com;

    ssl_certificate     /etc/nginx/ssl/server.fullchain.crt;
    ssl_certificate_key /etc/nginx/ssl/server.key;

    ssl_client_certificate /etc/nginx/ssl/intermediate.crt;
    ssl_verify_client      on;

    location / {
        proxy_pass http://internal_app;
    }
}
```

### Сценарий 6: Постквантовая криптография (PQC) в mTLS

В 2026 году OpenSSL 3.5 LTS+ и 4.0 поддерживают гибридные постквантовые алгоритмы (например, `X25519MLKEM768`). В контексте mTLS это позволяет защитить рукопожатие от будущих атак квантовых компьютеров.

**Особенности:**
- PQC-сертификаты (ML-DSA / FIPS 203) имеют значительно больший размер (несколько КБ), что может вызвать фрагментацию пакетов при передаче цепочки.
- В 2026 году для клиентских сертификатов рекомендуется **ECDSA P-384** как баланс производительности и безопасности. Полный переход на ML-DSA ожидается после массового обновления инфраструктуры CA.

**Настройка гибридных кривых в глобальном блоке `http`:**
```nginx
http {
    ssl_ecdh_curve X25519MLKEM768:X25519:prime256v1:secp384r1;
}
```

## Операции и команды

### Управление службой Nginx

| Действие | Команда | Примечание |
| :--- | :--- | :--- |
| **Проверка конфигурации** | `nginx -t` | Обязательно выполнять перед применением изменений. |
| **Перезагрузка конфигурации** | `nginx -s reload` | Graceful reload, без разрыва существующих соединений. |
| **Перезапуск worker'ов** | `nginx -s reopen` | Повторное открытие лог-файлов. |
| **Остановка** | `nginx -s stop` | Быстрая остановка. |
| **Корректное завершение** | `nginx -s quit` | Ожидание завершения текущих запросов. |
| **Статус через systemd** | `systemctl status nginx` | Проверка активного статуса службы. |

### Управление PKI и сертификатами

```bash
# Просмотр деталей клиентского сертификата
openssl x509 -in client.crt -text -noout
# → Subject, Issuer, Serial, Not Before/After, X509v3 extensions

# Проверка срока действия
openssl x509 -in client.crt -noout -dates
# → notBefore=May  1 00:00:00 2026 GMT
# → notAfter=May  1 00:00:00 2027 GMT

# Проверка подписи сертификата CA
openssl verify -CAfile ca.crt client.crt
# → client.crt: OK

# Проверка соответствия ключа и сертификата
openssl x509 -noout -modulus -in client.crt | openssl md5
openssl ecparam  -noout -modulus -in client.key | openssl md5
# → хеши должны совпадать

# Проверка цепочки с промежуточным CA
openssl verify -CAfile ca.crt -untrusted intermediate.crt client.crt
# → client.crt: OK

# Генерация CSR (Certificate Signing Request)
openssl req -new -key client.key -out client.csr \
  -subj "/C=RU/ST=Moscow/L=Moscow/O=Example/OU=IT/CN=client-01"

# Подпись CSR Intermediate CA
openssl x509 -req -in client.csr -CA intermediate.crt -CAkey intermediate.key \
  -CAcreateserial -out client.crt -days 365 -sha384 \
  -extfile <(echo "basicConstraints=CA:FALSE\nkeyUsage=digitalSignature\nextendedKeyUsage=clientAuth")
```

### Диагностика mTLS-соединений

```bash
# Полная проверка handshake с клиентским сертификатом
openssl s_client -connect api.example.com:443 \
  -cert client.crt -key client.key -CAfile ca.crt \
  -servername api.example.com -showcerts
# → Verify return code: 0 (ok)

# Проверка поддержки TLS 1.3
openssl s_client -connect api.example.com:443 -tls1_3 \
  -cert client.crt -key client.key -CAfile ca.crt

# Проверка конкретного cipher suite
openssl s_client -connect api.example.com:443 \
  -cert client.crt -key client.key -CAfile ca.crt \
  -cipher TLS_AES_256_GCM_SHA384

# Проверка через curl (удобно для скриптов)
curl -v --cert client.crt --key client.key --cacert ca.crt \
  https://api.example.com/healthz
# → HTTP/2 200

# Проверка отзыва через CRL
openssl verify -crl_check -CAfile ca.crt -CRLfile crl.pem client.crt
# → client.crt: OK

# Проверка статуса OCSP для сертификата
openssl ocsp -issuer intermediate.crt -cert client.crt \
  -url http://ocsp.example.com:80 -CAfile ca.crt
# → Response Status: successful (0x0)
```

### Управление CRL

```bash
# Генерация CRL (OpenSSL CA)
openssl ca -gencrl -config openssl.cnf -out crl.pem

# Просмотр содержимого CRL
openssl crl -in crl.pem -text -noout
# → показывает отозванные серийные номера и даты

# Конвертация CRL в DER (для некоторых приложений)
openssl crl -in crl.pem -outform DER -out crl.der
```

### Мониторинг и аудит

```bash
# Проверка активных TLS-сессий
ss -tnp | grep :443 | grep ESTAB | wc -l

# Анализ логов mTLS
awk '$8 ~ /FAILED/' /var/log/nginx/mtls_access.log | tail -n 20

# Проверка срока действия удаленного сертификата
echo | openssl s_client -connect api.example.com:443 2>/dev/null \
  | openssl x509 -noout -enddate
# → notAfter=May  1 00:00:00 2027 GMT

# Мониторинг OCSP в логах
journalctl -u nginx --since "1 hour ago" | grep -i ocsp
```

## Устранение неполадок

### Типичные ошибки mTLS

| Ошибка в логе / симптом | Вероятная причина | Решение |
| :--- | :--- | :--- |
| `400 Bad Request (No required SSL certificate was sent)` | Клиент не отправил сертификат или его CA отсутствует в `ssl_client_certificate`. | Убедитесь, что `ssl_client_certificate` содержит весь цепочку доверия (Intermediate + Root). Проверьте, что клиентский сертификат имеет EKU Client Auth. |
| `alert handshake failure (40)` | Сервер требует mTLS, но клиент не поддерживает его или не передал SNI. | Проверьте `ssl_verify_client` и наличие SNI у клиента. Убедитесь, что `ssl_protocols` включает TLSv1.2 или TLSv1.3. |
| `certificate verify failed` | Ошибка в `ssl_client_certificate` или просроченный сертификат. | Убедитесь, что файл содержит всю цепочку до Root CA. Проверьте срок: `openssl x509 -in cert.pem -noout -dates`. |
| `Handshake failure (Unknown CA)` | Издатель клиентского сертификата не найден в `ssl_client_certificate`. | Добавьте соответствующий Intermediate CA в `ssl_client_certificate`. Проверьте: `openssl verify -CAfile ca.crt client.crt`. |
| `CRL is not valid yet` | CRL имеет невалидную дату начала действия. | Перегенерируйте CRL. Проверьте системное время: `timedatectl status`. |
| `OCSP response: no response` | OCSP-резолвер недоступен. | Проверьте доступность порта 80/443 на CA. Убедитесь, что `resolver` указан в конфигурации Nginx. |

### Диагностика совместимости клиентов

```bash
# Проверка поддержки TLS 1.3 конкретным клиентом
openssl s_client -connect api.example.com:443 -tls1_3 \
  -cert client.crt -key client.key -CAfile ca.crt

# Проверка цепочки с детальным выводом
openssl s_client -connect api.example.com:443 \
  -cert client.crt -key client.key -CAfile ca.crt \
  -showcerts -CAfile /etc/ssl/certs/ca-certificates.crt

# Проверка переменных mTLS в конфигурации
nginx -T 2>/dev/null | grep ssl_client
# → показывает все директивы mTLS в активной конфигурации

# Проверка логов на ошибки handshake
tail -f /var/log/nginx/error.log | grep -i "handshake\|ssl\|verify"
```

### Внешний аудит

Для публичных сервисов с mTLS используйте **SSL Labs Server Test** ([https://www.ssllabs.com/ssltest/](https://www.ssllabs.com/ssltest/)).

**На что смотреть (2026):**
- **Chain issues**: Ошибки указывают на отсутствие Intermediate CA в `ssl_certificate` или `ssl_client_certificate`.
- **Protocol Support**: TLS 1.3 должен быть активен. TLS 1.0/1.1 — отключены.
- **Handshake Simulation**: Проверка, что сервер корректно требует клиентский сертификат.

## Рекомендации и лучшие практики

### Чеклист безопасности mTLS (2026)

- [ ] **TLS 1.3**: Обязателен для mTLS (шифрование `CertificateRequest`).
- [ ] **Private CA**: Используется внутренний CA для клиентских сертификатов. Публичные CA не выпускают Client Auth сертификаты.
- [ ] **Иерархия**: Root CA хранится offline. Intermediate CA используется для повседневных операций.
- [ ] **Цепочка**: `ssl_client_certificate` содержит Intermediate CA + Root CA в одном файле.
- [ ] **EKU**: Клиентские сертификаты имеют расширение `clientAuth` (OID `1.3.6.1.5.5.7.3.2`).
- [ ] **Глубина**: `ssl_verify_depth` установлен не менее `2`.
- [ ] **OCSP**: Включен для мгновенного отзыва доступа (`ssl_ocsp on`).
- [ ] **Кэш OCSP**: `ssl_ocsp_cache shared:CLIENT_OCSP:20m;` для снижения нагрузки.
- [ ] **Резолвер**: Указан внешний резолвер для OCSP-запросов.
- [ ] **Сессии**: `ssl_session_cache shared:SSL:10m;` и `ssl_session_timeout 1d;`.
- [ ] **kTLS**: Включен на уровне OpenSSL (`ssl_conf_command Options +KTLS`) для снижения нагрузки на CPU.
- [ ] **Версия сервера**: Скрыта (`server_tokens off`).
- [ ] **Права доступа**: Ключи — `600`, сертификаты — `644`, директории — `750`.
- [ ] **Ротация**: TTL клиентских сертификатов — не более 90 дней.
- [ ] **Аудит**: Включено логирование `$ssl_client_verify` и `$ssl_client_serial`.

### Производительность

- **ECDSA vs RSA**: Используйте **ECDSA P-384** для клиентских сертификатов. Размер ключа меньше, скорость рукопожатия выше.
- **kTLS**: Включайте на высоконагруженных серверах. Требует OpenSSL 3.0+ и поддержки в ядре (`modprobe tls`).
- **Сессии TLS**: `ssl_session_cache shared:SSL:10m` — оптимальный размер для большинства серверов. Для высоконагруженных увеличивайте до `20m` или `50m`.
- **Буферы**: `ssl_buffer_size 4k` ускоряет передачу первого пакета.
- **Кэширование сертификатов**: В Nginx 1.30+ кэширование сертификатов включено по умолчанию. Для динамических путей используйте `ssl_certificate_cache` (только в Angie).

### Эксплуатационные процедуры

**Ротация сертификатов:**
- Настраивайте автоматическое обновление за 30 дней до истечения срока действия.
- Используйте ACME-клиенты с поддержкой Internal CA (например, Smallstep CA) или скрипты на базе OpenSSL.
- После обновления перезагружайте Nginx: `nginx -s reload`.

**Мониторинг истечения:**
- Добавьте в мониторинг (Prometheus + Node Exporter или Zabbix) проверку срока действия сертификатов.
- Команда для ручной проверки: `echo | openssl s_client -connect api.example.com:443 2>/dev/null | openssl x509 -noout -dates`.

**Резервное копирование:**
- Регулярно копируйте CA-ключи (`ca.key`, `intermediate.key`) в защищенное хранилище. Потеря ключа означает необходимость перевыпуска всех сертификатов.
- Храните резервные копии в зашифрованном виде с ограниченным доступом.

**Откат изменений:**
```bash
# Перед изменением конфигурации
sudo cp /etc/nginx/nginx.conf /etc/nginx/nginx.conf.bak

# Восстановление при проблемах
sudo cp /etc/nginx/nginx.conf.bak /etc/nginx/nginx.conf
sudo nginx -t && sudo nginx -s reload
```

### Совместимость клиентов (Baseline 2026)

| Категория | Поддержка mTLS | Рекомендация |
| :--- | :--- | :--- |
| **Современные браузеры (Chrome 125+, FF 125+)** | TLS 1.3, mTLS, Hybrid PQC | Полная поддержка всех функций. |
| **Apple (iOS 18+, macOS 15+)** | TLS 1.3, mTLS, Hybrid PQC | Поддержка нативная при наличии доверенных CA в системе. |
| **Legacy Android (8.0 - 11.0)** | TLS 1.2 / 1.3 | Требуют ECDHE-AES-GCM шифров для работы. |
| **Инфраструктурные (Java 11, Go 1.22+)** | TLS 1.3 | Поддерживают современный mTLS, но могут не поддерживать ECH. |
| **Устаревшие (TLS 1.0/1.1)** | Не поддерживаются | Полностью выведены из эксплуатации (RFC 8996). |

**Важное замечание**: TLS 1.0 и 1.1 полностью выведены из эксплуатации. В Nginx 1.30+ поддержка этих протоколов может быть удалена на уровне сборки.

## Дополнительная информация

### См. также

- **[Обзор TLS/SSL в Nginx](./nginx_tls_ssl_overview.md)** — архитектура TLS, ECH, PQC, глобальная конфигурация.
- **[Диагностика SSL/TLS сертификатов](../../../../Security/Tools/ssl_certificate_diagnostics.md)** — команды для анализа цепочек и форматов.
- **[Инфраструктура открытых ключей (PKI)](../../../../Security/Concepts/pki_overview.md)** — архитектура CA, форматы сертификатов и механизмы отзыва.
