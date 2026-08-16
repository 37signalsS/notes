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

### Сравнение с IAST и RASP

| Технология | Место работы | Знание кода | Основное преимущество |
| :--- | :--- | :--- | :--- |
| **DAST** | Внешний периметр | Нет (Black Box) | Обнаружение инфраструктурных проблем и ошибок конфигурации. |
| **IAST** | Внутри приложения | Частичное (Gray Box) | Высокая точность, отсутствие ложных срабатываний, обнаружение «слепых» зон. |
| **RASP** | Внутри приложения | Полное (Self-Prot) | Блокировка атак в реальном времени на основе поведения приложения. |

Подробнее о выборе подхода: **[SAST vs DAST — сравнение подходов](./sast_vs_dast.md)**.

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

## Дополнительная информация

### Рекомендации по настройке (2026)

- **ASPM Orchestration:** Интегрируйте результаты DAST в платформы **ASPM (Application Security Posture Management)** для корреляции с находками SAST и SCA.
- **Исключайте маршруты:** Не сканируйте деструктивные методы (например, `DELETE /api/v1/users/all`) или нерелевантные эндпоинты (health-чеки) без бэкапа.
- **Используйте SARIF:** Конвертируйте отчеты в формат **SARIF** для отображения в Security Dashboards (GitHub/GitLab).
- **Ограничивайте нагрузку:** Настраивайте RPS, чтобы не вызвать DDoS-эффект на тестовую базу данных.
- **Интеграция с eBPF:** Внедряйте рантайм-инструментацию (Tetragon, Pixie) для отслеживания системных вызовов, провоцируемых DAST-запросами. Это помогает выявить RCE, скрытые от внешнего анализа.
- **Сброс данных:** Используйте снимки БД или миграции для возврата среды в исходное состояние после активного скана.

## См. также

- **[Статический анализ безопасности (SAST)](./sast_overview.md)**
- **[Сравнение подходов SAST vs DAST](./sast_vs_dast.md)**
- **[Интеграция безопасности в CI/CD](./sast_dast_cicd_integration.md)**
- **[Уязвимости SAST и DAST](./sast_dast_vulnerabilities.md)**
- **[Межсетевой экран веб-приложений (WAF)](../Security/ApplicationSecurity/waf.md)**
- **[Безопасность сетевого взаимодействия](../Networking/overview.md)**
