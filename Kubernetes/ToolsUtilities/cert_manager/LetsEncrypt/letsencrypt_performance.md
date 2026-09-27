# Let's Encrypt: Производительность при масштабе

## Определения

**TLS Handshake Latency** — время рукопожатия TLS между клиентом и сервером. Зависит от алгоритма ключа (ECDSA быстрее RSA), размера цепочки сертификатов и количества SAN. Для Let's Encrypt ECDSA: 10-30 мс, RSA: 20-60 мс.

**Certificate Chain Size** — суммарный размер leaf + intermediate + root сертификатов. ECDSA-цепочка: 1.5-2.5 KB, RSA-цепочка: 3-5 KB. Влияет на время загрузки страницы (особенно на мобильных устройствах).

**ACME API Throughput** — количество ACME-запросов в единицу времени. Let's Encrypt: 300 new orders / 3 часа на аккаунт. При массовом перевыпуске необходимо учитывать rate limits и шардировать заказы.

**CT Log Latency** — задержка логирования пре-сертификата в CT-логах. Обычно 1-5 секунд. При высокой нагрузке на CT-логи может увеличиваться до 30 секунд.

---

## Основные концепции

### Влияние алгоритма ключа на производительность

| Параметр | RSA-2048 | RSA-4096 | ECDSA P-256 | ECDSA P-384 |
| :--- | :--- | :--- | :--- | :--- |
| **Размер ключа (байты)** | 256 | 512 | 32 | 48 |
| **Размер подписи** | 256 | 512 | 64 | 96 |
| **TLS Handshake (мс)** | 20-40 | 40-80 | 10-20 | 15-30 |
| **Подпись CSR (мс)** | 5-15 | 20-50 | 1-3 | 2-5 |
| **CPU нагрузка (%)** | Средняя | Высокая | Низкая | Средняя |
| **Размер сертификата** | 2-3 KB | 3-4 KB | 0.5-1 KB | 1-1.5 KB |

**Вывод:** ECDSA P-256 обеспечивает в 2-4 раза более быстрый TLS-handshake по сравнению с RSA-2048 при сохранении аналогичного уровня безопасности. При масштабе (1000+ RPS) разница становится критичной.

### Влияние размера SAN на производительность

| Количество SAN | Размер сертификата | Время парсинга | Рекомендация |
| :--- | :--- | :--- | :--- |
| 1-5 | 0.5-1 KB | < 1 мс | Оптимально |
| 6-15 | 1-2 KB | 1-3 мс | Приемлемо |
| 16-50 | 2-4 KB | 3-10 мс | Рассмотрите wildcard |
| 51-100 | 4-8 KB | 10-30 мс | Используйте wildcard |

**Рекомендация:** При более чем 10 SAN используйте wildcard-сертификаты (`*.example.com`) через DNS-01. Это снижает размер сертификата и ускоряет TLS-handshake.

### Rate Limits и масштабирование

| Rate Limit | Значение | Влияние на масштаб |
| :--- | :--- | :--- |
| Certificates per Domain | 50 / 7 дней | Ограничивает количество уникальных доменов |
| Duplicate Certificates | 5 / 7 дней | Ограничивает перевыпуск одного набора SAN |
| Failed Validations | 5 / 1 час | Критично при mass-reissue |
| New Orders | 300 / 3 часа | Ограничивает параллельные перевыпуски |

**Стратегии масштабирования:**
1. **Разделение Issuer**: Отдельный ClusterIssuer для каждого домена/команды.
2. **Staging-first**: Тестирование через Staging перед Production.
3. **ARI**: Динамическое управление окном продления (cert-manager v1.15+).
4. **Шардирование**: Последовательное продление с задержкой между Order.

---

## Практические сценарии

### Сценарий 1: Массовый перевыпуск сертификатов

При миграции кластера или смене CA необходимо перевыпустить数百 сертификатов без превышения rate limits.

```bash
# 1. Подсчёт количества сертификатов
CERT_COUNT=$(kubectl get certificate -A --no-headers | wc -l)
echo "Total certificates: $CERT_COUNT"

# 2. Стратегия шардирования: не более 50 сертификатов в час
# (300 orders / 3 часа = 100 orders/час, но запас прочности)

# 3. Поочерёдное продление с задержкой
kubectl get certificate -A -o jsonpath='{range .items[*]}{.metadata.namespace}/{.metadata.name}{"\n"}{end}' | \
  while read cert; do
    echo "Renewing: $cert"
    cmctl renew $(echo $cert | cut -d/ -f2) -n $(echo $cert | cut -d/ -f1)
    sleep 10  # 10 секунд между заказами
  done

# 4. Мониторинг rate limits
kubectl logs -n cert-manager -l app=cert-manager | grep -i "rate\|limit\|429" | tail -20
```

### Сценарий 2: Оптимизация TLS-сервера (Nginx)

```nginx
# Оптимальная конфигурация Nginx для Let's Encrypt ECDSA
server {
    listen 443 ssl http2;
    server_name app.example.com;

    # ECDSA-сертификат (основной)
    ssl_certificate /etc/ssl/certs/app.example.com.crt;
    ssl_certificate_key /etc/ssl/private/app.example.com.key;

    # TLS 1.3 (быстрейший handshake)
    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_prefer_server_ciphers on;

    # OCSP Stapling (ускоряет проверку отзыва)
    ssl_stapling on;
    ssl_stapling_verify on;
    ssl_trusted_certificate /etc/ssl/certs/app.example.com.chain.crt;
    resolver 1.1.1.1 8.8.8.8 valid=300s;

    # Session resumption (ускоряет повторные подключения)
    ssl_session_cache shared:SSL:10m;
    ssl_session_timeout 1d;
    ssl_session_tickets off;

    # HSTS (preloading)
    add_header Strict-Transport-Security "max-age=63072000; includeSubDomains; preload" always;
}
```

### Сценарий 3: Мониторинг производительности TLS

```yaml
# PrometheusRule для мониторинга TLS-производительности
apiVersion: monitoring.coreos.com/v1
kind: PrometheusRule
metadata:
  name: letsencrypt-performance-rules
  namespace: cert-manager
spec:
  groups:
  - name: performance.rules
    rules:
    # Мониторинг времени выпуска сертификата
    - alert: CertificateIssuanceSlow
      expr: |
        histogram_quantile(0.95,
          rate(certmanager_http_acme_client_request_duration_seconds_bucket[5m])
        ) > 30
      for: 10m
      labels:
        severity: warning
      annotations:
        summary: "ACME-запросы медленные (p95 > 30 сек)"

    # Мониторинг количества активных Order
    - alert: TooManyActiveOrders
      expr: |
        count(certmanager_order_ready_status) > 100
      for: 5m
      labels:
        severity: warning
      annotations:
        summary: "Более 100 активных Order - возможны rate limits"

    # Мониторинг ошибок ACME
    - alert: HighACMEErrorRate
      expr: |
        rate(certmanager_http_acme_client_request_count{status=~"4..|5.."}[5m]) > 0.1
      for: 5m
      labels:
        severity: warning
      annotations:
        summary: "Высокий уровень ошибок ACME API"
```

```bash
# Проверка времени TLS-handshake
curl -w "TLS handshake: %{time_appconnect}s\nTotal: %{time_total}s\n" -o /dev/null -s https://app.example.com

# Проверка размера сертификата
echo | openssl s_client -connect app.example.com:443 2>/dev/null | openssl x509 -noout -text | grep -E "DNS:|Public-Key"

# Проверка CT-логов (время логирования)
openssl s_client -connect app.example.com:443 2>/dev/null | openssl x509 -noout -text | grep -A 5 "CT Precertificate SCTs"
```

### Сценарий 4: Оптимизация cert-manager для высокой нагрузки

```yaml
# Оптимальные resource limits для cert-manager при 500+ сертификатах
apiVersion: apps/v1
kind: Deployment
metadata:
  name: cert-manager
  namespace: cert-manager
spec:
  replicas: 3  # HA для webhook
  template:
    spec:
      containers:
      - name: cert-manager
        resources:
          requests:
            cpu: 500m
            memory: 512Mi
          limits:
            cpu: "1"
            memory: 1Gi
        args:
        - --v=4  # Повышенное логирование для диагностики
        - --max-concurrent-challenges=10  # Параллельные Challenge
      - name: cert-manager-webhook
        resources:
          requests:
            cpu: 250m
            memory: 256Mi
          limits:
            cpu: 500m
            memory: 512Mi
```

---

## Дополнительная информация

### Бенчмарки TLS-handshake

| Сценарий | RSA-2048 | ECDSA P-256 | Улучшение |
| :--- | :--- | :--- | :--- |
| **Текстовые страницы** | 35 мс | 15 мс | 57% быстрее |
| **Мобильные устройства** | 60 мс | 25 мс | 58% быстрее |
| **WebSocket/TCP** | 40 мс | 18 мс | 55% быстрее |
| **gRPC** | 30 мс | 12 мс | 60% быстрее |

### Рекомендации по масштабу

| Количество сервисов | Рекомендация |
| :--- | :--- |
| 1-10 | Один ClusterIssuer, ECDSA P-256 |
| 10-50 | Разделение Issuer по командам, wildcard через DNS-01 |
| 50-200 | Множественные ClusterIssuer, шардирование Order |
| 200+ | Terraform + cert-manager, автоматизация через GitOps |

### Смотрите также

- **[Let's Encrypt: Обзор](./index.md)** — rate limits и алгоритмы ключей
- **[cert-manager: Администрирование](../Administration/index.md)** — HA и ресурсы
- **[TLS Hardening](../../../../Networking/Protocols/HTTP/http_tls_hardening.md)** — настройка TLS
- **[Let's Encrypt: Network Security](./letsencrypt_network_security.md)** — сетевая безопасность
- **[Let's Encrypt: Compliance](./letsencrypt_compliance.md)** — соответствие требованиям
