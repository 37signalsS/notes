# SAST vs DAST: сравнение подходов

## Definitions

**SAST (Static Application Security Testing)** и **DAST (Dynamic Application Security Testing)** — взаимодополняющие подходы к тестированию безопасности приложений.

- **SAST** — «белый ящик»: анализ исходного/байт-кода до запуска приложения.
- **DAST** — «черный ящик»: тестирование работающего приложения через внешние интерфейсы.

Детальные обзоры: [SAST](./sast_overview.md), [DAST](./dast_overview.md).

## Basic Concepts

### Сравнение по ключевым критериям

| Критерий | SAST | DAST |
| :--- | :--- | :--- |
| **Этап** | Коммит/PR, сборка | Тест/стейджинг после деплоя |
| **Контекст** | Статический анализ кода | Рантайм, реальная конфигурация |
| **Скорость** | Быстро (инкрементально), долго (полный скан) | Средне/долго (зависит от сложности) |
| **False positives** | Часты без настройки | Реже (зависят от среды/аутентификации) |
| **Покрытие** | 100% кода (включая неиспользуемый) | Только доступные маршруты |
| **Требования** | Исходный код, правила | Развернутая среда, тестовые креды |
| **Цель** | Найти дефекты до выполнения | Подтвердить эксплуатацию |

### Типы обнаруживаемых уязвимостей

- **SAST:** инъекции (SQL, Command, LDAP), небезопасная десериализация, ошибки логики авторизации, слабые криптоалгоритмы, секреты в коде.
- **DAST:** XSS, ошибки заголовков (HSTS, CSP), уязвимости сессий, CSRF, SSRF, открытые редиректы.

Полное сопоставление — в [обзоре уязвимостей SAST/DAST](./sast_dast_vulnerabilities.md).

### Ограничения

- **SAST:** зависит от качества правил; пропускает уязвимости из генерации кода; требует настройки для снижения шума.
- **DAST:** чувствителен к качеству среды; не покрывает скрытые эндпоинты; может создавать нагрузку на тестовое окружение.

## Practical Scenarios

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

## Additional Information

### Комбинированная стратегия

- **Shift Left:** SAST в IDE + pre-commit хуки для ранней обратной связи.
- **Shift Right:** DAST в ночных сборках с полной аутентификацией.
- **Корреляция:** связывание отчётов SAST/DAST для приоритизации эксплуатируемых уязвимостей.

### Рекомендации по настройке

- Блокируйте только critical/high на старте, ужесточайте постепенно.
- SAST: используйте baseline и инкрементальные сканы.
- DAST: исключайте деструктивные маршруты, настраивайте профили аутентификации.
- Исключения храните в репозитории (`.sast-ignore`, `dast-exceptions.json`).

Методология DevSecOps — в [обзоре DevSecOps](./devsecops_overview.md).
