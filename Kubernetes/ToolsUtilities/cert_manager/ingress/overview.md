# Интеграция Cert-manager с Ingress: Обзор

## Определения

**Ingress-аннотации cert-manager** — механизм автоматического создания и обновления сертификатов для Ingress-ресурсов через добавление специальных аннотаций.

**Преимущества:**

- Минимальная конфигурация
- Автоматическое продление
- Интеграция с любым Ingress Controller (nginx, Traefik, HAProxy)

---

## Основные концепции

### Поток работы

```
Ingress с аннотацией
       ↓
cert-manager обнаруживает аннотацию
       ↓
Создаётся Certificate ресурс
       ↓
Выполняется ACME-проверка (HTTP-01/DNS-01)
       ↓
Secret создаётся/обновляется
       ↓
Ingress использует Secret
```

### Аннотации cert-manager

| Аннотация | Описание | Пример |
| :--- | :--- | :--- |
| `cert-manager.io/issuer` | Issuer в том же namespace | `my-issuer` |
| `cert-manager.io/cluster-issuer` | ClusterIssuer (общекластерный) | `letsencrypt-prod` |
| `cert-manager.io/issue-temporary-certificate` | Временный сертификат до ACME | `true` |
| `cert-manager.io/acme-challenge-type` | Принудительный solver | `http01`, `dns01` |
| `cert-manager.io/common-name` | Переопределение CN | `example.com` |
| `cert-manager.io/duration` | Срок действия | `2160h` |
| `cert-manager.io/renew-before` | Время до продления | `360h` |
| `cert-manager.io/private-key-size` | Размер ключа | `4096` |
| `cert-manager.io/private-key-algorithm` | Алгоритм | `RSA`, `ECDSA` |

---

## Дополнительная информация

### Связанные документы

- **[Let's Encrypt](./letsencrypt.md)** — публичные сертификаты через ACME
- **[Private CA](./private_ca.md)** — собственные центры сертификации
- **[Administration](./administration.md)** — управление и диагностика cert-manager

### Диагностика

```bash
# Статус Certificate
kubectl get certificate -n default

# Детали Certificate
kubectl describe certificate myapp-tls -n default

# Связанные Order и Challenge
kubectl get order -n default
kubectl get challenge -n default

# Логи cert-manager
kubectl logs -n cert-manager -l app=cert-manager --tail=100
```

### Устаревшие аннотации

| Устаревшая | Современная замена |
| :--- | :--- |
| `kubernetes.io/tls-acme: "true"` | `cert-manager.io/cluster-issuer` |
| `certmanager.k8s.io/issuer` | `cert-manager.io/issuer` |

> **Важно:** Используйте только аннотации с префиксом `cert-manager.io`.
