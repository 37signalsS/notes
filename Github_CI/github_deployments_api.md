# GitHub Deployments API: Деплой, окружения и статусы

**Актуально для:** GitHub Deployments API, Environments API (октябрь 2026); GitHub Enterprise Server 3.14+

GitHub Deployments API — это набор REST endpoint-ов для координации и протоколирования жизненного цикла развертывания (deployment lifecycle) на уровне репозитория. Он обеспечивает двустороннюю связь между GitHub и инфраструктурными инструментами развертывания (GitHub Actions, ArgoCD, Flux, Jenkins, локальные bash/ansible-скрипты, bare-metal оркестраторы). Deployments API выступает в роли **протокола согласования и аудита**: фиксирует намерение развернуть конкретный коммит в заданное окружение, применяет политики защиты (gates), собирает статусы исполнения и сохраняет полную историю релизов.

## Определения

- **Deployment**: Запрос на развертывание конкретного коммита (SHA), ветки или тега в целевое логическое окружение (например, `production`). Содержит метаданные: задачу (`task`), полезную нагрузку (`payload`), флаги изоляции и требования к предварительным проверкам.
- **Environment**: Именованная среда развертывания (`staging`, `production`, `baremetal-cluster-01`), служащая границей безопасности. К окружению привязываются правила защиты (Protection Rules), специфичные секреты, переменные и политики веток.
- **Deployment Status**: Фиксация текущего состояния развертывания (`queued`, `in_progress`, `success`, `failure`, `error`, `inactive`, `pending`). Каждый статус может содержать ссылки на журналы (`log_url`), работающее приложение (`environment_url`) и текстовое описание.
- **Protection Rules**: Барьеры безопасности, проверяемые GitHub перед допуском к выполнению деплоя:
  - **Required Reviewers**: Требование явного ручного подтверждения (Manual Approval) от конкретных пользователей или команд до начала выполнения задачи.
  - **Wait Timer**: Искусственная задержка (в минутах) между запросом на деплой и фактическим стартом выполнения.
  - **Deployment Branch Policy**: Ограничение веток и тегов, из которых разрешен деплой в данное окружение (`protected_branches` либо пользовательские шаблоны `custom_branch_policies`).
  - **Prevent Self-Review**: Запрет автору запуска или инициатору изменений самостоятельно подтверждать деплой в защищенное окружение.
- **Custom Deployment Protection Rules**: Внешние шлюзы валидации на базе GitHub Apps. При запуске деплоя GitHub отправляет webhook во внешнюю систему (например, локальный мониторинг Prometheus, ITSM/ServiceNow), ожидая утверждения или отклонения через REST API.
- **Auto-Inactive**: Механизм автоматического перевода всех предыдущих успешных деплоев в том же окружении в статус `inactive` при появлении нового статуса `success`.
- **Transient Environment**: Флаг (`transient_environment: true`), указывающий на временный характер окружения (динамические preview-окружения для PR, эфемерные тестовые стенды), не требующий долгосрочного сохранения активности в интерфейсе.
- **Concurrency Group**: Механизм сериализации очередей в GitHub Actions, гарантирующий выполнение только одного развертывания в окружение в единицу времени (`cancel-in-progress: false` для продакшена).

## Архитектура и модель выполнения

### Модель состояний (Deployment State Machine)

Жизненный цикл развертывания представляет собой конечный автомат, управляемый событиями из Actions или внешних систем:

```text
               ┌───────────────┐
               │    Created    │ (POST /deployments)
               └───────┬───────┘
                       │
       ┌───────────────┴───────────────┐
       ▼                               ▼
┌──────────────┐               ┌──────────────┐
│   waiting    │               │    queued    │
│ (Gates/Timer)│               └──────┬───────┘
└──────┬───────┘                      │
       │ Approved                     │
       └───────────────┬──────────────┘
                       ▼
               ┌──────────────┐
               │ in_progress  │
               └───────┬───────┘
                       │
         ┌─────────────┼─────────────┐
         ▼             ▼             ▼
  ┌─────────────┐ ┌─────────┐ ┌─────────────┐
  │   success   │ │ failure │ │    error    │
  └──────┬──────┘ └─────────┘ └─────────────┘
         │
         │ Новый успешный деплой (auto_inactive: true)
         ▼
  ┌─────────────┐
  │  inactive   │
  └─────────────┘
```

1. **Создание запроса (`Created`)**: Через API создается объект Deployment. Если указан параметр `auto_merge: true`, GitHub предварительно проверяет возможность fast-forward слияния базовой ветки. Если переданы `required_contexts`, валидируются статусы коммита.
2. **Ожидание шлюзов (`waiting`)**: Если окружение защищено правилами (Manual Approval, Wait Timer, Custom Protection Rules), Actions приостанавливает выполнение задачи.
3. **Очередь и запуск (`queued` / `in_progress`)**: Исполнитель (runner или внешний оркестратор) берет задачу в работу и публикует статус `in_progress`.
4. **Финал выполнения (`success` / `failure` / `error`)**:
   - `success` — развертывание прошло успешно; публикуется `environment_url`. Предыдущие активные деплои в этом окружении автоматически переводятся в `inactive`.
   - `failure` — развертывание завершилось с ошибкой конфигурации или тестов приложения.
   - `error` — произошел сбой инфраструктуры доставки (недоступность узла, сбой сети, ошибка раннера).
5. **Деактивация (`inactive`)**: Сигнализирует, что данная версия более не активна в окружении (заменена более новой или откачена).

### Архитектура взаимодействия с внешней инфраструктурой

Deployments API поддерживает две модели интеграции: нативную (GitHub Actions) и агентскую/внешнюю (On-Prem CD, Bare-Metal, Webhooks):

```text
┌────────────────────────────────────────────────────────────────────────┐
│ GitHub Repository & Environments                                       │
│                                                                        │
│   [Git Commit / Ref] ──> [Protection Rules] ──> [Deployments API]      │
│                                                        │               │
└────────────────────────────────────────────────────────┼───────────────┘
                                                         │
                         ┌───────────────────────────────┴──────────────┐
                         │                                              │
           Модель 1: GitHub Actions (Push/Native)        Модель 2: Внешний CD (Webhook/API)
                         │                                              │
                         ▼                                              ▼
            ┌─────────────────────────┐                   ┌──────────────────────────┐
            │ Self-Hosted Runner      │                   │ On-Premise Gateway       │
            │                         │                   │ (Webhook Listener)       │
            │ 1. Читает Env Secrets   │                   │                          │
            │ 2. OIDC -> On-Prem Vault│                   │ 1. Принимает webhook     │
            │ 3. Ansible / Helm / K8s │                   │ 2. Запускает оркестрацию │
            │ 4. Статус через Actions │                   │ 3. Шлет статусы через API│
            └────────────┬────────────┘                   └─────────────┬────────────┘
                         │                                              │
                         └──────────────────────┬───────────────────────┘
                                                ▼
                               ┌─────────────────────────────────┐
                               │ On-Premise Инфраструктура       │
                               │ (Bare-Metal / K8s / VM Clusters)│
                               └─────────────────────────────────┘
```

### Модель безопасности и токенов

- **Права доступа**: Для создания деплоев и изменения статусов токен (`GITHUB_TOKEN` или PAT / App Token) должен обладать правами `deployments: write` и `contents: read`.
- **Изоляция секретов окружений**: Секреты и переменные, настроенные для окружения (`Settings → Environments`), становятся доступны задаче **только** при наличии блока `environment: <имя>`. Если задача запускается без явного указания окружения, доступ к его секретам аппаратно заблокирован.
- **OIDC Claims**: При использовании OpenID Connect для интеграции с внутренними системами (например, корпоративным HashiCorp Vault или Kubernetes API без статических токенов), JWT-токен GitHub содержит клеймы:
  - `environment`: точное имя окружения (например, `production`).
  - `environment_node_id`: глобальный идентификатор среды.
  - `ref`: ветка или тег развертывания.
  Это позволяет на стороне Vault настроить политику: выдавать доступ к боевым базам данных только тем раннерам, у которых claim `environment == "production"`.

---

## Практические сценарии

### Сценарий 1: Нативный CD конвейер в GitHub Actions с сериализацией и защитой

Развертывание на локальный Kubernetes-кластер или bare-metal стенд через Self-Hosted Runner с привязкой к окружению `production`, ограничением параллелизма и динамической ссылкой на окружение.

**Предварительные требования**:
- Окружение `production` создано в репозитории (`Settings → Environments`).
- Назначены Required Reviewers и включен Wait Timer (5 минут).
- Настроен Self-Hosted Runner с меткой `self-hosted-prod`.

```yaml
name: Deploy Production Service

on:
  push:
    branches:
      - main

permissions:
  contents: read
  deployments: write
  id-token: write

concurrency:
  group: production_deployment
  cancel-in-progress: false  # Критично: никогда не прерывать выполняющийся деплой на проде!

jobs:
  deploy:
    runs-on: [self-hosted, linux, self-hosted-prod]
    environment:
      name: production
      url: ${{ steps.rollout.outputs.service_url }}
    steps:
      - name: Checkout repository
        uses: actions/checkout@v7

      - name: Download release artifacts
        uses: actions/download-artifact@v8
        with:
          name: application-binary
          path: ./bin/

      - name: Execute deployment script
        id: rollout
        env:
          DB_PASSWORD: ${{ secrets.PROD_DB_PASSWORD }}
          INTERNAL_ROUTER: ${{ vars.PROD_ROUTER_HOST }}
        run: |
          echo "Starting rollout to local infrastructure..."
          chmod +x ./bin/app
          # Имитация наката релиза на локальные узлы
          ./scripts/deploy-onprem.sh --binary="./bin/app" --target="$INTERNAL_ROUTER"
          
          # Экспорт URL для кнопки View Deployment в интерфейсе GitHub
          echo "service_url=https://internal-app.corp.local" >> "$GITHUB_OUTPUT"

      - name: Verify health checks
        run: |
          curl --fail --silent --show-error https://internal-app.corp.local/healthz
```

**Механика работы**:
1. При старте job `deploy` GitHub переводит её в состояние `Waiting`.
2. Назначенным ревьюерам отправляется уведомление; после их подтверждения запускается таймер задержки.
3. В интерфейсе репозитория создается объект Deployment со статусом `in_progress`.
4. После успешного шага `rollout` GitHub Actions автоматически отправляет статус `success` с указанием URL из `steps.rollout.outputs.service_url`.

---

### Сценарий 2: Полное управление жизненным циклом деплоя через GitHub CLI и REST API

Сценарий для внешней автоматизации (внешний orchestrator, Jenkins, или SRE-скрипт сопровождения релиза на on-prem стенды).

```bash
# 1. Создать Deployment для коммита на окружение staging с отключенным auto_merge
# auto_merge=false гарантирует, что GitHub не попытается автоматически влить main в ref
DEPLOYMENT_ID=$(gh api -X POST /repos/org/repo/deployments \
  -H "Accept: application/vnd.github+json" \
  -H "X-GitHub-Api-Version: 2026-03-10" \
  -f ref="v2.4.0" \
  -f environment="staging" \
  -f task="deploy" \
  -F auto_merge=false \
  -F required_contexts='["ci/lint","ci/test"]' \
  -f description="Release v2.4.0 to staging cluster" \
  --jq '.id')

echo "Created deployment ID: $DEPLOYMENT_ID"
# → Created deployment ID: 1984729102

# 2. Перевести deployment в статус in_progress перед началом реальных работ
gh api -X POST /repos/org/repo/deployments/$DEPLOYMENT_ID/statuses \
  -H "Accept: application/vnd.github+json" \
  -H "X-GitHub-Api-Version: 2026-03-10" \
  -f state="in_progress" \
  -f description="Running Ansible rollout playbooks..." \
  -f log_url="https://loki.corp.local/explore?job=deploy-staging&id=1984729102"
# → {"id": 89201928, "state": "in_progress", "description": "Running Ansible rollout playbooks..."}

# 3. Выполнение развертывания (внешний скрипт наката)
# ... ansible-playbook -i staging site.yml ...

# 4а. В случае успеха: фиксация success и публикация environment_url
# auto_inactive=true (по умолчанию) переведет предыдущий успешный деплой в inactive
gh api -X POST /repos/org/repo/deployments/$DEPLOYMENT_ID/statuses \
  -H "Accept: application/vnd.github+json" \
  -H "X-GitHub-Api-Version: 2026-03-10" \
  -f state="success" \
  -f environment="staging" \
  -f environment_url="https://staging.corp.local" \
  -f log_url="https://loki.corp.local/explore?job=deploy-staging&id=1984729102" \
  -f description="Deployment v2.4.0 verified and active"
# → {"id": 89202054, "state": "success", "environment_url": "https://staging.corp.local"}

# 4б. В случае сбоя: фиксация failure
# gh api -X POST /repos/org/repo/deployments/$DEPLOYMENT_ID/statuses \
#   -H "Accept: application/vnd.github+json" \
#   -f state="failure" \
#   -f description="Smoke tests failed: connection timeout on port 8443"
```

---

### Сценарий 3: Настройка Environments, правил защиты и политик веток через REST API

Автоматизация настройки окружений через Infrastructure-as-Code или скрипты инициализации инфраструктуры репозитория.

```bash
# 1. Создать/обновить окружение production с таймером ожидания и запретом self-review
# Назначаем команду DevOps (ID команды: 928374) в качестве обязательных проверяющих
gh api -X PUT /repos/org/repo/environments/production \
  -H "Accept: application/vnd.github+json" \
  -H "X-GitHub-Api-Version: 2026-03-10" \
  --input - <<'EOF'
{
  "wait_timer": 10,
  "prevent_self_review": true,
  "reviewers": [
    {
      "type": "Team",
      "id": 928374
    }
  ],
  "deployment_branch_policy": {
    "protected_branches": false,
    "custom_branch_policies": true
  }
}
EOF
# → {"name": "production", "wait_timer": 10, "prevent_self_review": true}

# 2. Настроить допустимые шаблоны веток (только main и релизные теги v*.*.*)
# Разрешаем ветку main
gh api -X POST /repos/org/repo/environments/production/deployment-branch-policies \
  -H "Accept: application/vnd.github+json" \
  -f name="main" \
  -f type="branch"
# → {"id": 4321, "name": "main", "type": "branch"}

# Разрешаем релизные теги
gh api -X POST /repos/org/repo/environments/production/deployment-branch-policies \
  -H "Accept: application/vnd.github+json" \
  -f name="v*.*.*" \
  -f type="tag"
# → {"id": 4322, "name": "v*.*.*", "type": "tag"}

# 3. Проверка настроенных политик веток
gh api /repos/org/repo/environments/production/deployment-branch-policies \
  --jq '.branch_policies[] | {id: .id, name: .name, type: .type}'
# → {"id": 4321, "name": "main", "type": "branch"}
# → {"id": 4322, "name": "v*.*.*", "type": "tag"}
```

---

### Сценарий 4: Rollback (Откат версии) и перевод деплоев в статус Inactive

Когда система мониторинга фиксирует деградацию сервиса, SRE выполняет откат на предыдущую заведомо рабочую версию.

```bash
# 1. Поиск предыдущего успешного deployment
PREVIOUS_SHA=$(gh api /repos/org/repo/deployments \
  -f environment="production" \
  --jq '[.[] | select(.id != 1984729102)] | .[0].sha')

echo "Reverting to stable commit SHA: $PREVIOUS_SHA"
# → Reverting to stable commit SHA: 7b81f2a3c94d1e

# 2. Пометить текущий сбойный deployment как inactive
gh api -X POST /repos/org/repo/deployments/1984729102/statuses \
  -H "Accept: application/vnd.github+json" \
  -f state="inactive" \
  -f description="Manually marked inactive due to incident INC-4921"
# → {"id": 89205100, "state": "inactive"}

# 3. Инициировать новый Deployment на стабильный коммит
ROLLBACK_DEPLOY_ID=$(gh api -X POST /repos/org/repo/deployments \
  -H "Accept: application/vnd.github+json" \
  -f ref="$PREVIOUS_SHA" \
  -f environment="production" \
  -f task="rollback" \
  -F auto_merge=false \
  -f description="Emergency rollback to $PREVIOUS_SHA" \
  --jq '.id')

# 4. Перевести статус отката в in_progress, накатить версию и зафиксировать success
gh api -X POST /repos/org/repo/deployments/$ROLLBACK_DEPLOY_ID/statuses \
  -f state="in_progress" \
  -f description="Restoring previous container image..."

# ... Запуск отката в локальном кластере: helm rollback app-production 14 ...

gh api -X POST /repos/org/repo/deployments/$ROLLBACK_DEPLOY_ID/statuses \
  -f state="success" \
  -f environment="production" \
  -f environment_url="https://production.corp.local" \
  -f description="Rollback complete. Stable state restored."
# → {"id": 89205211, "state": "success"}
```

---

### Сценарий 5: Webhook-Driven интеграция для On-Premise инфраструктуры

Принцип работы: разработчик создает Deployment в GitHub, репозиторий отправляет webhook `deployment` во внутренний корпоративный шлюз, который производит физическую выкатку и возвращает статусы через API.

**Обработчик Webhook (Python/Flask на внутреннем сервере с доступом к GitHub Enterprise / github.com)**:

```python
#!/usr/bin/env python3
"""On-Premise deployment worker listening for GitHub deployment events."""
import hmac
import hashlib
import subprocess
import requests
from flask import Flask, request, jsonify

app = Flask(__name__)
WEBHOOK_SECRET = b"SuperSecretSharedKey123"
GITHUB_TOKEN = "ghp_InternalAutomationToken"

def verify_signature(payload, signature_header):
    if not signature_header:
        return False
    sha_name, signature = signature_header.split("=")
    mac = hmac.new(WEBHOOK_SECRET, msg=payload, digestmod=hashlib.sha256)
    return hmac.compare_digest(mac.hexdigest(), signature)

def update_status(statuses_url, state, description, env_url=None):
    headers = {
        "Authorization": f"Bearer {GITHUB_TOKEN}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2026-03-10"
    }
    data = {
        "state": state,
        "description": description,
        "environment_url": env_url
    }
    requests.post(statuses_url, json=data, headers=headers, timeout=10)

@app.route("/webhook/deployments", methods=["POST"])
def handle_deployment():
    signature = request.headers.get("X-Hub-Signature-256")
    if not verify_signature(request.get_data(), signature):
        return jsonify({"error": "Invalid signature"}), 403

    event = request.headers.get("X-GitHub-Event")
    if event != "deployment":
        return jsonify({"message": "Ignored"}), 200

    payload = request.json
    action = payload.get("action")
    if action != "created":
        return jsonify({"message": "Not a created action"}), 200

    deployment = payload["deployment"]
    statuses_url = deployment["statuses_url"]
    sha = deployment["sha"]
    env = deployment["environment"]

    # 1. Сообщить GitHub, что деплой взят в работу
    update_status(statuses_url, "in_progress", f"Deploying {sha[:7]} to {env}...")

    # 2. Вызов локальной утилиты развертывания (Ansible / Shell)
    try:
        res = subprocess.run(
            ["/opt/scripts/deploy-worker.sh", env, sha],
            check=True,
            capture_output=True,
            text=True
        )
        update_status(statuses_url, "success", "Deployed successfully", f"https://{env}.corp.local")
    except subprocess.CalledProcessError as exc:
        update_status(statuses_url, "failure", f"Deploy failed: {exc.stderr[:100]}")

    return jsonify({"status": "processed"}), 200

if __name__ == "__main__":
    app.run(host="127.0.0.1", port=8080)
```

---

### Сценарий 6: Custom Deployment Protection Rules через GitHub App

Custom Protection Rules позволяют внешним системам выступать в качестве гейта безопасности перед выполнением задачи с окружением `environment: production`.

**Шаг 1: Привязка правила к окружению через REST API**:

```bash
# Получить ID установленного GitHub App (интеграции)
APP_ID=$(gh api /orgs/corp/installations --jq '.[0].app_id')

# Активировать Custom Protection Rule для окружения production
gh api -X POST /repos/org/repo/environments/production/deployment_protection_rules \
  -H "Accept: application/vnd.github+json" \
  -H "X-GitHub-Api-Version: 2026-03-10" \
  -F integration_id="$APP_ID"
# → {"id": 19283, "node_id": "DPR_kwDO...", "enabled": true}
```

**Шаг 2: Обработка события `deployment_protection_rule` и подтверждение**:

Когда GitHub Actions доходит до задачи с `environment: production`, он шлет webhook с событием `deployment_protection_rule` (action: `requested`). Внешний сервис опрашивает мониторинг и утверждает или отклоняет запуск:

```bash
# Внешний сервис проверяет локальный Prometheus:
# curl -s "http://prometheus.corp.local:9090/api/v1/query?query=sum(alerts{severity='critical'})"
# Если критических алертов 0 -> подтвердить деплой:

RUN_ID=12849102847

gh api -X POST /repos/org/repo/actions/runs/$RUN_ID/deployment_protection_rule \
  -H "Accept: application/vnd.github+json" \
  -H "X-GitHub-Api-Version: 2026-03-10" \
  -f environment_name="production" \
  -f state="approved" \
  -f comment="Pre-deploy verification passed: Prometheus alerts=0, CPU headroom > 40%"
# → {"message": "Success"}

# Если обнаружена проблема -> отклонить деплой:
# gh api -X POST /repos/org/repo/actions/runs/$RUN_ID/deployment_protection_rule \
#   -f environment_name="production" \
#   -f state="rejected" \
#   -f comment="Deployment blocked: Active P1 incident in progress"
```

---

## Операции и команды

### Сводная таблица REST API Deployments & Environments

| Операция | HTTP метод и Endpoint | Описание |
|---|---|---|
| Создать deployment | `POST /repos/{owner}/{repo}/deployments` | Создает запрос на деплой для ref/sha в указанный environment |
| Список deployments | `GET /repos/{owner}/{repo}/deployments` | Возвращает список деплоев с фильтрацией по `sha`, `ref`, `task`, `environment` |
| Получить deployment | `GET /repos/{owner}/{repo}/deployments/{deployment_id}` | Детальные свойства конкретного deployment |
| Удалить deployment | `DELETE /repos/{owner}/{repo}/deployments/{deployment_id}` | Удаляет запись деплоя (требует отсутствия активных статусов) |
| Список статусов | `GET /repos/{owner}/{repo}/deployments/{id}/statuses` | История изменений состояний деплоя |
| Создать статус | `POST /repos/{owner}/{repo}/deployments/{id}/statuses` | Создает статус (`in_progress`, `success`, `failure`, `inactive`) |
| Получить статус | `GET /repos/{owner}/{repo}/deployments/{id}/statuses/{status_id}` | Детали конкретного изменения статуса |
| Список environments | `GET /repos/{owner}/{repo}/environments` | Список всех окружений репозитория с правилами защиты |
| Создать/обновить environment | `PUT /repos/{owner}/{repo}/environments/{environment_name}` | Конфигурирует reviewers, wait_timer, branch policies |
| Получить environment | `GET /repos/{owner}/{repo}/environments/{environment_name}` | Просмотр настроек защиты конкретного окружения |
| Удалить environment | `DELETE /repos/{owner}/{repo}/environments/{environment_name}` | Удаляет окружение и отвязанные правила |
| Список branch policies | `GET /repos/{owner}/{repo}/environments/{env}/deployment-branch-policies` | Список правил разрешенных веток/тегов |
| Добавить branch policy | `POST /repos/{owner}/{repo}/environments/{env}/deployment-branch-policies` | Добавляет паттерн ветки или тега (`name`, `type`) |
| Удалить branch policy | `DELETE /repos/.../environments/{env}/deployment-branch-policies/{id}` | Удаляет правило ветки |
| Включить Custom Protection Rule | `POST /repos/{owner}/{repo}/environments/{env}/deployment_protection_rules` | Привязывает GitHub App к окружению |
| Утвердить Custom Protection Rule | `POST /repos/{owner}/{repo}/actions/runs/{run_id}/deployment_protection_rule` | Утверждает (`approved`) или отклоняет (`rejected`) запуск |

### Параметры создания Deployment (`POST /deployments`)

| Параметр | Тип | Обязательный | Описание и умолчания |
|---|---|---|---|
| `ref` | string | Да | Ветка, тег или полный 40-символьный SHA коммита для развертывания |
| `task` | string | Нет | Тип задачи (по умолчанию `deploy`). Примеры: `deploy:migrate`, `rollback` |
| `auto_merge` | boolean | Нет | По умолчанию `true`. При `true` GitHub пытается автоматически обновить `ref` до default branch |
| `required_contexts` | array | Нет | Список статус-чеков, обязанных быть `success`. По умолчанию — все чеки default branch. Для отключения передается `[]` |
| `payload` | object/string | Нет | JSON-объект произвольных пользовательских данных, передаваемых внешнему исполнителю |
| `environment` | string | Нет | Имя целевого окружения (по умолчанию `production`) |
| `description` | string | Нет | Описание деплоя (макс. 140 символов) |
| `transient_environment` | boolean | Нет | По умолчанию `false`. `true` используется для временных PR/preview сред |
| `production_environment` | boolean | Нет | `true` указывает, что среда является продуктовой (влияет на аудит и UI) |

### Допустимые состояния Deployment Status

| Состояние (`state`) | Назначение |
|---|---|
| `queued` | Задача деплоя поставлена в очередь на стороне исполнителя |
| `in_progress` | Процесс развертывания физически выполняется в инфраструктуре |
| `success` | Развертывание завершено успешно. Приложение доступно по `environment_url` |
| `failure` | Развертывание завершилось ошибкой тестов или скрипта выкатки |
| `error` | Инфраструктурный сбой (сеть, аутентификация, отказ раннера) |
| `inactive` | Деплой выведен из эксплуатации или заменен более свежей версией |
| `pending` | Устаревшее состояние инициализации (рекомендуется `queued`) |

### Практические команды GitHub CLI

```bash
# Получить список последних 5 деплоев в окружении production
gh api "/repos/org/repo/deployments?environment=production&per_page=5" \
  --jq '.[] | {id: .id, ref: .ref, sha: .sha[0:7], created: .created_at, task: .task}'
# → {"created": "2026-10-11T12:00:00Z", "id": 1984729102, "ref": "v2.4.0", "sha": "e9a1b2c", "task": "deploy"}

# Получить текущий активный статус деплоя
gh api /repos/org/repo/deployments/1984729102/statuses \
  --jq '.[0] | {state: .state, description: .description, env_url: .environment_url}'
# → {"description": "Deployment v2.4.0 verified and active", "env_url": "https://staging.corp.local", "state": "success"}

# Удалить deployment (требуется, чтобы все статусы были удалены или не блокировали операцию)
gh api -X DELETE /repos/org/repo/deployments/1984729102
# → HTTP 204 No Content
```

---

## Диагностика и устранение неполадок

| Симптом | Причина | Решение |
|---|---|---|
| Ошибка `409 Conflict: Merge conflict` при вызове `POST /deployments` | Включен `auto_merge: true`, и ветка развертывания отстает от `main`, вызывая конфликт слияния | Передавать явный флаг `-F auto_merge=false` при создании deployment либо предварительно выполнить rebase/merge ветки |
| Ошибка `409 Conflict: Commit status checks failed` | Не все проверки из `required_contexts` завершились успешно для указанного коммита | Дождаться завершения обязательных CI-пайплайнов (`ci/test`) либо передать `-F required_contexts='[]'`, если чеки не требуются |
| Ошибка `403 Forbidden: Resource not accessible by integration` | Встроенный токен Actions не имеет прав на создание деплоев | Добавить блок `permissions: { deployments: write, contents: read }` на уровне workflow или job |
| Ошибка `404 Not Found` при попытке обновить статус деплоя | Указан неверный ID деплоя или токен не имеет доступа к репозиторию | Проверить права токена и валидность `deployment_id`, возвращенного на шаге создания |
| Задача в GitHub Actions висит в статусе `Waiting` бесконечно | Настроены `reviewers`, но никто не подтвердил запуск, либо сработал `prevent_self_review` | Назначенный проверяющий должен зайти в интерфейс запуска Actions и нажать `Review deployments`. Автор запуска не может одобрить свой деплой при включенном `prevent_self_review` |
| Ошибка `Branch "feature-x" is not allowed to deploy to production` | Включена `deployment_branch_policy`, и ветка не соответствует разрешенным шаблонам | Развертывать только из веток, внесенных в policy (например, `main` или `release/*`), либо добавить шаблон через API `POST .../deployment-branch-policies` |
| Несколько одновременных деплоев вызывают гонку данных на серверах | В workflow не настроена сериализация через `concurrency` | Добавить `concurrency: group: production, cancel-in-progress: false` на уровне задачи деплоя |
| Секреты окружения пустые внутри шагов скрипта | Имя окружения в `environment:` не совпадает с именем в настройках репозитория | Проверить точное совпадение регистра и имени в ключе `environment: name` и в `Settings → Environments` |
| Ошибка `400 Bad Request` при вызове `DELETE /deployments/{id}` | Нельзя удалить деплой, пока его последний статус числится как активный (`success`) | Сначала отправить статус `inactive` для этого деплоя через `POST .../statuses`, после чего повторить удаление |
| Webhook `deployment` не доходит до внутреннего сервера | Внутренний endpoint недоступен из сети GitHub или в настройках webhook не выбрано событие `Deployments` | Настроить реверс-прокси/шлюз с валидным SSL-сертификатом и убедиться, что событие `Deployments` отмечено в `Settings → Webhooks` |

---

## Лучшие практики

1. **Всегда отключать `auto_merge` для внешних систем**: При программном вызове `POST /deployments` явно указывайте `auto_merge: false`. Автоматическое слияние ветки по умолчанию внутри API-запроса непредсказуемо меняет SHA коммита и приводит к неожиданным ошибкам 409 Conflict.
2. **Строгая сериализация с `cancel-in-progress: false`**: Для производственных сред (`production`) всегда используйте группу `concurrency: group: production_deploy` с `cancel-in-progress: false`. Отмена деплоя посреди выполнения playbook приводит к половинчатому состоянию инфраструктуры и недоступности сервисов.
3. **Изоляция боевых секретов исключительно в Environments**: Запрещается хранить учетные данные продакшена в общерепозиторных секретах (`Repository secrets`). Переносите их в `Environment secrets` и настраивайте правило `Required Reviewers` + `Prevent Self-Review`.
4. **Использование OIDC вместо статических токенов**: Вместо постоянных SSH-ключей и паролей в секретах используйте связку GitHub OIDC с локальным HashiCorp Vault или SPIFFE. Валидируйте клейм `environment: production` на стороне Vault.
5. **Публикация информативных `environment_url` и `log_url`**: При переводе деплоя в `in_progress` всегда передавайте ссылку на централизованный сбор логов (Grafana Loki / ELK), а при `success` — прямой URL приложения. Это экономит время дежурных SRE во время разбора инцидентов.
6. **Автоматический учет статуса Inactive**: Полагайтесь на флаг `auto_inactive: true` (по умолчанию) при отправке статуса `success`. Это гарантирует, что в интерфейсе GitHub активным всегда отображается только один актуальный релиз на каждое окружение.
7. **Разметка эфемерных сред (`transient_environment: true`)**: При развертывании временных тестовых стендов для Pull Request (feature preview) передавайте флаг `transient_environment: true`. Это очищает аналитику и интерфейс репозитория от мусорных долгосрочных записей.
8. **Фиксация SHA коммита, а не веток**: Внешние CD-инструменты должны создавать deployment с указанием точного 40-значного SHA коммита в поле `ref`, а не имени ветки `main`, чтобы исключить расхождения между моментом запроса и моментом выкатки.

---

## Дополнительная информация

- **[Ключевые концепции GitHub Actions](./Core_Concept.md)** — основы жизненного цикла воркфлоу, базовые понятия окружений.
- **[Синтаксис воркфлоу](./Workflow_Syntax.md)** — спецификация синтаксиса `environment:`, `concurrency:` и контекстов.
- **[Оптимизация воркфлоу](./Optimization.md)** — управление параллелизмом и очередями `concurrency`.
- **[Управление секретами](./secrets_management.md)** — разграничение секретов уровней Repository, Organization и Environment.
- **[GitHub Webhooks](./github_webhooks.md)** — прием и валидация событий `deployment` и `deployment_status`.
- **[GitHub Apps](./github_apps.md)** — архитектура приложений для реализации Custom Deployment Protection Rules.
- **[GitHub API: REST, GraphQL, Rate Limits](./github_api.md)** — базовые правила аутентификации, заголовки и лимиты запросов к REST API.
- **[Управление релизами](./Release_Management.md)** — релизные пайплайны и артефакты.
- **[Rulesets](./rulesets.md)** — защита веток и правила публикации тегов.
- **Официальная документация GitHub**:
  - [REST API endpoints for Deployments](https://docs.github.com/en/rest/deployments/deployments)
  - [REST API endpoints for Environments](https://docs.github.com/en/rest/deployments/environments)
  - [Using environments for deployment in GitHub Actions](https://docs.github.com/en/actions/deployment/targeting-different-environments/using-environments-for-deployment)
