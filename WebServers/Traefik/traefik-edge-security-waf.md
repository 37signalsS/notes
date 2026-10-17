# Traefik + CrowdSec: файрвол и WAF на edge

**Актуально для:** Traefik v3.3+, CrowdSec v1.6+, crowdsec-bouncer-traefik-plugin v1.5+ (с поддержкой Traefik v2.11+)

## Определения

**Edge Security (Безопасность периметра)** — комплекс мер фильтрации, инспекции и разграничения доступа на точке входа в инфраструктуру (ingress/reverse proxy) до того, как сетевой трафик достигает внутренних прикладных сервисов.

**WAF (Web Application Firewall)** — защитный экран прикладного уровня (L7), анализирующий HTTP/HTTPS-запросы на наличие признаков атак (SQLi, XSS, RCE, Path Traversal) с использованием сигнатур и правил (например, OWASP CRS).

**CrowdSec** — модульная open-source система обнаружения и предотвращения вторжений (IPS/IDS) с поведенческим анализом. Анализирует системные и прикладные журналы (логи), выявляет аномалии и атаки, генерирует локальные блокировки и обменивается анонимизированными сигналами репутации IP-адресов в глобальной CTI-сети (Cyber Threat Intelligence).

**LAPI (Local API)** — центральный управляющий демон CrowdSec: хранит базу локальных и глобальных решений (decisions/банов), управляет аутентификацией агентов и баундеров, синхронизирует списки блокировок.

**CrowdSec Engine (Агент)** — фоновый сервис, выполняющий разбор логов через парсеры (`parsers`), сопоставление событий со сценариями атак (`scenarios`) и отправку решений о блокировке в LAPI.

**Bouncer (Ремедиатор)** — компонент CrowdSec, применяющий решения о блокировке на конкретном уровне сетевого стека. Для Traefik баундер реализован в виде middleware-плагина (`crowdsec-bouncer-traefik-plugin`), исполняемого интерпретатором Yaegi внутри процесса Traefik.

**AppSec Component** — встроенный в CrowdSec (начиная с v1.6.0) WAF-модуль реального времени. Выполняет синхронную инспекцию тела (body), заголовков и параметров HTTP-запросов на основе правил ModSecurity/OWASP CRS, обеспечивая виртуальный патчинг уязвимостей.

**Virtual Patching (Виртуальный патчинг)** — блокировка попыток эксплуатации известных уязвимостей на уровне WAF без внесения изменений в исходный код целевого приложения.

**Yaegi** — встроенный в Traefik интерпретатор языка Go, исполняющий динамические community-плагины без необходимости перекомпиляции основного бинарного файла Traefik.

**Fail-Open / Fail-Close** — стратегия поведения системы защиты при недоступности сервиса инспекции (LAPI или AppSec): Fail-Open пропускает трафик при сбое, предотвращая отказ в обслуживании (DoS легитимных клиентов); Fail-Close блокирует трафик, ставя безопасность выше доступности.

## Архитектура и принципы работы

### Архитектурная модель: асинхронный и синхронный контуры

Интеграция Traefik и CrowdSec объединяет два независимых контура защиты:

```
[ Клиент (HTTP/HTTPS) ]
         │
         ▼
┌────────────────────────────────── Traefik Edge Proxy ───────────────────────────────────┐
│ EntryPoint (:80 / :443)                                                                  │
│   │                                                                                     │
│   ▼                                                                                     │
│ [ Middleware: crowdsec-bouncer ]                                                        │
│   │                                                                                     │
│   ├── 1. Проверка IP (in-memory кэш / Redis) ──▶ [ Локальный бан: 403 Forbidden ]      │
│   │                                                                                     │
│   └── 2. Синхронный запрос инспекции WAF ───┐ (AppSec HTTP API :7422)                   │
│                                             │                                           │
│   ┌─────────────────────────────────────────┘                                           │
│   ▼                                                                                     │
│ [ Роутер / Сервис бэкенда ] ──▶ Ответ клиенту                                           │
│   │                                                                                     │
│   └─▶ Запись access.log (JSON) в shared volume / сокет                                  │
└───────────────────────┬─────────────────────────────────────────────────────────────────┘
                        │ (Асинхронный контур)
                        ▼
┌───────────────────────────────── CrowdSec Container ────────────────────────────────────┐
│ [ Log Acquisition (acquis.yaml) ]                                                       │
│   │ читает access.log Traefik                                                           │
│   ▼                                                                                     │
│ [ CrowdSec Engine ] ──▶ Parsers (traefik-logs) ──▶ Scenarios (HTTP CVE, Brute-force)    │
│   │                                                                                     │
│   ▼ Создание решения (Decision)                                                         │
│ [ Local API (LAPI :8080) ] ◀── Периодическая синхронизация решений (Stream Mode)        │
│   ▲                      └──▶ Отправка сигналов в CTI Community                         │
│   │                                                                                     │
│ [ AppSec Engine (:7422) ] ◀── Синхронная инспекция тела/заголовков (OWASP CRS)          │
└─────────────────────────────────────────────────────────────────────────────────────────┘
```

1. **Асинхронный контур (Поведенческий анализ логов):**
   - Traefik обрабатывает запросы и непрерывно пишет журнал `access.log` в формате JSON.
   - CrowdSec Engine через механизм `acquisition` считывает логи, парсит их с помощью коллекции `crowdsecurity/traefik` и сопоставляет с паттернами атак (перебор паролей, сканирование уязвимостей, шторм ошибок `4xx/5xx`).
   - При срабатывании сценария Engine передает решение о блокировке (Decision) в LAPI (например: `IP 198.51.100.25 -> ban na 4h`).
   - Нагрузка на критический путь обработки HTTP-запроса отсутствует.

2. **Синхронный контур (L7-репутация и WAF-инспекция):**
   - Каждый входящий запрос перехватывается middleware-плагином `crowdsec-bouncer-traefik-plugin`.
   - Плагин извлекает реальный IP-адрес клиента (с учетом доверенных прокси) и проверяет его по локальному кэшу решений.
   - Если включен `crowdsecAppsecEnabled: true`, плагин отправляет тело, заголовки и URI запроса в AppSec-компонент CrowdSec (порт 7422).
   - При совпадении с правилами WAF или наличии активного бана плагин прерывает запрос и возвращает код `403 Forbidden` (или страницу проверки `Captcha`).

### Режимы работы плагина-баундера (crowdsecMode)

В плагине `crowdsec-bouncer-traefik-plugin` реализовано 5 режимов работы:

| Режим (`crowdsecMode`) | Механика работы | Задержка на запрос (Latency) | Рекомендация для SRE / Production |
| :--- | :--- | :--- | :--- |
| **`stream`** | Плагин раз в `updateIntervalSeconds` (по умолчанию 60 сек) опрашивает LAPI и загружает дельту заблокированных IP в локальный in-memory кэш. Проверка входящих запросов идет исключительно по памяти. | **< 0.1 мс** (локальный lookup) | **Основной стандарт для High-Load и Production.** Нулевое влияние сетевых вызовов на RPS. |
| **`live`** | Плагин проверяет локальный кэш. При промахе (новый IP) выполняет блокирующий HTTP-запрос к LAPI и сохраняет ответ в кэш на `defaultDecisionSeconds`. | **1–15 мс** при cache miss | Допустим для низконагруженных сервисов с высокими требованиями к мгновенному применению банов. |
| **`appsec`** | Проверка репутации IP отключается. Выполняется только инспекция запроса через AppSec WAF. | **1–5 мс** (инспекция тела) | Применяется, если фильтрация IP вынесена на уровень ядра Linux (eBPF, iptables, nftables). |
| **`alone`** | Автономный режим: баундер опрашивает напрямую Central API (CAPI) CrowdSec раз в 2 часа, минуя локальный LAPI. Локальные сценарии не работают. | **< 0.1 мс** (in-memory кэш) | Изолированные серверы без развертывания CrowdSec Engine. |
| **`none`** | Синхронный HTTP-запрос к LAPI на каждый входящий запрос без кэширования. | **5–30 мс** на каждый запрос | **Запрещен в Production** (перегружает LAPI, деградирует latency). |

### Fail2ban против CrowdSec в архитектуре Traefik

В инфраструктуре на базе Linux и Docker классический `Fail2ban` имеет системные архитектурные ограничения:

1. **Обход цепочки INPUT в Docker NAT:** Docker манипулирует таблицами `iptables` и направляет трафик контейнеров через цепочки `PREROUTING` и `DOCKER-USER` в обход стандартной цепочки `INPUT`, куда Fail2ban по умолчанию добавляет правила `DROP`. В результате запросы продолжают поступать в Traefik.
2. **Изоляция нод:** Fail2ban защищает только одну виртуальную машину. CrowdSec синхронизирует решения между кластером серверов через единый LAPI.
3. **Глубина анализа:** Fail2ban оперирует примитивными регулярными выражениями над текстовыми строками. CrowdSec использует типизированные парсеры (JSON, Syslog) с поддержкой обогащения метаданными (GeoIP, автономные системы AS, обратный DNS).

## Практические сценарии и конфигурация

### Сценарий 1: Production-развертывание Traefik v3 + CrowdSec в Docker Compose

Полнофункциональный стек с общей сетью, общим томом для логов, включенным AppSec WAF и режимом `stream`.

Структура каталогов на хосте:

```
/opt/edge-security/
├── docker-compose.yml
└── crowdsec/
    ├── acquis.yaml
    └── parsers/
```

Файл `/opt/edge-security/crowdsec/acquis.yaml`:

```yaml
# 1. Сбор и разбор access-логов Traefik
filenames:
  - /var/log/traefik/access.log
labels:
  type: traefik
---
# 2. Инспекция прикладного трафика (AppSec WAF)
source: appsec
listen_addr: 0.0.0.0:7422
appsec_config: crowdsecurity/appsec-default
labels:
  type: appsec
```

Файл `/opt/edge-security/docker-compose.yml`:

```yaml
services:
  crowdsec:
    image: crowdsecurity/crowdsec:v1.6.4
    container_name: crowdsec
    restart: unless-stopped
    environment:
      COLLECTIONS: >-
        crowdsecurity/linux
        crowdsecurity/traefik
        crowdsecurity/http-cve
        crowdsecurity/appsec-virtual-patching
        crowdsecurity/appsec-generic-rules
        crowdsecurity/whitelist-good-actors
      GIN_MODE: release
    volumes:
      - crowdsec-db:/var/lib/crowdsec/data
      - crowdsec-config:/etc/crowdsec
      - ./crowdsec/acquis.yaml:/etc/crowdsec/acquis.yaml:ro
      - traefik-logs:/var/log/traefik:ro
    networks:
      - internal-net
    ports:
      # LAPI и AppSec слушают только во внутренней сети контейнеров!
      - "127.0.0.1:8080:8080"

  traefik:
    image: traefik:v3.3.4
    container_name: traefik
    restart: unless-stopped
    depends_on:
      - crowdsec
    command:
      - "--api.dashboard=false"
      - "--entrypoints.web.address=:80"
      - "--entrypoints.websecure.address=:443"
      - "--providers.docker=true"
      - "--providers.docker.exposedbydefault=false"
      # Подключение плагина CrowdSec Bouncer
      - "--experimental.plugins.crowdsec-bouncer.modulename=github.com/maxlerebourg/crowdsec-bouncer-traefik-plugin"
      - "--experimental.plugins.crowdsec-bouncer.version=v1.5.0"
      # Настройка AccessLog в формате JSON для CrowdSec Engine
      - "--accesslog=true"
      - "--accesslog.filepath=/var/log/traefik/access.log"
      - "--accesslog.format=json"
      - "--accesslog.bufferingSize=100"
    environment:
      - CROWDSEC_LAPI_KEY=${CROWDSEC_LAPI_KEY}
    volumes:
      - /var/run/docker.sock:/var/run/docker.sock:ro
      - traefik-logs:/var/log/traefik
    networks:
      - internal-net
      - public-net
    ports:
      - "80:80"
      - "443:443"
    labels:
      - "traefik.enable=true"
      # Определение middleware плагина баундера
      - "traefik.http.middlewares.crowdsec-waf.plugin.crowdsec-bouncer.enabled=true"
      - "traefik.http.middlewares.crowdsec-waf.plugin.crowdsec-bouncer.crowdsecMode=stream"
      - "traefik.http.middlewares.crowdsec-waf.plugin.crowdsec-bouncer.crowdsecLapiUrl=http://crowdsec:8080"
      - "traefik.http.middlewares.crowdsec-waf.plugin.crowdsec-bouncer.crowdsecLapiKey=${CROWDSEC_LAPI_KEY}"
      - "traefik.http.middlewares.crowdsec-waf.plugin.crowdsec-bouncer.updateIntervalSeconds=60"
      # AppSec WAF параметры
      - "traefik.http.middlewares.crowdsec-waf.plugin.crowdsec-bouncer.crowdsecAppsecEnabled=true"
      - "traefik.http.middlewares.crowdsec-waf.plugin.crowdsec-bouncer.crowdsecAppsecHost=crowdsec:7422"
      - "traefik.http.middlewares.crowdsec-waf.plugin.crowdsec-bouncer.crowdsecAppsecFailureBlock=false"
      # Доверенные IP для извлечения X-Forwarded-For (подсети Docker/LB)
      - "traefik.http.middlewares.crowdsec-waf.plugin.crowdsec-bouncer.forwardedHeadersTrustedIPs=127.0.0.1/32,10.0.0.0/8,172.16.0.0/12,192.168.0.0/16"

  backend-app:
    image: nginx:1.27-alpine
    container_name: backend-app
    restart: unless-stopped
    networks:
      - internal-net
    labels:
      - "traefik.enable=true"
      - "traefik.http.routers.backend.rule=Host(`app.internal.example`)"
      - "traefik.http.routers.backend.entrypoints=web"
      - "traefik.http.routers.backend.middlewares=crowdsec-waf@docker"
      - "traefik.http.services.backend.loadbalancer.server.port=80"

volumes:
  crowdsec-db:
  crowdsec-config:
  traefik-logs:

networks:
  public-net:
    driver: bridge
  internal-net:
    driver: bridge
```

### Сценарий 2: Первичная инициализация баундера и генерация ключа

Перед запуском связки необходимо сгенерировать токен аутентификации баундера в LAPI.

```bash
# 1. Запуск CrowdSec для генерации конфигурации и баз данных
docker compose up -d crowdsec
# → Container crowdsec  Started

# 2. Создание учетной записи bouncer в LAPI и получение API-ключа
docker compose exec crowdsec cscli bouncers add traefik-bouncer
# → Api key for 'traefik-bouncer':
# →
# →    c8f2b3e41a9985d26f04746ecf137e2a
# →
# → Please keep this key safe, you won't be able to retrieve it again.

# 3. Экспорт переменной окружения в файл .env
echo "CROWDSEC_LAPI_KEY=c8f2b3e41a9985d26f04746ecf137e2a" > .env

# 4. Запуск всех сервисов
docker compose up -d
# → Container traefik  Started
# → Container backend-app  Started

# 5. Проверка статуса подключения баундера
docker compose exec crowdsec cscli bouncers list
# → -----------------------------------------------------------------------------------------------------------------------
# →  NAME             IP ADDRESS  VALID  LAST API PULL         TYPE                       VERSION  AUTH TYPE
# → -----------------------------------------------------------------------------------------------------------------------
# →  traefik-bouncer  172.20.0.3  ✔      2026-10-17T12:00:00Z  crowdsec-traefik-plugin    v1.5.0   api-key
# → -----------------------------------------------------------------------------------------------------------------------
```

### Сценарий 3: Конфигурация через File Provider (Bare-Metal / On-Premise)

Для высоконагруженных bare-metal инсталляций без Docker socket используется файловый провайдер динамической конфигурации.

Файл статической конфигурации `traefik.yml`:

```yaml
entryPoints:
  web:
    address: ":80"
    forwardedHeaders:
      trustedIPs:
        - "127.0.0.1/32"
        - "192.168.1.0/24"

providers:
  file:
    directory: "/etc/traefik/dynamic"
    watch: true

experimental:
  plugins:
    crowdsec-bouncer:
      moduleName: "github.com/maxlerebourg/crowdsec-bouncer-traefik-plugin"
      version: "v1.5.0"

accessLog:
  filePath: "/var/log/traefik/access.log"
  format: "json"
  bufferingSize: 50
```

Файл динамической конфигурации `/etc/traefik/dynamic/waf-middleware.yml`:

```yaml
http:
  middlewares:
    crowdsec-waf:
      plugin:
        crowdsec-bouncer:
          enabled: true
          logLevel: "INFO"
          crowdsecMode: "stream"
          updateIntervalSeconds: 30
          defaultDecisionSeconds: 60
          crowdsecLapiUrl: "http://127.0.0.1:8080"
          crowdsecLapiKey: "c8f2b3e41a9985d26f04746ecf137e2a"
          crowdsecAppsecEnabled: true
          crowdsecAppsecHost: "127.0.0.1:7422"
          crowdsecAppsecFailureBlock: false
          crowdsecAppsecUnreachableBlock: false
          crowdsecAppsecBodyLimit: 10485760 # 10 MB лимит инспекции тела
          forwardedHeadersTrustedIPs:
            - "127.0.0.1/32"
            - "192.168.1.0/24"

  routers:
    corporate-app:
      rule: "Host(`service.corp.local`)"
      entryPoints:
        - web
      middlewares:
        - crowdsec-waf
      service: corporate-service

  services:
    corporate-service:
      loadBalancer:
        servers:
          - url: "http://10.10.10.50:8080"
```

### Сценарий 4: Валидация защиты и симуляция инцидентов

#### Тест 1: Проверка блокировки AppSec WAF (виртуальный патчинг SQLi / XSS)

В отличие от поведенческого анализа, AppSec WAF блокирует атаку с первого же запроса в реальном времени.

```bash
# Выполняем тестовый запрос с сигнатурой SQL Injection в строке запроса
curl -i -s -H "Host: app.internal.example" "http://127.0.0.1/?id=1%27%20UNION%20SELECT%20null,username,password%20FROM%20users--"
# → HTTP/1.1 403 Forbidden
# → Content-Type: text/plain; charset=utf-8
# → Date: Sat, 17 Oct 2026 12:05:00 GMT
# → Content-Length: 9
# →
# → Forbidden

# Проверка алерта в консоли CrowdSec
docker compose exec crowdsec cscli alerts list -l 1
# → --------------------------------------------------------------------------------------------------------
# →  ID   SCOPE:VALUE        ACTION  REASON                                   EVENTS  DATE
# → --------------------------------------------------------------------------------------------------------
# →  1    Ip:192.168.1.15    ban     crowdsecurity/appsec-generic-rules       1       2026-10-17 12:05:00
# → --------------------------------------------------------------------------------------------------------
```

#### Тест 2: Проверка поведенческой блокировки сканирования (L7 Brute-force / 404 шторм)

```bash
# Симуляция сканирования чувствительных эндпоинтов (404 Not Found)
for i in $(seq 1 60); do
  curl -s -o /dev/null -w "%{http_code}\n" -H "Host: app.internal.example" "http://127.0.0.1/admin-probe-$i.php"
done
# → Первые запросы возвращают 404, затем 403 Forbidden

# Проверка созданного решения
docker compose exec crowdsec cscli decisions list
# → -------------------------------------------------------------------------------------------------------
# →  ID    SOURCE    SCOPE:VALUE      ACTION  REASON                        EVENTS  EXPIRATION  ALERT ID
# → -------------------------------------------------------------------------------------------------------
# →  42    crowdsec  Ip:192.168.1.15  ban     crowdsecurity/http-crawl-non_existent_url  60      3h59m       2
# → -------------------------------------------------------------------------------------------------------
```

### Сценарий 5: Тюнинг AppSec и подавление ложных срабатываний (False Positives)

При интеграции WAF легитимные запросы к REST API (например, передача фрагментов Markdown, SQL-запросов в админке или сложных JSON) могут вызывать ложные срабатывания (False Positives).

1. Определите идентификатор сработавшего правила через детальный просмотр алерта:

```bash
docker compose exec crowdsec cscli alerts inspect 1
# → Вывод содержит: rule_name: "crowdsecurity/appsec-generic-rules"
# → и appsec_rule_id: "00000001-0000-0000-0000-000000000002"
```

2. Создайте файл исключений `/opt/edge-security/crowdsec/appsec-rules/exclusions.yaml`:

```yaml
name: custom/admin-markdown-allow
description: "Отключение проверки тела для эндпоинта редактирования статей"
appsec_rules:
  - 00000001-0000-0000-0000-000000000002
conditions:
  - req.Host == 'app.internal.example'
  - req.URI startsWith '/api/v1/articles/edit'
  - req.Method == 'POST'
```

3. Перезагрузите сервис CrowdSec:

```bash
docker compose exec crowdsec cscli hub update
docker compose restart crowdsec
# → Container crowdsec  Started
```

## Эксплуатация и регламентные команды

Все операции управления, мониторинга и администрирования выполняются утилитой `cscli` внутри контейнера или на хосте.

### Управление решениями и блокировками (Decisions)

| Операция | Команда | Ожидаемый результат / Назначение |
| :--- | :--- | :--- |
| **Список активных банов** | `cscli decisions list` | Таблица всех активных IP, причин и времени истечения бана |
| **Ручной бан IP** | `cscli decisions add --ip 203.0.113.10 --duration 24h --reason "Manual SRE ban"` | `# → decision successfully added` |
| **Бан подсети (CIDR)** | `cscli decisions add --range 198.51.100.0/24 --duration 1h --reason "Botnet range"` | `# → decision successfully added` |
| **Удаление бана по IP** | `cscli decisions delete --ip 203.0.113.10` | `# → 1 decision(s) deleted` |
| **Удаление всех банов** | `cscli decisions delete --all` | Полная очистка локальной базы решений |

### Управление ремедиаторами (Bouncers)

```bash
# Список зарегистрированных баундеров и время последней активности
cscli bouncers list
# → Выводит список с колонками NAME, IP ADDRESS, VALID, LAST API PULL, TYPE

# Создание нового токена для баундера
cscli bouncers add edge-traefik-02
# → Возвращает API Key для передачи в конфигурацию

# Удаление устаревшего баундера
cscli bouncers delete edge-traefik-old
# → bouncer 'edge-traefik-old' deleted
```

### Управление коллекциями и правилами WAF (Hub)

```bash
# Проверка установленных коллекций
cscli collections list
# → Список установленных коллекций правил

# Обновление метаданных каталога Hub
cscli hub update
# → downloaded hub index

# Обновление всех установленных правил и парсеров до актуальных версий
cscli hub upgrade
# → upgraded crowdsecurity/traefik, crowdsecurity/appsec-generic-rules

# Установка коллекции для защиты WordPress / специфичных CMS при необходимости
cscli collections install crowdsecurity/wordpress
# → collection crowdsecurity/wordpress installed successfully
```

### Диагностика телеметрии и парсеров

```bash
# Анализ метрик парсинга логов Traefik
cscli metrics
# → Таблицы:
# → Route metrics: сколько строк прочитано из /var/log/traefik/access.log
# → Parser metrics: сколько строк успешно распарсено парсером crowdsecurity/traefik
# → Scenario metrics: какие сценарии зафиксировали совпадения
```

## Устранение неисправностей

| Симптом / Ошибка | Первопричина | Диагностика | Решение |
| :--- | :--- | :--- | :--- |
| **`Error getting bouncer stream` в логах Traefik** | Неверный `crowdsecLapiKey` либо сетевая изоляция LAPI. | `docker logs traefik \| grep crowdsec`<br>`docker compose exec traefik nc -zv crowdsec 8080` | Проверить соответствие ключа выводу `cscli bouncers list`. Убедиться, что Traefik и CrowdSec находятся в общей Docker-сети. |
| **Все входящие клиенты получают `403 Forbidden`** | Ошибочно заблокирован шлюз или proxy из-за `0.0.0.0/0` в `forwardedHeadersTrustedIPs`. | `cscli decisions list`<br>Проверка заголовка `X-Forwarded-For` в access.log | Очистить бан шлюза: `cscli decisions delete --ip <IP>`. Жестко ограничить `forwardedHeadersTrustedIPs` только доверенными upstream-прокси. |
| **AppSec WAF не блокирует SQLi/XSS** | Слушатель AppSec не запущен или плагин не обращается на порт `7422`. | `docker compose logs crowdsec \| grep appsec`<br>`docker compose exec traefik nc -zv crowdsec 7422` | Убедиться, что в `acquis.yaml` объявлен блок `source: appsec` со `listen_addr: 0.0.0.0:7422`, и в Traefik задан `crowdsecAppsecHost=crowdsec:7422`. |
| **Отказ LAPI приводит к 500/502 на всех роутерах** | Включен режим Fail-Close при недоступности AppSec или LAPI. | `docker logs traefik` фиксирует timeouts к `http://crowdsec:8080` | Выставить `crowdsecAppsecFailureBlock: false` и `crowdsecAppsecUnreachableBlock: false`. В продакшене перевести `crowdsecMode` в `stream`. |
| **CrowdSec Engine не реагирует на атаки (0 алертов)** | Логи Traefik не поступают в контейнер CrowdSec или тип парсера не совпадает. | `cscli metrics` показывает 0 прочитанных строк в `acquisition` | Проверить монтирование общего тома `traefik-logs`. Убедиться, что в Traefik задан `--accesslog.format=json`, а в `acquis.yaml` указан лейбл `type: traefik`. |
| **Все клиенты отображаются с IP `172.x.x.1`** | Отсутствует обработка заголовков проксирования за балансировщиком/NAT. | В `access.log` поле `ClientAddr` указывает на шлюз Docker | Настроить `entryPoints.web.forwardedHeaders.trustedIPs` в Traefik и добавить IP балансировщика в доверенные. |
| **Рост потребления памяти процессом Traefik** | Чрезмерно большой размер локального кэша плагина в режиме `live` при DDoS. | Мониторинг resident memory Traefik: `docker stats traefik` | Переключить режим на `stream`, при котором в памяти хранятся только заблокированные IP, либо подключить внешний `Redis` к плагину. |

## Рекомендации и SRE-чеклист

### Защита от подмены заголовков (IP Spoofing)

Плагин извлекает IP-адрес клиента из заголовков `X-Forwarded-For` или `X-Real-IP`.

> [!CAUTION]
> Никогда не используйте `forwardedHeadersTrustedIPs: 0.0.0.0/0` на публичном периметре. Злоумышленник может отправить поддельный заголовок `X-Forwarded-For: 1.1.1.1` и обойти блокировку либо вызвать ложный бан доверенного адреса.

- В параметре `forwardedHeadersTrustedIPs` перечисляйте **только** адреса upstream-балансировщиков (HAProxy, Keepalived VIP, локальные шлюзы).
- В конфигурации EntryPoint Traefik активируйте `forwardedHeaders.trustedIPs` с аналогичными доверенными подсетями.

### Выбор архитектурного режима (Live vs Stream)

- Для боевых продуктивных сред (RPS > 100) обязательно используйте `crowdsecMode: stream`.
- Настройте таймер обновления `updateIntervalSeconds: 30` или `60`. Задержка в 30 секунд между генерацией бана в LAPI и его применением на edge полностью компенсируется нулевым оверхедом на инспекцию IP.
- Режим `live` резервируйте исключительно для сред с низким трафиком или тестовых контуров.

### Отказоустойчивость и безопасность (Fail-Open)

- При проектировании edge-инфраструктуры разделяйте доступность и фильтрацию: сбой контейнера CrowdSec не должен приводить к падению публичного сайта.
- Устанавливайте параметры:
  - `crowdsecAppsecFailureBlock: false`
  - `crowdsecAppsecUnreachableBlock: false`
- При таком подходе временная недоступность LAPI приведет к пропуску запросов (Fail-Open), но не нарушит доступность для пользователей.

### Белые списки (Whitelisting)

Чтобы исключить риск блокировки систем мониторинга, сканеров безопасности CI/CD и офисных шлюзов, настройте локальный парсер белых списков в CrowdSec.

Создайте файл `/opt/edge-security/crowdsec/parsers/s02-enrich/00-whitelist.yaml`:

```yaml
name: custom/corporate-whitelists
description: "Исключение корпоративных IP и мониторинга из банов"
whitelist:
  reason: "Corporate internal IP addresses"
  ip:
    - "127.0.0.1"
    - "192.168.1.100" # Prometheus scraper
  cidr:
    - "10.100.0.0/16" # Корпоративный VPN
```

### Мониторинг и алертинг

1. **Экспорт метрик CrowdSec:**
   CrowdSec экспортирует метрики в формате Prometheus на порту `6060` (эндпоинт `/metrics`). Контролируйте ключевые показатели:
   - `cs_active_decisions` — количество активных заблокированных IP.
   - `cs_alerts_total` — интенсивность генерации алертов.
   - `cs_reader_hits_total` — поток считываемых строк логов Traefik.
2. **Метрики Traefik:**
   Отслеживайте динамику кодов `403 Forbidden` через стандартную метрику `traefik_http_requests_total{code="403"}`. Резкий скачок указывает либо на начавшуюся L7-атаку, либо на ложные срабатывания WAF после релиза новой версии приложения.

## Дополнительная информация

- [Плагины Traefik](./traefik-plugins.md) — механизмы загрузки, компиляции и манифесты плагинов в среде Yaegi.
- [Харденинг безопасности Traefik](./traefik-security-hardening.md) — TLS-профили, защита от DDoS, безопасные HTTP-заголовки.
- [Middleware безопасности Traefik](./traefik-middlewares-security.md) — настройка BasicAuth, ForwardAuth и IPAllowList.
- [Доверенные заголовки и X-Forwarded-For](./traefik-forwarded-headers.md) — корректная обработка клиентских IP через обратные прокси.
- [Наблюдаемость и метрики Traefik](./traefik-observability.md) — экспорт метрик в Prometheus и конфигурирование JSON-логов.
- [Прикладная безопасность: WAF](../../Security/ApplicationSecurity/waf.md) — классификация WAF, OWASP Core Rule Set и тюнинг правил.
- [Защита от ботов и скрейпинга](../Concepts/bot_protection.md) — противодействие автоматизированному сканированию и парсингу.
- [Инъекции SQL (SQL Injection)](../../Security/ApplicationSecurity/sql_injection.md) — векторы атак, выявляемые модулем AppSec WAF.
- [XSS и Content Security Policy](../../Security/ApplicationSecurity/xss_and_csp.md) — межсайтовый скриптинг и защита заголовками.