# SAST vs DAST — сравнение подходов

## Определения

Для обеспечения безопасности приложений (Application Security Testing — AST) используются три основных подхода и анализ зависимостей:

- **SAST (Static Application Security Testing)** — «белый ящик»: анализ исходного кода, байт-кода или бинарных файлов без запуска приложения.
- **DAST (Dynamic Application Security Testing)** — «черный ящик»: тестирование работающего приложения через его внешние интерфейсы (HTTP/API).
- **IAST (Interactive Application Security Testing)** — «серый ящик»: гибридный подход, использующий агентов внутри работающего приложения для анализа кода и потоков данных в реальном времени.
- **SCA (Software Composition Analysis)** — анализ сторонних библиотек и зависимостей на наличие известных уязвимостей (CVE). См. [Анализ зависимостей и SBOM](../../Security/Supply_Chain_Security/dependency_and_sbom_analysis.md).

## Базовые концепции

### Сравнение методов анализа

| Критерий | SAST | DAST | IAST |
| :--- | :--- | :--- | :--- |
| **Принцип** | Белый ящик (статический) | Черный ящик (динамический) | Серый ящик (гибридный) |
| **Этап CI/CD** | Кодирование, сборка | Тест, стейджинг | Тестирование (QA/автотесты) |
| **Контекст** | Исходный код | Работающее приложение | Код + Рантайм |
| **Точность** | Высокий уровень шума (FP) | Редкие FP (подтверждено) | Высочайшая (видит данные в коде) |
| **Покрытие** | 100% исходного кода | Только активные маршруты | Только пройденные тестами пути |
| **Требования** | Доступ к коду | Развернутая среда | Агент в рантайме |
| **Цель** | Найти ошибки в коде | Найти ошибки в рантайме/конфиге | Найти эксплуатируемые дефекты |

### Типы обнаруживаемых уязвимостей

Каждый метод тестирования специализируется на определенных классах дефектов:

- **SAST:** специализируется на ошибках в коде, логике авторизации и конфигурациях (IaC).
- **DAST:** выявляет уязвимости рантайма, конфигурации серверов и сетевые угрозы.
- **IAST:** фокусируется на эксплуатируемых дефектах в реальных потоках данных.
- **SCA:** нацелен на уязвимости в сторонних компонентах.

Подробное сопоставление и полный перечень уязвимостей — в **[обзоре уязвимостей SAST/DAST](./sast_dast_vulnerabilities.md)**.

### Ограничения

- **SAST:** зависит от качества правил; пропускает уязвимости из динамически генерируемого кода; требует настройки для снижения шума.
- **DAST:** чувствителен к качеству тестовой среды; не покрывает скрытые или не задокументированные эндпоинты; может создавать деструктивную нагрузку на окружение.
- **IAST:** требует поддержки конкретного языка программирования; может замедлять работу приложения; требует наличия функциональных тестов для обеспечения покрытия.

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
- **Корреляция:** использование ASOC-платформ (Application Security Orchestration and Correlation), таких как DefectDojo или AppSec Phoenix, для объединения результатов SAST, DAST и SCA в единую очередь на исправление.

### Рекомендации по настройке

- Блокируйте только critical/high на старте, ужесточайте постепенно.
- SAST: используйте baseline и инкрементальные сканы.
- DAST: исключайте деструктивные маршруты, настраивайте профили аутентификации.
- Исключения храните в репозитории (`.sast-ignore`, `dast-exceptions.json`).

## См. также

- [Анализ зависимостей и SBOM](../../Security/Supply_Chain_Security/dependency_and_sbom_analysis.md)
- [Интеграция SAST/DAST в CI/CD](./sast_dast_cicd_integration.md)
- [Типичные уязвимости SAST и DAST](./sast_dast_vulnerabilities.md)
