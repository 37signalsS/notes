# Взаимная аутентификация клиентов (mTLS) в Angie

## Определения

**Взаимная аутентификация TLS (Mutual TLS, mTLS)** — механизм безопасности на транспортном уровне (L4/L7), при котором не только клиент проверяет подлинность сервера по его сертификату, но и сервер проверяет подлинность клиента с помощью его TLS-сертификата. Это обеспечивает высший уровень assurance для межсервисного взаимодействия (M2M), критических API и административных панелей.

**Angie** расширяет классический mTLS Nginx, добавляя поддержку динамических переменных в путях к сертификатам и CRL, нативный модуль ACME для автоматизации выпуска сертификатов в модуле Stream, а также Certificates API для управления цепочками доверия в runtime.

## Основные концепции

### Архитектура mTLS в Angie

Angie наследует событийно-ориентированную многопроцессную архитектуру (master и worker процессы). mTLS-рукопожатие выполняется в контексте воркеров, что позволяет эффективно использовать многопроцессорность и NUMA-узлы.

**Жизненный цикл mTLS-соединения:**
1. Клиент инициирует TCP-соединение (или UDP для QUIC).
2. Angie принимает соединение на `listen 443 ssl`.
3. Выполняется TLS-рукопожатие. При `ssl_verify_client on` сервер отправляет `CertificateRequest`, запрашивая сертификат клиента.
4. Клиент отправляет свой сертификат (если настроен `ssl_client_certificate`, клиент выбирает сертификат из списка доверенных CA).
5. Angie проверяет цепочку сертификата клиента: подпись, срок действия, глубину иерархии (`ssl_verify_depth`), статус отзыва (CRL/OCSP).
6. При успехе устанавливается сессионный ключ; при необходимости выполняется привязка к бэкенду через переменные `$ssl_client_*`.
7. Данные передаются с шифрованием (в user-space или через kTLS).

В 2026 году в связи с ограничениями публичных CA (Let's Encrypt и др.) на выпуск сертификатов с расширением Client Auth, mTLS практически полностью перешел на использование **Private CA** (HashiCorp Vault, Easy-RSA) и современные алгоритмы подписи (**ECDSA P-384**). TLS 1.3 является обязательным стандартом для mTLS, так как `CertificateRequest` шифруется, исключая утечку информации о требуемых CA.

### Ключевые директивы

| Директива | Описание | Особенности Angie |
|:----------|:---------|:------------------|
| `ssl_client_certificate` | Путь к сертификату CA для проверки клиента. | Список этих CA отправляется клиенту в CertificateRequest. |
| `ssl_verify_client` | Режимы: `on`, `off`, `optional`, `optional_no_ca`. | Базовый переключатель режима проверки. |
| `ssl_crl` | Путь к списку отозванных сертификатов (CRL). | **Поддерживает переменные**, что позволяет обновлять CRL без `reload`. |
| `ssl_verify_depth` | Глубина проверки цепочки (минимум 2 для Intermediate CA). | Стандартная проверка иерархии. |
| `ssl_certificate_cache` | Кэширование сертификатов при использовании переменных. | Радикально ускоряет работу при динамических путях. |
| `ssl_ocsp` | Проверка статуса сертификата клиента онлайн. | Стандарт 2026 года для мгновенного отзыва доступа. |
| `ssl_trusted_certificate` | Путь к доверенному сертификату для проверки OCSP. | Обязателен при использовании `ssl_ocsp` с промежуточными CA. |
| `ssl_ocsp_cache` | Кэш для ответов OCSP. | Снижает нагрузку на OCSP-резолвер CA. |

### Режимы проверки клиентских сертификатов

| Режим | Поведение | Применение |
|:------|:----------|:-----------|
| `off` | Проверка отключена | Публичные сайты без ограничения по сертификатам. |
| `on` | Требуется валидный сертификат | Строгая изоляция; блокада невалидных клиентов. |
| `optional` | Клиент может отправить сертификат; валидные сертификаты принимаются | Градуальное внедрение; пассивный мониторинг. |
| `optional_no_ca` | Принимается любой сертификат без проверки CA | Доверие логике приложения; deprecated для production. |

### Переменные клиентского сертификата (Angie 1.12+)

| Переменная | Описание |
|:-----------|:---------|
| `$ssl_client_verify` | Результат проверки (`SUCCESS`, `FAILED:reason`, `NONE`). |
| `$ssl_client_s_dn` | Distinguished Name (DN) субъекта. |
| `$ssl_client_i_dn` | Distinguished Name (DN) издателя (CA). |
| `$ssl_client_s_dn_cn` | Common Name (CN) из DN субъекта. |
| `$ssl_client_serial` | Серийный номер сертификата. |
| `$ssl_client_v_remain` | Количество дней до истечения срока действия. |
| `$ssl_client_v_start` | Дата начала действия сертификата. |
| `$ssl_client_v_end` | Дата окончания действия сертификата. |
| `$ssl_client_sigalg` | Алгоритм подписи (например, `sha384WithRSAEncryption`). |
| `$ssl_client_raw_cert` | Полный текст сертификата в формате PEM. |

## Практические сценарии

### Сценарий 1: Настройка PKI с использованием Easy-RSA

Easy-RSA остается эталонным инструментом для быстрого развертывания внутреннего центра сертификации. Рекомендуется для небольших и средних инфраструктур, где требуется простота управления без внешних зависимостей.

#### 1.1 Инициализация PKI

```bash
sudo apt update && sudo apt install easy-rsa
mkdir ~/easy-rsa-ca
cd ~/easy-rsa-ca
ln -s /usr/share/easy-rsa/* .
./easyrsa init-pki
```

#### 1.2 Создание Центра Сертификации (CA)

```bash
# Создание CA без пароля для автоматизации (в 2026 рекомендуется ECDSA)
./easyrsa build-ca nopass
```

#### 1.3 Генерация сертификатов

```bash
# Сертификат сервера
./easyrsa build-server-full server nopass

# Сертификат клиента
./easyrsa build-client-full client nopass

# Список отозванных сертификатов (CRL)
./easyrsa gen-crl
```

#### 1.4 Конфигурация виртуального хоста в Angie

```nginx
server {
    listen 443 ssl;
    server_name your.domain.com;

    ssl_certificate /etc/angie/ssl/server.crt;
    ssl_certificate_key /etc/angie/ssl/server.key;

    # Настройки mTLS
    ssl_client_certificate /etc/angie/ssl/ca.crt;
    ssl_crl /etc/angie/ssl/crl.pem;
    ssl_verify_client on;
    ssl_verify_depth 2;

    location / {
        add_header X-SSL-Client-Verify $ssl_client_verify;
        add_header X-SSL-Client-S-DN $ssl_client_s_dn;
        proxy_pass http://backend;
    }
}
```

### Сценарий 2: mTLS в модуле Stream (L4) с ACME (Angie 1.10+)

Защита TCP/UDP трафика (например, PostgreSQL) с автоматизацией сертификатов. Используется встроенный ACME для внутреннего PKI.

```nginx
stream {
    # Использование встроенного ACME для внутреннего PKI
    acme_client pki_internal {
        server https://vault.internal/v1/pki/acme/directory;
        contact mailto:admin@internal.local;
    }

    server {
        listen 5432 ssl;
        
        ssl_certificate     acme:pki_internal;
        ssl_certificate_key acme:pki_internal;

        # Конфигурация mTLS
        ssl_verify_client on;
        ssl_trusted_certificate /etc/angie/ssl/ca.crt;
        
        # TLS 1.3 Early Data для производительности
        ssl_early_data on;

        proxy_pass pg_cluster;
    }
}
```

### Сценарий 3: Динамическое обновление CRL и кэширование

В Angie использование переменных в `ssl_crl` позволяет мгновенно блокировать доступ без `reload`. В 2026 году рекомендуется комбинировать CRL с OCSP для гарантированной актуальности статуса отзыва.

```nginx
http {
    # Кэш для ускорения работы с динамическими путями
    ssl_certificate_cache max=1000 inactive=10m;

    server {
        listen 443 ssl;
        set $dynamic_crl "/etc/angie/ssl/crl.pem";
        
        ssl_client_certificate /etc/angie/ssl/ca.crt;
        ssl_crl $dynamic_crl;
        ssl_verify_client on;
        
        location / {
            # Проверка срока действия в логах
            access_log /var/log/angie/mtls_access.log combined if=$ssl_client_verify;
        }
    }
}
```

### Сценарий 4: Управление через Certificates API (Angie 1.12+)

Позволяет обновлять цепочки доверия программно без остановки сервиса.

```bash
# Пример обновления сертификата через API
curl -X POST -H "Content-Type: application/json" \
  --data '{"certificate": "/etc/angie/ssl/new_ca.crt"}' \
  http://127.0.0.1/api/v1/http/certificates/mtls_zone
```

### Сценарий 5: Защита административных интерфейсов

mTLS для административных панелей Angie (API, статус, прометеус). Позволяет ограничить доступ только доверенными операторами, исключая необходимость дополнительной аутентификации по паролю.

```nginx
# Защищенный доступ к API и статусу
location /api/v1/ {
    ssl_client_certificate /etc/angie/ssl/admin_ca.crt;
    ssl_verify_client on;
    ssl_verify_depth 2;
    
    proxy_pass http://127.0.0.1:8080/;
}

location /status {
    ssl_client_certificate /etc/angie/ssl/admin_ca.crt;
    ssl_verify_client on;
    stub_status;
}
```

### Сценарий 6: mTLS для внутренних API и бэкендов

Внутренние сервисы (payment gateway, CI/CD runners, monitoring agents) должны аутентифицироваться через mTLS, исключая использование слабых токенов или открытых портов.

```nginx
server {
    listen 443 ssl;
    server_name api.internal.example.com;

    ssl_certificate /etc/angie/ssl/server.crt;
    ssl_certificate_key /etc/angie/ssl/server.key;

    ssl_client_certificate /etc/angie/ssl/internal_ca.crt;
    ssl_verify_client on;
    ssl_verify_depth 2;

    # Передача информации о клиенте бэкенду
    proxy_set_header X-Client-Verify $ssl_client_verify;
    proxy_set_header X-Client-S-DN $ssl_client_s_dn;
    proxy_set_header X-Client-Serial $ssl_client_serial;

    location / {
        proxy_pass http://internal_backend;
    }
}
```

### Сценарий 7: mTLS с проверкой OCSP (Angie 1.12+)

Использование онлайн-проверки статуса сертификата для мгновенного отзыва доступа без распространения нового CRL на все узлы. OCSP-стаплинг поддерживается как для серверных, так и для клиентских сертификатов.

```nginx
server {
    listen 443 ssl;
    server_name secure.example.com;

    ssl_certificate /etc/angie/ssl/server.crt;
    ssl_certificate_key /etc/angie/ssl/server.key;

    # Настройки mTLS
    ssl_client_certificate /etc/angie/ssl/ca.crt;
    ssl_verify_client on;

    # OCSP для проверки статуса клиентских сертификатов
    ssl_ocsp on;
    ssl_ocsp_cache shared:CLIENT_OCSP:20m;

    # Резолвер для OCSP-резолверов CA
    resolver 1.1.1.1 8.8.8.8 valid=300s;

    location / {
        proxy_pass http://backend;
    }
}
```

### Сценарий 8: mTLS для Health Checks

При `ssl_verify_client on` локальные проверки (health checks от балансировщика, `curl` внутри контейнера) падают, так как не имеют сертификата. Решение — выделение отдельного виртуального хоста для проверок без mTLS.

```nginx
# Внешний HTTPS порт с mTLS
server {
    listen 443 ssl;
    server_name api.example.com;

    ssl_certificate /etc/angie/ssl/server.crt;
    ssl_certificate_key /etc/angie/ssl/server.key;

    ssl_client_certificate /etc/angie/ssl/clients_ca.crt;
    ssl_verify_client on;

    location / {
        proxy_pass http://backend;
    }
}

# Внутренний порт для health checks без mTLS
server {
    listen 8080;
    server_name localhost;

    location /healthz {
        access_log off;
        return 200 'OK';
    }
}
```

## Операции и команды

### Управление процессами Angie

```bash
# Проверка синтаксиса конфигурации
sudo angie -t
# → angie: the configuration file /etc/angie/angie.conf syntax is ok

# Проверка конфигурации с тестовой загрузкой сертификатов
sudo angie -T
# → показывает загруженные конфиги, ACME-клиенты и сертификаты

# Применение конфигурации (zero downtime)
sudo angie -s reload

# Перезапуск worker процессов
sudo angie -s reopen

# Остановка сервера
sudo angie -s stop

# Принудительная остановка
sudo angie -s quit
```

### Генерация и управление PKI (Easy-RSA)

```bash
# Инициализация PKI
./easyrsa init-pki

# Создание CA (ECDSA P-384)
./easyrsa build-ca nopass

# Выпуск сертификата сервера
./easyrsa build-server-full server nopass

# Выпуск клиентского сертификата
./easyrsa build-client-full client nopass

# Создание CRL
./easyrsa gen-crl

# Отзыв сертификата
./easyrsa revoke client
./easyrsa gen-crl
```

### Управление сертификатами через OpenSSL

```bash
# Просмотр сертификата
openssl x509 -in client.crt -text -noout
# → показывает субъект, издателя, сроки, алгоритм подписи

# Проверка соответствия ключа и сертификата
openssl x509 -noout -modulus -in client.crt | openssl md5
openssl rsa  -noout -modulus -in client.key | openssl md5
# → вывод должен совпадать

# Проверка срока действия
openssl x509 -in client.crt -noout -dates
# → notBefore=...
# → notAfter=...

# Генерация CSR (Certificate Signing Request)
openssl req -new -key client.key -out client.csr \
  -subj "/C=RU/ST=Moscow/L=Moscow/O=Example/OU=IT/CN=client"

# Подпись CSR корневым CA
openssl x509 -req -in client.csr -CA ca.crt -CAkey ca.key \
  -CAcreateserial -out client.crt -days 365 -sha384

# Проверка подписи сертификата
openssl verify -CAfile ca.crt client.crt
# → client.crt: OK
```

### Проверка mTLS-соединений

```bash
# Тестирование handshake с клиентским сертификатом
openssl s_client -connect your.domain.com:443 \
  -cert client.crt -key client.key -CAfile ca.crt -debug
# → показывает полную цепочку, алгоритмы, статус verify

# Проверка конкретного cipher
openssl s_client -connect your.domain.com:443 \
  -cert client.crt -key client.key -CAfile ca.crt \
  -cipher TLS_AES_256_GCM_SHA384

# Проверка поддержки TLS 1.3
openssl s_client -connect your.domain.com:443 -tls1_3

# Тестирование через curl
curl https://your.domain.com --insecure \
  --cert client.crt --key client.key --cacert ca.crt

# Проверка срока действия удаленного сертификата
echo | openssl s_client -connect your.domain.com:443 2>/dev/null \
  | openssl x509 -noout -dates

# Проверка цепочки сертификатов
openssl s_client -connect your.domain.com:443 -showcerts \
  -CAfile /etc/angie/ssl/ca.crt
```

### Управление CRL

```bash
# Генерация CRL (Easy-RSA)
./easyrsa gen-crl

# Проверка CRL
openssl crl -in crl.pem -text -noout
# → показывает отозванные серийные номера и даты

# Проверка сертификата в CRL
openssl verify -crl_check -CAfile ca.crt -CRLfile crl.pem client.crt
# → client.crt: OK (или ERROR)

# Конвертация CRL в DER (для некоторых приложений)
openssl crl -in crl.pem -outform DER -out crl.der
```

### Управление через Certificates API

```bash
# Просмотр текущих сертификатов
curl -s http://127.0.0.1/api/v1/http/certificates/ | jq .

# Обновление CA-сертификата через API
curl -X POST -H "Content-Type: application/json" \
  --data '{"certificate": "/etc/angie/ssl/new_ca.crt"}' \
  http://127.0.0.1/api/v1/http/certificates/mtls_zone

# Проверка статуса через API
curl -s http://127.0.0.1/api/v1/http/ssl/ | jq .

# Просмотр поддерживаемых шифров
curl -s http://127.0.0.1/api/v1/http/ssl/ciphers | jq .

# Статус OCSP Stapling
curl -s http://127.0.0.1/api/v1/http/ssl/ocsp/ | jq .
```

## Диагностика и тестирование

### Типичные ошибки mTLS-handshake

| Ошибка | Причина | Диагностика и решение |
|:-------|:--------|:----------------------|
| `400 Bad Request (No required SSL certificate was sent)` | Клиент не отправил сертификат | Проверьте что Root CA клиента добавлен в `ssl_client_certificate`. Убедитесь что клиентская конфигурация содержит `--cert` и `--key`. |
| `Handshake failure (Unknown CA)` | Сервер не доверяет издателю клиентского сертификата | Убедитесь что сертификат клиента подписан CA из `ssl_client_certificate`. Проверьте цепочку: `openssl verify -CAfile ca.crt client.crt`. |
| `certificate verify failed` | Ошибка в `ssl_client_certificate` | Убедитесь что файл содержит всю цепочку до Root CA. Проверьте права доступа: `600` для ключа, `644` для сертификата. |
| `CRL is not valid yet` | CRL имеет невалидную дату начала действия | Перегенерируйте CRL: `./easyrsa gen-crl`. Проверьте системное время на сервере (`timedatectl status`). |
| `OCSP response: no response` | OCSP-резолвер недоступен | Проверьте доступность порта 80/443 на CA. Убедитесь что `resolver` указан в конфигурации Angie. |
| `SSL: error:14094410:SSL routines:sslv3 alert handshake failure` | Клиент не поддерживает требуемые шифры или mTLS | Проверьте `ssl_ciphers` и `ssl_protocols`. Убедитесь что клиент поддерживает TLS 1.2+. |

### Диагностика через OpenSSL

```bash
# Полная диагностика handshake
openssl s_client -connect your.domain.com:443 \
  -cert client.crt -key client.key -CAfile ca.crt \
  -showcerts -tls1_2 -tlsextdebug

# Проверка конкретного алгоритма подписи
openssl s_client -connect your.domain.com:443 \
  -cert client.crt -key client.key -CAfile ca.crt \
  -sigalg rsa_pss_rsae_sha384

# Проверка цепочки сертификатов сервера
echo | openssl s_client -connect your.domain.com:443 \
  -servername your.domain.com 2>/dev/null \
  | openssl x509 -outform PEM > server.pem
```

### Проверка Angie runtime

```bash
# Проверка что mTLS активен (локальный curl без сертификата должен падать)
curl -k https://localhost:443/
# → 400 Bad Request (No required SSL certificate was sent)

# Проверка переменных mTLS в конфигурации
sudo angie -T | grep ssl_client

# Проверка логов mTLS
sudo tail -f /var/log/angie/mtls_access.log | grep FAILED
# → ищем клиентов с истекшими сертификатами

# Проверка статуса OCSP
sudo journalctl -u angie | grep -i ocsp
# → показывает ответы OCSP и ошибки резолва
```

## Лучшие практики

### Безопасность

1. **Используйте Private CA** вместо публичных CA для клиентских сертификатов. Публичные CA (Let's Encrypt) не выпускают сертификаты с расширением Client Auth из-за политики безопасности.
2. **ECDSA P-384** — минимальный стандарт 2026 года для подписи сертификатов. RSA 4096 допустим только для legacy-систем.
3. **TLS 1.3 обязателен** — `CertificateRequest` шифруется, исключая пассивное выявление требуемых CA злоумышленником.
4. **Корневой CA не храните на сервере** — используйте Intermediate CA для выдачи клиентских сертификатов. `ssl_client_certificate` должен содержать только Intermediate CA, а не Root CA.
5. **Права доступа:**
   ```bash
   chmod 600 /etc/angie/ssl/server.key
   chmod 644 /etc/angie/ssl/server.crt
   chmod 600 /etc/angie/ssl/ca.key
   chmod 644 /etc/angie/ssl/ca.crt
   chown root:angie /etc/angie/ssl/*
   ```
6. **SELinux/AppArmor:** При использовании переменных в `ssl_crl` или `ssl_certificate` убедитесь что политики разрешают чтение файлов рабочим процессам Angie.
7. **Объединение CA:** При использовании Intermediate CA объедините Root и Intermediate в один файл `ssl_client_certificate`, иначе клиенты с сертификатами от Intermediate CA не смогут пройти проверку.

### Жизненный цикл сертификатов

1. **Ротация:** Сертификаты должны иметь TTL не более 90 дней. Используйте ACME или Vault Agent для автоматической ротации.
2. **Резервное копирование:** Регулярно копируйте CA-ключи (`ca.key`) в защищенное хранилище. Потеря ключа означает необходимость перевыпуска всех сертификатов.
3. **Мониторинг сроков действия:**
   ```bash
   # Скрипт мониторинга (cron, ежедневно)
   echo | openssl s_client -connect your.domain.com:443 2>/dev/null \
     | openssl x509 -noout -enddate
   ```
4. **Отзыв:** При компрометации клиентского сертификата немедленно добавьте его в CRL и распространите. Проверяйте `ssl_crl` на актуальность.

### Производительность

1. **Кэширование сертификатов:** Обязательно включите `ssl_certificate_cache` при использовании переменных в путях к сертификатам:
   ```nginx
   ssl_certificate_cache max=2000 inactive=30m;
   ```
2. **kTLS:** Для снижения нагрузки на CPU включите Kernel TLS:
   ```nginx
   ssl_conf_command Options +KTLS;
   ```
   Требует OpenSSL 3.0+ и поддержки в ядре (`modprobe tls`).
3. **Сессии TLS:** Используйте сессии для снижения накладных расходов на рукопожатие:
   ```nginx
   ssl_session_cache shared:SSL:10m;
   ssl_session_timeout 1d;
   ssl_session_tickets off;
   ```
4. **QUIC оптимизации:** Для HTTP/3 с mTLS включите:
   ```nginx
   quic_gso on;
   quic_bpf on;
   ```

### Эксплуатация

1. **Единый CA:** Для инфраструктуры используйте один корневой CA с несколькими Intermediate CA для разных сред (dev, staging, prod).
2. **Логирование:** Включите детальное логирование mTLS для аудита:
   ```nginx
   log_format mtls_detail '$remote_addr - $ssl_client_s_dn_cn [$time_local] '
                          '"$request" $status $body_bytes_sent '
                          'ssl_protocol=$ssl_protocol ssl_cipher=$ssl_cipher '
                          'verify=$ssl_client_verify serial=$ssl_client_serial';
   access_log /var/log/angie/mtls_access.log mtls_detail;
   ```
3. **Multi-node синхронизация:** При использовании нескольких серверов Angie синхронизируйте CA-ключи, сертификаты и CRL через NFS, rsync или shared storage. Используйте Certificates API для централизованного управления.
4. **Тестирование:** После изменения `ssl_client_certificate` или `ssl_crl` всегда выполняйте:
   ```bash
   sudo angie -t
   sudo angie -s reload
   ```
5. **Откат:** Сохраняйте предыдущие версии конфигурации:
   ```bash
   sudo cp /etc/angie/angie.conf /etc/angie/angie.conf.bak
   ```

### Откат изменений

При проблемах с mTLS конфигурацией:
1. Сохраните рабочий конфиг: `sudo cp /etc/angie/angie.conf /etc/angie/angie.conf.bak`.
2. Восстановите предыдущую версию: `sudo cp /etc/angie/angie.conf.bak /etc/angie/angie.conf`.
3. Проверьте конфигурацию: `sudo angie -t`.
4. Примените: `sudo angie -s reload`.

## Дополнительная информация

### Ограничения и известные проблемы

1. **ACME для Client Auth:** Публичные CA (Let's Encrypt) не выпускают сертификаты с расширением Client Auth. Используйте Private CA (Vault, Easy-RSA) или корпоративные ACME-серверы.
2. **Переменные в ssl_client_certificate:** В Nginx/Angie переменные в `ssl_client_certificate` не поддерживаются (в отличие от `ssl_crl`). Для динамического выбора CA используйте Certificates API.
3. **Multi-server:** При использовании нескольких серверов Angie без shared storage необходимо синхронизировать `ssl_client_certificate`, `ssl_crl` и `ssl_certificate` вручную.
4. **Совместимость с Nginx:** Angie сохраняет полную обратную совместимость с директивами Nginx для mTLS. Все примеры Nginx работают в Angie без изменений.

### См. также

- [Настройка mTLS в Nginx (общие принципы)](../Nginx/Security/TLS_SSL/nginx_mtls_configuration.md)
- [Настройка TLS в Angie (базовая конфигурация)](./angie_tls_setup.md)
- [Обзор возможностей Angie](./angie_overview.md)
- [Модуль ACME в Angie](./angie_acme_module.md)
- [Автоматизация PKI с HashiCorp Vault](../../Vault/concepts.md)
- [Обзор TLS/SSL в Nginx](../Nginx/Security/TLS_SSL/nginx_tls_ssl_overview.md)
- [Диагностика SSL/TLS сертификатов](../../../../Security/Tools/ssl_certificate_diagnostics.md)
