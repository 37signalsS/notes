# Certificate Transparency (CT) — прозрачность сертификатов

## Определения

**Certificate Transparency (CT, RFC 6962)** — инфраструктура публичного логирования сертификатов X.509. Все выпущенные сертификаты записываются в публичные, только для чтения, криптографически верифицируемые логи, что позволяет обнаруживать ошибочно или恶意 выпущенные сертификаты.

**CT Log** — только для чтения,_APPEND-only структура данных, куда записываются все выпущенные сертификаты. Реализуется как Merkle Tree (хэш-дерево) для обеспечения целостности.

**SCT (Signed Certificate Timestamp)** — криптографическая подпись, подтверждающая, что сертификат был добавлен в CT Log. Содержит: версию SCT, имя лога, время включения, подпись.

**Log ID** — уникальный идентификатор CT-лога (SHA-256 хэш публичного ключа лога).

**Pre-certificate** — предварительный сертификат, выпущенный CA перед финальной подписью. Содержит `poison` extension (1.3.6.1.4.1.11129.2.4.3), указывающую, что сертификат должен быть залогирован.

**Monitor** — наблюдатель, отслеживающий CT-логи на наличие подозрительных сертификатов (например, выпущенных без авторизации).

---

## Теоретический блок

### Зачем нужна CT

1. **Обнаружение поддельных сертификатов:** Если CA (или злоумышленник с доступом к CA) выпустит сертификат для чужого домена, владелец домена увидит это в CT-логе
2. **Ответственность CA:** Публичность логов создаёт давление на CA — невозможно тайно выпустить сертификат
3. **Compliance:** Chrome, Firefox, Safari требуют SCT для доверия к сертификатам (с 2018 года)
4. **Инструменты мониторинга:** Сервисы (crt.sh, Facebook CT Monitor, Google Argon) позволяют отслеживать сертификаты для вашего домена

### Архитектура CT

```text
┌──────────┐   提交ляет    ┌──────────┐    добавляет    ┌──────────┐
│    CA    │──────────────▶│  CT Log  │───────────────▶│ Merkle   │
│          │  pre-certificate│  (append-only) │  Tree     │
└──────────┘              └──────────┘              └──────────┘
     │                          │
     │  получает SCT            │  возвращает SCT
     │◀─────────────────────────│
     │
     │ встраивает SCT
     │ в сертификат
     ▼
┌──────────┐
│  Leaf    │  (сертификат + SCT)
│  Cert    │
└──────────┘
     │
     │ клиент проверяет
     ▼
┌──────────┐
│  Клиент  │  проверяет SCT через
│          │  CT-лог или nonce
└──────────┘
```

### Требования браузеров (2026)

| Браузер | Требование CT | Минимум SCT |
| :--- | :--- | :--- |
| Chrome | Обязательно | 2 SCT от разных логов |
| Firefox | Обязательно | 2 SCT |
| Safari | Обязательно | 2 SCT |
| Edge | Обязательно (на базе Chromium) | 2 SCT |

### embedded SCT vs delivered SCT

| Метод | Описание | Использование |
| :--- | :--- | :--- |
| Embedded SCT | SCT встроен в расширение сертификата (X.509v3) | Public CA (Let's Encrypt, DigiCert) |
| TLS Extension | SCT передаётся как расширение TLS handshake | Когда невозможно встроить в сертификат |
| OCSP Stapling | SCT в ответе OCSP | Дополнительный канал доставки |

---

## Практический блок

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

### Проверка через在线-инструменты

```bash
# crt.sh — поиск сертификатов по домену
curl -s "https://crt.sh/?q=mycompany.com&output=json" | jq '.[] | {name_value, issuer_name, not_before, not_after}'

# Проверка CT через лог
curl -s "https://ct.googleapis.com/logs/argon2026/ct/v1/get-entries?start=0&end=0" | jq .
```

### Настройка CT-мониторинга

#### crt.sh (PostgreSQL)

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

#### Prometheus + crt.sh Exporter

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

Для внутренних CA CT-логи не обязательны, но полезны:

```bash
# Развертывание Trillian (Google CT Log) для внутренних сертификатов
# Trillian — open-source реализация CT-лога

git clone https://github.com/google/trillian.git
cd trillian

# Docker Compose для быстрого запуска
docker-compose up -d
```

### Проверка SCT через openssl s_client

```bash
# Проверка SCT при подключении к серверу
openssl s_client -connect myservice.local:443 -servername myservice.local -ct </dev/null 2>/dev/null | grep -A 3 "SCT"
# → Signed Certificate Timestamp:
# →   Version: v1 (0x0)
# →   Log ID: ...
# →   Timestamp: ...
```

### Настройка CT для Nginx (доставка SCT через TLS)

```nginx
# Nginx автоматически отправляет SCT, если они встроены в сертификат
# Дополнительная настройка не требуется

server {
    listen 443 ssl;
    server_name myservice.local;

    ssl_certificate     /etc/ssl/certs/leaf.crt;  # с встроенными SCT
    ssl_certificate_key /etc/ssl/private/leaf.key;

    # Проверка SCT (опционально, для диагностики)
    # openssl s_client -connect myservice.local:443 -ct
}
```

---

## Типичные ошибки

| Ошибка | Причина | Решение |
| :--- | :--- | :--- |
| `SSL: CERTIFICATE_IS_NOT_SCT_LOGGED` | Сертификат не содержит SCT | Перевыпустите сертификат с CT (ACME-клиенты добавляют SCT автоматически) |
| `Missing SCT` | SCT не встроен в сертификат и не доставляется через TLS | Используйте CA, поддерживающую CT (Let's Encrypt, DigiCert) |
| Браузер показывает предупреждение | Недостаточно SCT (нужно минимум 2) | Убедитесь, что CA отправляет сертификат в ≥2 CT-лога |
| Ложные срабатывания мониторинга | Выпущен сертификат для поддомена | Настройте точные правила мониторинга (regex для домена) |

---

## Лучшие практики

1. **Используйте ACME-клиенты** (certbot, lego) — они автоматически добавляют SCT при выпуске сертификатов Let's Encrypt
2. **Мониторьте CT-логи** для своего домена — настройте алерты на новые сертификаты (crt.sh, Facebook CT)
3. **Для внутренних CA:** CT-логи опциональны, но рекомендуются для сред >100 нод
4. **Не пытайтесь обойти CT** — браузеры не будут доверять сертификатам без SCT
5. **Используйте `pre-certificate` workflow** для внутренних CA, если хотите CT-мониторинг
6. **Комбинируйте** CT-мониторинг с Certificate Pinning для максимальной защиты

---

## Дополнительная информация

- **RFC 6962** — [Certificate Transparency](https://datatracker.ietf.org/doc/html/rfc6962)
- **crt.sh** — [Поиск сертификатов в CT-логах](https://crt.sh)
- **Google Argon** — [CT Log](https://ct.googleapis.com/logs/argon2026/)
- **[Certificate Pinning](./certificate_pinning.md)** — дополнительный механизм защиты
- **[Обзор PKI](./pki_overview.md)** — базовые понятия PKI
- **[Let's Encrypt](../../WebServers/Concepts/https_with_certbot.md)** — CA с поддержкой CT
