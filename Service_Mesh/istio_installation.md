# Установка и базовая настройка Istio

## Определения

**istioctl** — официальная утилита командной строки для установки, настройки, отладки и управления Istio. В 2026 году является мощным инструментом для управления Ambient Mesh, инспекции сетевых путей и отладки Gateway API.

**Gateway API** — стандарт Kubernetes (Networking API), ставший в 2025–2026 гг. основным способом конфигурации трафика в Istio (вместо `VirtualService`). Установка Gateway API CRDs является обязательным условием для полноценной работы меша.

**Профили конфигурации (Profiles)** — наборы предустановленных настроек Istio, оптимизированные для различных сценариев (демо, продакшен, минимальная установка, ambient).

**Sidecar Injection (инъекция сайдкара)** — процесс добавления прокси-контейнера Envoy в Pod приложения. В 2026 году сосуществует с моделью Ambient, но постепенно вытесняется ею в новых инсталляциях.

**Ambient Mesh (Sidecar-less)** — архитектура Istio (General Availability), разделяющая функции прокси на L4 (Ztunnel) и L7 (Waypoint Proxy). Позволяет включать поды в меш без инъекции Sidecar и перезапуска контейнеров.

**istio-cni** — DaemonSet, выполняющий прозрачное перенаправление трафика в Ztunnel без привилегированного init-контейнера. Поддерживает `iptables`, `nftables` (приоритетен с 1.27+) и eBPF-редирект.

**Ztunnel (Zero Trust Tunnel)** — узеловый DaemonSet (на Rust), обеспечивающий mTLS и L4-авторизацию для всех подов на узле в режиме Ambient. Использует протокол HBONE (HTTP/2 CONNECT) для инкапсуляции трафика.

**Waypoint Proxy** — Deployment на базе Envoy для L7-функций (HTTP-маршрутизация, сложные политики) в режиме Ambient. Создаётся по требованию для конкретного неймспейса или сервиса.

---

## Предварительные требования

### Аппаратные и программные требования

**Kubernetes:**
- Версия **1.30+** (рекомендуется 1.32–1.36 для Istio 1.30+)
- Статус кластера: `Ready` на всех нодах
- Режимы работы: bare-metal, виртуализация (KVM/VirtualBox), любые оркестраторы поверх Linux

**Ядро ОС:**
- Linux 5.10+ с поддержкой eBPF (для акселерации Istio CNI)
- Модуль `bpf` загружен: `lsmod | grep bpf`
- Для `nftables`: ядро 5.13+ (Istio 1.27+ автоматически определяет и использует nftables при наличии)

**Сетевые интерфейсы:**
- Каждая нода должна иметь уникальный hostname, разрешаемый через DNS или `/etc/hosts`
- Отсутствие конфликтов CIDR между cluster CIDR и сервисами, которые будут маршрутизироваться через mesh

**Ресурсы Control Plane (istiod):**
- **Минимум:** 1 vCPU, 2 GB RAM
- **Рекомендуется (prod, >500 подов):** 2+ реплики istiod, по 500m CPU и 1Gi RAM на реплику
- **Дисковое пространство:** 10 GB на ноду для Ztunnel (логи, метрики)

**Ресурсы Data Plane (Ztunnel):**
- **На ноду:** 50m CPU (requests), 200m CPU (limits), 64Mi RAM (requests), 256Mi RAM (limits)
- **Waypoint Proxy:** 100m CPU / 128Mi RAM на реплику при нагрузке до 1000 RPS

**CNI-плагин:**
- Istio CNI устанавливается вместе с профилем `ambient` и требует совместимого основного CNI (Calico, Cilium, Flannel или bridge/ macvlan)
- Порядок загрузки: основной CNI должен загружаться перед `istio-cni`
- Проверка: `lsmod | grep -E "calico|cilium|flannel|istio"`

### Gateway API CRDs

Перед установкой Istio необходимо убедиться, что в кластере установлены CRD Gateway API (версии 1.1.0+).

```bash
# Проверка наличия CRD
kubectl get crd gateways.gateway.networking.k8s.io || \
  kubectl apply -f https://github.com/kubernetes-sigs/gateway-api/releases/download/v1.1.0/standard-install.yaml

# Проверка версии CRD
kubectl get crd gateways.gateway.networking.k8s.io -o jsonpath='{.status.conditions[?(@.type=="Established")].status}'
# → True
```

---

## Варианты установки

В современных инфраструктурах (2026) используются три основных метода, каждый из которых имеет свои преимущества:
1.  **Helm (рекомендуется для Production/GitOps)**: стандартный способ управления жизненным циклом. В 1.32+ установка разделена на модули: `base`, `istiod`, `cni`, `ztunnel`, `gateway`.
2.  **istioctl (рекомендуется для управления и отладки)**: обеспечивает прямой контроль через профили и удобные инструменты диагностики. Используется для быстрого развертывания Ambient режима.
3.  **Istio Operator (рекомендуется для сложной кастомизации)**: позволяет декларативно управлять ресурсами через CRD `IstioOperator`. Хотя сообщество движется к Helm, оператор остается актуальным для сложных Enterprise-сценариев.

---

## Установка через istioctl

### 1. Подготовка и скачивание

Istio требует работающий Kubernetes кластер.

```bash
# Скачивание актуальной версии (пример для 1.32)
curl -L https://istio.io/downloadIstio | ISTIO_VERSION=1.32.0 sh -

# Добавление в PATH
cd istio-1.32.0
export PATH=$PWD/bin:$PATH

# Проверка версии CLI и связи с кластером
istioctl version
# → client version: 1.32.0
# → control plane version: N/A (не установлен)
```

### 2. Выбор профиля конфигурации

| Профиль | Компоненты | Назначение |
| :--- | :--- | :--- |
| **default** | `istiod`, Ingress Gateway | Рекомендуется для большинства рабочих нагрузок с Sidecars. |
| **demo** | `istiod`, Ingress, Egress | Для обучения (включает всё, но потребляет много ресурсов). |
| **minimal** | `istiod` | Только плоскость управления, без шлюзов. |
| **ambient** | `istiod`, CNI, Ztunnel | **Рекомендуемый профиль 2026 г.** для Sidecar-less архитектуры. |
| **empty** | — | База для полностью кастомных конфигураций. |

### 3. Выполнение установки

```bash
# Установка с профилем ambient (включает Ztunnel и CNI)
istioctl install --set profile=ambient -y

# Установка классического профиля с кастомизацией
istioctl install --set profile=default --set meshConfig.accessLogFile=/dev/stdout -y

# Установка demo-профиля (обучение: istiod + Ingress + Egress, много ресурсов)
istioctl install --set profile=demo -y
```

### 4. Верификация установки

```bash
# Проверка статуса компонентов
kubectl get pods -n istio-system
# → NAME                                   READY   STATUS
# → istiod-<hash>-0                        1/1     Running
# → istio-cni-node-<node>                  1/1     Running
# → ztunnel-<node>                         1/1     Running

# Проверка версии
istioctl version
# → client version: 1.32.0
# → control plane version: 1.32.0

# Проверка установки
istioctl verify-install
```

---

## Кастомизация через Istio Operator

Использование оператора позволяет декларативно управлять параметрами установки.

### 1. Подготовка манифеста
```bash
# Выгрузка профиля demo для редактирования
istioctl profile dump demo > demo-operator.yaml
```

### 2. Примеры кастомизации в YAML
```yaml
apiVersion: install.istio.io/v1alpha1
kind: IstioOperator
spec:
  profile: demo
  components:
    egressGateways:
    - name: istio-egressgateway
      enabled: true
      k8s:
        resources:
          requests:
            cpu: 100m
            memory: 128Mi
    ingressGateways:
    - name: custom-ingressgateway
      enabled: true
      label:
        istio: custom-ingressgateway
      k8s:
        service:
          type: LoadBalancer
          ports:
          - port: 80
            name: http
          - port: 443
            name: https
```

### 3. Применение и обновление
```bash
# Установка на основе файла
istioctl install -f demo-operator.yaml -y

# Обновление (Upgrade) с сохранением настроек
istioctl upgrade -f demo-operator.yaml -y
```

---

## Установка через Helm

Рекомендуется для промышленной эксплуатации. Установка в 2026 году строго модульная.

### 1. Подготовка
```bash
helm repo add istio https://istio-release.storage.googleapis.com/charts
helm repo update
```

### 2. Установка базовых компонентов
```bash
# 1. Base (CRDs и общие ресурсы)
helm install istio-base istio/base -n istio-system --create-namespace

# 2. Istiod (Control Plane)
helm install istiod istio/istiod -n istio-system --wait

# 3. CNI (Обязательно для Ambient и безопасности Sidecar)
helm install istio-cni istio/cni -n istio-system --set profile=ambient

# 4. Ztunnel (Node-level L4 Proxy для Ambient)
helm install ztunnel istio/ztunnel -n istio-system
```

### 3. Пример кастомизации values.yaml
```yaml
# values.yaml для продакшена
global:
  nativeNftables: true
  proxy:
    resources:
      requests:
        cpu: 50m
        memory: 64Mi
      limits:
        cpu: 200m
        memory: 128Mi

ztunnel:
  resources:
    requests:
      cpu: 50m
      memory: 64Mi
    limits:
      cpu: 200m
      memory: 256Mi

istiod:
  replicaCount: 2
  resources:
    requests:
      cpu: 500m
      memory: 1Gi
    limits:
      cpu: "2"
      memory: 4Gi

cni:
  ambient:
    enabled: true
    logging:
      level: info
```

Применение кастомизации:
```bash
helm upgrade --install istio-base istio/base -n istio-system --create-namespace -f values.yaml
helm upgrade --install istiod istio/istiod -n istio-system -f values.yaml
helm upgrade --install istio-cni istio/cni -n istio-system -f values.yaml --set profile=ambient
helm upgrade --install ztunnel istio/ztunnel -n istio-system -f values.yaml
```

### 4. Установка шлюзов (Gateway API)
Рекомендуется использовать чарт `gateway` для развертывания шлюзов Ingress/Egress.
```bash
helm install istio-ingress istio/gateway -n istio-ingress --create-namespace
```

---

## Внедрение в меш (Enrolling Workloads)

### 1. Модель Ambient (Sidecar-less, Рекомендуется)
В этом режиме поды включаются в меш мгновенно, без перезапуска. L4 функции (mTLS) обеспечивает Ztunnel.
```bash
# Активация Ambient режима для неймспейса
kubectl label namespace <ns-name> istio.io/dataplane-mode=ambient
```

### 2. Модель Sidecar (Классическая)
Требует перезапуска подов для внедрения прокси Envoy.
```bash
# Активация Sidecar инъекции
kubectl label namespace <ns-name> istio-injection=enabled
kubectl rollout restart deployment -n <ns-name>
```

### 3. Ручная инъекция Sidecar
Используется для конкретных YAML-файлов или при отсутствии прав на лейблинг неймспейса.
```bash
istioctl kube-inject -f my-app.yaml | kubectl apply -f -
```

---

## Настройка L7 функций (Waypoint Proxy)

В режиме Ambient для работы L7 (HTTP маршрутизация, политики авторизации по заголовкам) требуется развернуть Waypoint Proxy.

```bash
# Развертывание Waypoint для неймспейса
istioctl waypoint apply --namespace <ns-name>

# Настройка использования Waypoint неймспейсом
kubectl label namespace <ns-name> istio.io/use-waypoint=waypoint
```

### Масштабирование Waypoint Proxy

Waypoint Proxy масштабируется через стандартный Kubernetes HPA. Рекомендуемые лимиты: 100m CPU / 128Mi RAM на реплику при нагрузке до 1000 RPS.

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

---

## Обновление (Upgrade)

### Через istioctl
```bash
# Проверка текущей версии
istioctl version

# Обновление с сохранением конфигурации
istioctl upgrade -y

# Проверка после обновления
istioctl version
kubectl get pods -n istio-system -l app=istiod -o wide
```

### Через Helm
```bash
# Обновление компонентов
helm upgrade istio-base istio/base -n istio-system -f values.yaml
helm upgrade istiod istio/istiod -n istio-system -f values.yaml
helm upgrade istio-cni istio/cni -n istio-system -f values.yaml
helm upgrade ztunnel istio/ztunnel -n istio-system -f values.yaml
```

### Rolling Restart istiod
```bash
kubectl rollout restart deployment/istiod -n istio-system
kubectl rollout status deployment/istiod -n istio-system
```

### Канареечное обновление по ревизиям (Revision-based Canary Upgrade)

Стратегия обновления, при которой новая версия istiod устанавливается параллельно со старой. Трафик постепенно переключается на новую ревизию, что позволяет обнаружить проблемы до полного переключения. Подробный сценарный обзор см. в [Канареечное обновление Istio](./istio_canary_upgrades.md).

```bash
# 1. Установка новой ревизии alongside старой
istioctl install --set profile=default --set revision=v1-32-0 -y

# 2. Проверка, что обе ревизии работают
kubectl get pods -n istio-system -l app=istiod
# → istiod-v1-31-0-abc123   1/1     Running   0   30d
# → istiod-v1-32-0-def456   1/1     Running   0   5m

# 3. Переключение тестового namespace на новую ревизию
kubectl label namespace my-app istio.io/rev=v1-32-0 --overwrite
kubectl rollout restart deployment -n my-app

# 4. Валидация
istioctl analyze -n my-app
istioctl proxy-status | grep my-app

# 5. При проблемах — откат за секунды
kubectl label namespace my-app istio.io/rev=v1-31-0 --overwrite
kubectl rollout restart deployment -n my-app

# 6. После успешной валидации — удаление старой ревизии
istioctl uninstall --revision=v1-31-0 -y
```

---

## Миграция с Sidecar на Ambient

Поэтапный переход без Downtime:

```bash
# 1. Убедиться, что кластер установлен в режиме Ambient
istioctl install --set profile=ambient -y

# 2. Отключить automatic sidecar injection для namespace
kubectl label namespace my-app istio-injection-

# 3. Перезапустить поды (они подключатся к Ambient через ztunnel)
kubectl rollout restart deployment/my-app -n my-app

# 4. Проверить, что поды в Ambient-режиме
istioctl experimental ambient describe pod my-app-pod -n my-app
# → L4 traffic handled by ztunnel on node-1

# 5. Если нужен L7 — создать waypoint
istioctl waypoint apply -n my-app --enroll-namespace
```

**Ожидаемые результаты:**
- Задержка снижается на 40–60%.
- Потребление RAM на ноде падает на 70–80%.
- L7-функции (Canary, Fault Injection) требуют развертывания Waypoint.

---

## Проверка и диагностика

### 1. Верификация Ambient Mesh
```bash
# Описание сетевого пути пода в Ambient
istioctl ambient describe pod <pod-name> -n <ns-name>
# → Результат должен показывать ztunnel (L4) и waypoint (L7, если настроен)
```

### 2. Проверка статуса прокси и Control Plane
```bash
# Статус синхронизации конфигураций
istioctl proxy-status

# Проверка версии компонентов
istioctl version
```

### 3. Анализ конфигураций
```bash
# Поиск ошибок в ресурсах меша (VirtualServices, Gateways и т.д.)
istioctl analyze -A

# Валидация конкретного файла
istioctl validate -f virtual-service.yaml
```

### 4. Проверка инъекции сайдкара
```bash
# Проверка типа сайдкара (Native Sidecar)
kubectl get pod my-app-pod -n my-app -o jsonpath='{.spec.initContainers[?(@.name=="istio-proxy")].restartPolicy}'
# → Always

# Проверка статуса инъекции через istioctl
istioctl x check-inject deploy/my-app -n my-app
# → Pod has sidecar injected: istio-proxy (native: true)
```

### 5. Проверка установки
```bash
istioctl verify-install
```

---

## Бэкап и восстановление

```bash
# Экспорт всех ресурсов Istio (VirtualService, DestinationRule, Gateway, AuthorizationPolicy)
kubectl get virtualservices,destinationrules,gateways,authorizationpolicies,envoyfilters -A -o yaml > istio-config-backup.yaml

# Бэкап ConfigMap с конфигурацией меша
kubectl get configmap istio -n istio-system -o yaml > istio-mesh-config-backup.yaml

# Бэкап лейблов неймспейсов для инъекции
kubectl get ns -l istio-injection=enabled -o yaml > istio-ns-backup.yaml

# Восстановление
kubectl apply -f istio-config-backup.yaml
kubectl apply -f istio-mesh-config-backup.yaml
kubectl apply -f istio-ns-backup.yaml
```

---

## Удаление Istio

```bash
# Удаление через Helm (в обратном порядке)
helm uninstall ztunnel -n istio-system
helm uninstall istio-cni -n istio-system
helm uninstall istiod -n istio-system
helm uninstall istio-base -n istio-system

# Полное удаление через istioctl
istioctl uninstall --purge -y
```

---

## Устранение неполадок

### Типичные ошибки установки

| Симптом | Причина | Решение |
| :--- | :--- | :--- |
| `istioctl install` завершается с ошибкой CNI | Конфликт с существующим CNI | Проверьте `kubectl get pods -n kube-system -l k8s-app=calico` (или другой CNI). Убедитесь, что `istio-cni` загружается последним: `lsmod \| grep istio`. |
| Pod не enrolls в Ambient Mesh | Неймспейс не помечен или CNI не Ready | Примените метку: `kubectl label namespace <ns> istio.io/dataplane-mode=ambient`. Проверьте pods CNI: `kubectl get pods -n istio-system -l app=istio-cni-node`. |
| `failed to setup iptables rules: exit status 2` | Конфликт правил iptables/nftables | Переключите на `nftables` (`--set values.global.nativeNftables=true`) или увеличьте лимиты: `sysctl -w net.netfilter.nf_conntrack_max=1048576`. |
| Waypoint не создаётся | Нет Gateway API или недостаточно прав | Проверьте CRD: `kubectl get crd gateways.gateway.networking.k8s.io`. Проверьте права istiod: `kubectl auth can-i create gateways -n <ns> --as system:serviceaccount:istio-system:istiod`. |
| Высокий CPU на ноде от Ztunnel | Конфликт правил или слишком много подов | Переключите на `nftables`, проверьте количество правил: `iptables -L -t nat -v \| wc -l`. |
| mTLS не работает между подами | Сертификаты не синхронизированы | Проверьте `istioctl proxy-status`. Убедитесь, что istiod выпустил сертификаты: `istioctl proxy-config secret <pod> -n <ns>`. |
| `Connection reset by peer` | `PeerAuthentication: STRICT`, клиент без mesh | Переведите в `PERMISSIVE` или добавьте ServiceEntry для внешних сервисов. |

### Диагностика CNI
```bash
# Логи CNI для диагностики перехвата
kubectl logs -n istio-system -l app=istio-cni-node --tail=100

# Проверка загруженных модулей
lsmod | grep istio
# Должен быть загружен после основного CNI

# Проверка выбранного стека (iptables/nftables)
kubectl get cm istio-cni-config -n istio-system -o jsonpath='{.data.values}' | grep -i nftables
```

### Диагностика Ztunnel
```bash
# Логи Ztunnel на конкретной ноде
POD=$(kubectl get pods -n istio-system -l app=ztunnel -o jsonpath='{.items[0].metadata.name}')
kubectl logs -n istio-system $POD --tail=100

# Метрики Ztunnel
kubectl exec -n istio-system -it <ztunnel-pod> -- curl -s localhost:15020/metrics | grep ztunnel

# Использование ресурсов
kubectl top pods -n istio-system -l app=ztunnel
```

---

## Лучшие практики

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

---

## Крайние случаи и ограничения

1. **hostNetwork**: Поды, использующие `hostNetwork: true`, не могут быть enrolleed в Ambient Mesh, так как CNI не может перехватывать трафик на уровне узла без конфликта. Используйте модель Sidecar или выделенный namespace без Ambient.
2. **Привилегированные контейнеры**: При `privileged: true` или с capability `NET_ADMIN` CNI-перехват может не применяться. Решение: явно указать istio-cni через `cni.storage.istio.io/plugin-name` в annotations пода.
3. **Windows-контейнеры**: Ambient Mesh поддерживает только Linux-подобные ноды. Windows-контейнеры должны оставаться вне меша или использовать модель Sidecar (если поддерживается в будущих версиях).
4. **Конфликт с другим CNI**: Если в кластере уже используется Cilium, Calico или другой CNI, убедитесь, что `istio-cni` загружается последним. Проверка порядка модулей:
   ```bash
   lsmod | grep istio
   # Должен быть загружен после основного CNI
   ```
5. **Инициализация контейнеров (initContainers)**: В моделе Ambient init-контейнеры приложений не должны требовать доступа к сети до запуска Ztunnel; при необходимости добавьте `istio.io/dataplane-mode=ambient` на namespace и используйте `pause` на 1-2 секунды для гарантии готовности CNI.

---

## Дополнительная информация

- [Архитектура Istio и режим Ambient](./istio_architecture.md)
- [Прокси Sidecar: реализации и сценарии](./proxy_sidecar.md)
- [Наблюдаемость Istio (Kiali, Grafana)](./istio_observability_and_tools.md)
- [Политики безопасности Istio](./istio-security-policies.md)
- [Сравнение Istio и Linkerd](./istio_vs_linkerd.md)
- [Канареечное обновление Istio](./istio_canary_upgrades.md)
- [Ограничение скорости (Rate Limiting) в Istio](./istio_rate_limiting.md)
- [Интеграция виртуальных машин (VM Workloads) в Istio](./istio_vm_workloads.md)

Документация: [Istio Installation Guides](https://istio.io/latest/docs/setup/install/).
