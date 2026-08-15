# Установка и базовая настройка Istio

## Определения

**istioctl** — официальная утилита командной строки для установки, настройки, отладки и управления Istio. В 2026 году является мощным инструментом для управления Ambient Mesh, инспекции сетевых путей и отладки Gateway API.

**Gateway API** — стандарт Kubernetes (Networking API), ставший в 2025–2026 гг. основным способом конфигурации трафика в Istio (вместо `VirtualService`). Установка Gateway API CRDs является обязательным условием для полноценной работы меша.

**Профили конфигурации (Profiles)** — наборы предустановленных настроек Istio, оптимизированные для различных сценариев (демо, продакшен, минимальная установка, ambient).

**Sidecar Injection (инъекция сайдкара)** — процесс добавления прокси-контейнера Envoy в Pod приложения. В 2026 году сосуществует с моделью Ambient, но постепенно вытесняется ею в новых инсталляциях.

**Ambient Mesh (Sidecar-less)** — архитектура Istio (General Availability), разделяющая функции прокси на L4 (Ztunnel) и L7 (Waypoint Proxy). Позволяет включать поды в меш без инъекции Sidecar и перезапуска контейнеров.

---

## Варианты установки

В современных инфраструктурах (2026) используются три основных метода, каждый из которых имеет свои преимущества:
1.  **Helm (рекомендуется для Production/GitOps)**: стандартный способ управления жизненным циклом. В 1.32+ установка разделена на модули: `base`, `istiod`, `cni`, `ztunnel`, `gateway`.
2.  **istioctl (рекомендуется для управления и отладки)**: обеспечивает прямой контроль через профили и удобные инструменты диагностики. Используется для быстрого развертывания Ambient режима.
3.  **Istio Operator (рекомендуется для сложной кастомизации)**: позволяет декларативно управлять ресурсами через CRD `IstioOperator`. Хотя сообщество движется к Helm, оператор остается актуальным для сложных Enterprise-сценариев.

---

## Предварительное условие: Kubernetes Gateway API

Перед установкой Istio необходимо убедиться, что в кластере установлены CRD Gateway API (версии 1.1.0+).

```bash
# Проверка наличия CRD
kubectl get crd gateways.gateway.networking.k8s.io || \
  kubectl apply -f https://github.com/kubernetes-sigs/gateway-api/releases/download/v1.1.0/standard-install.yaml
```

---

## Установка через istioctl

### 1. Подготовка и скачивание

Istio требует работающий Kubernetes кластер (EKS, GKE, AKS или локальные Kind/Minikube).

```bash
# Скачивание актуальной версии (пример для 1.32)
curl -L https://istio.io/downloadIstio | ISTIO_VERSION=1.32.0 sh -

# Добавление в PATH
cd istio-1.32.0
export PATH=$PWD/bin:$PATH

# Проверка версии CLI и связи с кластером
istioctl version
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

### 3. Установка шлюзов (Gateway API)
Рекомендуется использовать чарт `gateway` для развертывания шлюзов Ingress/Egress.
```bash
helm install istio-ingress istio/gateway -n istio-ingress --create-namespace
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

### 4. Проверка установки
```bash
istioctl verify-install
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

## Дополнительная информация

- [Архитектура Istio и режим Ambient](./istio_architecture.md)
- [Прокси Sidecar: реализации и сценарии](./proxy_sidecar.md)
- [Наблюдаемость Istio (Kiali, Grafana)](./istio_observability_and_tools.md)
- [Политики безопасности Istio](./istio-security-policies.md)
- [Сравнение Istio и Linkerd](./istio_vs_linkerd.md)

Документация: [Istio Installation Guides](https://istio.io/latest/docs/setup/install/).
