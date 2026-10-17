# Интеграция виртуальных машин (VM Workloads) в Istio

**Актуально для:** Istio 1.31.x

## Определения

**WorkloadEntry** — ресурс Istio (`networking.istio.io/v1`), представляющий внешнюю рабочую нагрузку (виртуальную машину, bare-metal сервер) как часть Service Mesh. Позволяет назначить SPIFFE-идентичность и подключить VM к mesh через sidecar-прокси.

**WorkloadGroup** — ресурс Istio (`networking.istio.io/v1`), описывающий группу идентичных VM (например, масштабируемую группу виртуальных машин). Используется совместно с `WorkloadEntry` для автоматической регистрации эндпоинтов.

**VM Sidecar** — компонент Envoy + istio-agent, устанавливаемый на VM через пакет `istio-sidecar` (`deb`/`rpm`) и запускаемый как systemd-юнит `istio`. Конфигурация и сертификаты для VM генерирует управленческий узел через `istioctl x workload entry configure`.

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
- `spec.template` — шаблон пода (аннотации, labels), на основе которого создаются `WorkloadEntry`.
- `spec.probe` — health-check для автоматической регистрации/дерегистрации.

**WorkloadEntry** регистрирует отдельную VM:
- `spec.address` — IP-адрес VM.
- `spec.labels` — метки для политики безопасности и маршрутизации.
- `spec.serviceAccount` — ServiceAccount для SPIFFE-идентичности.
- `spec.network` — сеть (для мультикластера).

### Жизненный цикл VM в mesh

1. **Установка sidecar'а** на VM через пакет `istio-sidecar` и systemd-юнит `istio` (конфигурация генерируется через `istioctl x workload entry configure` на управленческом узле).
2. **Регистрация** в Control Plane: sidecar запрашивает xDS-конфигурацию и сертификаты.
3. **WorkloadEntry** автоматически создаётся при успешной регистрации.
4. **Health-check**: Control Plane мониторит здоровье VM через probe; при unhealthy — дерегистрация.
5. **Traffic**: VM получает трафик через Kubernetes Service с `endpoints` из `WorkloadEntry`.

---

## Предварительные требования

- Кластер **Kubernetes 1.32–1.37** с Istio **1.31.2** (см. [сценарий установки](./istio_installation.md)).
- **istioctl 1.31** на управленческой машине, откуда есть `kubectl`-доступ к кластеру.
- **East-west gateway**, через который VM достигает `istiod`. На кластере выполните (пример):
  ```bash
  kubectl apply -n istio-system -f samples/multicluster/expose-istiod.yaml
  ```
  Sidecar VM подключается к istiod на порт **15012** (XDS) и использует **15014** для проверки готовности.
- **ServiceAccount** для VM в неймспейсе (`vm-app-sa` в примерах) и единый **trust domain** `cluster.local` для всего mesh.
- На VM — **Linux** (Debian/Ubuntu или RHEL/CentOS 8) с `sudo`; устанавливается пакет `istio-sidecar` (`deb`/`rpm`).
- **Third-party service account tokens** включены в кластере (иначе добавьте `--set values.global.jwtPolicy=first-party-jwt` к установке Istio).
- Сетевая связность: VM → istiod:15012 и VM → east-west gateway.

---

## Практические сценарии

### Сценарий 1: Подготовка Control Plane для VM

Убедитесь, что istiod доступен для VM (XDS — порт 15012, readiness — порт 15014) и в неймспейсе создан ServiceAccount:

```bash
# 1. Проверка портов istiod (15012 = XDS для sidecar VM, 15014 = healthz/monitoring)
kubectl get svc istiod -n istio-system -o jsonpath='{.spec.ports[*]}'
# → 15012 15012 TCP 15014 15014 TCP

# 2. Namespace для VM и ServiceAccount (метка istio-injection не нужна —
#    sidecar на VM управляется systemd, а не инъекцией в поды)
kubectl create namespace vm-services
cat <<EOF | kubectl apply -f -
apiVersion: v1
kind: ServiceAccount
metadata:
  name: vm-app-sa
  namespace: vm-services
EOF
# → serviceaccount/vm-app-sa created
```

### Сценарий 2: Создание WorkloadGroup и ServiceEntry

```yaml
# WorkloadGroup — шаблон для группы VM
apiVersion: networking.istio.io/v1
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
    network: vm-network
  probe:
    httpGet:
      path: /health
      port: 8080
    initialDelaySeconds: 5
    periodSeconds: 10
    timeoutSeconds: 3
    failureThreshold: 3
---
# ServiceEntry — подключение VM-сервиса к mesh (выбор эндпоинтов по меткам auto-регистрируемых WorkloadEntry)
apiVersion: networking.istio.io/v1
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
  resolution: DNS
  workloadSelector:
    labels:
      app: legacy-db
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

### Сценарий 3: Установка и регистрация sidecar на VM

Интеграция VM состоит из двух стадий: (1) на **управленческой машине** (с `istioctl` и `kubectl`) генерируются конфигурация и сертификаты, (2) на **VM** устанавливается пакет `istio-sidecar` и запускается systemd-юнит `istio`.

**На управленческой машине:**

```bash
# 1. Установите istioctl (1.31.2) на машину с доступом к кластеру
curl -L https://istio.io/downloadIstio | ISTIO_VERSION=1.31.2 sh -
cd istio-1.31.2
export PATH=$PWD/bin:$PATH

# 2. WorkloadGroup из Сценария 2 сохраняем в workloadgroup.yaml и применяем
#    в кластере (он служит шаблоном для автоматических WorkloadEntry),
#    затем генерируем артефакты для VM: cluster.env, istio-token, mesh.yaml,
#    root-cert.pem, hosts
kubectl apply -f workloadgroup.yaml -n vm-services
WORKDIR="${HOME}/vmintegration"
mkdir -p "${WORKDIR}"
istioctl x workload entry configure -f workloadgroup.yaml \
  -o "${WORKDIR}" \
  --clusterID cluster1 \
  --autoregister
# (файлы: cluster.env, istio-token, mesh.yaml, root-cert.pem, hosts)

# 3. Безопасно пересыпите ${WORKDIR} на VM (scp/sftp)
```

**На VM (Ubuntu/Debian):**

```bash
# 1. Пакет istio-sidecar ставится прямо на VM (istioctl НЕ нужен на VM)
curl -LO https://blob.istio.io/istio-release/releases/1.31.2/deb/istio-sidecar.deb
sudo dpkg -i istio-sidecar.deb
# (RHEL/CentOS: curl -LO https://blob.istio.io/istio-release/releases/1.31.2/rpm/istio-sidecar.rpm && sudo rpm -i istio-sidecar.rpm)

# 2. Разместите артефакты по путям, ожидаемым istio-agent:
sudo mkdir -p /etc/certs /var/run/secrets/tokens /var/lib/istio/envoy \
             /etc/istio/proxy /etc/istio/config
sudo cp root-cert.pem /etc/certs/root-cert.pem
sudo cp istio-token  /var/run/secrets/tokens/istio-token
sudo cp cluster.env  /var/lib/istio/envoy/cluster.env
sudo cp mesh.yaml    /etc/istio/config/mesh
sudo sh -c 'cat hosts >> /etc/hosts'

# 3. Передайте права пользователю istio-proxy (владелец процесса Envoy)
sudo chown -R istio-proxy /var/lib/istio /etc/certs /etc/istio/proxy \
                          /etc/istio/config /var/run/secrets

# 4. Запустите sidecar (systemd-юнит именуется istio, а не istio-proxy)
sudo systemctl start istio

# 5. Статус юнита и логи
sudo systemctl status istio
# → active (running)
sudo journalctl -u istio -n 50 --no-pager
# → ... sds resource:default pushed key/cert pair to proxy ...

# 6. Проверка: sidecar получил сертификаты. SPIFFE ID хранится в SAN (URI),
#    а не в subject CN:
openssl x509 -in /etc/certs/cert-chain.pem -noout -ext subjectAltName
# → subjectAltName = URI:spiffe://cluster.local/ns/vm-services/sa/vm-app-sa
```

### Сценарий 4: Автоматическая регистрация VM

При использовании `WorkloadGroup` с auto-registration VM автоматически регистрируется при старте sidecar'а:

```bash
# 1. Убедитесь, что WorkloadGroup создан
kubectl get workloadgroup legacy-db-group -n vm-services -o yaml

# 2. На VM: при старте sidecar'а WorkloadEntry создаётся автоматически
sudo systemctl start istio

# 3. Проверьте на Control Plane
kubectl get workloadentry -n vm-services
# → NAME                  AGE
# → legacy-db-group-10.0.1.50   30s

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
# Из Kubernetes-пода — запрос к VM-сервису
kubectl exec -it deploy/api-server -n prod -- curl -s http://legacy-db.vm-services.svc.cluster.local:5432/health
# → 200 OK (или аналогичный ответ health-check'а)

# Проверка mTLS: curl -v выводит subject/issuer сертификата VM-сайдкара.
# Subject CN = trust domain; SPIFFE-ID (spiffe://...) хранится в SAN сертификата:
kubectl exec -it deploy/api-server -n prod -- curl -v http://legacy-db.vm-services.svc.cluster.local:5432/health 2>&1 | grep -i "subject\|issuer"
# → subject: CN=cluster.local
# → issuer: CN=cluster.local
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
# Разрешить обращение к VM только из определенных неймспейсов
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
| **VM не регистрируется в mesh** | Sidecar не может достучаться до istiod (XDS 15012), либо istiod не готов | Проверьте сетевую связность на 15012; проверьте готовность istiod: `curl -s http://istiod.istio-system.svc.cluster.local:15014/healthz/ready` (\`=200 OK\`). На VM проверьте готовность прокси: `curl -s -I localhost:15021/healthz/ready`. Проверьте DNS на VM. |
| **Сертификат не выпущен** | ServiceAccount не существует или RBAC запрещает доступ | Проверьте: `kubectl get sa vm-app-sa -n vm-services`. Убедитесь, что istiod имеет права на создание сертификатов. |
| **VM не видна в Kubernetes Endpoints** | WorkloadEntry не создан или labels не совпадают | Проверьте `kubectl get workloadentry -n vm-services`. Убедитесь, что labels в WorkloadEntry совпадают с `workloadSelector` в ServiceEntry. |
| **mTLS handshake failure** | У VM и Kubernetes-подов разные trust domains | Убедитесь, что VM использует тот же trustDomain (`cluster.local`). Проверьте корневой сертификат на VM: `openssl x509 -in /etc/certs/root-cert.pem -noout -subject`. |
| **Трафик не маршрутизируется на VM** | ServiceEntry не включает эндпоинт VM | Проверьте `istioctl proxy-config clusters deploy/<pod> -n <ns> | grep <vm-service>`. Убедитесь, что `resolution` и `workloadSelector`/`endpoints` настроены. |
| **VM sidecar падает при старте** | Неверный путь к сертификатам или конфигурации | Проверьте логи: `journalctl -u istio` (или `/var/log/istio/istio.log`). Убедитесь, что файлы конфигурации скопированы в правильные директории (`/etc/istio/config/mesh`, `/var/lib/istio/envoy/cluster.env`, `/etc/certs/root-cert.pem`). |

---

## Лучшие практики эксплуатации

1. **Одна trust domain:** используйте единый trust domain (`cluster.local`) для всего mesh, включая VM. Это обеспечивает взаимную аутентификацию без дополнительной настройки.
2. **ServiceAccount per VM:** создайте отдельный ServiceAccount для каждой группы VM. Это позволяет настраивать гранулярные политики безопасности.
3. **Автоматическая регистрация:** используйте `WorkloadGroup` с auto-registration для динамических групп VM. Ручная регистрация через `WorkloadEntry` подходит для статических серверов.
4. **Health-check:** настройте `probe` в `WorkloadGroup` для автоматической дерегистрации unhealthy VM. Это предотвращает направление трафика на неработающие экземпляры.
5. **NetworkPolicy:** настройте NetworkPolicy на VM для ограничения доступа только к istiod и необходимым сервисам.
6. **Мониторинг:** добавьте VM в ServiceMonitor для Prometheus. Метрики Envoy на VM собираются аналогично Kubernetes-подам.
7. **Безопасность:** не храните сертификаты на VM в открытом виде. Используйте temporary credentials или hardware security modules (HSM) для production.
8. **Миграция:** при миграции VM в Kubernetes используйте canary-подход: сначала запустите новую версию в Kubernetes, затем переключите трафик через параметр `weight` в `VirtualService`/`DestinationRule`.

## Очистка и откат

Чтобы удалить VM из mesh (devops/sysadmin очистка окружения):

**На VM:**

```bash
sudo systemctl stop istio
sudo systemctl disable istio
# удалить пакет istio-sidecar
sudo dpkg -r istio-sidecar        # Debian/Ubuntu
# sudo rpm -e istio-sidecar        # RHEL/CentOS
# при ручных установках — удалить артефакты
sudo rm -rf /etc/certs /etc/istio /var/lib/istio /var/run/secrets/tokens /var/log/istio
```

**В кластере (на управленческой машине):**

```bash
# удалить ресурсы mesh, связанные с VM
kubectl delete serviceentry legacy-db -n vm-services
kubectl delete workloadgroup legacy-db-group -n vm-services
kubectl delete workloadentry -n vm-services -l app=legacy-db
# при необходимости — удалить ServiceAccount
kubectl delete serviceaccount vm-app-sa -n vm-services
```

Сами CRD `WorkloadEntry`/`WorkloadGroup`/`ServiceEntry` удалять не нужно — они управляются пакетом `istio-base` и подходят для переиспользования.

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
- [DNS для VM](./istio-dns.md) — DNS proxying и разрешение имён для VM-роутов
- [Мультикластерный mesh expansion](./istio-multicluster.md) — mesh expansion с VM/bare-metal

Документация: [Virtual Machine Installation](https://istio.io/latest/docs/setup/install/virtual-machine/), [Virtual Machine Architecture](https://istio.io/latest/docs/ops/deployment/vm-architecture/), [Debugging Virtual Machines](https://istio.io/latest/docs/ops/diagnostic-tools/virtual-machines/), [WorkloadEntry Reference](https://istio.io/latest/docs/reference/config/networking/workload-entry/), [WorkloadGroup Reference](https://istio.io/latest/docs/reference/config/networking/workload-group/).
