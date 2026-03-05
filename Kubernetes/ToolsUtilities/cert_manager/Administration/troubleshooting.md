# Диагностика и troubleshooting Cert-manager

## Определения

**Troubleshooting cert-manager** — процесс выявления и устранения проблем при выпуске и продлении сертификатов.

> **Навигация:** [Главная Administration](./index.md) | [Операции](./operations.md)

---

## Practical Scenarios

### Проверка состояния ресурсов

```bash
# Статус всех Certificate
kubectl get certificates --all-namespaces

# Детали конкретного Certificate
kubectl describe certificate <name> -n <namespace>

# Статус Order (ACME)
kubectl get orders --all-namespaces

# Статус Challenge (ACME проверки)
kubectl get challenges --all-namespaces

# Проверка Issuer/ClusterIssuer
kubectl get issuers,clusterissuers --all-namespaces
kubectl describe issuer <name> -n <namespace>
```

---

### Логи компонентов

```bash
# Основной контроллер
kubectl logs -n cert-manager -l app=cert-manager --tail=100

# Webhook
kubectl logs -n cert-manager -l app=webhook --tail=100

# CA Injector
kubectl logs -n cert-manager -l app=cainjector --tail=100

# Поиск ошибок ACME
kubectl logs -n cert-manager -l app=cert-manager | grep -i "acme\|error"
```

---

### Частые проблемы и решения

#### Certificate в статусе Pending

**Причина:** ACME-проверка не пройдена.

```bash
# Проверить детали
kubectl describe certificate <name> -n <namespace>

# Проверить Challenge
kubectl describe challenge <name> -n <namespace>

# Проверить Order
kubectl describe order <name> -n <namespace>
```

**Возможные причины:**

| Проблема | Диагностика | Решение |
| :--- | :--- | :--- |
| **HTTP-01 недоступен** | `curl http://<domain>/.well-known/acme-challenge/` | Проверить Ingress, firewall |
| **DNS-01 не прошёл** | Проверить TXT-запись: `dig TXT _acme-challenge.<domain>` | Проверить DNS API credentials |
| **Rate limit** | `kubectl get order -o yaml` | Использовать staging, подождать |

---

#### Secret не создаётся

**Причина:** Certificate не готов или ошибка записи Secret.

```bash
# Проверить события
kubectl get events -n <namespace> --sort-by='.lastTimestamp'

# Проверить RBAC для cert-manager
kubectl describe clusterrole cert-manager-controller-certificates
```

---

#### Webhook timeout

**Причина:** Проблемы с сетью или ресурсами webhook.

```bash
# Проверить webhook deployment
kubectl get deployment cert-manager-webhook -n cert-manager
kubectl describe deployment cert-manager-webhook -n cert-manager

# Проверить сервис
kubectl get svc cert-manager-webhook -n cert-manager
kubectl get endpoints cert-manager-webhook -n cert-manager
```

**Решение:**

```bash
# Пересоздать webhook
kubectl rollout restart deployment cert-manager-webhook -n cert-manager
```

---

#### Ошибка цепочки доверия

**Причина:** Приложение не доверяет CA.

```bash
# Получить CA из Secret
kubectl get secret <ca-secret> -n <namespace> -o jsonpath='{.data.ca\.crt}' | base64 -d > ca.crt

# Проверить сертификат
openssl verify -CAfile ca.crt <cert.crt>
```

**Решение:** Импортировать `ca.crt` в trust store приложения.

---

## Additional Information

### Связанные темы

- [Private CA](../private_ca.md) — создание собственного CA
- [LetsEncrypt](../LetsEncrypt/) — практические сценарии с Let's Encrypt
- [Installation](../install.md) — установка cert-manager
