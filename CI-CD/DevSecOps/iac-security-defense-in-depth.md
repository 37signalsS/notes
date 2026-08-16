# Эшелонированная защита (Defense in Depth) на уровне IaC

## Определения

**Эшелонированная защита (Defense in Depth) в IaC** — стратегия многоуровневого контроля безопасности инфраструктурного кода, при которой защитные механизмы располагаются слоями. В 2026 году этот подход базируется на концепции **Zero Trust Infrastructure**, где ни одно изменение не считается безопасным без прохождения через цепочку независимых проверок: от IDE до среды выполнения (Runtime).

*   **Shift Left 2.0:** Перенос безопасности «максимально влево» — непосредственно в IDE с использованием ИИ-ассистентов, которые блокируют уязвимые паттерны на этапе написания кода, а не после коммита.
*   **IaC Drift (Дрейф конфигурации):** Расхождение между описанным в коде (Desired State) и реальным состоянием ресурсов в облаке (Actual State). Эшелонированная защита обязана не только предотвращать ошибки, но и обнаруживать дрейф, возникший в обход IaC.
*   **PQC-Integrity (Постквантовая целостность):** Использование квантово-устойчивых алгоритмов подписи (например, **ML-DSA**) для подтверждения авторства IaC-модулей и манифестов, предотвращающее атаки типа «Harvest Now, Decrypt Later» (HNDL).

## Базовые концепции

### Принцип многослойного контроля (IaC Security Layers)

В отличие от разовых проверок, современный эшелонированный подход подразумевает непрерывную валидацию на каждом этапе:

1.  **Уровень 0: IDE & Local Development (Pre-commit):** Блокировка утечек секретов (`TruffleHog`), линтинг (`tflint`) и базовая проверка безопасности (`Checkov`) на машине разработчика.
2.  **Уровень 1: Source Control Management (SCM):** Защищенные ветки (Protected Branches), обязательная подпись коммитов и процедура **Two-Party Review** (проверка кода вторым специалистом).
3.  **Уровень 2: CI Pipeline (IaC SAST & SCA):** Глубокий статический анализ всей инфраструктуры, включая проверку сторонних модулей (SCA) и генерацию **SBOM/CBOM** для инфраструктурных компонентов.
4.  **Уровень 3: Policy as Code (Validation & Compliance):** Проверка соответствия бизнес-правилам и корпоративным стандартам (например, OPA/Sentinel) на этапе `terraform plan`.
5.  **Уровень 4: Admission Control & Cloud Guardrails:** Финальный фильтр перед применением изменений. Облачные политики (AWS SCP, Azure Policy) и контроллеры допуска (Kyverno) блокируют недопустимые действия на уровне API.
6.  **Уровень 5: Runtime Security & Drift Detection:** Непрерывный мониторинг состояния развернутой инфраструктуры и автоматизированное оповещение (или исправление) при обнаружении несанкционированных изменений.

### Жизненный цикл безопасности IaC (Lifecycle 2026)

Безопасность не является отдельным этапом, она интегрирована во весь жизненный цикл:

1.  **Plan:** Threat Modeling инфраструктуры. Определение критических ресурсов и выбор Guardrails.
2.  **Code:** Написание манифестов с поддержкой ИИ-линтеров. Локальная валидация.
3.  **Review:** Аудит изменений. Проверка соответствия SLSA Source Track (подпись, идентичность).
4.  **Integrate:** Запуск CI-тестов. Генерация аттестаций сборки.
5.  **Deploy:** Валидация политик (Policy as Code). Проверка подписей артефактов.
6.  **Operate:** Детектирование дрейфа. eBPF-мониторинг системных вызовов в контейнерах.
7.  **Decommission:** Безопасное удаление ресурсов и отзыв прав доступа.

## Практические сценарии

### Уровень 0: IDE & Локальный контроль (Shift Left)

**Инструменты:** `tflint`, `Checkov`, `TruffleHog`, `AI Copilot`.
**Назначение:** Обнаружение ошибок и утечек до фиксации кода в Git.

#### Настройка pre-commit (`.pre-commit-config.yaml`)

**Предварительные требования:** Установленный Python, `pre-commit` и бинарные файлы линтеров.

```yaml
repos:
  - repo: https://github.com/pre-commit/pre-commit-hooks
    rev: v4.6.0
    hooks:
      - id: trailing-whitespace
      - id: end-of-file-fixer
  - repo: https://github.com/trufflesecurity/trufflehog
    rev: v3.82.0
    hooks:
      - id: trufflehog
        args: ["git", "file://.", "--only-verified"]
  - repo: https://github.com/bridgecrewio/checkov.git
    rev: 3.2.200
    hooks:
      - id: checkov
        args: [--quiet, --compact, --soft-fail]
```

**Отладка:** Если `checkov` работает слишком медленно, используйте параметр `--skip-check` для исключения ресурсоемких проверок на локальном этапе.

---

### Уровень 1: Защита Source Control (SCM)

**Инструменты:** GitHub/GitLab Settings, `GnuPG` / `Sigstore`.
**Назначение:** Гарантия авторства кода и предотвращение обхода проверок.

**Настройки Branch Protection:**
1.  **Require signed commits:** Блокировка коммитов без подписи (защита от подмены автора).
2.  **Require pull request reviews:** Минимум 2 одобряющих ревью (Two-Party Review).
3.  **Require status checks to pass:** Обязательное прохождение всех CI-пайплайнов перед слиянием.

---

### Уровень 2: Статический анализ в CI (IaC SAST & SCA)

**Инструменты:** `tfsec`, `KICS`, `Snyk Infrastructure as Code`.
**Назначение:** Глубокий анализ графа ресурсов и проверка безопасности сторонних модулей.

#### Пример GitHub Action для tfsec
```yaml
- name: Run tfsec
  uses: aquasecurity/tfsec-action@v1.0.0
  with:
    github_token: ${{ secrets.GITHUB_TOKEN }}
    working_directory: terraform/
    soft_fail: false # Блокировать пайплайн при критических находках
```

**Технический нюанс (SCA):** Используйте `Checkov` для проверки версий провайдеров. Использование `latest` запрещено, так как это нарушает воспроизводимость и может привести к внедрению вредоносного кода через upstream.

---

### Уровень 3: Policy as Code (Validation)

**Инструменты:** `Open Policy Agent (OPA)`, `HashiCorp Sentinel`.
**Назначение:** Валидация `terraform plan` на соответствие сложным бизнес-логикам (например, ограничения по стоимости или регионам).

#### Пример политики OPA для ограничения регионов (`regions.rego`)
```rego
package terraform

import input as tfplan

allowed_regions = ["europe-west3", "europe-west4"]

deny[msg] {
    resource := tfplan.resource_changes[_]
    resource.type == "google_compute_instance"
    region := resource.change.after.zone
    not startswith(region, allowed_regions[_])
    msg := sprintf("Регион %v не разрешен для деплоя", [region])
}
```

---

### Уровень 4: Облачные Guardrails & Admission Control

**Инструменты:** `AWS SCP`, `Azure Policy`, `Kyverno` (для K8s).
**Назначение:** Непреодолимые барьеры на уровне API облака или кластера.

**Сценарий:** AWS Service Control Policy (SCP), запрещающая создание публичных S3-бакетов на уровне всей Organization Unit (OU). Даже если Terraform настроен на Public, запрос будет отклонен AWS API с ошибкой `AccessDenied`.

---

### Уровень 5: Runtime Security & Drift Detection

**Инструменты:** `driftctl` (архивный, заменен на нативный drift detection в Terraform Cloud/OpenTofu), `Tetragon`.
**Назначение:** Выявление изменений, сделанных вручную через консоль ("Shadow Ops").

#### Настройка Drift Detection в пайплайне
Запускайте проверку по расписанию (cron):
```bash
# Для OpenTofu / Terraform
tofu plan -detailed-exitcode > /dev/null
if [ $? -eq 2 ]; then
  echo "ВНИМАНИЕ: Обнаружен дрейф конфигурации!"
  # Отправка уведомления в Slack/Jira
fi
```

---

## Рекомендации и лучшие практики

1.  **Принцип "Fail Fast":** Уровни 0 и 1 должны блокировать 80% простых ошибок. Уровни 3-4 предназначены для сложных архитектурных рисков.
2.  **Использование SBOM для IaC:** Генерируйте список всех используемых модулей и версий провайдеров (`cyclonedx-terraform`).
3.  **Аудит Service Accounts:** Сервисные аккаунты IaC должны иметь права только на те ресурсы, которыми они управляют (Least Privilege).
4.  **Регулярная ротация секретов:** Интегрируйте IaC с HashiCorp Vault для получения динамических учетных данных провайдеров.

## Устранение типичных проблем

| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| **Ложные срабатывания (False Positives)** | Устаревшие правила SAST | Используйте inline-аннотации для подавления (напр. `#tfsec:ignore:aws-s3-enable-versioning`). |
| **Медленный CI** | Огромное количество ресурсов | Используйте инкрементальное сканирование (только измененных файлов). |
| **Конфликты Guardrails** | Пересечение политик OPA и SCP | Централизуйте управление политиками; SCP должны быть более "грубыми", OPA — детальными. |

## Дополнительная информация
- [DevSecOps — обзор методологии](./devsecops_overview.md)
- [Безопасность цепочки поставок (Supply Chain Security)](../../Security/Supply_Chain_Security/overview.md)
- [Kubernetes: Admission Controllers](../../Kubernetes/Concepts/admission_controllers.md)
- [GitOps: Управление политиками](../../GitOps/Concepts/gitops-policy-management.md)
- [Управление секретами в CI/CD](./secrets_management.md)
