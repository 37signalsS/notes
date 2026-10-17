# Архитектура и компоненты Istio

## Определения

**Istio** — открытая реализация [Service Mesh](./service_mesh_concepts.md), обеспечивающая безопасность, управление трафиком и наблюдаемость микросервисов. В 2026 году архитектура Istio ориентирована на максимальную производительность и гибкость развертывания через разделение функций L4 и L7.

Архитектура Istio разделена на две плоскости:
- **Control Plane (Плоскость управления)**: управляет конфигурацией, безопасностью и реестром сервисов.
- **Data Plane (Плоскость данных)**: набор прокси-серверов, обрабатывающих трафик. В современных версиях (1.30+) поддерживаются две модели: **Sidecar** и **Ambient** (рекомендуемая). Обе модели могут сосуществовать в одном меше и взаимодействуют между собой через mTLS, что упрощает поэтапную миграцию.

---

## Основные концепции

### Плоскость управления: istiod

**istiod** — единый бинарный компонент плоскости управления. Он объединяет функции, которые ранее выполнялись отдельными компонентами (Pilot, Citadel, Galley), сохраняя их логическое разделение внутри.

Основные функции `istiod`:
- **Конфигурация (xDS)**: преобразует декларативные YAML-манифесты (Gateway API, VirtualService) в низкоуровневые инструкции xDS для Envoy и Ztunnel.
- **Service Discovery**: агрегирует информацию об эндпоинтах из API-сервера Kubernetes и внешних реестров.
- **Управление идентификацией (CA)**: выступает в роли доверенного центра сертификации (Certificate Authority), выпуская кратковременные сертификаты X.509 для mTLS на основе **SPIFFE**-идентификаторов (обычно привязанных к Kubernetes ServiceAccount).
- **Валидация**: проверяет корректность манифестов перед их применением.

### Эксплуатация istiod

**Жизненный цикл и обновления:**
- `istiod` разворачивается как Deployment с репликами. Для Rolling Restart используйте:
  ```bash
  kubectl rollout restart deployment/istiod -n istio-system
  kubectl rollout status deployment/istiod -n istio-system
  ```
- При обновлении версии Istio через Helm или `istioctl upgrade` обновляется только Deployment; ConfigMap и CRD остаются совместимыми. Для проверки успешности обновления:
  ```bash
  istioctl version
  kubectl get pods -n istio-system -l app=istiod -o wide
  ```
- Масштабирование: для больших кластеров (>500 подов) рекомендуется минимум 2 реплики istiod с параметром `--max-connections` и лимитами CPU/memory (рекомендация: 500m CPU / 1Gi RAM на реплику для 1000 подов).

**Бэкап конфигурации:**
```bash
# Экспорт всех ресурсов Istio (VirtualService, DestinationRule, Gateway, AuthorizationPolicy)
kubectl get virtualservices,destinationrules,gateways,authorizationpolicies,envoyfilters -A -o yaml > istio-config-backup.yaml

# Бэкап ConfigMap с конфигурацией меша
kubectl get configmap istio -n istio-system -o yaml > istio-mesh-config-backup.yaml
```

### Плоскость данных (Data Plane)

#### 1. Модель Sidecar (классическая)

В этой модели [прокси-сервер Envoy](./proxy_sidecar.md) запускается в каждом Pod как дополнительный контейнер.
- **Механизм**: перехват трафика через `iptables` (или eBPF-редирект) внутри сетевого пространства имён пода.
- **Особенности**: обеспечивает полную изоляцию и весь спектр L7-функций, но требует значительных ресурсов (RAM/CPU) на каждый экземпляр приложения.
- **Нативные сайдкары Kubernetes**: с Istio 1.27 внедрение Sidecar-модели использует механизм [нативных sidecar-контейнеров](../Kubernetes/Base/Pod/pod_sidecar_patterns.md) (`restartPolicy: Always` в фазах инициализации), что исключает «пустое» состояние init-контейнера и ускоряет запуск подов. Native Sidecar стабилен с Kubernetes 1.33.

#### 2. Модель Ambient (Sidecar-less) — GA статус

Архитектура Ambient Mesh официально стабилизирована (GA с Istio 1.24, ноябрь 2024) и является рекомендуемой для большинства сценариев. Пакет Istio 1.30.x поддерживает Kubernetes 1.32–1.37. Она разделяет обязанности меша на два уровня:

**L4-уровень: Ztunnel (Zero Trust Tunnel)**
- **Развертывание**: DaemonSet на каждом узле кластера.
- **Функции**: прозрачный mTLS, L4-авторизация, сбор TCP-метрик.
- **Протокол HBONE**: использует **HTTP-Based Overlay Network Environment** (инкапсуляция TCP в HTTP/2 CONNECT) для безопасной передачи трафика между узлами.
- **Производительность**: написан на Rust, потребляет минимум ресурсов (shared-модель).
- **Ограничения**: ztunnel работает на L4 и не анализирует HTTP, поэтому HTTP-телеметрия, L7-политики и маршрутизация требуют Waypoint.

**Подсистема перехвата: istio-cni**
- **Развертывание**: DaemonSet (`istio-cni-node`) в `istio-system`, устанавливается вместе с профилем `ambient`.
- **Роль**: выполняет прозрачное перенаправление трафика в ztunnel без привилегированного init-контейнера. Поддерживает цепочки `iptables` и `nftables` (последние включаются с Istio 1.27 параметром `values.global.nativeNftables=true` и приоритетны для новых инсталляций), а также eBPF-редирект.
- **Безопасность конфигурации**: с 1.30 права доступа к файлам CNI ужесточены (`0600`), что ограничивает их чтение непривилегированными процессами.
- **Отладка**: логи CNI доступны через Pod `istio-cni-node` в `istio-system`. Для диагностики конфликтов с другими CNI-плагинами проверьте:
  ```bash
  kubectl logs -n istio-system -l app=istio-cni-node --tail=100
  # Типичная ошибка: "failed to setup iptables rules: exit status 2"
  # Причина: конфликт с kube-proxy или другим плагином. Решение: убедитесь, что параметр
  # values.cni.ambient.logging.level установлен в "debug" и проверьте порядок загрузки модулей.
  ```
- **Выбор стека**: `nftables` приоритетен для новых инсталляций (меньше правил, выше производительность). При миграции с `iptables` на `nftables` требуется переустановка CNI DaemonSet.

**L7-уровень: Waypoint Proxy**
- **Развертывание**: Deployment на базе Envoy, создаваемый для конкретного неймспейса или сервиса.
- **Функции**: сложная маршрутизация, фильтрация заголовков, политики безопасности на уровне L7.
- **Принцип работы**: подключается только тогда, когда это необходимо (через метку `istio.io/use-waypoint`), и обрабатывает трафик, перенаправленный из Ztunnel. Масштабируется независимо через HPA.
- **Гибридный режим**: Ambient и Sidecar могут сосуществовать в одном меше; istio-cni поддерживает работу с уже внедрёнными sidecar-контейнерами.

**Масштабирование и отладка Waypoint:**
- Waypoint Proxy масштабируется через стандартный Kubernetes HPA. Рекомендуемые лимиты: 100m CPU / 128Mi RAM на реплику при нагрузке до 1000 RPS.
- Для настройки HPA:
  ```yaml
  apiVersion: autoscaling/v2
  kind: HorizontalPodAutoscaler
  metadata:
    name: my-app-waypoint-hpa
    namespace: my-app
  spec:
    scaleTargetRef:
      apiVersion: apps/v1
      kind: Deployment
      name: namespace-waypoint
    minReplicas: 1
    maxReplicas: 5
    metrics:
    - type: Resource
      resource:
        name: cpu
        target:
          type: Utilization
          averageUtilization: 70
  ```
- **Диагностика**: проверка статуса waypoint и синхронизации конфигурации:
  ```bash
  istioctl waypoint list -n my-app
  istioctl proxy-status | grep my-app
  kubectl get pods -n my-app -l gateway.networking.k8s.io/gateway-name=namespace-waypoint
  ```

### Сравнение моделей развертывания

| Критерий | Sidecar Model | Ambient Mesh (GA) |
| :--- | :--- | :--- |
| **Изоляция** | Максимальная (per-pod) | Групповая (node/namespace) |
| **Ресурсы** | Высокие накладные расходы | Снижение оверхеда до 90% |
| **Обновление** | Требует рестарта приложения | Прозрачное обновление прокси |
| **Безопасность** | mTLS на уровне пода | mTLS на уровне узла (Ztunnel) |
| **Сложность** | Средняя | Низкая (прозрачное внедрение) |

### Эксплуатация Ztunnel

**Мониторинг и ресурсы:**
- Ztunnel экспортирует метрики на порту `15020` внутри пода. Для сбора метрик используйте ServiceMonitor или прямые запросы:
  ```bash
  kubectl exec -n istio-system -it <ztunnel-pod> -- curl -s localhost:15020/metrics | grep ztunnel
  ```
- Рекомендуемые лимиты ресурсов (DaemonSet):
  ```yaml
  resources:
    requests:
      cpu: 50m
      memory: 64Mi
    limits:
      cpu: 200m
      memory: 256Mi
  ```
- При росте кластера следите за утечками памяти в ztunnel (известные баг-репорты в 1.28–1.29, исправлены в 1.30).

**Типичные ошибки и решения:**
| Симптом | Причина | Решение |
| :--- | :--- | :--- |
| Под не получает IP из меша | Ztunnel не перехватывает трафик | Проверьте л CNI: `kubectl logs -n istio-system -l app=istio-cni-node`. Убедитесь, что неймспейс помечен `istio.io/dataplane-mode=ambient`. |
| mTLS не работает между подами | Сертификаты не синхронизированы | Проверьте `istioctl proxy-status`. Убедитесь, что istiod выпустил сертификаты: `istioctl proxy-config secret <pod> -n <ns>`. |
| Высокий CPU на ноде | Конфликт правил iptables/nftables | Переключите CNI на `nftables` (`values.global.nativeNftables=true`) или проверьте количество правил: `iptables -L -t nat -v | wc -l`. |
| Трафик не маршрутизируется на waypoint | Метка `istio.io/use-waypoint` отсутствует | Примените метку: `kubectl label namespace my-app istio.io/use-waypoint=namespace-waypoint`. |

**Логи:**
```bash
# Логи Ztunnel на конкретной ноде
POD=$(kubectl get pods -n istio-system -l app=ztunnel -o jsonpath='{.items[0].metadata.name}')
kubectl logs -n istio-system $POD --tail=100

# Логи CNI для диагностики перехвата
kubectl logs -n istio-system -l app=istio-cni-node --tail=100
```

---

## Практические сценарии

### Установка и развертывание

Подробные инструкции по установке Istio через `istioctl` (включая профили Ambient, Demo, Default) и Helm, а также методы инъекции сайдкаров описаны в разделе **[Установка и базовая настройка Istio](./istio_installation.md)**.

### Настройка Waypoint Proxy через Gateway API (GAMMA)

Для выполнения L7-задач (например, канареечных развертываний через `HTTPRoute`) необходимо развернуть Waypoint и указать, какие неймспейсы/сервисы должны его использовать.

Waypoint-прокси создаются декларативно как ресурсы `Gateway` из Kubernetes Gateway API, а подключение происходит через метку `istio.io/use-waypoint` (для неймспейса, сервиса или пода). Самый простой способ — управление через `istioctl`:

```bash
# Создание waypoint для неймспейса (автоматически ставит метку istio.io/use-waypoint)
istioctl waypoint apply -n my-app --enroll-namespace

# Проверка созданных waypoint
istioctl waypoint list -n my-app
```

Эквивалентное декларативное описание через Gateway API:

```yaml
apiVersion: gateway.networking.k8s.io/v1
kind: Gateway
metadata:
  name: namespace-waypoint
  namespace: my-app
spec:
  gatewayClassName: istio-waypoint
```

После этого трафик к сервисам неймспейса `my-app`, требующий L7-обработки, будет автоматически направляться Ztunnel через созданный Waypoint прокси. Все `HTTPRoute` в этом неймспейсе будут автоматически использовать созданный Waypoint прокси.

### Политики безопасности Istio

Безопасность в Istio обеспечивается через ресурсы `PeerAuthentication` (аутентификация mTLS) и `AuthorizationPolicy` (авторизация доступа). Эти политики исполняются на уровне Ztunnel (L4) и Waypoint Proxy (L7) в режиме Ambient, либо непосредственно в Sidecar-прокси.

Подробное описание и примеры см. в [Политиках безопасности Istio](./istio-security-policies.md).

### Диагностика архитектуры

**Команды проверки состояния компонентов:**
```bash
# Сводка по синхронизации xDS (Control Plane → Data Plane)
istioctl proxy-status
# → SYNCED: конфигурация доставлена; NOT SYNCED: проблема доставки (проверьте сеть/istiod)

# Описание сетевого пути пода в Ambient
istioctl x describe pod <pod-name> -n <namespace>
# → Показывает: ztunnel (L4), waypoint (L7), политики, сертификаты

# Анализ всех ресурсов меша на ошибки
istioctl analyze -A

# Валидация конкретного манифеста
istioctl validate -f virtual-service.yaml

# Проверка конфигурации прокси (все плоскости)
istioctl proxy-config all deploy/my-app -n my-app
```

**Диагностика сертификатов:**
```bash
# Просмотр сертификатов в sidecar
istioctl proxy-config secret <pod-name> -n <namespace> -o json | jq '.dynamicActiveSecrets[0].secret.tlsCertificate.certificateChain.inlineBytes' | base64 -d | openssl x509 -noout -text

# Проверка срока действия сертификата
istioctl proxy-config secret <pod-name> -n <namespace> -o json | jq '.dynamicActiveSecrets[0].secret.tlsCertificate.certificateChain.inlineBytes' | base64 -d | openssl x509 -noout -enddate

# Проверка сертификатов Ztunnel (Ambient)
ZTUNNEL_POD=$(kubectl get pods -n istio-system -l app=ztunnel -o jsonpath='{.items[0].metadata.name}')
kubectl exec -n istio-system $ZTUNNEL_POD -- cat /etc/istio/ztunnel/secret/root-cert.pem | openssl x509 -noout -text
```

**Диагностика производительности:**
```bash
# Использование ресурсов Ztunnel по нодам
kubectl top pods -n istio-system -l app=ztunnel

# Метрики Envoy (sidecar/waypoint)
kubectl exec -n my-app <waypoint-pod> -- curl -s localhost:15000/stats | grep <service-name>
```

---

## Дополнительная информация

### Протокол HBONE и eBPF-ускорение

В 2026 году Istio активно использует eBPF для обхода сетевого стека ядра при передаче трафика в Ztunnel.
- **HBONE (HTTP/2 CONNECT)**: обеспечивает безопасный туннель между узлами, позволяя передавать метаданные (идентификатор источника) вместе с трафиком.
- **eBPF Redirection**: заменяет медленные правила `iptables`, обеспечивая практически мгновенное перенаправление пакетов в локальный Ztunnel.

### Мультикластерная архитектура

Полное описание моделей, east-west gateway, сетевой изоляции, failover и практики настройки вынесено в отдельный документ **[Мультикластерная и мультисетевая архитектура Istio](./istio-multicluster.md)**.

Кратко, Istio поддерживает два основных режима:
- **Primary-Remote (разделенный Control Plane):** один istiod управляет кластерами. Remote регистрируются через `RemoteSecret` (Kubernetes Secret с kubeconfig); cross-cluster трафик — через стандартный Kubernetes EndpointSlice с внешними IP или через dedicated east-west gateway.
- **Multi-Primary (независимые Control Plane):** каждый кластер имеет свой `istiod`; синхронизация сервисов через `ServiceEntry` или federation через shared Kubernetes API server. Меньше распространен из-за сложности согласования сертификатов и политик.

**Быстрая проверка мультикластерности:**
```bash
# На Primary кластере: проверка статуса remote clusters
istioctl remote-clusters --context="${CTX_CLUSTER1}"

# Проверка наличия remote secrets
kubectl get secrets -n istio-system -l "istio/multiCluster=true"

# Проверка, что сервис из Remote кластера виден в Primary
kubectl get endpoints <remote-service>.<remote-ns> -n <local-ns>
```

### Расширяемость прокси: TrafficExtension

Начиная с Istio 1.30 (май 2026) конфигурация расширений Envoy унифицирована через API **`TrafficExtension`** (`extensions.istio.io/v1alpha1`), который заменяет `WasmPlugin` в качестве основного механизма расширения прокси. API поддерживает два типа расширений:

- **WebAssembly (Proxy-Wasm)**: модули, загружаемые из OCI-реестров; применяются к HTTP (L7) и TCP (L4).
- **Lua-скрипты**: инлайн-код внутри ресурса, выполняемый в Envoy; применяются только к HTTP (L7).

`TrafficExtension` работает во всех моделях данных plane — Sidecar, входящие/исходящие шлюзы и Waypoint Proxy в Ambient. Способ таргетинга зависит от модели:

- **`selector` (по меткам)** — для sidecar и шлюзов; ресурс в `istio-system` действует кластерно, в любом другом неймспейсе — только для workloads этого неймспейса.
- **`targetRefs` (на `Gateway`/`Service`)** — обязателен для Waypoint Proxy в Ambient, так как waypoint не сопоставляется с workloads через label-селекторы.

Порядок выполнения фильтров задаётся полями `phase` (`AUTHN`, `AUTHZ`, `STATS` или по умолчанию — у роутера) и `priority`: чем выше приоритет, тем раньше расширение в цепочке фильтров Envoy.

Пример Lua-расширения для waypoint в Ambient:

```yaml
apiVersion: extensions.istio.io/v1alpha1
kind: TrafficExtension
metadata:
  name: add-header
  namespace: my-app
spec:
  targetRefs:
  - kind: Gateway
    group: gateway.networking.k8s.io
    name: namespace-waypoint
  phase: AUTHN
  lua:
    inlineCode: |
      function envoy_on_request(req)
        req:headers():add("x-extension", "lua")
      end
```

**Практический сценарий: Wasm-модуль через TrafficExtension (OCI-реестр)**

WebAssembly-модули загружаются из OCI-образа; указывайте `sha256` для воспроизводимости и фиксированной версии:

```yaml
apiVersion: extensions.istio.io/v1alpha1
kind: TrafficExtension
metadata:
  name: my-authz-wasm
  namespace: my-app
spec:
  targetRefs:
  - kind: Gateway
    group: gateway.networking.k8s.io
    name: namespace-waypoint   # для Ambient обязателен targetRef
  phase: AUTHZ                # до/после авторизации
  priority: 10
  wasm:
    url: oci://registry.example.com/mesh/authz:v1.0.2
    sha256: 60d02a9c...        # digest модуля (проверяется при загрузке)
    imagePullPolicy: IfNotPresent
```

Таргетинг на sidecar и шлюзы выполняется через `selector` по меткам (ресурс в `istio-system` действует кластерно):

```yaml
spec:
  selector:
    matchLabels:
      app: my-app
  phase: STATS
  wasm:
    url: oci://registry.example.com/mesh/stats:v2
```

Проверка загрузки модуля и приложения фильтра:

```bash
# Конфигурация расширения видна в конфиг-дампе прокси
istioctl proxy-config all deploy/my-app -n my-app -o json | grep -i wasm

# Логи загрузчика
kubectl logs -n my-app deploy/my-app -c istio-proxy | grep -iE "wasm|extension"
```

Существующие ресурсы `WasmPlugin` остаются совместимыми: Istio внутренне преобразует их в `TrafficExtension` перед отправкой конфигурации в Envoy. Принудительной миграции в 1.30 нет, но всё новое развитие расширяемости ведётся в направлении `TrafficExtension`, для которого ожидается объявление `WasmPlugin` устаревшим в будущих выпусках.

### Крайние случаи и ограничения

1. **hostNetwork**: Поды, использующие `hostNetwork: true`, не могут быть enrolleed в Ambient Mesh, так как CNI не может перехватывать трафик на уровне узла без конфликта. Используйте модель Sidecar или выделенный namespace без Ambient.
2. **Привилегированные контейнеры**: При `privileged: true` или с capability `NET_ADMIN` CNI-перехват может не применяться. Решение: явно указать istio-cni через `cni.storage.istio.io/plugin-name` в annotations пода.
3. **Windows-контейнеры**: Ambient Mesh поддерживает только Linux-подобные ноды. Windows-контейнеры должны оставаться вне меша или использовать модель Sidecar (если поддерживается в будущих версиях).
4. **Конфликт с другим CNI**: Если в кластере уже используется Cilium, Calico или другой CNI, убедитесь, что `istio-cni` загружается последним. Проверка порядка модулей:
   ```bash
   lsmod | grep istio
   # Должен быть загружен после основного CNI
   ```
5. **Инициализация контейнеров (initContainers)**: В моделе Ambient init-контейнеры приложений не должны требовать доступа к сети до запуска Ztunnel; при необходимости добавьте `istio.io/dataplane-mode=ambient` на namespace и используйте `pause` на 1-2 секунды для гарантии готовности CNI.

### Отказоустойчивость

- **Ztunnel как SPOF**: Ztunnel разворачивается через `DaemonSet`. Если процесс падает, Kubernetes перезапускает его. Трафик прерывается только на время перезапуска и только на конкретной ноде.
- **Разделение уровней**: Падение Waypoint Proxy влияет только на L7-функции; базовое L4-соединение и mTLS продолжают работать через Ztunnel.
- **Отказоустойчивость istiod**: При использовании нескольких реплик istiod (>=2) Kubernetes Service распределяет нагрузку. Потеря одной реплики не нарушает выдачу сертификатов и xDS, так как данные хранятся в памяти (stateless). Для катастрофического сбоя используйте бэкап ConfigMap и перезапуск Deployment.
- **PodDisruptionBudget для istiod и шлюзов**: обязательный элемент для voluntary disruptions (drain нод, перезапусков API). Пример для istiod:
  ```yaml
  apiVersion: policy/v1
  kind: PodDisruptionBudget
  metadata:
    name: istiod-pdb
    namespace: istio-system
  spec:
    minAvailable: 1
    selector:
      matchLabels:
        app: istiod
  ```
  Аналогичный PDB создаётся для `istio-ingressgateway`/`istio-egressgateway` (minAvailable: 1–2 при масштабировании), чтобы обновления нод не отключали границу меша.
- **Дамп состояния**: Для диагностики состояния меша используйте:
  ```bash
  istioctl proxy-status
  istioctl x describe pod <pod-name> -n <namespace>
  ```

### Лучшие практики

1. **Постепенное внедрение**: Начинайте с режима Ambient L4 для обеспечения mTLS во всём кластере, затем добавляйте Waypoint Proxy только для сервисов, требующих L7-маршрутизации.
2. **Gateway API**: Используйте Gateway API (ресурсы `Gateway`, `HTTPRoute`) как основной интерфейс конфигурации. Legacy API (VirtualService) поддерживается, но не рекомендуется для новых проектов.
3. **Мониторинг Ztunnel**: Настраивайте алерты на использование ресурсов Ztunnel, так как он обслуживает все поды на ноде.
4. **Масштабирование istiod**: Для кластеров более 500 подов используйте минимум 2 реплики istiod с авто-scaler (HPA) по CPU > 70%.
5. **Управление CNI**: Используйте `nftables` для новых инсталляций (Istio 1.27+). При миграции с `iptables` планируйте окно обслуживания для переустановки DaemonSet CNI.
6. **Сертификаты**: Настройте автоматическую ротацию trust anchors перед истечением срока (рекомендуемый срок — 90 дней для промежуточных CA). Используйте `istioctl proxy-config secret` для проверки.
7. **Waypoint Proxy**: Разворачивайте waypoint per-namespace, а не per-service, для снижения оверхеда. Используйте HPA на основе CPU > 70% и памяти > 80%.
8. **Изоляция сред**: Разделяйте кластеры по окружениям (dev/staging/prod) разными неймспейсами или отдельными кластерами. Istio не предоставляет встроенной изоляции между окружениями внутри одного кластера на уровне Control Plane.
9. **Резервное копирование**: Регулярно экспортируйте конфигурацию меша (`kubectl get virtualservices,destinationrules,gateways,authorizationpolicies -A -o yaml`) и ConfigMap `istio` в `istio-system`.
10. **Режим Hybrid**: При переходе с Sidecar на Ambient не удаляйте sidecar сразу. Оставьте оба режима работающими параллельно в течение 2–4 недель для валидации трафика и политик.

### См. также

- [Управление трафиком в Istio](./traffic_management.md)
- [Конфигурация Sidecar в Istio](./istio-sidecar-configuration.md)
- [Политики безопасности Istio](./istio-security-policies.md)
- [Сравнение Istio и Linkerd](./istio_vs_linkerd.md)
- [Прокси Sidecar: реализации и сценарии](./proxy_sidecar.md)
- [Ограничение скорости (Rate Limiting) в Istio](./istio_rate_limiting.md)
- [Интеграция виртуальных машин (VM Workloads) в Istio](./istio_vm_workloads.md)
- [Канареечное обновление Istio](./istio_canary_upgrades.md)
- [Входящий шлюз (Ingress Gateway)](./istio-ingress-gateway.md)
- [Исходящий шлюз (Egress Gateway)](./istio-egress-gateway.md)
- [Мультикластерная архитектура Istio](./istio-multicluster.md)
- [Graceful shutdown и длинные соединения](./istio-graceful-shutdown.md)
- [Тюнинг производительности Istio](./istio-performance-tuning.md)

Документация: [Istio Architecture Guide](https://istio.io/latest/docs/ops/deployment/architecture/), [Istio Ambient In-Depth](https://istio.io/latest/docs/ambient/usage/).
