# Динамический анализ безопасности — DAST

## Определения

**DAST (Dynamic Application Security Testing — динамическое тестирование безопасности приложений)** — это метод анализа безопасности работающего приложения через его внешние интерфейсы (HTTP, API, WebSocket) с точки зрения внешнего пользователя («тестирование черного ящика»). Инструменты DAST взаимодействуют с приложением, имитируя поведение злоумышленника, не имея доступа к исходному коду, байт-коду или внутренней архитектуре системы.

Цель DAST — выявление уязвимостей времени выполнения (runtime), которые зависят от конфигурации сервера, сетевых настроек, состояния базы данных и реальных потоков данных.

В 2026 году DAST эволюционировал от простой автоматизации к **автономии**:
- **Autonomous Pentesting (Автономный пентестинг)** — использование ИИ-агентов на базе **LAM (Large Action Models)** и фреймворков **ReAct (Reasoning + Acting)**. Агенты самостоятельно исследуют поверхность атаки, планируют стратегию взлома и динамически адаптируют нагрузку для обхода современных WAF/IPS.
- **OAST (Out-of-band Application Security Testing)** — расширение DAST для обнаружения «слепых» уязвимостей (Blind SSRF, асинхронные инъекции). Сканер мониторит внешние коллбэки от приложения на подконтрольный сервер (например, **Interactsh** или **Burp Collaborator**) в течение длительного времени.
- **API-First DAST** — фокус на глубоком анализе бизнес-логики API (BOLA, BFLA), тестировании gRPC/Protobuf, GraphQL и защите протоколов взаимодействия ИИ-агентов, таких как **MCP (Model Context Protocol)**.

## Основные концепции

### Механизм работы DAST (Lifecycle 2026)

Процесс сканирования включает пять критических этапов:

1.  **Обнаружение (Discovery/Crawling):**
    - **Headless-краулинг:** использование браузерных движков (Playwright, Puppeteer) для рендеринга JavaScript и обнаружения путей в SPA (React, Vue, Next.js).
    - **Анализ спецификаций:** автоматический импорт OpenAPI 3.x, GraphQL-интроспекция и работа с MCP-серверами.
2.  **Фаззинг (Fuzzing):**
    - **Mutation-based:** изменение существующих запросов.
    - **Autonomous Fuzzing:** ИИ-агент подбирает пейлоады на основе семантики параметров (например, понимает, что поле `token` требует атак на JWT, а `path` — на Path Traversal).
3.  **Анализ ответов и OAST-взаимодействие:**
    - Сопоставление кодов ошибок, времени ответа и содержимого страниц.
    - Мониторинг внешних коллбэков для выявления аномалий, не возвращающих ответ напрямую.
4.  **Верификация (PoC Generation):** автоматическое создание подтверждения уязвимости (Proof-of-Concept) для исключения ложных срабатываний.
5.  **Анализ достижимости (Reachability Analysis):** корреляция с результатами SAST/SCA в рамках платформ **ASPM** для подтверждения эксплуатации уязвимых участков кода.

### Архитектура DAST-сканера (proxy/MITM-модель)

Большинство классических DAST-инструментов (в частности OWASP ZAP) работают по модели перехватывающего прокси:
- **Proxy:** сканер становится HTTP(S)-прокси между клиентом (краулером/фаззером) и целевым приложением. Весь трафик проходит через него, что позволяет модифицировать запросы «на лету» и анализировать ответы.
- **Spider/Crawler:** обходит приложение от заданной точки входа, следуя по ссылкам, формам и спецификациям (OpenAPI/GraphQL), строя модель поверхности атаки.
- **Active Scanner:** для каждого найденного параметра/эндпоинта применяет набор тестов (пейлоады) и сопоставляет ответы с сигнатурами уязвимостей.
- **Fuzzer:** подставляет мутированные/случайные значения в поля, отслеживая аномалии (ошибки, задержки, нестандартные ответы).

Именно поэтому DAST требует **работающего** приложения и сетевой доступности цели — в отличие от SAST, который анализирует код «на диске». DAST также отличается от сетевых сканеров уязвимостей (Nessus, OpenVAS), которые проверяют ОС и сервисы по версиям, а не логику приложения на уровне запросов/ответов.

### Сравнение с IAST и RASP

| Технология | Место работы | Знание кода | Основное преимущество |
| :--- | :--- | :--- | :--- |
| **DAST** | Внешний периметр | Нет (Black Box) | Обнаружение инфраструктурных проблем и ошибок конфигурации. |
| **IAST** | Внутри приложения | Частичное (Gray Box) | Высокая точность, отсутствие ложных срабатываний, обнаружение «слепых» зон. |
| **RASP** | Внутри приложения | Полное (Self-Prot) | Блокировка атак в реальном времени на основе поведения приложения. |

Подробнее о выборе подхода: **[SAST vs DAST — сравнение подходов](./sast_vs_dast.md)**. Статический анализ (SAST) подробно разобран в **[обзоре SAST](./sast_overview.md)**.

### Популярные инструменты (Классика + 2026)

| Категория | Инструменты | Особенности |
| :--- | :--- | :--- |
| **Autonomous AI** | XBOW, NodeZero, Penligent | Полная автономия: от разведки до генерации Proof-of-Concept и верификации эксплойтов. |
| **Open Source** | OWASP ZAP, Nuclei, Nikto | ZAP — универсальный прокси-сканер; Nuclei — быстрый темплейтный сканер для CVE. |
| **Enterprise** | Burp Suite, Acunetix, Checkmarx DAST | Глубокий анализ, продвинутые механизмы обхода WAF, поддержка MFA. |
| **DevOps-native** | StackHawk, GitLab DAST, Zerothreat | Ориентированы на автоматизацию, поддержку OpenAPI и современных API (gRPC, GraphQL). |
| **AI Security** | Giskard, Lakera | Специализированные инструменты для тестирования LLM и AI-агентов. |

### Типы обнаруживаемых уязвимостей

Современный DAST покрывает как классические векторы, так и специфические угрозы 2026 года:

1.  **Инъекции:** SQL, NoSQL, OS Command, LDAP, Template Injection (SSTI).
2.  **Межсайтовый скриптинг (XSS):** Отраженный, Хранимый и DOM-based.
3.  **Ошибки контроля доступа:** **IDOR** (Insecure Direct Object Reference) и **BOLA** (Broken Object Level Authorization).
4.  **Слепые уязвимости:** Blind SSRF (через OAST), Blind SQLi.
5.  **Конфигурационные ошибки:** Небезопасные заголовки (CORS, CSP, HSTS), открытые отладочные интерфейсы.
6.  **Уязвимости ИИ-агентов (2026):** **Prompt Injection** (внедрение инструкций в LLM через поля ввода) и **Tool Abuse** (несанкционированное использование инструментов MCP-сервера).
7.  **Утечка данных:** Эксфильтрация чувствительной информации (PII, секреты) в ответах API.

> Классы уязвимостей 1–5 и 7 соотносятся с **OWASP Top 10 (2021)** (A03 Injection, A01 Broken Access Control, A05 Security Misconfiguration и др.), а API-специфичные (BOLA/BFLA, см. п. 3) — с **OWASP API Security Top 10 (2023)**. Указанные выше «уязвимости ИИ-агентов» (п. 6) относятся к отдельной, быстро меняющейся области и вынесены за рамки базового DAST-конвейера.

Подробное сопоставление — в **[обзоре уязвимостей SAST/DAST](./sast_dast_vulnerabilities.md)**.

### Режимы сканирования

| Режим | Описание | Применение |
| :--- | :--- | :--- |
| **Пассивный (Passive Discovery)** | Анализ трафика и заголовков без активных воздействий. | IDE-плагины, pre-commit, быстрый аудит «на лету» без риска уронить сервис. |
| **Активный (Active Fuzzing)** | Полный набор атак: отправка вредоносных данных, проверка граничных значений. | Стейджинг, ночные сканы, регрессионные тесты безопасности. |
| **С аутентификацией** | Использование сессий (Cookie), токенов (OIDC/JWT) или MFA-байпасов. | Проверка логики личных кабинетов и административных интерфейсов. |
| **API-центричный** | Сканирование по спецификациям (OpenAPI, GraphQL, gRPC, MCP). | Современные микросервисные архитектуры и ИИ-инфраструктура. |
| **Autonomous Attack** | Режим ИИ-агента: исследование состояний приложения и динамический подбор векторов. | Глубокий пентест без написания ручных сценариев. |
| **OAST Interaction** | Отправка пейлоадов с ожиданием внешнего коллбэка. | Обнаружение уязвимостей, не возвращающих ответ напрямую (Out-of-band). |

### Ограничения

- **Покрытие (Coverage):** Краулеры могут пасовать перед сложными SPA на React/Next.js без headless-движков.
- **Слепые зоны:** DAST не видит код, который не вызывается через внешние интерфейсы. Решение — интеграция с **IAST** или **eBPF-инструментацией**.
- **Производительность:** Активный ИИ-пентест создает высокую нагрузку. Необходимо настраивать **Quality Gates** и RPS.
- **AI Hallucinations (2026):** Автономные сканеры могут генерировать ложные срабатывания в сложных цепочках логики. Требуется верификация PoC.
- **Аутентификация:** Современные схемы (MFA, SSO, биометрия) требуют сложной настройки прокси или использования «доверенных» сессионных токенов.

### Границы применимости (что DAST не увидит)

Помимо перечисленного в «Ограничениях», на практике DAST плохо покрывает:
- **Логические/бизнес-уязвимости**, требующие удержания сложного состояния (многошаговые сценарии, цепочки вызовов) — без явного описания сценария сканер их не воспроизведёт.
- **Контроль доступа без учётных данных:** BOLA/BFLA выявляются только при наличии как минимум двух разных сессий (обычный и привилегированный пользователь).
- **Уязвимости в коде, недостижимом извне:** функции, вызываемые только по внутренним очередям/крону/админским хукам, останутся вне охвата (компенсируется SAST/IAST).
- **Гонки (race conditions):** стандартные DAST-сканеры не проводят точного пошагового тайминга; требуются специализированные инструменты (например, Burp Turbo Intruder) и ручная настройка.

## Практические сценарии

### Внедрение в CI/CD и управление состоянием

Автоматизация DAST требует подготовки стабильного тестового окружения (staging или review-apps). Основные стратегии включают:
1.  **Database Snapshots:** восстановление БД перед каждым сканированием.
2.  **Review Apps:** запуск изолированной среды для каждого Pull Request.
3.  **Идемпотентность:** использование аккаунтов, действия которых не влияют на глобальное состояние системы.
4.  **Quality Gates:** автоматическая блокировка релизов при обнаружении уязвимостей критического уровня.

Подробные рекомендации описаны в **[руководстве по интеграции безопасности в CI/CD](./sast_dast_cicd_integration.md)**.

### Пример 1: Быстрый скан Nuclei с OAST в CI/CD

```yaml
nuclei_scan:
  image: projectdiscovery/nuclei:latest
  stage: test
  script:
    # Использование Interactsh для обнаружения Blind RCE/SSRF и MCP-уязвимостей
    - nuclei -target $TARGET_URL -interactsh-url https://oast.pro -severity critical,high -o reports/nuclei.json
    - nuclei -target $MCP_SERVER_URL -tags mcp,ai-security -o reports/mcp.json
  artifacts:
    paths: [reports/*.json]
```

### Пример 2: Baseline-скан OWASP ZAP в GitLab CI

```yaml
dast_baseline:
  image: owasp/zap2docker-stable
  stage: test
  variables:
    TARGET: "http://app:8080"
  script:
    # Запуск базового сканирования (пассивный анализ + ограниченный активный)
    - zap-baseline.py -t $TARGET -r zap-report.html -x zap-report.xml -m 5 -z "-config api.disablekey=true"
  artifacts:
    when: always
    paths: [zap-report.html, zap-report.xml]
```

### Пример 3: Full-скан с аутентификацией и OAST

```bash
# Запуск полного сканирования с использованием сессионной cookie и OAST-сервера
docker run --rm -v $PWD/reports:/zap/wrk \
  -e ZAP_COOKIE="session=abc123" \
  owasp/zap2docker-stable zap-full-scan.py \
  -t http://app:8080 \
  -z "-config oast.server.url=https://oast-callback.example.com" \
  -z "-config httpsessions.tokens.param.name=session -config httpsessions.tokens.param.value=$ZAP_COOKIE" \
  -r full.html -x full.xml
```

### Пример 4: API-скан GraphQL с интроспекцией

```bash
# Тестирование GraphQL API на основе интроспекции
docker run --rm -v $PWD/reports:/zap/wrk owasp/zap2docker-stable \
  zap-api-scan.py -t http://app:8080/graphql -f graphql \
  -z "-config graphql.introspection=true" \
  -r api-graphql.html -x api-graphql.xml
```

### Пример 5: API-скан по спецификации OpenAPI

```bash
# Тестирование API на основе файла спецификации
docker run --rm -v $PWD/reports:/zap/wrk owasp/zap2docker-stable \
  zap-api-scan.py -t http://app:8080/openapi.yaml -f openapi \
  -r api-openapi.html -x api-openapi.xml
```

### Пример 6: Автономный DAST-агент (StackHawk)

```yaml
stackhawk_scan:
  image: stackhawk/hawkscan:latest
  stage: security
  script:
    # Агент использует OpenAPI спецификацию для автономного исследования путей
    - hawk scan stackhawk.yml --rev-app $CI_ENVIRONMENT_URL
  variables:
    APP_ID: $HAWK_APP_ID
    API_KEY: $HAWK_API_KEY
```

### Пример 7: Автономный DAST-агент (penligent/pentest-agent)

```yaml
autonomous_pentest:
  image: penligent/agent:latest
  stage: dynamic_scan
  script:
    # Агент самостоятельно исследует API и пытается провести BOLA/IDOR атаки
    - pentest-agent scan --target $CI_ENVIRONMENT_URL --mode autonomous --report gl-dast-report.json
  artifacts:
    reports:
      dast: gl-dast-report.json
```

### Пример 8: Проверка обхода WAF (Evasion)

```bash
# Использование кастомных заголовков и кодировок для проверки WAF
nuclei -target $TARGET_URL -t templates/evasion/ -H "X-Originating-IP: 127.0.0.1" -H "User-Agent: Googlebot"
```

### Пример 9: Тестирование безопасности MCP-сервера (2026)

```bash
# Проверка MCP-сервера на возможность Tool Abuse и Prompt Injection
pentest-agent scan --target http://mcp-server:8080 --protocol mcp --mode autonomous
```

### Локальный запуск DAST-инструментов (self-hosted, без облака)

Ниже — воспроизводимые примеры для on-prem/self-hosted окружений. Все инструменты запускаются локально или на self-hosted раннере, без внешних облачных сервисов и без ИИ-компонентов. Для каждого сценария указаны предусловия, команда, проверка результата и типичные проблемы.

#### Сценарий A: OWASP ZAP baseline (Docker, пассивный + ограниченный активный)

**Предусловия:** Docker; цель доступна по сети с хоста раннера (`curl -I http://app:8080` проходит).

```bash
docker run --rm -v "$PWD/reports:/zap/wrk" \
  owasp/zap2docker-stable zap-baseline.py \
  -t http://app:8080 \
  -r zap-report.html -x zap-report.xml -J zap-report.json \
  -m 5 -z "-config api.disablekey=true"
# -t            : цель
# -m 5          : до 5 минут на spider (обход ссылок)
# -r/-x/-J      : отчёты HTML/XML/JSON
# -z            : дополнительные опции ZAP
```

**Validation:** `zap-report.json` содержит массив `alerts`; код возврата `0` (есть warnings) или `1` (есть high).

**Troubleshooting:**
- `Target not reachable` — проверить сетевую связность с хоста раннера и что стенд поднят до запуска DAST.
- Самоподписанный TLS — добавить `-z "-config httpsender.useUnsafeSSLCertificates=true"` (только в доверенном контуре).
- Долгий скан — увеличить `-m` или ограничить область через `-u` (включения).

#### Сценарий B: OWASP ZAP full-scan с аутентификацией (сессия)

**Предусловия:** валидная сессионная cookie или токен; цель доступна.

```bash
docker run --rm -v "$PWD/reports:/zap/wrk" \
  -e ZAP_SESSION="session=abc123" \
  owasp/zap2docker-stable zap-full-scan.py \
  -t http://app:8080 \
  -r full.html -x full.xml -J full.json \
  -z "-config httpsessions.tokens.param.name=session" \
  -z "-config httpsessions.tokens.param.value=$ZAP_SESSION" \
  -z "-config oast.server.url=http://interactsh.local"   # self-hosted OAST
# zap-full-scan.py выполняет полный активный скан (включая fuzzing)
```

**Validation:** в `full.json` появляются `alerts`; для OAST — коллбэки на локальном сервере.

**Troubleshooting:**
- Аутентификация падает — cookie могла истечь; используйте скрипт входа ZAP или renewal токена в пайплайне.
- OAST не срабатывает — приложение должно иметь исходящий доступ (egress) к `interactsh.local` по 53/80/443.

#### Сценарий C: OWASP ZAP API-скан (OpenAPI и GraphQL)

**Предусловия:** файл спецификации `openapi.yaml` или доступный GraphQL-эндпоинт с интроспекцией.

```bash
# OpenAPI
docker run --rm -v "$PWD/reports:/zap/wrk" owasp/zap2docker-stable \
  zap-api-scan.py -t http://app:8080/openapi.yaml -f openapi \
  -r api-openapi.html -x api-openapi.xml

# GraphQL (через интроспекцию)
docker run --rm -v "$PWD/reports:/zap/wrk" owasp/zap2docker-stable \
  zap-api-scan.py -t http://app:8080/graphql -f graphql \
  -z "-config graphql.introspection=true" \
  -r api-graphql.html -x api-graphql.xml
```

**Validation:** отчёты содержат алерты по эндпоинтам API; код возврата соответствует уровню находок.

**Troubleshooting:**
- GraphQL-интроспекция отключена — предоставьте файл схемы через `-t schema.graphql` и `-f graphql`.
- Часть методов не покрыта — явно укажите доп. спецификацию или используйте authenticated scan.

#### Сценарий D: Nuclei + локальный Interactsh (OAST, self-hosted)

**Предусловия:** Docker; целевое приложение имеет исходящий доступ к OAST-серверу на раннере.

```bash
# 1. Поднять self-hosted OAST-сервер (без внешних зависимостей)
docker run -d --name interactsh -p 53:53/udp -p 80:80 -p 443:443 \
  projectdiscovery/interactsh-server

# 2. Nuclei с указанием локального сервера для OOB-коллбэков
nuclei -u http://app:8080 -severity critical,high \
  -interactsh-server http://<IP_хоста_раннера>:80 -o nuclei.txt -json
```

**Validation:** `nuclei.txt` — matched templates; для blind SSRF/RCE — записи коллбэков в логах `interactsh`.

**Troubleshooting:**
- OOB не срабатывает — проверить, что приложение может достучаться до `IP_хоста_раннера` по 53/80/443; фаервол раннера не блокирует входящие коллбэки.
- Пусто — проверить живость `-u`; добавить `-silent=false` для диагностики.

#### Сценарий E: Фаззинг параметров ffuf

**Предусловия:** бинарь `ffuf`; словарь (например, `seclists`).

```bash
ffuf -u http://app:8080/api?FUZZ=test \
  -w /usr/share/seclists/Discovery/Web-Content/raft-medium-words.txt \
  -mc all -t 40 -p 0.0 -s
# FUZZ     : место подстановки из словаря
# -mc all  : показывать все коды ответа (далее фильтруем аномалии)
# -t 40    : параллелизм
# -p 0.0   : без задержки (осторожно на prod-подобных стендах)
```

**Validation:** вывод показывает ответы, отличающиеся от базового (аномалии по коду/длине) — кандидаты на уязвимые параметры.

**Troubleshooting:**
- Высокий шум — фильтровать `-fc 404`, `-fs <baseline_len>`.
- WAF/rate-limit блокирует — снизить `-t`, добавить `-rate` или заголовки `-H`.

#### Сценарий F: Проверка SQL-инъекций sqlmap

**Предусловия:** бинарь `sqlmap`; целевой параметр идентифицирован.

```bash
sqlmap -u "http://app:8080/item?id=1" --batch --level=2 --risk=1 \
  --output-dir=reports/sqlmap
# --level/--risk : глубина/агрессивность тестов
# --batch        : без интерактивного ввода
```

**Validation:** `reports/sqlmap/<target>/log` содержит подтверждение инъекции (тип СУБД, вектор эксплуатации).

**Troubleshooting:**
- Ничего не найдено — параметр может быть защищён WAF; снизить `--risk`, использовать `--tamper`.
- Блокировка по частоте — `--delay` и `--safe-url` для удержания сессии.

#### Сценарий G: Обзор поверхности (Nikto, feroxbuster)

```bash
# Базовая проверка конфигурации веб-сервера
nikto -h http://app:8080 -output nikto.txt

# Content discovery (брастинг каталогов)
feroxbuster -u http://app:8080 -x php,html,js -d 2 -o ferox.txt
```

**Validation:** `nikto.txt` — найденные заголовки/файлы; `ferox.txt` — обнаруженные пути.

**Troubleshooting:**
- Много 404-шума у feroxbuster — настроить `-C` (auto-calibration) или фильтры; для Nikto — игнорировать известные файлы через `-evasion`/`--nointeractive`.

#### Сценарий H: Quality Gate (bash, self-hosted)

Минимальный скрипт, читающий отчёты и завершающий сборку при критических находках:

```bash
#!/usr/bin/env bash
set -euo pipefail
FAIL=0

# ZAP: считаем alerts с riskcode 3 (High)
DAST_HIGH=$(jq '[.alerts[]? | select(.riskcode=="3")] | length' reports/zap-report.json || echo 0)
echo "DAST high: $DAST_HIGH"

# Nuclei: число matched results
NUCLEI=$(grep -c "\[.*\]" reports/nuclei.txt || true)
echo "Nuclei findings: $NUCLEI"

[ "$DAST_HIGH" -gt 0 ] && FAIL=1
exit $FAIL
```

**Troubleshooting:** если `jq` отсутствует — установить (`apt-get install jq` или эквивалент); проверять наличие файлов отчётов перед парсингом.

### Операционные рекомендации для DevOps/SRE/Sysadmin

- **Где запускать:** DAST требует развёрнутого приложения — ставьте его на review-apps или staging, параллельно деплою стенда, а не на этап сборки. Раннер должен иметь сетевой доступ к цели, но стенд не должен иметь выхода в прод (egress allowlist). Используйте изолированный network namespace / VLAN / docker network, чтобы фаззинг не затронул смежные системы.
- **Ресурсы и сайзинг:** ZAP/Nuclei требуют ~2 vCPU и 4 ГБ RAM; для больших приложений увеличьте heap JVM ZAP через переменную окружения `JAVA_OPTS=-Xmx2g`. Активный скан создаёт значительную нагрузку — планируйте ночные/периодические запуски.
- **Ограничение нагрузки (RPS):** чтобы не вызвать эффект DDoS на тестовую БД, ограничивайте скорость. В ZAP — через `-z "-config rules.codenomicon.attackstrength=LOW"` и throttle; в Nuclei — флаг `-rate 50` (запросов/сек). Контролируйте RPS на стороне стенда.
- **Самоподписанные сертификаты:** DAST должен доверять TLS цели — для ZAP добавьте `-z "-config httpsender.useUnsafeSSLCertificates=true"` (только в доверенном контуре!).
- **Аутентификация на практике:** передавайте сессионные токены через защищённые CI-переменные; для сложных схем (SSO/MFA) используйте скрипты входа ZAP или renewal токена в пайплайне. Не сканируйте деструктивные методы (например, `DELETE /api/v1/users/all`) без бэкапа.
- **Идемпотентность и сброс данных:** используйте снимки БД (Database Snapshots) или миграции для возврата среды в исходное состояние после активного скана; применяйте выделенные тестовые аккаунты, действия которых не влияют на глобальное состояние.
- **Хранение и ротация отчётов:** сохраняйте артефакты в локальном хранилище (например, MinIO/S3-совместимое или NFS) с ротацией; конвертируйте отчёты в **SARIF** для дашбордов безопасности. DAST часто используют для проверки обхода WAF — см. также **[Межсетевой экран веб-приложений (WAF)](../../Security/ApplicationSecurity/waf.md)**.
- **Triage и подавление:** каждая находка High+ → тикет; подавление (suppression) только через review с обоснованием; регулярный пересмотр базовой линии технического долга. Используйте baseline-файл ZAP для подавления известных ложных срабатываний.
- **Расписание:** ночные/периодические сканы на staging; для каждого PR — быстрый baseline (passive). Подробные пайплайны — в **[руководстве по интеграции безопасности в CI/CD](./sast_dast_cicd_integration.md)**.

## Дополнительная информация

### Рекомендации по настройке (2026)

- **ASPM Orchestration:** Интегрируйте результаты DAST в платформы **ASPM (Application Security Posture Management)** для корреляции с находками SAST и SCA.
- **Исключайте маршруты:** Не сканируйте деструктивные методы (например, `DELETE /api/v1/users/all`) или нерелевантные эндпоинты (health-чеки) без бэкапа.
- **Используйте SARIF:** Конвертируйте отчеты в формат **SARIF** для отображения в Security Dashboards (GitHub/GitLab).
- **Ограничивайте нагрузку:** Настраивайте RPS, чтобы не вызвать DDoS-эффект на тестовую базу данных.
- **Интеграция с eBPF:** Внедряйте рантайм-инструментацию (Tetragon, Pixie) для отслеживания системных вызовов, провоцируемых DAST-запросами. Это помогает выявить RCE, скрытые от внешнего анализа.
- **Сброс данных:** Используйте снимки БД или миграции для возврата среды в исходное состояние после активного скана.

## См. также

- **[Сравнение подходов SAST vs DAST](./sast_vs_dast.md)**
- **[Интеграция безопасности в CI/CD](./sast_dast_cicd_integration.md)**
- **[Уязвимости SAST и DAST](./sast_dast_vulnerabilities.md)**
