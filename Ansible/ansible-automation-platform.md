# Ansible Automation Platform (AAP) и AWX

## Определения

- **Ansible Automation Platform (AAP)** — корпоративная платформа автоматизации от Red Hat, включающая Automation Controller (бывший Ansible Tower), Automation Hub (реестр коллекций), Execution Environments, Event-Driven Ansible Controller и инструменты для разработки, тестирования и анализа. В версии 2.7+ включает Platform Gateway и ansible.platform collection для Configuration as Code.
- **AWX** — проект с открытым исходным кодом, upstream-версия AAP. Включает Web UI, REST API и Execution Environments. Последний стабильный релиз — 24.6.1 (июль 2024), дальнейшая разработка ведётся в ветке `devel`.
- **Automation Controller (Контроллер автоматизации)** — серверная часть платформы: оркестрация запусков, управление инвентарём, credential-хранилище, RBAC и REST API. Бывший Ansible Tower. В AAP 2.7 — версия 4.8.x.
- **Automation Hub** — частный реестр Ansible-коллекций с сертифицированными Red Hat коллекциями, версионированием и signed-артефактами. В AAP 2.7 — версия 4.12.x.
- **Job Template (Шаблон задания)** — описание запуска плейбука: инвентарь + credentials + проект + Execution Environment + плейбук. Запускается через API или Web UI.
- **Workflow Job Template (Шаблон рабочего процесса)** — цепочка Job Templates с логическими условиями (On Success/Failure/Always) и Approval Nodes.
- **Surveys (Опросы)** — интерактивные формы для ввода `extra_vars` перед запуском шаблона.
- **Inventory Source (Источник инвентаря)** — конфигурация автоматической загрузки хостов из внешних систем (Satellite, Foreman, LDAP, Static, Script).
- **Project (Проект)** — Git-репозиторий с плейбуками, ролями и переменными.
- **Credential (Учётные данные)** — защищённое хранилище секретов с механизмом инжекта переменных в Execution Environment.
- **Execution Environment (EE)** — OCI-контейнер с Ansible Core, Python-зависимостями и коллекциями. В AAP 2.7 удалено соглашение `:latest` для минимального EE.
- **Execution Node (Узел выполнения)** — сервер для запуска Execution Environments. Типы: Default (локальный), Execution (выделенный), Hop (промежуточный для маршрутизации).
- **Receptor** — mesh-сеть для маршрутизации заданий между Control Plane и Execution Nodes. Обеспечивает TLS-шифрование, балансировку и отказоустойчивость.
- **Platform Gateway** — единая точка входа для всех API-запросов в AAP 2.6+. Маршрутизирует трафик к Automation Controller, Automation Hub и Event-Driven Ansible Controller.
- **ansible.platform collection** — unified Configuration as Code (CaC) интерфейс для AAP 2.7+. Позволяет управлять платформой через декларативные плейбуки.
- **Notification (Уведомление)** — автоматическая отправка событий (успех/ошибка) во внешние системы.
- **Schedule (Расписание)** — cron-подобный планировщик автоматического запуска заданий.

## Предварительные требования

### Для AAP 2.7 (коммерческое решение)

| Компонент | Минимум | Рекомендация |
| :--- | :--- | :--- |
| **ansible-core** | 2.16+ | 2.21+ |
| **Automation Controller** | 4.8.0 | 4.8.3+ (последний patch) |
| **Automation Hub** | 4.12.0 | 4.12.3+ |
| **Event-Driven Ansible** | 1.3.0 | 1.3.4+ |
| **PostgreSQL** | 12+ (внешний или встроенный) | PostgreSQL 14+ на выделенном сервере |
| **Redis** | 6+ (для очередей) | Redis 7+ кластер |
| **Receptor** | 1.6+ | 1.6.6+ |
| **Podman** | 4.0+ | 4.4+ (rootless) |
| **ОС** | RHEL 8.6+, Ubuntu 22.04+ | RHEL 9+ |
| **Python** (control node) | 3.11+ | 3.14 |
| **ansible.platform** | 2.7.0 | 2.7.0+ |

### Для AWX 24.6.1+ (open-source)

| Компонент | Минимум | Рекомендация |
| :--- | :--- | :--- |
| **ansible-core** | 2.15+ | 2.21+ |
| **Python** | 3.11+ | 3.14 |
| **Podman/Docker** | 4.0+ | Podman 4.4+ (rootless) |
| **PostgreSQL** | 12+ | 14+ |
| **Redis** | 6+ | 7+ |
| **Git** | 2.30+ | 2.40+ |

**Проверка окружения:**
```bash
ansible --version | head -1
# → ansible [core 2.21.x]

ansible-galaxy collection list ansible.platform
# → ansible.platform 2.7.0

podman --version
# → podman version 4.4.x
```

## Основные концепции

### Архитектура AAP 2.x

```
┌─────────────────────────────────────────────────────────────────────┐
│                        CONTROL PLANE                               │
│  ┌──────────────┐  ┌──────────────────┐  ┌──────────────────────┐ │
│  │ Platform     │  │ Automation       │  │ PostgreSQL           │ │
│  │ Gateway      │──│ Controller       │  │ (база данных)        │ │
│  │ (единый API) │  │ (оркестрация)    │  └──────────────────────┘ │
│  └──────┬───────┘  └────────┬─────────┘                             │
│         │            ┌──────┴───────┐                             │
│         │            │ Redis        │                             │
│         │            │ (очереди)    │                             │
│  ┌──────┴──────────────────────────────────────────────────────┐  │
│  │                  Execution Plane                             │  │
│  │  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐         │  │
│  │  │ Receptor    │  │ Receptor    │  │ Receptor    │  ...    │  │
│  │  │ Mesh Node   │◄─│ Mesh Node   │◄─│ Mesh Node   │         │  │
│  │  │ (Hop)       │  │ (Execution) │  │ (Hop)       │         │  │
│  │  └──────┬──────┘  └──────┬──────┘  └──────┬──────┘         │  │
│  │         │                │                │                  │  │
│  │  ┌──────┴──────┐  ┌──────┴──────┐  ┌──────┴──────┐         │  │
│  │  │ EE Container│  │ EE Container│  │ EE Container│  ...    │  │
│  │  └─────────────┘  └─────────────┘  └─────────────┘         │  │
│  └─────────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────────┘
```

**Control Plane:** Platform Gateway, Automation Controller, PostgreSQL, Redis, Automation Hub.
**Execution Plane:** Receptor Mesh Nodes (Hop/Execution), Execution Environments (OCI).

### Receptor Mesh: принцип работы

Receptor реализует mesh-сеть поверх TCP/TLS для маршрутизации заданий между Control Plane и удалёнными Execution Nodes:

1. **Регистрация узлов:** Каждый Execution Node регистрируется в mesh через Receptor Controller на Control Plane.
2. **Маршрутизация:** Задания маршрутизируются через intermediate Hop Nodes, что позволяет строить топологии типа "звезда", "цепочка" или "full mesh".
3. **Шифрование:** Все соединения в mesh шифруются через TLS 1.3 с mTLS-аутентификацией узлов.
4. **Балансировка:** Receptor поддерживает балансировку нагрузки между Execution Nodes в рамках одного типа.
5. **Отказоустойчивость:** При недоступности узла задания автоматически перенаправляются на другие Execution Nodes.

### Platform Gateway (AAP 2.6+)

Platform Gateway — единая точка входа для всех внешних API-запросов. В AAP 2.7 все прямые интеграции с Automation Controller, Automation Hub и Event-Driven Ansible должны маршрутизироваться через Gateway:

- **Преимущества:** централизованный аудит, единая аутентификация, упрощение firewall-правил.
- **Миграция:** Существующие прямые интеграции с API должны быть обновлены для маршрутизации через Gateway.
- **Требования:** NGINX log format с дополнительными полями (обновление для AAP 2.6 patch от 25 марта 2026).

### Сравнение AAP и AWX

| Критерий | AAP 2.7 | AWX 24.6.1+ |
| :--- | :--- | :--- |
| Поддержка | Red Hat 24/7, SLA | Сообщество, нет SLA |
| Certified Collections | Да | Нет |
| Execution Nodes с Receptor | Да | Базовая поддержка |
| Platform Gateway | Да | Нет |
| ansible.platform (CaC) | Да | Нет |
| LDAP/AD / SSO | Полная интеграция | Ограниченная |
| Audit Logging | Расширенный | Базовый |
| Event-Driven Ansible | Да | Нет |
| Стоимость | Платная (подписка) | Бесплатно |
| Развёртывание | RHEL, OpenShift, Ansible installer | Docker/Podman, Kubernetes |

### Жизненный цикл заданий

| Стадия | Описание |
| :--- | :--- |
| **Pending** | В очереди, ожидание ресурсов Execution Node |
| **Waiting** | Завершение зависимостей или обновление проекта |
| **Running** | Выполнение плейбука в Execution Environment |
| **Completed** | Successful/Failed, логи сохраняются в БД |

### Projects: Git-источники кода

Project — Git-репозиторий (GitHub, GitLab, Bitbucket, internal Git) с плейбуками, ролями и переменными.

**Настройка:** Credentials (Git-токен/SSH-ключ), SCM URL, SCM Branch, Update on Launch.

### Inventory Sources: статический и динамический инвентарь

| Источник | Тип | Примеры переменных |
| :--- | :--- | :--- |
| **Satellite/Foreman** | Динамический | `id`, `hostgroup`, `environment` |
| **LDAP** | Динамический | `uid`, `cn`, `memberOf` |
| **Static YAML/INI** | Статический | Ручное определение хостов |
| **Script** | Статический | Вывод JSON/YAML из скрипта |

### Workflows

Workflows объединяют Job Templates, Inventory Syncs и Project Updates в цепочки:

- `On Success` — при успешном завершении
- `On Failure` — при ошибке
- `Always` — независимо от результата
- **Approval Nodes** — ручное подтверждение

### Surveys

Интерактивные формы для ввода `extra_vars` перед запуском. Типы полей: Text, Password, Multiple Choice, Integer, Float, Textarea. Валидация через regex.

### Credentials

| Тип | Назначение | Как передаётся в задание |
| :--- | :--- | :--- |
| **Machine** | SSH-доступ к managed nodes | `ANSIBLE_PRIVATE_KEY_FILE`, `ANSIBLE_USER` |
| **Vault** | Пароль для `ansible-vault` | Не через переменную окружения, а флагом `--ask-vault-pass` / `--vault-id <id>@prompt` и ответом на prompt процесса |
| **SCM** | Git-доступ к проектам | `GIT_TOKEN`, `GIT_SSH_KEY` |
| **Network** | Сетевое оборудование | Нет (используется `network_cli`) |
| **Custom** | Внешние API | Пользовательские переменные через Injector |

Поля типа **Vault**: `vault_password` (обязательное) и `vault_id` (необязательное, для multi-Vault).

> Тип Vault не инжектит `ANSIBLE_VAULT_PASSWORD_FILE`. Механизм другой — см. раздел [Vault Credentials и ansible-vault в AAP/AWX](#vault-credentials-и-ansible-vault-в-aapawx).

### Vault Credentials и ansible-vault в AAP/AWX

Тип credential **Vault** хранит пароль шифрования `ansible-vault`. Поля: `vault_password` (обязательное) и `vault_id` (необязательное — метка для multi-Vault).

#### Как пароль попадает в задание

Механизм не через переменную окружения. Controller модифицирует командную строку `ansible-playbook` и отвечает на prompt процесса:

| Ситуация | Что добавляет Controller к команде | Как отвечает Controller |
| :--- | :--- | :--- |
| Credential без `vault_id` | `--ask-vault-pass` | На строку `Vault password:` подставляет значение `vault_password` |
| Credential с `vault_id` | `--vault-id <vault_id>@prompt` | На строку `Vault password (<vault_id>):` подставляет значение |

Пароль передаётся в процесс через stdin в момент выполнения и не остаётся ни в переменных окружения задания, ни в аргументах командной строки, ни в файле на диске. Плагин Vault credential не имеет инжектора `env`/`file`/`extra_vars` — он обрабатывается отдельно.

Практическое следствие: значение `vault_password` **не доступно в плейбуке как переменная**. Попытка сослаться на него в шаблоне даст `undefined`. Пароль используется только для расшифровки файлов.

#### Prompt on launch и ограничения

Значение `vault_password: "ASK"` включает режим **Prompt on launch**: при запуске задания открывается диалог с полями для ввода пароля и подтверждения. Если задан `vault_id`, поле называется `vault_password.<vault_id>`.

Ограничения:

- **Prompt on launch нельзя использовать в Scheduled Jobs** — у расписания нет интерактивного пользователя, задание упадёт;
- значения `""` и `"ASK"` считаются незаполненными: credential без реального пароля молча не даст расшифровки;
- пароль хранится в базе данных PostgreSQL, зашифрованный AES-256-CBC с HMAC-SHA256; ключ выводится из `/etc/awx/SECRET_KEY`, имени поля и id записи. Потеря или смена `SECRET_KEY` делает все секреты в базе нечитаемыми.

#### Multi-Vault: несколько хранилищ

AWX/AAP поддерживает несколько vault-паролей на одном задании. Создайте отдельный credential **на каждое хранилище** и укажите в поле `vault_id` метку из заголовка файла (`$ANSIBLE_VAULT;1.2;AES256;prod`).

```bash
# Два credential: prod и staging
curl -sk -X POST "https://aap.example.com/api/v2/credentials/" \
  -H "Authorization: Bearer $AAP_TOKEN" -H "Content-Type: application/json" \
  -d '{
    "name": "Vault Prod",
    "credential_type": 4,
    "inputs": {"vault_password": "<REDACTED>", "vault_id": "prod"}
  }' | python3 -m json.tool | rg '"id"'
# → "id": 21

# Привязать к job template 7
curl -sk -X POST "https://aap.example.com/api/v2/job_templates/7/credentials/" \
  -H "Authorization: Bearer $AAP_TOKEN" -H "Content-Type: application/json" \
  -d '{"associate": true, "id": 21}' -o /dev/null -w '%{http_code}\n'
# → 204

# Второй credential — staging
curl -sk -X POST "https://aap.example.com/api/v2/job_templates/7/credentials/" \
  -H "Authorization: Bearer $AAP_TOKEN" -H "Content-Type: application/json" \
  -d '{"associate": true, "id": 22}' -o /dev/null -w '%{http_code}\n'
# → 204
```

Controller преобразует их в `--vault-id prod@prompt --vault-id staging@prompt` и при запросе `Vault password (prod):` подаст нужный пароль.

**Критично важно:** уникальность credential определяется парой «тип + `vault_id`». Два credential без `vault_id` или с одинаковым `vault_id` будут отклонены:

```json
{"error": "Cannot assign multiple Vault credentials."}
```

#### Пароль Vault из внешнего менеджера секретов

Credential типа **Vault** всегда хранит пароль в базе AAP. Если мастер-пароль не должен там лежать, замените хранилище скриптом-источником: credential другого типа (например, HashiCorp Vault Secret Lookup) с инжектом `file` записывает секрет во временный файл, а задание получает путь.

```yaml
# Custom Credential Type: инжект файла, который читает .vault_pass
inputs:
  fields:
    - id: vault_pass
      type: string
      label: Vault password
      secret: true
injectors:
  file:
    template: "{{ vault_pass }}"
  env:
    ANSIBLE_VAULT_PASSWORD_FILE: "{{ tower.filename }}"
```

Схема `vault_identity`, `vault_encrypt_identity` и `ANSIBLE_VAULT_ID_MATCH` в AAP/AWX не настраивается — они остаются на уровне `ansible.cfg` проекта или переменных задания. Полный список опций — в [Ansible Vault: Основы](./Vault/basics.md).

#### Ограничения, о которых стоит знать на собеседовании

| Вопрос | Ответ |
| :--- | :--- |
| Где лежит пароль Vault credential? | В PostgreSQL, зашифрован AES-256-CBC + HMAC-SHA256, ключ из `/etc/awx/SECRET_KEY` |
| Виден ли пароль в `ps` на execution node? | Нет, передаётся через stdin в момент prompt |
| Доступен ли пароль как переменная в плейбуке? | Нет, только для расшифровки |
| Можно ли использовать Prompt on launch в расписании? | Нет, задание упадёт |
| Сколько хранилищ Vault поддерживается? | Несколько, через отдельный credential на каждый `vault_id` |
| Что будет при потере `SECRET_KEY`? | Все зашифрованные поля в базе станут нечитаемыми |

### Execution Environments

OCI-контейнер с Ansible Core, коллекциями и зависимостями. В AAP 2.7 удалено соглашение `:latest` для минимального EE — теперь требуется явное указание версии образа.

Полное руководство по сборке EE — в [Среды выполнения Ansible](./ansible-execution-environments.md).

### Notifications, Schedules, Webhooks и REST API

Подробные примеры — см. [AAP: операционные сценарии и API](./ansible-automation-platform-operations.md).

## Практические сценарии

### Установка AWX через Docker/Podman

```bash
git clone https://github.com/ansible/awx.git && cd awx/tools/docker-compose
mkdir -p pg_data redis_data

cat > .env << EOF
POSTGRES_USER=awx
POSTGRES_PASSWORD=YourStrongPassword
POSTGRES_DB=awx
AWX_ADMIN_USER=admin
AWX_ADMIN_PASSWORD=YourAdminPassword
AWX_SECRET_KEY=$(python3 -c "import secrets; print(secrets.token_hex(32))")
EOF

podman-compose up -d
podman-compose ps
# → awx_web, awx_task, awx_postgres, awx_redis — all Up
```

**Первичная настройка:**
1. Откройте `http://localhost:80`, войдите как `admin` / `YourAdminPassword`
2. Settings → Organizations → Add
3. Resources → Projects → Add (укажите Git-URL)
4. Resources → Inventories → Add (Static или Dynamic)
5. Resources → Credentials → Add (тип Machine)
6. Resources → Job Templates → Add

### Установка через Operator (Kubernetes/OpenShift)

```bash
# Kubernetes (Helm)
helm repo add awx https://ansible.github.io/awx-operator/
helm install awx awx/awx-operator -n awx --create-namespace \
  --set postgres.enabled=true --set postgres.image=postgres:14

# OpenShift (OperatorHub)
oc create namespace awx
oc apply -f - <<EOF
apiVersion: awx.ansible.com/v1beta1
kind: AWX
metadata:
  name: awx
  namespace: awx
spec:
  service_type: LoadBalancer
  ingress_type: Route
  hostname: awx.internal.example.com
EOF
```

### Конфигурация Execution Environments

```bash
cat > execution-environment.yml << EOF
version: 3
build_arg_defaults:
  EE_BASE_IMAGE: "quay.io/ansible/ansible-runner:stable-2.7"
  EE_BUILDER_IMAGE: "quay.io/ansible/ansible-builder:latest"
dependencies:
  python: [requests, pyyaml]
  system: [git-core, openssh-clients]
additional_build_steps:
  append_final:
    - RUN pip3 install --upgrade pip
EOF

ansible-builder build -t my-custom-ee:2.7
```

### Настройка Receptor Mesh

```bash
# На Execution Node (сначала установите receptor):
curl -L https://receptor.example.com/receptor.tar.gz -o receptor.tar.gz
tar xzf receptor.tar.gz

# Конфигурация receptor (receptor.conf)
[receptor]
node_name = execution-node-1
tls_client_cert = /etc/receptor/tls/client.crt
tls_client_key = /etc/receptor/tls/client.key
tls_ca = /etc/receptor/tls/ca.crt
peers = controller-node.example.com:27199

# Запуск receptor
receptor --config /etc/receptor/receptor.conf
```

### Configuration as Code через ansible.platform

```yaml
---
- name: Configure AAP via Configuration as Code
  hosts: localhost
  connection: local
  gather_facts: false
  vars:
    aap_url: "https://aap.internal"
    aap_token: "{{ vault_aap_token }}"
  tasks:
    - name: Create Organization
      ansible.platform.organization:
        name: "Production"
        description: "Production workloads"
        state: present
        controller_host: "{{ aap_url }}"
        controller_token: "{{ aap_token }}"

    - name: Create Execution Node
      ansible.platform.instance:
        name: "execution-node-1"
        node_type: execution
        hostname: "10.0.1.50"
        organization: "Production"
        state: present
```

## Операции и команды

### Управление Execution Environments

Полное руководство по сборке EE — в [Среды выполнения Ansible](./ansible-execution-environments.md).

| Действие | Команда |
| :--- | :--- |
| Сборка EE | `ansible-builder build -t my-ee:2.7` |
| Проверка EE | `ansible-navigator images list` |
| Запуск плейбука в EE | `ansible-navigator run playbook.yml --execution-environment-image my-ee:2.7` |

### Receptor CLI

| Действие | Команда |
| :--- | :--- |
| Проверка статуса mesh | `receptorctl status` |
| Просмотр пиров | `receptorctl peer list` |
| Отправка тестового сигнала | `receptorctl ping node-name` |
| Просмотр соединений | `receptorctl connection list` |

### ansible.platform (Configuration as Code)

| Модуль | Назначение |
| :--- | :--- |
| `ansible.platform.organization` | Управление организациями |
| `ansible.platform.team` | Управление командами |
| `ansible.platform.credential` | Управление учётными данными |
| `ansible.platform.inventory` | Управление инвентарями |
| `ansible.platform.project` | Управление проектами |
| `ansible.platform.job_template` | Управление шаблонами заданий |
| `ansible.platform.workflow_job_template` | Управление workflow-шаблонами |
| `ansible.platform.instance` | Управление Execution Nodes |

### REST API endpoints

Краткий справочник:

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

Полные примеры API-вызовов, RBAC автоматизация, Webhooks — см. [AAP: операционные сценарии и API](./ansible-automation-platform-operations.md).

## Диагностика

### Типичные ошибки

| Ошибка | Причина | Решение |
| :--- | :--- | :--- |
| Job Template не запускается | Нет прав на Inventory/Credentials | Проверить RBAC (Roles → Permissions) |
| Sync проекта не работает | Git-токен истёк | Обновить Credential проекта |
| EE не стартует | Podman недоступен | `systemctl status podman`, проверить права |
| Survey не отображается | Survey отключён | Включить в Job Template, проверить spec |
| Webhook не приходит | URL неверен/firewall | Проверить URL, открыть порт 443 |
| LDAP не работает | Неверный URL/фильтр | `ldapsearch -H ldap://... -D "cn=admin,dc=..." -W` |
| PostgreSQL не отвечает | Переполнение диска | `df -h`, `podman logs aap-postgres` |
| API 403 Forbidden | Токен истёк/нет прав | Пересоздать OAuth2-токен, проверить permissions |
| Receptor mesh недоступен | TLS-сертификаты не совпадают | Проверить `receptorctl status`, обновить CA |
| Platform Gateway 502 | Контроллер недоступен | Проверить статус NGINX и backend-сервисы |

### Диагностические команды

```bash
# Статус контейнеров AAP
podman-compose ps

# Логи заданий
podman-compose logs -f awx_task

# Проверка Redis
redis-cli PING
# → PONG

# Проверка PostgreSQL
podman exec aap-postgres psql -U awx -c "SELECT version();"

# Проверка API
curl -s "$AWX_HOST/api/v2/ping/" | jq '.ping, .ha, .version'
# → "pong" / false / "24.6.1"

# Статус Receptor mesh
receptorctl status
receptorctl peer list

# Проверка Execution Nodes
curl -H "Authorization: Bearer $AWX_TOKEN" "$AWX_HOST/api/v2/instances/" | jq '.results[].name'
```

## Безопасность

1. **Шифрование:** PostgreSQL SSL, LDAPS (порт 636), Webhook через HTTPS, Receptor mesh через TLS 1.3 с mTLS.
2. **Credential Management:** HashiCorp Vault / CyberArk, регулярная ротация ключей. Никогда не передавайте credentials в открытом виде. Пароли Vault credential шифруются AES-256-CBC + HMAC-SHA256 и не читаются из плейбука.
3. **Vault в заданиях:** Не используйте `Prompt on launch` в Scheduled Jobs. Для multi-Vault создавайте отдельный credential на каждое хранилище с уникальным `vault_id`. Секреты, попавшие в задание, читаются только в памяти процесса.
3. **RBAC:** принцип наименьших привилегий, изоляция Production/Staging через Organizations и Teams.
4. **Сеть:** Firewall Control Plane ↔ Execution Plane, VPN для удалённых нод. Platform Gateway как единая точка входа.
5. **Platform Gateway:** Настройте NGINX log format с дополнительными полями для аудита (требуется для AAP 2.6+).
6. **Аудит:** Включите расширенное аудит логирование в Automation Controller и Event-Driven Ansible.
7. **Backup:** Регулярный бэкап PostgreSQL и export через `awx-manage export_data`.

## Лучшие практики

- **Идемпотентность:** Используйте `ansible.platform` collection для управления конфигурацией AAP как кодом. Все изменения должны быть воспроизводимы.
- **Execution Environments:** Собирайте минимальные EE с явным указанием версии (без `:latest`). Храните образы в доверенном реестре (Harbor, Quay).
- **Receptor Mesh:** Используйте Hop Nodes для изоляции сегментов сети (DMZ, многодоменные среды). Настройте TLS для всех соединений.
- **Vault:** Храните все credentials в `ansible-vault` или внешних системах (HashiCorp Vault). Используйте `vault_` префикс для переменных. Пароль Vault credential не подставляйте в шаблоны — он доступен только для расшифровки. Если мастер-пароль не должен храниться в базе AAP, подключите credential-источник с инжектом `file`.
- **HTTPS:** Всегда используйте HTTPS с валидными сертификатами. Отключите `ansible_winrm_server_cert_validation=ignore` в production.
- **RBAC:** Разделяйте доступ через Organizations → Teams → Roles. Используйте принцип наименьших привилегий. Для Production deploy требуйте Approval Nodes.
- **Projects:** Используйте `Update on Launch` только для критически важных проектов. Для остальных — ручная синхронизация.
- **Inventory:** Предпочитайте динамические источники (Satellite, LDAP) статическим. Используйте caching для уменьшения нагрузки.
- **Мониторинг:** Настройте алерты на `awx_active_tasks`, `awx_pending_tasks`, `awx_job_success_rate`.
- **Backup:** Автоматический бэкап PostgreSQL + `awx-manage export_data` через cron.
- **Platform Gateway:** Используйте Gateway как единую точку входа для всех API. Отключите прямые доступы к внутренним сервисам.

## Мониторинг

| Метрика | Описание | Алерт |
| :--- | :--- | :--- |
| `awx_active_tasks` | Активные задания | > forks × 2 |
| `awx_pending_tasks` | Задания в очереди | > 100 в течение 5 мин |
| `awx_job_success_rate` | Процент успешных запусков | < 95% |
| `awx_api_response_time` | Время ответа API | > 2 секунды |
| `receptor_connected_peers` | Подключённые пиры Receptor | < ожидаемого количества |
| `receptor_queue_depth` | Глубина очереди Receptor | > 50 заданий |

```bash
# Prometheus exporter
docker run -d --name awx_exporter -p 9128:9128 \
  -e AWX_HOST=http://awx:80 -e AWX_TOKEN=$AWX_TOKEN \
  quay.io/prometheuscommunity/awx-exporter:latest
```

## Дополнительная информация

*   **[AAP: операционные сценарии и API](./ansible-automation-platform-operations.md)** — RBAC, Credentials, Workflows, Surveys, REST API, Webhooks, Backup.
*   **[Execution Environments](./ansible-execution-environments.md)** — сборка и настройка EE для AAP/AWX.
*   **[Event-Driven Ansible](./event-driven-ansible.md)** — action `run_job_template` для интеграции EDA с AAP.
*   **[Ansible Vault: Основы](./Vault/basics.md)** — CLI, конфигурация `vault_identity`, `vault_id_match`, формат заголовков.
*   **[Ansible Vault: Лучшие практики](./Vault/best_practices.md)** — векторы утечек, ротация, интеграция с CI/CD.
*   **[Ansible Vault: Управление паролями](./Vault/passwords.md)** — скрипты-источники, GPG, `pass`, KeePassXC.
*   **[Безопасность Ansible](./ansible_security_best_practices.md)** — credential management, защита автоматизации.
*   **[Identity Management и RBAC](./ansible-identity-management.md)** — автоматизация управления командами и ролями через `ansible.controller`.
*   **[Сравнение: AWX vs Semaphore](./ansible_semaphore.md)** — альтернативные решения.
