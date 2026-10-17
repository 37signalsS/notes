# Безопасность VictoriaMetrics (single-node / cluster)

**Актуально для:** VictoriaMetrics v1.154.x (Community) / v1.148.x LTS (Enterprise)

## Определения

**Базовая аутентификация (`-httpAuth.*`)** — HTTP Basic Auth на всех HTTP-эндпоинтах одного компонента: флаги `-httpAuth.username` и `-httpAuth.password`. Аутентификация выключена, если `-httpAuth.username` пуст. Значение пароля читается не только из командной строки, но и из файла (`-httpAuth.password=file:///path/to/pass`) либо по `http(s)://`-адресу — то же касается всех `-*AuthKey`-флагов.

**AuthKey (`-*AuthKey`)** — отдельные ключи на отдельные служебные эндпоинты: `-metricsAuthKey`, `-flagsAuthKey`, `-pprofAuthKey`, `-configAuthKey`, `-reloadAuthKey`, `-deleteAuthKey`, `-snapshotAuthKey`, `-forceMergeAuthKey`, `-forceFlushAuthKey`, `-search.resetCacheAuthKey`, `-logNewSeriesAuthKey`, `-metricNamesStatsResetAuthKey`. Ключ передаётся в query-аргументе `authKey=`. **Если AuthKey задан, он переопределяет `-httpAuth.*`**: эндпоинт принимает только `authKey` и игнорирует Basic Auth; если AuthKey не задан — срабатывает обычная проверка `-httpAuth.*`.

**Периметр (auth proxy)** — `vmauth` (Community) или `vmgateway` (Enterprise) между внешними клиентами и компонентами хранилища. Единственная точка, которой разрешён вход из недоверенной сети: она завершает TLS, аутентифицирует и маршрутизирует запросы.

**mTLS (mutual TLS)** — двусторонняя проверка сертификатов. В VictoriaMetrics два независимых уровня:
1. **Входящие запросы на `-httpListenAddr`**: флаги `-tls` + `-mtls` (+ `-mtlsCAFile` для своего CA) — Enterprise.
2. **Трафик между компонентами кластера** (`vminsert`/`vmselect`/`vmstorage`): флаги `-cluster.tls*` — Enterprise.

**vmgateway** — Enterprise-компонент над `vmauth`: JWT/OIDC-аутентификация, тенантные ACL и ограничение частоты запросов. Подробнее — [Enterprise-функции](./enterprise_features.md).

**Тенант (`accountID:projectID`)** — единица изоляции данных в кластере. Адресуется в пути (`/insert/0/prometheus/...`) либо (с v1.143.0, по умолчанию с v1.150.0) HTTP-заголовками `AccountID`/`ProjectID` — что и создаёт основной вектор подмены тенанта, см. модель угроз.

## Базовые концепции

### Модель угроз и поверхность атаки

| Угроза | Вектор | Последствие | Основная защита |
| :--- | :--- | :--- | :--- |
| Подмена метрик (data poisoning) | Открытый `/api/v1/write`, `/insert/*` | Ложные алерты, скрытие инцидента | `vmauth` + сетевая изоляция |
| Чтение чужого тенанта | Клиент задаёт `AccountID`/`ProjectID` или `extra_filters[]` | Утечка метрик другой команды | Принудительная перезапись заголовков в `vmauth` |
| Перехват учётных данных | Basic Auth/TLS-токены по незашифрованному HTTP | Компрометация доступа ко всему стеку | TLS на периметре (`-tls`, `-tlsMinVersion=TLS12`) |
| Брутфорс токенов `vmauth` | Массовые запросы с неверным токеном | Подбор рабочего токена | Обновление до v1.154.0+ (замедление невалидных запросов) |
| Доступ к служебным API | Незащищённые `/snapshot/create`, `/api/v1/admin/tsdb/delete_series`, `/-/reload` | Потеря данных, DoS, раскрытие конфига | `-snapshotAuthKey`, `-deleteAuthKey`, `-reloadAuthKey` и др. |
| Раскрытие секретов | `/flags`, `/config`, `/debug/pprof`, `/metrics` | Утечка флагов, паролей, топологии | `-*AuthKey` + ограничение доступа к порту |
| XSS в `vmui` | Подделка данных в UI (Metric Relabeling Debug, Query Analyzer, Dashboards) | Кража сессий пользователя UI | Обновление до v1.154.0+ |
| DoS через тяжёлые запросы | Нагрузка на `vmselect`/`vmauth` | Недоступность мониторинга | Лимиты конкурентности `vmauth` (`-maxConcurrentRequests`, `-maxConcurrentPerUserRequests`) |

### Периметр аутентификации в стеке

```
внедоверенная сеть (Grafana, агенты, curl)
   │  HTTPS + Basic Auth / Bearer / JWT / OIDC
   ▼
┌────────────────┐
│  vmauth        │  терминация TLS, авторизация, маршруты, лимиты   :8427
│  vmgateway (E) │  JWT/OIDC + тенантные ACL + rate limiting
└───────┬────────┘
        │  внутренняя сеть (Community: без TLS; Enterprise: mTLS)
        ▼
 vminsert / vmselect / vmsingle / vmalert / vmagent
        │
        ▼
   vmstorage (кластер)
```

Компоненты хранилища по умолчанию слушают **HTTP без аутентификации** — они рассчитаны на то, что перед ними стоит прокси. Открытые наружу без прокси считаются опасными: `/metrics`, `/api/v1/write`, `/insert/*`, `/select/*`, `/api/v1/admin/*`, `/snapshot*`, `/-/reload`, `/vmui`.

### Экспозиция портов

| Компонент | Порт по умолчанию | Допустимая экспозиция |
| :--- | :--- | :--- |
| `victoria-metrics` (single) | `8428` | Только подсетью мониторинга либо через `vmauth` |
| `vminsert` | `8480` | Только через `vmauth`, никогда напрямую извне |
| `vmselect` | `8481` | Только через `vmauth`, никогда напрямую извне |
| `vmstorage` | `8482` (HTTP), `8400`/`8401` (TCP) | Только внутри кластерной подсети |
| `vmagent` | `8429` | Подсистема мониторинга (скрейп `/metrics`) |
| `vmalert` | `8880` | Подсистема мониторинга, UI — через прокси |
| `vmauth` | `8427` | Единственный порт, допустимый на недоверенном контуре (HTTPS) |

Полный список портов — в [обзоре VictoriaMetrics](./overview.md). Базовый принцип: компоненты стека живут в приватной сети, наружу выносится только точка авторизации.

### Ключевые флаги защиты

| Компонент | Серверные флаги (HTTP-интерфейс) |
| :--- | :--- |
| любой компонент | `-httpAuth.username`, `-httpAuth.password[=file://...]`, `-tls`, `-tlsCertFile`, `-tlsKeyFile`, `-tlsMinVersion` (`TLS10`/`TLS11`/`TLS12`/`TLS13`), `-tlsCipherSuites` |
| любой компонент (Enterprise) | `-mtls`, `-mtlsCAFile`; `-tlsAutocertHosts`, `-tlsAutocertEmail`, `-tlsAutocertCacheDir` (Let's Encrypt) |
| любой компонент | `-http.header.hsts`, `-http.header.csp`, `-http.header.frameOptions`; `-httpListenAddr=unix:/path/to/socket` |
| `vmsingle` | `-deleteAuthKey`, `-snapshotAuthKey`, `-configAuthKey`, `-reloadAuthKey`, `-forceMergeAuthKey`, `-forceFlushAuthKey`, `-search.resetCacheAuthKey` |
| `vmselect` | `-deleteAuthKey` |
| `vmstorage` | `-snapshotAuthKey`, `-forceMergeAuthKey`, `-forceFlushAuthKey` |
| `vmauth` | `-auth.config`, `-configCheckInterval`, `-httpAuthHeader`, `-backend.TLSCAFile`/`-backend.TLSCertFile`/`-backend.TLSKeyFile`/`-backend.tlsInsecureSkipVerify`, `-maxConcurrentRequests`, `-maxConcurrentPerUserRequests`, `-removeXFFHTTPHeaderValue`, `-httpInternalListenAddr` |
| `vmagent` | `-httpAuth.*`, `-tls*`, `-metricsAuthKey`; `-remoteWrite.basicAuth.*`, `-remoteWrite.bearerToken[File]`, `-remoteWrite.headers`, `-remoteWrite.tls*` |
| `vmalert` | `-httpAuth.*`, `-tls*`; `-datasource.basicAuth.*`, `-datasource.bearerToken[File]`, `-datasource.headers`, `-datasource.tls*`; аналогично `-notifier.*`, `-remoteWrite.*` |

### AuthKey по эндпоинтам

| Эндпоинт | Флаг | Риск при открытом доступе |
| :--- | :--- | :--- |
| `/metrics` | `-metricsAuthKey` | Топология и поведение стека |
| `/flags` | `-flagsAuthKey` | Раскрытие активной конфигурации (значения паролей в выводе маскируются) |
| `/config` | `-configAuthKey` | Пароли в `-promscrape.config` и других конфигах |
| `/-/reload` | `-reloadAuthKey` | Принудительная перезагрузка конфигурации |
| `/debug/pprof/*` | `-pprofAuthKey` | Профили процесса, память |
| `/api/v1/admin/tsdb/delete_series` | `-deleteAuthKey` | Массовое удаление серий |
| `/snapshot*` | `-snapshotAuthKey` | Создание/удаление снапшотов, расход диска |
| `/internal/force_merge`, `/internal/force_flush` | `-forceMergeAuthKey`, `-forceFlushAuthKey` | Непредвиденная нагрузка на IO |
| `/internal/resetRollupResultCache` | `-search.resetCacheAuthKey` | Сброс кеша запросов |
| `/internal/log_new_series` | `-logNewSeriesAuthKey` | Логирование новых серий |

### Шифрование в покое

- VictoriaMetrics **не шифрует данные на диске**. Для encryption-at-rest применяйте шифрование уровня ОС/ФС (`LUKS`/`dm-crypt`), шифрование раздела или шифрование тома в Kubernetes (шифрованный `storageClass`).
- Резервные копии (`vmbackup`) и снапшоты наследуют ту же защиту: шифруйте место их хранения отдельно от исходного тома.

## Практические сценарии

Перед настройкой подготовьте: сертификаты для `-tlsCertFile`/`-tlsKeyFile` (генерация CA и подпись — в разделе «Генерация TLS-сертификатов для mTLS» файла [Безопасность Prometheus](../Prometheus/security.md)), файлы паролей с правами `600` и решите, какой компонент станет единственной точкой входа (`vmauth`).

### 1. Базовая аутентификация и TLS на vmsingle

```bash
# /etc/victoria-metrics/secrets/http_pass — только для процесса
sudo install -o root -g victoria-metrics -m 600 /dev/null /etc/victoria-metrics/secrets/http_pass
printf %s "$VM_PASSWORD" | sudo tee /etc/victoria-metrics/secrets/http_pass > /dev/null
# → пароль берётся из окружения вызывающей оболочки, права 600 сохраняются

victoria-metrics \
  -storageDataPath=/var/lib/victoria-metrics \
  -httpListenAddr=10.10.0.11:8428 \
  -httpAuth.username=vm \
  -httpAuth.password=file:///etc/victoria-metrics/secrets/http_pass \
  -tls \
  -tlsCertFile=/etc/victoria-metrics/tls/server.crt \
  -tlsKeyFile=/etc/victoria-metrics/tls/server.key \
  -tlsMinVersion=TLS12
```

- Пароль в аргументе командной строки виден в `ps` и `/proc/<pid>/cmdline` — всегда используйте `file://` или `%{ENV_VAR}` (раскрытие переменной выполняет сам VictoriaMetrics при старте).
- `-httpListenAddr` указывает на конкретный интерфейс: слушать `0.0.0.0` допустимо только за firewall-ом.
- Значения парольных флагов в выводе `/flags` заменяются на `secret`, но сам `/flags` всё равно закрывайте ключом.

### 2. Защита служебных эндпоинтов ключами

```bash
victoria-metrics \
  -storageDataPath=/var/lib/victoria-metrics \
  -httpAuth.username=vm \
  -httpAuth.password=file:///etc/victoria-metrics/secrets/http_pass \
  -metricsAuthKey=file:///etc/victoria-metrics/secrets/metrics_key \
  -flagsAuthKey=file:///etc/victoria-metrics/secrets/flags_key \
  -configAuthKey=file:///etc/victoria-metrics/secrets/config_key \
  -deleteAuthKey=file:///etc/victoria-metrics/secrets/delete_key \
  -snapshotAuthKey=file:///etc/victoria-metrics/secrets/snapshot_key \
  -reloadAuthKey=file:///etc/victoria-metrics/secrets/reload_key
```

Ключ передаётся в query-аргументе:

```bash
# Без ключа — 401, с корректным ключом — 200
curl -s -o /dev/null -w '%{http_code}\n' http://localhost:8428/flags
# → 401
curl -s -o /dev/null -w '%{http_code}\n' \
  "http://localhost:8428/flags?authKey=$(cat /etc/victoria-metrics/secrets/flags_key)"
# → 200
```

### 3. Тенантные ACL и защита заголовков через vmauth

```yaml
# /etc/victoriametrics/vmauth.yml
users:
  - username: grafana
    password: grafana-secret
    url_prefix: http://vmselect:8481/select/0/prometheus/

  - username: vmagent
    password: write-secret
    url_prefix: http://vminsert:8480/insert/0/prometheus/

  # Клиенту tenant 2 запрещено задавать тенант самостоятельно:
  # значения заголовков принудительно перезаписываются на бэкенде.
  - username: team-b
    password: team-b-secret
    url_prefix: http://vmselect:8481/
    headers:
      - "AccountID: 2"
      - "ProjectID: 0"
```

Ключевые моменты:

- Заголовки `AccountID`/`ProjectID` с v1.150.0 читаются по умолчанию (`-enableMultitenancyViaHeaders`) — без явной перезаписи в `headers` клиент выберет любой тенант.
- При маршрутизации `multitenant`-запросов в `url_prefix` обязательны явные `extra_label`/`extra_filters`: клиентские `extra_filters[]` объединяются с серверными по логике `OR` и обходят ограничение тенанта.
- Правила `src_paths` должны быть тенант-скоупленными; API, дающие доступ ко всем тенантам, из per-tenant маршрутов исключаются.
- Рекомендуется перечень разрешённых путей вместо пропускающего по умолчанию: минимальная поверхность атаки.
- Формат конфига, ретраи, балансировка — в [vmauth](./vmauth_overview.md).

Запуск и проверка конфигурации:

```bash
vmauth \
  -auth.config=/etc/victoriametrics/vmauth.yml \
  -configCheckInterval=10s \
  -httpListenAddr=10.10.0.11:8427 \
  -tls \
  -tlsCertFile=/etc/victoria-metrics/tls/server.crt \
  -tlsKeyFile=/etc/victoria-metrics/tls/server.key \
  -tlsMinVersion=TLS12 \
  -removeXFFHTTPHeaderValue \
  -maxConcurrentRequests=500 \
  -maxConcurrentPerUserRequests=50

vmauth -auth.config=/etc/victoriametrics/vmauth.yml -dryRun
# → конфигурация проверена, ошибок нет
```

### 4. mTLS (Enterprise)

**а) Проверка клиентских сертификатов на входящем порту** (все компоненты, в том числе `vmauth`):

```bash
./victoria-metrics \
  -httpListenAddr=:8428 \
  -tls -tlsCertFile=/etc/vm/tls/server.crt -tlsKeyFile=/etc/vm/tls/server.key \
  -mtls -mtlsCAFile=/etc/vm/tls/ca.crt
# → принимаются только запросы с валидным клиентским сертификатом из ca.crt
```

**б) Шифрование и взаимная проверка между компонентами кластера:**

```bash
# на vminsert, vmselect и vmstorage — одинаковый набор
vmstorage \
  -httpListenAddr=:8482 \
  -cluster.tls=true \
  -cluster.tlsCertFile=/etc/vm/cluster/tls.crt \
  -cluster.tlsKeyFile=/etc/vm/cluster/tls.key \
  -cluster.tlsCAFile=/etc/vm/cluster/ca.crt

vminsert \
  -storageNode=vmstorage-0:8400 \
  -cluster.tls=true \
  -cluster.tlsCertFile=/etc/vm/cluster/tls.crt \
  -cluster.tlsKeyFile=/etc/vm/cluster/tls.key \
  -cluster.tlsCAFile=/etc/vm/cluster/ca.crt
```

- `-cluster.tlsInsecureSkipVerify` отключает проверку сертификатов пиров и ломает защиту — только для отладки.
- Для многоуровневого кластера существуют аналогичные `-clusternative.tls*` флаги на `-clusternativeListenAddr`.
- Без Enterprise трафик между компонентами не шифруется — закрывайте его сетевой изоляцией (сценарий 7).

### 5. Безопасная доставка данных в vmagent

```bash
vmagent \
  -promscrape.config=/etc/victoria-metrics/scrape.yml \
  -remoteWrite.url=https://vmauth:8427/insert/0/prometheus/api/v1/write \
  -remoteWrite.basicAuth.username=vmagent \
  -remoteWrite.basicAuth.passwordFile=/etc/victoria-metrics/secrets/rw_password \
  -remoteWrite.tlsCAFile=/etc/victoria-metrics/tls/ca.crt \
  -httpListenAddr=10.10.0.11:8429 \
  -httpAuth.username=vmagent \
  -httpAuth.password=file:///etc/victoria-metrics/secrets/http_pass \
  -metricsAuthKey=file:///etc/victoria-metrics/secrets/metrics_key
```

Скрейпинг целей с аутентификацией — в конфиге `-promscrape.config` (поля `basic_auth`, `authorization`, `bearer_token[File]`, `oauth2`, `tls_config`):

```yaml
scrape_configs:
  - job_name: app
    scheme: https
    basic_auth:
      username: scrape
      password_file: /etc/victoria-metrics/secrets/scrape_password
    tls_config:
      ca_file: /etc/victoria-metrics/tls/ca.crt
      insecure_skip_verify: false
    static_configs:
      - targets: ["app.internal:9464"]
```

Альтернативы для `-remoteWrite.url`: `-remoteWrite.bearerToken[File]`, произвольные заголовки `-remoteWrite.headers='X-Auth: value'`, клиентский сертификат `-remoteWrite.tlsCertFile`/`-remoteWrite.tlsKeyFile`.

### 6. vmalert: источник данных и нотификаторы

```bash
vmalert \
  -rule=/etc/victoria-metrics/rules/*.yml \
  -datasource.url=https://vmauth:8427 \
  -datasource.basicAuth.username=vmalert \
  -datasource.basicAuth.passwordFile=/etc/victoria-metrics/secrets/vmalert_pass \
  -datasource.tlsCAFile=/etc/victoria-metrics/tls/ca.crt \
  -remoteWrite.url=https://vmauth:8427/api/v1/write \
  -remoteWrite.basicAuth.username=vmalert \
  -remoteWrite.basicAuth.passwordFile=/etc/victoria-metrics/secrets/vmalert_pass \
  -notifier.url=https://alertmanager:9093 \
  -notifier.bearerTokenFile=/etc/victoria-metrics/secrets/am_token \
  -httpListenAddr=10.10.0.11:8880 \
  -httpAuth.username=vmalert \
  -httpAuth.password=file:///etc/victoria-metrics/secrets/http_pass
```

- Учётные данные передаются флагами `-datasource.basicAuth.*`, **не** query-аргументами в URL.
- Пользователь `vmalert` и его маршруты на `vmselect`/`vminsert` описываются в `-auth.config` `vmauth` — см. сценарий 3.
- Адреса источников и нотификаторов по умолчанию вычищаются из логов, UI и метрик; флаги `-datasource.showURL`, `-notifier.showURL`, `-remoteWrite.showURL` возвращают их в открытом виде — в production не задавать.

### 7. Сетевая изоляция (bare-metal и Kubernetes)

```bash
# Разрешаем запись в vminsert только из подсети мониторинга
sudo iptables -A INPUT -p tcp --dport 8480 -s 10.10.0.0/24 -j ACCEPT
sudo iptables -A INPUT -p tcp --dport 8480 -j DROP

# Проверка наличия правила (exit 0 — правило есть)
sudo iptables -C INPUT -p tcp --dport 8480 -s 10.10.0.0/24 -j ACCEPT; echo $?
# → 0
```

```yaml
# Пример: доступ к vmselect только с подов vmauth.
# Лейблы подставьте фактические: kubectl get pod -n monitoring --show-labels
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: vmselect-allow-vmauth
  namespace: monitoring
spec:
  podSelector:
    matchLabels:
      app.kubernetes.io/name: vmselect
  policyTypes: [Ingress]
  ingress:
    - from:
        - podSelector:
            matchLabels:
              app.kubernetes.io/name: vmauth
      ports:
        - protocol: TCP
          port: 8481
```

Тот же принцип распространяется на `8480`, `8482` и `8428`. Широкие примеры правил (iptables/nftables/ufw, общий NetworkPolicy-паттерн) — в [сетевой безопасности Prometheus](../Prometheus/security_network.md): меняются только порты и имена подов.

### 8. Аудит попыток входа и лимитов

```promql
# Все компоненты: неверный Basic Auth
sum(rate(vm_http_request_errors_total{reason="wrong_basic_auth"}[5m])) > 0

# Все компоненты: неверный или отсутствующий authKey
sum(rate(vm_http_request_errors_total{reason="wrong_auth_key"}[5m])) > 0

# vmauth: ошибки запросов по пользователям
sum(rate(vmauth_user_request_errors_total[5m])) by (username) > 0

# vmauth: запросы, пришедшие без авторизации (метрика ведётся,
# только если задана секция unauthorized_user)
rate(vmauth_unauthorized_user_request_errors_total[5m]) > 0

# vmauth: отклонения по лимиту конкурентности (429)
sum(rate(vmauth_concurrent_requests_limit_reached_total[5m])) > 0
```

Логи `vmauth` (access log) и метрики по каждому пользователю (`vmauth_user_requests_total`, `vmauth_user_request_errors_total`) дают аудит без сторонних систем; при необходимости включайте access log и выгружайте его в общий пайплайн логов.

## Валидация установки

Команды выполняются на узле, где поднят контур сценариев 1–3 (TLS + Basic Auth + AuthKey):

```bash
ADDR=10.10.0.11                     # адрес из -httpListenAddr в примерах выше
PASS=$(cat /etc/victoria-metrics/secrets/http_pass)
KEY=$(cat /etc/victoria-metrics/secrets/flags_key)

# 1. Запрос без пароля отклоняется (-k — самоподписанный сертификат)
curl -sk -o /dev/null -w '%{http_code}\n' https://${ADDR}:8428/metrics
# → 401

# 2. Правильная аутентификация
curl -sk -u vm:${PASS} -o /dev/null -w '%{http_code}\n' https://${ADDR}:8428/metrics
# → 200

# 3. Служебный эндпоинт закрыт ключом (без ключа — 401)
curl -sk -o /dev/null -w '%{http_code}\n' https://${ADDR}:8428/flags
# → 401
curl -sk -o /dev/null -w '%{http_code}\n' "https://${ADDR}:8428/flags?authKey=${KEY}"
# → 200

# 4. TLS-сертификат и минимальная версия протокола
echo | openssl s_client -connect ${ADDR}:8428 -servername ${ADDR} -tls1_2 2>/dev/null \
  | grep -E 'subject=|Protocol|Verify return code'
# → subject=CN = ...
# → Protocol  : TLSv1.2
# → Verify return code: 0 (ok)

# 5. TLS 1.1 отвергается при -tlsMinVersion=TLS12
curl -sk -o /dev/null -w '%{http_code}\n' --tls-max 1.1 https://${ADDR}:8428/metrics
# → 000   (соединение не установлено: сервер требует TLS1.2+)

# 6. Права на файл пароля
sudo ls -l /etc/victoria-metrics/secrets/http_pass
# → -rw------- 1 root victoria-metrics ... /etc/victoria-metrics/secrets/http_pass
```

## Поиск и устранение неисправностей

| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| `401` с верными логином/паролем | Используется `file://`, но файл пуст/не читается процессом; спецсимволы в пароле | Проверить владельца и права файла, содержимое (`-httpAuth.password` читается при каждом обращении) |
| `401` и текст `Expected to receive non-empty authKey when -X is set` | Эндпоинт защищён AuthKey, запрос без `authKey=` | Добавить `?authKey=...` (curl) или использовать Basic Auth только на незащищённых AuthKey путях |
| `401` и текст `The provided authKey doesn't match -X` | Неверный или устаревший ключ | Сверить значение флага и передаваемый `authKey`, при `file://` — убедиться, что файл обновлён |
| `400`/ошибка рукопожатия на HTTPS | Сертификат не подписан, истёк, не тот CA | `-tlsCertFile`/`-tlsKeyFile`, цепочка и CN/SAN; `openssl verify -CAfile ca.crt server.crt` |
| `403`/handshake failure только на `-mtls` | Нет клиентского сертификата либо чужой CA | Проверить `-mtlsCAFile` (или системный trust store), перевыпустить сертификат клиента |
| Кластер: узлы не соединяются после включения `-cluster.tls` | Разные CA, отсутствует сертификат у части узлов, включён `-cluster.tlsInsecureSkipVerify` в неожиданном месте | Одинаковый `-cluster.tlsCAFile` на всех узлах, сверка `-cluster.tlsCertFile`/`-cluster.tlsKeyFile` |
| `401` у vmalert на запросах к источнику | Учётные данные не заданы или заданы не теми флагами | `-datasource.basicAuth.username`/`-datasource.basicAuth.password[File]` (не query-аргументы в URL) |
| vmalert логирует полный URL источника | Включён `-datasource.showURL` | Снять флаг; по умолчанию адреса вычищаются |
| Прямой доступ к `/insert/*` извне | Нет прокси-периметра / открыт порт | Поставить `vmauth`, закрыть `8480`/`8481` firewall-ом или NetworkPolicy |
| `429` на запросах через `vmauth` | Достигнут лимит конкурентности | `-maxConcurrentRequests`, `-maxConcurrentPerUserRequests`, `max_concurrent_requests` на пользователя |
| Подделка тенанта при включённой мульти-тенантности через заголовки | Клиент сам передаёт `AccountID`/`ProjectID` | Перезаписать заголовки в секции `headers` пользователя `vmauth` |
| Ложные ошибки авторизации по IP за прокси | Некорректный источник IP (`-httpRealIPHeader` на интернет-входе, подделанный `X-Forwarded-For`) | На интернет-входе не задавать `-httpRealIPHeader`, ставить `-removeXFFHTTPHeaderValue`, сбрасывать `X-Forwarded-For` на внешнем прокси |

## Рекомендации по эксплуатации

- Ставьте `vmauth` перед `vminsert`/`vmselect`/`vmsingle` всегда, когда к ним обращается больше одного клиента; прямых адресов компонентов наружу не выдавайте.
- Включайте TLS на каждом выходе за пределы доверенной сети, `-tlsMinVersion=TLS12`; на публичном контуре — HSTS через `-http.header.hsts`, CSP через `-http.header.csp`, `X-Frame-Options` через `-http.header.frameOptions`.
- Ограничивайте список разрешённых путей в `vmauth` (`url_map` + `deny_paths`) вместо широкого пропускания.
- Храните секреты в файлах с правами `600` (Vault, Kubernetes Secrets, менеджер секретов) и подключайте их через `file://`/`*File`-флаги и `%{ENV_VAR}`; не оставляйте пароли в командной строке и в конфигах.
- Ротируйте пароли, токены и сертификаты по расписанию: перечитывание `-httpAuth.password`/`-metricsAuthKey` из файла происходит без перезапуска, сертификаты по `-tlsCertFile`/`-tlsKeyFile` — каждую секунду; `vmauth` перечитывает `-auth.config` по `SIGHUP` либо по `-configCheckInterval`.
- Закрывайте `/metrics`, `/flags`, `/config`, `/debug/pprof` ключами и сетью: доступ к ним — только у подсистемы мониторинга и администраторов.
- Не используйте `-cluster.tlsInsecureSkipVerify`, `-backend.tlsInsecureSkipVerify`, `-datasource.tlsInsecureSkipVerify` и `tls_insecure_skip_verify` в production.
- Не включайте `-datasource.showURL`/`-notifier.showURL`/`-remoteWrite.showURL` и `dump_request_on_errors: true` в `vmauth` на постоянной основе: оба режима раскрывают чувствительные данные.
- Ограничивайте разбор трассировок запросов (`-denyQueryTracing`), если эндпоинты доступны шире круга администраторов.
- Слушайте служебные протоколы ввода данных (Graphite/OpenTSDB) на конкретном интерфейсе, а не на всех: `-graphiteListenAddr=10.10.0.11:2003` вместо `:2003`.

### Обновления и security-фиксы

Security-фиксы публикуются в последнем релизе, а также в LTS-линиях (v1.148.x, v1.136.x — последние релизы веток v1.148.6 и v1.136.20); LTS-ветки получают bugfix и security-фиксы 12 месяцев с момента выпуска, новые LTS выходят каждые 6 месяцев. Для не-LTS (Community) установок обновляйтесь до последнего релиза.

Фиксы, напрямую влияющие на безопасность контура мониторинга:

| Релиз | Исправление |
| :--- | :--- |
| v1.151.0 (бэкпорт v1.148.3) | Обход Basic Auth для путей с суффиксами `/config`, `/reload` в `vmsingle`, `vmagent`, `vminsert`, `vmselect` |
| v1.152.0 (бэкпорт v1.148.4) | Обход авторизации в `vmauth` при маршрутизации по JWT-claim `match_claims` |
| v1.153.0 (бэкпорт v1.148.5) | `vmauth`: ограничение редиректов OIDC Discovery исходным хостом; лимит памяти на `zstd`-блоки нативного импорта |
| v1.154.0 | `vmauth`: замедление запросов с неверными токенами при настроенном `unauthorized_user` (защита от брутфорса); XSS в `vmui` |
| v1.149.0 (бэкпорт v1.148.1) | `/api/v1/admin/tsdb/delete_series` и `/tags/delSeries` принимают только `POST` (защита от SSRF-удаления данных) |

### Чек-лист внедрения

- [ ] Компоненты хранилища недоступны напрямую из недоверенной сети, наружу вынесен только `vmauth` по HTTPS.
- [ ] Заданы `-httpAuth.*` и ключи для всех используемых служебных эндпоинтов.
- [ ] Включён `-tls` с `-tlsMinVersion=TLS12` на всех публичных точках входа.
- [ ] Тенант защищён от подмены: заголовки/`extra_filters` перезаписываются в `vmauth`.
- [ ] Секреты лежат в файлах с правами `600` и подключены через `file://`/`*File`.
- [ ] Настроены алерты на `vm_http_request_errors_total{reason=...}` и метрики `vmauth`.
- [ ] Установка обновлена до релиза с последними security-фиксами.
- [ ] Данные на диске и бэкапы защищены шифрованием уровня ОС/ФС.

### Очистка и откат

- После ротации паролей удалите старые файлы-секреты и проверьте, что в конфигурации и в истории команд не осталось значений в открытом виде.
- После перевыпуска сертификатов отзовите старые в CA и удалите их копии из конфигов и образов.
- При отказе от `-tls*`/`-mtls*`/`-cluster.tls*` верните исходные значения флагов через unit-файл/манифест и перезапустите компоненты по одному, чтобы не прервать запись.
- Снапшоты, созданные для проверки `-snapshotAuthKey`, удаляйте после использования — они занимают место в `-storageDataPath/snapshots/`.

## Ограничения и особые случаи

- `-httpAuth.*` — только HTTP Basic Auth на порту самого компонента: без TLS пароль передаётся в base64, эквивалентном открытому тексту. Basic Auth не заменяет ни прокси, ни шифрование.
- AuthKey **переопределяет** Basic Auth на своём эндпоинте: при заданном `-metricsAuthKey` запрос с корректным `-httpAuth.*`, но без `authKey=` будет отклонён с `401`.
- mTLS, IP-фильтры `ip_filters` (`allow_list`/`deny_list`), Let's Encrypt (`-tlsAutocert*`) и `vmgateway` — Enterprise-возможности; в Community остаётся сетевая изоляция и `vmauth`.
- В Community трафик `vminsert`/`vmselect` ↔ `vmstorage` не шифруется: без Enterprise изолируйте кластерную подсеть (`8400`/`8401`, `8482`).
- `vmauth` не является WAF и не хранит пароли пользователей: за выдачу и ротацию JWT отвечает внешний IdP (OIDC Discovery); начиная с v1.153.0 страница входа и cookie-сессия реализованы внутри самого `vmauth`.
- Публикация мульти-тенантных путей (`/insert/<suffix>`, `/select/<suffix>`) допустима только для доверенных источников: недоверенный клиент может испортить данные тенанта или получить доступ к чужим.
- `-httpListenAddr=unix:/path` не сочетается с `-tls` и `-httpListenAddr.useProxyProtocol`; права на сокет задаются `umask` процесса (при системном `0022` доступ только у владельца).
- Лимиты конкурентности `vmauth` (`429 Too Many Requests`) защищают от перегрузки, но не от медленного брутфорса: за этим отвечает обновление до v1.154.0+, а также сетевые/IDP-лимиты.
- Basic Auth в `vmauth` не поддерживает хеширование паролей в конфиге — пароль хранится там открытым текстом, поэтому сам `-auth.config` должен иметь права `600`.

## Дополнительная информация

### См. также

- [vmauth: прокси и маршрутизация](./vmauth_overview.md) — формат `-auth.config`, пользователи, ACL, токены;
- [VictoriaMetrics: обзор](./overview.md) — компоненты, порты, флаги;
- [Операции с кластером](./cluster_operations.md) — тенанты, изоляция, балансировка;
- [HTTP API: справочник](./http_api_reference.md) — опасные эндпоинты запись/удаление/снапшоты;
- [vmagent: обзор](./vmagent_overview.md) — сбор и доставка метрик;
- [vmalert: обзор](./vmalert_overview.md) — источники, нотификаторы, аудит;
- [VictoriaMetrics Enterprise](./enterprise_features.md) — `vmgateway`, mTLS, дополнительные функции;
- [Безопасность Prometheus](../Prometheus/security.md) — аналог для стека Prometheus (генерация сертификатов, `web-config`);
- [Сетевая безопасность Prometheus](../Prometheus/security_network.md) — firewall, NetworkPolicy, сегментация;
- [Мета-мониторинг](../Concepts/Observability_and_Monitoring/meta-monitoring.md) — безопасность системы наблюдаемости в целом.
