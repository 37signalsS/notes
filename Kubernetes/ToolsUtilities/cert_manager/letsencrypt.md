# Конфигурация для публичных CA (Let's Encrypt)

Для получения публично доверенных сертификатов настраивается `ClusterIssuer` для Let's Encrypt.

```yaml
# clusterissuer-letsencrypt.yaml
apiVersion: cert-manager.io/v1
kind: ClusterIssuer
metadata:
  name: letsencrypt-prod
spec:
  acme:
    email: your-email@example.com
    server: https://acme-v02.api.letsencrypt.org/directory
    privateKeySecretRef:
      name: letsencrypt-prod-private-key
    solvers:
    - http01:
        ingress:
          class: nginx # Укажите ваш Ingress-класс
```

---

*Основа: [](../cert_manager.md)*
