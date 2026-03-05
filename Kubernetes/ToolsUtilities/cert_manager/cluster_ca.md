# Использование CA кластера для внутренних сертификатов

## Определения

**CA кластера** — корневой центр сертификации Kubernetes, который подписывает сертификаты всех компонентов кластера (kubelet, kube-apiserver, etcd, webhook).

**Сценарий использования:** Внутренние сервисы кластера (Ingress, mTLS), которым нужно доверять со стороны компонентов Kubernetes.

---

## Основные концепции

### Отличия от приватного CA

| Аспект | CA кластера | Приватный CA |
| :--- | :--- | :--- |
| **Источник доверия** | `/etc/kubernetes/pki/ca.crt` | Self-signed в кластере |
| **Доступ** | Требуется доступ к master-узлам | Только kubectl API |
| **Доверие** | Все компоненты кластера | Только явно настроенные сервисы |
| **Жизненный цикл** | Зависит от кластера | Независимый |
| **Сложность** | Средняя | Низкая |

### Архитектура

```
/etc/kubernetes/pki/ca.crt
         ↓
Secret (tls) в cert-manager
         ↓
CA Issuer
         ↓
Сертификаты сервисов
```

---

## Практические сценарии

### Сценарий 1: Базовый CA кластера

**Цель:** Выпустить сертификат для внутреннего Ingress, подписанный CA кластера.

#### Шаг 1: Создание Secret с CA кластера

> **Требование:** Доступ к master-узлу и файлам в `/etc/kubernetes/pki/`.

```bash
kubectl create secret tls kubernetes-ca-secret \
  --cert=/etc/kubernetes/pki/ca.crt \
  --key=/etc/kubernetes/pki/ca.key \
  -n cert-manager
```

**Важно:**
- Операция требует прав администратора кластера
- Ключ CA (`ca.key`) должен храниться в секрете
- Рекомендуется ограничить доступ к Secret через RBAC

#### Шаг 2: Создание Issuer на основе CA

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

**Issuer vs ClusterIssuer:**
- `Issuer` — доступен только в том же namespace (cert-manager)
- `ClusterIssuer` — доступен из всех namespace (рекомендуется для общих сервисов)

#### Шаг 3: Запрос сертификата

```yaml
apiVersion: cert-manager.io/v1
kind: Certificate
metadata:
  name: internal-services-tls
  namespace: monitoring
spec:
  secretName: internal-services-secret
  duration: 2160h  # 90 дней
  renewBefore: 360h  # 15 дней
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
  duration: 8760h
  renewBefore: 720h
  issuerRef:
    name: kubernetes-cluster-ca
    kind: ClusterIssuer
  dnsNames:
    - my-app.production.svc.cluster.local
```

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

**Использование в Pod:**

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

## Дополнительная информация

### Проверка доверия

```bash
# Получить CA кластера из Secret
kubectl get secret kubernetes-ca-secret -n cert-manager -o jsonpath='{.data.ca\.crt}' | base64 -d > cluster-ca.crt

# Проверить сертификат сервиса
openssl verify -CAfile cluster-ca.crt <(kubectl get secret internal-services-secret -n monitoring -o jsonpath='{.data.tls\.crt}' | base64 -d)
```

### Безопасность

| Риск | Митигация |
| :--- | :--- |
| Утечка ключа CA | Ограничить RBAC на Secret, аудит доступа |
| Компрометация сервиса | Использовать отдельные Certificate для каждого сервиса |
| Отсутствие ротации | Настроить `duration` и `renewBefore` |

### Надёжность информации

| Аспект | Оценка | Обоснование |
| :--- | :--- | :--- |
| Доступ к CA кластера | **10** | Стандартная практика Kubernetes |
| mTLS сценарии | **9** | Подтверждено документацией cert-manager |
| RBAC для Secret | **10** | Стандарт Kubernetes |

### Частые ошибки

| Ошибка | Причина | Решение |
| :--- | :--- | :--- |
| `Permission denied` к `/etc/kubernetes/pki/` | Недостаточно прав | Выполнять от имени пользователя с доступом к master |
| Certificate `Pending` | Secret не найден | Проверить namespace Secret и Issuer |
| Ошибка доверия в приложении | CA не добавлен в trust store | Импортировать `ca.crt` из Secret в приложение |

---

*SSoT для CA кластера. Последняя проверка актуальности: март 2026.*
