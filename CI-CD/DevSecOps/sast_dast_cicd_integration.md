# Интеграция SAST и DAST в CI/CD

**Reliability Score: 10** (SSoT + Web Verification 2026: актуализировано на основе стандартов ASPM оркестрации, AI-driven Remediation и eBPF-мониторинга)

## Определения

Интеграция сканеров статического (**SAST**) и динамического (**DAST**) анализа в конвейер **CI/CD** — это фундамент методологии **DevSecOps**, обеспечивающий автоматизированный контроль безопасности на каждом этапе поставки ПО.

В 2026 году парадигма интеграции сместилась в сторону **ASPM (Application Security Posture Management)** — системы, которая не просто собирает отчеты, а оркеструет работу всех инструментов и управляет рисками на основе контекста выполнения.

Ключевые концепции 2026 года:
- **Shift Left 2.0:** Интеграция безопасности непосредственно в IDE и AI-копилоты, блокирующая уязвимый код до его попадания в репозиторий.
- **Reachability-Driven Gates:** Принятие решений о блокировке сборки на основе достижимости уязвимости в рантайме (через данные eBPF/IAST).
- **Auto-Remediation Pipelines:** Автоматические рабочие циклы, в которых ИИ-агенты создают и валидируют исправления для найденных уязвимостей.

## Базовые концепции

### Точки встраивания безопасности в конвейер (SDLC 2026)

| Этап конвейера | Тип проверки | Цель | Особенности 2026 |
| :--- | :--- | :--- | :--- |
| **IDE / Commit** | **AI-SAST / Lints** | Мгновенная обратная связь | Блокировка уязвимых паттернов «на лету». |
| **Pull Request** | **Incremental SAST / SCA** | Анализ диффа и Living SBOM | Проверка Reachability и авто-фикс от ИИ. |
| **Build** | **Container / SBOM Sign** | Аттестация артефактов | Подпись образов через Sigstore и фиксация VEX. |
| **Review / Staging** | **Autonomous DAST / IAST** | Глубокий пентест и eBPF | Автономные ИИ-агенты исследуют новые API. |
| **Release Gate** | **ASPM Correlation** | Финальный риск-менеджмент | Сопоставление находок из всех слоев анализа. |
| **Runtime / Prod** | **eBPF Monitoring** | Feedback в пайплайн | Обнаружение новых путей исполнения (Reachability). |

### Расширенный инструментарий безопасности (2026)

Помимо SAST и DAST, современная интеграция включает следующие типы инструментов и протоколов:

1. **Сканирование секретов и нечеловеческих сущностей (Secrets & NHI):**
   - **Gitleaks / TruffleHog:** Поиск закоммиченных токенов, ключей **API** и паролей. 
   - **В 2026 году:** Фокус на **NHI (Non-Human Identities)** — аудит прав доступа ИИ-агентов и автоматическая ротация ключей через **OIDC (OpenID Connect)** для исключения хранения статических секретов в переменных CI.
2. **Анализ состава ПО (Living SBOM):**
   - **Trivy / Snyk / Syft:** Обнаружение уязвимостей в библиотеках.
   - **В 2026 году:** Переход к концепции **Living SBOM** — динамическому графу зависимостей в форматах **SPDX 3.0** или **CycloneDX 1.6**, который обновляется в реальном времени при каждом изменении кода. Подробнее: **[анализ зависимостей и SBOM](../../Security/Supply_Chain_Security/dependency_and_sbom_analysis.md)**.
3. **Сканирование инфраструктуры (IaC Scanning):**
   - **Checkov / tfsec / KICS:** Поиск небезопасных конфигураций в Terraform, Helm и K8s (например, запуск от root, отсутствие сетевых политик).
4. **Интерактивный и рантайм анализ (IAST & eBPF):**
   - **IAST:** Гибридный метод для подтверждения уязвимостей.
   - **В 2026 году:** Широкое использование **eBPF (Tetragon / Falco)** для обратной связи в пайплайн. Если рантайм-мониторинг показывает, что уязвимая функция в библиотеке реально вызывается, критичность в CI повышается.
5. **Оркестрация (ASPM — Application Security Posture Management):**
   - **Apiiro / Cycode / DefectDojo:** В 2026 году платформы ASOC эволюционировали в **ASPM**. Они коррелируют данные SAST, DAST и SCA, отсеивая до 90% шума за счет анализа достижимости (**Reachability Analysis**).

### Политики и пороги качества (Quality Gates 2026)

- **Риск-ориентированные пороги:** Блокировка пайплайна при условии `Severity: High` + `Exploitable: Yes` + `Reachability: Confirmed`.
- **Фиксация базы (Vulnerability Baseline):** Блокировка только новых уязвимостей (технический долг фиксируется в ASPM).
- **VEX-аттестации (Vulnerability Exploitability eXchange):** Использование файлов VEX для автоматического подавления алертов, если доказано, что уязвимость не эксплуатируема в текущем контексте.
- **Управление исключениями:** Использование файлов `.sast-ignore`, `.trivyignore` или централизованных политик в ASPM-платформе.

## Практические сценарии

### Пример конфигурации в GitLab CI (2026)

Комплексный пример, включающий OIDC-аутентификацию, инкрементальный SAST и автономный DAST.

```yaml
stages: [lint, test, security, deploy, dynamic_scan]

# 1. Поиск секретов с использованием OIDC (без статических токенов)
secrets_scan:
  stage: security
  image: zricethezav/gitleaks:latest
  id_tokens:
    SIGSTORE_ID_TOKEN: # OIDC для подписи результатов
      aud: sigstore
  script:
    - gitleaks detect --source . --verbose
  allow_failure: false

# 2. Инкрементальный SAST с поддержкой AI Auto-Fix
sast_scan:
  stage: security
  image: registry.example.com/tools/sast-ai:latest
  rules:
    - if: '$CI_MERGE_REQUEST_IID'
  script:
    # Анализ только измененного кода (diff)
    - sast-tool scan --changed-only --format sarif --out reports/sast.sarif
    # Автоматическое создание PR с исправлением (если включено в ASPM)
    - sast-tool remediate --input reports/sast.sarif --apply-fixes
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
    # ИИ-агент самостоятельно исследует новые эндпоинты
    - pentest-agent scan --target $TARGET_URL --mode autonomous --report reports/dast.json
  artifacts:
    reports:
      dast: reports/dast.json
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
        // Использование SARIF для интеграции с ASPM
        sh 'sast-tool scan --format sarif -o reports/sast.sarif'
      }
    }
    stage('Security: SCA') {
      steps {
        // Генерация SBOM и проверка уязвимостей
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
        sh 'dast-tool scan "$REVIEW_URL" --profile autonomous -o reports/dast.json'
      }
    }
  }
  post {
    always { 
      archiveArtifacts artifacts: 'reports/*', allowEmptyArchive: true
      // Отправка результатов в ASPM (например, DefectDojo)
      sh './scripts/upload_to_aspm.sh reports/'
    }
  }
}
```

## Дополнительная информация

### Оптимизация производительности пайплайна (2026)

- **Incremental Analysis:** Сканирование только измененных файлов (diff) для SAST и SCA. Современные ИИ-сканеры анализируют дифференциал, сохраняя контекст всего приложения.
- **Reachability Feedback:** Если eBPF-мониторинг в проде показывает, что код не вызывается, ASPM может автоматически снизить приоритет или отключить блокирующую проверку для этой уязвимости в CI.
- **Parallel & Fail-Fast:** Запуск быстрых проверок (Secrets, Lints) в начале; тяжелые сканы (Full DAST) выносятся в асинхронные пайплайны.
- **OIDC-аутентификация:** Ускоряет запуск джоб за счет отсутствия необходимости ручного проброса и обновления переменных с секретами.

### Культура взаимодействия (Security Culture 2.0)

- **AI-Guided Remediation:** Разработчики получают не просто список ошибок, а готовые патчи, проверенные на безопасность. Это снижает сопротивление внедрению инструментов.
- **ASPM Visibility:** Единый Dashboard для ИБ и Dev-команд, где виден реальный риск, а не просто количество алертов.
- **Security-as-Code:** Все политики и пороги качества хранятся в Git и проходят через процесс рецензирования (Code Review).

## См. также

- **[Типичные уязвимости SAST и DAST](./sast_dast_vulnerabilities.md)**
- **[Сравнение подходов SAST vs DAST](./sast_vs_dast.md)**
- **[Анализ зависимостей и SBOM](../../Security/Supply_Chain_Security/dependency_and_sbom_analysis.md)**
- **[Интеграция тестов в CI/CD](../../Testing/testing_cicd_integration.md)**
- **[Обзор DevSecOps](./devsecops_overview.md)**
