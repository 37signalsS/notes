# Использование CA кластера для выпуска внутренних сертификатов

Для внутренних сервисов, которые не доступны извне, нет необходимости получать публично доверенные сертификаты (например, от Let's Encrypt). Вместо этого можно использовать корневой CA самого кластера Kubernetes для подписи сертификатов. Это обеспечивает шифрование трафика внутри кластера, которому доверяют все его компоненты.

**Задача:** Выпустить TLS-сертификат для внутреннего Ingress-ресурса (например, `netdata.k8s.local`), подписанный корневым CA кластера.

## Шаг 1: Создание `Secret` с корневым CA кластера

Сначала необходимо сделать сертификат и ключ корневого CA Kubernetes доступными для `cert-manager`. Для этого создается `Secret` типа `tls` в том же `namespace`, где будет работать `cert-manager`.

> **Внимание:** Эта операция требует доступа к master-узлу и файлам в `/etc/kubernetes/pki/`.

```bash
kubectl create secret tls kubernetes-ca-secret \
  --cert=/etc/kubernetes/pki/ca.crt \
  --key=/etc/kubernetes/pki/ca.key \
  -n cert-manager # или другой namespace, где работает cert-manager
```

## Шаг 2: Создание `Issuer` на основе секрета

Теперь создаем `Issuer` (или `ClusterIssuer`), который будет использовать этот секрет для подписи сертификатов.

```yaml
# cluster-ca-issuer.yaml
apiVersion: cert-manager.io/v1
kind: Issuer
metadata:
  name: kubernetes-ca-issuer
  namespace: cert-manager
spec:
  ca:
    secretName: kubernetes-ca-secret # Ссылка на секрет с CA кластера
```

*   `kind: Issuer`: Если `Issuer` и `Secret` находятся в одном namespace.
*   `kind: ClusterIssuer`: Если вы хотите, чтобы `Issuer` был доступен из любого namespace (в этом случае `Secret` все равно должен быть в `cert-manager` namespace).

## Шаг 3: Запрос сертификата через ресурс `Certificate`

Создаем ресурс `Certificate`, который запрашивает у нашего `Issuer`'а сертификат для нужных доменных имен.

```yaml
# internal-certificate.yaml
apiVersion: cert-manager.io/v1
kind: Certificate
metadata:
  name: internal-services-tls
  namespace: monitoring # Namespace, где будет использоваться сертификат
spec:
  secretName: internal-services-secret # Имя секрета, куда будет сохранен сертификат
  duration: 2160h # 90d
  renewBefore: 360h # 15d
  issuerRef:
    name: kubernetes-ca-issuer
    kind: Issuer
    group: cert-manager.io
  dnsNames:
    - netdata.k8s.local
    - grafana.k8s.local
    - prometheus.k8s.local
```

После применения этого манифеста `cert-manager` создаст в `namespace: monitoring` секрет `internal-services-secret` с TLS-сертификатом, подписанным CA кластера.

## Шаг 4: Использование сертификата в `Ingress`

Наконец, используем созданный секрет в `Ingress`-ресурсе.

```yaml
# netdata-ingress.yaml
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: netdata-ingress
  namespace: monitoring
  annotations:
    # Аннотация, чтобы cert-manager управлял этим Ingress
    cert-manager.io/issuer: "kubernetes-ca-issuer" 
spec:
  ingressClassName: system-ingress # Указываем наш внутренний Ingress-контроллер
  tls:
  - hosts:
    - netdata.k8s.local
    secretName: internal-services-secret # Ссылка на наш секрет
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

Этот подход позволяет централизованно управлять TLS-сертификатами для всех внутренних сервисов, обеспечивая безопасное взаимодействие внутри кластера.

---

*Основа: [](../cert_manager.md)*
