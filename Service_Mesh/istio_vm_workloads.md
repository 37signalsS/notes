# Интеграция виртуальных машин (VM Workloads) в Istio

## Определения

**WorkloadEntry** — ресурс Istio (`networking.istio.io/v1beta1`), представляющий внешнюю рабочую нагрузку (виртуальную машину, bare-metal сервер) как часть Service Mesh. Позволяет назначить SPIFFE-идентичность и подключить VM к mesh через sidecar-прокси.

**WorkloadGroup** — ресурс Istio (`networking.istio.io/v1alpha3`), описывающий группу идентичных VM (например, масштабируемую группу виртуальных машин). Используется совместно с `WorkloadEntry` для автоматической регистрации эндпоинтов.

**VM Sidecar** — прокси-контейнер Envoy, устанавливаемый на виртуальную машину для обработки трафика. В 2026 году VM sidecar устанавливается через `istioctl proxy.mesh` или через systemd-юнит.

**Auto Registration (автоматическая регистрация)** — механизм, при котором VM автоматически регистрируется в Service Mesh при старте sidecar'а, используя `WorkloadGroup` как шаблон.

**Смешанный режим (Mixed Mode)** — архитектура, в которой Kubernetes-поды и VM сосуществуют в одном mesh и обращаются друг к другу через единый Service Discovery.

---

## Основные концепции

### Зачем интегрировать VM в Service Mesh

| Задача | Решение через Istio |
| :--- | :--- |
| **Единая безопасность** | mTLS между VM и Kubernetes-подами через SPIFFE-идентичность |
| **Единая наблюдаемость** | Метрики, логи и трассировка VM в Kiali/Grafana/Prometheus наравне с подами |
| **Управление трафиком** | Маршрутизация, circuit breaking, retries для VM-сервисов |
| **Постепенная миграция** | VM и Kubernetes-сервисы могут сосуществовать в одном mesh во время миграции |

### Архитектура интеграции VM

```
┌─────────────────────────────────────────────────────┐
│                   Kubernetes Cluster                │
│  ┌──────────────┐  ┌──────────────┐                │
│  │  Pod A (K8s) │  │  Pod B (K8s) │                │
│  │  ┌────────┐  │  │  ┌────────┐  │                │
│  │  │  App   │  │  │  │  App   │  │                │
│  │  └───┬────┘  │  │  └───┬────┘  │                │
│  │      │       │  │      │       │                │
│  │  ┌───┴────┐  │  │  ┌───┴────┐  │                │
│  │  │ Envoy  │  │  │  │ Envoy  │  │                │
│  │  └────────┘  │  │  └────────┘  │                │
│  └──────────────┘  └──────────────┘                │
│                                                     │
│  ┌──────────────────────┐                           │
│  │      istiod          │  ← Выпуск сертификатов    │
│  │  (Control Plane)     │  ← xDS конфигурация      │
│  └──────────────────────┘                           │
└────────────────────────┬────────────────────────────┘
                         │ mTLS (SPIFFE)
                         │
┌────────────────────────┴────────────────────────────┐
│              Virtual Machine (VM)                   │
│  ┌──────────────┐  ┌────────────────────────────┐  │
│  │  Legacy App  │  │  Envoy Sidecar (systemd)   │  │
│  │  (port 8080) │  │  - SPIFFE сертификат        │  │
│  └──────────────┘  │  - mTLS с Kubernetes подами │  │
│                     │  - Метрики/логи             │  │
│                     └────────────────────────────┘  │
└─────────────────────────────────────────────────────┘
```

### WorkloadEntry и WorkloadGroup

**WorkloadGroup** определяет шаблон для группы VM:
- `metadata.name` — имя группы, используется в `ServiceEntry.endpoints`.
- `spec.template` — шаблон пода (аннотации,.labels), на основе которого создаются `WorkloadEntry`.
- `spec.probe` — health-check для автоматической регистрации/дерегистрации.

**WorkloadEntry** регистрирует отдельную VM:
- `spec.address` — IP-адрес VM.
- `spec.labels` — метки для политики безопасности и маршрутизации.
- `spec.serviceAccount` — ServiceAccount для SPIFFE-идентичности.
- `spec.network` — сеть (для мультикластера).

### Жизненный цикл VM в mesh

1. **Установка sidecar'а** на VM через `istioctl proxy mesh` или systemd.
2. **Регистрация** в Control Plane: sidecar запрашивает xDS-конфигурацию и сертификаты.
3. **WorkloadEntry** автоматически создается при successful registration.
4. **Health-check**: Control Plane мониторит здоровье VM через probe; при unhealthy — дерегистрация.
5. **Traffic**: VM получает трафик через Kubernetes Service с `endpoints` из `WorkloadEntry`.

---

## Практические сценарии

### Сценарий 1: Подготовка Control Plane для VM

Убедитесь, что istiod настроен на выдачу сертификатов для VM:

```bash
# 1. Проверка, что istiod слушает на порту 15012 (HTTP) для VM
kubectl get svc istiod -n istio-system -o jsonpath='{.spec.ports[*]}'
# → 15012 15012 TCP 15014 15014 TCP

# 2. Убедитесь, что namespace для VM существует и включен в mesh
kubectl create namespace vm-services
kubectl label namespace vm-services istio-injection=enabled

# 3. Создайте ServiceAccount для VM
cat <<EOF | kubectl apply -f -
apiVersion: v1
kind: ServiceAccount
metadata:
  name: vm-app-sa
  namespace: vm-services
EOF
```

### Сценарий 2: Создание WorkloadGroup и ServiceEntry

```yaml
# WorkloadGroup — шаблон для группы VM
apiVersion: networking.istio.io/v1alpha3
kind: WorkloadGroup
metadata:
  name: legacy-db-group
  namespace: vm-services
spec:
  metadata:
    labels:
      app: legacy-db
      version: v1
  template:
    labels:
      app: legacy-db
      version: v1
    serviceAccount: vm-app-sa
  probe:
    httpGet:
      path: /health
      port: 8080
    initialDelaySeconds: 5
    periodSeconds: 10
    timeoutSeconds: 3
    failureThreshold: 3
---
# ServiceEntry — подключение VM к mesh
apiVersion: networking.istio.io/v1beta1
kind: ServiceEntry
metadata:
  name: legacy-db
  namespace: vm-services
spec:
  hosts:
  - legacy-db.vm-services.svc.cluster.local
  location: MESH_INTERNAL
  ports:
  - number: 5432
    name: tcp
    protocol: TCP
  resolution: STATIC
  workloadSelector:
    labels:
      app: legacy-db
  endpoints:
  - address: 10.0.1.50
    labels:
      app: legacy-db
      version: v1
    network: vm-network
    serviceAccount: vm-app-sa
  - address: 10.0.1.51
    labels:
      app: legacy-db
      version: v1
    network: vm-network
    serviceAccount: vm-app-sa
```

**Проверка:**
```bash
# Проверка WorkloadGroup
kubectl get workloadgroup -n vm-services
# → NAME              AGE
# → legacy-db-group   5m

# Проверка ServiceEntry
kubectl get serviceentry -n vm-services
# → NAME         HOSTS                                    LOCATION       AGE
# → legacy-db    legacy-db.vm-services.svc.cluster.local   MESH_INTERNAL  5m

# Проверка, что VM-эндпоинты видны в mesh
istioctl proxy-config clusters deploy/my-app -n prod | grep legacy-db
# → cluster.outbound|5432||legacy-db.vm-services.svc.cluster.local
```

### Сценарий 3: Установка sidecar на VM

**На VM (Ubuntu/Debian):**
```bash
# 1. Скачайте и установите istioctl на VM
curl -L https://istio.io/downloadIstio | ISTIO_VERSION=1.32.0 sh -
cd istio-1.32.0
export PATH=$PWD/bin:$PATH

# 2. Сгенерируйте конфигурацию для VM
istioctl proxy mesh generate \
  --name legacy-db \
  --namespace vm-services \
  --meshID mesh1 \
  --trustDomain cluster.local \
  --serviceAccount vm-app-sa \
  --instructions ./vm-setup.md

# 3. Следуйте инструкциям из vm-setup.md (обычно):
# - Установить systemd-юнит для envoy
# - Скопировать сертификаты
# - Настроить сеть (iptables/nftables для перехвата трафика)

# 4. Запустите sidecar
sudo systemctl start istio-proxy

# 5. Проверьте статус
sudo systemctl status istio-proxy
# → active (running)

# 6. Проверьте, что sidecar получил сертификаты
openssl x509 -in /etc/certs/cert-chain.pem -noout -subject
# → subject: CN=spiffe://cluster.local/ns/vm-services/sa/vm-app-sa
```

### Сценарий 4: Автоматическая регистрация VM

При использовании `WorkloadGroup` с auto-registration VM автоматически регистрируется при старте sidecar'а:

```bash
# 1. Убедитесь, что WorkloadGroup создан
kubectl get workloadgroup legacy-db-group -n vm-services -o yaml

# 2. На VM: sidecar при старте создаст WorkloadEntry автоматически
sudo systemctl start istio-proxy

# 3. Проверьте на Control Plane
kubectl get workloadentry -n vm-services
# → NAME                  AGE
# → legacy-db-10.0.1.50   30s

# 4. Проверьте, что эндпоинт появился в Endpoints
kubectl get endpoints legacy-db -n vm-services
# → NAME         ENDPOINTS                          AGE
# → legacy-db    10.0.1.50:5432,10.0.1.51:5432      1m
```

### Сценарий 5: Обращение из Kubernetes-подов в VM-сервис

```yaml
# Deployment в Kubernetes, обращающийся к VM-сервису
apiVersion: apps/v1
kind: Deployment
metadata:
  name: api-server
  namespace: prod
spec:
  replicas: 2
  selector:
    matchLabels:
      app: api-server
  template:
    metadata:
      labels:
        app: api-server
    spec:
      serviceAccountName: api-server-sa
      containers:
      - name: app
        image: my-api:latest
        ports:
        - containerPort: 8080
        env:
        - name: DB_HOST
          value: "legacy-db.vm-services.svc.cluster.local"
        - name: DB_PORT
          value: "5432"
---
# Service для VM-сервиса (опционально, для DNS-резолва)
apiVersion: v1
kind: Service
metadata:
  name: legacy-db
  namespace: vm-services
spec:
  selector:
    app: legacy-db
  ports:
  - port: 5432
    targetPort: 5432
    protocol: TCP
```

**Проверка связи:**
```bash
# Из Kubernetes-пода
kubectl exec -it deploy/api-server -n prod -- curl -s http://legacy-db.vm-services.svc.cluster.local:5432/health
# → 200 OK (или аналогичный ответ health-check'а)

# Проверка mTLS
kubectl exec -it deploy/api-server -n prod -- curl -v http://legacy-db.vm-services.svc.cluster.local:5432/health 2>&1 | grep -i "subject\|issuer"
# → SSL connection using TLSv1.3 / ...
# → Server certificate:
# →  subject: CN=spiffe://cluster.local/ns/vm-services/sa/vm-app-sa
```

### Сценарий 6: Мониторинг VM в Kiali

VM-сервисы отображаются в Kiali наравне с Kubernetes-подами:

```bash
# Проверка, что VM появился в Kiali
# 1. Откройте Kiali UI
kubectl port-forward -n istio-system svc/kiali 20001:20001

# 2. Перейдите вкладку Graph → выберите namespace vm-services
# 3. VM-сервис будет отображен как узел графа с меткой "VM"

# Проверка метрик VM через Prometheus
kubectl exec -n monitoring prometheus-0 -- wget -qO- 'http://localhost:9090/api/v1/query?query=istio_requests_total{destination_workload="legacy-db",destination_workload_namespace="vm-services"}'
# → {"status":"success","data":{"resultType":"vector","result":[{"metric":{...},"value":[1695379200,"1500"]}]}}
```

### Сценарий 7: Политики безопасности для VM

```yaml
# Разрешить обращение к VM только из определенного неймспейса
apiVersion: security.istio.io/v1
kind: AuthorizationPolicy
metadata:
  name: allow-prod-to-vm
  namespace: vm-services
spec:
  selector:
    matchLabels:
      app: legacy-db
  action: ALLOW
  rules:
  - from:
    - source:
        namespaces: ["prod", "staging"]
    to:
    - operation:
        ports: ["5432"]
```

```bash
# Проверка
kubectl exec -n prod deploy/api-server -- curl -s -o /dev/null -w "%{http_code}" http://legacy-db.vm-services.svc.cluster.local:5432/health
# → 200

kubectl exec -n dev deploy/test-app -- curl -s -o /dev/null -w "%{http_code}" http://legacy-db.vm-services.svc.cluster.local:5432/health
# → 403 (заблокировано AuthorizationPolicy)
```

---

## Типичные ошибки и устранение неполадок

| Ошибка | Причина | Решение |
| :--- | :--- | :--- |
| **VM не регистрируется в mesh** | Sidecar не может достучаться до istiod (15012) | Проверьте сетевую связность: `curl http://istiod.istio-system.svc.cluster.local:15012/healthz/ready`. Проверьте DNS на VM. |
| **Сертификат не выпущен** | ServiceAccount не существует или RBAC запрещает доступ | Проверьте: `kubectl get sa vm-app-sa -n vm-services`. Убедитесь, что istiod имеет права на создание сертификатов. |
| **VM не видна в Kubernetes Endpoints** | WorkloadEntry не создан или labels не совпадают | Проверьте `kubectl get workloadentry -n vm-services`. Убедитесь, что labels в WorkloadEntry совпадают с `workloadSelector` в ServiceEntry. |
| **mTLS handshake failure** | У VM и Kubernetes-подов разные trust domains | Убедитесь, что VM использует тот же trustDomain (`cluster.local`). Проверьте корневой сертификат на VM: `openssl x509 -in /etc/certs/root-cert.pem -noout -subject`. |
| **Трафик не маршрутизируется на VM** | ServiceEntry не включает эндпоинт VM | Проверьте `istioctl proxy-config clusters deploy/<pod> -n <ns> | grep <vm-service>`. Убедитесь, что `resolution: STATIC` и `endpoints` указаны явно. |
| **VM sidecar падает при старте** | Неверный путь к сертификатам или конфигурации | Проверьте логи: `journalctl -u istio-proxy`. Убедитесь, что файлы конфигурации скопированы в правильные директории. |

---

## Лучшие практики эксплуатации

1. **Одна trust domain:** используйте единый trust domain (`cluster.local`) для всего mesh, включая VM. Это обеспечивает взаимную аутентификацию без дополнительной настройки.
2. **ServiceAccount per VM:** создайте отдельный ServiceAccount для каждой группы VM. Это позволяет настраивать гранулярные политики безопасности.
3. **Автоматическая регистрация:** используйте `WorkloadGroup` с auto-registration для динамических групп VM. Ручная регистрация через `WorkloadEntry` подходит для статических серверов.
4. **Health-check:** настройте `probe` в `WorkloadGroup` для автоматической дерегистрации unhealthy VM. Это предотвращает направление трафика на неработающие экземпляры.
5. **NetworkPolicy:** настройте NetworkPolicy на VM для ограничения доступа только к istiod и необходимым сервисам.
6. **Мониторинг:** добавьте VM в ServiceMonitor для Prometheus. Метрики Envoy на VM собираются аналогично Kubernetes-подам.
7. **Безопасность:** не храните сертификаты на VM в открытом виде. Используйте temporary credentials или hardware security modules (HSM) для production.
8. **Миграция:** при миграции VM в Kubernetes используйте canary-подход: сначала запустите новую версию в Kubernetes, затем переключите трафик через权重 в ServiceEntry.

---

## Дополнительная информация

### Ограничения

1. **Ambient Mesh и VM:** Ambient Mesh (Ztunnel) в 2026 году не поддерживает VM напрямую. VM должны использовать модель Sidecar (Envoy).
2. **Windows VM:** Istio sidecar поддерживает только Linux-based VM. Windows VM должны использовать mesh через прокси на уровне сети (например, Envoy на отдельном Linux-хосте).
3. **Лицензирование:** Envoy sidecar на VM распространяется под лицензией Apache 2.0. Проверьте требования вашего окружения.

### Связанные темы

- [Архитектура Istio](./istio_architecture.md) — overview архитектуры и компонентов
- [Политики безопасности Istio](./istio-security-policies.md) — mTLS, AuthorizationPolicy
- [Конфигурация Sidecar в Istio](./istio-sidecar-configuration.md) — Sidecar resource и egress control

Документация: [Istio VM Support](https://istio.io/latest/docs/ops/configuration/vm-support/), [WorkloadEntry Reference](https://istio.io/latest/docs/reference/config/networking/workload-entry/).
