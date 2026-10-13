# DORA-метрики в GitOps: измерение скорости и стабильности доставки

**Актуально для:** Argo CD v2.12+ / v3.x, Flux v2.3+, Prometheus 2.50+ / 3.x, Grafana 10+/11+, Apache DevLake 1.0+, Kubernetes 1.28–1.32+ (on-premise / bare-metal)

Пять ключевых метрик DORA (Deployment Frequency, Lead Time for Changes, Change Failure Rate, Failed Deployment Recovery Time, Deployment Rework Rate) являются индустриальным стандартом оценки эффективности конвейера поставки программного обеспечения. В парадигме GitOps вся инфраструктура и состояние приложений декларативно фиксируются в репозитории Git, а контроллеры доставки непрерывно согласуют фактическое состояние кластера с эталонным. Это делает GitOps идеальной средой для объективного аудита: факт доставки — это наблюдаемое событие синхронизации и фиксации коммита в рантайме, а не статус завершения задачи во внешнем CI-раннере.

## Определения

- **DORA (DevOps Research and Assessment)**: Исследовательская методология, оценивающая баланс между скоростью внесения изменений (пропускная способность) и стабильностью производственной среды.
- **Deployment Frequency (DF)**: Частота успешного применения изменений в производственную среду (Production). В GitOps единицей измерения является успешная синхронизация и переход рабочих нагрузок в статус `Healthy` на целевой ревизии, а не коммит или запуск сборочного пайплайна.
- **Lead Time for Changes (LTFC)**: Время, проходящее от момента фиксации исходного кода разработчиком (мердж коммита в основную ветку приложения) до момента фактического запуска и успешного функционирования этого изменения в кластере Production.
- **Change Failure Rate (CFR)**: Доля изменений (деплоев), потребовавших аварийного вмешательства (откат `git revert`, хотфикс, ручной rollback или исправление конфигурации) из-за деградации производственной среды в течение установленного окна наблюдения.
- **Failed Deployment Recovery Time (FDRT)**: Время, необходимое для восстановления работоспособности сервиса после неудачного деплоя — от момента фиксации деградации или срабатывания алерта до возврата системы в состояние `Healthy` / `Ready`. Ранее в отчетах DORA именовалось Mean Time to Restore (MTTR).
- **Deployment Rework Rate (DRR)**: Доля деплоев, являющихся незапланированной повторной работой (хотфиксы, срочные патчи, исправления невыявленных дефектов), выполненных в течение заданного окна (например, 7 дней) после релиза.
- **Двухконтурная модель репозиториев (Two-Repository Model)**: Разделение контура исходного кода сервиса (`app-repo`) и контура декларативной конфигурации GitOps (`gitops-repo`).
- **Синхронизация (Sync / Reconcile)**: Процесс приведения состояния манифестов в кластере в точное соответствие с манифестами в Git силами контроллера (Argo CD Application Controller или Flux Kustomize/Helm Controller).
- **Уровни зрелости поставки (Performance Tiers)**: Пороговые значения ежегодных исследований DORA (бенчмарки 2025–2026):

| Уровень (Tier) | Deployment Frequency | Lead Time for Changes | Change Failure Rate | Failed Deployment Recovery Time | Deployment Rework Rate |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **Elite** | По требованию (несколько раз в день) | < 1 дня | < 4% | < 1 часа | < 4% |
| **High** | Ежедневно – еженедельно | 1 день – 1 неделя | 4–8% | < 1 дня | 4–8% |
| **Medium** | Еженедельно – ежемесячно | 1–4 недели | 8–16% | < 1 дня | 8–16% |
| **Low** | Реже одного раза в месяц | > 1 месяца | > 16% | > 1 недели | > 16% |

Пороговые значения служат индикатором здоровья процессов для инженерных команд и SRE, а не инструментом административного контроля (KPI).

## Базовые концепции и архитектура

### Сравнение сбора метрик: Push CI/CD против GitOps

В традиционной Push-модели процесс доставки завершается запуском команды `kubectl apply` или `helm upgrade` из временного runner-контейнера. Это создает фундаментальные искажения при сборе метрик:

```text
Push-модель (CI-centric):
[Commit] ──► [CI Build] ──► [CI Deploy Job] ──► API Server
                                 │
                   Ложный сигнал успеха: Job = Succeeded,
                   но поды падают в CrashLoopBackOff через 30 секунд.

GitOps-модель (Reconciliation loop):
[App Repo] ──► [CI Build & Image] ──► [GitOps Repo (SHA)]
                                              │ (Pull)
                                              ▼
                                    [GitOps Controller]
                                              │ (Sync & Health Check)
                                              ▼
                                    [Kubernetes Pods: Ready]
                   Объективный сигнал: Успех только при фактическом
                   переходе ресурсов в статус Healthy/Ready в кластере.
```

| Критерий | Push CI/CD | GitOps (Pull) |
| :--- | :--- | :--- |
| **Фиксация факта деплоя** | Лог завершения шага пайплайна | Метрика контроллера (`argocd_app_sync_total`, `gotk_reconcile_*`) |
| **Проверка работоспособности** | Требует самописных скриптов ожидания (`kubectl rollout status`) | Встроена в контроллер (Health Status Argo CD, Ready Condition Flux) |
| **Трассируемость ревизии** | Переменные окружения CI (могут теряться) | Жесткая привязка к Git commit SHA в `status.sync.revision` |
| **Учет ручных вмешательств** | Не фиксируется CI-системой | Автоматический откат или статус `OutOfSync` при дрейфе |
| **Точность таймингов** | Зависит от доступности runner-очередей | Фиксируется на уровне контроллера кластера |

### Архитектура сбора данных: сквозной Lead Time в двухконтурной модели

В корпоративных on-premise средах исходный код приложения и конфигурация окружений физически разнесены:
1. **Репозиторий исходного кода (`billing-app.git`)**: коммит разработчика $C_{app}$ с временной меткой $T_{commit}$.
2. **Пайплайн сборки (CI)**: сборка контейнера, публикация образа с неизменяемым дайджестом `image@sha256:...`.
3. **Репозиторий конфигурации (`cluster-gitops.git`)**: автоматический коммит бота (Renovate, Image Updater, CI-скрипт) $C_{gitops}$ с обновлением тега/дайджеста в Kustomize/Helm.
4. **Контроллер доставки (CD)**: обнаружение коммита, синхронизация и стабилизация подов в кластере Production в момент $T_{deploy}$.

```text
├───────────────────────── Сквозной Lead Time for Changes ─────────────────────────┤
┌──────────────┐          ┌──────────────┐            ┌──────────────┐          ┌──────────────┐
│   App Repo   │ ──(CI)──►│   OCI Reg    │ ──(Bot)──► │ GitOps Repo  │ ──(CD)──►│  K8s Prod    │
│  Commit SHA  │          │ Image Digest │            │ Manifest SHA │          │ Status Ready │
└──────────────┘          └──────────────┘            └──────────────┘          └──────────────┘
       ▲                                                                               ▲
       │                                                                               │
   T(commit) ──────────────────────────────────────────────────────────────────────► T(deploy)
```

> **Критическое правило для SRE/DevOps:** Если вычислять Lead Time исключительно по истории `gitops-repo`, замеряется не время поставки ценности, а лишь интервал опроса GitOps-контроллера (обычно 1–3 минуты). Настоящий DORA Lead Time требует сопоставления времени коммита из `app-repo` с моментом появления соответствующего артефакта в продакшен-кластере.

### Сигналы контроллеров доставки

Контроллеры экспортируют Prometheus-метрики и Kubernetes Events, которые формируют первичный поток данных:

| Сигнал доставки | Argo CD (on-premise) | Flux v2 (on-premise) |
| :--- | :--- | :--- |
| **Успешная доставка** | `argocd_app_sync_total{phase="Succeeded"}`, история `status.history[].revision` | `gotk_reconcile_condition{type="Ready", status="True"}`, `gotk_reconcile_duration_seconds_count{status="success"}` |
| **Длительность применения** | `argocd_app_sync_duration_seconds` (гистограмма) | `gotk_reconcile_duration_seconds` (гистограмма контроллеров) |
| **Сбой доставки (Sync Error)** | `argocd_app_sync_total{phase=~"Failed\|Error"}` | `gotk_reconcile_condition{type="Ready", status="False"}`, `gotk_reconcile_duration_seconds_count{status="error"}` |
| **Деградация в рантайме** | `argocd_app_info{health_status="Degraded"}` | `gotk_reconcile_condition{type="Stalled", status="True"}` |
| **События отката** | Появление `status.history[].rollback=true` или коммит `revert` в Git | Новый коммит `revert` в Git-источнике |

### Математические формулы расчета метрик в GitOps

1. **Deployment Frequency (DF)**:
   $$DF = \sum \Delta \text{argocd\_app\_sync\_total}\{\text{phase}=\text{"Succeeded"}, \text{project}=\text{"production"}\}$$
   Учитываются только уникальные ревизии в целевом namespace/project, исключая повторные reconciliation-проходы без изменения ревизии.

2. **Lead Time for Changes (LTFC)**:
   $$LTFC = T_{\text{first\_healthy\_prod}}(C_{app}) - T_{\text{author\_merge}}(C_{app})$$
   Где $C_{app}$ — коммит в основной ветке репозитория исходного кода.

3. **Change Failure Rate (CFR)**:
   $$CFR = \frac{N_{\text{failed\_sync}} + N_{\text{incidents\_in\_window}}}{N_{\text{total\_deployments}}} \times 100\%$$
   Где деплой помечается сбойным, если:
   - Фаза синхронизации завершилась со статусом `Failed` или `Error`;
   - Либо в течение временного окна наблюдения (обычно 1–4 часа после синхронизации) сработал критический алерт Alertmanager на деградацию SLO/сервиса.

4. **Failed Deployment Recovery Time (FDRT)**:
   $$FDRT = T_{\text{healthy\_recovery}} - T_{\text{alert\_firing\_or\_degraded}}$$
   В GitOps откат оформляется через `git revert` (создание нового коммита) либо через экстренный откат в UI/CLI Argo CD. Завершением считается момент возврата метрики здоровья приложения в статус `Healthy`.

5. **Deployment Rework Rate (DRR)**:
   $$DRR = \frac{N_{\text{hotfix\_or\_patch\_deployments}}}{N_{\text{total\_deployments}}} \times 100\%$$
   Доля синхронизаций ревизий, чьи сообщения коммитов содержат маркеры хотфиксов (`fix:`, `hotfix:`, `revert:`) или ссылки на тикеты инцидентов, примененных в течение 7 дней после мажорного релиза.

### Подводные камни и искажения измерений

- **Смешение сред (Dev/Stage/Prod):** Запросы PromQL без жесткой фильтрации по меткам `project="production"` или `dest_namespace="production"` завышают Deployment Frequency в десятки раз за счет тестовых сред.
- **Шум от ботов автоматизации (Renovate / Image Updater):** Фоновые обновления второстепенных зависимостей искусственно раздувают DF и создают видимость высокой активности. Рекомендуется выделять бот-деплои в отдельный дашборд.
- **Стирание истории в etcd (Kubernetes Event TTL):** По умолчанию события Kubernetes хранятся в `etcd` ровно 1 час (`--event-ttl=1h0m0s`). Расчет DORA на основе `kubectl get events` невозможен без долговременного экспорта в Loki или реляционную БД.
- **Ограничение истории ревизий в Argo CD:** По умолчанию параметр `spec.revisionHistoryLimit` равен 10. Если за сутки произошло 15 синхронизаций, первые 5 будут удалены из CRD `Application`, что исказит ретроспективный расчет при прямом опросе Kubernetes API.
- **Преждевременный расчет успеха:** Если считать деплой успешным в момент старта синхронизации, CFR окажется искусственно занижен, так как контроллер еще не дождался прохождения проб `ReadinessProbe` подами новой реплики.

## Практические сценарии и настройка

### Предварительные требования

Для развертывания контура измерения DORA-метрик в локальной инфраструктуре необходимы:

| Компонент | Минимальная версия | Назначение |
| :--- | :--- | :--- |
| **Kubernetes** | 1.28+ (on-premise / bare-metal) | Кластер выполнения рабочих нагрузок |
| **Argo CD / Flux** | Argo CD 2.12+ или Flux v2.3+ | GitOps-контроллеры с включенным Prometheus metrics endpoint |
| **Prometheus** | 2.50+ / 3.x | Сбор и хранение метрик контроллеров |
| **Loki** | 2.9+ / 3.x | Хранение структурированных журналов событий синхронизации |
| **Grafana** | 10.4+ / 11.x | Визуализация дашбордов и вычисление трендов |
| **Python** | 3.9+ (с библиотеками `requests`, `python-dateutil`) | Выполнение вспомогательных скриптов корреляции |

---

### Сценарий 1: Мониторинг Deployment Frequency и длительности синхронизации в Prometheus

Контроллеры Argo CD и Flux экспортируют метрики на эндпоинты метрик внутри кластера (`:8082` для `argocd-metrics`, `:8080` для контроллеров Flux).

#### 1. Метрики Argo CD в Grafana

```promql
# 1. Deployment Frequency: количество успешных синхронизаций за последние 30 дней
sum(increase(argocd_app_sync_total{project="production", phase="Succeeded"}[30d]))

# 2. Суточная частота деплоев (деплоев в день) за последние 7 дней с шагом 1d
sum by (name) (increase(argocd_app_sync_total{project="production", phase="Succeeded"}[1d]))

# 3. Средняя длительность синхронизации (секунды) за неделю
sum(rate(argocd_app_sync_duration_seconds_sum{project="production"}[7d]))
/
sum(rate(argocd_app_sync_duration_seconds_count{project="production"}[7d]))

# 4. Процент зависших или аварийных синхронизаций
(
  sum(rate(argocd_app_sync_total{project="production", phase=~"Failed|Error"}[1d]))
  /
  sum(rate(argocd_app_sync_total{project="production"}[1d]))
) * 100
```

#### 2. Метрики Flux v2 в Grafana

Для кластеров под управлением Flux аналогичные метрики собираются с `kustomize-controller` и `helm-controller`:

```promql
# 1. Deployment Frequency для Kustomization в namespace production
sum(increase(gotk_reconcile_duration_seconds_count{kind="Kustomization", namespace="production", status="success"}[30d]))

# 2. Частота деплоев HelmRelease
sum(increase(gotk_reconcile_duration_seconds_count{kind="HelmRelease", namespace="production", status="success"}[30d]))

# 3. Средняя длительность реконсиляции Kustomization
sum(rate(gotk_reconcile_duration_seconds_sum{kind="Kustomization", namespace="production"}[7d]))
/
sum(rate(gotk_reconcile_duration_seconds_count{kind="Kustomization", namespace="production"}[7d]))
```

**Валидация через curl:**

```bash
# Проверка поступления метрики Argo CD из Prometheus API
curl -s "http://prometheus.monitoring.svc.cluster.local:9090/api/v1/query?query=sum(increase(argocd_app_sync_total%7Bphase%3D%22Succeeded%22%7D%5B1h%5D))" | jq .
# → {
# →   "status": "success",
# →   "data": {
# →     "resultType": "vector",
# →     "result": [
# →       { "metric": {}, "value": [ 1740000000, "3" ] }
# →     ]
# →   }
# → }
```

---

### Сценарий 2: Расчет сквозного Lead Time через корреляцию Git ↔ Argo CD

Для преодоления проблемы разделения репозиториев (`app-repo` и `gitops-repo`) пайплайн CI при сборке артефакта записывает SHA коммита приложения в аннотацию манифеста Deployment:

```yaml
# Фрагмент k8s Deployment в gitops-repo
apiVersion: apps/v1
kind: Deployment
metadata:
  name: billing-service
  namespace: production
  annotations:
    app.company.internal/source-commit-sha: "a1b2c3d4e5f678901234567890abcdef12345678"
    app.company.internal/source-commit-time: "2026-10-10T08:15:00Z"
```

Скрипт сопоставляет историю синхронизаций Argo CD с временными метками коммитов в исходном репозитории:

```python
#!/usr/bin/env python3
"""
calculate_lead_time.py
Скрипт расчета Lead Time for Changes между коммитом в GitLab и деплоем в Argo CD.
Запуск в bare-metal окружении без внешних облачных зависимостей.
"""

import subprocess
import json
import sys
from datetime import datetime

APP_NAME = "billing-service"
ARGOCD_SERVER = "argocd.internal.infra"

def get_argocd_history(app_name):
    """Извлечение истории ревизий через CLI Argo CD."""
    cmd = ["argocd", "app", "history", app_name, "--output", "json"]
    res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if res.returncode != 0:
        print(f"Ошибка получения истории Argo CD: {res.stderr}", file=sys.stderr)
        return []
    return json.loads(res.stdout)

def get_git_commit_time(repo_path, commit_sha):
    """Получение времени автора коммита из локального Git-репозитория исходного кода."""
    cmd = ["git", "-C", repo_path, "log", "-1", "--format=%cI", commit_sha]
    res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if res.returncode != 0:
        return None
    raw_time = res.stdout.strip()
    return datetime.fromisoformat(raw_time.replace("Z", "+00:00"))

def main():
    repo_path = "/var/repos/billing-app.git"
    history = get_argocd_history(APP_NAME)
    if not history:
        sys.exit(1)

    lead_times = []
    print(f"Расчет Lead Time для приложения: {APP_NAME}")
    print(f"{'Revision SHA':<12} | {'Commit Time (UTC)':<20} | {'Deploy Time (UTC)':<20} | {'Lead Time (hours)':<15}")
    print("-" * 75)

    for record in history:
        deploy_str = record.get("deployedAt")
        rev_sha = record.get("revision")
        if not deploy_str or not rev_sha:
            continue

        deploy_time = datetime.fromisoformat(deploy_str.replace("Z", "+00:00"))
        commit_time = get_git_commit_time(repo_path, rev_sha)

        if commit_time:
            delta_hours = (deploy_time - commit_time).total_seconds() / 3600.0
            if delta_hours >= 0:
                lead_times.append(delta_hours)
                print(f"{rev_sha[:10]:<12} | {commit_time.strftime('%Y-%m-%d %H:%M'):<20} | {deploy_time.strftime('%Y-%m-%d %H:%M'):<20} | {delta_hours:<15.2f}")

    if lead_times:
        lead_times.sort()
        p50 = lead_times[len(lead_times) // 2]
        p90 = lead_times[int(len(lead_times) * 0.9)]
        print("-" * 75)
        print(f"Итоговая статистика (n={len(lead_times)}):")
        print(f"Медиана (p50): {p50:.2f} ч | 90-й перцентиль (p90): {p90:.2f} ч")
    else:
        print("Не найдено пересечений между ревизиями Argo CD и историей коммитов.")

if __name__ == "__main__":
    main()
```

**Ожидаемый вывод скрипта:**

```text
# → Расчет Lead Time для приложения: billing-service
# → Revision SHA | Commit Time (UTC)    | Deploy Time (UTC)    | Lead Time (hours)
# → ---------------------------------------------------------------------------
# → f4a1c89012   | 2026-10-10 11:20     | 2026-10-10 13:45     | 2.42           
# → 8b2e119a00   | 2026-10-11 09:05     | 2026-10-11 10:15     | 1.17           
# → c190de441a   | 2026-10-12 14:00     | 2026-10-12 17:30     | 3.50           
# → ---------------------------------------------------------------------------
# → Итоговая статистика (n=3):
# → Медиана (p50): 2.42 ч | 90-й перцентиль (p90): 3.50 ч
```

---

### Сценарий 3: Change Failure Rate и FDRT через события контроллеров и Alertmanager в Loki

Для честного измерения CFR и FDRT деплой связывается с алертами Alertmanager через отправку структурированных логов в Loki.

#### 1. Настройка Argo CD Notifications для экспорта событий в Loki

В ConfigMap `argocd-notifications-cm` настраивается Webhook-интеграция для отправки событий синхронизации:

```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: argocd-notifications-cm
  namespace: argocd
data:
  service.webhook.loki: |
    url: http://loki.logging.svc.cluster.local:3100/loki/api/v1/push
    headers:
      - name: Content-Type
        value: application/json

  template.app-sync-event: |
    webhook:
      loki:
        method: POST
        body: |
          {
            "streams": [
              {
                "stream": {
                  "app": "argocd",
                  "project": "{{.app.spec.project}}",
                  "application": "{{.app.metadata.name}}",
                  "event_type": "{{if .app.status.operationState.phase}}{{.app.status.operationState.phase}}{{else}}Unknown{{end}}",
                  "revision": "{{.app.status.sync.revision}}"
                },
                "values": [
                  [ "{{toNano .app.status.operationState.finishedAt}}", "Sync finished with phase {{.app.status.operationState.phase}}" ]
                ]
              }
            ]
          }

  trigger.on-sync-status: |
    - when: app.status.operationState.phase in ['Succeeded', 'Failed', 'Error']
      send: [app-sync-event]
```

Подписка на события в целевом приложении `Application`:

```yaml
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: billing-prod
  namespace: argocd
  annotations:
    notifications.argoproj.io/subscribe.on-sync-status.loki: ""
spec:
  project: production
  # ...
```

#### 2. Запросы LogQL для расчета CFR и FDRT в Grafana

```logql
# 1. Change Failure Rate: отношение сбойных фаз к общему числу синхронизаций
(
  sum(count_over_time({app="argocd", project="production", event_type=~"Failed|Error"}[30d]))
  /
  sum(count_over_time({app="argocd", project="production", event_type=~"Succeeded|Failed|Error"}[30d]))
) * 100

# 2. Корреляция: количество инцидентов деградации подов после деплоя
# Фильтрация событий алерта KubePodCrashLooping в пределах 2 часов после деплоя
count_over_time({namespace="production", alertname="KubePodCrashLooping"}[2h])
```

#### 3. Расчет FDRT при аварийном откате

При возникновении сбоя фиксация инцидента и времени его устранения рассчитывается по интервалу между переходом приложения в `Degraded` и возвратом в `Healthy`:

```promql
# Длительность нахождения приложения в статусе Degraded (секунды)
sum_over_time((argocd_app_info{project="production", health_status="Degraded"} == 1)[1h:1m]) * 60
```

---

### Сценарий 4: Развертывание и интеграция self-hosted Apache DevLake

В инфраструктурах без облачных SaaS-сервисов развертывается **Apache DevLake** — open-source платформа под лицензией Apache 2.0, предназначенная для централизованного сбора инженерных метрик (включая DORA) из on-premise GitLab, Gitea, Jira, SonarQube и Argo CD.

#### 1. Развертывание стека через Helm (on-premise)

```bash
# 1. Добавление официального репозитория
helm repo add devlake https://apache.github.io/incubator-devlake-helm
helm repo update

# 2. Создание файла локальных настроек с выделенным хранилищем (Ceph/NFS)
cat <<EOF > /tmp/devlake-values.yaml
replicaCount: 1
mysql:
  useExternal: false
  storage:
    storageClass: "local-fast-sc"
    size: 50Gi
grafana:
  useExternal: false
  adminPassword: "StrongLocalPassword2026"
service:
  type: ClusterIP
EOF

# 3. Установка в пространство имен devlake
helm upgrade --install devlake devlake/devlake -n devlake --create-namespace -f /tmp/devlake-values.yaml
# → Release "devlake" has been upgraded. Happy Helming!
```

#### 2. Подключение источников данных

1. Открыть веб-интерфейс конфигуратора Config UI (`http://devlake-ui.internal:4000`).
2. Добавить коннектор **GitLab**:
   - URL: `https://gitlab.company.internal`
   - Personal Access Token с правами `read_api`.
3. Добавить коннектор **Argo CD**:
   - URL: `https://argocd.company.internal`
   - Инфраструктурный токен учетной записи с правами `applications, get`.
4. Настроить проект сбора (Data Pipeline):
   - Scope: Репозитории `apps/billing` и манифесты `gitops/cluster-prod`.
   - В правилах трансформации (Transformation Rules) указать регулярное выражение для определения Production-деплоев: `.*production.*`.
5. Готовые дашборды DORA доступны в встроенной Grafana DevLake (`Dashboard -> DORA`).

## Операции и команды

Справочник базовых команд для извлечения сырых данных и валидации потока метрик.

### 1. Извлечение истории синхронизаций Argo CD

```bash
# Получение 5 последних ревизий приложения billing-prod
argocd app history billing-prod -o json | jq -r '.[] | [.id, .revision[0:10], .deployedAt] | @tsv'
# → 1	a1b2c3d4e5	2026-10-10T10:00:00Z
# → 2	b2c3d4e5f6	2026-10-11T12:30:00Z
# → 3	c3d4e5f6a1	2026-10-12T15:45:00Z

# Проверка текущего статуса здоровья и синхронизации
argocd app get billing-prod --output json | jq '{sync: .status.sync.status, health: .status.health.status, revision: .status.sync.revision[0:10]}'
# → {
# →   "sync": "Synced",
# →   "health": "Healthy",
# →   "revision": "c3d4e5f6a1"
# → }
```

### 2. Извлечение статусов реконсиляции Flux v2

```bash
# Список Kustomization в производственном контуре с ревизиями
flux get kustomizations -n production
# → NAME        REVISION        SUSPENDED       READY   MESSAGE
# → apps        main@sha1:c3d4e False           True    Applied revision: main@sha1:c3d4e
# → infra       main@sha1:89abc False           True    Applied revision: main@sha1:89abc

# Проверка истории HelmRelease
flux get helmreleases -n production
# → NAME        REVISION        SUSPENDED       READY   MESSAGE
# → redis       7.1.0           False           True    Helm install succeeded
```

### 3. Извлечение временных меток из локального Git-репозитория

```bash
# Время создания коммита в формате ISO 8601 UTC
git log -1 --format=%cI a1b2c3d4e5
# → 2026-10-10T09:45:12+00:00

# Выборка всех мердж-коммитов в ветке main за последние 14 дней
git log --merges --since="14 days ago" --pretty=format:'%H %ct %s' origin/main
# → a1b2c3d4e5f6 1740000000 Merge branch 'feature/billing-fix' into 'main'
```

### 4. Прямой запрос к API Prometheus для валидации счетчиков

```bash
# Текущее значение счетчика успешных синхронизаций
curl -s -G "http://prometheus.monitoring.svc.cluster.local:9090/api/v1/query" \
  --data-urlencode "query=argocd_app_sync_total{project=\"production\", phase=\"Succeeded\"}" \
  | jq -r '.data.result[] | [.metric.name, .value[1]] | @tsv'
# → billing-prod	142
# → auth-prod	89
```

## Диагностика и устранение неисправностей

| Симптом | Вероятная причина | Диагностика | Решение |
| :--- | :--- | :--- | :--- |
| **DF аномально завышена (сотни в день)** | В расчет попадают dev/stage окружения или периодические reconcile-проходы контроллера | `argocd app list -o json \| jq '.[].spec.destination'` | Добавить фильтрацию по метке `project="production"` и `dest_server` в запросах PromQL. Исключить авто-reconcile без изменения ревизии. |
| **Lead Time равен нулю или отрицательный** | Рассинхронизация системного времени (NTP) на серверах либо squash-мердж перезаписал SHA коммита | Выполнить `chronyc tracking` на нодах; сверить SHA из `argocd app history` с `git log` приложения | Настроить синхронизацию времени по NTP; при squash-политиках привязывать аннотацию с исходным SHA коммита в CI. |
| **CFR стабильно равен 0% при регулярных сбоях** | Откаты выполняются ручным `kubectl rollout undo` мимо Git, либо аварийные sync не фиксируются | Проверить наличие `OutOfSync` в `argocd_app_info` | Запретить ручной доступ в кластер (Read-Only для людей), настроить отправку алертов Degraded в контур расчета CFR. |
| **FDRT завышен до бесконечности** | Инцидент устранен в кластере, но алерт в Alertmanager остался «висеть» из-за отсутствия резолва | Проверить статус алертов: `curl http://alertmanager:9093/api/v2/alerts` | Настроить корректные параметры `resolve_timeout` в Alertmanager и пробы `readinessProbe` в подах. |
| **Rework Rate растет, а CFR остается низким** | «Тихие дефекты»: релизы проходят успешную синхронизацию, но содержат логические баги, исправляемые срочными хотфиксами | Запросить историю коммитов: `git log --grep="hotfix:" --since="30 days ago"` | Ужесточить гейты автоматизированного тестирования на этапе CI перед публикацией артефактов в OCI-реестр. |
| **Пропали исторические данные старше суток** | Лимит истории ревизий (`revisionHistoryLimit`) сбросил старые записи | Проверить манифест: `kubectl get app billing-prod -o yaml \| grep revisionHistoryLimit` | Увеличить `spec.revisionHistoryLimit` до 30; настроить долгосрочный экспорт событий в Loki или DevLake. |

**Команды оперативной диагностики:**

```bash
# 1. Проверка ошибок контроллера Argo CD за последний час
kubectl logs -n argocd -l app.kubernetes.io/name=argocd-application-controller --since=1h | grep -i "failed to sync"
# → time="2026-10-12T18:00:00Z" level=error msg="Failed to sync: resource Deployment/billing-service is degraded"

# 2. Проверка состояния контроллеров Flux v2
kubectl get pods -n flux-system
# → NAME                                       READY   STATUS    RESTARTS   AGE
# → helm-controller-7d8b5c4f9-2x1za            1/1     Running   0          42d
# → kustomize-controller-6f7d8c9b5-9q8w7       1/1     Running   0          42d
# → source-controller-5c8b7d9f6-1a2b3          1/1     Running   0          42d
```

## Лучшие практики и эксплуатационные рекомендации

1. **Изоляция бот-активности от метрик инженерной команды:**
   Коммиты инструментов автоматического обновления зависимостей (Renovate, Dependabot, Argo CD Image Updater) должны иметь явную метку автора (например, `author: bot@company.internal`). При расчете метрик человеческой поставки исключайте бот-коммиты, либо ведите для них отдельную дорожку в дашборде. Это предотвратит искажение реальной скорости работы команды.

2. **Защита от потери событий Kubernetes:**
   Поскольку стандартный TTL событий Kubernetes в `etcd` составляет 60 минут, категорически запрещено полагаться на `kubectl get events` для аналитики DORA. Настройте агент сбора событий (например, `eventrouter` или `vector`) для немедленной пересылки всех системных событий кластера в централизованный Loki или ClickHouse с глубиной хранения не менее 90–180 дней.

3. **Связь CFR и FDRT с политикой Error Budget (SRE):**
   Метрика Change Failure Rate не должна существовать изолированно. Свяжите ее с бюджетом ошибок (Error Budget): если CFR за спринт превышает 8% (переход в зону Medium/Low) или исчерпано более 50% бюджета ошибок сервиса, запуск новых фичей автоматически блокируется пайплайном в пользу стабилизации и устранения технического долга.

4. **Использование Feature Flags для снижения FDRT:**
   Применение практики Feature Flags (OpenFeature / flagd) позволяет разделить понятия **Deploy** (физическая доставка кода в кластер через GitOps) и **Release** (предоставление функционала пользователям). В случае обнаружения дефекта в проде время восстановления (FDRT) сокращается с минут (время прохождения пайплайна и синхронизации) до миллисекунд (переключение kill-switch флага в ConfigMap или платформе флагов без передеплоя).

5. **Отказ от использования DORA как карательного KPI (No-Blame Culture):**
   Попытка привязать премии инженеров к показателям Deployment Frequency или Lead Time приводит к феномену «игры с метриками» (Gaming the metrics): разработчики начинают дробить один логический коммит на 20 пустых изменений ради роста DF, либо скрывать инциденты во избежание роста CFR. DORA — это диагностический термометр процессов, а не оценочная ведомость сотрудников.

6. **Очистка и регламент хранения данных:**
   - Ротируйте логи деплоев и уведомлений в Loki с использованием retention-политик (минимум 90 дней для квартальной отчетности).
   - Для Argo CD поддерживайте `spec.revisionHistoryLimit: 30`, чтобы не перегружать размер объектов `Application` в хранилище `etcd`.

## Дополнительная информация

### Связанные документы базы знаний

- [Журналы аудита и трассируемость](./audit_logs.md) — организация долговременного хранения событий и расследование инцидентов доставки.
- [Feature Flags в GitOps](./feature_flags_gitops.md) — разделение deploy и release для радикального снижения FDRT.
- [Пайплайны продвижения в Kargo](./kargo_promotion_pipelines.md) — продвижение артефактов между средами и учет staged lead time.
- [Прогрессивная доставка в GitOps](./progressive_delivery_gitops.md) — канареечные раскатки через Argo Rollouts и Flagger для снижения CFR.
- [Уведомления в GitOps](../gitops_notifications.md) — настройка webhook-провайдеров и контроллера уведомлений.
- [Диагностика и мониторинг Argo CD](../ArgoCD/argocd_troubleshooting_and_monitoring.md) — детальный справочник метрик Prometheus для Argo CD.
- [Метрики DORA в классическом CI/CD](../../CI-CD/Core_Concepts/dora_metrics.md) — общее руководство по DORA для разнородных сред.

---

## Вопросы для собеседования

### 1. Как переход на GitOps принципиально влияет на четыре ключевые метрики DORA?
**Ответ:**
- **Deployment Frequency (DF):** Возрастает благодаря автоматизации и доверию к процессу. Релизы становятся маленькими и частыми.
- **Lead Time for Changes (LTTC):** Может визуально вырасти, если время ожидания промоушена между средами (`dev` $\to$ `prod`) учитывается в метрике, но чистое время доставки после аппрува сокращается до минут.
- **Change Failure Rate (CFR):** Резко снижается, так как все манифесты проходят статические линтеры в PR, а прогрессивная доставка (Argo Rollouts / Flagger) локализует сбои на 5–10% трафика.
- **Failed Deployment Recovery Time (FDRT / MTTR):** Сокращается с десятков минут до секунд благодаря мгновенному `git revert` или откатным механизмам автоматических канареек по метрикам Prometheus.

### 2. В чем сложность расчета метрики Lead Time for Changes (LTTC) в архитектуре с разделением на App Repo и Config Repo?
**Ответ:** Возникает проблема выбора «точки отсчета»:
- Если мерить от коммита разработчика в App Repo до выхода в прод — в метрику попадает время нахождения фичи в QA/staging, что отражает организационные задержки, а не скорость инженерного конвейера.
- Если мерить от коммита в Config Repo до синхронизации Argo CD — метрика покажет идеальные 2 минуты, маскируя реальное время ожидания релиза.
- **Правильное решение:** Разделять метрику на два плеча: *Code Lead Time* (от коммита разработчика до сборки артефакта в реестре) и *Deployment Lead Time* (от создания MR на промоушен в продакшен-оверлей до подтверждения успешной синхронизации в кластере).

### 3. Что считается фактом деплоя (Deployment Event) в GitOps для метрики Deployment Frequency?
**Ответ:** Коммит в Git или успешное завершение CI-раннера **не являются** деплоем, так как манифест может зависнуть в очереди или упасть с ошибкой валидации API-сервера. Фактом деплоя в GitOps признается только событие, когда GitOps-контроллер успешно применил манифест к кластеру и поды перешли в состояние готовности: в Argo CD это статус `SyncStatus=Synced` одновременно с `HealthStatus=Healthy` для целевого объекта `Application`.

### 4. Считается ли автоматический откат канареечного релиза инцидентом при расчете Change Failure Rate (CFR)?
**Ответ:** Зависит от уровня зрелости SRE. В строгой трактовке канарейка — это защитный механизм пред-релизной проверки. Если канареечный анализ зафиксировал всплеск 5xx ошибок на 5% пользователей и Flagger вернул трафик на базовую версию за 60 секунд без деградации SLA сервиса, это классифицируется как **успешно предотвращенный сбой**, а не падение продакшена (CFR не увеличивается). Если же дефект пробил канареечные фильтры или привел к порче данных в базе данных, потребовав вмешательства дежурного инженера — событие обязано учитываться в CFR.

### 5. Как организовать сбор метрик DORA в On-Premise инфраструктуре без покупки облачных SaaS-решений?
**Ответ:** Стек строится на opensource-компонентах:
1. **События CI:** GitLab CI через вебхуки шлет события `pipeline_success` в Vector или специализированный экспортер (`gitlab-ci-pipelines-exporter`).
2. **События CD:** контроллер `argocd-notifications` или экспорт логов `argocd-application-controller` передает события перехода приложений в `Synced & Healthy` в Prometheus через метрику `argocd_app_sync_total`.
3. **Хранение и визуализация:** Prometheus агрегирует временные ряды, а стандартный дашборд Grafana на базе PromQL вычисляет перцентили Lead Time и частоту деплоев за последние 30/90 дней.
