# Api Access Forbidden: Методы аутентификации

## Методы аутентификации

| Метод | Описание | Когда используется |
|-------|----------|-------------------|
| **ServiceAccount Token** | JWT токен в `/var/run/secrets/kubernetes.io/serviceaccount/token` | Pod → API |
| **Client Certificate** | X.509 сертификат | kubectl, внешние клиенты |
| **Bearer Token** | Статический токен | Интеграции |
| **Webhook** | Внешний сервис аутентификации | Кастомные сценарии |

### 401 Unauthorized — проблемы с токеном

**Сообщение:**

```
Unauthorized: Invalid token
The token provided has expired
```

**Причины:**

- Истек срок действия токена ServiceAccount
- Token был отозван
- Неверный kubeconfig

**Решение:**

```bash
# Пересоздание token для ServiceAccount
kubectl delete secret <sa-token-secret>
# Kubernetes автоматически создаст новый

# Или явное создание token (Kubernetes 1.24+)
kubectl create token <sa-name> -n <namespace>

# Обновление kubeconfig
kubectl config set-credentials <user> --token=<new-token>
```

> **Важно:** С Kubernetes 1.24+ токены ServiceAccount не сохраняются в Secrets по умолчанию. Используйте `kubectl create token`.
