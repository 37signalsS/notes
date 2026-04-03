# Использование CA кластера для внутренних сертификатов

## Definitions

**CA кластера** — корневой центр сертификации Kubernetes, расположенный в `/etc/kubernetes/pki/ca.crt`. Подписывает сертификаты компонентов кластера (kubelet, kube-apiserver, etcd, admission webhooks).

**Применение:** Выпуск внутренних TLS-сертификатов для Ingress, mTLS и сервисов, которым должно доверять инфраструктурное ПО кластера.

**Связанные темы:**
- Приватный CA (self-signed): [Private_CA/scenarios.md](./Private_CA/scenarios.md)
- Troubleshooting cert-manager: [Administration/troubleshooting.md](./Administration/troubleshooting.md)
- Операции приватного CA (ротация, проверка): [Private_CA/operations.md](./Private_CA/operations.md)

---

## Basic Concepts

### Отличия от приватного CA (self-signed)

| Аспект | CA кластера | Приватный CA (self-signed) |
| :--- | :--- | :--- |
| **Источник доверия** | `/etc/kubernetes/pki/ca.crt` | Self-signed Issuer в cert-manager |
| **Доступ** | Требуется доступ к control plane | Только kubectl API |
| **Доверие** | Автоматическое для компонентов кластера | Только явно настроенные сервисы |
| **Жизненный цикл** | Зависит от кластера (совпадает с kubelet) | Независимый, управляется вручную |
| **Риски** | Компрометация = полный доступ к кластеру | Изолированный риск |
| **Сложность** | Средняя (требует доступа к master) | Низкая |

### Архитектура

```
/etc/kubernetes/pki/ca.crt + ca.key
         ↓
Secret (Opaque) в namespace cert-manager
         ↓
CA Issuer / ClusterIssuer
         ↓
Сертификаты сервисов (Ingress, mTLS, API)
```

### Критичные требования безопасности

- **Хранение `ca.key`:** Ключ CA кластера даёт возможность подписывать любые сертификаты в кластере. Использовать только в защищённом хранилище (например, encrypted backup).
- **RBAC:** Ограничить доступ к Secret с ключом через `resourceNames` и аудит.
- **Изоляция:** Для production-кластеров рекомендуется отдельный приватный CA вместо использования CA кластера.

---

## Practical Scenarios

### Сценарий 1: Базовый выпуск сертификата для Ingress

**Цель:** Выпустить сертификат для внутреннего Ingress, подписанный CA кластера.

#### Шаг 1: Создание Secret с CA кластера

> **Требование:** Доступ к control plane узлу и файлам `/etc/kubernetes/pki/`.

```bash
kubectl create secret tls kubernetes-ca-secret \
  --cert=/etc/kubernetes/pki/ca.crt \
  --key=/etc/kubernetes/pki/ca.key \
  -n cert-manager
```

**Важно:**
- Операция требует прав cluster-admin
- Secret создаётся в namespace `cert-manager` (для ClusterIssuer) или в namespace Issuer
- Ограничить доступ к Secret через RBAC

#### Шаг 2: Создание Issuer

```yaml
apiVersion: cert-manager.io/v1
kind: Issuer
metadata:
  name: kubernetes-ca-issuer
  namespace: cert-manager
spec:
  ca:
    secretName: kubernetes-ca-secret
```

> **Issuer vs ClusterIssuer:** `Issuer` работает только в своём namespace. Для общекластерного доступа использовать `ClusterIssuer` — [Сценарий 2](#сценарий-2-clusterissuer-для-общекластерного-доступа).

#### Шаг 3: Запрос сертификата

```yaml
apiVersion: cert-manager.io/v1
kind: Certificate
metadata:
  name: internal-services-tls
  namespace: monitoring
spec:
  secretName: internal-services-secret
  duration: 2160h          # 90 дней
  renewBefore: 360h        # 15 дней
  issuerRef:
    name: kubernetes-ca-issuer
    kind: Issuer
    group: cert-manager.io
  dnsNames:
    - netdata.k8s.local
    - grafana.k8s.local
    - prometheus.k8s.local
```

#### Шаг 4: Использование в Ingress

```yaml
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: netdata-ingress
  namespace: monitoring
  annotations:
    cert-manager.io/issuer: "kubernetes-ca-issuer"
spec:
  ingressClassName: system-ingress
  tls:
    - hosts:
        - netdata.k8s.local
      secretName: internal-services-secret
  rules:
    - host: netdata.k8s.local
      http:
        paths:
          - path: /
            pathType: Prefix
            backend:
              service:
                name: netdata
                port:
                  name: http
```

---

### Сценарий 2: ClusterIssuer для общекластерного доступа

**Цель:** Сделать CA кластера доступным из всех namespace.

```yaml
apiVersion: cert-manager.io/v1
kind: ClusterIssuer
metadata:
  name: kubernetes-cluster-ca
spec:
  ca:
    secretName: kubernetes-ca-secret  # Secret в namespace cert-manager
```

**Использование из любого namespace:**

```yaml
apiVersion: cert-manager.io/v1
kind: Certificate
metadata:
  name: my-app-cert
  namespace: production
spec:
  secretName: my-app-tls
  duration: 8760h           # 1 год
  renewBefore: 720h         # 30 дней
  issuerRef:
    name: kubernetes-cluster-ca
    kind: ClusterIssuer
  dnsNames:
    - my-app.production.svc.cluster.local
```

> **Примечание:** Аналогичный сценарий для self-signed CA описан в [Private_CA/scenarios.md](./Private_CA/scenarios.md).

---

### Сценарий 3: mTLS между сервисами

**Цель:** Настроить взаимную TLS-аутентификацию между сервисами.

#### Сертификат сервера

```yaml
apiVersion: cert-manager.io/v1
kind: Certificate
metadata:
  name: backend-server
  namespace: production
spec:
  secretName: backend-server-tls
  issuerRef:
    name: kubernetes-cluster-ca
    kind: ClusterIssuer
  dnsNames:
    - backend.production.svc
    - backend.production.svc.cluster.local
  usages:
    - server auth
```

#### Сертификат клиента

```yaml
apiVersion: cert-manager.io/v1
kind: Certificate
metadata:
  name: backend-client
  namespace: production
spec:
  secretName: backend-client-tls
  issuerRef:
    name: kubernetes-cluster-ca
    kind: ClusterIssuer
  dnsNames:
    - frontend.production.svc
  usages:
    - client auth
```

**Монтирование в Pod:**

```yaml
apiVersion: v1
kind: Pod
metadata:
  name: backend
spec:
  containers:
    - name: backend
      image: my-backend
      volumeMounts:
        - name: tls
          mountPath: /etc/tls
          readOnly: true
  volumes:
    - name: tls
      secret:
        secretName: backend-server-tls
```

---

## Additional Information

### Проверка доверия

```bash
# Получить CA кластера из Secret
kubectl get secret kubernetes-ca-secret -n cert-manager \
  -o jsonpath='{.data.ca\.crt}' | base64 -d > cluster-ca.crt

# Проверить сертификат сервиса
openssl verify -CAfile cluster-ca.crt \
  <(kubectl get secret internal-services-secret -n monitoring \
    -o jsonpath='{.data.tls\.crt}' | base64 -d)
```

> Детальная проверка цепочки доверия и кодировки ключей — в [Private_CA/operations.md](./Private_CA/operations.md).

### Безопасность

| Риск | Митигация |
| :--- | :--- |
| Утечка `ca.key` | Ограничить RBAC на Secret, аудит доступа, encrypted backup |
| Компрометация сервиса | Отдельный Certificate для каждого сервиса |
| Отсутствие ротации | Настроить `duration` и `renewBefore`, мониторинг истечения |

### Частые ошибки

| Ошибка | Причина | Решение |
| :--- | :--- | :--- |
| `Permission denied` к `/etc/kubernetes/pki/` | Недостаточно прав | Выполнять на control plane с правами root/cluster-admin |
| Certificate `Pending` | Secret не найден или Issuer недоступен | Проверить namespace Secret и статус Issuer (`kubectl describe issuer`) |
| Ошибка доверия в приложении | CA не добавлен в trust store приложения | Импортировать `ca.crt` из Secret в приложение |
| Конфликт с kube-apiserver cert | CA кластера истёк при kubeadm upgrade | Выполнить ротацию CA кластера (документация kubeadm) |

### Надёжность информации

| Аспект | Оценка | Обоснование |
| :--- | :--- | :--- |
| Доступ к CA кластера | **10** | Стандартная практика Kubernetes (kubeadm) |
| mTLS сценарии | **9** | Подтверждено документацией cert-manager |
| RBAC для Secret | **10** | Стандарт Kubernetes RBAC |
