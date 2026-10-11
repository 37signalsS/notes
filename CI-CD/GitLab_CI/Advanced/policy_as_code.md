# Policy-as-Code в GitLab CI/CD

**Актуально для:** GitLab 17.x–19.x

## Определения

**Policy-as-Code (PaC)** — подход к управлению политиками через код (файлы политик в репозитории), который обеспечивает автоматическую проверку, аудит и применение правил на всех этапах CI/CD.

**OPA (Open Policy Agent)** — универсальный движок политик, использующий язык Rego для определения правил. Применяется для проверки конфигураций Kubernetes, Terraform, Dockerfile и других структурированных файлов.

**Conftest** — CLI-инструмент для тестирования конфигураций с помощью OPA-политик. Поддерживает Kubernetes, Terraform, Dockerfile, JSON, YAML.

**Checkov** — статический анализатор IaC от Bridgecrew (Palo Alto). Поддерживает Terraform, Kubernetes, Dockerfile, Helm, Kustomize, OpenTofu. Имеет встроенные политики (checks) и поддержку кастомных политик.

**TFLint** — линтер для Terraform. Проверяет корректность HCL-синтаксиса, типы ресурсов, best practices.

**Trivy** — универсальный сканер безопасности от Aqua Security. Включает модуль misconfiguration scanning, наследующий функциональность tfsec (архивирован в 2025). Поддерживает Terraform, Kubernetes, Dockerfile, Helm.

> **Примечание:** tfsec официально архивирован в ноябре 2025 года, функциональность передана в Trivy. Для новых проектов используйте Trivy.

**Security Policy** — политики безопасности на уровне GitLab (Group/Project Security Policies). Включают в себя rules для SAST, DAST, Dependency Scanning, Container Scanning.

## Предварительные требования

- GitLab 17.0+ (Premium/Ultimate для встроенных Security Policies и Dependency Scanning)
- GitLab Runner с поддержкой Docker, Kubernetes или Shell executor
- Доступ к репозиторию с IaC-файлами (Terraform, Kubernetes-манифесты, Dockerfile)
- Инструменты CLI: conftest, checkov, tflint, trivy (опционально — в контейнерах GitLab CI)
- Настроенные секреты CI/CD: `GITLAB_TOKEN` или `GITLAB_API_TOKEN` для интеграции с Merge Request API
- Для конфиденциальных сред: air-gapped Runner'ы с предварительно загруженными образами и кэшем плагинов

## Основные концепции

### Архитектура Policy-as-Code в GitLab CI/CD

```
Push → Pipeline
  ├── Lint/Validate stage
  │   ├── TFLint (Terraform lint)
  │   ├── Checkov (IaC scan)
  │   ├── Conftest (OPA policies)
  │   └── Trivy config (Kubernetes/Dockerfile/Terraform scan)
  ├── Security stage
  │   ├── GitLab SAST
  │   ├── GitLab DAST
  │   ├── Dependency Scanning
  │   └── Container Scanning
  └── Deploy gate
      └── Manual approval / Security Policy enforcement
```

### Сравнение инструментов Policy-as-Code

| Инструмент | Язык политик | Форматы | Стоимость | Интеграция с GitLab |
| :--- | :--- | :--- | :--- | :--- |
| **OPA + Conftest** | Rego | Terraform, K8s, Docker, JSON, YAML | Open Source | Да (через CI job) |
| **Checkov** | Python/YAML | Terraform, K8s, Helm, Dockerfile, OpenTofu | Open Source + Enterprise | Да (через CI job) |
| **TFLint** | HCL | Terraform | Open Source | Да (через CI job) |
| **Trivy** | YAML/JSON | Terraform, K8s, Dockerfile, Helm | Open Source | Да (через CI job) |
| **GitLab Security Policies** | YAML | Встроенные templates | Встроено (Premium/Ultimate) | Да (native) |

### Где применять Policy-as-Code

| Этап | Инструменты | Что проверять |
| :--- | :--- | :--- |
| **Pre-commit** | pre-commit, checkov, tflint | Синтаксис, базовые политики |
| **CI lint** | Conftest, Checkov, TFLint, Trivy | Полный набор политик, compliance |
| **Security scan** | GitLab SAST/DAST, Trivy | Уязвимости, secrets, misconfigurations |
| **Deploy gate** | GitLab Security Policies, manual approval | Enforcement, compliance sign-off |

## Практические сценарии

### Сценарий 1: OPA + Conftest для Terraform

**Предварительные требования:** Terraform 1.x+, Git-репозиторий с `.tf`-файлами.

**Установка:**
```bash
# Установка Conftest (v0.69.0 на момент написания)
brew install conftest  # macOS/Linuxbrew
# Или статический бинарник
curl -L https://github.com/open-policy-agent/conftest/releases/download/v0.69.0/conftest_0.69.0_Linux_x86_64.tar.gz | tar xz
```

**Политика (`policy/terraform/general.rego`):**
```rego
package terraform.general

# Требование наличия тегов у всех ресурсов
deny[msg] {
  resource := input.resource_changes[_]
  not resource.change.after.tags
  msg := sprintf("Resource '%s' must have tags defined", [resource.name])
}

# Требование presence тега environment
deny[msg] {
  resource := input.resource_changes[_]
  tags := resource.change.after.tags
  not tags.environment
  msg := sprintf("Resource '%s' must have 'environment' tag", [resource.name])
}
```

**Валидация (локально):**
```bash
terraform init -backend=false
terraform plan -out=tfplan
terraform show -json tfplan > tfplan.json
conftest test tfplan.json --policy policy/terraform/
# → result: FAIL - Resource 'aws_instance.web' must have 'environment' tag
```

**Интеграция в GitLab CI:**
```yaml
stages:
  - validate
  - plan
  - apply

terraform_validate:
  stage: validate
  image: openpolicyagent/conftest:0.69.0
  script:
    - terraform init -backend=false
    - terraform plan -out=tfplan
    - terraform show -json tfplan > tfplan.json
    - conftest test tfplan.json --policy policy/terraform/
  only:
    - merge_requests
    - main
```

### Сценарий 2: Checkov для Kubernetes-манифестов

**Политика (`policy/kubernetes/ensure_pod_has_network_policy.yaml`):**
```yaml
# Checkov custom policy
name: "Ensure all pods have a NetworkPolicy"
metadata:
  category: "network"
  severity: "HIGH"
  id: "CKV_K8S_99"
  version: "1.0"
definition:
  resource_types:
    - "Pod"
  condition: AND
  - "or"
    - "has_network_policy"
    - "is_namespace_ignored"
  - "not"
    - "is_system_pod"
```

**Валидация (локально):**
```bash
checkov -d kubernetes/ --policy-path policy/kubernetes/ --output sarif --quiet
# → result: PASSed for 3 checks, FAILed for 1 check
```

**Интеграция в GitLab CI:**
```yaml
stages:
  - validate

checkov_scan:
  stage: validate
  image: bridgecrew/checkov:3.3.18
  script:
    - checkov -d kubernetes/ --policy-path policy/kubernetes/ --output sarif --quiet
  artifacts:
    reports:
      sarif: checkov-report.sarif
  only:
    - merge_requests
    - main
```

### Сценарий 3: TFLint для Terraform

**Конфигурация плагинов (`.tflint.hcl`):**
```hcl
plugin "terraform" {
  enabled = true
  version = "0.19.0"
  source  = "github.com/terraform-linters/tflint-ruleset-terraform"
}

plugin "gitlab" {
  enabled = true
  version = "0.2.0"
  source  = "github.com/terraform-linters/tflint-ruleset-gitlab"
}
```

**Валидация (локально):**
```bash
tflint --init
tflint -f compact
# → result: 1 issue found:
#   1 error, 0 warnings, 0 notices
```

**Интеграция в GitLab CI:**
```yaml
stages:
  - validate

tflint:
  stage: validate
  image: ghcr.io/terraform-linters/tflint:0.64.0
  script:
    - tflint --init
    - tflint -f compact
  only:
    - merge_requests
    - main
```

### Сценарий 4: Trivy для безопасности Terraform и Kubernetes

**Предварительные требования:** Trivy v0.71.0+ (исправляет CVE-2026-54448 — DoS при обработке Helm-архивов).

**Валидация (локально):**
```bash
trivy config --severity HIGH,CRITICAL terraform/ kubernetes/
# → result: Total: 2 (HIGH: 1, CRITICAL: 1)
```

**Интеграция в GitLab CI:**
```yaml
stages:
  - security

trivy_config_scan:
  stage: security
  image: aquasec/trivy:0.74.0
  script:
    - |
      trivy config \
        --severity HIGH,CRITICAL \
        --format sarif \
        --output trivy-report.sarif \
        terraform/ kubernetes/
  artifacts:
    reports:
      sarif: trivy-report.sarif
    paths:
      - trivy-report.sarif
  allow_failure: true
  only:
    - merge_requests
    - main
```

### Сценарий 5: GitLab Security Policies (Premium/Ultimate)

**Включение Security Policies:**
1. Перейдите в `Settings → Security → Security Policies`
2. Включите `Security Policy` для проекта/группы
3. Настройте правила для SAST, DAST, Dependency Scanning, Container Scanning

```yaml
# .gitlab/security-policies.yml
policies:
  - name: "Block merge if critical vulnerabilities found"
    rules:
      - type: "vulnerability"
        severity: "critical"
        action: "block_merge"
  - name: "Require SAST to pass"
    rules:
      - type: "sast"
        action: "require_pass"
  - name: "Require Container Scanning to pass"
    rules:
      - type: "container_scanning"
        action: "require_pass"
```

## Устранение неполадок

| Проблема | Возможная причина | Решение |
| :--- | :--- | :--- |
| Conftest падает на валидном плане | Устаревшая политика или несовместимый формат плана | Обновите политики под актуальную версию Terraform; проверьте, что `terraform show -json` возвращает валидный JSON |
| Checkov false positive | Устаревшее правило или кастомный policy с ошибкой | Обновите Checkov; используйте `--skip-check` для известных false positives |
| TFLint не находит плагины | Плагин не инициализирован или несовместимая версия | Выполните `tflint --init`; проверьте версию плагина в `.tflint.hcl` |
| Trivy не находит уязвимости в Terraform | Провайдер не поддерживается или файл исключен | Проверьте, что Terraform >= 0.12 и используются стандартные провайдеры |
| GitLab Security Policy не блокирует MR | Политика не опубликована или действие требует Ultimate | Убедитесь, что политика опубликована (`publish: true`) и инстанс имеет лицензию Ultimate |
| Пайплайн зависает на `conftest test` | Большой план Terraform или memory limit в Runner | Увеличьте `memory` в `.gitlab-ci.yml` или используйте `--parse-dynamic` |
| Trivy OOM при сканировании больших Helm-чартов | CVE-2026-54448 в версиях < 0.71.0 | Обновите Trivy до >= 0.71.0 |
| tfsec не обновляется | Проект архивирован | Мигрируйте на Trivy; см. [руководство по миграции](https://aquasecurity.github.io/tfsec/v1/guides/migration/) |

## Best Practices

### Разработка (Dev)

1. **Начинайте с pre-commit hooks:** Линтинг и базовые проверки до коммита экономят время.
2. **Пишите политики на Rego для OPA:** Универсальный формат, работает с любым IaC.
3. **Используйте Checkov для быстрого старта:** Встроенные checks покрывают 80% common issues.
4. **Интегрируйте проверки в MR:** Все проверки должны запускаться на merge requests, а не только в main.
5. **Не блокируйте merge на warnings:** Используйте `allow_failure: true` для non-critical checks.

### Эксплуатация (DevOps/SRE)

1. **Централизуйте политики:** Храните политики в отдельном репозитории, импортируйте в проекты.
2. **Версионируйте политики:** Каждое изменение политики — отдельный MR с review.
3. **Мониторьте compliance:** Регулярно проверяйте, сколько ресурсов нарушают политики.
4. **Используйте GitLab Security Policies:** Для enforcement на уровне группы (Premium/Ultimate).
5. **Интегрируйте с alerting:** При нарушении критичной политики — алерт в Slack/PagerDuty.
6. **Кэшируйте плагины TFLint и зависимости:** Указывайте кэш в `.gitlab-ci.yml`, чтобы `tflint --init` не качал плагины на каждый джоб.

### Sysadmin

1. **Настройте centralized policy engine:** OPA Server или Gatekeeper для admission control в кластерах.
2. **Ограничьте права на изменение политик:** Только Security/Platform команды могут менять политики.
3. **Аудит изменений политик:** Все изменения логируются и ревьюятся.
4. **Резервное копирование политик:** Политики — код, храните их в Git.
5. **Изоляция Runner'ов:** Для критичных проверок используйте отдельные Runner pool с dedicated хостами, не shared с разработческими джобами.

## Граничные случаи и ограничения

1. **Монорепозитории:** Большие репозитории с тысячами ресурсов могут вызывать OOM в Runner'ах при генерации Terraform plan. Используйте `terraform plan -refresh=false` и кэширование бэкенда, ограничьте сканирование только изменёнными директориями (`paths` в GitLab CI).
2. **Динамические входные данные:** Conftest работает с статическим планом; для ресурсов с `count`/`for_each` убедитесь, что план содержит все экземпляры.
3. **Правила Checkov с переменными:** Если политика зависит от переменных Terraform, используйте `evaluate-variables: true` или передавайте `var-file` в Checkov.
4. **Trivy в air-gapped средах:** Требуется скачивание правил и баз уязвимостей. Настройте локальный репозиторий или используйте `--offline-server-address`.
5. **GitLab SAST false positives:** Владельцы политик должны регулярно обновлять правила и корректировать exemptions через `.gitlab-ci.yml` (`variables: SAST_EXCLUDED_ANALYZERS`).

## Дополнительная информация

### Связанные файлы

- **[CI/CD Security Hardening](../Advanced/cicd_security_hardening.md)** — общие принципы защиты CI/CD
- **[SAST/DAST: уязвимости](../../../CI-CD/DevSecOps/sast_dast_vulnerabilities.md)** — SAST, DAST, dependency scanning
- **[Terraform + GitLab CI](../Tutorials/terraform_gitlab_ci_integration.md)** — интеграция Terraform с GitLab CI
- **[GitOps: управление политиками](../../GitOps/Concepts/gitops-policy-management.md)** — доставка политик через GitOps (ArgoCD, Gatekeeper, Kyverno)

### Внешние ресурсы

- [OPA Documentation](https://www.openpolicyagent.org/docs/)
- [Conftest](https://www.conftest.dev/)
- [Checkov](https://www.checkov.io/)
- [TFLint](https://github.com/terraform-linters/tflint)
- [Trivy](https://aquasecurity.github.io/trivy/)
- [GitLab Security Policies](https://docs.gitlab.com/ee/user/application_security/policies/index.html)

### Пересечение с другими разделами базы знаний

| Файл | Пересечение | Отличие |
| :--- | :--- | :--- |
| `GitOps/Concepts/gitops-policy-management.md` | OPA, Gatekeeper, Kyverno, Rego | Данный файл описывает enforcement на этапе CI/CD; `gitops-policy-management.md` — доставку политик в кластеры через ArgoCD и Teleport |
| `GitOps/Crossplane/policy_governance.md` | Kyverno, OPA Gatekeeper, ValidatingAdmissionPolicy | Данный файл охватывает IaC-сканирование в пайплайнах; `policy_governance.md` — admission control для Crossplane Claim/XR |
