# Api Access Forbidden: методы аутентификации и 401 Unauthorized

## Определения

**401 Unauthorized** — состояние, при котором Kubernetes не смог аутентифицировать запрос. Проблема возникает на этапе проверки личности (аутентификации), до передачи запроса на уровень авторизации (**RBAC**).

> Различие 401 vs 403: [definitions.md](definitions.md).
> Полное описание методов аутентификации: [../../../../Security/authentication.md](../../../../Security/authentication.md).

## Основные концепции

### Путь запроса при 401

```
Запрос к API
    ↓
Аутентификация
    ↓
401 — личность не подтверждена
    ↓
(запрос отклонён, RBAC не проверяется)
```

### Частые причины 401

| Причина | Симптомы | Когда возникает |
|---------|----------|-----------------|
| Истёкший токен ServiceAccount | `Unauthorized: Invalid token` | Токен истёк или отозван |
| Неверный kubeconfig | `error: You must be logged in to the server` | Смена контекста, устаревшие credentials |
| Истёкший клиентский сертификат | `x509: certificate has expired` | Сертификат >1 год, не ротируется |
| Отсутствующий токен в запросе | `Unauthorized` | Pod без mounted SA token |

> **Важно:** С Kubernetes 1.24+ токены ServiceAccount не сохраняются в Secrets по умолчанию. Используйте `kubectl create token`.

## Практические сценарии

### Сценарий 1: Истёкший токен ServiceAccount

**Сообщение:**

```
Unauthorized: Invalid token
The token provided has expired
```

**Диагностика:**
Общий алгоритм проверки токена приведен в **[диагностике 401](diagnostics.md#шаг-2-диагностика-401-unauthorized)**.

**Решение:**

```bash
# Kubernetes 1.24+: создание нового токена
kubectl create token <sa-name> -n <namespace>
...
```

# Для долгосрочного токена (срок до 1 года)

kubectl create token <sa-name> -n <namespace> --duration=8760h

# Обновление kubeconfig новым токеном

kubectl config set-credentials <user> --token=<new-token>

# Если токен хранился в Secret — пересоздание

kubectl delete secret <sa-token-secret> -n <namespace>

# Kubernetes автоматически создаст новый токен

```

### Сценарий 2: Истёкший клиентский сертификат

**Сообщение:**

```

Unable to connect to the server: x509: certificate has expired or is not yet valid

```

**Диагностика:**

```bash
# Проверка срока сертификата kubeconfig
kubectl config view --minify --raw -o jsonpath='{.users[0].user.client-certificate-data}' | base64 -d | openssl x509 -noout -dates

# Проверка срока сертификата kubelet на узле
openssl x509 -in /var/lib/kubelet/pki/kubelet-client-current.pem -noout -dates
```

**Решение:**

```bash
# Для kubeadm-кластера — ротация сертификентов
kubeadm certs renew all

# Для kubelet — автоматическая ротация (если enabled)
# Проверка CSR
kubectl get csr | grep Pending

# Одобрение ожидающего CSR
kubectl certificate approve <csr-name>
```

### Сценарий 3: Неверный kubeconfig после смены кластера

**Диагностика:**
Проверьте текущий контекст и доступные учетные записи с помощью **[базовых команд диагностики](diagnostics.md#шаг-2-диагностика-401-unauthorized)**.

**Решение:**

```bash
# Переключение контекста
kubectl config use-context <target-context>
...
```

# Обновление токена в kubeconfig

kubectl config set-credentials <user> --token=$(kubectl create token <sa-name> -n <namespace>)

# Обновление сертификата

kubectl config set-credentials <user> \
  --client-certificate=<path-to-cert> \
  --client-key=<path-to-key>

```

## Дополнительная информация

### Автоматизация проверки аутентификации

```bash
#!/bin/bash
# Проверка аутентификации для ServiceAccount

SA=${1:-default}
NS=${2:-default}
TOKEN=$(kubectl create token "$SA" -n "$NS")

# Тестовый запрос к API
curl -k -H "Authorization: Bearer $TOKEN" \
  https://<api-server>:6443/api/v1/namespaces/$NS/pods
```

### Связанные ресурсы

- [Определения 401/403](definitions.md)
- [Пошаговая диагностика](diagnostics.md)
- [Методы аутентификации](../../../../Security/authentication.md)
- [Управление kubeconfig](../../../../Operations/kubeconfig_and_connection.md)
- [Объекты RBAC](rbac_objects.md)
- [Лучшие практики](best_practices.md)
