# Certificate Transparency (CT) — прозрачность сертификатов

**Актуально для:** Certificate Transparency (RFC 9162, 2026; браузеры — Chrome 148, Firefox 135+, Safari 18, Edge 148)

## Определения

**Certificate Transparency (CT)** — инфраструктура публичного логирования сертификатов X.509. Все выпущенные сертификаты записываются в публичные, только для чтения, криптографически верифицируемые логи, что позволяет обнаруживать ошибочно или злонамеренно выпущенные сертификаты. Произошло эволюционное развитие: RFC 6962 (январь 2024) был заменён на **RFC 9162** (Certificate Transparency Version 2.0).

**CT Log** — только для чтения, append-only структура данных, куда записываются все выпущенные сертификаты. Реализуется как Merkle Tree (хэш-дерево) для обеспечения целостности.

**SCT (Signed Certificate Timestamp)** — криптографическая подпись, подтверждающая, что сертификат был добавлен в CT Log. Содержит: версию SCT, имя лога, время включения, подпись.

**Log ID** — уникальный идентификатор CT-лога (SHA-256 хэш публичного ключа лога).

**Pre-certificate** — предварительный сертификат, выпущенный CA перед финальной подписью. Содержит `poison` extension (OID 1.3.6.1.4.1.11129.2.4.3), указывающую, что сертификат должен быть залогирован в CT Log.

**Log List** — подписанный список всех известных CT-логов с их состояниями (Qualified, Usable, ReadOnly, Retired, Pending). Chrome публикует обновления Ежедневно.

**Monitor** — наблюдатель, отслеживающий CT-логи на наличие подозрительных сертификатов (например, выпущенных без авторизации).

**Оператор лога (Log Operator)** — организация, которая эксплуатиует CT Log (Google, DigiCert, Sectigo и др.). Для CT Compliance требуется минимум 2 SCT от разных операторов логов.

## Концепции и архитектура

### Зачем нужна CT

1. **Обнаружение поддельных сертификатов:** если CA (или злоумышленник с доступом к CA) выпустит сертификат для чужого домена, владелец домена увидит это в CT-логе
2. **Ответственность CA:** публичность логов создаёт давление на CA — невозможно тайно выпустить сертификат
3. **Compliance:** Chrome, Firefox, Safari, Edge требуют SCT для доверяемых сертификатов (начиная с 2018 года для Chrome; Firefox — начиная с версии 135, февраль 2025)
4. **Инструменты мониторинга:** сервисы (crt.sh, Facebook CT Monitor) позволяют отслеживать сертификаты для вашего домена

### Архитектура CT

```text
┌──────────┐  submit pre-   ┌──────────┐  append to    ┌──────────┐
│    CA    │  certificate   │  CT Log  │  Merkle Tree  │  Merkle  │
│          │───────────────▶│          │──────────────▶│  Tree    │
└──────────┘               └──────────┘               └──────────┘
    │                           │
    │  receives SCT            │  returns SCT
    │◀────────                   │
    │
    │ embeds SCT
    │ in certificate
    ▼
┌──────────┐
│  Leaf    │  (certificate + SCTs)
│  Cert    │
└──────────┘
    │
    │ client verifies
    ▼
┌──────────┐
│ Client   │  verifies SCTs against
│          │  CT log
└──────────┘
```

### SCT доставка — три метода

| Метод | Описание | Применение |
| :--- | :--- | :--- |
| Embedded SCT | SCT встроен в X.509 расширение сертификата | Public CA (Let's Encrypt, DigiCert) |
| TLS Extension | SCT передаётся как экстеншн TLS handshake | Когда невозможно встроить в сертификат |
| OCSP Stapling | SCT в ответе OCSP | Дополнительный канал доставки; в Chrome < 148 |

### Требования браузеров (2026)

CT Compliance зависит от браузера, возраста сертификата и количеств SCT от разных операторов логов:

| Браузер | Минимум SCT (embedded) | Минимум SCT (TLS/OCSP) | Примечание |
| :--- | :--- | :--- | :--- |
| Chrome 148+ | 2 (≤180 дней) / 3 (>180 дней) | 2 | ≥1 SCT от Qualified/Usable лога; ≥2 от разных операторов |
| Firefox 135+ | 2 (≤180 дней) / 3 (>180 дней) | 2 | ≥1 SCT от Admissible лога; ≥2 от разных операторов |
| Safari 18+ | 2 (≤180 дней) / 3 (181–398 дней) | — | ≥1 SCT от RFC 6962-compliant лога; максимум 1 SCT от одного оператора считается |
| Edge 148+ | 2 (≤180 дней) / 3 (>180 дней) | 2 | На базе Chromium, как Chrome |

**Примечание:** для сертификатов срока действия >180 дней требования жестче — 3 SCT от 3 разных логов. For enterprise/internal CAs в Firefox (не входит в корневой программу Mozilla) CT не требуется.

### Жизненный цикл CT

1. **CA выпускает pre-certificate** с `poison` extension
2. **CA отправляет pre-certificate в CT Log** (или использует TLS extension / OCSP stapling для доставки SCT)
3. **CT Log возвращает SCT** — криптографическую подпись с меткой времени
4. **CA встраивает SCT** в финальный сертификат (embedded SCT) или передаёт через TLS extension
5. **Клиент** (браузер/curl/openssl) проверяет SCT при TLS handshake
6. **Monitor** периодически сканирует CT-логи на наличие сертификатов для вашего домена

### Google CT Logs (2026)

| Log | URL | Статус |
| :--- | :--- | :--- |
| Argon2026h1 | `https://ct.googleapis.com/logs/us1/argon2026h1/` | Usable |
| Argon2026h2 | `https://ct.googleapis.com/logs/us1/argon2026h2/` | Usable (начиная с 2026-07-01) |
| Xenon2026h1 | `https://ct.googleapis.com/logs/eu1/xenon2026h1/` | Usable |
| Xenon2026h2 | `https://ct.googleapis.com/logs/eu1/xenon2026h2/` | Usable (начиная с 2026-07-01) |

Другие операторы: DigiCert (Wyvern, Sphinx), Sectigo (Sabre, Mammoth), TrustAsia.

## Практические сценарии

### Пререквизиты

- **TLS-сервер:** nginx/Apache/Balancer с сертификатом от публичной CA (Let's Encrypt, DigiCert) или внутренней PKI с CT поддержкой
- **Доступ к CT Logs:** для проверки — `curl` или `openssl s_client -ct`
- **Для внутренних CA:** развёрнутый CT Log (Trillian) или acceptance of CT-free mode для enterprise-корневых сертификатов в Firefox
- **Для мониторинга:** доступ к crt.sh API или локальный CT Log

### Проверка CT-статуса сертификата

```bash
# Проверка SCT в сертификате
openssl x509 -in leaf.crt -text -noout | grep -A 5 "CT Precertificate SCTs"
# → CT Precertificate SCTs:
# →   Signed Certificate Timestamp:
# →     Version: v1 (0x0)
# →     Log ID: ...
# →     Timestamp: Oct 21 12:00:00 2026 GMT
# →     Extensions: ...
# →     Signature Algorithm: ecdsa-with-SHA256
# →     Signature: ...
```

### Проверка SCT через openssl s_client

```bash
# Проверка SCT при подключении к серверу
openssl s_client -connect myservice.local:443 -servername myservice.local -ct </dev/null 2>&1 | grep -A 3 "SCT"
# → Signed Certificate Timestamp:
# →   Version: v1 (0x0)
# →   Log ID: ...
# →   Timestamp: ...
```

### Проверка через онлайн-инструменты

```bash
# crt.sh — поиск сертификатов по домену
curl -s "https://crt.sh/?q=mycompany.com&output=json" | jq '.[] | {name_value, issuer_name, not_before, not_after}'

# Проверка CT через Google Argon2026h1
curl -s "https://ct.googleapis.com/logs/us1/argon2026h1/ct/v1/get-entries?start=0&end=0" | jq .
```

### Настройка CT-мониторинга

#### crt.sh (локальный экземпляр для приватных доменов)

```bash
# Установка crt.sh для внутреннего мониторинга
git clone https://github.com/crtsh/crt.sh.git
cd crt.sh

# Требуется PostgreSQL с расширением pg_trgm
# Конфигурация в db.sql и web/
```

#### Facebook CT Monitor

```bash
# Мониторинг через Facebook CT API
curl -s "https://graph.facebook.com/certificates?query=mycompany.com&fields=name_value,issuer_name,not_before,not_after" | jq .
```

#### Prometheus + CT Exporter

```yaml
# prometheus.yml
scrape_configs:
  - job_name: 'ct_monitor'
    static_configs:
      - targets: ['ct-exporter:9090']
    metrics_path: /metrics
    params:
      domain: ['mycompany.com']
```

### Интеграция с внутренней PKI

Для внутренних CA CT-логи не обязательны, но полезны для сред с >100 узлами:

```bash
# Развертывание Trillian (Google CT Log) для внутренних сертификатов
git clone https://github.com/google/trillian.git
cd trillian

# Быстрый запуск через Docker Compose
docker-compose up -d

# Инициализация лога
go run ./cmd/trillian_log_server/integration/ct_integration.go \
  -logtostderr -v -http_endpoint :8091 -grpc_endpoint :8092 \
  -storage_backend mysql -mysql_uri "root@tcp(localhost:3306)/ctlog"
```

### Настройка CT для Nginx

```nginx
# Nginx автоматически отправляет SCT, если они встроены в сертификат
# Дополнительная настройка не требуется

server {
    listen 443 ssl http2;
    server_name myservice.local;

    ssl_certificate     /etc/ssl/certs/leaf.crt;  # сертификат с встроенными SCT
    ssl_certificate_key /etc/ssl/private/leaf.key;
}
```

### Настройка CT для Apache

```apache
# Apache также использует встроенные SCT из сертификата
# Дополнительная настройка не требуется

<VirtualHost *:443>
    ServerName myservice.local

    SSLEngine on
    SSLCertificateFile      /etc/ssl/certs/leaf.crt
    SSLCertificateKeyFile   /etc/ssl/private/leaf.key
</VirtualHost>
```

## Операции и команды

### Извлечение Log ID из сертификата

```bash
# Просмотр всех Log ID из сертификата
openssl x509 -in leaf.crt -text -noout | grep -A 3 "CT Precertificate SCTs"
# →     Log ID: 29:... (Google Argon2026h1)
# →     Log ID: f2:... (DigiCert)
```

### Проверка статуса CT Log

```bash
# Статус Google Argon2026h1
curl -s "https://ct.googleapis.com/logs/us1/argon2026h1/ct/v1/get-sth" | jq .
# → {"sha256_root_hash":"...","tree_size":123456,"timestamp":...,"tree_head_signature":"..."}

# Статус DigiCert
curl -s "https://ct.googleapis.com/logs/argon2026/ct/v1/get-sth" | jq .
```

### Генерация backup-ключа для сертификата

```bash
# Генерация RSA ключа 2048 бит
openssl genrsa -out /etc/ssl/private/backup.key 2048

# Или ECDSA ключ
openssl ecparam -name prime256v1 -genkey -noout -out /etc/ssl/private/backup.key
```

### Извлечение публичного ключа для pinning

```bash
# Извлечение SPKI (SubjectPublicKeyInfo) и вычисление SHA-256
openssl x509 -in leaf.crt -pubkey -noout | openssl pkey -pubin -outform DER | openssl dgst -sha256 -binary | openssl enc -base64
# → YLh1dUR9y6Kja30RrAn7JKnbQG/uEtLMkBgFF2Fuihg=

# с curl: curl --pinnedpubkey 'sha256//<hash>' https://myservice.local
```

## Устранение неполадок

| Ошибка | Причина | Решение |
| :--- | :--- | :--- |
| `SSL: CERTIFICATE_IS_NOT_SCT_LOGGED` | Сертификат не содержит SCT | Перевыпустите сертификат с CT (ACME-клиенты добавляют SCT автоматически) |
| `Missing SCT` | SCT не встроен и не доставляется через TLS | Используйте CA с поддержкой CT (Let's Encrypt, DigiCert) |
| `MOZILLA_PKIX_ERROR_INSUFFICIENT_CERTIFICATE_TRANSPARENCY` | Недостаточно SCT для Firefox 135+ | Убедитесь, что CA отправляет ≥2 SCT от разных логов |
| `CT log list expired` | Chrome: лог list старше 70 дней | Обновите Chrome или компонент CT Log List |
| Ложные срабатывания мониторинга | Выпущен сертификат для поддомена | Настройте точные правила мониторинга (regex для домена) |
| `Failed to verify SCT` в openssl s_client | OpenSSL < 1.1.0 не поддерживает CT | Используйте OpenSSL 1.1.0+ или проверяйте через crt.sh |

## Лучшие практики

1. **Используйте ACME-клиенты** (certbot, lego) — они автоматически добавляют SCT при выпуске сертификатов Let's Encrypt
2. **Мониторьте CT-логи** для своего домена — настройте алерты на новые сертификаты (crt.sh, Facebook CT)
3. **Для сертификатов >180 дней** запрашивайте 3 SCT от 3 разных операторов логов
4. **Для внутренних CA:** CT-логи опциональны, но рекомендуются для сред с >100 узлами
5. **Регулярно проверяйте статус CT Logs** — используйте `get-sth` endpoint для проверки доступности и актуальности
6. **Комбинируйте** CT-мониторинг с Certificate Pinning для максимальной защиты
7. **Не обходите CT** — браузеры не доверят сертификатам без SCT (кроме enterprise-корневых в Firefox)
8. **Для enterprise-корневых сертификатов в Firefox** используйте GPO/preference `security.pki.certificate_transparency.mode=0` для локальных CA

## Дополнительная информация

- **RFC 9162** — [Certificate Transparency Version 2.0](https://datatracker.ietf.org/doc/html/rfc9162) (текущая версия)
- **RFC 6962** — [Certificate Transparency](https://datatracker.ietf.org/doc/html/rfc6962) (устаревшая, но поддерживается для обратной совместимости)
- **crt.sh** — [Поиск сертификатов в CT-логах](https://crt.sh)
- **Google Chrome CT Policy** — [CT Compliance Requirements](https://googlechrome.github.io/CertificateTransparency/ct_policy.html)
- **MDN Certificate Transparency** — [Browser CT Requirements](https://developer.mozilla.org/en-US/docs/Web/Security/Defenses/Certificate_Transparency)
- **[Certificate Pinning](./certificate_pinning.md)** — дополнительный механизм защиты
- **[Обзор PKI](./pki_overview.md)** — базовые понятия PKI
- **[Let's Encrypt](../../WebServers/Concepts/https_with_certbot.md)** — CA с поддержкой CT
- **[TLS](../../Networking/Protocols/tls.md#ct-certificate-transparency)** — CT в контексте TLS протокола
