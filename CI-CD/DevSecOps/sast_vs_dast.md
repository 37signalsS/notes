# SAST vs DAST: сравнение подходов

## Определения

**SAST (Static Application Security Testing — статическое тестирование безопасности приложений)** и **DAST (Dynamic Application Security Testing — динамическое тестирование безопасности приложений)** — взаимодополняющие подходы к тестированию безопасности приложений.

- **SAST** — «белый ящик»: анализ исходного/байт-кода до запуска приложения.
- **DAST** — «черный ящик»: тестирование работающего приложения через внешние интерфейсы.

Детальные обзоры: [SAST](./sast_overview.md), [DAST](./dast_overview.md).

## Базовые концепции

### Сравнение по ключевым критериям

| Критерий | SAST | DAST |
| :--- | :--- | :--- |
| **Этап** | PR (Pull Request) / MR (Merge Request), сборка | Тест/стейджинг после деплоя |
| **Контекст** | Статический анализ кода | Рантайм, реальная конфигурация |
| **Скорость** | Быстро (инкрементально), долго (полный скан) | Средне/долго (зависит от сложности) |
| **False positives** | Часты без настройки | Реже (зависят от среды/аутентификации) |
| **Покрытие** | 100% кода (включая неиспользуемый) | Только доступные маршруты |
| **Требования** | Исходный код, правила | Развернутая среда, тестовые креды |
| **Цель** | Найти дефекты до выполнения | Подтвердить эксплуатацию |

### Типы обнаруживаемых уязвимостей

- **SAST:** инъекции (SQL, Command, LDAP), небезопасная десериализация, ошибки логики авторизации, слабые криптоалгоритмы, секреты в коде.
- **DAST:** XSS (Cross-Site Scripting), ошибки заголовков (HSTS — HTTP Strict Transport Security, CSP — Content Security Policy), уязвимости сессий, CSRF (Cross-Site Request Forgery), SSRF (Server-Side Request Forgery), открытые редиректы.

Полное сопоставление — в [обзоре уязвимостей SAST/DAST](./sast_dast_vulnerabilities.md).

### Ограничения

- **SAST:** зависит от качества правил; пропускает уязвимости из генерации кода; требует настройки для снижения шума.
- **DAST:** чувствителен к качеству среды; не покрывает скрытые эндпоинты; может создавать нагрузку на тестовое окружение.

## Практические сценарии

### Порядок интеграции в CI/CD

1. **SAST на PR/MR** — инкрементальный анализ изменённого кода.
2. **DAST на review-окружении** — после деплоя временной среды.
3. **Ночной регресс** — полный скан обоих типов.
4. **Pre-release gate** — финальная проверка перед релизом.

### Пример: GitLab CI

```yaml
stages: [test, security, deploy]

sast:
  stage: security
  image: registry.example.com/tools/sast:latest
  script:
    # Анализ в формате SARIF (Static Analysis Results Interchange Format)
    - ./sast --path . --format sarif --out sast.sarif
    - ./severity-gate sast.sarif --fail-on high
  artifacts:
    paths: [sast.sarif]

deploy_review:
  stage: deploy
  script:
    - ./deploy.sh --env review
  environment:
    name: review/$CI_COMMIT_REF_SLUG
    url: https://$CI_COMMIT_REF_SLUG.review.example.com

dast:
  stage: security
  needs: ["deploy_review"]
  image: registry.example.com/tools/dast:latest
  script:
    - ./dast --target $CI_ENVIRONMENT_URL --login-file creds.json --out dast.json
    - ./severity-gate dast.json --fail-on medium
  artifacts:
    paths: [dast.json]
```

Детали интеграции — в [SAST/DAST в CI/CD](./sast_dast_cicd_integration.md).

## Дополнительная информация

### Комбинированная стратегия

- **Shift Left:** SAST в IDE (Integrated Development Environment) + pre-commit хуки для ранней обратной связи.
- **Shift Right:** DAST в ночных сборках с полной аутентификацией.
- **Корреляция:** связывание отчётов SAST/DAST для приоритизации эксплуатируемых уязвимостей.

### Рекомендации по настройке

- Блокируйте только critical/high на старте, ужесточайте постепенно.
- SAST: используйте baseline и инкрементальные сканы.
- DAST: исключайте деструктивные маршруты, настраивайте профили аутентификации.
- Исключения храните в репозитории (`.sast-ignore`, `dast-exceptions.json`).

### См. также

- [Обзор методологии DevSecOps](./devsecops_overview.md)
- [Интеграция SAST/DAST в CI/CD](./sast_dast_cicd_integration.md)
- [Типичные уязвимости SAST и DAST](./sast_dast_vulnerabilities.md)
