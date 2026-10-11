# GitLab CI/CD для IaC пайплайнов: backends, drift detection и state management

**Актуально для:** GitLab 19.x, Terraform 1.16.x, OpenTofu 1.12.x

## Предварительные требования

### Желаемые компетенции
*   **Системное администрирование:** Уверенная работа с Linux/Unix, понимание lifecycle сервисов (systemd), базовое сетевое администрирование (SSH, firewall, DNS).
*   **Работа с репозиториями:** Git (ветвление, merge, code review), понимание CI/CD-пайплайнов.
*   **Языки конфигурации:** Чтение YAML, JSON, HCL; базовое понимание Jinja2 для шаблонизации.

### Инструменты
*   **IaC-инструмент:** Terraform 1.16.x или OpenTofu 1.12.x.
*   **Backend для state:** На выбор — HTTP-сервис, Consul, etcd, Kubernetes (для on-prem); S3-совместимое хранилище (MinIO, Ceph) или cloud backend.
*   **Линтеры:** `tflint`, `checkov`, `tfsec`, `conftest`.
*   **CI/CD:** GitLab 19.x с настроенными раннерами.
*   **Среда выполнения:** Локальная или тестовая инфраструктура для проверки изменений перед применением в production.

### Безопасность
*   **Принцип наименьших привилегий:** Учетная запись, от которой запускается IaC-пайплайн, должна иметь минимально необходимые права.
*   **Хранение секретов:** Настроен менеджер секретов (HashiCorp Vault, SOPS) или защищенные переменные окружения CI/CD.
*   **Аудит:** Включено логирование всех применений инфраструктурных изменений.

## Определения

**IaC (Infrastructure as Code)** — управление инфраструктурой через декларативные конфигурации (Terraform, OpenTofu, Ansible). В контексте GitLab CI/CD — автоматическое применение изменений инфраструктуры через пайплайны.

**State locking** — механизм предотвращения параллельного применения изменений, который защищает от гонок и повреждения state-файла. Реализуется через backend (Consul, etcd, Kubernetes, HTTP, S3-compatible).

**Drift detection** — обнаружение расхождений между желаемым состоянием (код) и фактическим состоянием (инфраструктура). Terraform/OpenTofu поддерживают `terraform plan -refresh-only` и `tofu plan -refresh-only`.

**Workspace** — изолированное окружение Terraform/OpenTofu (аналог environment). Один backend может содержать множество workspaces.

**Backend** — хранилище для state-файла Terraform/OpenTofu. Типы: local, HTTP, Consul, etcd, Kubernetes, S3, GCS, Azure Blob.

**Sensitive variables** — переменные, которые не должны отображаться в логах (пароли, ключи, токены). В GitLab CI — `masked: true`, `protected: true`.

**State lifecycle** — последовательность операций с state-файлом: инициализация (`init`), чтение (`pull`), применение (`apply`), принудительное обновление (`push`), импорт существующих ресурсов (`import`), удаление ресурсов (`rm`).

**Refresh-only plan** — план, который только обновляет state in-memory для сравнения с реальной инфраструктурой, не применяя изменений. Используется для drift detection.

**Resource group** — механизм GitLab CI/CD, который гарантирует, что в конкретной среде запускается только один деплой одновременно. При попытке второго параллельного запуска задача ставится в очередь (`pending`).

## Основные концепции

### Архитектура управления state в GitLab CI/CD

```
GitLab Repository
  └── .gitlab-ci.yml
        ├── validate stage (fmt, validate, lint)
        ├── plan stage (terraform plan -out=tfplan)
        ├── apply stage (manual approval → terraform apply)
        └── drift-detection stage (scheduled: terraform plan -refresh-only)

State Backend (on-prem)
  ├── Consul KV (state + session-based locking)
  ├── etcd (state + lock)
  ├── Kubernetes Secret (state + lock)
  └── HTTP REST API (state + LOCK/UNLOCK endpoints)

Notifications
  ├── Slack/PagerDuty (drift alerts)
  ├── GitLab Issue (manual remediation)
  └── Email (state lock timeout)
```

### Сравнение backends для Terraform/OpenTofu (on-prem фокус)

| Backend | State locking | Encryption | Versioning | Рекомендация |
| :--- | :--- | :--- | :--- | :--- |
| **Consul** | Да (Consul session) | TLS | Нет | Стандарт для Consul-инфраструктуры |
| **etcd** | Да (etcd lock) | TLS | Нет | Для Kubernetes-инфраструктуры |
| **Kubernetes** | Да (K8s secret) | K8s encryption | Нет | GitLab Runner в K8s |
| **HTTP** | Да (LOCK/UNLOCK endpoints) | TLS | Зависит от реализации | Кастомные REST API |
| **S3-compatible (MinIO)** | Да (нативный locking или DynamoDB-совместимый) | SSE | Да | Self-hosted S3 |
| **Local** | Нет (файловая система) | Нет | Нет | Только для экспериментов |

> **Примечание:** Cloud-native backends (AWS S3, GCS, Azure Blob) также поддерживаются, но требуют отдельной инфраструктуры и не рассматриваются как primary recommendation в контексте on-prem/self-hosted сред.

### Сравнение drift detection инструментов

| Инструмент | Метод | Скорость | Точность | Гейт в CI |
| :--- | :--- | :--- | :--- | :--- |
| **Terraform/OpenTofu plan -refresh-only** | Pull state → compare | Медленная | Высокая | Да |
| **Ansible --check** | Push desired state → compare | Средняя | Средняя | Да |
| **Custom scripts** | API-запросы → compare | Быстрая | Зависит от скрипта | Да |
| **OpenSCAP** | Compliance scan | Средняя | Высокая | Да |

### OpenTofu vs Terraform в GitLab CI

| Критерий | Terraform | OpenTofu |
| :--- | :--- | :--- |
| **Лицензия** | BSL (Business Source License) | MPL 2.0 (Linux Foundation) |
| **Текущая стабильная версия** | 1.16.x (август 2026) | 1.12.x (август 2026) |
| **State locking** | Consul, etcd, K8s, HTTP, S3+DynamoDB | Consul, etcd, K8s, HTTP, S3 (+ нативный S3 locking через `use_lockfile=true`) |
| **Шифрование state** | Зависит от backend | Нативное шифрование state |
| **Рекомендация** | Существующие проекты | Новые проекты (2026) |

### State lifecycle и workspace isolation

State-файл — самый критичный компонент IaC. Его lifecycle включает:

1. **Инициализация:** `terraform init` создаёт `.terraform` и подключает backend.
2. **Чтение:** `terraform state pull` загружает state из remote backend.
3. **Планирование:** `terraform plan` читает state, сравнивает с конфигурацией.
4. **Применение:** `terraform apply` пишет новый state в backend (под lock).
5. **Импорт:** `terraform import` добавляет существующий ресурс в state.
6. **Удаление:** `terraform state rm` удаляет ресурс из state (не удаляет сам ресурс).

**Workspace isolation** — каждый workspace имеет свой state-файл внутри одного backend. Это позволяет разделить окружения (`dev`, `staging`, `production`) без дублирования инфраструктуры backend.

### Управление секретами в IaC-пайплайнах

Стратегии хранения секретов в GitLab CI/CD для IaC:

| Стратегия | Описание | Инструменты | Когда использовать |
| :--- | :--- | :--- | :--- |
| **GitLab protected variables** | Переменные в Settings → CI/CD, masked/protected | GitLab CI/CD | Простые пайплайны, Dev/Staging |
| **External Secrets Manager** | Секреты хранятся во внешнем менеджере (Vault) | HashiCorp Vault, SOPS | Enterprise-среды, compliance-требования |
| **SOPS-шифрование** | Файлы с секретами зашифрованы в Git | SOPS (Mozilla), Age | Git-ориентированный workflow |
| **OIDC workload identity** | Временные credentials без статических ключей | GitLab OIDC, cloud IAM | Production, least privilege |

## Практические сценарии

### Сценарий 1: Выбор backend для on-prem сред

Выбор backend зависит от инфраструктуры и требований к locking:

| Инфраструктура | Рекомендуемый backend | State locking | Encryption |
| :--- | :--- | :--- | :--- |
| **Consul cluster** | Consul KV | Да (session) | TLS |
| **etcd cluster** | etcd | Да (lock) | TLS |
| **Kubernetes** | Kubernetes Secret | Да | K8s encryption |
| **Кастомная HTTP API** | HTTP | Да (LOCK/UNLOCK) | TLS |
| **MinIO / S3-compatible** | S3 | Да (нативный locking) | SSE |
| **Эксперименты** | Local | Нет | Нет |

### Сценарий 2: Scheduled drift detection (Terraform/OpenTofu)

```yaml
stages:
  - drift-detection

variables:
  TF_ROOT: ${CI_PROJECT_DIR}/terraform
  TF_IMAGE: hashicorp/terraform:1.16.0

drift-detection:
  stage: drift-detection
  image: ${TF_IMAGE}
  script:
    - cd $TF_ROOT
    - terraform init -backend-config="bucket=${TF_STATE_NAME}" -backend-config="key=${TF_STATE_NAME}.tfstate"
    - terraform plan -refresh-only -out=drift-plan -no-color || true
    - |
      if terraform show -no-color drift-plan | grep -q "No changes."; then
        echo "No drift detected"
        echo "DRIFT_STATUS=no_drift" >> $CI_ENVIRONMENT_VARIABLES
      else
        echo "Drift detected!"
        terraform show -no-color drift-plan
        echo "DRIFT_STATUS=drift_detected" >> $CI_ENVIRONMENT_VARIABLES
        curl -X POST -H 'Content-type: application/json' \
          --data "{\"text\":\"Drift detected in ${CI_PROJECT_NAME}!\"}" \
          $SLACK_WEBHOOK_URL
        exit 1
      fi
  only:
    - schedules
  tags:
    - drift-runner
  resource_group: ${CI_PROJECT_NAME}-drift
```

### Сценарий 3: Multi-workspace pipeline

```yaml
variables:
  TF_WORKSPACE: ${CI_ENVIRONMENT_NAME:-dev}

stages:
  - plan
  - apply

plan:
  stage: plan
  image: hashicorp/terraform:1.16.0
  script:
    - cd $TF_ROOT
    - terraform workspace select -or-create $TF_WORKSPACE
    - terraform plan -out=tfplan -no-color
  artifacts:
    paths:
      - $TF_ROOT/tfplan
    expire_in: 1 week
  environment:
    name: $TF_WORKSPACE

apply:
  stage: apply
  image: hashicorp/terraform:1.16.0
  script:
    - cd $TF_ROOT
    - terraform workspace select $TF_WORKSPACE
    - terraform apply -no-color -auto-approve tfplan
  environment:
    name: $TF_WORKSPACE
  only:
    - main
  when: manual
  resource_group: ${CI_PROJECT_NAME}-${TF_WORKSPACE}
```

### Сценарий 4: HTTP backend для on-prem инфраструктуры

```yaml
variables:
  TF_ROOT: ${CI_PROJECT_DIR}/terraform
  STATE_ADDRESS: "https://terraform-state.internal.company.com/state/${CI_PROJECT_NAME}"

stages:
  - plan
  - apply

plan:
  stage: plan
  image: hashicorp/terraform:1.16.0
  script:
    - cd $TF_ROOT
    - terraform init \
        -backend-config="address=${STATE_ADDRESS}" \
        -backend-config="lock_address=${STATE_ADDRESS}" \
        -backend-config="unlock_address=${STATE_ADDRESS}"
    - terraform plan -out=tfplan -no-color
  artifacts:
    paths:
      - $TF_ROOT/tfplan
    expire_in: 1 week

apply:
  stage: apply
  image: hashicorp/terraform:1.16.0
  script:
    - cd $TF_ROOT
    - terraform apply -no-color -auto-approve tfplan
  only:
    - main
  when: manual
  resource_group: ${CI_PROJECT_NAME}-production
```

### Сценарий 5: Consul backend

```yaml
variables:
  TF_ROOT: ${CI_PROJECT_DIR}/terraform
  CONSUL_ADDRESS: "consul.service.consul:8500"

stages:
  - plan
  - apply

plan:
  stage: plan
  image: hashicorp/terraform:1.16.0
  script:
    - cd $TF_ROOT
    - terraform init \
        -backend-config="address=${CONSUL_ADDRESS}" \
        -backend-config="path=${CI_PROJECT_NAME}/terraform.tfstate"
    - terraform plan -out=tfplan -no-color
  artifacts:
    paths:
      - $TF_ROOT/tfplan
    expire_in: 1 week

apply:
  stage: apply
  image: hashicorp/terraform:1.16.0
  script:
    - cd $TF_ROOT
    - terraform apply -no-color -auto-approve tfplan
  only:
    - main
  when: manual
  resource_group: ${CI_PROJECT_NAME}-production
```

### Сценарий 6: Резервное копирование и восстановление state

```yaml
variables:
  TF_ROOT: ${CI_PROJECT_DIR}/terraform
  TF_STATE_BUCKET: "terraform-state-${CI_PROJECT_ID}"

backup-state:
  stage: .pre
  image: hashicorp/terraform:1.16.0
  script:
    - cd $TF_ROOT
    - terraform init -backend-config="bucket=${TF_STATE_BUCKET}" -backend-config="key=backups/terraform.tfstate"
    - terraform state pull > backup-${CI_COMMIT_SHORT_SHA}.tfstate
    - terraform state push backup-${CI_COMMIT_SHORT_SHA}.tfstate
  only:
    - main
  tags:
    - backup-runner

restore-state:
  stage: .pre
  image: hashicorp/terraform:1.16.0
  script:
    - cd $TF_ROOT
    - terraform init -backend-config="bucket=${TF_STATE_BUCKET}" -backend-config="key=backups/terraform.tfstate"
    - terraform state push backup-${CI_COMMIT_SHORT_SHA}.tfstate
  only:
    - schedules
  tags:
    - backup-runner
  when: manual
```

### Сценарий 7: Drift detection для Ansible

```yaml
stages:
  - drift-detection

variables:
  ANSIBLE_INVENTORY: ${CI_PROJECT_DIR}/inventory/production.ini

drift-detection:
  stage: drift-detection
  image: ansible/ansible:latest
  script:
    - cd $CI_PROJECT_DIR/ansible
    - ansible-playbook site.yml --check --diff -i ${ANSIBLE_INVENTORY} > drift-report.txt || true
    - |
      if grep -q "changed=" drift-report.txt; then
        echo "DRIFT_DETECTED=true" >> drift.env
        cat drift-report.txt
      else
        echo "DRIFT_DETECTED=false" >> drift.env
      fi
  artifacts:
    reports:
      dotenv: drift.env
    paths:
      - drift-report.txt
    expire_in: 7 days
  rules:
    - if: $CI_PIPELINE_SOURCE == "schedule"
      cron: "0 6 * * 1-5"
  resource_group: ${CI_PROJECT_NAME}-ansible-drift
```

### Сценарий 8: Pipeline controls с resource_group и needs

```yaml
stages:
  - validate
  - plan
  - apply

variables:
  TF_ROOT: ${CI_PROJECT_DIR}/terraform

.validate:
  stage: validate
  image: hashicorp/terraform:1.16.0
  script:
    - cd $TF_ROOT
    - terraform init -backend=false
    - terraform fmt -check -recursive
    - terraform validate

.plan:
  stage: plan
  image: hashicorp/terraform:1.16.0
  script:
    - cd $TF_ROOT
    - terraform init -backend-config="bucket=terraform-state-${CI_PROJECT_ID}" -backend-config="key=production/terraform.tfstate"
    - terraform plan -out=tfplan
  artifacts:
    paths:
      - $TF_ROOT/tfplan
    expire_in: 7 days
  resource_group: ${CI_PROJECT_NAME}-plan

plan-staging:
  extends: .plan
  variables:
    ENVIRONMENT: "staging"
  resource_group: ${CI_PROJECT_NAME}-staging-plan

.apply:
  stage: apply
  image: hashicorp/terraform:1.16.0
  script:
    - cd $TF_ROOT
    - terraform apply -auto-approve tfplan
  resource_group: ${CI_PROJECT_NAME}-apply

apply-staging:
  extends: .apply
  variables:
    ENVIRONMENT: "staging"
  needs: ["plan-staging"]
  when: manual

notify:
  stage: apply
  image: curlimages/curl:8.8.0
  script:
    - curl -X POST "$SLACK_WEBHOOK" -H "Content-Type: application/json" \
      -d "{\"text\":\"Infrastructure deployed to ${ENVIRONMENT}\"}"
  needs: ["apply-staging"]
```

### Сценарий 9: OpenTofu с нативным S3 locking

```yaml
variables:
  TF_ROOT: ${CI_PROJECT_DIR}/terraform
  TF_STATE_BUCKET: "terraform-state-${CI_PROJECT_ID}"

stages:
  - validate
  - plan
  - apply

plan:
  stage: plan
  image: opentofu/opentofu:1.12.6
  script:
    - cd $TF_ROOT
    - tofu init \
        -backend-config="bucket=${TF_STATE_BUCKET}" \
        -backend-config="key=production/terraform.tfstate" \
        -backend-config="use_lockfile=true"
    - tofu plan -out=tfplan -no-color
  artifacts:
    paths:
      - $TF_ROOT/tfplan
    expire_in: 7 days

apply:
  stage: apply
  image: opentofu/opentofu:1.12.6
  script:
    - cd $TF_ROOT
    - tofu apply -no-color -auto-approve tfplan
  only:
    - main
  when: manual
  resource_group: ${CI_PROJECT_NAME}-production
```

## Валидация и проверка

1. **Plan output:** Проверьте output `terraform plan` — должен отображаться корректный план изменений.
2. **State lock:** Проверьте, что state lock работает — параллельные запуски через `resource_group` должны блокироваться.
3. **Drift detection:** Запустите drift detection по расписанию и проверьте алерты.
4. **Workspace:** Проверьте, что workspaces создаются корректно для каждого окружения.
5. **Backend:** Проверьте connectivity к backend — `terraform init` должен завершаться без ошибок.
6. **Secrets masking:** Проверьте, что чувствительные переменные не отображаются в логах (`masked: true`).

## Устранение неполадок

| Проблема | Возможная причина | Решение |
| :--- | :--- | :--- |
| State lock timeout | Другой apply всё ещё выполняется | Увеличьте `lock_timeout` в backend config или используйте `resource_group` |
| Drift detection не находит drift | `-refresh-only` не обновляет state | Используйте `terraform plan -detailed-exitcode` |
| Workspace не создаётся | Нет прав на workspace | Проверьте `terraform workspace` permissions |
| Backend initialization fails | Неверные credentials к backend | Проверьте IAM/Service Account permissions или TLS-сертификаты |
| Force-unlock required | State lock завис после падения apply | `terraform force-unlock <LOCK_ID>` (используйте осторожно) |
| HTTP backend 423 Locked | Другой процесс держит lock | Дождитесь освобождения lock или проверьте endpoint |
| Consul session expired | Сессия Consul истекла во время apply | Увеличьте `lock_timeout` или проверьте connectivity к Consul |
| etcd lock lost | Потеряна связь с etcd | Проверьте firewall и сертификаты etcd |

## Best Practices

### Разработка (Dev)

1. **Версионируйте state:** Включите versioning для remote backend для возможности отката.
2. **Шифруйте state:** Всегда используйте шифрование (TLS для Consul/etcd, SSE для S3-compatible).
3. **Используйте workspaces для environments:** `dev`, `staging`, `production` — отдельные workspaces.
4. **Тестируйте drift detection:** Запускайте drift detection по расписанию (weekly) для early detection.
5. **Используйте `-out=tfplan`:** Сохраняйте план в артефакт для аудита.

### Эксплуатация (DevOps/SRE)

1. **Автоматизируйте drift detection:** Запускайте drift detection по расписанию (weekly).
2. **Алерты на drift:** Настройте алерты в Slack/PagerDuty при обнаружении drift.
3. **Мониторьте state locking:** Алерт при timeout'ах блокировки.
4. **Резервное копирование state:** Регулярно бэкапите state-файл.
5. **Используйте `resource_group`:** Гарантируйте, что parallel deployments в одну среду невозможны.

### Sysadmin

1. **Ограничьте доступ к backend:** Только CI/CD service account имеет права на state.
2. **Настройте retention для state versions:** Удаляйте старые версии state (например, >90 дней).
3. **Аудит изменений state:** Включите audit logging для backend.
4. **Настройте TLS:** Для Consul/etcd/HTTP backend используйте только TLS.
5. **Мониторьте backend availability:** Алерт при недоступности Consul/etcd/K8s API.

## Ограничения и крайние случаи

### Ограничения IaC в GitLab CI

*   **State lock при long-running apply:** Длительные `terraform apply` (>30 минут) могут вызывать таймауты в GitLab Runner. Решение: увеличение `timeout` в job, использование `resource_group`, или split apply на несколько stage.
*   **Workspace naming conflicts:** OpenTofu/Terraform запрещают невалидные workspace names. Валидация имени workspace должна происходить до `terraform workspace select`.
*   **Concurrent apply protection:** Только один `resource_group` на среду. Для разных проектов, работающих с одним backend, требуется внешний координатор (Consul lock, etcd).
*   **State file size:** Большие state-файлы (>100 МБ) замедляют `plan` и `apply`. Решение: разделение на модули и workspaces.
*   **Provider plugin caching:** Повторная загрузка провайдеров на каждом job замедляет пайплайн. Решение: GitLab CI caching для `.terraform` directory.

### Типичные ошибки

*   **Hardcoded backend config:** Хранение bucket names и regions в коде. Решение: переменные окружения.
*   **Local backend в CI:** Использование `local` backend в CI приводит к тому, что state теряется между job. Решение: всегда remote backend.
*   **Отсутствие `resource_group`:** Параллельные deployments в production могут вызвать state corruption. Решение: `resource_group` на apply stage.
*   **Manual changes в production:** Прямые изменения через cloud console/SSH приводят к drift. Решение: строгая политика "все изменения через IaC".

## Очистка

```bash
# Удаление resources через Terraform
cd terraform && terraform destroy -var-file="production.tfvars" -auto-approve

# Очистка orphaned resources
terraform state list | while read resource; do
  if ! terraform state show $resource > /dev/null 2>&1; then
    echo "Removing orphaned state: $resource"
    terraform state rm $resource
  fi
done

# Удаление workspace
terraform workspace delete production

# Очистка GitLab CI artifacts и кэша
gitlab-runner cache clear
```

## Дополнительная информация

### См. также

*   **[Terraform и GitLab CI интеграция](../Tutorials/terraform_gitlab_ci_integration.md)** — практическое руководство по Terraform в GitLab CI
*   **[Policy-as-Code в GitLab CI](../Advanced/policy_as_code.md)** — OPA, Checkov, TFLint, Trivy
*   **[Infrastructure as Code — обзор](../../../Concepts/iac_overview.md)** — теория IaC, паттерны, практики
*   **[GitLab CI/CD Security Hardening](../Advanced/cicd_security_hardening.md)** — защита CI/CD
*   **[Resource group и управление пайплайном](../Advanced/resource_group_and_pipeline_control.md)** — предотвращение параллельных deployments

### Внешние ресурсы

*   [Terraform State Locking](https://developer.hashicorp.com/terraform/language/state/locking)
*   [Terraform Drift Detection](https://developer.hashicorp.com/terraform/tutorials/state/resource-drift)
*   [OpenTofu Documentation](https://opentofu.org/docs/)
*   [OpenTofu S3 Backend](https://opentofu.org/docs/language/settings/backends/s3)
*   [Terraform HTTP Backend](https://developer.hashicorp.com/terraform/language/v1.16.x/backend/http)
