# Использование Cert-manager с Ingress

Самый распространенный способ использования `cert-manager` — это автоматическое получение сертификатов для Ingress-ресурсов с помощью аннотаций.

Просто добавьте аннотацию в ваш Ingress-манифест, и `cert-manager` сделает все остальное.

```yaml
apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: my-ingress
  annotations:
    # Указываем, какой ClusterIssuer использовать
    cert-manager.io/cluster-issuer: "letsencrypt-prod"
spec:
  ingressClassName: nginx
  tls:
  - hosts:
    - my-domain.com
    secretName: my-domain-tls # cert-manager создаст и заполнит этот секрет
  rules:
  - host: my-domain.com
    http:
      paths:
      - path: /
        pathType: Prefix
        backend:
          service:
            name: my-service
            port:
              number: 80
```

> **Примечание об устаревшей аннотации:** Ранее использовалась аннотация `kubernetes.io/tls-acme: "true"`. Она считается устаревшей и ее следует избегать. Вместо нее всегда используйте `cert-manager.io/cluster-issuer` или `cert-manager.io/issuer`.

---

## Прямое создание ресурса Certificate

Второй способ — создать ресурс `Certificate` напрямую. Этот подход обеспечивает больший контроль и полезен, когда сертификат не привязан к Ingress (например, для mTLS между сервисами).

В этом ресурсе вы описываете желаемый сертификат, указываете доменные имена и ссылаетесь на `Issuer` или `ClusterIssuer`.

```yaml
apiVersion: cert-manager.io/v1
kind: Certificate
metadata:
  name: my-domain-com
  namespace: default
spec:
  # Имя секрета, в который будет сохранен сертификат
  secretName: my-domain-tls
  # Длительность и период обновления
  duration: 2160h # 90d
  renewBefore: 360h # 15d
  # Доменные имена
  dnsNames:
  - my-domain.com
  - www.my-domain.com
  # Ссылка на Issuer или ClusterIssuer
  issuerRef:
    name: letsencrypt-prod
    kind: ClusterIssuer
```

Cert-manager отследит этот ресурс и автоматически создаст/обновит секрет `my-domain-tls` с валидным сертификатом.

---

*Основа: [](../cert_manager.md)*
