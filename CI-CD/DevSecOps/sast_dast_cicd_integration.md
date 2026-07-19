# Интеграция SAST и DAST в CI/CD

## Определения

Интеграция сканеров статического (**SAST — Static Application Security Testing — статическое тестирование безопасности приложений**) и динамического (**DAST — Dynamic Application Security Testing — динамическое тестирование безопасности приложений**) анализа в конвейер **CI/CD (Continuous Integration / Continuous Deployment — непрерывная интеграция и непрерывное развертывание)** является ключевой практикой методологии **DevSecOps**.

Цель интеграции — получение быстрого и воспроизводимого сигнала о рисках безопасности до релиза, реализация стратегии **Shift Left** (сдвиг безопасности «влево», на ранние этапы разработки) и предотвращение попадания уязвимостей в промышленную среду.

## Базовые концепции

### Точки встраивания безопасности в конвейер

Современный **DevSecOps** пайплайн включает многоуровневую проверку на различных этапах жизненного цикла разработки.

| Этап конвейера | Тип проверки | Цель | Особенности |
| :--- | :--- | :--- | :--- |
| **Commit / Push** | **Secrets Detection** | Поиск секретов в коде | Быстрый скан коммита на наличие ключей, паролей. |
| **Pull / Merge Request**| **SAST** / **IaC Scan** | Анализ изменённого кода | Инкрементальный анализ (diff), проверка Dockerfile/Terraform. |
| **После сборки** | **SCA** / **Container Scan**| Скан зависимостей и образов | Проверка сторонних библиотек (CVE) и слоев образа. |
| **Review-окружение** | **DAST** | Тестирование приложения | Имитация атак на живое приложение (Black Box). |
| **Ночной регресс** | **Deep SAST/DAST** | Глубокое сканирование | Полные профили анализа, долгие тесты. |
| **Перед релизом** | **Compliance Check** | Финальный контроль | Проверка политик (Release Gates), подпись артефактов. |

### Расширенный инструментарий безопасности

Помимо SAST и DAST, интеграция включает следующие типы инструментов:

1. **Сканирование секретов (Secrets Scanning):**
   - **Gitleaks / TruffleHog:** Поиск случайно закоммиченных токенов, ключей **API (Application Programming Interface — программный интерфейс приложения)** и паролей. Должен запускаться максимально рано.
2. **Анализ состава ПО (SCA — Software Composition Analysis):**
   - **Trivy / Snyk:** Обнаружение уязвимостей в сторонних библиотеках и создание **SBOM (Software Bill of Materials — состав ПО)**. Подробнее: **[анализ зависимостей и SBOM](../../Security/Supply_Chain_Security/dependency_and_sbom_analysis.md)**.
3. **Сканирование инфраструктуры как кода (IaC Scanning):**
   - **Checkov / tfsec:** Поиск небезопасных конфигураций в Terraform, Kubernetes-манифестах и Helm-чартах (например, привилегированные контейнеры, открытые S3-бакеты).
4. **Интерактивный анализ (IAST — Interactive AST):**
   - Гибридный метод, использующий агентов внутри приложения для подтверждения уязвимостей в реальном времени. См. **[сравнение подходов SAST vs DAST](./sast_vs_dast.md)**.
5. **Оркестрация и агрегация (ASOC — Application Security Orchestration and Correlation):**
   - **DefectDojo:** Централизованная платформа для сбора отчетов от всех сканеров, дедупликации уязвимостей и управления процессом исправления (Triage).

### Политики и пороги качества (Quality Gates)

- **Порог критичности (Severity Threshold):** Автоматическая остановка пайплайна при обнаружении уязвимостей уровня `High` или `Critical`.
- **Фиксация базы (Vulnerability Baseline):** Блокировка только новых уязвимостей. Старые находки фиксируются как технический долг и обрабатываются отдельно.
- **Управление исключениями:** Механизм подавления ложноположительных срабатываний (**False Positives**) через файлы конфигурации (например, `.sast-ignore`, `.trivyignore`), хранящиеся в репозитории.

## Практические сценарии

### Пример конфигурации в GitLab CI

Комплексный пример, включающий проверку секретов, SAST и DAST.

```yaml
stages: [lint, test, security, deploy, dynamic_scan]

# 1. Поиск секретов (запускается всегда)
secrets_scan:
  stage: security
  image: 
    name: zricethezav/gitleaks:latest
    entrypoint: [""]
  script:
    - gitleaks detect --source . --verbose --redact
  allow_failure: false # Блокируем пайплайн при наличии секретов

# 2. Статический анализ (SAST)
sast_scan:
  stage: security
  image: registry.example.com/tools/sast:latest
  rules:
    - if: '$CI_MERGE_REQUEST_IID'
  script:
    - sast-tool scan --changed-only --format sarif --out reports/sast.sarif
    - sast-tool gate --min-severity=high --input reports/sast.sarif
  artifacts:
    when: always
    paths: [reports/sast.sarif]

# 3. Динамический анализ (DAST) на временной среде
dast_scan:
  stage: dynamic_scan
  needs: ["deploy_review"]
  image: registry.example.com/tools/dast:stable
  variables:
    TARGET_URL: $REVIEW_URL
  script:
    - dast-tool auth --user test --password $TEST_PASS
    - dast-tool scan $TARGET_URL --profile quick --report reports/dast.json
    - dast-tool gate --min-severity=medium --input reports/dast.json
  artifacts:
    when: always
    paths: [reports/dast.json]
```

### Пример Jenkins Pipeline (Declarative)

```groovy
pipeline {
  agent any
  stages {
    stage('Security: Secrets') {
      steps {
        sh 'gitleaks detect --source . -v'
      }
    }
    stage('Security: SAST') {
      steps {
        sh 'sast-tool scan --format sarif -o reports/sast.sarif'
      }
    }
    stage('Security: SCA') {
      steps {
        sh 'trivy fs --severity HIGH,CRITICAL --exit-code 1 .'
      }
    }
    stage('Deploy Review') {
      steps { 
        sh './scripts/deploy_review.sh' 
      }
    }
    stage('Security: DAST') {
      steps {
        sh 'dast-tool scan "$REVIEW_URL" --profile quick -o reports/dast.json'
      }
    }
  }
  post {
    always { 
      archiveArtifacts artifacts: 'reports/*', allowEmptyArchive: true
    }
  }
}
```

## Дополнительная информация

### Оптимизация производительности пайплайна

- **Инкрементальные проверки:** Сканирование только измененных файлов (diff) для SAST и линтеров.
- **Параллельное выполнение:** Запуск SAST, SCA и линтеров в параллельных задачах.
- **Кэширование баз данных уязвимостей:** Кэширование папок сканеров (например, `.trivy/cache`) для ускорения SCA.
- **Fail Fast:** Запуск самых быстрых проверок (Secrets, Lints) в начале пайплайна.

### Культура взаимодействия (Security Culture)

- **Прозрачность:** Отчеты должны быть доступны разработчикам в привычном интерфейсе (GitLab Security Dashboard, PR comments).
- **Обучение:** Использование результатов сканирования как учебного материала (пояснения к уязвимостям и способы их исправления).
- **Разделение ответственности:** Разработчики исправляют код, ИБ-команда настраивает политики и управляет исключениями.

### См. также

- **[Типичные уязвимости SAST и DAST](./sast_dast_vulnerabilities.md)**
- **[Сравнение подходов SAST vs DAST](./sast_vs_dast.md)**
- **[Анализ зависимостей и SBOM](../../Security/Supply_Chain_Security/dependency_and_sbom_analysis.md)**
- **[Интеграция тестов в CI/CD](../../Testing/testing_cicd_integration.md)** — общие принципы Quality Gates.
