# Эшелонированная защита (Defense in Depth) на уровне IaC

**Актуально для:** OpenTofu 1.11+ / Terraform 1.9+; Trivy 0.71+; Checkov 3.3+; tflint 0.61+; Kyverno 1.11+

## Определения

**Эшелонированная защита (Defense in Depth) в IaC** — стратегия многоуровневого контроля безопасности инфраструктурного кода, при которой защитные механизмы располагаются слоями. Современный подход базируется на концепции **Zero Trust Infrastructure**, где ни одно изменение не считается безопасным без прохождения через цепочку независимых проверок: от IDE до среды выполнения (Runtime).

*   **Shift Left:** Перенос безопасности «максимально влево» — в IDE и локальную разработку через линтеры, SAST-плагины и pre-commit хуки (Checkov, Trivy, tflint), которые блокируют уязвимые паттерны на этапе написания кода, а не после коммита.
*   **IaC Drift (Дрейф конфигурации):** Расхождение между описанным в коде (Desired State) и реальным состоянием ресурсов в целевой среде (Actual State). Эшелонированная защита обязана не только предотвращать ошибки, но и обнаруживать дрейф, возникший в обход IaC. Подробнее: [Обнаружение дрейфа](../Core_Concepts/pipeline_glossary.md#drift-detection).
*   **Integrity (Целостность и provenance):** Подтверждение авторства и неизменности IaC-модулей и планов через подпись артефактов (Sigstore Cosign, in-toto attestations) и привязку к SLSA-уровням происхождения — практический пример ниже.
*   **OpenTofu:** Open-source IaC-инструмент (MPL 2.0, Linux Foundation/CNCF), форк Terraform с родной поддержкой шифрования state и S3 state locking. В 2025–2026 году стал стандартом для self-hosted и on-prem развёртываний,替代 BSL-лицензионный Terraform в новых проектах.

## Базовые концепции

### Принцип многослойного контроля (IaC Security Layers)

В отличие от разовых проверок, современный эшелонированный подход подразумевает непрерывную валидацию на каждом этапе:

1.  **Уровень 0: IDE & Local Development (Pre-commit):** Блокировка утечек секретов (`TruffleHog`), линтинг (`tflint`) и базовая проверка безопасности (`Checkov`/`Trivy`) на машине разработчика.
2.  **Уровень 1: Source Control Management (SCM):** Защищенные ветки (Protected Branches), обязательная подпись коммитов и процедура **Two-Party Review** (проверка кода вторым специалистом).
3.  **Уровень 2: CI Pipeline (IaC SAST & SCA):** Глубокий статический анализ всей инфраструктуры, включая проверку сторонних модулей (SCA) и генерацию **SBOM/CBOM** для инфраструктурных компонентов.
4.  **Уровень 3: Policy as Code (Validation & Compliance):** Проверка соответствия бизнес-правилам и корпоративным стандартам (например, OPA/Sentinel) на этапе `terraform plan`. Маппинг на CIS, NIST, PCI-DSS, GDPR.
5.  **Уровень 4: Admission Control & Guardrails:** Финальный фильтр перед применением изменений. Контроллеры допуска (Kyverno, OPA Gatekeeper) и политики кластера/платформы блокируют недопустимые действия на уровне API.
6.  **Уровень 5: Runtime Security & Drift Detection:** Непрерывный мониторинг состояния развернутой инфраструктуры и автоматизированное оповещение (или исправление) при обнаружении несанкционированных изменений.

### Жизненный цикл безопасности IaC (Lifecycle)

Безопасность не является отдельным этапом, она интегрирована во весь жизненный цикл:

1.  **Plan:** Threat Modeling инфраструктуры. Определение критических ресурсов и выбор Guardrails. Валидация state backend (шифрование, locking, backup).
2.  **Code:** Написание манифестов с проверкой линтерами (tflint) и SAST-плагинами IDE. Локальная валидация.
3.  **Review:** Аудит изменений. Проверка соответствия SLSA Source Track (подпись, идентичность).
4.  **Integrate:** Запуск CI-тестов. Генерация аттестаций сборки. Сканирование Trivy/Checkov.
5.  **Deploy:** Валидация политик (Policy as Code). Проверка подписей артефактов. Admission Control.
6.  **Operate:** Детектирование дрейфа. eBPF-мониторинг системных вызовов в контейнерах. Корреляция с SIEM.
7.  **Decommission:** Безопасное удаление ресурсов и отзыв прав доступа. Архивирование state.

### Компенсирующие слои, модель угроз и целостность цепочки поставок

Эшелонированная защита работает потому, что слои **компенсируют** слабости друг друга: если злоумышленник обходит один (например, разработчик отключает pre-commit), следующий (CI SAST, Policy as Code, Admission Control) перехватывает изменение. Типовые векторы атак на IaC и как их закрывают слои:

- **Компрометация CI-токена/runner:** злоумышленник применяет вредоносный план в обход SCM. Компенсируется Уровнем 4 (Admission Control/Kyverno) и Уровнем 3 (Policy as Code проверяет сам план, а не только дифф).
- **Вредоносный upstream-модуль:** подмена зависимого модуля/провайдера. Компенсируется SCA (Уровень 2), SBOM и подписью артефактов (см. ниже).
- **«Shadow Ops» (ручное изменение через консоль):** обход IaC. Компенсируется Уровнем 5 (Drift Detection) и средой выполнения.
- **Компрометация state backend:** кража или модификация `tfstate`. Компенсируется шифрованием state (S3 SSE-KMS / OpenTofu native encryption), versioning и ограниченными IAM-правами.

**Целостность и SBOM для IaC.** Для инфраструктурного кода применимы те же принципы, что и для приложений ([обзор цепочки поставок](../../Security/Supply_Chain_Security/overview.md)):
- Генерируйте **SBOM/CBOM** модулей и провайдеров (`cyclonedx-terraform`, `syft`), чтобы отслеживать уязвимые зависимости. Секреты провайдеров не должны попадать в SBOM — см. [управление секретами в CI/CD](./secrets_management.md).
- Подписывайте и верифицируйте модули/планы с помощью **Sigstore Cosign** (in-toto attestations, SLSA-совместимо) — self-hosted OSS-подход, не требующий облака:
- `tfsec` прекратил развитие и был объединён с Trivy; для новых проектов используйте `trivy config` вместо `tfsec`.

```bash
# подпись артефакта плана/модуля
cosign sign-blob plan.binary --key cosign.key --output-signature plan.sig
# верификация перед apply в CI
cosign verify-blob plan.binary --key cosign.pub --signature plan.sig
```

## Практические сценарии

### Уровень 0: IDE & Локальный контроль (Shift Left)

**Инструменты:** `tflint` (0.61+), `Checkov` (3.3+), `TruffleHog`, IDE-плагины SAST (Semgrep/Trivy).
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
    rev: v3.88.0
    hooks:
      - id: trufflehog
        args: ["git", "file://.", "--only-verified"]
  - repo: https://github.com/bridgecrewio/checkov.git
    rev: 3.3.8
    hooks:
      - id: checkov
        args: [--quiet, --compact, --soft-fail]
  - repo: https://github.com/aquasecurity/trivy
    rev: v0.74.0
    hooks:
      - id: trivy-config
        args: ['--skip-dirs', '.terraform']
```

**Отладка:** Если `checkov` или `trivy` работают слишком медленно, используйте параметр `--skip-check` / `--skip-dirs` для исключения ресурсоемких проверок на локальном этапе.

**Validation:** `pre-commit run --all-files` возвращает ненулевой код при находках; локальный коммит блокируется до исправления.

---

### Уровень 1: Защита Source Control (SCM)

**Инструменты:** GitHub/GitLab Settings, `GnuPG` / `Sigstore`.
**Назначение:** Гарантия авторства кода и предотвращение обхода проверок.

**Настройки Branch Protection:**
1.  **Require signed commits:** Блокировка коммитов без подписи (защита от подмены автора).
2.  **Require pull request reviews:** Минимум 2 одобряющих ревью (Two-Party Review).
3.  **Require status checks to pass:** Обязательное прохождение всех CI-пайплайнов перед слиянием.

**Практика: верификация подписанных коммитов в CI (без облака).** Настройки SCM недостаточно — проверку нужно дублировать в пайплайне, чтобы обход через локальный push не прошёл:

```bash
# включить подписание локально (GPG)
git config --global user.signingkey <KEYID>
git config --global commit.gpgsign true
# в CI: отклонять неподписанные коммиты в MR
git log --show-signature -1 HEAD | grep -q "Good signature" || {
  echo "ОШИБКА: коммит не подписан"; exit 1; }
```

**Troubleshooting:** если GPG недоступен в CI, используйте Sigstore `gitsign` (keyless, на основе OIDC) или проверку подписи OCI-артефактов через `cosign` (см. раздел «Целостность и SBOM для IaC»).

---

### Уровень 2: Статический анализ в CI (IaC SAST & SCA)

**Инструменты:** `Trivy` (0.71+, absorbed tfsec), `Checkov` (3.3+), `KICS`, `Snyk Infrastructure as Code`.
**Назначение:** Глубокий анализ графа ресурсов и проверка безопасности сторонних модулей.

> **Примечание:** `tfsec` объединён с Trivy и больше не развивается отдельно. Все проверки tfsec доступны в `trivy config` с теми же ID правил (AVD-*). Для новых проектов используйте Trivy как единый сканер IaC + CVE + секретов.

#### Пример GitHub Action для Trivy (IaC + Secret)

```yaml
- name: Run Trivy IaC scan
  uses: aquasecurity/trivy-action@latest
  with:
    scan-type: config
    scan-ref: terraform/
    format: sarif
    output: trivy-results.sarif
    severity: CRITICAL,HIGH
```

**Технический нюанс (SCA):** Используйте `Checkov` или `Trivy` для проверки версий провайдеров. Использование `latest` запрещено, так как это нарушает воспроизводимость и может привести к внедрению вредоносного кода через upstream.

**Расширенный пример: GitLab CI (IaC SAST + SCA + инкрементальное сканирование).** Вынесите проверки в отдельный job:

```yaml
iac-sast:
  image: aquasec/trivy:0.74.0
  script:
    - trivy config --severity CRITICAL,HIGH terraform/
    - checkov -d terraform/ --soft-fail-on WARN --framework terraform
    - kics scan -p terraform/ -o json --report-formats json
    # инкрементально: только изменённые в MR .tf-файлы
    - |
      git diff --name-only origin/main...HEAD | grep '\.tf$' > changed.lst
      if [ -s changed.lst ]; then
        trivy config $(cat changed.lst)
      else
        echo "Нет изменений в .tf-файлах"
      fi
  artifacts:
    reports:
      sast: gl-sast-report.json
```

**Validation:** пайплайн падает при критических находках (`--exit-code 1` для Trivy); отчёты загружаются как артефакты/SAST-отчёты GitLab.
**Troubleshooting:**
- *Медленный CI:* ограничьте область (`-d terraform/<service>`), используйте кэш провайдеров и инкрементальное сканирование.
- *Шум от сторонних модулей:* исключите `modules/vendor/` через `--skip-dirs` / `.checkovignore`.
- *Trivy не видит переменные:* передайте `--tf-vars` или `-var-file` для корректного разрешения интерполяций.

---

### Уровень 3: Policy as Code (Validation & Compliance)

**Инструменты:** `Open Policy Agent (OPA)`, `HashiCorp Sentinel`, `conftest`.
**Назначение:** Валидация `terraform plan` на соответствие сложным бизнес-логикам и Compliance-фреймворкам (CIS, NIST, PCI-DSS, GDPR, SOC 2).

#### Пример политики OPA для ограничения регионов (`regions.rego`)

```rego
package terraform

import input as tfplan

allowed_datacenters = ["dc-prod-01", "dc-prod-02"]

deny[msg] {
    resource := tfplan.resource_changes[_]
    resource.type == "vsphere_virtual_machine"
    dc := resource.change.after.datacenter
    not allowed_datacenters[_] == dc
    msg := sprintf("Datacenter %v не разрешен для деплоя", [dc])
}
```

**Как запускать эту политику в CI (без облака).** OPA-политику применяют к JSON-плану через `conftest`:

```bash
# получить план в JSON (Terraform / OpenTofu)
tofu plan -out tfplan.binary && tofu show -json tfplan.binary > tfplan.json
# проверить план политикой
conftest test tfplan.json --policy regions.rego
# при нарушении deny conftest возвращает ненулевой код -> пайплайн падает
```

**Validation:** `conftest test` завершается с ошибкой при нарушении `deny`; интегрируйте как отдельный шаг *перед* `apply`.
**Troubleshooting:** убедитесь, что структура `tfplan.json` соответствует версии Terraform/OpenTofu (поле `resource_changes`); для OpenTofu формат идентичен.

#### Compliance mapping

Trivy и Checkov автоматически мапят находки на compliance-фреймворки:
- **CIS Benchmarks** (AWS/Azure/GCP/Kubernetes)
- **PCI DSS v4.0**
- **NIST SP 800-53 / 800-171**
- **GDPR / SOC 2 / HIPAA / ISO 27001**

Используйте `trivy config --compliance cis_aws` или `checkov --framework terraform --check CIS_AWS_*` для генерации отчётов, приемлемых для аудиторов.

---

### Уровень 4: Admission Control & Guardrails

**Инструменты:** `Kyverno`, `OPA Gatekeeper`, `conftest` (для проверки планов/манифестов).
**Назначение:** Непреодолимые барьеры на уровне API кластера или платформы управления.

**Пример self-hosted Admission Control (Kyverno, Kubernetes on-prem).** Блокируйте небезопасные манифесты на уровне кластера без привязки к облачному провайдеру (подробнее — [Admission Controllers](../../Kubernetes/Concepts/admission_controllers.md) и [управление политиками GitOps](../../GitOps/Concepts/gitops-policy-management.md)):

```yaml
# require-non-root-user.yaml — запрет контейнеров от root
apiVersion: kyverno.io/v1
kind: ClusterPolicy
metadata:
  name: require-non-root-user
spec:
  validationFailureAction: Enforce
  rules:
  - name: check-runasnonroot
    match:
      resources:
        kinds:
        - Pod
    validate:
      message: "Контейнеры не могут работать от root"
      pattern:
        spec:
          containers:
          - securityContext:
              runAsNonRoot: true
```

**Validation:** попытка применить Pod с `runAsNonRoot: false` отклоняется API-сервером (`denied by require-non-root-user`).
**Troubleshooting:** для сложной логики используйте OPA Gatekeeper (Rego) — см. [разбор OPA](../../Kubernetes/Security/rbac/limitations_opa.md); держите политики в Git (GitOps) и тестируйте их через `kyverno apply` до мержа.

---

### Уровень 5: Runtime Security & Drift Detection

**Инструменты:** OpenTofu/Terraform native `-refresh-only`, `driftctl` (архивный), `Driftive`, `Tetragon`, `Falco`.
**Назначение:** Выявление изменений, сделанных вручную через консоль ("Shadow Ops").

#### Настройка Drift Detection в пайплайне (modern approach)

Современный подход использует встроенный режим `-refresh-only` вместо устаревших внешних инструментов:

```bash
# OpenTofu / Terraform 1.9+: refresh-only drift detection
tofu plan -refresh-only -detailed-exitcode >/dev/null
case $? in
  0) echo "Дрейфа нет" ;;
  2) echo "ВНИМАНИЕ: Обнаружен дрейф конфигурации!" | mail -s "IaC Drift" oncall@corp.local ;;
  *) echo "Ошибка планирования" ;;
esac
```

**Планировщик дрейфа (systemd timer, без зависимости от cron-окружения).** Вместо разовой проверки настройте постоянный мониторинг:

```ini
# /etc/systemd/system/iac-drift.timer
[Unit]
Description=Ежедневная проверка дрейфа IaC
[Timer]
OnCalendar=*-*-* 03:00:00
Persistent=true
[Install]
WantedBy=timers.target
```

```bash
# /usr/local/bin/iac-drift.sh (вызывается сервисом)
tofu plan -refresh-only -detailed-exitcode -out drift.tfplan >/dev/null 2>&1
case $? in
  0) echo "Дрейфа нет" ;;
  2) echo "Дрейф обнаружен" | mail -s "IaC Drift" oncall@corp.local ;;
esac
```

**Runbook SRE при обнаружении дрейфа (Remediation).**
1. Не применять `apply` автоматически — сначала классифицировать: ожидаемое изменение (запланированное) vs несанкционированное («Shadow Ops»).
2. Для несанкционированного: зафиксировать в incident-трекере, уведомить владельца, при необходимости откатить вручную и усилить Admission Control (Уровень 4).
3. Для ожидаемого: обновить код IaC (`tofu apply` из кода), чтобы Desired/Actual совпали.

**Runtime-подтверждение (eBPF, без облака).** Falco/Tetragon на узлах фиксируют аномалии (например, ручное изменение конфигурации в обход IaC), подтверждая, что дрейф реально эксплуатируется:

```yaml
# Falco rule (фрагмент): ручное изменение конфигурации в обход IaC
- rule: Unexpected K8s Config Change
  desc: Ручное изменение конфигурации в обход IaC
  condition: k8s_audit and response_operation="update" and not pod_namespace in ("ci")
  output: "Ручное изменение (user=%user.name)"
  priority: WARNING
```

---

### State Backend Security (SysAdmin)

**Безопасность state backend** — критически важный аспект, часто упускаемый при обсуждении эшелонированной защиты.

**Шифрование и locking:**
- **OpenTofu 1.7+:** родное шифрование state и plan файлов через `encryption {}` блок с поддержкой PBKDF2, AWS KMS, GCP KMS, Azure Key Vault.
- **S3 backend:** включите `use_lockfile=true` (OpenTofu/Terraform 1.10+) для native state locking без DynamoDB. Включите Bucket Versioning для восстановления после случайного удаления.
- **S3 SSE:** включите `encrypt = true` и preferably `kms_key_id` для SSE-KMS.

**Резервное копирование state:**
- Регулярный бэкап `tfstate` в отдельный bucket/регион с immutability policy.
- Тестируйте восстановление state ежеквартально (DR drill).
- Никогда не храните state локольно для production-окружений.

**Пример backend configuration (OpenTofu):**

```hcl
terraform {
  backend "s3" {
    bucket         = "tofu-state-prod"
    key            = "network/terraform.tfstate"
    region         = "eu-central-1"
    use_lockfile   = true
    encrypt        = true
    kms_key_id     = "arn:aws:kms:eu-central-1:123456789:alias/tofu-state-key"
  }
  encryption {
    key_provider "pbkdf2" "local" {
      passphrase = "correct-horse-battery-staple"
    }
    state {
      method = key_provider.pbkdf2.local
    }
  }
}
```

## Рекомендации и лучшие практики

1.  **Принцип "Fail Fast":** Уровни 0 и 1 должны блокировать 80% простых ошибок. Уровни 3-4 предназначены для сложных архитектурых рисков.
2.  **Использование SBOM для IaC:** Генерируйте список всех используемых модулей и версий провайдеров (`cyclonedx-terraform`).
3.  **Аудит Service Accounts:** Сервисные аккаунты IaC должны иметь права только на те ресурсы, которыми они управляют (Least Privilege).
4.  **Регулярная ротация секретов:** Интегрируйте IaC с HashiCorp Vault для получения динамических учетных данных провайдеров.
5.  **State backend security:** всегда используйте remote state с шифрованием, locking и versioning.
6.  **Compliance as Code:** мапьте политики на compliance-фреймворки (CIS, PCI-DSS, NIST) для упрощения аудита.
7.  **Change Management:** обновления сканеров и политик проходят через тот же IaC-процесс, что и инфраструктура — версионируются, ревьюятся, тестируются в staging.

## Устранение типичных проблем

| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| **Ложные срабатывания (False Positives)** | Устаревшие правила SAST | Используйте inline-аннотации для подавления с обоснованием (напр. `#tfsec:ignore:<rule-id>` или `checkov:skip=<ID>:<причина>`). |
| **Медленный CI** | Огромное количество ресурсов | Используйте инкрементальное сканирование (только измененных файлов). |
| **Конфликты Guardrails** | Пересечение политик OPA и Kyverno | Централизуйте управление политиками; кластерные Guardrails (Kyverno) — более "грубыми", OPA/conftest на плане — детальными. |
| **Drift detection не работает** | Устаревший `driftctl` или неправильный exit code | Используйте `tofu plan -refresh-only -detailed-exitcode`; убедитесь, что backend поддерживает locking. |
| **State file corrupted** | Concurrent apply без locking | Включите `use_lockfile=true` в S3 backend; для legacy DynamoDB — проверьте таблицу. |
| **Секреты в state файле** | Провайдер сохраняет ключи в state | Используйте OpenTofu native encryption или внешний KMS; настройте `sensitive = true` для outputs. |
| **Trivy не видит переменные Terraform** | Отсутствуют `.tfvars` или workspace | Передайте `--tf-vars` или запускайте в директории с правильным workspace. |

## Операционные практики для DevOps/SRE/Sysadmin

### Метрики программы (SLO/SLI)

Отслеживайте:
- **Scan Success Rate:** доля успешных пайплайнов без критичных IaC-нарушений (target: >99%).
- **Policy Pass Rate:** доля планов, прошедших OPA/conftest без deny.
- **Drift MTTR:** время от обнаружения дрейфа до фиксации кода (target: < 24h для production).
- **Scan Duration:** p95 времени выполнения Trivy/Checkov на репозиторий (target: < 5 min).
- **Mean Time to Policy Update (MTTPU):** время от принятия новой политики до деплоя в Admission Control.
- **% Suppressions:** доля подавлений правил с обоснованием (алерт при >10% без review).

Дашборд в Grafana/Prometheus. Источником метрик являются SARIF-отчёты Trivy/Checkov и логи CI-раннеров.

### Владение (Ownership)

Каждый репозиторий IaC привязан к владельцу через CODEOWNERS; находка/дрейф без владельца не закрывается.

### Дисциплина подавлений

Аннотации `#tfsec:ignore:...` и исключения OPA/Checkov только с обоснованием и сроком; регулярный review, чтобы не накопить «тихие» уязвимости.

### Change Management для политик и сканеров

Обновления политик OPA/Rego и версий сканеров (Trivy, Checkov) проходят через тот же процесс, что и IaC:
1. Ветка `policy-updates` с изменением.
2. CI: линтинг Rego (`conftest test --namespace all`), dry-run на актуальном плане.
3. Two-Party Review + Approval от Security-команды.
4. Мерж и автоматическое применение к кластеру через GitOps (Argo CD/Flux).

### Инцидент-респонс для несанкционированного изменения

Эскалация в on-call, ротация затронутых секретов провайдеров (см. [управление секретами](./secrets_management.md)), блокировка через Admission Control, post-mortem.

### Resource Constraints и cgroup-лимиты для раннеров

Сканеры IaC (Trivy, Checkov) интенсивно используют CPU и память при больших монореpos. Настройте:
- `MemoryMax=4G` / `CPUQuota=200%` для job-контейнеров сканирования.
- Отдельный pool раннеров для IaC-сканов с изоляцией от application-билдов.
- Ограничение параллелизма (`--concurrency 4` в Trivy) для предотвращения OOM.

### Сетевая изоляция

IaC-сканеры должны иметь доступ только к:
- Реестру модулей (`registry.terraform.io`, внутренний модульный registry).
- API провайдеров для валидации плана (если используется `terraform plan` с реальным бэкендом).
- Внешним базам CVE (NVD, GHSA) — через прокси с аудитом.

Запретите исходящий трафик из job-контейнеров сканирования в интернет, кроме разрешённых доменов (egress firewall в раннере).

### Журналирование и retention

- Все логи Trivy/Checkov/OPA сохраняются в центральный storage (Loki/ELK) с retention 90 дней.
- Обогащение логов `pipeline_id`, `repo`, `commit_sha`, `actor` для построения таймлайна.
- Алерт при попытке отключения сканера или изменении `.pre-commit-config.yaml` без CODEOWNERS approval.

## Дополнительная информация
- [DevSecOps — обзор методологии](./devsecops_overview.md)
- [GitOps: Управление политиками](../../GitOps/Concepts/gitops-policy-management.md)
- [Kubernetes: Admission Controllers](../../Kubernetes/Concepts/admission_controllers.md)
- [Обнаружение дрейфа](../Core_Concepts/pipeline_glossary.md#drift-detection)
- [Test-Driven Infrastructure (TDI)](../Testing/tdd_bdd_overview.md#test-driven-infrastructure-tdi)
