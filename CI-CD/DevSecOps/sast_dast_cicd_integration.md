# Интеграция SAST и DAST в CI/CD

## Определения

Интеграция сканеров статического (**SAST**) и динамического (**DAST**) анализа в конвейер **CI/CD** — это фундамент методологии **DevSecOps**, обеспечивающий автоматизированный контроль безопасности на каждом этапе жизненного цикла разработки ПО.

В 2026 году парадигма интеграции сместилась в сторону **ASPM (Application Security Posture Management)** — систем, которые оркеструют работу всех инструментов анализа и управляют рисками на основе контекста выполнения.

Ключевые концепции 2026 года:
- **Shift Left 2.0:** перенос проверок безопасности непосредственно в IDE и ИИ-копилоты, что позволяет блокировать уязвимый код до его фиксации в репозитории.
- **Reachability-Driven Gates:** принятие решений о блокировке сборки на основе подтвержденной достижимости уязвимости в рантайме (через данные **IAST** или **eBPF**).
- **Auto-Remediation Pipelines:** автоматизированные циклы, в которых ИИ-агенты самостоятельно создают и валидируют Pull Requests с исправлениями для найденных дефектов.

## Базовые концепции

### Точки встраивания безопасности в конвейер (SDLC 2026)

| Этап конвейера | Тип проверки | Цель | Особенности 2026 |
| :--- | :--- | :--- | :--- |
| **IDE / Commit** | **AI-SAST / Lints** | Мгновенная обратная связь | Блокировка уязвимых паттернов в реальном времени. |
| **Pull Request** | **Incremental SAST / SCA** | Анализ диффа и Living SBOM | Проверка Reachability и авто-фикс от ИИ-агентов. |
| **Build** | **Container / SBOM Sign** | Аттестация артефактов | Подпись образов через Sigstore и фиксация VEX-статусов. |
| **Review / Staging** | **Autonomous DAST / IAST** | Глубокий пентест и eBPF | ИИ-агенты исследуют новые API и логические связи. |
| **Release Gate** | **ASPM Correlation** | Финальный риск-менеджмент | Корреляция находок из всех слоев (SAST + DAST + SCA). |
| **Runtime / Prod** | **eBPF Monitoring** | Обратная связь в пайплайн | Обнаружение новых путей исполнения для Reachability Analysis. |

### Расширенный инструментарий безопасности (2026)

Помимо классических SAST и DAST, современная интеграция включает следующие компоненты:

1.  **Сканирование секретов и NHI (Non-Human Identities):**
    - **Gitleaks / TruffleHog:** поиск закоммиченных токенов, API-ключей и паролей.
    - **Безопасность NHI:** аудит прав доступа ИИ-агентов и сервисных аккаунтов. Использование **OIDC (OpenID Connect)** для исключения хранения статических секретов в переменных CI.
2.  **Анализ состава ПО (Living SBOM):**
    - **Trivy / Snyk / Syft:** инвентаризация зависимостей.
    - **Living SBOM:** динамический граф компонентов в форматах **SPDX 3.0** или **CycloneDX 1.6**, обновляемый при каждом изменении кода. Подробнее: **[Анализ зависимостей и SBOM](../../Security/Supply_Chain_Security/dependency_and_sbom_analysis.md)**.
3.  **Сканирование инфраструктуры (IaC Scanning):**
    - **Checkov / KICS / Terrascan:** выявление небезопасных конфигураций в Terraform, Helm и Dockerfile (например, отсутствие Network Policies или запуск от root).
4.  **Рантайм-анализ и eBPF-фидбэк:**
    - **IAST:** подтверждение эксплуатируемости уязвимостей в работающем приложении.
    - **eBPF (Tetragon / Pixie):** мониторинг системных вызовов в реальном времени. Если рантайм-данные подтверждают вызов уязвимой функции, приоритет соответствующей находки в CI повышается до критического.
5.  **Оркестрация ASPM:**
    - **Cycode / Apiiro / DefectDojo:** платформы для централизованного сбора данных, удаления дубликатов и приоритизации рисков на основе бизнес-контекста.

### Политики и ворота качества (Quality Gates 2026)

- **Риск-ориентированные пороги:** блокировка сборки только при условии `Severity: High` + `Exploitable: Yes` + `Reachability: Confirmed`.
- **Vulnerability Baseline:** использование «базовой линии» для блокировки только новых уязвимостей, при этом старые (технический долг) управляются отдельно в ASPM.
- **VEX-аттестации (Vulnerability Exploitability eXchange):** использование машиночитаемых VEX-файлов для автоматического подавления алертов, если доказано, что уязвимость не влияет на безопасность продукта.
- **SARIF-стандарт:** использование формата **SARIF (Static Analysis Results Interchange Format)** для обеспечения интероперабельности между различными сканерами и платформами визуализации (GitHub/GitLab Security Dashboards).

## Практические сценарии

### Пример конфигурации в GitLab CI (2026)

Комплексный пример, включающий OIDC-аутентификацию, инкрементальный SAST и экспорт в SARIF.

```yaml
stages: [lint, test, security, deploy, dynamic_scan]

# 1. Поиск секретов с использованием OIDC (без статических токенов)
secrets_scan:
  stage: security
  image: zricethezav/gitleaks:latest
  id_tokens:
    SIGSTORE_ID_TOKEN:
      aud: sigstore
  script:
    - gitleaks detect --source . --verbose
  allow_failure: false

# 2. Инкрементальный SAST с экспортом в SARIF и поддержкой AI Auto-Fix
sast_scan:
  stage: security
  image: registry.example.com/tools/sast-ai:latest
  rules:
    - if: '$CI_MERGE_REQUEST_IID'
  script:
    # Анализ только измененного кода (diff)
    - sast-tool scan --changed-only --format sarif --out reports/sast.sarif
    # Инициация автоматического исправления через ИИ-агента
    - sast-tool remediate --input reports/sast.sarif --apply-fixes --create-branch
  artifacts:
    reports:
      sast: reports/sast.sarif

# 3. Автономный DAST на review-окружении
dast_scan:
  stage: dynamic_scan
  needs: ["deploy_review"]
  image: registry.example.com/tools/autonomous-dast:latest
  variables:
    TARGET_URL: $CI_ENVIRONMENT_URL
  script:
    # ИИ-агент самостоятельно исследует новые эндпоинты API
    - pentest-agent scan --target $TARGET_URL --mode autonomous --report reports/dast.json
  artifacts:
    reports:
      dast: reports/dast.json
```

### Пример Jenkins Pipeline (Declarative)

> Примечание: данный пример приведён в синтаксисе Jenkins Declarative Pipeline. Общее сравнение декларативного и скриптового подходов к построению пайплайнов см. в **[Глоссарии пайплайнов](../Core_Concepts/pipeline_glossary.md#декларативный-pipeline)**.

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
        // Использование SARIF для бесшовной интеграции с ASPM-платформой
        sh 'sast-tool scan --format sarif -o reports/sast.sarif'
      }
    }
    stage('Security: SCA') {
      steps {
        // Генерация Living SBOM и проверка зависимостей
        sh 'trivy fs --format cyclonedx --output sbom.json .'
        sh 'trivy sbom sbom.json --severity HIGH,CRITICAL --exit-code 1'
      }
    }
    stage('Deploy Review') {
      steps { 
        sh './scripts/deploy_review.sh' 
      }
    }
    stage('Security: DAST') {
      steps {
        // Запуск автономного сканера для динамического анализа API
        sh 'dast-tool scan "$REVIEW_URL" --profile autonomous -o reports/dast.json'
      }
    }
  }
  post {
    always { 
      archiveArtifacts artifacts: 'reports/*', allowEmptyArchive: true
      // Синхронизация результатов с центральной ASPM-системой (например, DefectDojo)
      sh './scripts/upload_to_aspm.sh reports/'
    }
  }
}
```

## Дополнительная информация

### Оптимизация производительности пайплайна (2026)

- **Incremental Analysis:** сканирование только диффа изменений для SAST и SCA. Современные сканеры сохраняют контекст всего приложения в графе, анализируя только затронутые узлы.
- **Reachability Feedback Loop:** интеграция с **eBPF**-мониторингом в продакшене. Если мониторинг показывает, что уязвимый код в библиотеке никогда не вызывается, ASPM может автоматически снизить приоритет уязвимости в CI или выдать VEX-исключение.
- **Parallel & Fail-Fast:** запуск быстрых легковесных проверок (Secrets, IaC Lint) параллельно на ранних стадиях; тяжелые сканы (Full DAST) выносятся во внеочередные или асинхронные пайплайны.
- **OIDC-аутентификация:** ускоряет запуск заданий и повышает безопасность за счет отсутствия необходимости ручного обновления статических секретов.

### Культура взаимодействия (Security Culture 2.0)

- **AI-Guided Remediation:** разработчики получают не просто отчет об ошибке, а проверенный ИИ-агентом патч, готовый к применению. Это снижает «сопротивление» внедрению инструментов безопасности.
- **Risk Visibility:** использование единого Dashbord (ASPM), где виден реальный риск для бизнеса, а не абстрактное количество алертов.
- **Security-as-Code:** все конфигурации сканеров, политики и пороги качества хранятся в Git и проходят через процесс Code Review вместе с кодом приложения.

## См. также

- **[Типичные уязвимости SAST и DAST](./sast_dast_vulnerabilities.md)**
- **[Сравнение подходов SAST vs DAST](./sast_vs_dast.md)**
- **[Анализ зависимостей и SBOM](../../Security/Supply_Chain_Security/dependency_and_sbom_analysis.md)**
- **[Интеграция автоматизированных тестов в CI/CD](../../Testing/testing_cicd_integration.md)**
- **[DevSecOps — обзор методологии](./devsecops_overview.md)**
