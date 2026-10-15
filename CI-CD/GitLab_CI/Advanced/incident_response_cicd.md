**Актуально для:** GitLab 19.x / GitLab Runner 19.x

# Incident Response для CI/CD

## Определения

- **CI/CD Incident** — событие, нарушающее нормальную работу пайплайна, Runner'а, реестра артефактов или процесса деплоя. Включает сбои сборки, тестирования, доставки, а также проблемы с инфраструктурой CI/CD (registry, runner, агенты).
- **Rollback через CI/CD** — процесс отката к предыдущей рабочей версии приложения или конфигурации через пайплайн. Реализуется через dedicated rollback job, reuse существующего deploy stage или manual trigger отката.
- **MTTR (Mean Time To Recovery)** — среднее время восстановления пайплайна или процесса деплоя от момента обнаружения инцидента до полного восстановления рабочего состояния. В контексте DORA: **Failed Deployment Recovery Time**. Подробнее: **[Метрики DORA](../../Core_Concepts/dora_metrics.md)**.
- **MTTD (Mean Time To Detect)** — среднее время от начала инцидента до его обнаружения системой мониторинга или on-call инженером.
- **MTTA (Mean Time To Acknowledge)** — среднее время от срабатывания алерта до принятия инцидента дежурным.
- **Runner** — агент, выполняющий задачи CI/CD. В GitLab Runner исполняет jobs в изолированных окружениях (Docker, Kubernetes, shell).
- **Registry** — хранилище контейнерных образов и артефактов. В GitLab встроенный Container Registry хранит образы, связанные с пайплайнами.
- **Runbook** — пошаговая инструкция реакции на типовой инцидент, проверенная на DR-площадке и содержащая команды верификации.
- **Error Budget** — допустимый объём сбоев, связывающий надёжность и скорость выпуска. Примечание: общие принципы и связь с SLO описаны в **[Управлении инцидентами и постмортемах (SRE)](../../Core_Concepts/incident_response_sre.md)**.

## Основные концепции

### Архитектура CI/CD как система с точками отказа

Инцидент в CI/CD редко ограничивается одним компонентом. Типичный путь распространения:

```
Push → Webhook → GitLab Workhorse → Sidekiq → Pipeline Scheduler
  → Runner (concurrency limit, disk, network)
  → Executor (Docker/K8s/Shell)
  → Registry (pull/push, auth, storage driver)
  → Deployment (K8s API, SSH, agent)
```

Каждый этап — потенциальная точка отказа. При диагностике важно локализовать проблему на конкретном компоненте, а не останавливаться на общем "пайплайн упал".

### Типы CI/CD инцидентов

| Тип инцидента | Компонент | Типичная причина | Влияние |
|:---|:---|:---|:---|
| **Pipeline Failure** | Scheduler / Runner / Executor | Ошибка YAML, нехватка ресурсов, сбой executor | Блокирует деплой, замедляет релизы |
| **Runner Down** | Runner агент | Остановлен сервис, диск переполнен, сеть недоступна | Jobs ставятся в очередь, растёт время сборки |
| **Deployment Failure** | Deployment target | Неверный манифест, нехватка ресурсов в кластере, отказ API | Приложение в нерабочем состоянии |
| **Registry Outage** | Container Registry | Переполнен диск, истёк сертификат, сбой storage driver | Невозможно скачать/загрузить образы |
| **Secret Leak** | CI/CD Variables / Артефакты | Утечка через логи, артефакты, публичный репозиторий | Критическая угроза безопасности |
| **Pipeline Hang** | Scheduler / Runner / External service | Deadlock, зависший внешний вызов, неограниченный timeout | Занимает ресурсы, блокирует очереди |
| **Flaky Tests** | Test stage / Executor environment | Нестабильные тесты, race conditions, неидентичные окружения | Ложные срабатывания, потеря доверия |
| **Concurrency Exhaustion** | Runner fleet | Все слоты заняты, `concurrent` достиг лимита | Jobs pending, рост queue time |
| **Cache Corruption** | Runner cache / S3 backend | Повреждённый кэш, несовместимость версий инструментов | Непредсказуемые сборки, сложная диагностика |

### Severity levels для CI/CD инцидентов

Общие принципы классификации и escalation matrix описаны в **[Управлении инцидентами и постмортемах (SRE)](../../Core_Concepts/incident_response_sre.md)**. Ниже — CI/CD-специфичные примеры:

**SEV-1 (Critical)**
- Все пайплайны заблокированы (GitLab недоступен или Sidekiq не обрабатывает очереди)
- Деплой в production невозможен
- Утечка секретов или credentials через CI/CD
- Registry недоступен для всех проектов
- Compromise Runner'ов (подозрение на malicious job)

**SEV-2 (High)**
- Основные пайплайны (main, production) не работают
- Деплой в production затруднён
- Runner'ы не выполняют jobs > 30 минут
- Критические тесты падают на main ветке
- Registry недоступен для критических проектов

**SEV-3 (Medium)**
- Отдельные пайплайны падают
- Non-critical jobs завершаются с ошибками
- Увеличилось время сборки > 2x от baseline
- Flaky tests в main ветке
- Ротация секретов задержана

**SEV-4 (Low)**
- Cosmetic issues в CI/CD конфигурации
- Deprecated warnings
- Медленные, но работающие пайплайны
- Проблемы с notification'ами

### Роли в инцидентах CI/CD

| Аспект | DevOps | SRE | Sysadmin |
|:---|:---|:---|:---|
| **Детекция** | Алерты пайплайнов, связь с DORA-метриками | SLO пайплайнов, burn rate алерты, Alertmanager | Мониторинг железа/сети/дисков Runner'ов, uptime sensor |
| **Triage** | Оценка влияния на деплой и артефакты | Оценка SEV по Error Budget, назначение IC | Оценка инфраструктурного влияния (диск, сеть, питание) |
| **Mitigation** | Откат деплоя, feature flag, pause pipeline | Автономный откат по SLO, circuit breaker | Graceful shutdown Runner'а, drain нод, переключение VIP/HAProxy |
| **Investigation** | Логи пайплайна, артефакты, Git history | Трассировка, burn rate анализ, Golden Signals | journald, syslog, сетевые дампы, tcpdump, `dmesg` |
| **Postmortem** | Action items по пайплайну, SBOM, provenance | RCA, 5 почему, безвиновный разбор | Action items по инфраструктуре (железо, сеть, бэкапы) |
| **Prevention** | Quality Gates, SAST/SCA, иммутабельные артефакты | Chaos Engineering, SLO-бюджет, автономная доставка | Золотой образ, Packer, immutable infrastructure, rotation |

### Связь с наблюдаемостью

Без метрик/логов/трасс инцидент не диагностировать. Алерты должны быть actionnable и привязаны к SLO, а не к «шуму» ресурсов. См. **[Наблюдаемость пайплайнов](../../Core_Concepts/pipeline_observability.md)** и **[Мониторинг и метрики GitLab CI/CD](./monitoring_and_metrics.md)**.

## Практические сценарии

### Сценарий 1: Runner недоступен

**Признаки:**
- Jobs в статусе `pending` > 10 минут
- Метрика `gitlab_runner_jobs_running_total` = 0 при наличии `gitlab_ci_current_queue_size` > 0
- `journalctl -u gitlab-runner` показывает ошибки подключения

```bash
# 1. Проверка статуса runner'а
sudo gitlab-runner status
# → Active (running) / Inactive

# 2. Проверка connectivity к GitLab
sudo gitlab-runner verify
# → Verifying runner... is alive

# 3. Проверка логов
sudo journalctl -u gitlab-runner -n 50 --no-pager
# → ERROR: Failed to connect to GitLab

# 4. Проверка API GitLab
curl -sSL https://gitlab.example.com/api/v4/version
# → {"version":"19.4.0","revision":"..."}

# 5. Перезапуск runner'а
sudo gitlab-runner restart
sudo gitlab-runner status
# → Active (running)

# 6. Если runner registered, но не работает — перерегистрация
sudo gitlab-runner unregister --name "production-runner"
sudo gitlab-runner register \
  --url https://gitlab.example.com \
  --token $RUNNER_TOKEN \
  --executor docker \
  --docker-image alpine:latest \
  --tag-list "production,docker" \
  --run-untagged="false" \
  --locked="true"

# Валидация: проверьте, что runner появился в UI (Settings > CI/CD > Runners) со статусом online
```

**Валидация:** Запустите тестовый пайплайн. Job должен перейти в `running` в течение 1 минуты.

### Сценарий 2: Pipeline failure на build stage

**Признаки:**
- Job завершается с `exit code 1` или системной ошибкой
- Артефакт не создан
- Лог содержит ошибки сборки

```bash
# 1. Локальная проверка Dockerfile
docker build -t test-build .

# 2. Проверка .gitlab-ci.yml через CI Lint
# UI: https://gitlab.example.com/<project>/-/ci/lint

# 3. Проверка переменных окружения
# UI: Settings > CI/CD > Variables
# Убедитесь, что защищённые переменные доступны только для protected веток

# 4. Очистка кеша runner'а
sudo gitlab-runner cache-clear --all-runners

# 5. Проверка disk space на runner
df -h /var/lib/docker
# → /dev/sda1       500G  450G   50G  90% /

# 6. Очистка неиспользуемых ресурсов Docker
docker system prune -a -f --filter "until=24h"

# 7. Проверка network connectivity из runner'а
docker run --rm alpine:latest curl -sSL https://registry.example.com/v2/
# → {"repositories":[...]} или ошибка

# Валидация: перезапустите упавший job. Он должен завершиться успешно.
```

**Edge case:** Если проблема воспроизводится только на конкретном runner'е — проверьте `concurrent` в `/etc/gitlab-runner/config.toml`. При превышении лимита jobs будут ждать в очереди.

### Сценарий 3: Deployment failure

**Признаки:**
- Rolling update завис или не стартовал
- Pod'ы в статусе `CrashLoopBackOff` или `ImagePullBackOff`
- ReplicaSet не набирает желаемое количество подов

```bash
# 1. Проверка текущего состояния деплоя
kubectl rollout status deployment/app-name --timeout=30s
# → error: deployment "app-name" exceeded its progress deadline

# 2. Просмотр rollout history
kubectl rollout history deployment/app-name
# → REVISION  CHANGE-CAUSE
# → 42        deploy v1.7.3 (10:00)
# → 41        deploy v1.7.2 (2026-09-26)

# 3. Ручной rollback к предыдущей версии
kubectl rollout undo deployment/app-name
kubectl rollout status deployment/app-name --timeout=60s
# → deployment "app-name" successfully rolled out

# 4. Rollback к конкретной ревизии
kubectl rollout undo deployment/app-name --to-revision=41

# 5. Проверка подов
kubectl get pods -l app=app-name
kubectl describe pod <pod-name>

# 6. Логи упавшего пода
kubectl logs <pod-name> --previous
# → panic: runtime error: invalid memory address

# Валидация: после rollback проверьте health-эндпоинт
curl -fsS http://app.internal/healthz
# → {"status":"ok"}
```

**Edge case:** При использовании Helm, rollback выполняется через `helm rollback <release> <revision>`. Helm revision persists даже после удаления release — это позволяет откатиться на историческую ревизию.

### Сценарий 4: Registry outage

**Признаки:**
- Jobs падают с `pull access denied` или `connection refused`
- Метрика registry latency растёт
- `curl https://registry.example.com/v2/_catalog` возвращает 5xx

```bash
# 1. Проверка доступности registry
curl -sSL https://registry.example.com/v2/_catalog
# → {"repositories":[...]} или ошибка соединения

# 2. Проверка авторизации
echo $CI_REGISTRY_PASSWORD | docker login $CI_REGISTRY -u $CI_REGISTRY_USER --password-stdin
# → Login Succeeded

# 3. Проверка disk space на registry-ноде
df -h /var/lib/registry
# → /dev/sdb1       500G  450G   50G  90% /

# 4. Очистка локального кеша Docker
docker system prune -a -f --filter "until=24h"

# 5. Очистка неиспользуемых образов в registry (если есть admin-доступ)
docker exec -it registry registry garbage-collect --delete-untagged /etc/distribution/config.yml

# 6. Переключение на fallback registry
export CI_REGISTRY=fallback-registry.internal
export CI_REGISTRY_USER=$FALLBACK_REGISTRY_USER
export CI_REGISTRY_PASSWORD=$FALLBACK_REGISTRY_PASSWORD

# Валидация: запустите job, который пушит и пулит образ. Оба действия должны пройти.
```

**Edge case:** Registry certificate expiry. Проверяйте срок действия сертификата через `openssl s_client -connect registry.example.com:5000 -servername registry.example.com </dev/null 2>/dev/null | openssl x509 -noout -dates`.

### Сценарий 5: Secret leak

**Признаки:**
- Секрет обнаружен в логах пайплайна, артефактах или публичном репозитории
- Сработал scanner (gitlab-secrets, trufflehog)
- Подозрение на компрометацию CI/CD Variables

```bash
# Немедленные действия:
# 1. Остановить все пайплайны (Settings > CI/CD > Pipeline triggers > disable)
# 2. Ротировать скомпрометированные секреты
# 3. Проверить git history на наличие секретов

# 1. Проверка git history (предпочитайте git filter-repo вместо устаревшего git filter-branch)
git log --all --oneline | head -20
git log -p --all -S "SECRET_VALUE" | head -50

# 2. Ротация секретов:
# - CI/CD Variables в UI: Settings > CI/CD > Variables
# - Rotate → введите новое значение
# - Запустите пайплайн с новым секретом

# 3. Очистка git history (если секрет в коммитах)
# git filter-repo (предпочтительно):
pip install git-filter-repo
git filter-repo --path path/to/secret.file --invert-paths --force
git push origin --force --all

# 4. Проверка Audit Logs
# UI: Monitor > Audit Events
# Фильтр: "secrets" или имя скомпрометированной переменной

# 5. Отзыв токенов
# PAT: User Settings > Access Tokens > Revoke
# Project Token: Settings > Access Tokens > Revoke
# Trigger Token: Settings > CI/CD > Pipeline triggers > Delete

# Валидация: убедитесь, что старый секрет больше не работает. Запустите пайплайн с новым значением.
```

**Edge case:** Если секрет утек в артефакт, который был скачан — невозможно гарантировать его удаление у получателя. Ротация обязательна, даже если артефакт "удалён".

## Скрипты автоматического отката

### Rollback script для Kubernetes

```bash
#!/bin/bash
set -euo pipefail

DEPLOYMENT_NAME=${1:-"app-name"}
NAMESPACE=${2:-"production"}
MAX_RETRIES=3
RETRY_DELAY=10

echo "Starting rollback for $DEPLOYMENT_NAME in namespace $NAMESPACE"

# 1. Проверка текущего статуса
CURRENT_STATUS=$(kubectl rollout status deployment/$DEPLOYMENT_NAME -n $NAMESPACE --timeout=10s 2>&1 || true)

if echo "$CURRENT_STATUS" | grep -q "successfully rolled out"; then
    echo "Deployment is already in good state. No rollback needed."
    exit 0
fi

# 2. Выполнение rollback
for i in $(seq 1 $MAX_RETRIES); do
    echo "Rollback attempt $i of $MAX_RETRIES"
    
    kubectl rollout undo deployment/$DEPLOYMENT_NAME -n $NAMESPACE
    
    # 3. Ожидание завершения
    if kubectl rollout status deployment/$DEPLOYMENT_NAME -n $NAMESPACE --timeout=120s; then
        echo "Rollback successful on attempt $i"
        
        # 4. Верификация
        REVISION=$(kubectl rollout history deployment/$DEPLOYMENT_NAME -n $NAMESPACE | tail -1 | awk '{print $1}')
        echo "Current revision: $REVISION"
        
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

**Валидация:** После rollback проверьте health-эндпоинт и SLO-метрики. Скрипт возвращает 0 только при полной верификации.

### Rollback script для Docker Compose

```bash
#!/bin/bash
set -euo pipefail

COMPOSE_FILE=${1:-"docker-compose.yml"}
PREVIOUS_IMAGE=${2:-""}

echo "Starting rollback for Docker Compose services"

# 1. Остановка текущих сервисов
docker-compose -f $COMPOSE_FILE down

# 2. Если указана конкретная версия образа
if [ -n "$PREVIOUS_IMAGE" ]; then
    export IMAGE_TAG=$PREVIOUS_IMAGE
    echo "Rolling back to image: $PREVIOUS_IMAGE"
fi

# 3. Запуск с предыдущей версией
docker-compose -f $COMPOSE_FILE up -d

# 4. Верификация
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

### Git rollback script

```bash
#!/bin/bash
set -euo pipefail

COMMITS_BACK=${1:-1}
BRANCH=${2:-"main"}

echo "Rolling back $COMMITS_BACK commits on branch $BRANCH"

# 1. Сохранение текущего состояния
CURRENT_COMMIT=$(git rev-parse HEAD)
echo "Current commit: $CURRENT_COMMIT"

# 2. Определение коммита для отката
TARGET_COMMIT=$(git rev-parse HEAD~$COMMITS_BACK)
echo "Target commit: $TARGET_COMMIT"

# 3. Revert коммитов
git revert --no-commit HEAD~$COMMITS_BACK..HEAD

# 4. Создание коммита отката
git commit -m "Rollback: reverting last $COMMITS_BACK commits

Reverted from $CURRENT_COMMIT to $TARGET_COMMIT"

# 5. Push изменений
git push origin $BRANCH

echo "Rollback completed. New commit created."
echo "To undo this rollback: git revert HEAD"
```

**Валидация:** После rollback проверьте, что пайплайн запускается успешно и артефакты корректны.

## Шаблоны коммуникации

### Шаблон уведомления о начале инцидента

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

### Шаблон обновления статуса

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

### Шаблон закрытия инцидента

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

## Мониторинг пайплайнов

### GitLab API мониторинг

```bash
#!/bin/bash
# Проверка статуса пайплайнов через GitLab API

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

### Prometheus метрики для CI/CD

```yaml
# gitlab-ci-metrics.yml
groups:
  - name: gitlab_ci
    rules:
      - alert: GitLabCIPipelineFailed
        expr: pipelines_finished_total{status="failed"} > 0
        for: 5m
        labels:
          severity: critical
        annotations:
          summary: "GitLab CI pipeline failed"
          description: "Pipeline {{ $labels.pipeline_id }} in project {{ $labels.project_id }} has failed"
      
      - alert: GitLabCIRunnerDown
        expr: sum(gitlab_runner_jobs_running_total) == 0 and sum(gitlab_ci_current_queue_size) > 5
        for: 2m
        labels:
          severity: critical
        annotations:
          summary: "GitLab CI runner is down"
          description: "No active runners but jobs are pending"
      
      - alert: GitLabCIPipelineSlow
        expr: gitlab_ci_pipeline_time_to_finished_seconds > 1800
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "GitLab CI pipeline is running too long"
          description: "Pipeline {{ $labels.pipeline_id }} has been running for more than 30 minutes"

      - alert: GitLabCIRunnerDiskSpaceLow
        expr: node_filesystem_avail_bytes{mountpoint="/builds"} < 10737418240
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "GitLab Runner disk space low"
          description: "Runner {{ $labels.runner_id }} has less than 10GB free"
```

### Alertmanager конфигурация

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

## Дополнительная информация

### Связанные темы

- **[Управление инцидентами и постмортемы (SRE)](../../Core_Concepts/incident_response_sre.md)** — общие принципы, severity levels, escalation matrix, postmortem methodology
- **[Мониторинг и метрики GitLab CI/CD](./monitoring_and_metrics.md)** — GitLab-специфичные метрики, DORA в контексте GitLab
- **[Отладка и устранение неполадок](./debugging_and_troubleshooting.md)** — методология диагностики, `gitlab-runner exec`, CI_DEBUG_TRACE
- **[Стратегии развёртывания](../Deployment_Strategies/)** — Blue/Green, Canary, Rolling, автоматический откат
- **[Переменные и секреты GitLab CI](../Concepts/gitlab_ci_variables_secrets.md)** — иерархия переменных, безопасность, ротация
- **[Обзор Runner и Executor](./gitlab_ci_runners_executors.md)** — типы executor'ов, конфигурация, тюнинг
- **[Наблюдаемость пайплайнов](../../Core_Concepts/pipeline_observability.md)** — SLI/SLO, трейсы, Golden Signals для CI/CD
- **[Frontend incident response](../../Frontend_CI_CD/frontend_incident_response.md)** — фронтенд-специфичные инциденты (broken deploy, stale SW, CDN)
- **[Mobile incident response](../../mobile-ci-cd/incident-response-mobile.md)** — мобильные инциденты, hotfix, App Store/Google Play откат

### Чек-лист инцидент-менеджмента

#### До инцидента
- [ ] Настроен on-call ротация с escalation policy
- [ ] Есть runbook'и для типичных CI/CD инцидентов
- [ ] Настроены алерты для пайплайнов и Runner'ов
- [ ] Есть шаблоны коммуникации
- [ ] Проведены tabletop exercises
- [ ] Документированы escalation procedures
- [ ] Настроен status page (если требуется публичная коммуникация)
- [ ] Настроен CI Lint для валидации конфигурации
- [ ] Настроена автоматическая ротация секретов

#### Во время инцидента
- [ ] Определить severity level
- [ ] Создать incident channel (Slack/Teams)
- [ ] Уведомить stakeholders
- [ ] Начать timeline документирование
- [ ] Назначить Incident Commander
- [ ] Проводить regular updates (каждые 15-30 минут для SEV-1/SEV-2)
- [ ] Применить mitigation (откат, feature flag, pause pipeline)
- [ ] Сохранить логи и артефакты для расследования

#### После инцидента
- [ ] Собрать данные для postmortem (логи, метрики, timeline)
- [ ] Провести postmortem meeting в течение 48 часов
- [ ] Заполнить action items с владельцами и дедлайнами
- [ ] Обновить runbook'ы
- [ ] Улучшить алерты (если были пробелы в детекции)
- [ ] Проверить выполнение action items через 2 недели
- [ ] Провести knowledge sharing

#### Ключевые метрики для отслеживания
- MTTR (Mean Time To Recovery) — цель: < 30 минут для CI/CD
- MTTD (Mean Time To Detect) — цель: < 5 минут
- MTTA (Mean Time To Acknowledge) — цель: < 5 минут для SEV-1/SEV-2
- MTBF (Mean Time Between Failures)
- Change Failure Rate — доля неудачных деплоев
- Deployment Frequency
- Lead Time for Changes
- Pipeline Success Rate — доля успешных пайплайнов
- Runner Availability — доступность Runner'ов
- Queue Time — время ожидания job в очереди

### Типичные ошибки и решения

| Симптом | Причина | Решение | Роль |
|:---|:---|:---|:---|
| **Pipeline hangs indefinitely** | Нет `timeout` в job, зависший external service | Добавьте `timeout-minutes` в job; настройте circuit breaker для внешних вызовов | DevOps |
| **Jobs stuck in pending** | Все Runner'ы заняты, `concurrent` достиг лимита | Масштабируйте флот Runner'ов, проверьте `concurrent` в `config.toml` | Sysadmin |
| **Disk full on Runner** | Нет очистки кэша/workspace | `docker system prune -af`, ограничьте retention артефактов | Sysadmin |
| **Registry pull fails** | Истёк сертификат, disk full, auth expired | Проверьте срок сертификата, `df -h`, обновите токены | Sysadmin / DevOps |
| **Secret leak in logs** | Включён `CI_DEBUG_TRACE` на shared runner | Отключите debug, проверьте Audit Logs, ротируйте секрет | DevOps / SRE |
| **Flaky tests on CI** | Неидентичные окружения, race conditions | Используйте ephemeral runners, фиксируйте версии в lock-файлах | DevOps |
| **Deployment stuck in progress** | K8s API недоступен, неверный манифест | Проверьте `kubectl get events`, откатите через `kubectl rollout undo` | DevOps / SRE |
| **Runner not picking jobs** | Теги не совпадают, runner paused | Проверьте `tags` в задаче и настройки Runner'ов | DevOps |
| **Token expired/revoked** | Токен доступа к registry или API истёк | Обновите CI/CD Variables, проверьте `CI_JOB_TOKEN` | DevOps |
| **Pipeline success but app broken** | Нет smoke-тестов после деплоя | Добавьте smoke stage с healthcheck в пайплайн | DevOps |
| **Cache corruption** | Повреждённый кэш на S3 или локальный | Очистите кэш, проверьте целостность, используйте versioning | Sysadmin / DevOps |
| **Artifact retention exceeded** | Артефакты удалены, нужна старая версия | Настройте retention policy, хранитеSBOM отдельно | DevOps |
