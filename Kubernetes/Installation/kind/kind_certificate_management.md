# kind — управление сертификатами

## Определения

**PKI (Public Key Infrastructure)** — инфраструктура открытых ключей, обеспечивающая выпуск, управление и проверку цифровых сертификатов. В Kubernetes PKI используется для аутентификации компонентов (API-сервер, kubelet, etcd, scheduler, controller-manager) и клиентов (kubectl, пользователи).

**kubeadm certs** — набор команд для управления сертификатами, созданными kubeadm: `check-expiration`, `renew`, `renew-all`. Автоматизирует процесс ротации сертификатов Control Plane.

**Service Account Token** — JWT-токен, автоматически монтируемый в каждый под для аутентификации при взаимодействии с API-сервером.

---

## Основные концепции

### Сертификаты в kind

kind автоматически создаёт все необходимые сертификаты при `kind create cluster`. Сертификаты хранятся внутри control-plane узла (Docker-контейнера):

| Сертификат | Путь в узле | Назначение |
|:---|:---|:---|
| **ca.crt / ca.key** | `/etc/kubernetes/pki/` | Корневой CA кластера |
| **apiserver.crt / apiserver.key** | `/etc/kubernetes/pki/` | TLS API-сервера |
| **apiserver-kubelet-client.crt** | `/etc/kubernetes/pki/` | Клиентский сертификат API → kubelet |
| **front-proxy-ca.crt** | `/etc/kubernetes/pki/` | CA для API Aggregation |
| **front-proxy-client.crt** | `/etc/kubernetes/pki/` | Клиентский сертификат Aggregation |
| **etcd/ca.crt** | `/etc/kubernetes/pki/etcd/` | CA для etcd |
| **etcd/server.crt** | `/etc/kubernetes/pki/etcd/` | TLS сервера etcd |
| **etcd/peer.crt** | `/etc/kubernetes/pki/etcd/` | etcd peer-to-peer |
| **sa.key / sa.pub** | `/etc/kubernetes/pki/` | Service Account ключи (не x509!) |

### Особенности сертификатов в kind

- kind использует ** самоподписанный CA** (self-signed CA), созданный при инициализации кластера
- Сертификаты действительны **1 год** (по умолчанию для kubeadm)
- kind не предоставляет `kubeadm certs renew` — для обновления сертификатов нужно пересоздавать кластер
- Сертификаты находятся **внутри контейнера**, поэтому для работы с ними нужно `docker exec`

### Когда нужны операции с сертификатами в kind

| Сценарий | Действие | Зачем |
|:---|:---|:---|
| Проверка срока действия | `openssl x509 -enddate` | Убедиться, что сертификаты не истекли |
| Просмотр Subject/Issuer | `openssl x509 -subject -issuer` | Диагностика проблем аутентификации |
| Генерация клиентского сертификата | `openssl` | Создание сертификата для пользователя |
| Проверка TLS-соединения | `curl -v` | Диагностика ошибок TLS |

---

## Практические сценарии

### Создание кластера для тестирования

```bash
kind create cluster --name cert-test
```

### Сценарий 1: Просмотр информации о сертификатах

```bash
# Определение имени control-plane контейнера
NODE=$(docker ps --filter "label=io.x-k8s.kind.cluster=cert-test" --format "{{.Names}}" | grep control-plane)

# Просмотр CA-сертификата
docker exec $NODE cat /etc/kubernetes/pki/ca.crt | openssl x509 -text -noout | head -20
# → Certificate:
# →     Data:
# →         Version: 3 (0x2)
# →         Serial Number: ...
# →         Signature Algorithm: sha256WithRSAEncryption
# →         Issuer: CN = kubernetes

# Просмотр срока действия
docker exec $NODE openssl x509 -in /etc/kubernetes/pki/apiserver.crt -noout -dates
# → notBefore=Jan  1 00:00:00 2026 GMT
# → notAfter=Jan  1 00:00:00 2027 GMT

# Просмотр Subject и SAN (Subject Alternative Names)
docker exec $NODE openssl x509 -in /etc/kubernetes/pki/apiserver.crt -noout -subject -ext subjectAltName
# → subject=CN = kube-apiserver
# → X509v3 Subject Alternative Name:
# →     DNS:kubernetes, DNS:kubernetes.default, DNS:kubernetes.default.svc
# →     DNS:localhost, IP Address:10.96.0.1, IP Address:172.18.0.2

# Просмотр всех сертификатов сразу
docker exec $NODE ls -la /etc/kubernetes/pki/
docker exec $NODE ls -la /etc/kubernetes/pki/etcd/
```

### Сценарий 2: Проверка TLS-соединения с API-сервером

```bash
# Проверка: kubectl подключается корректно
kubectl cluster-info --context kind-cert-test
# → Kubernetes control plane is running at https://127.0.0.1:xxxxx

# Проверка TLS через curl
APISERVER=$(kubectl config view -o jsonpath='{.clusters[0].cluster.server}')
CACERT=$(mktemp)
kubectl config view --raw -o jsonpath='{.clusters[0].cluster.certificate-authority-data}' | base64 -d > $CACERT

curl -s --cacert $CACERT $APISERVER/version
# → {"major":"1","minor":"37","gitVersion":"v1.37.0",...}

# Проверка без CA (должна быть ошибка TLS)
curl -s $APISERVER/version
# → curl: (60) SSL certificate problem: unable to get local issuer certificate

# Проверка с --insecure (для отладки)
curl -sk $APISERVER/version
# → {"major":"1","minor":"37",...}  ← работает, но небезопасно!
```

### Сценарий 3: Создание клиентского сертификата для пользователя

```bash
# 1. Генерация приватного ключа
openssl genrsa -out user-dev.key 2048

# 2. Создание CSR (Certificate Signing Request)
openssl req -new -key user-dev.key -out user-dev.csr \
  -subj "/CN=dev-user/O=developers"

# 3. Подписание CSR CA-сертификатом кластера
# (В kind нужно выполнить внутри control-plane узла)
docker exec $NODE sh -c '
  openssl x509 -req -in /dev/stdin \
    -CA /etc/kubernetes/pki/ca.crt \
    -CAkey /etc/kubernetes/pki/ca.key \
    -CAcreateserial \
    -out /tmp/user-dev.crt \
    -days 30 \
    -sha256
' < user-dev.csr

# 4. Копирование сертификата на хост
docker cp $NODE:/tmp/user-dev.crt ./user-dev.crt

# 5. Создание kubeconfig для пользователя
kubectl config set-cluster kind-cert-test \
  --certificate-authority=$(mktemp) \
  --embed-certs=true \
  --server=$(kubectl config view -o jsonpath='{.clusters[0].cluster.server}')

# Получение CA из кластера
kubectl config view --raw -o jsonpath='{.clusters[0].cluster.certificate-authority-data}' | base64 -d > ca.crt

# Создание kubeconfig
kubectl config set-cluster cert-test \
  --server=$(kubectl config view -o jsonpath='{.clusters[0].cluster.server}') \
  --certificate-authority=ca.crt \
  --embed-certs=true \
  --kubeconfig=user-dev.kubeconfig

kubectl config set-credentials dev-user \
  --client-certificate=user-dev.crt \
  --client-key=user-dev.key \
  --embed-certs=true \
  --kubeconfig=user-dev.kubeconfig

kubectl config set-context dev-user \
  --cluster=cert-test \
  --user=dev-user \
  --namespace=default \
  --kubeconfig=user-dev.kubeconfig

kubectl config use-context dev-user --kubeconfig=user-dev.kubeconfig

# 6. Проверка: пользователь может читать поды
kubectl --kubeconfig=user-dev.kubeconfig get pods
# → NAME    READY   STATUS    RESTARTS   AGE

# 7. Проверка: пользователь НЕ может удалять поды
kubectl --kubeconfig=user-dev.kubeconfig delete pod test-pod
# → Error: pods "test-pod" is forbidden: User "dev-user" cannot delete resource "pods"
```

### Сценарий 4: Диагностика ошибок сертификатов

**Типичные ошибки:**

| Ошибка | Причина | Решение |
|:---|:---|:---|
| `x509: certificate has expired` | Сертификат истёк | Пересоздать кластер kind (kind не поддерживает `certs renew`) |
| `x509: certificate signed by unknown authority` | CA не доверяет сертификату | Убедиться, что используется правильный CA в kubeconfig |
| `tls: bad certificate` | Клиентский сертификат невалиден | Проверить CN/O в сертификате |
| `unable to get local issuer certificate` | CA-сертификат не указан | Добавить `--certificate-authority` в kubeconfig |

**Команды диагностики:**

```bash
# Проверка текущего контекста
kubectl config current-context

# Проверка сервера и CA
kubectl config view --minify

# Проверка: какой сертификат используется kubectl
kubectl -v=9 get pods 2>&1 | grep -i "certificate\|tls\|ssl"

# Проверка сертификата API-сервера извне
openssl s_client -connect 127.0.0.1:$(kubectl config view -o jsonpath='{.clusters[0].cluster.server}' | sed 's|https://127.0.0.1:||') </dev/null 2>/dev/null | openssl x509 -noout -dates

# Проверка: SAN API-сервера
docker exec $NODE openssl x509 -in /etc/kubernetes/pki/apiserver.crt -noout -ext subjectAltName
```

### Сценарий 5: Service Account токены в kind

```bash
# Просмотр токена ServiceAccount
kubectl create serviceaccount test-sa
kubectl create token test-sa --duration=1h
# → eyJhbGciOiJSUzI1NiIsImtpZCI6Ij...

# Проверка: токен работает
TOKEN=$(kubectl create token test-sa --duration=1h)
APISERVER=$(kubectl config view -o jsonpath='{.clusters[0].cluster.server}')

curl -s -H "Authorization: Bearer $TOKEN" \
  -k $APISERVER/api/v1/namespaces/default/pods
# → {"kind":"PodList","items":[...]}

# Просмотр JWT-токена (декодирование payload)
echo $TOKEN | cut -d. -f2 | base64 -d 2>/dev/null | jq .
# → {"aud":["https://kubernetes.default.svc"],"exp":...,"iat":...,"kubernetes.io":...}
```

---

## Дополнительная информация

### Ссылки

- [kind — определения и концепции](./kind_concepts.md) — архитектура и внутреннее устройство узлов
- [Certificate Management](../../Operations/certificate_management.md) — полная теория управления сертификатами
- [SSL Expiration Prevention](../../Operations/ssl_expiration_prevention.md) — предотвращение истечения сертификатов
- [Certificate Auth](../../Security/rbac/certificate_auth.md) — аутентификация через сертификаты
- [Официальная документация PKI](https://kubernetes.io/docs/setup/best-practices/certificates/)
