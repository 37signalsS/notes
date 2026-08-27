# Прогрессивная доставка в GitOps: Argo Rollouts и Flagger

Прогрессивная доставка (canary, blue/green, A/B) — обязательный элемент production-зрелого GitOps: обычный RollingUpdate Kubernetes переключает трафик на новую версию до того, как метрики подтвердят ее здоровье. Два контроллера добавляют эту логику поверх GitOps-синхронизации: **Argo Rollouts** и **Flagger**.

## Предварительные требования

| Компонент | Требование |
| :--- | :--- |
| Argo Rollouts | Линейка v1.x; CLI `kubectl-argo-rollouts` для наблюдения и ручного управления |
| Flagger | Актуальная ветка 1.4x (релиз 1.44.0 — июль 2026; сборка под Kubernetes 1.36); CRD `flagger.app/v1beta1` |
| Управление трафиком | Service mesh (Istio/Linkerd/Kuma), ingress (NGINX, Traefik, Contour) или Gateway API v1.4 — для canary/A-B по весам; для blue/green Flagger умеет обходиться чистым Kubernetes |
| Метрики | Доступный Prometheus (или совместимый бэкенд) для автоматического анализа; load-tester для webhooks Flagger |
| GitOps-агент | Argo CD v3.x либо Flux v2.9.x ([сравнение](../argo_vs_flux_manifests.md)) |

Исходное состояние: приложение доставляется через GitOps как обычный `Deployment`, в кластере есть Prometheus со стандартными метриками запросов (`istio_requests_total` или эквивалент ingress).

## Определения

- **Прогрессивная доставка (Progressive Delivery)**: Семейство стратегий постепенного выпуска — Canary (пошаговое наращивание доли трафика), Blue/Green (параллельная версия с мгновенным переключением), A/B (разделение по заголовкам/cookie), Traffic Mirroring (копия трафика без ответов пользователям).
- **Argo Rollouts**: Контроллер проекта Argo, вводящий ресурс `Rollout` — замену Deployment с расширенными стратегиями. Шаги выпуска декларативно описаны в самом манифесте (`setWeight`, `pause`, `analysis`).
- **AnalysisTemplate / AnalysisRun**: CRD Rollouts: шаблон проверки (Prometheus-запрос + порог) и единичный прогон анализа. Провал AnalysisRun останавливает и откатывает rollout.
- **Flagger**: Контроллер прогрессивной доставки (из экосистемы Flux, работает и с Argo CD). Работает **поверх обычного Deployment**: сам создает канареечную копию, сервисы primary/canary и объекты маршрутизации (HTTPRoute/VirtualService), постепенно сдвигает веса и откатывает релиз при деградации SLI.
- **MetricTemplate**: CRD Flagger — переиспользуемое определение запроса к системе метрик; встроенные проверки `request-success-rate` и `request-duration` покрывают базовые случаи.
- **Manual gating**: Возможность приостановить выпуск и потребовать явного подтверждения человека (паузы Rollouts, confirm-rollout webhook Flagger).

## Базовые концепции

### Два подхода к канарейке

| Аспект | Argo Rollouts | Flagger |
| :--- | :--- | :--- |
| Модель ресурсов | Замена: манифест описывает `kind: Rollout` вместо Deployment | Надстройка: Deployment остается, рядом CRD `Canary` |
| Кто создает канарейку | Один ресурс Rollout управляет обеими версиями (revision-based) | Контроллер сам клонирует Deployment в `<name>-canary` |
| Описание шагов | В манифесте приложения (`steps`) — видно в PR | В отдельном CRD Canary — отделено от приложения |
| Анализ метрик | Inline `analysis:` в шагах или фоновый Background Analysis | `analysis.interval/threshold/metrics` в CRD + MetricTemplates |
| Изменение инфраструктуры | Нужен mesh/ingress, поддерживающий взвешенный трафик | То же для canary; blue/green работает без них |
| Порог входа | Переписывание манифестов приложений | Установка контроллера + один CRD на сервис |

Выбор: если команды владеют своими полными манифестами и хотят видеть стратегию выпуска прямо в PR — Rollouts; если платформенная команда хочет дать разработчикам «канарейку из коробки» без правки их манифестов — Flagger. Оба инструмента сочетаются с любым GitOps-агентом.

### Интеграция с синхронизацией GitOps

Ключевой контракт: **Git меняет желаемое состояние, контроллер доставки управляет процессом перехода**.

```text
Git commit (новый тег образа)
        │
        ▼
GitOps-агент синхронизирует ресурс          ← зона Argo CD / Flux
        │
        ▼
Rollout / Deployment изменен
        │
        ▼
PD-контроллер начинает выпуск               ← зона Rollouts / Flagger
   setWeight → pause → analysis → promote
        │
        ├── метрики ОК ────► 100% новой версии, статус Healthy
        └── метрики упали ►  откат к предыдущей версии, статус Degraded
```

Практические следствия:

1. **Откат = git revert не всегда нужен**: при провале анализа PD-контроллер сам вернет предыдущую ревизию. Git при этом продолжает указывать на «плохой» тег — коммит revert все равно обязателен, иначе следующий цикл синхронизации запустит неудачный выпуск заново.
2. **Статус OutOfSync у Argo CD — нормальное явление во время канарейки**, если анализ длится дольше интервала реконсиляции и PD-контроллер временно мутирует поля (например, образы сервисов). Настраивается через `ignoreDifferences` ([детали игнорирования](../ArgoCD/synchronization/ignore_differences.md)).
3. **Health-check для CRD Rollout нужно добавить вручную** — иначе Argo CD считает паузу между шагами деградацией (см. Сценарий 1).
4. **Flux завершает Kustomization статусом Ready сразу после применения** — он не ждет окончания анализа. Наблюдаемость выпуска строится на статусе самого Rollout/Canary и алертах ([уведомления](../gitops_notifications.md)).

### Канал обратной связи

Оба контроллера используют одну схему принятия решений:

- **Метрики**: запросы к Prometheus с порогами (`thresholdRange`). Базовые — success rate (не-5xx) и P99 latency; кастомные — любые PromQL (длина очереди, ошибки бизнес-логики).
- **Webhooks** (Flagger): `pre-rollout` (conformance-тесты до получения трафика), `rollout` (проверки на каждом шаге), `confirm-rollout` (ручной гейт), `post-rollout` (финализация).
- **Алерты**: события о начале/откате канарейки уходят в Slack/Teams/Discord — связка с [уведомлениями GitOps](../gitops_notifications.md) дает полную картину «коммит → деплой → результат анализа».

## Практические сценарии

### Сценарий 1: Canary через Argo Rollouts с доставкой Argo CD

Шаг 1 — манифест приложения становится `Rollout`:

```yaml
apiVersion: argoproj.io/v1alpha1
kind: Rollout
metadata:
  name: billing-api
  namespace: billing
spec:
  replicas: 10
  strategy:
    canary:
      canaryService: billing-api-canary     # Service для канареечных подов
      stableService: billing-api-stable
      trafficRouting:
        nginx:
          stableIngress: billing-api-ingress
      steps:
        - setWeight: 10
        - pause: { duration: 5m }
        - analysis:
            templates:
              - templateName: success-rate-check
        - setWeight: 50
        - pause: { duration: 10m }
        - analysis:
            templates:
              - templateName: success-rate-check
  selector:
    matchLabels: { app: billing-api }
  template:
    metadata:
      labels: { app: billing-api }
    spec:
      containers:
        - name: api
          image: ghcr.io/org/billing-api:v1.9.0
          readinessProbe: { httpGet: { path: /healthz, port: 8080 } }
```

Шаг 2 — шаблон анализа метрик:

```yaml
apiVersion: argoproj.io/v1alpha1
kind: AnalysisTemplate
metadata:
  name: success-rate-check
  namespace: billing
spec:
  args:
    - name: service-name
  metrics:
    - name: success-rate
      interval: 1m
      count: 5
      successCondition: result[0] >= 0.99
      failureLimit: 1                      # одна серия неудач = откат
      provider:
        prometheus:
          address: http://prometheus.monitoring:9090
          query: |
            sum(rate(nginx_ingress_controller_requests{service="{{ args.service-name }}",status!~"[45].*"}[2m]))
            /
            sum(rate(nginx_ingress_controller_requests{service="{{ args.service-name }}"}[2m]))
```

Шаг 3 — кастомный health check, чтобы Argo CD корректно интерпретировал паузы:

```yaml
# ConfigMap argocd-cm, ключ resource.customizations
resource.customizations.health.argoproj.io_Rollout: |
  hs := {}
  if obj.status ~= nil then
    if obj.status.conditions ~= nil then
      for i, condition in ipairs(obj.status.conditions) do
        if condition.type == "Progressing" and condition.reason == "Available" then
          hs.status = "Healthy"
        end
        if condition.type == "Progressing" and condition.reason == "Progressing" then
          hs.status = "Progressing"
        end
        if condition.type == "Degraded" then
          hs.status = "Degraded"
          hs.message = condition.message
        end
      end
    end
  end
  return hs
```

Проверка полного цикла:

```bash
kubectl argo rollouts get rollout billing-api -n billing --watch
# → Weight: 10   STEP: setWeight:10   DESIRED: 10 ...
# → ✔ Step: pause (5m)
# → Weight: 50   ... AnalysisRun billing-api-... Successful

# Ручное продвижение мгновенно (для демо):
kubectl argo rollouts promote billing-api -n billing --full

# Тест отката: вернуть старый тег в манифесте и наблюдать отмену
kubectl argo rollouts undo billing-api -n billing
# → rollout "billing-api" undone (v1 → v0)
```

### Сценарий 2: Canary через Flagger поверх обычного Deployment

Доставка — любой агент (пример ниже нейтрален: ресурс просто попадает в кластер через Git).

```bash
# Установка Flagger с провайдером Gateway API
helm repo add flagger https://flagger.app
helm upgrade -i flagger flagger/flagger \
  --namespace flagger-system \
  --set meshProvider=gatewayapi:v1 \
  --set metricsServer=http://prometheus.monitoring:9090
# -> flagger deployed
```

```yaml
apiVersion: flagger.app/v1beta1
kind: Canary
metadata:
  name: billing-api
  namespace: billing
spec:
  targetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: billing-api                    # существующий Deployment менять не нужно
  progressDeadlineSeconds: 600
  service:
    port: 8080
    hosts: ['api.example.com']
    gatewayRefs:
      - name: public-gateway
        namespace: gateway-system
  analysis:
    interval: 1m
    threshold: 5                         # 5 неудачных проверок подряд = откат
    maxWeight: 50                        # максимум трафика на канарейку
    stepWeight: 10                       # шаг наращивания за интервал
    metrics:
      - name: request-success-rate
        thresholdRange: { min: 99 }      # % не-5xx
        interval: 1m
      - name: request-duration
        thresholdRange: { max: 500 }     # P99, мс
        interval: 30s
    webhooks:
      - name: smoke-test
        type: pre-rollout                # до первого процента трафика
        url: http://flagger-loadtester.billing/
        timeout: 60s
        metadata:
          type: bash
          cmd: 'curl -sf http://billing-api-canary.billing:8080/healthz'
```

Что произойдет после обновления тега образа в Git: Flagger создаст `billing-api-canary` Deployment и пару сервисов, прогонит smoke-test, затем каждые 60 секунд будет поднимать вес на 10%, проверяя метрики; при достижении 50% и успехе всех проверок — продвинет версию в primary и обнулит канарейку. При деградации — вернет весь трафик primary и пометит выпуск failed.

Наблюдение:

```bash
kubectl get canaries.flagger.app -A
# → NAMESPACE   NAME          STATUS       WEIGHT   LASTTRANSITIONTIME
# → billing     billing-api   Progressing  40%      2026-08-24T12:41:00Z

watch kubectl get httproute -n billing
# → веса маршрута меняются каждый интервал анализа
```

### Сценарий 3: Blue/Green без service mesh

Для систем без L7-маршрутизатора Flagger предлагает blue/green на чистом Kubernetes: вместо весов используется количество итераций проверок перед переключением:

```yaml
spec:
  # targetRef/service — как в сценарии 2, но provider по умолчанию (kubernetes)
  analysis:
    iterations: 10                       # 10 итераций conformance/load-тестов
    interval: 1m
    mirror: false
    webhooks:
      - name: load-test
        type: rollout
        url: http://flagger-loadtester.billing/
        timeout: 60s
        metadata:
          cmd: 'hey -z 1m -q 10 -c 2 http://billing-api-primary.billing:8080/'
```

Трафик переключается на зеленую версию только после успешных проверок; при сбое зеленые поды масштабируются в ноль, а primary остается нетронутым. Эквивалент в Rollouts — стратегия `blueGreen` с `autoPromotionEnabled: false` и ручным подтверждением.

### Сценарий 4: Ручной гейт подтверждения выпуска

Регуляторные системы часто требуют явного решения человека перед полным переключением:

```bash
# === Rollouts: бесконечная пауза + ручное продвижение ===
# в steps заменить последний pause на:
#   - pause: {}            # без duration = ждать команды
kubectl argo rollouts status billing-api -n billing
# → PausePending
kubectl argo rollouts promote billing-api -n billing
# → rollout 'billing-api' promoted
```

```yaml
# === Flagger: гейт через confirm-rollout webhook ===
webhooks:
  - name: gate
    type: confirm-rollout              # выпуск не начнется без POST /gate/approve
    url: http://approval-service.platform/approve/billing-api
```

Гейт-сервис может интегрироваться с системой тикетов: аппрув в Jira автоматически вызывает endpoint — человек решает в привычном интерфейсе, аудит остается в Git и событиях.

### Сценарий 5: A/B-тестирование (маршрутизация по заголовкам/cookie)

Canary делит трафик случайно — каждый запрос может попасть в новую версию. A/B закрепляет пользователя за версией по признаку (заголовок, cookie, user-agent), что дает чистое сравнение поведения групп:

```yaml
apiVersion: flagger.app/v1beta1
kind: Canary
metadata:
  name: billing-api
  namespace: billing
spec:
  targetRef: {apiVersion: apps/v1, kind: Deployment, name: billing-api}
  service:
    port: 8080
    # Закрепление сессии: только Safari-клиенты видят канарейку,
    # остальные продолжают ходить в primary
    match:
      - headers:
          user-agent:
            prefix: Mozilla/5.0 (Macintosh; Intel Mac OS X) AppleWebKit/605
  analysis:
    interval: 1m
    iterations: 10            # фиксированное число проверок вместо весов
    threshold: 5
    metrics:
      - name: request-success-rate
        thresholdRange: {min: 99}
```

Нюансы:

- A/B во Flagger требует провайдера маршрутизации, поддерживающего матчинг заголовков (Istio, NGINX, Gateway API); на «чистом Kubernetes» недоступен.
- В Argo Rollouts эквивалент — шаги `experiment:` между `setWeight` (параллельный запуск обеих версий с анализом) либо header-маршрутизация через Istio VirtualService в `trafficRouting`. Отдельный ресурс `Experiment` полезен для **теневых прогонов**: новая версия получает трафик вне основного маршрута и не влияет на пользователей.

```yaml
# Rollouts: изолированный эксперимент над новой версией
apiVersion: argoproj.io/v1alpha1
kind: Experiment
metadata:
  name: billing-shadow
  namespace: billing
spec:
  duration: 30m
  progressDeadlineSeconds: 2200
  analyses:
    - templateName: success-rate-check
      args: [{name: service-name, value: billing-shadow}]
  templates:
    - name: canary
      selector:
        matchLabels: {app: billing-api}
      replicas: 2
      template:
        metadata: {labels: {app: billing-api}}
        spec:
          containers:
            - name: api
              image: ghcr.io/org/billing-api:v2.0.0-rc.1
```

```bash
kubectl get experiment billing-shadow -n billing
# → NAME             STATUS      MESSAGE
# → billing-shadow   Running     analysis successful so far
```

### Сценарий 6: Traffic Mirroring (теневой трафик)

Зеркалирование отправляет копию реального продового трафика в новую версию, не возвращая пользователю ее ответы. Единственный способ проверить поведение под настоящим профилем нагрузки до того, как версия получит хотя бы 1% живых пользователей:

```yaml
# Flagger: зеркалирование вместо наращивания веса
spec:
  analysis:
    interval: 1m
    iterations: 10        # 10 минут приема зеркального трафика
    threshold: 5
    mirror: true          # копия каждого запроса уходит в canary
    webhooks:
      - name: load-test
        type: rollout
        url: http://flagger-loadtester.billing/
        timeout: 90s
        metadata:
          cmd: 'hey -z 1m -q 10 -c 2 http://billing-api-primary.billing:8080/'
```

Ограничения, о которых стоит помнить:

- Поддерживается ограниченным набором прослоек (Istio, ingress-nginx) — проверяйте совместимость до внедрения;
- Канарейка получает **двойную нагрузку** на записи: зеркальные запросы доходят до БД/кешей. Side-effect-безопасность (идемпотентность, отдельные тестовые хранилища) — обязательное условие;
- Метрики анализа считаются по зеркальному трафику: ошибки новой версии видны сразу, пользователи их не замечают.

После успешного mirroring-этапа выпуск переходит к обычным весам (10% → 50% → 100%) или ручному гейту.

## Дополнительная информация

### Взаимодействие с механизмами GitOps

| Механизм | Как сочетается |
| :--- | :--- |
| Sync waves / dependsOn | PD-контроллер должен быть установлен раньше приложений (wave `-1` или зависимость инфраструктурной Kustomization) |
| Ignore differences | Временно мутируемые PD-контроллером поля (веса, селекторы сервисов) — кандидаты на игнорирование |
| Progressive Sync (fleet-level) | Разные уровни осторожности: Rolling Sync раскатывает версию по кластерам, canary — по трафику внутри кластера; вместе дают матрицу безопасности |
| Notifications | Статусы AnalysisRun/Canary транслируются в алерты; правило зрелых команд — алерт на каждый откат канарейки |
| Audit | Каждый шаг выпуска виден в событиях ресурсов — дополняет [трассируемость](./audit_logs.md) связкой PR → digest → AnalysisRun |

### Типовые проблемы и их решение

| Симптом | Причина | Решение |
| :--- | :--- | :--- |
| Argo CD показывает Rollout как Degraded во время плановой паузы | Отсутствует кастомный health check для CRD Rollout | Добавить Lua-настройку из Сценария 1 в `argocd-cm` |
| Канарейка перезапускается снова и снова | Изменения Deployment во время анализа триггерят новый цикл (Flagger) | Не пушить изменения в разгар анализа; проверить, что GitOps-агент не конфликтует мутациями (ignoreDifferences) |
| Анализ падает сразу, метрики пустые | Запрос Prometheus возвращает пустой ряд: неверные метки сервиса/namespace | Проверить запрос руками в Prometheus UI; учесть warm-up (initialDelay/первая итерация) |
| Flagger не создает HTTPRoute/VirtualService | Не заданы `hosts`/gatewayRefs либо meshProvider не совпадает с фактической сетевой прослойкой | Свернуть конфигурацию с документацией выбранного провайдера |
| Откат произошел, но Git все еще указывает на плохую версию | PD-откат локален для кластера | Всегда follow-up `git revert`; настроить алерт «canary failed» с ссылкой на MR |
| Вес трафика стоит на месте | Ingress/mesh не поддерживает канареечные аннотации/подмножества | Убедиться, что trafficRouting сконфигурирован именно под ваш ingress (nginx ≠ traefik ≠ istio) |

**Связанные документы:**
- [Канареечное развертывание](../../CI-CD/Deployment_Strategies/canary_deployment.md) — теория, метрики и требования к L7-трафику.
- [Обзор методологии GitOps](../GitOps_overview.md) — место прогрессивной доставки в методологии.
- [Уведомления в GitOps](../gitops_notifications.md) — алертинг статусов выпусков.
- [Feature Flags в GitOps](./feature_flags_gitops.md) — разделение deploy и release, комбинация с canary.
- [DORA-метрики](./dora_metrics_gitops.md) — как измерять эффект прогрессивной доставки (CFR, MTTR).

## Вопросы для собеседования

### Чем canary отличается от A/B-тестирования?
**Canary** делит трафик случайно по весам — проверяются технические характеристики версии (5xx, latency). **A/B** закрепляет пользователя за версией по признаку (заголовок, cookie) — сравнивается поведение групп (конверсия, воронка). Canary отвечает «не сломалась ли версия», A/B — «лучшая ли это версия».

### Почему после автоматического отката канарейки обязателен `git revert`?
PD-контроллер откатывает только состояние кластера; Git продолжает указывать на плохой тег. Следующий цикл синхронизации запустит неудачный выпуск заново. Revert коммита приводит источник правды в соответствие с реальностью.

### Что произойдет при UI-Rollback приложения Argo CD во время canary через Rollouts?
Argo CD вернет предыдущую ревизию манифестов, но контроллер Rollouts может продолжить собственный процесс (или конфликтовать с ним): правильный путь — откатывать через `kubectl argo rollouts undo` либо revert в Git. Ситуация подсвечивает правило: один владелец процесса выпуска.

### Когда Flagger предпочтительнее Argo Rollouts?
Когда платформенная команда хочет дать разработчикам «канарейку из коробки» без переписывания их манифестов: Flagger работает поверх обычного Deployment и сам создает все вспомогательные ресурсы. Rollouts выигрывают, когда команды владеют манифестами и хотят описывать стратегию выпуска прямо в PR.

### Как прогрессивная доставка влияет на DORA-метрики?
CFR снижается: провал ловится на 10% трафика и не становится полноценным инцидентом. MTTR снижается: откат автоматический за минуты. DF при этом может даже вырасти — страх выката уменьшается вместе с ценой ошибки.
