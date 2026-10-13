# Production Checklist для Deployment в Kubernetes

**Актуально для:** Kubernetes 1.30–1.32+

Комплексный контрольный список проверок (Production Readiness Review) для развертывания и обновления stateless-нагрузок в промышленных кластерах Kubernetes на bare-metal и локальной инфраструктуре. Руководство охватывает подготовку манифестов, верификацию цепочки поставок, аудит ресурсов и безопасности, непрерывный контроль процесса раскатки, валидацию сетевой связности и телеметрии, а также сценарии экстренного отката для инженеров DevOps, SRE и системных администраторов.

## Предварительные требования (Prerequisites)

- **Рабочий кластер Kubernetes:** версии 1.30–1.32+ (на базе `kubeadm`, RKE2 или K3s на bare-metal серверах или локальных гипервизорах) со стабильной API-группой `apps/v1`.
- **Утилиты командной строки и окружение:**
  - `kubectl` актуальной версии (в пределах ±1 minor от версии кластера). Флаг `--record` окончательно удален в версии 1.24; документирование причин изменений осуществляется исключительно через аннотацию `kubernetes.io/change-cause`.
  - `kubeconform` (v0.6.7+) для строгой валидации схем манифестов без необходимости подключения к кластеру.
  - `trivy` (v0.50+) для сканирования образов на уязвимости (CVE) и проверки конфигураций.
  - `cosign` (v2.2+) для проверки криптографических подписей образов из локального реестра.
  - `crane` (v0.19+) или `skopeo` (v1.14+) для инспекции метаданных и манифестов контейнеров в приватном реестре.
  - `jq` (v1.6+) и `curl` (v7.80+) для парсинга JSON-вывода и выполнения синтетических smoke-проверок.
- **Инфраструктурные компоненты (On-Premises):**
  - Приватный реестр контейнеров (Harbor или локальный OCI-реестр) с поддержкой immutable tags и сканирования уязвимостей.
  - Система мониторинга и сбора метрик: Prometheus v2.x/v3.x, `kube-state-metrics` v2.x и Alertmanager.
  - Система сбора логов: Fluent Bit, Vector или Promtail в связке с локальным хранилищем (Loki / ClickHouse).
  - Настроенный Ingress-контроллер (NGINX Ingress Controller или Envoy Gateway) и CoreDNS.
- **Права доступа (RBAC):**
  - Для инженера или сервисного аккаунта CI/CD требуются права на операции `get`, `list`, `watch`, `apply`, `patch`, `diff` для ресурсов `deployments`, `replicasets`, `pods`, `events`, `services`, `endpointslices`, `configmaps`, `secrets` в целевом пространстве имен.

---

## 1. Определения

- **Production Checklist (Контрольный список промышленной готовности)** — регламентированный перечень технических критериев и проверок, выполнение которых гарантирует соответствие развертываемого сервиса стандартам отказоустойчивости, безопасности, наблюдаемости и сетевой изоляции перед допуском в эксплуатацию.
- **Quality Gate (Шлюз качества)** — автоматизированный барьер в конвейере доставки или регламенте эксплуатации, блокирующий переход на следующий этап жизненного цикла при несоблюдении хотя бы одного порогового значения (например, наличие критических CVE, превышение лимитов ресурсов или сбой smoke-тестов).
- **Pre-flight Validation (Предрелизная проверка)** — комплекс статических и динамических тестов конфигурации, выполняемых до применения изменений в рабочей среде (валидация схемы OpenAPI, сопоставление различий `kubectl diff`, аудит квот и прав доступа).
- **Rollout Gate (Шлюз раскатки)** — фаза непрерывного мониторинга прогресса перехода на новую версию пода, контролирующая соблюдение параметров `maxSurge`, `maxUnavailable`, готовность контейнеров и отсутствие системных предупреждений.
- **Post-deploy Observability Gate (Пострелизный шлюз наблюдаемости)** — этап верификации функционального здоровья приложения после переключения рабочего трафика на основе четырех золотых сигналов SRE (Golden Signals) и отсутствия активных алертов.
- **Триада проб (Health Probes Triad)** — раздельные механизмы мониторинга жизненного цикла контейнера со стороны `kubelet`:
  - `startupProbe` — задерживает выполнение остальных проверок до завершения «тяжелой» инициализации приложения.
  - `livenessProbe` — определяет необходимость перезапуска зависшего контейнера (`kubelet` перезапускает процесс при сбое).
  - `readinessProbe` — определяет готовность контейнера принимать сетевой трафик (при сбое IP-адрес пода исключается из `EndpointSlice`).
- **PodDisruptionBudget (PDB)** — декларативное ограничение допустимого числа одновременно недоступных реплик при добровольных прерываниях (плановое обслуживание узлов `kubectl drain`, обновление ядра ОС на bare-metal).
- **Graceful Shutdown (Плавное завершение)** — детерминированный цикл остановки пода, при котором контейнер успевает завершить обработку активных клиентских соединений до получения фатального сигнала `SIGKILL` (координация хука `lifecycle.preStop`, таймаута `terminationGracePeriodSeconds` и синхронизации `EndpointSlice`).
- **Zero-Downtime Rollout** — процесс обновления приложения, при котором клиенты не получают ошибок разрыва соединения (502 Bad Gateway / Connection Refused) за счет непрерывного наличия минимально необходимого числа работоспособных реплик.
- **Rollback Budget (Бюджет на откат)** — регламентированное предельное время и пороговые показатели деградации сервиса (например, рост ошибок 5xx выше 1% в течение 60 секунд), по достижении которых автоматически инициируется откат к предыдущей стабильной ревизии.

---

## 2. Базовые концепции и архитектура

### Архитектура многоуровневых шлюзов качества (Quality Gates)

Надежность промышленной эксплуатации достигается за счет разделения процесса развертывания на последовательные шлюзы верификации:

```text
[ Манифест + Образ ]
        │
        ▼
┌─────────────────────────────────────────────────────────────┐
│ 1. Pre-deploy Gate (Статика, безопасность, ресурсы)        │
│    • Схема OpenAPI (kubeconform) • Различия (kubectl diff)  │
│    • CVE/SBOM (Trivy) • Подпись (Cosign) • Квоты / PDB      │
└─────────────────────────────────────────────────────────────┘
        │ Успешно (Pass)
        ▼
┌─────────────────────────────────────────────────────────────┐
│ 2. Admission & Scheduling Gate (API Server & Kube-Scheduler)│
│    • Валидация Admission Plugins • PSA Restricted           │
│    • Размещение подов с учетом Topology Spread Constraints  │
└─────────────────────────────────────────────────────────────┘
        │ Успешно (Pass)
        ▼
┌─────────────────────────────────────────────────────────────┐
│ 3. During-deploy Gate (Контроль Rollout в реальном времени) │
│    • Контроль таймаута progressDeadlineSeconds              │
│    • Ротация ReplicaSet • Условия подов (Pod Ready)         │
│    • Отсутствие Warning-событий в namespace                 │
└─────────────────────────────────────────────────────────────┘
        │ Успешно (Pass)
        ▼
┌─────────────────────────────────────────────────────────────┐
│ 4. Post-deploy Gate (Сетевой трафик и SRE Golden Signals)   │
│    • Синхронизация EndpointSlice • Внутренний/внешний Smoke │
│    • Проверка Prometheus (RPS, 5xx Rate, Latency p95/p99)   │
│    • Отсутствие CrashLoop / OOMKilled под нагрузкой         │
└─────────────────────────────────────────────────────────────┘
        │                                 │
     Pass                               Fail
        ▼                                 ▼
[ Стабилизация релиза ]       [ Экстренный Rollback ]
```

### Анатомия сбоев при развертывании без чеклиста

Игнорирование предварительных и промежуточных проверок в bare-metal окружении приводит к типовым системным авариям:

1. **Разрыв сетевых сессий и всплеск 5xx:**
   Если в манифесте отсутствует хук `preStop: exec: command: ["/bin/sleep", "10"]`, при остановке старого пода `kubelet` посылает процессу `SIGTERM` одновременно с отправкой события об удалении в API-сервер. Маршрутизаторы `kube-proxy` и Ingress-контроллеры обновляют локальные таблицы трансляции с задержкой в несколько секунд. В этот промежуток новые входящие запросы направляются на уже завершающийся контейнер, возвращая клиентам ошибки `502 Bad Gateway` или сброс TCP-соединений.
2. **Каскадное вытеснение и исчерпание Node Allocatable:**
   При агрессивных значениях `maxSurge: 50%` и выше контроллер Deployment единовременно создает избыточное число реплик. Если на узлах кластера отсутствует резерв по оперативной памяти, `kubelet` переходит в состояние `MemoryPressure` и инициирует принудительное вытеснение (Eviction) соседних подов с классом QoS `BestEffort` и `Burstable`.
3. **Невозможность воспроизводимого отката:**
   Использование плавающих тегов (например, `image: registry.local/app:latest` или `app:release-2026`) делает историю ревизий Kubernetes бесполезной. При выполнении команды `kubectl rollout undo` контроллер переключается на старый `ReplicaSet`, но `kubelet` использует закэшированный образ с тем же именем, либо скачивает измененный образ с тем же тегом. Это приводит к рассинхронизации реплик и невозможности отката на заведомо рабочую версию.
4. **Блокировка создания подов политиками PSA (Pod Security Admission):**
   Развертывание контейнера с конфигурацией по умолчанию в неймспейсе с профилем `pod-security.kubernetes.io/enforce: restricted` блокируется API-сервером на этапе Admission, если в манифесте явно не настроен `securityContext` (`runAsNonRoot: true`, запрет повышения привилегий, сброс Linux capabilities).

### Математика параметров безопасного Rollout

Контроллер Deployment управляет скоростью замены реплик через параметры `strategy.rollingUpdate`:

```text
Базовое число реплик: R = spec.replicas
Максимальное число подов при обновлении: MaxPods = R + maxSurge
Минимальное число доступных подов:       MinPods = R - maxUnavailable
```

**Рекомендации по расчету для bare-metal:**
- Для сервисов с `replicas >= 4`: `maxSurge: 25%`, `maxUnavailable: 0`. Это гарантирует 100% сохранение вычислительной мощности в любой момент обновления, требуя наличия не более 25% свободного запаса ресурсов на узлах.
- Для сервисов с жестким ограничением ресурсов: `maxSurge: 1`, `maxUnavailable: 0` — поочередная замена подов с минимальной нагрузкой на планировщик.
- Обязательная настройка `minReadySeconds: 15..30` — задает паузу после того, как `readinessProbe` пода перешла в статус `True`, перед тем как контроллер начнет сворачивать следующую старую реплику. Это предотвращает лавинообразное удаление старых подов, если новый под падает спустя 5–10 секунд после старта.

---

## 3. Практические сценарии

### Фаза 1: Pre-deploy Checklist (Предварительная проверка)

#### 1.1. Статическая и серверная валидация манифеста

```bash
# 1. Валидация структуры и схем OpenAPI без подключения к кластеру (для CI/CD)
kubeconform -strict -summary -output text deployment.yaml
# → deployment.yaml - Deployment my-app is valid

# 2. Серверная валидация схемы и admission-контроллеров на API-сервере
kubectl apply -f deployment.yaml --dry-run=server
# → deployment.apps/my-app configured (server dry run)

# 3. Проверка различий (diff) между текущим состоянием кластера и новым манифестом
kubectl diff -f deployment.yaml
# → Вывод стандартного unified diff (+/-) без применения изменений к etcd
```

**Критерий допуска:** Вывод `kubeconform` не содержит ошибок; `dry-run=server` завершается с кодом 0; `kubectl diff` содержит только ожидаемые изменения (версия образа, переменные окружения, ресурсы).

#### 1.2. Проверка безопасности контейнерного образа и цепочки поставки

```bash
# 1. Проверка наличия и доступности манифеста образа в приватном реестре по явному digest
crane manifest registry.local/prod/web-app@sha256:d8b74f07a72382c7a2b918f8e02cb8f34938bc9006e8b248a31362fa74efb1e3
# → {"schemaVersion": 2, "mediaType": "application/vnd.oci.image.manifest.v1+json", ...}

# 2. Сканирование образа на уязвимости (CVE) с блокировкой по критическим уровням
trivy image --severity HIGH,CRITICAL --ignore-unfixed --exit-code 1 registry.local/prod/web-app:v1.4.2
# → Total: 0 (HIGH: 0, CRITICAL: 0)

# 3. Верификация криптографической подписи образа через Cosign с локальным публичным ключом
cosign verify --key /etc/ssl/cosign/cosign.pub registry.local/prod/web-app:v1.4.2
# → The following checks were performed on each of these signatures:
# →   - The cosign claims were validated
# →   - Existence of the claims in the transparency log was verified
# →   - The signatures were verified against the specified public key
```

**Критерий допуска:** Образ зафиксирован неизменяемым хешем (SHA256 digest) или защищен от перезаписи политикой реестра; критические незакрытые CVE отсутствуют; подпись Cosign успешно верифицирована.

#### 1.3. Ресурсный аудит и планирование размещения на узлах

```bash
# 1. Проверка текущих лимитов и запаса в ResourceQuota целевого пространства имен
kubectl describe quota -n production
# → Name:            compute-resources
# → Resource         Used    Hard
# → --------         ----    ----
# → cpu              12      16
# → memory           24Gi    32Gi
# → pods             18      25

# 2. Проверка параметров LimitRange (дефолтные requests/limits и минимальные значения)
kubectl describe limitrange -n production
# → Resource  Type       Min   Max   Default Request  Default Limit
# → --------  ----       ---   ---   ---------------  -------------
# → cpu       Container  50m   4     250m             1
# → memory    Container  64Mi  8Gi   256Mi            1Gi

# 3. Аудит свободного объема ресурсов на рабочих узлах (Allocatable vs Non-terminated Pods)
kubectl describe nodes | grep -A 8 "Allocated resources:"
# →   Resource           Requests       Limits
# →   --------           --------       ------
# →   cpu                3800m (47%)    6200m (77%)
# →   memory             14336Mi (44%)  22528Mi (70%)

# 4. Проверка топологии размещения в манифесте
yq '.spec.template.spec.topologySpreadConstraints' deployment.yaml
# → Должно содержать распределение по kubernetes.io/hostname с maxSkew: 1
```

**Критерий допуска:** Сумма `requests` новых подов (с учетом `maxSurge`) укладывается в доступный остаток `ResourceQuota` и не превышает резерва `Allocatable` на узлах. Класс QoS определен как `Guaranteed` (requests == limits) или `Burstable` с обоснованными значениями.

#### 1.4. Аудит безопасности и соответствия Pod Security Standards (PSA)

```bash
# 1. Проверка меток профиля безопасности на целевом пространстве имен
kubectl get ns production -o jsonpath='{.metadata.labels}' | jq .
# → {
# →   "pod-security.kubernetes.io/enforce": "restricted",
# →   "pod-security.kubernetes.io/enforce-version": "latest",
# →   "pod-security.kubernetes.io/warn": "restricted"
# → }

# 2. Проверка контекста безопасности контейнера в манифесте
yq '.spec.template.spec.securityContext' deployment.yaml
# → runAsNonRoot: true
# → seccompProfile:
# →   type: RuntimeDefault

yq '.spec.template.spec.containers[0].securityContext' deployment.yaml
# → allowPrivilegeEscalation: false
# → readOnlyRootFilesystem: true
# → capabilities:
# →   drop:
# →     - ALL

# 3. Проверка сетевой изоляции пространства имен (наличие NetworkPolicy)
kubectl get networkpolicy -n production
# → NAME               POD-SELECTOR   AGE
# → default-deny-all   <none>         45d
# → allow-ingress      app=my-app     12d

# 4. Проверка сервисного аккаунта на отключение автоматического монтирования токена API
kubectl get sa app-service-account -n production -o jsonpath='{.automountServiceAccountToken}'
# → false
```

**Критерий допуска:** Профиль неймспейса соответствует `restricted`; контейнеры запускаются от непривилегированного пользователя без root-прав, файловая система корня доступна только для чтения (`readOnlyRootFilesystem: true`), сетевой трафик ограничен `NetworkPolicy`.

#### 1.5. Проверка внешних зависимостей и конфигурации

```bash
# 1. Проверка существования и ключей ConfigMap
kubectl get configmap my-app-config -n production -o jsonpath='{.data}' | jq 'keys'
# → [ "config.yaml", "logback.xml" ]

# 2. Проверка существования и типа Secret
kubectl get secret my-app-secrets -n production -o jsonpath='{.type}'
# → Opaque

# 3. Проверка статуса постоянных томов (PVC), если используются Stateful/LocalPV
kubectl get pvc -n production
# → NAME         STATUS   VOLUME                                     CAPACITY   ACCESS MODES   STORAGECLASS   AGE
# → data-app-0   Bound    pvc-8b1a32a1-0f2c-4f1b-8512-113328e2b8c9   50Gi       RWO            ceph-block     10d

# 4. Проверка наличия и состояния PodDisruptionBudget
kubectl get pdb -n production -l app=my-app
# → NAME         MIN AVAILABLE   MAX UNAVAILABLE   ALLOWED DISRUPTIONS   AGE
# → my-app-pdb   1               N/A               2                     10d
```

**Критерий допуска:** Все ключи в `ConfigMap` и `Secret`, объявленные в `envFrom` или `volumeMounts`, существуют; PVC находятся в статусе `Bound`; в PDB параметр `ALLOWED DISRUPTIONS` строго больше нуля (`> 0`).

---

### Фаза 2: During-deploy Checklist (Контроль в процессе раскатки)

#### 2.1. Инициация выкатки с фиксацией аудита

```bash
# 1. Применение манифеста
kubectl apply -f deployment.yaml -n production
# → deployment.apps/my-app configured

# 2. Обязательная фиксация причины изменения для истории ревизий
kubectl annotate deployment/my-app -n production \
  kubernetes.io/change-cause="Release v1.4.2: Security patch for CVE-2026-1182 and memory leak fix" \
  --overwrite
# → deployment.apps/my-app annotated
```

#### 2.2. Мониторинг прогресса выкатки в реальном времени

```bash
# 1. Отслеживание завершения rollout с детерминированным таймаутом
kubectl rollout status deployment/my-app -n production --timeout=5m
# → Waiting for deployment "my-app" rollout to finish: 1 out of 3 new replicas have been updated...
# → Waiting for deployment "my-app" rollout to finish: 2 out of 3 new replicas have been updated...
# → Waiting for deployment "my-app" rollout to finish: 1 old replicas are pending termination...
# → deployment "my-app" successfully rolled out

# 2. Параллельный мониторинг ротации поколений ReplicaSet
kubectl get rs -n production -l app=my-app -w
# → NAME                DESIRED   CURRENT   READY   AGE
# → my-app-76d997d97b   3         3         3       5d
# → my-app-58b9f69748   1         1         0       5s
# → my-app-58b9f69748   1         1         1       25s
# → my-app-76d997d97b   2         2         2       5d
```

#### 2.3. Перехват системных предупреждений и ошибок планирования

```bash
# 1. Непрерывный просмотр событий кластера типа Warning во время выкатки
kubectl get events -n production --field-selector type=Warning --sort-by='.lastTimestamp' -w
# → Ожидаемый результат: отсутствие событий FailedCreate, FailedScheduling,
# → FailedMount, FailedAttachVolume, Unhealthy, BackOff
```

#### 2.4. Потоковый аудит логов инициализации и проверка фаз подов

```bash
# 1. Проверка детального состояния фаз и условий подов новой ревизии
kubectl get pods -n production -l app=my-app -o wide
# → NAME                      READY   STATUS    RESTARTS   AGE   IP            NODE
# → my-app-58b9f69748-4k2x1   1/1     Running   0          45s   10.244.2.14   worker-02
# → my-app-58b9f69748-8z9ql   1/1     Running   0          25s   10.244.1.88   worker-01
# → my-app-58b9f69748-j7v92   1/1     Running   0          10s   10.244.3.41   worker-03

# 2. Просмотр первых 50 строк логов нового пода на предмет ошибок старта приложения
kubectl logs -l app=my-app,pod-template-hash=58b9f69748 -n production --tail=50 -f
# → 2026-10-13 19:55:01.102 [main] INFO  c.e.app.Application - Application started successfully in 4.312 seconds
# → 2026-10-13 19:55:02.400 [main] INFO  c.e.app.HttpServer  - Listening on port 8080
```

**Критерий допуска:** Вывод `kubectl rollout status` завершен с успешным сообщением в пределах таймаута; все поды перешли в статус `Running` и `1/1 Ready`; счетчик `RESTARTS` равен 0; события `Warning` отсутствуют; в логах отсутствуют `FATAL`, `PANIC`, необработанные исключения.

---

### Фаза 3: Post-deploy Checklist (Пострелизная верификация и телеметрия)

#### 3.1. Финальная валидация состояния контроллера

```bash
# 1. Проверка совпадения желаемого, обновленного и готового числа реплик
kubectl get deployment my-app -n production -o jsonpath='{
  "Desired": .spec.replicas,
  "Updated": .status.updatedReplicas,
  "Ready": .status.readyReplicas,
  "Available": .status.availableReplicas
}' | jq .
# → {
# →   "Desired": 3,
# →   "Updated": 3,
# →   "Ready": 3,
# →   "Available": 3
# → }

# 2. Проверка фактического образа, запущенного в кластере
kubectl get deployment my-app -n production -o jsonpath='{.spec.template.spec.containers[0].image}'
# → registry.local/prod/web-app:v1.4.2
```

#### 3.2. Сетевая проверка и smoke-тестирование

```bash
# 1. Проверка регистрации новых подов в EndpointSlice сервиса
kubectl get endpointslice -n production -l kubernetes.io/service-name=my-app -o wide
# → NAME             ADDRESSTYPE   PORTS         ENDPOINTS                              AGE
# → my-app-5b8c9     IPv4          8080/TCP      10.244.1.88,10.244.2.14,10.244.3.41    2m

# 2. Внутрикластерный smoke-тест из временного изолированного пода
kubectl run smoke-test --rm -i --restart=Never -n production \
  --image=registry.local/infra/curl:8.7.1 -- \
  curl -s -f -o /dev/null -w "%{http_code}\n" http://my-app.production.svc.cluster.local:8080/healthz
# → 200

# 3. Внешний smoke-тест через Ingress-контроллер
curl -k -s -f -o /dev/null -w "HTTP_STATUS: %{http_code}, TIME_TOTAL: %{time_total}s\n" \
  https://my-app.internal.domain/healthz
# → HTTP_STATUS: 200, TIME_TOTAL: 0.042s
```

#### 3.3. Observability Gate: Мониторинг четырех золотых сигналов SRE в Prometheus

Для оценки стабильности релиза в течение 10–15 минут после развертывания выполняются PromQL-запросы:

```promql
# 1. Error Rate (Темп ошибок): доля ответов 5xx в процентах (норма: < 0.1%)
sum(rate(http_requests_total{job="my-app", status=~"5.."}[5m]))
  /
sum(rate(http_requests_total{job="my-app"}[5m])) * 100

# 2. Latency (Задержка): 95-й и 99-й перцентили времени ответа (норма: не выше baseline)
histogram_quantile(0.95, sum(rate(http_request_duration_seconds_bucket{job="my-app"}[5m])) by (le))
histogram_quantile(0.99, sum(rate(http_request_duration_seconds_bucket{job="my-app"}[5m])) by (le))

# 3. Saturation (Насыщение): утилизация оперативной памяти относительно лимита
sum(container_memory_working_set_bytes{namespace="production", container="web-app"}) by (pod)
  /
sum(kube_pod_container_resource_limits{namespace="production", resource="memory", container="web-app"}) by (pod) * 100

# 4. CPU Throttling: процент усечения процессорного времени (норма: < 5%)
sum(increase(container_cpu_cfs_throttled_periods_total{namespace="production", container="web-app"}[5m]))
  /
sum(increase(container_cpu_cfs_periods_total{namespace="production", container="web-app"}[5m])) * 100

# 5. Проверка непредвиденных перезапусков контейнеров после релиза
sum(increase(kube_pod_container_status_restarts_total{namespace="production", container="web-app"}[15m]))
```

```bash
# 4. Проверка активных алертов в Alertmanager через CLI-утилиту amtool
amtool alert query alertname=~".*MyApp.*" --alertmanager.url=http://alertmanager.monitoring.svc:9093
# → Alertname   Severity   State   Starts At   Summary
# → (Вывод пуст: нет активных алертов)
```

#### 3.4. Аудит истории и фиксация ревизии

```bash
# 1. Просмотр истории ревизий с аннотациями причин изменений
kubectl rollout history deployment/my-app -n production
# → REVISION  CHANGE-CAUSE
# → 1         Initial production release v1.4.0
# → 2         Update configuration: increase thread pool
# → 3         Release v1.4.2: Security patch for CVE-2026-1182 and memory leak fix
```

**Критерий допуска:** Доля ошибок 5xx не превышает baseline (< 0.1%); задержка p95 стабильна; утечки памяти и троттлинг процессора отсутствуют; нет алертов в Alertmanager; аннотация `change-cause` сохранена в истории ревизий.

---

### Автоматизация Quality Gate в CI/CD

Пример законченного скрипта развертывания для локального CI/CD конвейера (GitLab CI Runner / Shell Executor) с автоматическим откатом при сбое любой из фаз:

```bash
#!/usr/bin/env bash
# production_deploy_gate.sh — Строгий шлюз развертывания с автоматическим откатом
set -euo pipefail

NAMESPACE="production"
DEPLOYMENT_NAME="my-app"
MANIFEST_FILE="deployment.yaml"
IMAGE_REF="${1:-}"
TIMEOUT="300s"

if [[ -z "$IMAGE_REF" ]]; then
  echo "Ошибка: Не указана ссылка на контейнерный образ." >&2
  exit 1
fi

echo "=== [Phase 1: Pre-deploy Validation] ==="
echo "1.1 Проверка синтаксиса и схемы через kubeconform..."
kubeconform -strict -summary -output text "$MANIFEST_FILE"

echo "1.2 Серверная валидация схемы в кластере..."
kubectl apply -f "$MANIFEST_FILE" -n "$NAMESPACE" --dry-run=server

echo "1.3 Сканирование образа на критические уязвимости..."
trivy image --severity HIGH,CRITICAL --ignore-unfixed --exit-code 1 "$IMAGE_REF"

echo "1.4 Проверка доступного остатка квоты..."
AVAILABLE_PODS=$(kubectl get quota compute-resources -n "$NAMESPACE" -o jsonpath='{.status.hard.pods}' 2>/dev/null || echo "100")
echo "Квота проверена. Допустимо создание подов."

echo "=== [Phase 2: During-deploy Execution] ==="
# Сохраняем номер текущей стабильной ревизии перед выкаткой
PREV_REVISION=$(kubectl get deployment "$DEPLOYMENT_NAME" -n "$NAMESPACE" \
  -o jsonpath='{.metadata.annotations.deployment\.kubernetes\.io/revision}' 2>/dev/null || echo "0")

echo "2.1 Применение манифеста..."
kubectl apply -f "$MANIFEST_FILE" -n "$NAMESPACE"

echo "2.2 Документирование причины релиза..."
kubectl annotate deployment/"$DEPLOYMENT_NAME" -n "$NAMESPACE" \
  kubernetes.io/change-cause="CI Deployment pipeline #${CI_PIPELINE_ID:-manual} by ${USER:-ci}" \
  --overwrite

echo "2.3 Мониторинг выкатки (таймаут: $TIMEOUT)..."
if ! kubectl rollout status deployment/"$DEPLOYMENT_NAME" -n "$NAMESPACE" --timeout="$TIMEOUT"; then
  echo "ВНИМАНИЕ: Превышен таймаут выкатки или обнаружен сбой подов! Инициируется аварийный откат..." >&2
  kubectl rollout undo deployment/"$DEPLOYMENT_NAME" -n "$NAMESPACE"
  kubectl rollout status deployment/"$DEPLOYMENT_NAME" -n "$NAMESPACE" --timeout=120s
  echo "Кластер возвращен к стабильному состоянию. Деплой провален." >&2
  exit 1
fi

echo "=== [Phase 3: Post-deploy Verification] ==="
echo "3.1 Проверка статуса готовности подов..."
READY_REPLICAS=$(kubectl get deployment "$DEPLOYMENT_NAME" -n "$NAMESPACE" -o jsonpath='{.status.readyReplicas}')
DESIRED_REPLICAS=$(kubectl get deployment "$DEPLOYMENT_NAME" -n "$NAMESPACE" -o jsonpath='{.spec.replicas}')

if [[ "$READY_REPLICAS" -ne "$DESIRED_REPLICAS" ]]; then
  echo "Ошибка: Число готовых реплик ($READY_REPLICAS) не соответствует желаемому ($DESIRED_REPLICAS). Откат..." >&2
  kubectl rollout undo deployment/"$DEPLOYMENT_NAME" -n "$NAMESPACE"
  exit 1
fi

echo "3.2 Выполнение внутрикластерного Smoke-теста..."
HTTP_STATUS=$(kubectl run "smoke-test-${RANDOM}" --rm -i --restart=Never -n "$NAMESPACE" \
  --image=registry.local/infra/curl:8.7.1 -- \
  curl -s -o /dev/null -w "%{http_code}" --max-time 5 \
  "http://${DEPLOYMENT_NAME}.${NAMESPACE}.svc.cluster.local:8080/healthz" || echo "000")

if [[ "$HTTP_STATUS" != "200" ]]; then
  echo "Ошибка: Smoke-тест вернул код $HTTP_STATUS вместо 200 OK! Инициируется аварийный откат..." >&2
  kubectl rollout undo deployment/"$DEPLOYMENT_NAME" -n "$NAMESPACE"
  exit 1
fi

echo "Успех: Все шлюзы контроля успешно пройдены. Релиз стабилен."
exit 0
```

---

### Экстренные процедуры (SRE Runbook)

При обнаружении деградации сервиса оператор применяет аварийный протокол:

```bash
# 1. Мгновенный откат к непосредственно предыдущей стабильной ревизии
kubectl rollout undo deployment/my-app -n production
# → deployment.apps/my-app rolled back

# 2. Откат к конкретной проверенной исторической ревизии (например, ревизия 2)
kubectl rollout undo deployment/my-app -n production --to-revision=2
# → deployment.apps/my-app rolled back to revision 2

# 3. Экстренная приостановка раскатки при обнаружении скрытой деградации
# (останавливает дальнейшую ротацию подов, сохраняя текущее соотношение старых и новых)
kubectl rollout pause deployment/my-app -n production
# → deployment.apps/my-app paused

# 4. Возобновление раскатки после исправления внешних факторов (базы данных, сетевых маршрутов)
kubectl rollout resume deployment/my-app -n production
# → deployment.apps/my-app resumed

# 5. Принудительный перезапуск без изменения кода (инъекция restartedAt метки)
kubectl rollout restart deployment/my-app -n production
# → deployment.apps/my-app restarted

# 6. Экстренное масштабирование мощности при всплеске нагрузки в процессе релиза
kubectl scale deployment/my-app -n production --replicas=6
# → deployment.apps/my-app scaled
```

---

## 4. Операции и команды

Сводный справочник команд для повседневной проверки и оперативного контроля развертывания:

| Действие | Команда | Назначение и ожидаемый результат |
|:---|:---|:---|
| **Валидация манифеста** | `kubeconform -strict -summary deployment.yaml` | Проверка синтаксиса по схемам OpenAPI без кластера (`# → Summary: 1/1 passed`). |
| **Серверный Dry-Run** | `kubectl apply -f deployment.yaml --dry-run=server` | Полная валидация схем и admission-контроллеров (`# → configured (server dry run)`). |
| **Аудит различий** | `kubectl diff -f deployment.yaml` | Вывод diff между etcd и манифестом (`# → unified diff`). |
| **Сканирование CVE** | `trivy image --severity HIGH,CRITICAL image:tag` | Поиск уязвимостей в образе перед деплоем (`# → Total: 0`). |
| **Верификация подписи** | `cosign verify --key key.pub image:tag` | Проверка целостности и происхождения артефакта (`# → claims validated`). |
| **Проверка квот** | `kubectl describe quota -n prod` | Контроль лимитов ресурсов пространства имен (`# → Used / Hard limits`). |
| **Мониторинг rollout** | `kubectl rollout status deployment/app -n prod --timeout=5m` | Блокирующее ожидание завершения обновления (`# → successfully rolled out`). |
| **История ревизий** | `kubectl rollout history deployment/app -n prod` | Просмотр журнала изменений с change-cause (`# → REVISION / CHANGE-CAUSE`). |
| **Откат к предыдущей** | `kubectl rollout undo deployment/app -n prod` | Возврат на предыдущую ревизию (`# → rolled back`). |
| **Откат к выбранной** | `kubectl rollout undo deployment/app -n prod --to-revision=N` | Детерминированный откат к ревизии N (`# → rolled back to revision N`). |
| **Заморозка rollout** | `kubectl rollout pause deployment/app -n prod` | Приостановка ротации контейнеров (`# → paused`). |
| **Проверка эндпоинтов** | `kubectl get endpointslice -l kubernetes.io/service-name=app -n prod` | Контроль регистрации IP-адресов подов в сети (`# → 3 IP endpoints`). |
| **Инспекция предупреждений** | `kubectl get events -n prod --field-selector type=Warning` | Быстрый поиск системных ошибок в namespace (`# → No events found`). |

---

## 5. Устранение неполадок

### 1. Поды зависают в статусе Pending при начале раскатки

- **Симптом:** Старые поды продолжают работать, новый под создается в `Pending`. Статус выкатки сообщает `Waiting for deployment "my-app" rollout to finish: 0 of 3 updated replicas are available...`.
- **Причина:** Превышена квота пространства имен (`ResourceQuota`) по суммарному объему CPU/RAM, либо на рабочих узлах кластера не хватает ресурсов `Allocatable` с учетом значения `maxSurge`.
- **Диагностика:**
  ```bash
  # Просмотр причин невозможности размещения пода
  kubectl describe pod -l app=my-app,pod-template-hash=<new-hash> -n production
  # → Events:
  # →   Warning  FailedScheduling  default-scheduler  0/6 nodes are available: 3 Insufficient memory, 3 node(s) had untolerated taint.
  
  # Проверка статуса квоты
  kubectl describe quota -n production
  # → Warning: exceeded quota: compute-resources, requested: memory=4Gi, used: 30Gi, limited: 32Gi
  ```
- **Решение:**
  1. Если блокирует квота: скорректировать лимиты квоты или временно уменьшить `maxSurge: 0`, `maxUnavailable: 1` для поочередной замены без всплеска потребления.
  2. Если блокируют ресурсы узлов: освободить память на воркерах, добавить воркер-ноду в bare-metal кластер или оптимизировать `resources.requests`.

### 2. Ошибки 502 Bad Gateway в процессе смены реплик

- **Симптом:** При плановом обновлении версии кратковременно подскакивает темп сетевых ошибок `HTTP 502/504` на Ingress-контроллере.
- **Причина:** В шаблоне пода отсутствует задержка `lifecycle.preStop`, а процесс в контейнере мгновенно перехватывает сигнал `SIGTERM` и закрывает слушающий сокет до того, как сетевые агенты (`kube-proxy`, `iptables/IPVS`) успели исключить IP пода из цепочек маршрутизации.
- **Диагностика:**
  ```bash
  # Проверка наличия preStop хука в спецификации контейнера
  yq '.spec.template.spec.containers[0].lifecycle' deployment.yaml
  # → null
  ```
- **Решение:** Добавить хук `preStop` со сном в 10–15 секунд и убедиться, что `terminationGracePeriodSeconds` превышает сумму сна и времени завершения активных соединений:
  ```yaml
  lifecycle:
    preStop:
      exec:
        command: ["/bin/sleep", "15"]
  terminationGracePeriodSeconds: 45
  ```

### 3. Ошибка CreateContainerConfigError или CrashLoopBackOff из-за безопасности

- **Симптом:** Новые поды переходят в `CreateContainerConfigError` или завершаются сразу после запуска (`CrashLoopBackOff` с кодом выхода 1 или 137).
- **Причина:**
  1. Манифест задеплоен в пространство имен с политикой `pod-security.kubernetes.io/enforce: restricted`, но спецификация не содержит обязательных полей `runAsNonRoot: true`, `readOnlyRootFilesystem: true`.
  2. В контейнере включен `readOnlyRootFilesystem: true`, но приложение пытается записать временные файлы или логи в стандартные системные каталоги (`/tmp`, `/var/run`, `/app/logs`) без монтирования томов `emptyDir`.
- **Диагностика:**
  ```bash
  kubectl get events -n production --field-selector reason=FailedCreate
  # → Warning  FailedCreate  replicaset/my-app-xxx  Error creating: pods "my-app-xxx" is forbidden: violates PodSecurity "restricted:latest"
  
  kubectl logs -l app=my-app,pod-template-hash=<new-hash> -n production
  # → java.io.IOException: Read-only file system at /tmp/app.lock
  ```
- **Решение:**
  1. Задать корректный `securityContext` в соответствии со стандартом Restricted.
  2. Сконфигурировать выделенные тома памяти для временных каталогов:
     ```yaml
     volumes:
       - name: tmp-dir
         emptyDir:
           medium: Memory
           sizeLimit: 128Mi
     volumeMounts:
       - name: tmp-dir
         mountPath: /tmp
     ```

### 4. Невозможность выполнить откат при использовании плавающего тега образа

- **Симптом:** Команда `kubectl rollout undo` завершается без ошибок, но сервис продолжает выдавать сбойное поведение, либо разные поды исполняют разный код.
- **Причина:** В манифесте был указан тег `:latest` или мутабельный тег релиза (например `:v1`). При сборке образ был перезаписан в реестре. Разные узлы используют разные версии слоя из локального Docker/containerd кэша.
- **Диагностика:**
  ```bash
  # Сравнение фактических SHA256 digest подов на разных узлах
  kubectl get pods -l app=my-app -n production \
    -o jsonpath='{range .items[*]}{.spec.nodeName}{"\t"}{.status.containerStatuses[0].imageID}{"\n"}{end}'
  # → worker-01  registry.local/app@sha256:aaaa...
  # → worker-02  registry.local/app@sha256:bbbb... (Рассинхронизация хешей!)
  ```
- **Решение:**
  1. Зафиксировать конкретный SHA256 дайджест в манифесте: `image: registry.local/app@sha256:aaaa...`.
  2. Включить на уровне приватного реестра (Harbor) запрет перезаписи тегов (Immutable Tag Rules).
  3. Ввести жесткое правило CI/CD: только семантическое версионирование (`v1.4.2`) либо хеш Git-коммита.

### 5. Блокировка планового дренирования узла (kubectl drain) из-за PDB

- **Симптом:** При попытке вывода ноды на техническое обслуживание команда `kubectl drain worker-01` зависает с ошибкой `Cannot evict pod as it would violate the pod's disruption budget`.
- **Причина:** `PodDisruptionBudget` настроен с параметром `minAvailable: 100%` или `minAvailable: 2` при общем числе реплик `spec.replicas: 2`. При этом одна из реплик не в статусе `Ready` либо PDB не оставляет зазора для временной недоступности.
- **Диагностика:**
  ```bash
  kubectl get pdb -n production -l app=my-app
  # → NAME         MIN AVAILABLE   ALLOWED DISRUPTIONS
  # → my-app-pdb   2               0                   (Запрещено вытеснение даже 1 пода!)
  ```
- **Решение:** Для сервисов из 2–3 реплик использовать `maxUnavailable: 1` вместо `minAvailable: 100%`. Это позволяет безопасно перемещать поды по одному при регламентных работах на bare-metal серверах.

---

## 6. Лучшие практики (Best Practices)

### Матрица соответствия Production Readiness (Quality Gates)

Перед переводом любого Deployment в эксплуатацию команда разработки и эксплуатации заполняет матрицу соответствия:

| Область | Критерий готовности к Production | Обязательность | Способ проверки |
|:---|:---|:---|:---|
| **Схема и манифест** | Валидация по OpenAPI схемам через `kubeconform` | Обязательно | `kubeconform -strict` в CI/CD |
| **Неизменяемость** | Фиксация digest либо уникального семантического тега | Обязательно | Статический анализ манифеста |
| **Уязвимости** | Отсутствие незакрытых CVE уровней Critical и High | Обязательно | `trivy image --exit-code 1` |
| **Подпись кода** | Наличие цифровой подписи релиза через Cosign | Обязательно | `cosign verify` в пайплайне |
| **Ресурсы** | Указание явных `requests` и `limits` (CPU и RAM) | Обязательно | `kube-score` / `yq` линтер |
| **Безопасность** | Соответствие профилю PSA Restricted (`runAsNonRoot`, ro-rootfs) | Обязательно | Admission webhook / CI проверка |
| **Сетевая изоляция** | Действующая `NetworkPolicy` с запретом нецелевого трафика | Обязательно | `kubectl get netpol -n <ns>` |
| **Отказоустойчивость** | Наличие PDB (`maxUnavailable: 1`), число реплик `>= 2` | Обязательно | `kubectl get pdb -n <ns>` |
| **Распределение** | Наличие `topologySpreadConstraints` по хостам | Обязательно | Аудит спецификации пода |
| **Плавный останов** | Триада проб + `preStop` sleep (10–15s) + корректный grace period | Обязательно | Аудит спецификации контейнера |
| **История ревизий** | `revisionHistoryLimit: 10` и аннотация `change-cause` | Обязательно | `kubectl rollout history` |
| **Наблюдаемость** | Настроенные дашборды SRE Golden Signals и алерты | Обязательно | Prometheus / Alertmanager |

### Регламент проведения релизов на Bare-Metal

1. **Релизные окна и запреты (Freeze Periods):** Не производить развертывание в периоды пиковой бизнес-нагрузки или за 1 час до окончания рабочей смены инженеров дежурной смены (SRE on-call).
2. **Изоляция изменений:** Никогда не объединять обновление версии бинарного кода и масштабные миграции схемы базы данных в один шаг выкатки. Сначала выполняется обратно-совместимая миграция БД, затем обновление Deployment.
3. **Очистка и управление историей:** Значение `revisionHistoryLimit` должно быть установлено в диапазоне от 5 до 10. Значение по умолчанию (10) является оптимальным; установка значения более 20 избыточно нагружает хранилище `etcd` неактивными объектами `ReplicaSet`.
4. **Принцип минимальных привилегий (Least Privilege):** Всегда отключать монтирование токена сервисного аккаунта (`automountServiceAccountToken: false`), если приложению не требуется напрямую опрашивать Kubernetes API.

---

## 7. Дополнительная информация

### См. также
- [Deployment: Обзор](./index.md) — концептуальные основы, архитектура контроллера и базовые сценарии.
- [Манифест и лучшие практики](./deployment_manifest.md) — детальный разбор всех полей манифеста, шаблона пода и QoS.
- [Управление жизненным циклом](./lifecycle_management.md) — математика ротации реплик, rollover и безаварийное переключение трафика.
- [Безопасность Deployment](./deployment_security_hardening.md) — hardened манифест, Pod Security Standards и секурная изоляция.
- [Мониторинг и наблюдаемость Deployment](./deployment_monitoring_observability.md) — метрики kube-state-metrics, PromQL и дашборды.
- [Продвинутые стратегии отката](./advanced_rollback_strategies.md) — алгоритмы автоматического и ручного восстановления.
- [Устранение неполадок Deployment](./troubleshooting.md) — исчерпывающая диагностика зависших выкаток и ошибок подов.
- [Kubeconform](../../ToolsUtilities/kubeconform_overview.md) — валидация манифестов по схемам OpenAPI в CI/CD.
- [Безопасность контейнеров и сканирование уязвимостей](../../../Docker/Docker_security/overview.md) — поиск CVE и защита цепочки поставки.
- [Безопасный релизный конвейер](../../../CI-CD/DevSecOps/secure_release_pipeline.md) — построение защищенных CI/CD пайплайнов.
- [Реагирование на инциденты в SRE](../../../CI-CD/Core_Concepts/incident_response_sre.md) — регламенты устранения сбоев и проведения postmortem.
- [Ошибки конфигурации контейнера: CreateContainerConfigError](../../Troubleshooting/Common_Errors/CreateContainerConfigError/definitions.md) — устранение сбоев ConfigMap и Secret.
- [Ошибки вытеснения подов: PodEvicted](../../Troubleshooting/Common_Errors/PodEvicted/definitions.md) — диагностика нехватки ресурсов и eviction.
- [Диагностика зависания PodPending](../../Troubleshooting/Common_Errors/pod_pending/diagnostics.md) — пошаговый алгоритм решения проблем с размещением подов.
