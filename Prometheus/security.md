# Безопасность Prometheus

## Определения

**Безопасность Prometheus** — совокупность архитектурных решений, настроек и технических средств, направленных на обеспечение конфиденциальности, целостности и доступности метрик, а также защиту инфраструктуры мониторинга от несанкционированного вмешательства.

Начиная с версии **Prometheus v3.0 (2024–2026)**, архитектура безопасности включает нативную поддержку TLS/Auth для всех эндпоинтов, включая новый приемник данных **OTLP (OpenTelemetry Line Protocol)**. Современный Prometheus спроектирован для работы в Zero Trust средах, где каждый поток данных (Pull или Push) должен быть авторизован и зашифрован.

**web-config.yml** — внешний YAML-файл, подключаемый флагом `--web.config.file`, содержащий параметры TLS-сервера (`tls_server_config`) и хешированные учетные данные (`basic_auth_users`) для веб-интерфейса и API.

**mTLS (Mutual TLS)** — режим аутентификации, при котором и сервер, и клиент предъявляют друг другу сертификаты, подписанные доверенным центром сертификации (CA).

**Defense in Depth** — стратегия эшелонированной защиты, при которой компрометация одного элемента инфраструктуры не приводит к полному захвату системы благодаря независимым слоям защиты.

> **См. также:** [DevSecOps](../CI-CD/DevSecOps/devsecops_overview.md) — общие принципы безопасности; [HTTP-аутентификация](../Networking/Protocols/HTTP/http_authentication.md) — теоретические основы.

## Основные концепции

### Модель угроз и рисков

| Фактор риска | Описание | Последствия |
| :--- | :--- | :--- |
| **Открытый OTLP Receiver** | Доступ к `/api/v1/otlp/*` без авторизации. | Инъекция ложных метрик, отравление TSDB (Data Poisoning). |
| **DoS-атаки через PromQL** | Выполнение сложных запросов с большой глубиной поиска. | Исчерпание RAM и падение сервера. |
| **UTF-8 Rendering (v3.0)** | Недостаточная фильтрация имен метрик в сторонних UI. | Риск XSS-атак при отображении «сырых» UTF-8 имен в браузере. |
| **Секреты в конфигурации** | Утечка токенов через эндпоинт `/-/config`. | Компрометация ключей доступа к внешним системам и хранилищам. |

### Многоуровневая стратегия защиты (Zero Trust)

Безопасность системы мониторинга строится по принципу эшелонированной обороны:

1.  **Защита входящего трафика (Ingress):**
    *   **Web Auth:** Basic Auth или OAuth2 для доступа к UI и API.
    *   **mTLS для OTLP:** Обязательная проверка клиентских сертификатов для всех приложений, отправляющих метрики по OTLP.
2.  **Защита исходящего трафика (Scrape):** Настройка безопасного взаимодействия с экспортерами (Basic Auth, OAuth2, mTLS, Bearer token).
3.  **Сетевая сегментация:** Использование firewall-правил (iptables/nftables) и ограничение слушаемого интерфейса для изоляции порта 9090.
4.  **Безопасность данных (At Rest):** Использование разрешений файловой системы и шифрования томов. Для долгосрочных хранилищ используйте TLS и краткоживущие credentials.

### Жизненный цикл секретов

Каждый секрет (пароль, токен, сертификат) проходит через этапы:
1.  **Создание:** генерация на защищенном хосте или во внешнем хранилище (Vault).
2.  **Хранение:** размещение в файле с правами `600`, владелец `prometheus:prometheus`, или в Kubernetes Secret.
3.  **Использование:** монтирование как файл (volume mount) или указание пути через `credentialsFile`.
4.  **Ротация:** обновление без перезапуска Prometheus через `/-/reload` (при включенном `--web.enable-lifecycle`).
5.  **Уничтожение:** безопасное удаление из файловой системы или внешнего хранилища.

## Практические сценарии

### Генерация TLS-сертификатов для mTLS

Перед настройкой TLS необходимо подготовить сертификаты. Для тестовых сред можно использовать самоподписанный CA.

**1. Создание приватного ключа CA:**
```bash
openssl genrsa -out ca.key 4096
chmod 600 ca.key
# → Generating RSA private key, 4096 bit long modulus
```

**2. Создание корневого сертификата CA:**
```bash
openssl req -x509 -new -nodes -key ca.key -sha256 -days 3650 \
  -out ca.crt \
  -subj "/C=RU/ST=Moscow/L=Moscow/O=Platform/OU=Monitoring/CN=ca.corp.local"
# → CA certificate created
```

**3. Создание серверного ключа и CSR:**
```bash
openssl genrsa -out server.key 2048
openssl req -new -key server.key -out server.csr \
  -subj "/C=RU/ST=Moscow/L=Moscow/O=Platform/OU=Monitoring/CN=prometheus.corp.local"
```

**4. Подпись серверного сертификата:**
```bash
openssl x509 -req -in server.csr -CA ca.crt -CAkey ca.key \
  -CAcreateserial -out server.crt -days 365 -sha256
# → Certificate created
```

**5. Создание клиентского ключа и CSR (для mTLS):**
```bash
openssl genrsa -out client.key 2048
openssl req -new -key client.key -out client.csr \
  -subj "/C=RU/ST=Moscow/L=Moscow/O=Platform/OU=Monitoring/CN=prometheus-client"
openssl x509 -req -in client.csr -CA ca.crt -CAkey ca.key \
  -CAcreateserial -out client.crt -days 365 -sha256
```

**6. Размещение сертификатов:**
```bash
sudo mkdir -p /etc/prometheus/certs
sudo cp ca.crt server.crt server.key client.crt client.key /etc/prometheus/certs/
sudo chown -R prometheus:prometheus /etc/prometheus/certs
sudo chmod 600 /etc/prometheus/certs/*.key
# → Permissions set
```

### Управление конфигурацией и правами доступа

**Создание bcrypt-хеша для Basic Auth:**
```bash
# Способ 1: htpasswd (если установлен)
htpasswd -nb admin 'StrongP@ssw0rd!' | cut -d: -f2
# → $2y$12$hNf2lSsxfm0.i4a.1kVpSOVyBCfIB51VRjgBUyv6kdnyTlgWj81Ay

# Способ 2: Python (встроенный bcrypt)
python3 -c "import bcrypt; print(bcrypt.hashpw(b'StrongP@ssw0rd!', bcrypt.gensalt()).decode())"
# → $2b$12$...
```

**Права на файлы конфигурации:**
```bash
sudo chown -R prometheus:prometheus /etc/prometheus /var/lib/prometheus
sudo chmod 600 /etc/prometheus/web-config.yml
sudo chmod 600 /etc/prometheus/certs/*.key
sudo chmod 644 /etc/prometheus/certs/*.crt
# → Permissions restricted
```

### Защита веб-интерфейса и API (web-config.yml)

Для активации нативного TLS и Basic Auth создайте файл конфигурации.

```yaml
# /etc/prometheus/web-config.yml
tls_server_config:
  cert_file: /etc/prometheus/certs/server.crt
  key_file: /etc/prometheus/certs/server.key
  client_ca_file: /etc/prometheus/certs/ca.crt
  client_auth_type: RequireAndVerifyClientCert

basic_auth_users:
  admin: "$2y$12$hNf2lSsxfm0.i4a.1kVpSOVyBCfIB51VRjgBUyv6kdnyTlgWj81Ay"
```

**Запуск сервера:**
```bash
# SystemdExecStart с элементами hardening
sudo systemctl edit prometheus
# → Переопределение ExecStart:
ExecStart=/usr/local/bin/prometheus \
    --config.file=/etc/prometheus/prometheus.yml \
    --storage.tsdb.path=/var/lib/prometheus/ \
    --storage.tsdb.retention.time=15d \
    --storage.tsdb.wal-compression \
    --web.enable-lifecycle \
    --web.enable-otlp-receiver \
    --web.config.file=/etc/prometheus/web-config.yml \
    --web.listen-address=127.0.0.1:9090 \
    --query.max-concurrency=20 \
    --query.max-samples=50000000 \
    --query.timeout=2m
```

**Systemd-юнит с hardening (полная конфигурация):**
```ini
[Unit]
Description=Prometheus Server
After=network-online.target

[Service]
User=prometheus
Group=prometheus
Type=simple
ExecStart=/usr/local/bin/prometheus \
    --config.file=/etc/prometheus/prometheus.yml \
    --storage.tsdb.path=/var/lib/prometheus/ \
    --storage.tsdb.retention.time=15d \
    --storage.tsdb.wal-compression \
    --web.enable-lifecycle \
    --web.enable-otlp-receiver \
    --web.config.file=/etc/prometheus/web-config.yml \
    --web.listen-address=127.0.0.1:9090 \
    --query.max-concurrency=20 \
    --query.max-samples=50000000 \
    --query.timeout=2m

Restart=always
NoNewPrivileges=true
ProtectSystem=full
ProtectHome=true
PrivateTmp=true

[Install]
WantedBy=multi-user.target
```

**В Docker/Podman:**
```bash
docker run -d \
  --name prometheus \
  -p 127.0.0.1:9090:9090 \
  -v /path/to/prometheus.yml:/etc/prometheus/prometheus.yml:ro \
  -v /path/to/web-config.yml:/etc/prometheus/web-config.yml:ro \
  -v /path/to/certs:/etc/prometheus/certs:ro \
  -v prometheus_data:/prometheus \
  --read-only \
  --cap-drop=ALL \
  --security-opt=no-new-privileges \
  prom/prometheus:v3.13.2 \
  --config.file=/etc/prometheus/prometheus.yml \
  --storage.tsdb.path=/prometheus \
  --storage.tsdb.wal-compression \
  --web.enable-lifecycle \
  --web.config.file=/etc/prometheus/web-config.yml \
  --web.listen-address=:9090
# → Container started with ID ...
```

### Аутентификация при сборе метрик (Scraping)

**OAuth2 с JWT Bearer Grant (RFC 7523):**
```yaml
scrape_configs:
  - job_name: 'secure-app'
    oauth2:
      client_id: 'prom-client'
      client_secret_file: '/etc/prometheus/secrets/oauth-secret'
      token_url: 'https://auth.example.com/token'
      grant_type: 'urn:ietf:params:oauth:grant-type:jwt-bearer'
      scopes: ['metrics.read']
    static_configs:
      - targets: ['app.corp.local:8443']
```

**Mutual TLS (mTLS) для целей:**
```yaml
scrape_configs:
  - job_name: 'database'
    scheme: https
    tls_config:
      ca_file: /etc/prometheus/certs/ca.crt
      cert_file: /etc/prometheus/certs/client.crt
      key_file: /etc/prometheus/certs/client.key
      insecure_skip_verify: false
    static_configs:
      - targets: ['db-exporter.corp.local:9100']
```

**Basic Auth для экспортера:**
```yaml
scrape_configs:
  - job_name: 'secure-exporter'
    scheme: https
    basic_auth:
      username: prometheus
      password: "${EXPORTER_PASSWORD}"
    tls_config:
      ca_file: /etc/prometheus/certs/ca.crt
      insecure_skip_verify: false
    static_configs:
      - targets: ['exporter-host:9100']
```

**Authorization Header (Bearer Token):**
```yaml
scrape_configs:
  - job_name: 'api-metrics'
    authorization:
      type: Bearer
      credentials: '/etc/prometheus/secrets/api-token/token'
    static_configs:
      - targets: ['metrics-api.corp.local:9090']
```

### Безопасность Remote Write

При отправке данных во внешние хранилища используйте TLS и минимальные привилегии.

**OAuth2 с краткоживущим токеном:**
```yaml
remote_write:
  - url: "https://mimir.corp.local/api/v1/push"
    headers:
      X-Prometheus-Remote-Write-Version: "2.0"
    oauth2:
      client_id: "prom-exporter"
      client_secret_file: "/var/run/secrets/remote-write-secret"
      token_url: "https://keycloak.corp.local/token"
    queue_config:
      max_samples_per_send: 1000
      batch_send_deadline: 5s
```

**Basic Auth + TLS для on-prem хранилища (VictoriaMetrics, Thanos):**
```yaml
remote_write:
  - url: "https://vmstorage.corp.local:8428/api/v1/write"
    basic_auth:
      username: "prometheus"
      password: "${REMOTE_PASSWORD}"
    tls_config:
      ca_file: /etc/prometheus/certs/ca.crt
      insecure_skip_verify: false
    queue_config:
      max_samples_per_send: 1000
      batch_send_deadline: 5s
```

### Безопасность OTLP-приемника

OTLP Receiver (gRPC 4317, HTTP 4318) должен быть защищен mTLS в production.

```yaml
otlp:
  promote_resource_attributes:
    - service.name
    - service.version
```

**Запуск с mTLS для OTLP:**
```bash
prometheus \
  --config.file=/etc/prometheus/prometheus.yml \
  --web.enable-otlp-receiver \
  --web.config.file=/etc/prometheus/web-config.yml
```

**Ограничение доступа к OTLP-портам (iptables пример):**
```bash
# Разрешить только CIDR корпоративной сети
iptables -A INPUT -p tcp --dport 4317 -s 10.0.0.0/8 -j ACCEPT
iptables -A INPUT -p tcp --dport 4317 -j DROP
```

### Валидация и проверка работоспособности

**1. Валидация синтаксиса web-config.yml:**
```bash
# Проверка загрузки web-config
promtool check web-config /etc/prometheus/web-config.yml
# → SUCCESS: 0.00 kB ... OK

# Проверка конфигурации Prometheus
promtool check config /etc/prometheus/prometheus.yml
# → SUCCESS: 0.00 kB ... OK
```

**2. Проверка доступности API с авторизацией:**
```bash
# Без авторизации — должно быть 401
curl -k https://localhost:9090/api/v1/status/flags
# → 401 Unauthorized

# С Basic Auth — успешный ответ
curl -k -u admin:StrongP@ssw0rd! https://localhost:9090/api/v1/status/flags | jq .
# → {"status":"success","data":[...]}

# Проверка здоровья
curl -k -u admin:StrongP@ssw0rd! https://localhost:9090/-/healthy
# → Prometheus Server is Healthy.

curl -k -u admin:StrongP@ssw0rd! https://localhost:9090/-/ready
# → Prometheus Server is Ready.
```

**3. Проверка целей скрапинга:**
```bash
curl -k -u admin:StrongP@ssw0rd! https://localhost:9090/api/v1/targets | jq '.data.activeTargets[] | {job: .labels.job, health: .health}'
# → [{"job":"prometheus","health":"up"}, ...]
```

**4. Проверка TLS-рукопожатия:**
```bash
openssl s_client -connect localhost:9090 -CAfile /etc/prometheus/certs/ca.crt
# → Verify return code: 0 (ok)
```

**5. Проверка OTLP-приемника:**
```bash
curl -k https://localhost:9090/api/v1/status/flags | grep otlp
# → "otelReceivedEnabled":true
```

### Диагностика и устранение неполадок

| Проблема | Вероятная причина | Диагностика | Решение |
| :--- | :--- | :--- | :--- |
| `401 Unauthorized` при доступе к API | Неверный пароль или хэш bcrypt | Проверить `basic_auth_users` в `web-config.yml` | Перегенерировать хэш, убедиться в корректности пароля |
| `403 Forbidden` | Ограничение по IP или NetworkPolicy | Проверить `iptables -L -n`, `nft list ruleset` | Добавить правило разрешения для доверенных подсетей |
| `SSL handshake failure` | Несовпадение CA или истекший сертификат | `openssl s_client -connect host:port` | Обновить сертификаты, проверить `client_ca_file` |
| `x509: certificate signed by unknown authority` | CA не добавлен в доверенные | `openssl verify -CAfile ca.crt server.crt` | Убедиться, что клиент использует правильный `ca_file` |
| `connection refused` на 9090 | Порт не слушается или занят | `ss -tlnp | grep 9090` | Проверить `--web.listen-address`, firewall |
| `scrape timeout` | Большая кардинальность или медленный экспортер | `curl -w "%{time_total}" https://target:9100/metrics` | Увеличить `scrape_timeout`, оптимизировать экспортер |
| `OTLP endpoint not found` | Флаг `--web.enable-otlp-receiver` не включен | `curl https://localhost:9090/api/v1/status/flags` | Добавить флаг в команду запуска |
| `config reload failed` | Ошибка в `web-config.yml` или правах | `journalctl -u prometheus -f` | Проверить синтаксис YAML, права на файл |
| `secret leaked in /-/config` | Секреты указаны в `prometheus.yml` вместо внешних файлов | `curl -u admin:pass https://localhost:9090/api/v1/status/config` | Перенести секреты в `credentialsFile` или env vars |
| `prometheus_http_requests_total{code="403"}` | Попытки доступа к защищенному эндпоинту без кредов | Проверить логи доступа | Добавить авторизацию в клиенты или настроить аутентификацию |

**Диагностические команды:**
```bash
# Проверка активных TLS-соединений
ss -tnp | grep 9090

# Проверка прав на файлы конфигурации
namei -l /etc/prometheus/web-config.yml
namei -l /etc/prometheus/certs/server.key

# Проверка работы systemd-юнита
systemctl status prometheus
journalctl -u prometheus -n 50 --no-pager

# Проверка firewall
iptables -L -n | grep 9090
nft list ruleset | grep 9090

# Проверка конфигурации Prometheus
promtool check config /etc/prometheus/prometheus.yml
promtool check web-config /etc/prometheus/web-config.yml

# Проверка targets
curl -s -u admin:password https://localhost:9090/api/v1/targets | jq '.data.activeTargets'
```

### Логирование и маскировка секретов

В Prometheus v3.0 эндпоинт `/-/metrics` автоматически маскирует чувствительные данные. Однако эндпоинт `/-/config` может отображать конфигурацию, включая секреты, если они заданы в `prometheus.yml` через переменные окружения, которые логируются процессом.

**Рекомендации:**
- Никогда не указывайте секреты напрямую в `prometheus.yml`.
- Используйте `credentialsFile` для файлов с токенами.
- Ограничьте доступ к API на уровне firewall: разрешайте `/-/metrics` только для систем мониторинга, а `/-/config` — только для администраторов.
- Включите аудит доступа к API через Prometheus метрики.

## Дополнительная информация

### Лучшие практики (Best Practices)

1.  **Принцип минимальных привилегий:** Запуск через `user: prometheus`. В systemd используйте `NoNewPrivileges=true`, `ProtectSystem=full`, `ProtectHome=true`, `PrivateTmp=true`.
2.  **Ограничение слушаемого интерфейса:** Используйте `--web.listen-address=127.0.0.1:9090` и reverse proxy (NGINX, Caddy) для внешнего доступа с дополнительной аутентификацией.
3.  **Сетевая изоляция:** Разрешайте inbound на порт 9090 только из доверенных подсетей (Grafana, jump-hosts).
4.  **mTLS для OTLP:** В production используйте `client_auth_type: RequireAndVerifyClientCert` для защиты от инъекции ложных метрик.
5.  **Скрытие секретов:** Эндпоинт `/-/config` может отображать чувствительные данные. Ограничивайте доступ к административному API.
6.  **Ограничение ресурсов запросов:**
    ```bash
    --query.max-concurrency=20
    --query.max-samples=50000000
    --query.timeout=2m
    ```
7.  **Никакой Basic Auth без TLS:** Basic Auth передает пароли в base64, что эквивалентно открытому тексту. Всегда используйте TLS при Basic Auth.
8.  **Ротация секретов:** Планируйте регулярную ротацию сертификатов (рекомендуется каждые 90 дней) и секретов.

### Мониторинг безопасности

Отслеживание аномалий и попыток взлома через внутренние метрики:

```promql
# Рост числа ошибок 403 (попытки доступа к запрещенным эндпоинтам)
rate(prometheus_http_requests_total{code="403"}[5m]) > 0.5

# Мониторинг использования ресурсов тяжелыми запросами
prometheus_engine_query_duration_seconds{quantile="0.99"} > 10

# Проверка количества активных серий (взрывной рост может указывать на инъекцию)
rate(prometheus_tsdb_head_series[5m]) > 0

# Доступ к конфигурации (кто читает /-/config)
rate(prometheus_http_requests_total{handler="/config"}[5m]) > 0
```

### Ограничения и граничные случаи

- **UTF-8 в именах метрик (v3.0+):** Поддержка расширенных символов увеличивает поверхность атаки XSS в сторонних UI. Убедитесь, что Grafana (v11+) корректно экранирует UTF-8 символы.
- **OTLP без mTLS:** Прием метрик по OTLP без клиентской аутентификации открывает возможность инъекции данных. Используйте `client_auth_type: RequireAndVerifyClientCert`.
- **Секреты в переменных окружения:** Prometheus логирует переменные окружения при старте в некоторых конфигурациях. Используйте `credentialsFile` вместо env vars.
- **Совместное использование web-config.yml:** При использовании нескольких Prometheus-инстансов с одной конфигурацией, утечка `web-config.yml` компрометирует все инстансы. Храните файлы в защищенном хранилище с аудитом доступа.
- **Ограничение размера секретов:** В Kubernetes размер Secret ограничен 1 MiB (etcd). При использовании Operator следите за размером сгенерированного конфига.
- **Совместимость TLS:** Prometheus v3 требует TLS 1.2+. Убедитесь, что клиенты и серверы используют поддерживаемые версии протокола.

### См. также
*   [Управление секретами в Prometheus Operator](./kubernetes/operator/Security/secrets_best_practices.md)
*   [Контроль доступа и RBAC](./kubernetes/operator/Security/access_control.md)
*   [Безопасность экспортеров](./Exporters/other_exporters.md)
*   [Сетевая безопасность](./security_network.md) - firewall, NetworkPolicy, порты
