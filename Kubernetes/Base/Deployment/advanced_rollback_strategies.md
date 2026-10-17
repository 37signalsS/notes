# Продвинутые стратегии отката Deployment

**Актуально для:** Kubernetes 1.30–1.32+

Практическое руководство для инженеров DevOps, SRE и системных администраторов по реализации отказоустойчивых стратегий отката (Rollback) в Kubernetes: от внутреннего механизма контроллера и аварийного ручного вмешательства до канареечного переключения трафика, интеграции с GitOps и защиты слоя данных. Без облачных абстракций, с фокусом на on-premise и bare-metal инсталляции.

## Предварительные требования (Prerequisites)

- Рабочий кластер Kubernetes v1.30+ (vanilla/kubeadm/RKE2 на bare-metal или виртуальных машинах).
- Установленный и настроенный `kubectl` с правами на управление ресурсами `apps/v1` (`Deployment`, `ReplicaSet`, `Pod`, `Service`).
- Базовое понимание жизненного цикла [Deployment](./index.md), [Lifecycle Management](./lifecycle_management.md) и [ReplicaSet](../replicaset.md).
- Установленные утилиты диагностики (`jq`, `curl`) и настроенный стек мониторинга (Prometheus / VictoriaMetrics + Alertmanager).

## 1. Определения

- **Rollback (Откат)** — процедура возврата приложения к ранее проверенной рабочей версии при обнаружении функциональных дефектов, деградации производительности или нарушении SLO. В Kubernetes откат Deployment не является «перемоткой времени назад», а представляет собой **Rollout Forward** — создание новой ревизии с восстановленным шаблоном пода (`spec.template`) из целевого исторического объекта `ReplicaSet`.
- **Revision (Ревизия)** — сохраненный снимок шаблона пода (`spec.template`), материализованный в кластере в виде отдельного объекта `ReplicaSet` с уникальным селектором `pod-template-hash` и порядковым номером в аннотации `deployment.kubernetes.io/revision`.
- **Automated Rollback (Автоматический откат)** — процедура отката, инициируемая автоматически CI/CD пайплайном, внешним оркестратором или системой мониторинга на основе превышения допустимого процента ошибок (5xx), роста латентности (P99/P95) или провала тестов приемки (Smoke/Synthetic checks).
- **Blast Radius Control (Управление областью поражения)** — ограничение доли пользователей и ресурсов кластера, затронутых сбоем или процессом отката, за счет применения канареечных долей трафика, лимитов `maxUnavailable` и бюджетов доступности `PodDisruptionBudget`.
- **GitOps Reconciliation Fight (Конфликт самоисцеления GitOps)** — состояние гонки, при котором оператор GitOps (например, ArgoCD) с включенным режимом `self-heal` или `prune` немедленно перезаписывает императивный откат, выполненный инженером через `kubectl rollout undo`, возвращая кластер в ошибочное состояние из Git.
- **Data/Schema Compatibility (Совместимость слоя данных)** — архитектурное состояние базы данных и постоянных хранилищ, при котором предыдущая версия кода приложения может продолжать работу с обновленной схемой БД без сбоев и потери консистентности.

## 2. Архитектура и механизм отката Deployment

### Внутренний механизм контроллера при откате

При выполнении команды `kubectl rollout undo` контроллер `Deployment` в составе `kube-controller-manager` производит серию детерминированных шагов согласования:

```text
[Команда kubectl rollout undo]
            ↓
1. Поиск ReplicaSet по аннотации deployment.kubernetes.io/revision
            ↓
2. Извлечение spec.template из целевого ReplicaSet
            ↓
3. Обновление spec.template в объекте Deployment (создание новой ревизии N+1)
            ↓
4. Запуск стандартного RollingUpdate:
   - Масштабирование целевого (старого) ReplicaSet вверх (replicas: 0 → N)
   - Масштабирование текущего (сбойного) ReplicaSet вниз (replicas: N → 0)
   - Соблюдение ограничений spec.strategy.rollingUpdate (maxSurge, maxUnavailable)
            ↓
5. Проверка readinessProbe и minReadySeconds для новых подов
```

Ключевые инженерные аспекты механизма:
1. **История монотонно растет:** Откат к ревизии 1 при текущей ревизии 3 создает ревизию 4, чей `spec.template` побайтово совпадает с ревизией 1.
2. **Откат подчиняется правилам RollingUpdate:** Контроллер не убивает все дефектные поды одновременно, если не настроена стратегия `Recreate`. Он соблюдает `maxUnavailable` и `maxSurge`.
3. **Зависимость от состояния подов:** Если предыдущий `ReplicaSet` использовал образ, который был удален из локального реестра (Registry Garbage Collection), откат перейдет в состояние `ImagePullBackOff` и зависнет до истечения `progressDeadlineSeconds`.
4. **Статус паузы (`spec.paused`):** Если Deployment находится в состоянии `paused: true`, команда `kubectl rollout undo` не выполнит масштабирование подов до тех пор, пока не будет вызван `kubectl rollout resume`.

### Матрица стратегий отката (SRE Decision Matrix)

| Стратегия | Механизм | Время реакции (MTTR) | Влияние на трафик | Риск конфликта с Git | Сфера применения |
|:---|:---|:---|:---|:---|:---|
| **Аварийный ручной (Manual CLI)** | `kubectl rollout undo` | Мгновенно (секунды) | Полная замена подов по правилам `RollingUpdate` | Высокий (при активном GitOps `self-heal`) | Критический отказ, инциденты SEV-1, ночные дежурства (On-call Break-Glass) |
| **CI/CD Gated Rollback** | Пайплайн: проверка `rollout status` + Smoke tests + `rollout undo` | Секунды — 2 минуты | Полная замена подов | Минимальный (пайплайн управляет релизом) | Плановые релизы через GitLab CI / Woodpecker / Drone |
| **Canary Traffic Rollback** | Мгновенный сброс веса трафика (Ingress canary weight → 0%) | Миллисекунды | Мгновенное изолирование сбойной версии от пользователей | Отсутствует (меняется только маршрутизация Ingress) | Высоконагруженные сервисы, канареечные релизы |
| **GitOps Revert** | `git revert HEAD` → push → operator sync | 1–3 минуты (цикл опроса Git) | Полная замена подов | Нулевой (Git остается источником правды) | Стандартная эксплуатация без жестких требований к секундному MTTR |

### Стейтфул-фактор: что НЕ восстанавливает откат Deployment

Типичная ошибка при проектировании процедур отката — предположение, что `kubectl rollout undo` возвращает систему в полностью исходное состояние.

1. **ConfigMap и Secret (при монтировании по имени):**
   Если конфигурация смонтирована по статическому имени (`name: app-config`), а изменения в ConfigMap были применены на месте (`in-place`), откат Deployment вернет старый бинарный образ/код, но он запустится с **новой (возможно, несовместимой) конфигурацией**.
   *Решение:* Использование иммутабельных версионированных ConfigMap (`immutable: true`) с добавлением хеша содержимого в имя (паттерн Kustomize `configMapGenerator`).
2. **Схема базы данных:**
   Если в рамках релиза выполнена деструктивная миграция (удаление колонки, изменение типов полей), откат пода к предыдущей версии приведет к падению старого кода из-за несоответствия схеме БД.
   *Решение:* Строгое следование паттерну **[Expand-Contract](../../../Databases/Concepts/migrations/expand_contract.md)** и подготовка процедур отката слоя данных (см. **[Стратегии отката данных](../../../Databases/Concepts/rollback_strategies.md)**).
3. **Хранилища PersistentVolume / файловые данные:**
   Данные, записанные дефектной версией на диск или в объектное хранилище (S3/MinIO), автоматически не удаляются и не модифицируются при откате подов.

## 3. Практические сценарии

### Сценарий 1: Аварийный откат через kubectl (SRE Runbook)

Стандартная процедура быстрого восстановления на production-кластере.

```bash
# 1. Просмотр истории ревизий с описанием причин
kubectl rollout history deployment/app-frontend -n production
# → REVISION  CHANGE-CAUSE
# → 1         Release v1.4.0 (initial)
# → 2         Release v1.4.1 (bugfix)
# → 3         Release v1.5.0 (corrupted release)

# 2. Детальная инспекция шаблона конкретной исторической ревизии
kubectl rollout history deployment/app-frontend -n production --revision=2

# 3. Предварительный просмотр (dry-run) изменений перед откатом
kubectl rollout undo deployment/app-frontend -n production --to-revision=2 --dry-run=server -o yaml | grep "image:"
# → image: internal-registry.local/apps/frontend:v1.4.1

# 4. Выполнение отката к проверенной ревизии
kubectl rollout undo deployment/app-frontend -n production --to-revision=2
# → deployment.apps/app-frontend rolled back

# 5. Ожидание завершения отката с фиксацией таймаута
kubectl rollout status deployment/app-frontend -n production --timeout=3m
# → Waiting for deployment "app-frontend" rollout to finish: 1 of 3 updated replicas are available...
# → deployment "app-frontend" successfully rolled out

# 6. Фиксация причины аварийного отката в аннотации
kubectl annotate deployment/app-frontend -n production \
  kubernetes.io/change-cause="EMERGENCY ROLLBACK: откат с ревизии 3 на ревизию 2 из-за деградации P99 latency" \
  --overwrite
# → deployment.apps/app-frontend annotated
```

### Сценарий 2: Автоматический откат в CI/CD пайплайне (GitLab CI)

Паттерн автоматической проверки состояния (Health Gating) внутри пайплайна с немедленным откатом при превышении таймаута или провале синтетического smoke-теста:

```yaml
deploy_production:
  stage: deploy
  image: internal-registry.local/devops/kubectl:1.31.1
  script:
    - export APP_NAME="app-frontend"
    - export NAMESPACE="production"
    
    # Запись причины развертывания
    - kubectl set image deployment/$APP_NAME frontend=$IMAGE_TAG -n $NAMESPACE
    - kubectl annotate deployment/$APP_NAME kubernetes.io/change-cause="Deploy $CI_COMMIT_SHORT_SHA by $GITLAB_USER_LOGIN" -n $NAMESPACE --overwrite
    
    # Контроль rollout с таймаутом
    - |
      if ! kubectl rollout status deployment/$APP_NAME -n $NAMESPACE --timeout=180s; then
        echo "CRITICAL: Rollout failed or timed out. Initiating automatic rollback..."
        kubectl rollout undo deployment/$APP_NAME -n $NAMESPACE
        kubectl rollout status deployment/$APP_NAME -n $NAMESPACE --timeout=120s
        echo "Rollback completed successfully"
        exit 1
      fi

    # Smoke-проверка доступности сервиса внутри кластера
    - |
      echo "Running post-deploy health check..."
      HEALTH_CODE=$(kubectl run smoke-check --rm -i --restart=Never --image=internal-registry.local/base/curl:8.9.0 -n $NAMESPACE -- \
        curl -s -o /dev/null -w "%{http_code}" http://$APP_NAME.$NAMESPACE.svc.cluster.local:8080/healthz)
      
      if [ "$HEALTH_CODE" != "200" ]; then
        echo "CRITICAL: Health check returned HTTP $HEALTH_CODE. Triggering automatic rollback..."
        kubectl rollout undo deployment/$APP_NAME -n $NAMESPACE
        kubectl rollout status deployment/$APP_NAME -n $NAMESPACE --timeout=120s
        exit 1
      fi
      echo "Deployment verified: HTTP 200 OK"
  rules:
    - if: $CI_COMMIT_BRANCH == "main"
```

### Сценарий 3: Канареечный откат на уровне Ingress-NGINX (on-premise)

При канареечном выпуске приложение разделяется на два `Deployment`: стабильный (`app-stable`) и канареечный (`app-canary`). При обнаружении аномалий откат заключается не в перезапуске контейнеров, а в мгновенном отсечении трафика от канарейки изменением веса маршрутизации.

Манифест канареечного Ingress:

```yaml
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: app-frontend-canary
  namespace: production
  annotations:
    nginx.ingress.kubernetes.io/canary: "true"
    nginx.ingress.kubernetes.io/canary-weight: "10"
spec:
  ingressClassName: nginx
  rules:
  - host: app.internal.company.net
    http:
      paths:
      - path: /
        pathType: Prefix
        backend:
          service:
            name: app-frontend-canary-svc
            port:
              number: 80
```

Процедура мгновенного аварийного отсечения канарейки:

```bash
# 1. Сброс веса канареечного трафика в 0% (время применения в NGINX < 1 секунды)
kubectl annotate ingress app-frontend-canary -n production \
  nginx.ingress.kubernetes.io/canary-weight="0" --overwrite
# → ingress.networking.k8s.io/app-frontend-canary annotated

# 2. Полное отключение канареечного правила (альтернативный вариант)
kubectl patch ingress app-frontend-canary -n production \
  --type=json -p='[{"op": "replace", "path": "/metadata/annotations/nginx.ingress.kubernetes.io~1canary", "value": "false"}]'
# → ingress.networking.k8s.io/app-frontend-canary patched

# 3. Изоляция подов канарейки для расследования (scale to 0 или заморозка)
kubectl scale deployment app-frontend-canary -n production --replicas=0
# → deployment.apps/app-frontend-canary scaled
```

### Сценарий 4: Разрешение конфликта GitOps при аварийном откате (Break-Glass Runbook)

Если кластер синхронизируется через ArgoCD с включенным `self-heal`, ручной `kubectl rollout undo` будет нейтрализован оператором в течение нескольких секунд. Для предотвращения этого применяется регламент аварийного вмешательства (Break-Glass).

#### Вариант А: Быстрый откат через Git (Рекомендуемый стандарт)

```bash
# 1. Откат последнего коммита в Git-репозитории конфигурации
git revert HEAD --no-edit
git push origin main
# → To git@internal-gitlab.local:k8s-infra/production.git
# →    def5678..abc1234  main -> main

# 2. Принудительный запуск немедленной синхронизации (без ожидания интервала опроса)
# Для ArgoCD:
argocd app sync production-frontend --prune
# → TIMESTAMP                  GROUP        KIND   NAMESPACE                  NAME    STATUS   HEALTH        HOOK  MESSAGE
# → 2026-10-13T18:50:12+03:00  apps   Deployment  production          app-frontend  Syncing  Progressing         
# → 2026-10-13T18:50:35+03:00  apps   Deployment  production          app-frontend   Synced       Synced
```

#### Вариант Б: Экстренная приостановка GitOps (Break-Glass для критических инцидентов)

```bash
# 1. Приостановка автоматической синхронизации
# В ArgoCD (отключение self-heal и auto-sync):
argocd app set production-frontend --sync-policy none
# → application 'production-frontend' updated

# 2. Безопасное выполнение прямого отката в кластере
kubectl rollout undo deployment/app-frontend -n production
kubectl rollout status deployment/app-frontend -n production --timeout=3m
# → deployment.apps/app-frontend successfully rolled out

# 3. После стабилизации сервиса: фиксация отката в Git-репозитории
git revert HEAD --no-edit && git push origin main

# 4. Возобновление штатной работы GitOps
# В ArgoCD:
argocd app set production-frontend --sync-policy automated --auto-prune --self-heal
```

### Сценарий 5: Обеспечение отката конфигураций (Иммутабельные ConfigMap)

Чтобы исключить расхождение версий бинарного кода и конфигурационных файлов при откате, конфигурации объявляются иммутабельными, а их имена версионируются хешем.

Манифест иммутабельного ConfigMap:

```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: app-frontend-config-a8f3b9c1
  namespace: production
immutable: true
data:
  config.json: |
    {
      "database_pool": 20,
      "log_level": "INFO",
      "feature_flag_new_billing": false
    }
```

Преимущества для процедуры отката:
1. Поле `immutable: true` блокирует любые попытки изменения содержимого со стороны API Kubernetes (`422 Unprocessable Entity`).
2. Каждый новый релиз создает ConfigMap с новым именем (`app-frontend-config-b9e4c1d2`).
3. Исторический `ReplicaSet` ревизии 1 ссылается на `app-frontend-config-a8f3b9c1`, а ревизии 2 — на `app-frontend-config-b9e4c1d2`.
4. При выполнении `kubectl rollout undo` поды автоматически возвращаются к корректной и неповрежденной конфигурации `app-frontend-config-a8f3b9c1`.

### Сценарий 6: Управление глубиной истории и экспорт ревизии

```bash
# 1. Проверка текущего лимита хранения ревизий ReplicaSet
kubectl get deployment app-frontend -n production -o jsonpath='{.spec.revisionHistoryLimit}'
# → 10

# 2. Установка оптимального лимита для production (баланс между etcd и глубиной отката)
kubectl patch deployment app-frontend -n production -p '{"spec":{"revisionHistoryLimit":5}}'
# → deployment.apps/app-frontend patched

# 3. Вывод всех дочерних ReplicaSet с их ревизиями и числом реплик
kubectl get rs -n production -l app.kubernetes.io/name=frontend \
  -o custom-columns=NAME:.metadata.name,REVISION:.metadata.annotations.deployment\.kubernetes\.io/revision,DESIRED:.spec.replicas,CURRENT:.status.replicas
# → NAME                            REVISION   DESIRED   CURRENT
# → app-frontend-6b8f9b9c9f         1          0         0
# → app-frontend-7c9f8a8b8e         2          3         3
# → app-frontend-8d7e6f5a4b         3          0         0

# 4. Извлечение манифеста пода из конкретного исторического ReplicaSet в файл для анализа
kubectl get rs app-frontend-6b8f9b9c9f -n production -o jsonpath='{.spec.template}' | jq . > restored-pod-template-rev1.json
```

## 4. Диагностика и устранение неполадок (Troubleshooting)

### Типовые проблемы при откате Deployment

| Симптом / Ошибка | Первопричина | Диагностика | Решение |
|:---|:---|:---|:---|
| `unable to find specified revision` | Целевой `ReplicaSet` был удален сборщиком мусора из-за превышения `revisionHistoryLimit`. | `kubectl get rs -n <ns> -l <selector>` | Откат невозможен через `rollout undo`. Выполнить повторный деплой манифеста из Git/архива. |
| `Deployment is paused` (откат принят, но поды не меняются) | У Deployment выставлен флаг `spec.paused: true`. Контроллер заморозил reconcile-логику. | `kubectl get deploy <name> -o jsonpath='{.spec.paused}'` | Выполнить `kubectl rollout resume deployment/<name>`. |
| `ImagePullBackOff` при откате к старой версии | Образ старой версии был вычищен из Container Registry или истек срок действия `imagePullSecrets`. | `kubectl describe pod <pod-name> \| grep -E "(Failed\|Error)"` | Восстановить образ в реестре, обновить секреты доступа или выполнить откат к альтернативной ревизии. |
| GitOps перезаписывает откат через 5–15 секунд | Включен `self-heal` в ArgoCD, признающий ручной откат дрифтом. | `argocd app get <name>` | Применить регламент Break-Glass (Сценарий 4) или выполнить `git revert`. |
| Старый код падает после отката (`CrashLoopBackOff` / 500 ошибки) | Схема БД изменена без обратной совместимости, либо ConfigMap обновлен in-place. | `kubectl logs <pod-name> --previous` | Проверить совместимость схемы БД. Откатить ConfigMap вручную или вернуть миграцию (если предусмотрен down-скрипт). |
| Откат завис в статусе масштабирования (`0 of N updated replicas`) | Блокировка со стороны `PodDisruptionBudget` (`minAvailable`) или нехватка ресурсов на нодах под `maxSurge`. | `kubectl describe pdb` и `kubectl get events` | Временно откорректировать PDB, освободить ресурсы узлов или изменить параметры `maxUnavailable`. |
| `field is immutable: spec.selector` | Попытка отката к ревизии с другой структурой селектора меток. | `kubectl describe rs <old-rs>` | Селектор меток неизменяем. Требуется удаление Deployment с флагом `--cascade=orphan` и пересоздание. |

### Пошаговый алгоритм диагностики зависшего отката

```bash
# Шаг 1: Проверка условий и статуса Deployment
kubectl describe deployment/app-frontend -n production | grep -A 10 "Conditions:"
# → Type           Status  Reason
# → ----           ------  ------
# → Available      True    MinimumReplicasAvailable
# → Progressing    False   ProgressDeadlineExceeded

# Шаг 2: Анализ событий в пространстве имен
kubectl get events -n production --sort-by='.lastTimestamp' --field-selector involvedObject.name=app-frontend
# → 2m   Warning   ProgressDeadlineExceeded   deployment/app-frontend   Deployment has timed out progressing

# Шаг 3: Проверка состояния подов целевого ReplicaSet
kubectl get pods -n production -l app.kubernetes.io/name=frontend -o wide
# → NAME                            READY   STATUS             RESTARTS   AGE
# → app-frontend-6b8f9b9c9f-x1z2a   0/1     CrashLoopBackOff   4          3m

# Шаг 4: Чтение логов аварийно завершившегося пода
kubectl logs app-frontend-6b8f9b9c9f-x1z2a -n production --previous --tail=50
# → 2026-10-13 18:52:10 ERROR: column "user_preferences" does not exist in table "users"
```

## 5. Лучшие практики (Best Practices)

1. **Регулирование `spec.revisionHistoryLimit`:**
   - Для production-сред держите значение в диапазоне `3–5`. Значение `0` полностью отключает возможность выполнения `kubectl rollout undo`. Значения больше `10` перегружают хранилище `etcd` метаданными неиспользуемых `ReplicaSet`.
2. **Обязательная фиксация причин релиза:**
   - Заполняйте аннотацию `kubernetes.io/change-cause` в CI/CD пайплайнах при каждом обновлении шаблона пода (`kubectl annotate deployment/<name> kubernetes.io/change-cause="Release vX.Y.Z: ticket SRE-123"`). Без нее `kubectl rollout history` отображает `<none>` вместо полезной информации.
3. **Использование иммутабельных конфигураций:**
   - Всегда включайте `immutable: true` в манифестах `ConfigMap` и `Secret` и используйте суффиксы-хеши в именах. Это гарантирует, что откат пода вернет его к исходному контексту конфигурации.
4. **Конфигурация параметров RollingUpdate:**
   - Не оставляйте значения по умолчанию (`25% / 25%`) без анализа емкости кластера.
   - Для приложений, чувствительных к деградации производительности: `maxUnavailable: 0`, `maxSurge: 25%` (гарантирует сохранение 100% рабочего пула при откате).
   - Для кластеров с жестким дефицитом CPU/Memory: `maxSurge: 0`, `maxUnavailable: 1` (исключает отказ по OOM/NoSchedule).
5. **Настройка `minReadySeconds`:**
   - Задавайте `minReadySeconds: 15..30`. Это заставляет контроллер выждать указанное время после перехода пода в статус `Ready`, прежде чем признать его `Available` и продолжить масштабирование. Это предотвращает ложноположительный откат на сервисах с отложенными сбоями при инициализации.
6. **Дисциплина миграций базы данных:**
   - Никогда не совмещайте деструктивные изменения базы данных и выпуск новой версии приложения в одном релизе. Всегда используйте двухфазный подход: сначала совместимое расширение схемы (Expand), затем релиз кода, и только после успешной стабилизации — сокращение старой схемы (Contract).
7. **Регулярные учения по аварийному откату (Rollback Game Days):**
   - Проверяйте работоспособность процедуры отката на тестовых и stage-контурах не реже одного раза в квартал: симулируйте `rollout undo`, отсечение канареечного Ingress и разрешение конфликтов GitOps.

## 6. Дополнительная информация

### Внутренние ссылки

- [Жизненный цикл Deployment](./lifecycle_management.md) — детальный разбор механики rollout, pause/resume, ReplicaSet и параметров обновления.
- [Манифест Deployment и лучшие практики](./deployment_manifest.md) — эталонные production-манифесты, параметры безопасности и надежности.
- [Диагностика и устранение неполадок](./troubleshooting.md) — общие сценарии сбоев в работе Deployment.
- [Progressive Delivery](./progressive_delivery.md) — канареечные и Blue-Green релизы с использованием Argo Rollouts и Flagger.
- [Deployment с GitOps](./deployment_with_gitops.md) — управление синхронизацией манифестов через ArgoCD.
- [Инцидент-менеджмент в CI/CD](../../../CI-CD/GitLab_CI/Advanced/incident_response_cicd.md) — регламенты реагирования на сбои пайплайнов и деплоев.
- [Обратно-совместимые миграции (Expand-Contract)](../../../Databases/Concepts/migrations/expand_contract.md) — методология сохранения совместимости слоя данных при откатах.
- [Стратегии отката данных](../../../Databases/Concepts/rollback_strategies.md) — откат миграций, транзакции DDL и согласованность хранилищ.
- [PodDisruptionBudget](../../Autoscaling/pod_disruption_budget.md) — обеспечение непрерывной доступности подов при плановом и внеплановом обновлении.
