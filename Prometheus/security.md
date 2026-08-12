# Безопасность Prometheus

## Определения

**Безопасность Prometheus** — совокупность архитектурных решений, настроек и технических средств, направленных на обеспечение конфиденциальности, целостности и доступности метрик, а также защиту инфраструктуры мониторинга от несанкционированного вмешательства.

Начиная с версии **Prometheus v3.0 (2024–2026)**, архитектура безопасности включает нативную поддержку TLS/Auth для всех эндпоинтов, включая новый приемник данных **OTLP (OpenTelemetry Line Protocol)**. Современный Prometheus спроектирован для работы в Zero Trust средах, где каждый поток данных (Pull или Push) должен быть авторизован и зашифрован.

> **См. также:** [DevSecOps](../CI-CD/DevSecOps/devsecops_overview.md) — общие принципы безопасности; [Безопасность Prometheus Operator](./kubernetes/operator/Security/index.md) — защита в Kubernetes; [HTTP-аутентификация](../Networking/Protocols/HTTP/http_authentication.md) — теоретические основы.

## Основные концепции

### Модель угроз и риски

| Фактор риска | Описание | Последствия |
| :--- | :--- | :--- |
| **Открытый OTLP Receiver** | Доступ к `/api/v1/otlp/*` без авторизации. | Инъекция ложных метрик, отравление TSDB (Data Poisoning). |
| **DoS-атаки через PromQL** | Выполнение сложных запросов с большой глубиной поиска. | Исчерпание RAM и падение сервера. |
| **UTF-8 Rendering (v3.0)** | Недостаточная фильтрация имен метрик в сторонних UI. | Риск XSS-атак при отображении «сырых» UTF-8 имен в браузере. |
| **Секреты в конфигурации** | Утечка токенов через эндпоинт `/-/config`. | Компрометация ключей доступа к облачным провайдерам. |

### Многоуровневая стратегия защиты (Zero Trust)

Безопасность системы мониторинга строится по принципу эшелонированной обороны:

1.  **Защита входящего трафика (Ingress):**
    *   **Web Auth:** Basic Auth или OAuth2 для доступа к UI и API.
    *   **mTLS для OTLP:** Обязательная проверка клиентских сертификатов для всех приложений, отправляющих метрики по OTLP.
2.  **Защита исходящего трафика (Scrape):** Настройка безопасного взаимодействия с экспортерами (Basic Auth, OAuth2, mTLS).
3.  **Сетевая сегментация:** Использование Network Policies и mTLS внутри Service Mesh (Istio/Linkerd) для изоляции порта 9090.
4.  **Безопасность данных (At Rest):** Использование разрешений файловой системы и шифрования томов. В v3.0 рекомендуется использовать **Remote Write 2.0** с OIDC для безопасной передачи данных в долгосрочные хранилища.


## Практические сценарии

### Встроенная защита Prometheus (web-config.yml)

Для активации нативного TLS и Basic Auth создайте файл конфигурации (например, `web-config.yml`). В v3.0 рекомендуется использовать **mTLS** для защиты эндпоинта OTLP.

```yaml
# /etc/prometheus/web-config.yml
tls_server_config:
  cert_file: /etc/prometheus/certs/server.crt
  key_file: /etc/prometheus/certs/server.key
  # Включение mTLS: требовать сертификат от клиента (приложения или Alloy)
  client_auth_type: RequireAndVerifyClientCert
  client_ca_file: /etc/prometheus/certs/client-ca.crt

basic_auth_users:
  admin: "$2y$12$hNf2lSsxfm0.i4a.1kVpSOVyBCfIB51VRjgBUyv6kdnyTlgWj81Ay"
```

Запуск сервера:
```bash
prometheus --config.file=prometheus.yml --web.config.file=web-config.yml --web.enable-otlp-receiver
```

### Аутентификация при сборе метрик (Scraping)

**OAuth2 с JWT Bearer Grant (RFC 7523):**
Появилась в v3.0 для безопасной интеграции с современными Identity Providers.

```yaml
scrape_configs:
  - job_name: 'secure-app'
    oauth2:
      client_id: 'prom-client'
      client_secret_file: '/etc/prometheus/secrets/oauth-secret'
      token_url: 'https://auth.example.com/token'
      # Новое в v3: использование JWT вместо обычных секретов
      grant_type: 'urn:ietf:params:oauth:grant-type:jwt-bearer'
      scopes: ['metrics.read']
```

**Mutual TLS (mTLS):**
```yaml
scrape_configs:
  - job_name: 'database'
    scheme: https
    tls_config:
      ca_file: /etc/prometheus/ca.crt
      cert_file: /etc/prometheus/client.crt
      key_file: /etc/prometheus/client.key
```

### Безопасность Remote Write 2.0

При отправке данных в облачные хранилища (Mimir, VictoriaMetrics) используйте OIDC для исключения долгоживущих секретов.

```yaml
remote_write:
  - url: "https://mimir.example.com/api/v1/push"
    headers:
      X-Prometheus-Remote-Write-Version: "2.0"
    oauth2:
      client_id: "prom-exporter"
      client_secret_file: "/var/run/secrets/remote-write-secret"
      token_url: "https://keycloak.example.com/token"
```

## Дополнительная информация

### Лучшие практики (Best Practices)

1.  **Принцип минимальных привилегий:** Запуск через `user: prometheus`. В K8s используйте `securityContext` с `runAsNonRoot: true`.
2.  **Защита UTF-8 (v3.0):** Будьте осторожны при визуализации меток с произвольным текстом. Убедитесь, что используемая версия Grafana (v11+) корректно экранирует UTF-8 символы для предотвращения XSS.
3.  **Скрытие секретов:** Эндпоинт `/-/metrics` в v3.0 автоматически маскирует чувствительные данные, но эндпоинт `/-/config` может их отображать. Ограничивайте доступ к административному API.
4.  **Ограничение ресурсов запросов:**
    ```bash
    --query.max-concurrency=20
    --query.max-samples=50000000
    --query.timeout=2m
    ```

### Мониторинг безопасности

Отслеживание аномалий и попыток взлома через внутренние метрики:

```promql
# Рост числа ошибок 403 (попытки доступа к запрещенным эндпоинтам)
rate(prometheus_http_requests_total{code="403"}[5m]) > 0.5

# Мониторинг использования ресурсов тяжелыми запросами
prometheus_engine_query_duration_seconds{quantile="0.99"} > 10
```

Для анализа структуры инфраструктуры и прав доступа в Kubernetes см. раздел **[RBAC и политики доступа](./kubernetes/operator/Security/access_control.md)**.

