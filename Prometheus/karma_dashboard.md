# Дашборд Karma

## Определения

**Karma** — дашборд с открытым исходным кодом для [Alertmanager](./alertmanager.md), предоставляющий расширенный пользовательский интерфейс для визуализации, фильтрации и управления оповещениями. В отличие от встроенного интерфейса Alertmanager, Karma спроектирована для работы в масштабных средах (Enterprise-уровень), где присутствуют сотни оповещений и десятки кластеров мониторинга.

На 2026 год Karma (версии 0.120+) остается стандартом де-факто для визуализации алертов в экосистеме Prometheus благодаря высокой скорости работы UI на React, поддержке агрегации из множества источников и встроенному механизму контроля доступа (ACL).

| Характеристика | Описание |
| :--- | :--- |
| **Тип приложения** | Stateless (без сохранения состояния на бэкенде, всё хранится в Alertmanager). |
| **Архитектура** | Бэкенд на Go, Фронтенд на React. |
| **Порт по умолчанию** | `8080` |
| **Интеграции (2026)** | Поддержка OIDC/OAuth2 "из коробки" для авторизации UI. |
| **Роль в пайплайне** | Агрегатор и визуализатор алертов. Prometheus → Alertmanager → Karma (UI) → SRE. |

**См. также:** [Alertmanager](./alertmanager.md), [Обзор Prometheus](./overview.md), [Service Discovery](./service_discovery_and_relabeling.md).

## Основные концепции

### Агрегация и дедупликация

Karma может собирать данные из неограниченного количества инстансов Alertmanager. Если один и тот же алерт (с идентичными метками) присутствует на нескольких серверах (например, в разных дата-центрах или в HA-паре Alertmanager), Karma автоматически объединяет их в одну карточку в интерфейсе, добавляя бейджи с именами источников.

Важно: дедупликация происходит на стороне Karma на основе набора меток. Если Alertmanager в разных кластерах присвоил алертам разные метки (например, `cluster=prod-east` и `cluster=prod-west`), Karma отобразит две отдельные карточки.

### Продвинутая фильтрация

Ключевая особенность Karma — мощный язык запросов для поиска алертов. Фильтры работают прямо в строке поиска UI:

*   `severity=critical` — поиск по точному совпадению метки.
*   `cluster!=prod` — исключение по метке.
*   `instance=~.*-web-.*` — поиск по регулярному выражению.
*   `@state=active` — фильтрация по состоянию (active, suppressed, unprocessed).
*   `@age>1h` — фильтрация по времени существования алерта (старше 1 часа).
*   `@receiver=slack` — фильтрация по получателю уведомлений (куда Alertmanager отправил алерт).
*   `@silence=created-by:sre-team` — фильтрация по автору Silence.
*   `@alertmanager=Production` — фильтрация по источнику Alertmanager.

### Подтверждения (Acknowledgements)

Karma позволяет отмечать алерты как подтверждённые (acknowledged). Это не подавляет уведомление (в отличие от Silence), но помечает алерт как "рассмотренный" и добавляет в карточку информацию о том, кто подтвердил и когда. В крупных командах acknowledgements снижают шум, так как SRE-инженер может отметить алерт, который уже принят в работу, без создания тишины.

### Управление замалчиваниями (Silences)

Karma предоставляет удобный интерфейс не только для просмотра активных замалчиваний, но и для их создания. Пользователь может в один клик создать Silence на основе текущих активных фильтров. Karma выступает как прокси, отправляя API-запрос на создание замалчивания напрямую в целевой Alertmanager.

Для работы создания silences через UI требуется `proxy: true` в конфигурации сервера Alertmanager. Без этого параметра Karma отображает алерты только в режиме чтения.

### Контроль доступа (ACL) и Авторизация

В современных версиях Karma поддерживает аутентификация через **OIDC (OpenID Connect)**. Это позволяет привязывать права доступа к группам пользователей из корпоративных каталогов (Keycloak, Azure AD, Okta). ACL позволяет:
*   Ограничить создание замалчиваний для критичных кластеров.
*   Запретить удаление чужих замалчиваний.
*   Настроить Read-Only режим для определенных пользователей.

При интеграции с OIDC важно правильно сопоставить группы из Identity Provider с правилами ACL в `config.yaml`. Karma не выполняет синхронизацию групп самостоятельно — это происходит на стороне IdP, а Karma лишь читает claims из JWT-токена.

### Представление данных: Grid и Table

Karma поддерживает два режима отображения алертов:
*   **Grid (сетка):** компактное представление с миниатюрами карточек. Подходит для общего обзора при большом количестве алертов.
*   **Table (таблица):** детальная таблица с сортировкой по колонкам. Подходит для анализа конкретных инцидентов.

Режим отображения можно задать в `config.yaml` в секции `grid` или переключать вручную через UI.

### История алертов

Karma может хранить историю закрытых алертов в памяти (в рамках сессии UI) или персистировать её в файл на хосте. В production-средах с высокой частотой алертов рекомендуется ограничить `history.retentionPeriod` (по умолчанию 24 часа), чтобы избежать утечек памяти на бэкенде.

### Сравнение: Karma vs Grafana Alerting vs Alertmanager UI

| Критерий | Karma | Grafana Alerting | Alertmanager UI |
| :--- | :--- | :--- | :--- |
| **Назначение** | Агрегатор алертов из множества Alertmanager | Управление алертами и дашборды | Встроенный UI одного Alertmanager |
| **Мультикластер** | Да — агрегация из неограниченного числа инстансов | Ограниченно (через多个 data sources) | Нет — один инстанс |
| **Фильтрация** | Мощный язык запросов (`@state=active severity=critical`) | Базовые фильтры по меткам | Минимальная |
| **Управление Silences** | Через UI (proxy: true) | Через UI | Через UI |
| **ACL** | Встроенный (OIDC + правила) | Через Grafana RBAC | Нет |
| **Метрики** | Экспортирует `/metrics` (Prometheus format) | Встроенные метрики Grafana | Нет |
| **Хранение состояния** | Stateless | В Grafana DB | В Alertmanager (silences) |
| **Простота развёртывания** | Отдельный бинарник/контейнер | Требует Grafana | Встроен в Alertmanager |
| **Когда использовать** | Мультикластер, централизованный обзор, ACL | Если Grafana уже является основным UI | Одиночный кластер, быстрый старт |

> **Практическая рекомендация:** В средах с одним кластером Alertmanager и Grafana — достаточно Grafana Alerting. Karma нужен когда: (1) несколько кластеров/инстансов Alertmanager, (2) требуется централизованный ACL для silences, (3) нужен lightweight UI без полной установки Grafana.

## Практические сценарии

### Запуск через Docker (одиночный инстанс Alertmanager)

В простых средах конфигурация передается через переменные окружения.

```bash
docker run -d \
  -p 8080:8080 \
  -e ALERTMANAGER_URI="http://alertmanager:9093" \
  -e ALERTMANAGER_NAME="Main-Cluster" \
  -e KARMA_NAME="Monitoring Dashboard" \
  -e FILTERS_DEFAULT="@state=active severity=critical" \
  ghcr.io/prymitive/karma:v0.131
```

**Ожидаемый результат:**
```bash
# → 7a3b2c1d4e5f6a7b8c9d0e1f2a3b4c5d6e7f8a9b
docker logs <container_id> 2>&1 | head -20
# → level=info msg="Starting Karma" version=v0.131.0
# → level=info msg="Connected to Alertmanager" name="Main-Cluster"
```

### Docker Compose (стек с Alertmanager)

Для сред, где Alertmanager и Karma развёрнуты через Docker Compose, добавьте сервис `karma` в существующий `compose.yml`. Это исключает необходимость внешнего reverse proxy для локальной разработки.

```yaml
services:
  karma:
    image: ghcr.io/prymitive/karma:v0.131
    container_name: karma
    restart: unless-stopped
    ports:
      - "8080:8080"
    environment:
      - ALERTMANAGER_URI=http://alertmanager:9093
      - ALERTMANAGER_NAME=Main-Cluster
      - KARMA_NAME=Monitoring Dashboard
      - FILTERS_DEFAULT=@state=active
    depends_on:
      alertmanager:
        condition: service_healthy
    healthcheck:
      test: ["CMD", "wget", "--quiet", "--tries=1", "--spider", "http://localhost:8080/health"]
      interval: 30s
      timeout: 5s
      retries: 3
      start_period: 10s
    networks:
      - monitoring

networks:
  monitoring:
    driver: bridge
```

**Валидация:**
```bash
docker compose up -d karma
# → Container karma  Started

docker compose ps karma
# → NAME      IMAGE                             COMMAND                  SERVICE   STATUS
# → karma     ghcr.io/prymitive/karma:v0.131    "/bin/karma --config.…"   karma     running (healthy)

curl -s http://localhost:8080/health
# → {"status":"healthy"}
```

### Развёртывание на bare-metal/VM (systemd)

Для хостовых систем без контейнеризации используйте бинарный файл и unit-файл systemd.

#### Предварительные требования

*   Linux-система с systemd v219+ (RHEL/CentOS 8+, Debian 11+, Ubuntu 20.04+).
*   Скачанный бинарный файл Karma (`karma-linux-amd64`) из [официального релиза](https://github.com/prymitive/karma/releases).
*   Развёрнутый Alertmanager, доступный по сети (`http://alertmanager.internal:9093`).
*   Пользователь `karma` без прав root:
    ```bash
    sudo useradd --system --no-create-home --shell /usr/sbin/nologin karma
    ```

#### Создание unit-файла

**`/etc/systemd/system/karma.service`**

```ini
[Unit]
Description=Karma Alertmanager Dashboard
Documentation=https://github.com/prymitive/karma
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=karma
Group=karma
ExecStart=/usr/local/bin/karma \
  --config.file=/etc/karma/config.yaml \
  --listen.address=0.0.0.0:8080
Restart=on-failure
RestartSec=30
LimitNOFILE=65536

# Hardening
NoNewPrivileges=true
ProtectSystem=full
ProtectHome=true
PrivateTmp=true
PrivateDevices=true
ProtectKernelTunables=true
ProtectKernelModules=true
ProtectControlGroups=true
RestrictSUIDSGID=true
RestrictNamespaces=true

[Install]
WantedBy=multi-user.target
```

**Включение и запуск:**
```bash
sudo systemctl daemon-reload
sudo systemctl enable --now karma
# → Created symlink /etc/systemd/system/multi-user.target.wants/karma.service

sudo systemctl status karma
# → ● karma.service - Karma Alertmanager Dashboard
# →      Loaded: loaded (/etc/systemd/system/karma.service; enabled)
# →      Active: active (running) since Thu 2026-09-17 18:00:00 UTC; 30s ago
```

**Проверка работоспособности:**
```bash
curl -s http://localhost:8080/health
# → {"status":"healthy"}

# Проверка доступности Alertmanager из-под пользователя karma
sudo -u karma curl -s http://alertmanager.internal:9093/api/v2/alerts
# → [] или JSON со списком алертов
```

### Конфигурация YAML: расширенные параметры

Для сложных инсталляций используется файл `config.yaml`. Ниже приведён полный пример с комментариями к каждому разделу.

```yaml
# config.yaml
alertmanager:
  interval: 1m        # Частота опроса серверов Alertmanager
  timeout: 10s        # Таймаут запроса к API Alertmanager
  servers:
    - name: "Production"
      uri: "http://alertmanager-prod:9093"
      proxy: true     # Разрешить создание silences через Karma UI
      timeout: 5s      # Переопределение глобального таймаута для этого сервера
    - name: "Staging"
      uri: "http://alertmanager-stage:9093"
      proxy: false     # Только чтение

labels:
  # Скрывать технические метки из общего списка для чистоты UI
  strip: ["prometheus", "job"]
  # Порядок отображения важных меток в карточке алерта
  keep: ["alertname", "severity", "cluster", "service"]

annotations:
  # Скрывать громоздкие аннотации (например, ссылки на Grafana)
  strip: ["runbook_url", "source_link"]
  # Приоритетные аннотации всегда показывать свернутыми
  keep: ["summary", "description"]

acknowledgements:
  expiry: 168h        # Через сколько часов подтверждения автоматически сбрасываются
  autoClose: false    # Автоматически закрывать алерт при подтверждении

history:
  retentionPeriod: 24h # Как долго хранить историю закрытых алертов в UI

grid:
  sorting:
    default: severity  # Сортировка по умолчанию: severity, age, state
    order: desc
  autoRefreshInterval: 30s # Автообновление списка алертов

silenceForm:
  defaultAuthor: "sre-oncall"  # Автор по умолчанию при создании тишины
  defaultComment: "Planned maintenance" # Комментарий по умолчанию

# Настройка контроля доступа
acl:
  silences:
    - action: allow
      filters:
        - cluster!=prod
    - action: block
      filters:
        - cluster=prod
      reason: "Создание тишины на prod разрешено только группе SRE."
```

### Nginx как reverse proxy (bare-metal)

В хостовых средах Karma обычно публикуется за reverse proxy (Nginx или Apache). Ниже минимальный пример конфигурации Nginx с Basic Auth и SSL termination.

**`/etc/nginx/conf.d/karma.conf`**

```nginx
upstream karma_backend {
    server 127.0.0.1:8080;
    keepalive 16;
}

server {
    listen 443 ssl http2;
    server_name karma.internal.example.com;

    ssl_certificate     /etc/ssl/certs/karma.crt;
    ssl_certificate_key /etc/ssl/private/karma.key;

    # Ограничения и hardening
    client_max_body_size 1M;
    proxy_read_timeout 60s;

    location / {
        auth_basic "Monitoring Dashboard";
        auth_basic_user_file /etc/nginx/.karma_passwd;

        proxy_pass http://karma_backend;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;

        # WebSocket поддержка (если используется)
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
    }
}
```

**Валидация конфигурации:**
```bash
sudo nginx -t
# → nginx: configuration file /etc/nginx/nginx.conf test is successful

sudo systemctl reload nginx
# → (без вывода при успехе)

curl -s -o /dev/null -w "%{http_code}" -u sre-user:password https://karma.internal.example.com/health
# → 200
```

### Валидация развёртывания

После установки Karma в любой среде выполните стандартный набор проверок:

```bash
# 1. Health endpoint
curl -s http://<karma-host>:8080/health
# → {"status":"healthy"}

# 2. Подключение к Alertmanager через UI:
#    Откройте браузер → https://karma.internal/ → статус подключения "OK"

# 3. Создание тестового Silence:
#    UI Karma → Filters: @state=active alertname=TestAlert → Silence
#    Проверьте в Alertmanager:
curl -s http://alertmanager:9093/api/v2/silences | jq length
# → 1 (должна появиться новая тишина)

# 4. Проверка метрик:
curl -s http://<karma-host>:8080/metrics | grep karma_alertmanager_errors_total
# → karma_alertmanager_errors_total 0
```

### Тестирование шаблонов уведомлений через Karma

Karma позволяет визуально проверить, что алерты отображаются корректно с нужными метками, аннотациями и группировкой. Это полезно при разработке или изменении Go-шаблонов Alertmanager.

**Сценарий:**

1.  **Отправьте тестовый алерт** в Alertmanager с нужными метками и аннотациями:

```bash
curl -XPOST http://alertmanager:9093/api/v1/alerts -d '[{
  "labels": {
    "alertname": "TestTemplateAlert",
    "severity": "critical",
    "service": "web-api",
    "instance": "web-01.prod"
  },
  "annotations": {
    "summary": "Тестовый алерт для проверки шаблона",
    "description": "Этот алерт создан для визуальной проверки отображения в Karma.",
    "runbook_url": "https://wiki.example.com/runbooks/test-template"
  }
}]'
```

2.  **Откройте UI Karma** и найдите алерт по фильтру:

```
alertname=TestTemplateAlert
```

3.  **Проверьте отображение:**
    - Метки `severity`, `service`, `instance` отображаются в карточке (не скрыты `labels.strip`).
    - Аннотации `summary` и `description` видны в карточке.
    - Аннотация `runbook_url` скрыта (настроена в `annotations.strip`).
    - Алерт сгруппирован по `alertname` и `severity` (настроено в `grouping.by`).

4.  **Проверьте Silence:** создайте тишину через UI Karma и убедитесь, что она появилась в Alertmanager:

```bash
curl -s http://alertmanager:9093/api/v2/silences | jq '.[].id'
# → "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx"
```

5.  **Удалите тестовый алерт** после проверки:

```bash
curl -XDELETE http://alertmanager:9093/api/v1/silence/<silence_id>
```

> **Совет:** Используйте `@state=active` в фильтре Karma для отображения только активных алертов. Для проверки `resolved`-состояния отправьте алерт и подождите `for`-период (или используйте `amtool` для немедленного закрытия).

## Дополнительная информация

### Мониторинг самой Karma

Karma экспортирует собственные метрики в формате Prometheus по пути `/metrics`.

*   `karma_alertmanager_errors_total` — счетчик ошибок при опросе бэкендов Alertmanager (важно для алертинга).
*   `karma_collected_alerts_count` — текущее количество собранных алертов со всех источников.
*   `karma_alertmanager_requests_duration_seconds` — гистограмма времени ответа от серверов Alertmanager.
*   `karma_ui_load_duration_seconds` — время загрузки UI (полезно для отслеживания деградации производительности на стороне клиента).
*   `karma_silences_total` — количество активных silences, видимых через Karma.

Рекомендуемые алерты на метрики Karma:
```yaml
# alertmanager_silences_total > 50 — аномальное количество тишин, возможно забытые заглушки
- alert: KarmaSilencesBuildup
  expr: karma_silences_total > 50
  for: 10m
  labels:
    severity: warning
  annotations:
    summary: "Большое количество активных silences в Karma"

# karma_alertmanager_errors_total увеличивается за 5m
- alert: KarmaAlertmanagerErrors
  expr: increase(karma_alertmanager_errors_total[5m]) > 10
  for: 5m
  labels:
    severity: critical
  annotations:
    summary: "Karma не может опросить Alertmanager"
```

### Безопасность

#### Reverse Proxy и аутентификация (bare-metal)

В хостовых средах используйте Nginx/Traefik с Basic Auth или OIDC. Для Basic Auth создайте файл паролей:
```bash
sudo htpasswd -c /etc/nginx/.karma_passwd sre-user
# → New password: ****
# → Re-type new password: ****
```

Важно: Basic Auth передаёт credentials в base64, что эквивалентно plaintext. Обязательно используйте HTTPS (Let's Encrypt или внутренний CA).

#### Рекомендации по развёртыванию

1.  **Read-only панели:** Для TV-панелей в офисе или публичных экранов используйте переменную окружения `KARMA_READ_ONLY=true` или параметр `readonly: true` в YAML. Это исключает случайное создание или удаление silences.
2.  **Network Policies (Kubernetes):** Разрешайте доступ к порту 8080 только от Ingress-контроллера.
3.  **OIDC Groups:** Сопоставляйте корпоративные группы с ACL-правилами. Избегайте overly broad правил (например, `action: allow` без фильтров).
4.  **HTTPS:** Всегда используйте TLS termination на уровне reverse proxy или Ingress. Karma сама по себе не предоставляет HTTPS.

### Устранение неисправностей

| Симптом | Возможная причина | Диагностика и решение |
| :--- | :--- | :--- |
| UI показывает "disconnected" | Неверный `alertmanager.servers.uri` или сеть | `curl -s http://<alertmanager>:9093/api/v2/alerts` из хоста/пода Karma. |
| Кнопка "Silence" неактивна | `proxy: false` или недоступность Alertmanager | Проверьте `config.yaml`: `proxy: true` и корректность `uri`. |
| Метрики Karma отсутствуют | Бэкенд не стартовал или порт 8080 закрыт | `curl -s http://localhost:8080/metrics`; проверка firewall. |
| Ошибки при опросе Alertmanager | Недоступность бэкенда, таймаут, невалидный сертификат | `karma_alertmanager_errors_total` растёт; проверка TLS если URI=https. |
| Утечка памяти при большом количестве алертов | Слишком большой `history.retentionPeriod` или отсутствие лимитов | Уменьшите `history.retentionPeriod`; проверьте лимиты памяти systemd/Docker. |
| Парсинг YAML завершается ошибкой | Синтаксическая ошибка или неподдерживаемый параметр | `karma --config.file=/etc/karma/config.yaml --dry-run` (если поддерживается версией); проверка через `yamllint`. |
| Конфигурация не применяется | В systemd бинарник запущен с флагом без указания файла | `systemctl cat karma | grep config.file`; перезапуск после исправления. |
| OIDC редирект работает по HTTP, а не HTTPS | В `authentication.oidc` не указан `issuer` с HTTPS или `redirect_uri` неверный | Проверьте `config.yaml`: `issuer` должен начинаться с `https://`; в IdP добавьте HTTPS redirect URI. |

### Резервное копирование и управление конфигурацией

*   **Версионирование:** Храните `config.yaml` в Git-репозитории вместе с манифестами развёртывания. Это обеспечивает аудит изменений и совместимость с GitOps-процессами.
*   **Экспорт silences:** Для disaster recovery регулярно экспортируйте активные silences через API Alertmanager:
    ```bash
    curl -s http://alertmanager:9093/api/v2/silences > /backups/alertmanager-silences-$(date +%Y%m%d).json
    ```
*   **Валидация перед применением:** После изменения `config.yaml` проверяйте синтаксис и перезапускайте Karma. В Kubernetes — `kubectl rollout restart`. В systemd — `sudo systemctl restart karma`.

### Производительность и масштабирование

*   **Количество алертов:** Karma комфортно работает с несколькими тысячами активных алертов на одном инстансе. При превышении 10 000 карточек рекомендуется:
    *   Увеличить лимиты памяти до `512Mi` (Docker) или настроить cgroup лимиты в systemd.
    *   Отключить `history` или уменьшить `retentionPeriod` до `1h`.
    *   Использовать агрессивную фильтрацию по умолчанию (`FILTERS_DEFAULT`).
*   **Частота опроса:** Уменьшение `alertmanager.interval` с `1m` до `30s` увеличивает нагрузку на Alertmanager API. Используйте значение не ниже `30s` при количестве источников более 5.
*   **Режим прокси:** `proxy: true` активирует создание silences через UI, что добавляет write-запросы к Alertmanager. В Read-Only средах (TV-панели, публичный доступ) всегда используйте `proxy: false`.

### Миграция с Alertmanager UI на Karma

При переходе со встроенного UI Alertmanager на Karma обратите внимание на следующие особенности:
*   **Mute Timings:** Karma не предоставляет интерфейс для управления Mute Timings. Используйте для этого UI Alertmanager или `amtool`.
*   **Inhibition Rules:** Управление inhibition-правилами остаётся в конфигурационном файле Alertmanager (`inhibit_rules` в `alertmanager.yml`). Karma только визуализирует результат их работы.
*   **Режимы отображения:** Grid view в Karma эмулирует компактный список, но не заменяет полностью функционал Alertmanager UI для тонкой настройки маршрутизации.

> **Практическое руководство:** Пошаговые инструкции по развёртыванию Karma в Kubernetes через ConfigMap и Deployment находятся в разделе [Alertmanager + Karma в Kubernetes: манифесты](./kubernetes/examples/alertmanager-karma-manifests-tutorial/intro.md).
