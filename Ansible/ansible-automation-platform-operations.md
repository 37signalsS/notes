# Ansible Automation Platform: операционные сценарии и API

> **Связанные документы:** [AAP: архитектура и настройка](./ansible-automation-platform.md) | [Execution Environments](./ansible-execution-environments.md) | [Event-Driven Ansible](./event-driven-ansible.md)

## Определения

**RBAC (Role-Based Access Control)** — модель управления доступом, основанная на ролях пользователей внутри иерархии Organizations → Teams → Users.

**Webhook Trigger** — механизм автоматического запуска Job Template по внешнему HTTP-событию (push в Git, alert из мониторинга).

**REST API v2** — программный интерфейс AAP/AWX для полного управления платформой (запуск, мониторинг, настройка).

**Platform Gateway** — единая точка входа для всех API-запросов в AAP 2.6+. Маршрутизирует трафик к Automation Controller, Automation Hub и Event-Driven Ansible Controller.

**Receptor Mesh** — распределённая сеть для маршрутизации заданий между Control Plane и Execution Nodes с TLS-шифрованием.

**ansible.platform collection** — unified Configuration as Code (CaC) интерфейс для AAP 2.7+, позволяет управлять платформой через декларативные плейбуки.

**Approval Node** — узел в Workflow, требующий ручного подтверждения перед продолжением выполнения.

**Survey** — интерактивная форма для ввода `extra_vars` перед запуском Job Template.

## 1. Job Templates: жизненный цикл

Запуск задания в AAP/AWX проходит через несколько стадий:

| Стадия | Описание | Что происходит |
| :--- | :--- | :--- |
| **Pending** | Задание поставлено в очередь | Ожидание освобождения ресурсов в Execution Node |
| **Waiting** | Ожидание зависимостей | Завершение предыдущих шагов Workflow или обновление проекта |
| **Running** | Выполнение плейбука | Запуск внутри Execution Environment (EE) |
| **Completed** | Финальное состояние | Successful или Failed, логи сохраняются в БД |

**Примеры состояний через API:**
```bash
curl -s "$AWX_HOST/api/v2/jobs/$JOB_ID/" \
  -H "Authorization: Bearer $AWX_TOKEN" | jq '.status'
# → "pending" / "waiting" / "running" / "successful" / "failed" / "error"
```

## 2. Projects: Git-источники кода

Project в AAP/AWX — это Git-репозиторий (или подписка на коллекции), содержащий плейбуки, роли, файлы и переменные.

**Типы проектов:**
- **Git** — основной источник (GitHub, GitLab, Bitbucket, internal Git)
- **Red Hat Automation Hub** — certified коллекции
- **Galaxy** — community коллекции

**Настройка Project:**
1. **Credentials** — Git-токен или SSH-ключ для доступа к репозиторию
2. **SCM Type** — Git, Mercurial
3. **SCM URL** — `https://github.com/org/repo.git`
4. **SCM Branch** — `main`, `develop`, `release/*`
5. **SCM Clean on Update** — очистка перед синхронизацией
6. **Update on Launch** — автоматическое обновление при каждом запуске Job Template

**Команды синхронизации:**
```bash
# Ручная синхронизация через API
curl -X POST "$AWX_HOST/api/v2/projects/$PROJECT_ID/update/" \
     -H "Authorization: Bearer $AWX_TOKEN"

# Проверка статуса
curl "$AWX_HOST/api/v2/projects/$PROJECT_ID/" \
     -H "Authorization: Bearer $AWX_TOKEN" | jq '.status'
# → "successful"
```

## 3. Inventory Sources: динамический инвентарь

Inventory Source позволяет автоматически загружать хосты из внешних систем:

| Источник | Тип | Примеры переменных |
| :--- | :--- | :--- |
| **Satellite/Foreman** | Динамический | `id`, `hostgroup`, `environment` |
| **LDAP** | Динамический | `uid`, `cn`, `memberOf` |
| **Static YAML/INI** | Статический | Ручное определение хостов |
| **Script** | Статический | Вывод JSON/YAML из скрипта |

**Пример Inventory Source для Satellite:**
```yaml
name: Red Hat Satellite
source: satellite
credentials:
  - name: Satellite Admin
    credential_type: Red Hat Satellite
source_filter: "hostgroup = web_servers"
update_on_launch: true
```

## 4. Workflows: визуальный редактор связей

Workflows позволяют строить сложные сценарии оркестрации:

*   **Узлы (Nodes):** Могут быть Job Templates, Inventory Syncs, Project Updates.
*   **Связи:**
    *   `On Success` (зеленая линия) — переход, если предыдущий шаг завершен успешно.
    *   `On Failure` (красная линия) — обработка ошибок (например, откат изменений или уведомление в Slack).
    *   `Always` (синяя линия) — выполнение независимо от результата (например, сбор логов).
*   **Approval Nodes:** Узлы, требующие ручного подтверждения администратором перед продолжением процесса.

**Пример Workflow: Deploy → Verify → Notify:**
```
[Deploy App] ──On Success──> [Verify Health] ──On Success──> [Notify Success]
        │                            │
        └──On Failure──> [Rollback] ──Always──> [Notify Failure]
```

**Пример Workflow с Approval:**
```
[Run Tests] ──On Success──> [Approval Node] ──On Success──> [Deploy to Production]
                                     │
                                     └──On Rejected──> [Notify Rejection]
```

**Workflow через API:**
```bash
# Создание Workflow
curl -X POST "$AWX_HOST/api/v2/workflow_job_templates/" \
     -H "Authorization: Bearer $AWX_TOKEN" \
     -H "Content-Type: application/json" \
     -d '{
       "name": "CI/CD Pipeline",
       "description": "Автоматический деплой при коммите в main",
       "ask_variables_on_launch": true
     }'

# Добавление ноды в Workflow
curl -X POST "$AWX_HOST/api/v2/workflow_job_templates/$WF_ID/workflow_nodes/" \
     -H "Authorization: Bearer $AWX_TOKEN" \
     -H "Content-Type: application/json" \
     -d '{
       "unified_job_template": $JOB_TEMPLATE_ID,
       "identifier": "deploy-node",
       "all_parents_must_converge": false
     }'

# Связывание нод
curl -X POST "$AWX_HOST/api/v2/workflow_nodes/$NODE_ID/success_nodes/" \
     -H "Authorization: Bearer $AWX_TOKEN" \
     -H "Content-Type: application/json" \
     -d '{"id": $NEXT_NODE_ID}'
```

## 5. Surveys: интерактивные опросы

Опросы позволяют абстрагировать технические детали от конечного пользователя:

*   **Типы полей:** Text, Password, Multiple Choice, Integer, Float, Textarea.
*   **Валидация:** Можно задать регулярные выражения для проверки вводимых данных.
*   **Переменные:** Введенные значения передаются в плейбук как `extra_vars`.
*   **Default values:** Значения по умолчанию, предзаполняемые форму.
*   **Required:** Обязательные и опциональные поля.

**Пример Survey для деплоя:**
```yaml
name: Deploy Application
description: "Выберите окружение и версию для деплоя"
spec:
  - question_name: "Окружение"
    variable: target_env
    type: multiplechoice
    choices:
      - "Development"
      - "Staging"
      - "Production"
    default: "Development"
    required: true

  - question_name: "Версия приложения"
    variable: app_version
    type: text
    default: "latest"
    required: true
    min_length: 1
    max_length: 50

  - question_name: "Количество реплик"
    variable: replica_count
    type: integer
    default: "2"
    min: 1
    max: 10
    required: true

  - question_name: "Комментарий к деплою"
    variable: deploy_comment
    type: textarea
    required: false
```

## 6. Credentials: типы и инжект

AAP/AWX поддерживает несколько типов credential:

| Тип | Назначение | Инжект переменных |
| :--- | :--- | :--- |
| **Machine** | SSH-доступ к managed nodes | `ANSIBLE_PRIVATE_KEY_FILE`, `ANSIBLE_USER` |
| **Vault** | Пароль для `ansible-vault` | Флаг `--ask-vault-pass` / `--vault-id <id>@prompt` и ответ на prompt процесса |
| **SCM** | Git-доступ к проектам | `GIT_TOKEN`, `GIT_SSH_KEY` |
| **Network** | Сетевое оборудование | Нет (используется `network_cli`) |
| **Custom** | Внешние API | Пользовательские переменные через Injector |

**Пример Injector Configuration:**
```yaml
# Injector: переменные окружения
env:
  MONITORING_API_TOKEN: "{{ api_token }}"
  SLACK_WEBHOOK_URL: "{{ slack_webhook }}"

# Injector: файлы (например, SSH-ключ)
file:
  template: "{{ private_key }}"
  path: "/tmp/ssh_key"
  mode: "0600"

# Injector: extra_vars
# Примечание: credential типа Vault не использует инжекторы extra_vars —
# его пароль передаётся через --ask-vault-pass. Пример для Custom типа.
extra_vars:
  api_region: "{{ region }}"
  api_endpoint: "{{ scheme }}://{{ host }}"
```

**Пример кастомного Credential Type (API мониторинга):**
1.  **Input Configuration (YAML):**
    ```yaml
    fields:
      - id: api_token
        type: string
        label: Service API Token
        secret: true
    ```
2.  **Injector Configuration (YAML):**
    ```yaml
    env:
      MONITORING_API_TOKEN: "{ {api_token} }"
    ```

## 7. Notifications: уведомления

AAP/AWX поддерживает интеграцию с внешними системами уведомлений:

| Тип | Настройка | Пример |
| :--- | :--- | :--- |
| **Email** | SMTP-сервер, порт, логин/пароль | Отправка отчётов о запусках |
| **Slack** | Webhook URL канала | Уведомления о деплое |
| **PagerDuty** | Service Key | Алерты о критических ошибках |
| **Webhook** | URL + Headers | Интеграция с внешними системами |
| **GitHub** | Token + Repository | Автоматические комментарии к PR |

**Пример Notification Template (Slack):**
```yaml
name: Slack Deploy Notifications
notification_type: slack
configuration:
  token: "xoxb-..."
  channels:
    - "#deployments"
    - "#devops"
```

**Пример Notification Template (Webhook):**
```yaml
name: Custom Webhook
notification_type: webhook
configuration:
  url: "https://monitoring.example.com/api/ansible-events"
  headers:
    Authorization: "Bearer $MONITORING_TOKEN"
    Content-Type: "application/json"
```

**Настройка уведомлений на Job Template:**
```bash
# Привязка Notification Template к Job Template
curl -X POST "$AWX_HOST/api/v2/job_templates/$JT_ID/notification_templates_success/" \
     -H "Authorization: Bearer $AWX_TOKEN" \
     -H "Content-Type: application/json" \
     -d '{"id": $NOTIF_ID}'

# Привязка к Workflow
curl -X POST "$AWX_HOST/api/v2/workflow_job_templates/$WF_ID/notification_templates_success/" \
     -H "Authorization: Bearer $AWX_TOKEN" \
     -H "Content-Type: application/json" \
     -d '{"id": $NOTIF_ID}'
```

## 8. Schedules: расписание запусков

Scheduler позволяет настроить автоматический запуск Job Templates или Workflow Job Templates по cron-расписанию:

**Примеры расписаний:**
```bash
# Ежедневно в 02:00
0 2 * * *

# Каждые 4 часа в будни
0 */4 * * 1-5

# Первый понедельник месяца в 09:00
0 9 1-7 * 1

# Каждые 30 минут с 08:00 до 20:00
*/30 8-20 * * *
```

**Настройка Schedule через API:**
```bash
curl -X POST "$AWX_HOST/api/v2/schedules/" \
     -H "Authorization: Bearer $AWX_TOKEN" \
     -H "Content-Type: application/json" \
     -d '{
       "name": "Nightly Security Scan",
       "unified_job_template": $JOB_TEMPLATE_ID,
       "rrule": "DTSTART:20240101T020000Z RRULE:FREQ=DAILY;INTERVAL=1",
       "enabled": true
     }'
```

**Привязка расписания к Job Template:**
```bash
# Через API
curl -X POST "$AWX_HOST/api/v2/job_templates/$JT_ID/schedules/" \
     -H "Authorization: Bearer $AWX_TOKEN" \
     -H "Content-Type: application/json" \
     -d '{"id": $SCHEDULE_ID}'
```

## 9. Webhook Triggers: автоматический запуск

AAP/AWX может автоматически запускать Job Templates по внешним событиям (webhooks):

**Типы webhook:**
- **GitHub** — push, pull_request, release
- **GitLab** — push, merge request
- **Generic Webhook** — любой HTTP POST

**Настройка Webhook для GitHub:**
1. В AAP/AWX: Job Templates → Webhook → Enable
2. Copy Webhook URL: `$AWX_HOST/api/v2/job_templates/$ID/github/`
3. В GitHub: Settings → Webhooks → Add webhook
4. Payload URL: скопированный URL
5. Content type: `application/json`
6. Secret: установить общий секрет
7. Events: выбрать `push`, `pull_request`

**Пример payload от GitHub:**
```json
{
  "ref": "refs/heads/main",
  "repository": {
    "full_name": "org/ansible-playbooks"
  },
  "pusher": {
    "name": "devops-user"
  },
  "head_commit": {
    "message": "Update nginx configuration"
  }
}
```

**Generic Webhook (внешние системы):**
```bash
# Отправка webhook из мониторинга
curl -X POST "$AWX_HOST/api/v2/job_templates/$JT_ID/github/" \
     -H "Content-Type: application/json" \
     -H "X-Webhook-Secret: $SECRET" \
     -d '{
       "ref": "refs/heads/main",
       "repository": {"full_name": "org/alerts"},
       "pusher": {"name": "prometheus"},
       "head_commit": {"message": "High CPU alert"}
     }'
```

## 10. REST API: интеграция и автоматизация

AAP/AWX предоставляет REST API v2 для полного управления платформой:

**Аутентификация:**
```bash
# OAuth2 Token (рекомендуется)
curl -H "Authorization: Bearer $AWX_TOKEN" "$AWX_HOST/api/v2/me/"

# Basic Auth (устаревший)
curl -u "admin:password" "$AWX_HOST/api/v2/me/"
```

**Основные endpoints:**
| Endpoint | Метод | Описание |
| :--- | :--- | :--- |
| `/api/v2/job_templates/` | GET | Список шаблонов заданий |
| `/api/v2/job_templates/$ID/launch/` | POST | Запуск шаблона |
| `/api/v2/jobs/` | GET | Список выполненных заданий |
| `/api/v2/inventories/` | GET | Список инвентарей |
| `/api/v2/projects/` | GET | Список проектов |
| `/api/v2/credentials/` | GET | Список credential |
| `/api/v2/workflow_job_templates/` | GET | Список workflow-шаблонов |
| `/api/v2/schedules/` | GET | Список расписаний |
| `/api/v2/notifications/` | GET | Список уведомлений |

**Примеры API-вызовов:**

```bash
# Запуск Job Template с параметрами
curl -X POST "$AWX_HOST/api/v2/job_templates/$ID/launch/" \
     -H "Authorization: Bearer $AWX_TOKEN" \
     -H "Content-Type: application/json" \
     -d '{
       "extra_vars": {
         "target_env": "staging",
         "app_version": "2.1.0"
       },
       "inventory": $INVENTORY_ID,
       "credentials": [$CREDENTIAL_ID],
       "limit": "web_servers"
     }'

# Проверка статуса запуска
curl "$AWX_HOST/api/v2/jobs/$JOB_ID/" \
     -H "Authorization: Bearer $AWX_TOKEN" | jq '.status, .started, .finished'
# → "successful"
# → "2024-01-15T10:30:00Z"
# → "2024-01-15T10:32:15Z"

# Получение логов запуска
curl "$AWX_HOST/api/v2/jobs/$JOB_ID/stdout/?format=txt" \
     -H "Authorization: Bearer $AWX_TOKEN"

# Синхронизация инвентаря
curl -X POST "$AWX_HOST/api/v2/inventories/$INV_ID/update_inventory/" \
     -H "Authorization: Bearer $AWX_TOKEN"

# Создание Workflow Job Template
curl -X POST "$AWX_HOST/api/v2/workflow_job_templates/" \
     -H "Authorization: Bearer $AWX_TOKEN" \
     -H "Content-Type: application/json" \
     -d '{
       "name": "CI/CD Pipeline",
       "description": "Автоматический деплой при коммите в main",
       "ask_variables_on_launch": true
     }'
```

**Автоматизация RBAC через ansible.controller:**
```yaml
# Создание команды
- name: Create DevOps Team
  ansible.controller.team:
    name: "DevOps"
    description: "Team for DevOps engineers"
    organization: "Production"
    state: present

# Назначение роли на Job Template
- name: Grant Execute Role
  ansible.controller.role:
    team: "DevOps"
    role: "execute"
    job_template: "Deploy Application"
    state: present

# Назначение credential на команду
- name: Grant Credential Access
  ansible.controller.credential:
    credential: "Production SSH Key"
    team: "DevOps"
    state: present
```

## 11. Автоматизация деплоя через Webhook

**Сценарий:** При пуше в ветку `main` автоматически запускается деплой в staging, а при релизе — в production.

**Настройка:**
1. **Job Template "Deploy to Staging":**
   - Project: Git-репозиторий с плейбуками
   - Playbook: `playbooks/deploy.yml`
   - Inventory: `Staging`
   - Credentials: SSH-ключ + Vault-пароль
   - Survey: выбор ветки/версии

2. **Job Template "Deploy to Production":**
   - Проект и плейбук аналогичны
   - Inventory: `Production`
   - Approval Node: требует ручного подтверждения

3. **Workflow:**
```
[GitHub Webhook] ──On Success──> [Deploy Staging] ──On Success──> [Approval] ──On Success──> [Deploy Production]
```

## 12. Backup и восстановление AAP

**Бэкап PostgreSQL:**
```bash
# Бэкап БД (AAP 2.7)
sudo podman exec -t awx-postgres pg_dumpall -U awx > awx_backup_$(date +%Y%m%d).sql

# Бэкап через AAP CLI (AAP 2.7+)
awx-manage export_data > data_export_$(date +%Y%m%d).json
```

**Восстановление:**
```bash
# Восстановление БД
cat awx_backup_20240115.sql | sudo podman exec -i awx-postgres psql -U awx

# Восстановление через AAP CLI
awx-manage import_data < data_export_20240115.json
```

**Автоматический бэкап (cron):**
```bash
# /etc/cron.d/awx-backup
0 2 * * * root /opt/awx-backup.sh >> /var/log/awx-backup.log 2>&1
```

## Смотрите также

*   **[AAP: архитектура и настройка](./ansible-automation-platform.md)** — архитектура, определения, установка, оптимизация.
*   **[Execution Environments](./ansible-execution-environments.md)** — сборка и настройка EE для AAP/AWX.
*   **[Event-Driven Ansible](./event-driven-ansible.md)** — action `run_job_template` для интеграции EDA с AAP.
*   **[Identity Management и RBAC](./ansible-identity-management.md)** — автоматизация управления командами и ролями.
*   **[Сравнение: AWX vs Semaphore](./ansible_semaphore.md)** — альтернативные решения.

---

## Multi-team RBAC Governance: Production/Staging workflows

### Архитектура доступа по командам

```
Organization: "Production Org"
├── Team: "Platform Engineers"
│   ├── Role: Admin (всё)
│   ├── Credentials: Production SSH, Vault
│   └── Inventories: Production, Staging
│
├── Team: "Backend Developers"
│   ├── Role: Execute (Job Templates)
│   ├── Credentials: Staging SSH
│   ├── Inventories: Staging
│   ├── Job Templates: Deploy Backend, Run Migrations
│   └── Deny: Production deploy
│
├── Team: "SRE On-Call"
│   ├── Role: Execute + Read
│   ├── Credentials: Production SSH (read-only)
│   ├── Inventories: Production
│   ├── Job Templates: Health Checks, Incident Response
│   └── Approval: Production remediation
│
└── Team: "Junior DevOps"
    ├── Role: Read (только просмотр)
    ├── Credentials: Staging SSH
    ├── Inventories: Staging
    └── Deny: Production, Credentials view
```

### Автоматизация RBAC через ansible.controller

```yaml
---
- name: Configure multi-team RBAC governance
  hosts: localhost
  connection: local
  gather_facts: false
  vars:
    awx_url: "https://aap.internal"
    awx_token: "{{ vault_awx_token }}"
    org_name: "Production Org"
  tasks:
    # ==================== Organizations ====================
    - name: Create Organization
      ansible.controller.organization:
        name: "{{ org_name }}"
        description: "Main organization for production workloads"
        state: present
        controller_host: "{{ awx_url }}"
        controller_username: admin
        controller_password: "{{ vault_awx_admin_pass }}"

    # ==================== Teams ====================
    - name: Create Platform Engineers team
      ansible.controller.team:
        name: "Platform Engineers"
        description: "Full access to all environments"
        organization: "{{ org_name }}"
        state: present

    - name: Create Backend Developers team
      ansible.controller.team:
        name: "Backend Developers"
        description: "Staging deploy only"
        organization: "{{ org_name }}"
        state: present

    - name: Create SRE On-Call team
      ansible.controller.team:
        name: "SRE On-Call"
        description: "Incident response and health checks"
        organization: "{{ org_name }}"
        state: present

    - name: Create Junior DevOps team
      ansible.controller.team:
        name: "Junior DevOps"
        description: "Read-only access for learning"
        organization: "{{ org_name }}"
        state: present

    # ==================== Credentials ====================
    - name: Create Production SSH credential
      ansible.controller.credential:
        name: "Production SSH Key"
        credential_type: "Machine"
        organization: "{{ org_name }}"
        inputs:
          sshkey_data: "{{ vault_production_ssh_key }}"
        state: present

    - name: Create Staging SSH credential
      ansible.controller.credential:
        name: "Staging SSH Key"
        credential_type: "Machine"
        organization: "{{ org_name }}"
        inputs:
          sshkey_data: "{{ vault_staging_ssh_key }}"
        state: present

    # ==================== Inventories ====================
    - name: Create Production inventory
      ansible.controller.inventory:
        name: "Production"
        organization: "{{ org_name }}"
        description: "Production environment - 500+ servers"
        state: present

    - name: Create Staging inventory
      ansible.controller.inventory:
        name: "Staging"
        organization: "{{ org_name }}"
        description: "Staging environment - mirrors production"
        state: present

    # ==================== Job Templates ====================
    - name: Create Deploy to Staging template
      ansible.controller.job_template:
        name: "Deploy to Staging"
        project: "Ansible Playbooks"
        playbook: "playbooks/deploy.yml"
        inventory: "Staging"
        credential: "Staging SSH Key"
        ask_variables_on_launch: true
        state: present

    - name: Create Deploy to Production template
      ansible.controller.job_template:
        name: "Deploy to Production"
        project: "Ansible Playbooks"
        playbook: "playbooks/deploy.yml"
        inventory: "Production"
        credential: "Production SSH Key"
        ask_variables_on_launch: true
        survey_enabled: true
        survey_spec: "{{ production_survey }}"
        state: present

    - name: Create Incident Response template
      ansible.controller.job_template:
        name: "Incident Response"
        project: "Ansible Playbooks"
        playbook: "playbooks/incident_response.yml"
        inventory: "Production"
        credential: "Production SSH Key"
        ask_limit_on_launch: true
        state: present

    # ==================== RBAC Roles ====================

    # Platform Engineers: полный доступ
    - name: PE - Admin on Organization
      ansible.controller.role:
        team: "Platform Engineers"
        role: "admin"
        organization: "{{ org_name }}"
        state: present

    # Backend Developers: только staging
    - name: BD - Execute on Deploy to Staging
      ansible.controller.role:
        team: "Backend Developers"
        role: "execute"
        job_template: "Deploy to Staging"
        state: present

    - name: BD - Read on Staging inventory
      ansible.controller.role:
        team: "Backend Developers"
        role: "use"
        inventory: "Staging"
        state: present

    - name: BD - Use Staging credential
      ansible.controller.role:
        team: "Backend Developers"
        role: "use"
        credential: "Staging SSH Key"
        state: present

    - name: BD - No access to Production
      ansible.controller.role:
        team: "Backend Developers"
        role: "read"
        inventory: "Production"
        state: absent  # Явный запрет

    # SRE On-Call: incident response + approval
    - name: SRE - Execute on Incident Response
      ansible.controller.role:
        team: "SRE On-Call"
        role: "execute"
        job_template: "Incident Response"
        state: present

    - name: SRE - Read on Production
      ansible.controller.role:
        team: "SRE On-Call"
        role: "read"
        inventory: "Production"
        state: present

    - name: SRE - Approve on Production Deploy
      ansible.controller.role:
        team: "SRE On-Call"
        role: "approve"
        workflow: "Production Deploy Pipeline"
        state: present

    # Junior DevOps: только чтение staging
    - name: Junior - Read on Staging
      ansible.controller.role:
        team: "Junior DevOps"
        role: "read"
        inventory: "Staging"
        state: present

    - name: Junior - Use Staging credential (read-only)
      ansible.controller.role:
        team: "Junior DevOps"
        role: "read"
        credential: "Staging SSH Key"
        state: present
```

### Workflow с Approval для Production

```yaml
---
- name: Create Production Deploy Pipeline with approval
  hosts: localhost
  connection: local
  gather_facts: false
  tasks:
    - name: Create Workflow
      ansible.controller.workflow_job_template:
        name: "Production Deploy Pipeline"
        organization: "Production Org"
        ask_variables_on_launch: true
        state: present

    - name: Add Staging Deploy node
      ansible.controller.workflow_job_template_node:
        workflow: "Production Deploy Pipeline"
        unified_job_template: "Deploy to Staging"
        success_nodes:
          - "Approval Node"

    - name: Add Approval node
      ansible.controller.workflow_job_template_node:
        workflow: "Production Deploy Pipeline"
        unified_job_template: "Approval for Production"
        identifier: "approval-node"
        success_nodes:
          - "Deploy to Production"

    - name: Add Production Deploy node
      ansible.controller.workflow_job_template_node:
        workflow: "Production Deploy Pipeline"
        unified_job_template: "Deploy to Production"
        identifier: "deploy-production"
```

### Синхронизация LDAP-групп с AAP командами

```yaml
---
- name: Sync LDAP groups to AAP teams
  hosts: localhost
  connection: local
  gather_facts: false
  vars:
    ldap_server: "ldap://ldap.internal"
    ldap_base_dn: "dc=example,dc=com"
    ldap_bind_dn: "cn=ansible,dc=example,dc=com"
    ldap_bind_password: "{{ vault_ldap_password }}"
  tasks:
    - name: Query LDAP for DevOps team members
      community.general.ldap_search:
        server_uri: "{{ ldap_server }}"
        bind_dn: "{{ ldap_bind_dn }}"
        bind_pw: "{{ ldap_bind_password }}"
        base_dn: "{{ ldap_base_dn }}"
        scope: "subordinate"
        filter: "(memberOf=cn=devops,ou=groups,dc=example,dc=com)"
        attrs:
          - uid
          - cn
          - mail
      register: ldap_devops

    - name: Query LDAP for SRE team members
      community.general.ldap_search:
        server_uri: "{{ ldap_server }}"
        bind_dn: "{{ ldap_bind_dn }}"
        bind_pw: "{{ ldap_bind_password }}"
        base_dn: "{{ ldap_base_dn }}"
        scope: "subordinate"
        filter: "(memberOf=cn=sre,ou=groups,dc=example,dc=com)"
        attrs:
          - uid
          - cn
          - mail
      register: ldap_sre

    - name: Sync DevOps team members to AAP
      ansible.controller.user:
        username: "{{ item.uid }}"
        first_name: "{{ item.cn }}"
        email: "{{ item.mail }}"
        state: present
      loop: "{{ ldap_devops.results }}"

    - name: Assign DevOps users to Platform Engineers team
      ansible.controller.role:
        team: "Platform Engineers"
        role: "member"
        user: "{{ item.uid }}"
        state: present
      loop: "{{ ldap_devops.results }}"
```

### Аудит и мониторинг доступа

```yaml
---
- name: Audit RBAC access patterns
  hosts: localhost
  connection: local
  gather_facts: false
  vars:
    awx_url: "https://aap.internal"
    awx_token: "{{ vault_awx_token }}"
  tasks:
    - name: Get all job runs from last 24h
      ansible.builtin.uri:
        url: "{{ awx_url }}/api/v2/jobs/?created__gte={{ (ansible_date_time.date | to_datetime('%Y-%m-%d') - timedelta(days=1)).strftime('%Y-%m-%dT00:00:00Z') }}"
        headers:
          Authorization: "Bearer {{ awx_token }}"
        return_content: true
      register: recent_jobs

    - name: Analyze access patterns
      ansible.builtin.set_fact:
        access_summary: >-
          {% set summary = {} %}
          {% for job in recent_jobs.json.results %}
          {% set user = job.created_by | default('system') %}
          {% set template = job.job_template | default('unknown') %}
          {% if user not in summary %}
          {% set _ = summary.update({user: {'templates': [], 'count': 0}}) %}
          {% endif %}
          {% set _ = summary[user].templates.append(template) %}
          {% set _ = summary.update({user: {'templates': summary[user].templates, 'count': summary[user].count + 1}}) %}
          {% endfor %}
          {{ summary }}

    - name: Detect unusual access patterns
      ansible.builtin.debug:
        msg: >-
          ALERT: User {{ item.key }} executed {{ item.value.count }} jobs
          including: {{ item.value.templates | unique | join(', ') }}
      loop: "{{ access_summary | dict2items }}"
      when: item.value.count > 50 or 'Production Deploy' in item.value.templates

    - name: Send audit report
      ansible.builtin.uri:
        url: "{{ slack_webhook_url }}"
        method: POST
        body_format: json
        body:
          text: |
            AAP RBAC Audit Report ({{ ansible_date_time.date }})
            Total jobs: {{ recent_jobs.json.count }}
            Users active: {{ access_summary | length }}
            {{ access_summary | to_nice_yaml }}
      delegate_to: localhost
```
