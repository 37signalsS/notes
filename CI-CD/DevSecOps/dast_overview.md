# Динамический анализ безопасности — DAST

## Определения

**DAST (Dynamic Application Security Testing — динамическое тестирование безопасности приложений)** — это метод анализа безопасности работающего приложения с точки зрения внешнего пользователя («тестирование черного ящика»). Инструменты DAST взаимодействуют с приложением через его внешние интерфейсы (HTTP, API), имитируя поведение злоумышленника без доступа к исходному коду.

Цель DAST — выявление уязвимостей рантайма (runtime), которые зависят от конфигурации сервера, сетевых настроек и реальных данных.

## Базовые концепции

### Популярные инструменты

| Категория | Инструменты | Особенности |
| :--- | :--- | :--- |
| **Open Source** | OWASP ZAP, Nuclei | ZAP — универсальный сканер; Nuclei — быстрый темплейтный сканер для CI/CD. |
| **Enterprise** | Burp Suite, Acunetix | Глубокий анализ, продвинутые механизмы обхода WAF. |
| **DevOps-native** | StackHawk, GitLab DAST | Ориентированы на автоматизацию, поддержку OpenAPI и современных фреймворков. |

### Типы обнаруживаемых уязвимостей

Сканеры динамического анализа ориентированы на обнаружение уязвимостей времени выполнения, которые сложно или невозможно выявить статическим анализом. Основные категории включают:

- Инъекции (SQL, NoSQL, Command)
- Межсайтовый скриптинг (XSS — Cross-Site Scripting)
- Ошибки аутентификации и управления сессиями
- Недостатки контроля доступа (IDOR — Insecure Direct Object Reference)
- Подделка запросов на стороне сервера (SSRF — Server-Side Request Forgery)
- Небезопасные конфигурации (заголовки безопасности, CORS — Cross-Origin Resource Sharing)

Полный список уязвимостей с сопоставлением по инструментам — в [обзоре уязвимостей SAST/DAST](./sast_dast_vulnerabilities.md).

### Режимы сканирования

| Режим | Описание | Применение |
| :--- | :--- | :--- |
| **Пассивный** | Анализ HTTP-ответов без отправки вредоносных данных. | Быстрые проверки в Pull Requests, аудит заголовков. |
| **Активный** | Полный набор атак (fuzzing), включая попытки инъекций. | Стейджинг, ночные сканы, регрессионные тесты. |
| **С аутентификацией** | Использование сессий (Cookie) или токенов (Bearer/OIDC). | Проверка логики, доступной только авторизованным пользователям. |
| **API-центричный** | Сканирование эндпоинтов по спецификациям (OpenAPI, GraphQL, gRPC). | Современные микросервисные архитектуры. |

### Ограничения

- **Покрытие (Coverage):** Краулеры часто пасуют перед SPA (Single Page Applications) на React/Vue без ручной настройки сценариев.
- **Слепые зоны:** DAST не видит код, который не вызывается через внешние интерфейсы. Решение — использование **IAST (Interactive AST)**.
- **Производительность:** Глубокое сканирование может занимать часы. В CI/CD рекомендуется использовать инкрементальные сканы или Nuclei-темплейты.
- **Аутентификация:** Сложные схемы (MFA, SSO, OIDC) требуют сложной настройки прокси или скриптов логина.

## Практические сценарии

### Внедрение в CI/CD

Автоматизация DAST требует подготовки стабильного тестового окружения (staging или review-apps). Основные стратегии включают разделение сканов на быстрые проверки при каждом изменении и глубокий анализ по расписанию.

Подробные рекомендации и примеры конвейерных конфигураций описаны в [руководстве по интеграции безопасности в CI/CD](./sast_dast_cicd_integration.md).

### Пример: Быстрый скан Nuclei в CI/CD

Nuclei позволяет выполнять проверки по конкретным шаблонам, что идеально подходит для коротких пайплайнов.

```yaml
nuclei_scan:
  image: projectdiscovery/nuclei:latest
  stage: test
  script:
    # Сканирование на критические CVE и ошибки конфигурации
    - nuclei -target $TARGET_URL -severity critical,high -o nuclei-report.json
    # → Результат: быстрый отчет nuclei-report.json с фокусом на критичные уязвимости
  artifacts:
    paths:
      - nuclei-report.json
```

### Пример: Baseline-скан OWASP ZAP в GitLab CI

```yaml
dast_baseline:
  image: owasp/zap2docker-stable
  stage: test
  variables:
    TARGET: "http://app:8080"
  script:
    # Запуск базового сканирования (пассивный анализ + ограниченный активный)
    - zap-baseline.py -t $TARGET -r zap-baseline.html -x zap-baseline.xml -m 5 -z "-config api.disablekey=true"
    # → Результат: отчеты zap-baseline.html и zap-baseline.xml с найденными проблемами
  artifacts:
    when: always
    paths:
      - zap-baseline.html
      - zap-baseline.xml
  allow_failure: false
```

### Пример: Full-скан с аутентификацией

```bash
# Запуск полного сканирования с использованием сессионной cookie
docker run --rm --network host \
  -v $PWD/reports:/zap/wrk \
  -e ZAP_COOKIE="session=abc123" \
  owasp/zap2docker-stable zap-full-scan.py \
  -t http://app:8080 \
  -r full.html -x full.xml \
  -z "-config api.disablekey=true -config spider.maxDuration=10" \
  -z "-config selenium.firefoxDriver=/usr/bin/geckodriver" \
  -z "-config httpsessions.tokens.param.name=session -config httpsessions.tokens.param.value=$ZAP_COOKIE"
# → Результат: глубокий отчет full.html, включая защищенные разделы приложения
```

### Пример: API-скан по спецификации OpenAPI

```bash
# Тестирование API на основе файла спецификации
docker run --rm -v $PWD/reports:/zap/wrk owasp/zap2docker-stable \
  zap-api-scan.py -t http://app:8080/openapi.yaml -f openapi \
  -r api.html -x api.xml -z "-config api.disablekey=true"
# → Результат: проверка всех эндпоинтов, описанных в openapi.yaml
```

## Дополнительная информация

### Рекомендации по настройке

- **Исключайте маршруты:** не сканируйте деструктивные методы (например, `DELETE /api/v1/users/all`) или нерелевантные эндпоинты (health-чеки).
- **Используйте SARIF:** для интеграции отчетов в GitLab/GitHub Security Dashboard конвертируйте отчеты сканеров в формат **SARIF (Static Analysis Results Interchange Format)**.
- **Ограничивайте нагрузку:** настраивайте скорость запросов (RPS), чтобы не вызвать DDoS-эффект на тестовую базу данных.
- **Интеграция с IAST:** если возможно, используйте IAST-агентов совместно с DAST для подтверждения уязвимостей в коде и уменьшения False Positives.
- **Сброс данных:** используйте миграции или снимки БД для возврата среды в исходное состояние после каждого активного скана.

## См. также

- [Статический анализ безопасности (SAST)](./sast_overview.md)
- [Сравнение подходов SAST vs DAST](./sast_vs_dast.md)
- [Интеграция безопасности в CI/CD](./sast_dast_cicd_integration.md)
