# Incident Response для CI/CD

---

## Определения

### CI/CD Incident
Инцидент, связанный с пайплайном, Runner'ом или процессом деплоя. Включает сбои сборки, тестирования, деплоя, а также проблемы с инфраструктурой CI/CD (registry, runner, агенты).

### Rollback через CI/CD
Процесс отката к предыдущей версии приложения через пайплайн. Реализуется через dedicated rollback job, reuse существующего deploy stage или manual trigger отката.

### Communication Plan
План коммуникации при инцидентах CI/CD. Определяет каналы связи,的责任人, шаблоны сообщений и частоту обновлений для stakeholder'ов.

### Postmortem для CI/CD
Анализ инцидента CI/CD после его разрешения. Включает timeline, root cause analysis, action items и меры по предотвращению повторения.

### MTTR (Mean Time To Recovery) для CI/CD
Среднее время восстановления пайплайна или процесса деплоя от момента обнаружения инцидента до полного восстановления рабочего состояния.

---

## Теоретический блок

### Типы CI/CD инцидентов

| Тип инцидента | Описание | Влияние |
|---|---|---|
| **Pipeline Failure** | Пайплайн завершается с ошибкой на любом этапе | Блокирует деплой, замедляет релизы |
| **Runner Down** | Runner недоступен или не выполняет jobs | Jobs ставятся в очередь, увеличивается время сборки |
| **Deployment Failure** | Деплой завершается неудачно | Приложение может быть в нерабочем состоянии |
| **Registry Outage** | Docker registry или artifact repository недоступен | Невозможно скачать/загрузить образы |
| **Secret Leak** | Утечка секретов через CI/CD | Критическая угроза безопасности |
| **Pipeline Hang** | Пайплайн завис и не завершается | Занимает ресурсы, блокирует очереди |
| **Flaky Tests** | Нестабильные тесты, падающие без причин | Ложные срабатывания, потеря доверия к тестам |

### Severity levels для CI/CD инцидентов

**SEV-1 (Critical)**
- Все пайплайны заблокированы
- Деплой в production невозможен
- Утечка секретов или credentials
- Registry недоступен для всех проектов

**SEV-2 (High)**
- Основные пайплайны не работают
- Деплой в production затруднен
- Runner'ы не выполняют jobs
- Критические тесты падают

**SEV-3 (Medium)**
- Отдельные пайплайны падают
- Non-critical jobs завершаются с ошибками
- Увеличилось время сборки
- Flaky tests в main ветке

**SEV-4 (Low)**
- Cosmetic issues в CI/CD конфигурации
- Deprecated warnings
- Медленные, но работающие пайплайны
- Проблемы с notification'ами

### Escalation matrix

```
SEV-4 → On-call DevOps → рабочее время
SEV-3 → On-call DevOps → 1 час ответа
SEV-2 → Senior DevOps + Team Lead → 30 минут ответа
SEV-1 → DevOps Lead + Engineering Manager + CTO → немедленно
```

**Эскалация по времени:**
1. 0-15 мин: On-call инженер пытается решить проблему
2. 15-30 мин: Эскалация на старшего инженера
3. 30-60 мин: Эскалация на team lead
4. 60+ мин: Эскалация на management

### Communication channels

| Канал | Использование | Формат |
|---|---|---|
| **Slack #incidents** | Основной канал для инцидентов | Real-time updates |
| **PagerDuty** | Эскалация и on-call ротация | Alerts + phone calls |
| **Email** | Уведомления для широкой аудитории | Дайджесты и summary |
| **Status Page** | Публичный статус для клиентов | Автоматические обновления |
| **Zoom/Meet** | War room для SEV-1 инцидентов | Live discussion |
| **Jira/Issues** | Трекинг action items | Postmortem tasks |

### Rollback strategies

**Blue-Green Deployment**
- Два идентичных окружения (blue и green)
- Мгновенный переключение трафика
- Откат за секунды
- Требует двойного ресурса

**Canary Deployment**
- Постепенный rollout на часть инстансов
- Мониторинг метрик перед полным деплоем
- Откат при аномалиях
- Меньший риск, но медленнее

**Manual Rollback**
- Ручной trigger отката через пайплайн
- Полный контроль над процессом
- Медленнее автоматического
- Подходит для сложных случаев

**Rollback через Git**
- Revert коммита с изменениями
- Новый пайплайн с предыдущим кодом
- Прозрачность через git history
- Требует времени на сборку

### Postmortem process для CI/CD

1. **Сбор данных** — timeline инцидента, метрики, логи
2. **Root Cause Analysis** — 5 Whys, fishbone diagram
3. **Влияние** — количество затронутых проектов, время простоя
4. **Что сработало** — какие части response были эффективны
5. **Что улучшить** — gaps в процессе
6. **Action items** — конкретные задачи с владельцами и дедлайнами
7. **Review** — обзор postmortem с командой

---

## Практический блок

### Runbook для типичных CI/CD инцидентов

#### 1. Runner недоступен

```bash
# Проверка статуса runner'а
sudo gitlab-runner status
sudo gitlab-runner verify

# Перезапуск runner'а
sudo gitlab-runner restart

# Проверка логов
sudo journalctl -u gitlab-runner -f

# Проверка подключения к GitLab
curl -sSL https://gitlab.example.com/api/v4/version

# Если runner registered但 не работает
sudo gitlab-runner unregister --all-runners
sudo gitlab-runner register \
  --url https://gitlab.example.com \
  --token $RUNNER_TOKEN \
  --executor docker \
  --docker-image alpine:latest
```

#### 2. Pipeline failure на build stage

```bash
# Локальная проверка Dockerfile
docker build -t test-build .

# Проверка .gitlab-ci.yml с линтером
# https://gitlab.example.com/ci/lint

# Проверка переменных окружения
# Settings → CI/CD → Variables

# Очистка кеша
# Settings → CI/CD → Pipelines → Clear cache

# Проверка disk space на runner
df -h
docker system prune -f
```

#### 3. Deployment failure

```bash
# Проверка текущего состояния деплоя
kubectl rollout status deployment/app-name

# Просмотр rollout history
kubectl rollout history deployment/app-name

# Ручной rollback к предыдущей версии
kubectl rollout undo deployment/app-name

# Rollback к конкретной ревизии
kubectl rollout undo deployment/app-name --to-revision=3

# Проверка подов
kubectl get pods -l app=app-name
kubectl describe pod <pod-name>

# Логи упавшего пода
kubectl logs <pod-name> --previous
```

#### 4. Registry outage

```bash
# Проверка доступности registry
curl -sSL https://registry.example.com/v2/_catalog

# Проверка авторизации
echo $CI_REGISTRY_PASSWORD | docker login $CI_REGISTRY -u $CI_REGISTRY_USER --password-stdin

# Очистка локального кеша Docker
docker system prune -a -f

# Использование fallback registry
export CI_REGISTRY=fallback-registry.example.com

# Проверка disk space на registry
df -h /var/lib/registry
```

#### 5. Secret leak

```bash
# Немедленные действия:
# 1. Остановить все пайплайны
# 2. Ротировать скомпрометированные секреты
# 3. Проверить git history на наличие секретов

# Проверка git history
git log --all --oneline | head -20
git log -p --all -S "SECRET_VALUE"

# Очистка git history (если секрет в коммитах)
git filter-branch --force --index-filter \
  'git rm --cached --ignore-unmatch path/to/secret.file' \
  --prune-empty --tag-name-filter cat -- --all

# Git LFS для секретов
echo "*.env filter=gitcrypt diff=gitcrypt" > .gitattributes
```

### Скрипты автоматического отката

#### Rollback script для Kubernetes

```bash
#!/bin/bash
set -euo pipefail

DEPLOYMENT_NAME=${1:-"app-name"}
NAMESPACE=${2:-"production"}
MAX_RETRIES=3
RETRY_DELAY=10

echo "Starting rollback for $DEPLOYMENT_NAME in namespace $NAMESPACE"

# Проверка текущего статуса
CURRENT_STATUS=$(kubectl rollout status deployment/$DEPLOYMENT_NAME -n $NAMESPACE --timeout=10s 2>&1 || true)

if echo "$CURRENT_STATUS" | grep -q "successfully rolled out"; then
    echo "Deployment is already in good state. No rollback needed."
    exit 0
fi

# Выполнение rollback
for i in $(seq 1 $MAX_RETRIES); do
    echo "Rollback attempt $i of $MAX_RETRIES"
    
    kubectl rollout undo deployment/$DEPLOYMENT_NAME -n $NAMESPACE
    
    # Ожидание завершения
    if kubectl rollout status deployment/$DEPLOYMENT_NAME -n $NAMESPACE --timeout=120s; then
        echo "Rollback successful on attempt $i"
        
        # Верификация
        REVISION=$(kubectl rollout history deployment/$DEPLOYMENT_NAME -n $NAMESPACE | tail -1 | awk '{print $1}')
        echo "Current revision: $REVISION"
        
        # Проверка подов
        READY=$(kubectl get deployment $DEPLOYMENT_NAME -n $NAMESPACE -o jsonpath='{.status.readyReplicas}')
        DESIRED=$(kubectl get deployment $DEPLOYMENT_NAME -n $NAMESPACE -o jsonpath='{.spec.replicas}')
        
        if [ "$READY" = "$DESIRED" ]; then
            echo "All $DESIRED replicas are ready"
            echo "Rollback completed successfully"
            exit 0
        fi
    fi
    
    echo "Attempt $i failed, waiting before retry..."
    sleep $RETRY_DELAY
done

echo "Rollback failed after $MAX_RETRIES attempts"
exit 1
```

#### Rollback script для Docker Compose

```bash
#!/bin/bash
set -euo pipefail

COMPOSE_FILE=${1:-"docker-compose.yml"}
PREVIOUS_IMAGE=${2:-""}

echo "Starting rollback for Docker Compose services"

# Остановка текущих сервисов
docker-compose -f $COMPOSE_FILE down

# Если указана конкретная версия образа
if [ -n "$PREVIOUS_IMAGE" ]; then
    export IMAGE_TAG=$PREVIOUS_IMAGE
    echo "Rolling back to image: $PREVIOUS_IMAGE"
fi

# Запуск с предыдущей версией
docker-compose -f $COMPOSE_FILE up -d

# Верификация
sleep 10
HEALTHY=true
for service in $(docker-compose -f $COMPOSE_FILE ps --services); do
    STATUS=$(docker-compose -f $COMPOSE_FILE ps $service | grep -o "Up\|Exit" | head -1)
    if [ "$STATUS" != "Up" ]; then
        echo "Service $service is not healthy"
        HEALTHY=false
    fi
done

if [ "$HEALTHY" = true ]; then
    echo "Rollback completed successfully"
    exit 0
else
    echo "Rollback completed but some services are unhealthy"
    exit 1
fi
```

#### Git rollback script

```bash
#!/bin/bash
set -euo pipefail

COMMITS_BACK=${1:-1}
BRANCH=${2:-"main"}

echo "Rolling back $COMMITS_BACK commits on branch $BRANCH"

# Сохранение текущего состояния
CURRENT_COMMIT=$(git rev-parse HEAD)
echo "Current commit: $CURRENT_COMMIT"

# Определение коммита для отката
TARGET_COMMIT=$(git rev-parse HEAD~$COMMITS_BACK)
echo "Target commit: $TARGET_COMMIT"

# Revert коммитов
git revert --no-commit HEAD~$COMMITS_BACK..HEAD

# Создание коммита отката
git commit -m "Rollback: reverting last $COMMITS_BACK commits

Reverted from $CURRENT_COMMIT to $TARGET_COMMIT"

# Push изменений
git push origin $BRANCH

echo "Rollback completed. New commit created."
echo "To undo this rollback: git revert HEAD"
```

### Шаблоны коммуникации

#### Шаблон уведомления о начале инцидента

```
🔴 INCIDENT STARTED

Title: [CI/CD Incident] - Brief description
Severity: SEV-X
Start Time: YYYY-MM-DD HH:MM UTC
Duration: X minutes

Affected Systems:
- GitLab CI/CD pipelines
- Runner group: [name]
- Projects affected: [list]

Impact:
- Pipeline failures for [projects]
- Deployment blocked for [environments]
- Build queue increased to [number] jobs

On-call Engineer: [Name]
Next Update: YYYY-MM-DD HH:MM UTC

Status: Investigating
```

#### Шаблон обновления статуса

```
🟡 INCIDENT UPDATE

Title: [CI/CD Incident] - Brief description
Severity: SEV-X
Duration: X minutes
Status: Investigating / Identified / Monitoring / Resolved

Progress:
- [Timestamp] Initial investigation started
- [Timestamp] Root cause identified: ...
- [Timestamp] Mitigation applied: ...

Current Status:
- Runner health: [status]
- Pipeline queue: [number] jobs
- Affected projects: [number]

Next Update: YYYY-MM-DD HH:MM UTC
```

#### Шаблон закрытия инцидента

```
🟢 INCIDENT RESOLVED

Title: [CI/CD Incident] - Brief description
Severity: SEV-X
Duration: X minutes (HH:MM - HH:MM UTC)
Status: RESOLVED

Root Cause:
Brief description of what caused the incident.

Impact:
- Total downtime: X minutes
- Pipelines affected: X
- Deployments blocked: X
- Projects impacted: X

Resolution:
Description of how the incident was resolved.

Timeline:
- HH:MM - Incident detected
- HH:MM - Investigation started
- HH:MM - Root cause identified
- HH:MM - Fix applied
- HH:MM - Incident resolved

Postmortem scheduled: YYYY-MM-DD HH:MM UTC
```

### Шаблон postmortem для CI/CD

```markdown
# Postmortem: [Incident Title]

## Metadata
- **Date:** YYYY-MM-DD
- **Severity:** SEV-X
- **Duration:** X minutes
- **Author:** [Name]
- **Participants:** [List]

## Executive Summary
Brief description of what happened, impact, and resolution.

## Timeline
| Time (UTC) | Event |
|---|---|
| HH:MM | Incident detected |
| HH:MM | Investigation started |
| HH:MM | Root cause identified |
| HH:MM | Mitigation applied |
| HH:MM | Incident resolved |

## Root Cause
Detailed description of the root cause.

## Impact
- **Pipelines affected:** X
- **Deployments blocked:** X
- **Projects impacted:** X
- **MTTR:** X minutes
- **Users affected:** X

## What Went Well
- List of things that worked well during the incident

## What Went Wrong
- List of things that didn't work well

## Where We Got Lucky
- Things that could have been worse

## Action Items
| Action | Owner | Priority | Due Date | Status |
|---|---|---|---|---|
| [Action 1] | [Name] | P1 | YYYY-MM-DD | Open |
| [Action 2] | [Name] | P2 | YYYY-MM-DD | Open |

## Lessons Learned
Key takeaways from this incident.

##附录
- Links to logs, dashboards, and relevant resources
```

### Алерты для мониторинга пайплайнов

#### GitLab API мониторинг

```bash
#!/bin/bash
# Проверка статуса пайплайнов

PROJECT_ID=${1:-""}
GITLAB_URL=${2:-"https://gitlab.example.com"}
TOKEN=${3:-$GITLAB_TOKEN}

# Получение последних пайплайнов
PIPELINES=$(curl -sSL \
  -H "PRIVATE-TOKEN: $TOKEN" \
  "$GITLAB_URL/api/v4/projects/$PROJECT_ID/pipelines?per_page=10")

# Проверка на failed пайплайны
FAILED=$(echo $PIPELINES | jq -r '.[] | select(.status == "failed") | .id')

if [ -n "$FAILED" ]; then
    echo "ALERT: Failed pipelines detected"
    for pipeline in $FAILED; do
        echo "Pipeline $pipeline failed"
        
        # Отправка уведомления в Slack
        curl -sSL -X POST \
          -H 'Content-type: application/json' \
          --data "{\"text\":\"🔴 Pipeline #$pipeline failed in project $PROJECT_ID\"}" \
          $SLACK_WEBHOOK_URL
    done
fi

# Проверка времени выполнения
SLOW_PIPELINES=$(echo $PIPELINES | jq -r '.[] | select(.duration > 1800) | .id')

if [ -n "$SLOW_PIPELINES" ]; then
    echo "WARNING: Slow pipelines detected"
    for pipeline in $SLOW_PIPELINES; do
        DURATION=$(echo $PIPELINES | jq -r ".[] | select(.id == $pipeline) | .duration")
        echo "Pipeline $pipeline took $DURATION seconds"
    done
fi
```

#### Prometheus метрики для CI/CD

```yaml
# gitlab-ci-metrics.yml
groups:
  - name: gitlab_ci
    rules:
      - alert: GitLabCIPipelineFailed
        expr: gitlab_ci_pipeline_status{status="failed"} > 0
        for: 5m
        labels:
          severity: critical
        annotations:
          summary: "GitLab CI pipeline failed"
          description: "Pipeline {{ $labels.pipeline_id }} in project {{ $labels.project_id }} has failed"
      
      - alert: GitLabCIRunnerDown
        expr: gitlab_ci_runner_status == 0
        for: 2m
        labels:
          severity: critical
        annotations:
          summary: "GitLab CI runner is down"
          description: "Runner {{ $labels.runner_id }} is not responding"
      
      - alert: GitLabCIPipelineSlow
        expr: gitlab_ci_pipeline_duration_seconds > 1800
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "GitLab CI pipeline is running too long"
          description: "Pipeline {{ $labels.pipeline_id }} has been running for more than 30 minutes"
```

#### Alertmanager конфигурация

```yaml
# alertmanager.yml
global:
  resolve_timeout: 5m

route:
  group_by: ['alertname', 'project_id']
  group_wait: 10s
  group_interval: 10s
  repeat_interval: 1h
  receiver: 'slack-notifications'
  
  routes:
    - match:
        severity: critical
      receiver: 'pagerduty-critical'
      repeat_interval: 5m
    
    - match:
        severity: warning
      receiver: 'slack-warnings'
      repeat_interval: 30m

receivers:
  - name: 'slack-notifications'
    slack_configs:
      - api_url: $SLACK_WEBHOOK_URL
        channel: '#ci-cd-alerts'
        title: '{{ .GroupLabels.alertname }}'
        text: '{{ range .Alerts }}{{ .Annotations.description }}{{ end }}'
  
  - name: 'pagerduty-critical'
    pagerduty_configs:
      - service_key: $PAGERDUTY_SERVICE_KEY
        severity: '{{ if eq .GroupLabels.severity "critical" }}critical{{ else }}warning{{ end }}'
  
  - name: 'slack-warnings'
    slack_configs:
      - api_url: $SLACK_WEBHOOK_URL
        channel: '#ci-cd-warnings'
        title: '{{ .GroupLabels.alertname }}'
        text: '{{ range .Alerts }}{{ .Annotations.description }}{{ end }}'
```

---

## Дополнительная информация

### Связанные темы
- GitLab CI/CD basics
- Docker и Container Registry
- Kubernetes deployments
- Infrastructure as Code (Terraform, Ansible)
- Monitoring and Observability (Prometheus, Grafana, ELK)
- SRE practices
- Chaos Engineering
- Incident Management (ITIL)

### Чек-лист инцидент-менеджмента

#### До инцидента
- [ ] Настроен on-call ротация
- [ ] Есть runbook'и для типичных инцидентов
- [ ] Настроены алерты для пайплайнов
- [ ] Есть шаблоны коммуникации
- [ ] Проведены tabletop exercises
- [ ] Документированы escalation procedures
- [ ] Настроен status page

#### Во время инцидента
- [ ] Определить severity level
- [ ] Создать incident channel (Slack)
- [ ] Уведомить stakeholders
- [ ] Начать timeline документирование
- [ ] Назначить Incident Commander
- [ ] Проводить regular updates
- [ ] Применить mitigation措施

#### После инцидента
- [ ] Собрать данные для postmortem
- [ ] Провести postmortem meeting
- [ ] Заполнить action items
- [ ] Обновить runbook'и
- [ ] Улучшить алерты
- [ ] Проверить выполнение action items
- [ ] Провести knowledge sharing

#### Ключевые метрики для отслеживания
- MTTR (Mean Time To Recovery)
- MTTD (Mean Time To Detect)
- MTBF (Mean Time Between Failures)
- Change Failure Rate
- Deployment Frequency
- Lead Time for Changes
- Pipeline Success Rate
- Runner Availability
