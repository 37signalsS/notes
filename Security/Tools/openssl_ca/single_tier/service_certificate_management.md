# Управление сертификатами сервисов в одноуровневом CA

## Определения

Базовые понятия PKI (Public Key Infrastructure, Инфраструктура открытых ключей), такие как **CSR (Certificate Signing Request, Запрос на подпись сертификата)**, **SAN (Subject Alternative Name, Альтернативное имя субъекта)** и **CRL (Certificate Revocation List, Список отзыва сертификатов)**, подробно описаны в **[обзоре PKI](../../../Concepts/pki_overview.md)**.

В контексте управления сервисами:

- **DN (Distinguished Name, Отличительное имя)** — уникальная строка идентификации субъекта (например, `/C=RU/ST=Moscow/O=Org/CN=server.local`).
- **mTLS (Mutual TLS)** — механизм взаимной аутентификации, где сервис-клиент также обязан предъявить сертификат, подписанный доверенным CA.
- **Цепочка доверия (Chain of Trust)** — в одноуровневой схеме состоит из сертификата сервиса и корневого сертификата `ca.crt`.
- **Key Usage** — расширение X.509, определяющее криптографические операции, допустимые для данного сертификата (подпись, шифрование, подпись сертификатов и т.д.).
- **Extended Key Usage (EKU)** — расширение, уточняющее назначение сертификата (аутентификация сервера `serverAuth`, клиента `clientAuth`, подпись кода `codeSigning` и т.д.).

## Базовые концепции

### Жизненный цикл сертификата сервиса

Процесс управления сертификатом по формальному методу включает следующие этапы:

1. **Генерация ключа и CSR:** выполняется локально на целевом сервере или в защищенном контуре.
2. **Передача запроса:** CSR отправляется администратору CA. Приватный ключ **никогда** не покидает сервер.
3. **Валидация и подпись:** администратор проверяет CSR, настраивает SAN (Subject Alternative Name) и подписывает запрос через `openssl ca`.
4. **Установка:** сертификат (`.crt`) и корень (`ca.crt`) устанавливаются в приложение/ОС.
5. **Ротация:** плановый перевыпуск до истечения срока действия (рекомендуется за 10–20% до конца срока).
6. **Отзыв:** немедленное аннулирование в базе CA при компрометации.

### Принципы безопасности

- **Минимальные привилегии:** доступ к приватному ключу сервиса должен иметь только пользователь, под которым запущен процесс (например, `www-data` или `nginx`).
- **Использование SAN:** современные системы (браузеры, Go-сервисы, браузеры с 2026 года) полностью игнорируют поле `Common Name (CN)`, если присутствует `Subject Alternative Name`. SAN является обязательным.
- **Алгоритмы 2026:** рекомендуется переход с RSA-4096 на **ECDSA (secp384r1)** для снижения нагрузки на CPU при TLS-handshake.
- **Хранение приватных ключей:** ключи сервисов должны храниться с правами `600`, ни при каких обстоятельствах не должны передаваться по сети или фиксироваться в логах.
- **Ограничение срока действия:** для production-сервисов рекомендуется срок действия не более 90–180 дней. Это снижает риски при утечке ключа и упрощает ротацию.

### Сравнение методов выпуска сертификатов

| Характеристика | Формальный метод (`openssl ca`) | Быстрый метод (`openssl x509 -req`) |
| :--- | :--- | :--- |
| **База данных** | `index.txt` (полный учёт) | Отсутствует |
| **Учёт статусов** | Valid / Revoked / Expired | Нет |
| **Поддержка CRL** | Да | Нет |
| **Аудит операций** | Журнал в `index.txt` и `db/newcerts/` | Отсутствует |
| **Сложность настройки** | Средняя (требуется `openssl.cnf` и БД) | Низкая |
| **Рекомендация** | Infrastructure services, mTLS, Production | Локальные тесты, Docker, dev-среды |

Подробнее о подходах см. в **[обзоре архитектуры](./overview.md#подходы-к-управлению-ca)**.

## Практические сценарии

### Предварительные требования

#### Аппаратные и программные требования

- **ОС:** Linux (Debian/Ubuntu, RHEL/CentOS/Fedora, Alpine) или macOS. Инструкции tested на Linux x86_64.
- **OpenSSL:** версия 3.0.0 или выше. Проверка: `openssl version -a`.
- **CA:** развернутый одноуровневый CA по инструкции в **[Настройка CA](./ca_setup.md)**.
- **Права:** доступ пользователя с возможностью чтения файлов CA (`ca/ca.crt`, `ca/ca.key`). Для установки сертификатов в системные хранилища требуются права `root` или `sudo`.
- **Дисплей:** для операций с парольной фразой (если ключ CA шифруется) требуется терминал с поддержкой ввода пароля.

#### Проверка окружения

```bash
# Проверка версии OpenSSL
openssl version -a
# → OpenSSL 3.0.x ...

# Проверка доступных провайдеров (OpenSSL 3.0+)
openssl list -providers
# → Providers:
# →  ... (default provider)
# →  ... (legacy provider, при необходимости)
```

#### Установка зависимостей

```bash
# Debian/Ubuntu
sudo apt update && sudo apt install -y openssl libssl-dev

# RHEL/CentOS/Fedora
sudo dnf install -y openssl openssl-devel

# Alpine
sudo apk add openssl openssl-dev
```

### Выпуск сертификата (Key -> CSR -> CRT)

#### Шаг 1: Генерация на стороне сервиса

**Вариант А: Классический RSA (4096 бит)**
```bash
openssl genrsa -out service.key 4096
openssl req -new -key service.key -out service.csr \
    -subj "/C=RU/ST=Moscow/O=Dev/OU=IT/CN=service.local"
```

**Вариант Б: Современный ECDSA (P-384)**
```bash
openssl req -new -newkey ec:<(openssl ecparam -name secp384r1) -nodes \
    -keyout service.key -out service.csr \
    -subj "/C=RU/ST=Moscow/O=Dev/OU=IT/CN=service.local"
```

**Вариант В: Ed25519 (максимальная производительность)**
```bash
openssl genpkey -algorithm Ed25519 -out service.key
openssl req -new -key service.key -out service.csr \
    -subj "/C=RU/ST=Moscow/O=Dev/OU=IT/CN=service.local"
```

> **Важно:** Приватный ключ `service.key` должен храниться с правами `600` и никогда не покидать целевой сервер.

#### Шаг 2: Подпись администратором CA

Администратор проверяет запрос и вносит DNS/IP в `ca/openssl.cnf` (секция `[alt_names]`):

```ini
[alt_names]
DNS.1 = service.local
DNS.2 = *.service.local
IP.1  = 10.0.0.50
```

> **Рекомендация:** для production-сред используйте `copy_extensions = copy` в `ca/openssl.cnf`. Это позволяет передавать SAN через CSR, не меняя конфиг CA для каждого нового сервиса.

Выполнение подписи:

```bash
cd ca
openssl ca -config openssl.cnf -in ../service.csr -out ../service.crt \
    -extensions v3_req -notext
```

**Ключевые флаги `openssl ca`:**
- `-config openssl.cnf` — путь к конфигурационному файлу CA.
- `-in ../service.csr` — входной запрос на подпись.
- `-out ../service.crt` — путь для сохранения подписанного сертификата.
- `-extensions v3_req` — секция расширений, применяемая к конечному сертификату (определена в `openssl.cnf`).
- `-notext` — не включать текстовое представление сертификата в вывод.

**Expected output:**
```
Using configuration from openssl.cnf
Check that the request matches the signature
Signature ok
The Subject's Distinguished Name is as follows
...
Certificate Details:
...
1 out of 1 certificate requests certified, commit? [y/n]: y
Write out database with 1 new entries
Data Base Updated
```

### Выпуск клиентского сертификата для mTLS

Для взаимной аутентификации (mTLS) клиентский сертификат выпускается аналогично серверному, но с расширением `extendedKeyUsage = clientAuth`.

#### Шаг 1: Генерация ключа и CSR на стороне клиента

```bash
openssl genrsa -out client.key 4096
openssl req -new -key client.key -out client.csr \
    -subj "/C=RU/ST=Moscow/O=Dev/OU=IT/CN=service-client"
```

#### Шаг 2: Подпись администратором CA

В `ca/openssl.cnf` добавьте или используйте секцию `[v3_client]`:
```ini
[v3_client]
basicConstraints       = CA:FALSE
keyUsage               = nonRepudiation, digitalSignature, keyEncipherment
extendedKeyUsage       = clientAuth
subjectKeyIdentifier   = hash
authorityKeyIdentifier = keyid,issuer
```

Выполните подпись:
```bash
cd ca
openssl ca -config openssl.cnf -in ../client.csr -out ../client.crt \
    -extensions v3_client -notext
```

### Управление SAN в production

При выпуске сертификатов для сервисов, развернутых в нескольких средах (Dev/QA/Prod), используйте отдельные SAN для каждой среды или переissuedвайте сертификаты при изменении окружения.

**Паттерн: SAN по окружению**

```ini
[alt_names]
# Dev
DNS.1 = service.dev.local
IP.1  = 10.0.1.50

# QA
DNS.2 = service.qa.local
IP.2  = 10.0.2.50

# Prod
DNS.3 = service.prod.local
IP.3  = 10.0.3.50
```

> **Важно:** для сервисов, развернутых за load balancer или reverse proxy (Nginx, HAProxy), SAN должен содержать внешние доменные имена, а не внутренние IP.

### Установка корневого сертификата в доверенные хранилища

#### Операционные системы

**Linux (Debian/Ubuntu/Angie):**
```bash
sudo cp ca.crt /usr/local/share/ca-certificates/internal-ca.crt
sudo update-ca-certificates
```

**Linux (RHEL/CentOS/Fedora):**
```bash
sudo cp ca.crt /etc/pki/ca-trust/source/anchors/
sudo update-ca-trust
```

#### Docker-контейнеры

При сборке образа добавьте сертификат в системное хранилище внутри Dockerfile:
```dockerfile
COPY ca.crt /usr/local/share/ca-certificates/internal-ca.crt
RUN update-ca-certificates
```

#### Java (KeyStore/TrustStore)

Java использует собственное хранилище `cacerts`. Для добавления корня:
```bash
keytool -import -alias internal-ca -file ca.crt \
    -keystore $JAVA_HOME/lib/security/cacerts -storepass changeit -noprompt
```

### Отзыв и работа с CRL

Если ключ сервиса утерян, его нужно пометить как `Revoked` в базе CA и выпустить новый список отзыва.

```bash
cd ca

# 1. Отзыв (меняет статус в index.txt на 'R')
openssl ca -config openssl.cnf -revoke ../service.crt

# 2. Перегенерация CRL
openssl ca -config openssl.cnf -gencrl -out crl.pem
```

Для того чтобы отзыв работал, приложения должны быть настроены на проверку файла `crl.pem`. В Nginx это делается директивой `ssl_crl /etc/nginx/ssl/ca/crl.pem;`.

### Верификация перед деплоем

Всегда проверяйте валидность пары «ключ-сертификат» перед перезагрузкой сервиса:

```bash
# Проверка соответствия (хеши должны совпасть)
openssl x509 -noout -modulus -in service.crt | openssl sha256
openssl rsa -noout -modulus -in service.key | openssl sha256

# Проверка цепочки
openssl verify -CAfile ca.crt service.crt
```

## Типичные ошибки и диагностика

### Ошибка: `unable to load certificate` / `certificate verify failed`

**Причина:** Путь к `ca.crt` или `ca.key` указан неверно, файлы повреждены или у процесса нет прав на чтение.

**Диагностика:**
```bash
# Проверка доступности файлов
ls -la ca/ca.crt ca/ca.key

# Проверка читаемости
file ca/ca.crt ca/ca.key
openssl x509 -in ca/ca.crt -noout -text
```

### Ошибка: `Verify return code: 20 (unable to get local issuer certificate)`

**Причина:** Корневой CA не установлен в доверенное хранилище операционной системы или не передан через `-CAfile`.

**Решение:**
```bash
# Для проверки вручную
openssl s_client -connect my-service.local:443 -servername my-service.local -CAfile ca/ca.crt </dev/null | grep "Verify return code"
# → Verify return code: 0 (ok)

# Установка корня в ОС
# Debian/Ubuntu
sudo cp ca/ca.crt /usr/local/share/ca-certificates/internal-ca.crt
sudo update-ca-certificates

# RHEL/CentOS/Fedora
sudo cp ca/ca.crt /etc/pki/ca-trust/source/anchors/
sudo update-ca-trust
```

### Ошибка: `Verify return code: 21 (unable to verify the first certificate)`

**Причина:** Сервер передает только leaf-сертификат без промежуточного CA. В одноуровневой архитектуре это означает, что сервер настроен некорректно.

**Диагностика:**
```bash
# Просмотр цепочки, передаваемой сервером
openssl s_client -connect my-service.local:443 -servername my-service.local -showcerts </dev/null | grep -E "s:|i:"
# → s:/CN=my-service.local
# → i:/CN=My Private Root CA
```

### Ошибка: `signature routines::unsupported algorithm`

**Причина:** Алгоритм хеширования, указанный в `-sha384`, не поддерживается провайдером OpenSSL 3.0+.

**Решение:** используйте `-sha256` или явно укажите провайдер Legacy:
```bash
openssl x509 -req -in service.csr -CA ca/ca.crt -CAkey ca/ca.key -CAcreateserial \
    -out service.crt -days 90 -sha256 -provider legacy
```

### Ошибка: `Error loading extension` / `invalid extension`

**Причина:** Синтаксис `subjectAltName` в `-extfile` указан неверно (отсутствуют `DNS:` или `IP:`, некорректные пробелы).

**Решение:** проверьте синтаксис:
```bash
# Корректный формат
subjectAltName=DNS:service.local,DNS:www.service.local,IP:10.0.0.5

# Некорректные примеры:
# subjectAltName=service.local           ← нет префикса DNS:
# subjectAltName=DNS:service.local IP:10.0.0.5  ← запятая вместо пробела
```

### Ошибка: `serial file already exists` / `trying to commit certificate twice`

**Причина:** Файл `.srl` с серийным номером уже существует, и OpenSSL не может его прочитать или записать.

**Решение:**
```bash
# Проверка содержимого
cat service.srl

# Переинициализация (если нет конфликта с другими сертификатами)
echo "1000" > service.srl
```

### Ошибка: `No value for key` / `unable to find key`

**Причина:** Флаг `-CAkey` указан, но ключ зашифрован парольной фразой, и OpenSSL не может его прочитать в неинтерактивном режиме.

**Решение:** либо вводите парольную фразу при запросе, либо используйте незашифрованный ключ для тестовых сред.

### Ошибка: `database locked`

**Причина:** Другой процесс (например, параллельный вызов `openssl ca`) удерживает блокировку на файле `index.txt`.

**Решение:**
```bash
# Проверка блокировок
ls -la ca/db/index.txt.*

# Удаление устаревших блокировок (только если нет запущенных процессов openssl ca)
rm -f ca/db/index.txt.lock
```

## Рекомендации и лучшие практики

### Предварительная проверка перед деплоем

Всегда выполняйте комплексную проверку перед установкой сертификата в production:

```bash
# 1. Проверка соответствия ключа и сертификата
openssl x509 -noout -modulus -in service.crt | openssl sha256
openssl rsa -noout -modulus -in service.key | openssl sha256
# Хеши должны совпасть

# 2. Проверка цепочки доверия
openssl verify -CAfile ca/ca.crt service.crt
# → service.crt: OK

# 3. Проверка срока действия
openssl x509 -in service.crt -noout -dates

# 4. Проверка SAN (обязательно для современных браузеров)
openssl x509 -in service.crt -noout -text | grep -A 1 "Subject Alternative Name"
# → DNS:service.local, DNS:www.service.local, IP:10.0.0.5
```

### Безопасность при работе с утилитами

- **Никогда не передавайте приватный ключ CA по сети.** Все операции с `ca.key` выполняйте на машине, где хранится CA.
- **Храните `service.key` с правами `600`.** Утечка приватного ключа сервиса позволяет impersonate-атаки.
- **Проверяйте `issuer` перед установкой:** убедитесь, что сертификат выпущен именно вашим CA, а не публичным центром.
- **Используйте `-CAfile` явно:** не полагайтесь на системное хранилище CA в скриптах — указывайте корень явно.

### Автоматизация в CI/CD

Для встраивания диагностики в пайплайны используйте неинтерактивные флаги:

```bash
# Неинтерактивная проверка
if openssl verify -CAfile ca/ca.crt service.crt | grep -q "OK"; then
    echo "Certificate is valid"
else
    echo "Certificate verification failed"
    exit 1
fi

# Проверка срока действия (если осталось меньше 30 дней — fail)
openssl x509 -in service.crt -noout -checkend 2592000 || echo "CRITICAL: Certificate expires soon"
```

### Ротация сертификатов

Рекомендуется реализовать автоматическую ротацию за 30–60 дней до истечения срока:

```bash
# Проверка сертификатов в директории сервиса
for crt in /etc/nginx/ssl/*.crt; do
    if openssl x509 -in "$crt" -noout -checkend 2592000; then
        echo "$(basename $crt): OK"
    else
        echo "$(basename $crt): WARNING - expires within 30 days"
    fi
done
```

### Wildcard-сертификаты через одноуровневый CA

Wildcard-сертификаты (`*.service.local`) выпускаются аналогично обычным, но SAN должен содержать wildcard и корневой домен:

```ini
# ca/openssl.cnf — секция [alt_names]
[alt_names]
DNS.1 = *.service.local
DNS.2 = service.local
IP.1  = 10.0.5.10
```

```bash
cd ca
openssl ca -config openssl.cnf -in ../service.csr -out ../service.crt \
    -extensions v3_req -notext -batch
```

Проверка:

```bash
openssl x509 -in service.crt -noout -text | grep -A 2 "Subject Alternative Name"
# → X509v3 Subject Alternative Name:
# →     DNS:*.service.local, DNS:service.local, IP Address:10.0.5.10
```

> **Ограничение wildcard:** покрывает только ОДИН уровень поддоменов:
> - `api.service.local` — доверяет (да)
> - `v2.api.service.local` — НЕ доверяет (нет)
> - `service.local` — НЕ доверяет (нет, нужен отдельный SAN)
>
> Для глубоких поддоменов перечисляйте их явно в SAN.

### Автоматизация ротации сертификатов

#### Скрипт проверки и автоматической переподписи

```bash
#!/bin/bash
# cert-renew.sh — проверка срока действия и автоматическая ротация

CA_DIR="/opt/ca"
CERT_DIR="/etc/nginx/ssl"
WARN_DAYS=30

for crt in "$CERT_DIR"/*.crt; do
    [ -f "$crt" ] || continue

    if ! openssl x509 -in "$crt" -noout -checkend $((WARN_DAYS * 86400)) 2>/dev/null; then
        SUBJECT=$(openssl x509 -in "$crt" -noout -subject -nameopt multiline | grep commonName | awk '{print $3}')
        EXPIRY=$(openssl x509 -in "$crt" -noout -enddate | cut -d= -f2)
        echo "WARNING: $crt ($SUBJECT) истекает: $EXPIRY"

        # Автоматическая переподпись
        KEY="${crt%.crt}.key"
        CSR="${crt%.crt}.csr"

        openssl genrsa -out "$KEY" 4096 2>/dev/null
        openssl req -new -key "$KEY" -out "$CSR" \
            -subj "$(openssl x509 -in "$crt" -noout -subject | sed 's/^subject=//')" 2>/dev/null

        cd "$CA_DIR"
        if openssl ca -config openssl.cnf -in "$CSR" -out "${crt}.new" \
            -extensions v3_req -notext -batch 2>/dev/null; then
            mv "${crt}.new" "$crt"
            echo "RENEWED: $crt"
            systemctl reload nginx
        else
            echo "ERROR: Failed to renew $crt"
            rm -f "${crt}.new"
        fi
        rm -f "$CSR"
    fi
done
```

#### Cron-задача для ежедневной проверки

```bash
# crontab root: ежедневная проверка в 03:00
0 3 * * * /opt/scripts/cert-renew.sh >> /var/log/cert-renewal.log 2>&1
```

### Интеграция с Nginx

После выпуска сертификата через ваш одноуровневый CA настройте Nginx:

```nginx
server {
    listen 443 ssl http2;
    server_name service.local;

    ssl_certificate     /etc/nginx/ssl/service.crt;
    ssl_certificate_key /etc/nginx/ssl/service.key;

    # Проверка клиентских сертификатов (mTLS)
    # ssl_client_certificate /etc/nginx/ssl/ca.crt;
    # ssl_verify_client on;

    # Hardened TLS
    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_ciphers ECDHE-ECDSA-AES256-GCM-SHA384:ECDHE-RSA-AES256-GCM-SHA384:ECDHE-ECDSA-CHACHA20-POLY1305:ECDHE-RSA-CHACHA20-POLY1305:ECDHE-ECDSA-AES128-GCM-SHA256:ECDHE-RSA-AES128-GCM-SHA256;
    ssl_prefer_server_ciphers on;
    ssl_session_cache shared:SSL:10m;
    ssl_session_timeout 10m;

    # CRL для mTLS (проверка отозванных)
    # ssl_crl /etc/nginx/ssl/crl.pem;

    location / {
        proxy_pass http://backend;
    }
}

server {
    listen 80;
    server_name service.local;
    return 301 https://$host$request_uri;
}
```

Проверка:

```bash
nginx -t && systemctl reload nginx

# Верификация TLS
openssl s_client -connect service.local:443 -servername service.local \
    -CAfile /etc/nginx/ssl/ca.crt </dev/null | grep "Verify return code"
# → Verify return code: 0 (ok)
```

### Экспорт в PKCS#12 (для Java/Windows)

Для Java KeyStore, IIS или Windows Certificate Store:

```bash
# Полный контейнер с цепочкой CA
openssl pkcs12 -export -out service.p12 \
    -in service.crt -inkey service.key \
    -certfile ca/ca.crt \
    -name "service.local" \
    -passout pass:changeit

# Импорт в Java KeyStore
keytool -importkeystore \
    -srckeystore service.p12 -srcstoretype PKCS12 -srcstorepass changeit \
    -destkeystore service.jks -deststoretype JKS -deststorepass changeit
```

Подробнее о конвертации форматов — в [Конвертация форматов и продвинутая конфигурация](./formats_and_advanced_config.md).

## Ограничения и крайние случаи

- **Отсутствие статусов сертификатов:** в одноуровневой архитектуре без формального метода (`openssl ca` с `index.txt`) нет возможности отслеживать статус (Valid/Revoked/Expired) без ручного сканирования CRL.
- **CRL в одноуровневой схеме:** CRL должен генерироваться вручную. В формальном методе это делается через `openssl ca -gencrl`. В быстром методе CRL может отсутствовать полностью.
- **Совместимость оболочек:** команды с `<(printf ...)` требуют Bash. В Alpine Linux, Ubuntu/Debian (где `/bin/sh` → dash) используйте явный вызов Bash или временные файлы.
- **Сервисы с жесткими требованиями к совместимости:** некоторые устаревшие системы (например, старые Java-приложения до версии 8) могут требовать RSA-ключей и специфических расширений.
- **Накладные расходы на проверку:** при росте числа сертификатов (>100) проверка целостности через `index.txt` становится предпочтительнее ручных команд.
- **Регуляторные требования:** в некоторых отраслях (финансы, медицина) требуется использование двухуровневой архитектуры и сертифицированных криптографических средств (СКЗИ).

## Очистка и откат изменений

### Удаление временных файлов диагностики

```bash
# Удаление временных сертификатов и ключей
rm -f service.crt service.key service.csr service.srl

# Удаление установленных корневых сертификатов из доверенных хранилищ ОС
# Debian/Ubuntu
sudo update-ca-certificates --fresh

# RHEL/CentOS/Fedora
sudo update-ca-trust
```

### Откат тестового окружения

Если сертификат был установлен в приложение (Nginx, Apache, Java Keystore), выполните откат в обратном порядке:

1. Удалите сертификат из конфигурации сервиса.
2. Перезапустите сервис.
3. Удалите корневой сертификат из доверенного хранилища ОС/контейнера.
4. Удалите файлы CA и сгенерированные ключи.

### Отзыв всех сертификатов (экстренный сценарий)

```bash
cd ca

# Отзыв всех сертификатов через скрипт (формальный метод)
for cert in db/newcerts/*.pem; do
    openssl ca -config openssl.cnf -revoke "$cert"
done

# Генерация нового CRL
openssl ca -config openssl.cnf -gencrl -out crl.pem

# Распространение нового CRL на все сервисы
```

## Дополнительная информация

### Связанные темы

- **[Обзор одноуровневого CA](./overview.md)** — архитектурные подходы и сравнение.
- **[Настройка CA](./ca_setup.md)** — создание корневой инфраструктуры и `openssl.cnf`.
- **[Утилиты и диагностика OpenSSL](./common_utilities.md)** — команды глубокой проверки сертификатов.
- **[Конвертация форматов](./formats_and_advanced_config.md)** — PEM/DER/PKCS#12, продвинутый openssl.cnf.
- **[Диагностика SSL/TLS сертификатов](../../ssl_certificate_diagnostics.md)** — решение типичных ошибок при настройке TLS.
- **[Быстрый метод выпуска](./quick_method.md)** — упрощенная подпись без базы данных.
