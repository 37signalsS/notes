# Ansible Automation Platform (AAP) и AWX

## Предварительные требования

### Для AAP (коммерческое решение)

| Компонент | Минимум | Рекомендация |
| :--- | :--- | :--- |
| Control Node | 4 vCPU, 8 GB RAM, 40 GB SSD | 8+ vCPU, 16+ GB RAM, 100+ GB SSD |
| Execution Node | 4 vCPU, 8 GB RAM, 40 GB SSD | 8+ vCPU, 16+ GB RAM, 100+ GB SSD |
| PostgreSQL | 12+ (внешний или встроенный) | PostgreSQL 14+ на выделенном сервере |
| Redis | 6+ (для очередей) | Redis 7+ кластер |
| Docker/Podman | 20.10+ | Podman 4+ (без демона) |
| ОС | RHEL 8.6+, CentOS Stream 8+, Ubuntu 22.04+ | RHEL 9+ |

### Для AWX (open-source)

| Компонент | Минимум | Рекомендация |
| :--- | :--- | :--- |
| Сервер | 2 vCPU, 4 GB RAM, 20 GB SSD | 4+ vCPU, 8+ GB RAM, 50+ GB SSD |
| Docker/Podman | 20.10+ | Podman 4+ |
| Python | 3.9+ | 3.11+ |
| Git | 2.0+ | 2.30+ |

## Определения

**Ansible Automation Platform (AAP)** — корпоративная платформа автоматизации от Red Hat, включающая Automation Controller (бывший Ansible Tower), Automation Hub (реест коллекций), Execution Environments и инструменты для разработки, тестирования и анализа.

**AWX** — проект с открытым исходным кодом, upstream-версия AAP. Включает Web UI, REST API и Execution Environments, но не содержит Enterprise-компоненты (LDAP/SAML, certified collections, расширенный аудит).

**Automation Controller (Контроллер автоматизации)** — серверная часть платформы: оркестрация запусков, управление инвентарём, credential-хранилище, RBAC и REST API. Бывший Ansible Tower.

**Automation Hub** — частный реестр Ansible-коллекций с сертифицированными Red Hat коллекциями, версионированием и signed-артефактами.

**Job Template (Шаблон задания)** — описание запуска плейбука: инвентарь + credentials + проект + Execution Environment + плейбук. Запускается через API или Web UI.

**Workflow Job Template (Шаблон рабочего процесса)** — цепочка Job Templates с логическими условиями (On Success/Failure/Always) и Approval Nodes.

**Surveys (Опросы)** — интерактивные формы для ввода `extra_vars` перед запуском шаблона.

**Inventory Source (Источник инвентаря)** — конфигурация автоматической загрузки хостов из внешних систем (AWS, GCP, Azure, VMware, Satellite, LDAP).

**Project (Проект)** — Git-репозиторий с плейбуками, ролями и переменными.

**Credential (Учётные данные)** — защищённое хранилище секретов с механизмом инжекта переменных в Execution Environment.

**Execution Environment (EE)** — OCI-контейнер с Ansible Core, Python-зависимостями и коллекциями.

**Execution Node (Узел выполнения)** — сервер для запуска Execution Environments.

**Notification (Уведомление)** — автоматическая отправка событий (успех/ошибка) во внешние системы.

**Schedule (Расписание)** — cron-подобный планировщик автоматического запуска заданий.

## Основные концепции

### Архитектура AAP 2.x

```
┌─────────────────────────────────────────────────────────────────────┐
│                        CONTROL PLANE                               │
│  ┌──────────────┐  ┌──────────────────┐  ┌──────────────────────┐ │
│  │ Web UI / API │  │ Automation       │  │ PostgreSQL           │ │
│  │ (React)      │  │ Controller       │  │ (база данных)        │ │
│  └──────┬───────┘  └────────┬─────────┘  └──────────────────────┘ │
│         │            ┌──────┴───────┐                             │
│         │            │ Redis        │                             │
│         │            │ (очереди)    │                             │
│  ┌──────┴──────────────────────────────────────────────────────┐  │
│  │                  Execution Nodes                             │  │
│  │  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐         │  │
│  │  │ EE Container│  │ EE Container│  │ EE Container│  ...    │  │
│  │  └─────────────┘  └─────────────┘  └─────────────┘         │  │
│  └─────────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────────┘
```

**Control Plane:** Web UI / API (React), Automation Controller, PostgreSQL, Redis.
**Execution Plane:** Execution Nodes (Default/Execution/Hop), Execution Environments (OCI).

### Сравнение AAP и AWX

| Критерий | AAP | AWX |
| :--- | :--- | :--- |
| Поддержка | Red Hat 24/7 | Сообщество |
| Certified Collections | Да | Нет |
| Execution Nodes | Да | Базовая поддержка |
| LDAP/AD / SSO | Полная интеграция | Ограниченная |
| Audit Logging | Расширенный | Базовый |
| Стоимость | Платная (подписка) | Бесплатно |

### 1. Жизненный цикл Job Templates

| Стадия | Описание |
| :--- | :--- |
| **Pending** | В очереди, ожидание ресурсов Execution Node |
| **Waiting** | Завершение зависимостей или обновление проекта |
| **Running** | Выполнение плейбука в Execution Environment |
| **Completed** | Successful/Failed, логи сохраняются в БД |

### 2. Projects: Git-источники кода

Project — Git-репозиторий (GitHub, GitLab, Bitbucket) с плейбуками, ролями и переменными.

**Настройка:** Credentials (Git-токен/SSH-ключ), SCM URL, SCM Branch, Update on Launch.

```bash
# Синхронизация через API
curl -X POST "$AWX_HOST/api/v2/projects/$PROJECT_ID/update/" \
     -H "Authorization: Bearer $AWX_TOKEN"
curl "$AWX_HOST/api/v2/projects/$PROJECT_ID/" \
     -H "Authorization: Bearer $AWX_TOKEN" | jq '.status'
# → "successful"
```

### 3. Inventory Sources: динамический инвентарь

| Источник | Примеры переменных |
| :--- | :--- |
| **AWS EC2** | `instance_id`, `private_ip`, `tags` |
| **GCP / Azure** | `name`, `zone`, `resource_group` |
| **VMware / OpenStack** | `uuid`, `ip_address`, `flavor` |
| **Satellite / LDAP** | `id`, `hostgroup`, `uid` |
| **Static YAML/Script** | Ручное определение |

### 4. Workflows

Workflows объединяют Job Templates, Inventory Syncs и Project Updates в цепочки:

- `On Success` (зеленая) — при успешном завершении
- `On Failure` (красная) — при ошибке
- `Always` (синяя) — независимо от результата
- **Approval Nodes** — ручное подтверждение

```
[Deploy App] →On Success→ [Verify Health] →On Success→ [Notify Success]
       │                          │
       └──On Failure──> [Rollback] →Always→ [Notify Failure]
```

### 5. Surveys

Интерактивные формы для ввода `extra_vars` перед запуском. Типы полей: Text, Password, Multiple Choice, Integer, Float, Textarea. Валидация через regex.

### 6. Credentials и Injector

| Тип | Инжект |
| :--- | :--- |
| **Machine** | `ANSIBLE_PRIVATE_KEY_FILE`, `ANSIBLE_USER` |
| **Vault** | `ANSIBLE_VAULT_PASSWORD_FILE` |
| **Cloud** | `AWS_ACCESS_KEY_ID`, `GCP_AUTH_KIND` |
| **Custom** | Пользовательские переменные через Injector |

### 7-10. Notifications, Schedules, Webhooks, REST API

Подробные примеры — см. [AAP: операционные сценарии и API](./ansible-automation-platform-operations.md).

## Практические сценарии

Подробные примеры вынесены в отдельный документ:

*   **[AAP: операционные сценарии и API](./ansible-automation-platform-operations.md)** — RBAC, Credentials, Workflows, Surveys, REST API, Webhooks, Backup/Restore.

## Установка и настройка AWX

### Установка через Docker/Podman (рекомендуется)

```bash
# Клонирование и запуск
git clone https://github.com/ansible/awx.git && cd awx/tools/docker-compose
mkdir -p pg_data redis_data

# Настройка переменных
cat > .env << EOF
POSTGRES_USER=awx
POSTGRES_PASSWORD=YourStrongPassword
POSTGRES_DB=awx
AWX_ADMIN_USER=admin
AWX_ADMIN_PASSWORD=YourAdminPassword
AWX_SECRET_KEY=$(python3 -c "import secrets; print(secrets.token_hex(32))")
EOF

# Запуск
docker-compose up -d
docker-compose ps  # → awx_web, awx_task, awx_postgres, awx_redis — all Up
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
  hostname: awx.example.com
EOF
```

### Конфигурация Execution Environments

```bash
# Кастомный EE
cat > execution-environment.yml << EOF
version: 1
build_arg_defaults:
  EE_BASE_IMAGE: "quay.io/ansible/ansible-runner:latest"
  EE_BUILDER_IMAGE: "quay.io/ansible/ansible-builder:latest"
dependencies:
  python: [boto3, botocore, apache-libcloud]
  system: [git-core, openssh-clients]
additional_build_steps:
  append_final:
    - RUN pip3 install --upgrade pip
EOF
ansible-builder build -t my-custom-ee:latest
```

Настройка EE в Job Template (или через API `POST /api/v2/execution_environments/`).

## Дополнительная информация

### Масштабирование через Execution Nodes

| Тип | Описание | Использование |
| :--- | :--- | :--- |
| **Default** | Локальный узел (встроен в Control Plane) | Тестирование |
| **Execution** | Выделенный узел для запуска EE | Продакшн |
| **Hop** | Промежуточный узел для маршрутизации | DMZ, многодоменные среды |

```bash
# Установка агента на удалённом узле
curl -L https://releases.ansible.com/ansible-automation-platform/2.4/ansible-automation-platform-2.4.0.tar.gz -o aap.tar.gz
tar xzf aap.tar.gz && cd ansible-automation-platform-2.4.0
sudo ./setup.sh -e node_type=execution -e awx_admin_password=YourPassword

# Управление через API
curl -H "Authorization: Bearer $AWX_TOKEN" "$AWX_HOST/api/v2/instances/" | jq '.results[].name'
curl -X POST "$AWX_HOST/api/v2/instances/" \
     -H "Authorization: Bearer $AWX_TOKEN" -H "Content-Type: application/json" \
     -d '{"name": "node-3", "node_type": "execution", "hostname": "10.0.1.50", "enabled": true}'
```

### Производительность и оптимизация

| Параметр | Значение | Описание |
| :--- | :--- | :--- |
| `forks` | 20-50 | Параллельные запуски (по умолчанию 5) |
| `job_timeout` | 0-86400 | Таймаут выполнения задания (секунды) |
| `idle_timeout` | 0-999999 | Таймаут простоя Execution Environment |
| `container_options` | `--memory=2g --cpus=2` | Ресурсные ограничения для EE |

```sql
-- Оптимизация PostgreSQL
ALTER SYSTEM SET shared_buffers = '4GB';
ALTER SYSTEM SET work_mem = '256MB';
ALTER SYSTEM SET max_parallel_workers_per_gather = 4;
SELECT pg_reload_conf();
```

```bash
# Redis
redis-cli CONFIG SET maxmemory 2gb
redis-cli CONFIG SET maxmemory-policy allkeys-lru
```

### Безопасность

1. **Шифрование:** PostgreSQL SSL, LDAPS (порт 636), Webhook через HTTPS
2. **Credential Management:** HashiCorp Vault / CyberArk, регулярная ротация ключей
3. **RBAC:** принцип наименьших привилегий, изоляция Production/Development
4. **Сеть:** Firewall Control Plane ↔ Execution Plane, VPN для удалённых нод

### Troubleshooting

| Проблема | Причина | Решение |
| :--- | :--- | :--- |
| Job Template не запускается | Нет прав на Inventory/Credentials | Проверить RBAC (Roles → Permissions) |
| Sync проекта не работает | Git-токен истёк | Обновить Credential проекта |
| EE не стартует | Docker/Podman недоступен | `systemctl status docker`, проверить права |
| Survey не отображается | Survey отключён | Включить в Job Template, проверить spec |
| Webhook не приходит | URL неверен/firewall | Проверить URL, открыть порт 443 |
| LDAP не работает | Неверный URL/фильтр | `ldapsearch -H ldap://... -D "cn=admin,dc=..." -W` |
| PostgreSQL не отвечает | Переполнение диска | `df -h`, `docker logs awx-postgres` |
| API 403 Forbidden | Токен истёк/нет прав | Пересоздать OAuth2-токен, проверить permissions |

**Диагностические команды:**
```bash
docker-compose logs -f awx_task           # Логи заданий
docker-compose ps                          # Статус контейнеров
redis-cli PING                             # → PONG
docker exec awx-postgres psql -U awx -c "SELECT version();"
curl -s "$AWX_HOST/api/v2/ping/" | jq '.ping, .ha, .version'
# → "pong" / false / "24.6.1"
```

### Мониторинг AAP/AWX

| Метрика | Описание | Алерт |
| :--- | :--- | :--- |
| `awx_active_tasks` | Активные задания | > forks × 2 |
| `awx_pending_tasks` | Задания в очереди | > 100 в течение 5 мин |
| `awx_job_success_rate` | Процент успешных запусков | < 95% |
| `awx_api_response_time` | Время ответа API | > 2 секунды |

```bash
# Prometheus exporter
docker run -d --name awx_exporter -p 9128:9128 \
  -e AWX_HOST=http://awx:80 -e AWX_TOKEN=$AWX_TOKEN \
  quay.io/prometheuscommunity/awx-exporter:latest
```

## Смотрите также

*   **[AAP: операционные сценарии и API](./ansible-automation-platform-operations.md)** — RBAC, Credentials, Workflows, Surveys, REST API, Webhooks, Backup.
*   **[Execution Environments](./ansible-execution-environments.md)** — сборка и настройка EE для AAP/AWX.
*   **[Event-Driven Ansible](./event-driven-ansible.md)** — action `run_job_template` для интеграции EDA с AAP.
*   **[Безопасность Ansible](./ansible_security_best_practices.md)** — credential management, защита автоматизации.
*   **[Identity Management и RBAC](./ansible-identity-management.md)** — автоматизация управления командами и ролями через `ansible.controller`.
*   **[Сравнение: AWX vs Semaphore](./ansible_semaphore.md)** — альтернативные решения.
