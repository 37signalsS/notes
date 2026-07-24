# Ошибки доступа к API: алгоритмы и методы диагностики

## Определения

**Диагностика ошибок доступа к API** — системный процесс выявления причин отказов с кодами 401 (Unauthorized) и 403 (Forbidden) в кластере Kubernetes. Процесс направлен на определение этапа, на котором был отклонен запрос: аутентификация, авторизация (RBAC) или контроль допуска (Admission Control).

**MTTD (Mean Time To Detect)** — среднее время обнаружения первопричины ошибки. В контексте API Kubernetes минимизируется за счет использования структурированных алгоритмов проверки.

> Типовые случаи 403 (Namespaced): [common.md](common.md)
> Расширенные сценарии (Admission, Cluster-wide): [advanced.md](advanced.md)

## Основные концепции

### Каскадный алгоритм диагностики

Проверка должна выполняться строго последовательно, так как каждый следующий этап предполагает успешное прохождение предыдущего.

```text
Ошибка API
    ↓
1. Определение кода ответа (через -v=8)
    ├── 401 Unauthorized → Проблема АУТЕНТИФИКАЦИИ (Кто вы?)
    └── 403 Forbidden    → Проблема АВТОРИЗАЦИИ или ПОЛИТИК
         ↓
    2. Идентификация субъекта (ServiceAccount, User, Group)
         ↓
    3. Проверка RBAC (Есть ли права в RoleBinding?)
         ↓
    4. Проверка Admission Control (PSA, Quotas, Webhooks)
         ↓
    5. Проверка логов API-сервера (если причина неясна)
```

### Инструментарий диагноста

| Инструмент | Сфера применения | Ключевая команда |
|------------|------------------|------------------|
| **Kubectl** | Проверка прав и манифестов | `kubectl auth can-i` |
| **Verbosity** | Детализация HTTP-запроса | `-v=8` или `-v=9` |
| **Events** | Ошибки Admission Control | `kubectl get events -n <ns>` |
| **API Server Logs** | Глубокий анализ отказов | `journalctl -u kube-apiserver` |

## Практические сценарии

### Шаг 1: Точная идентификация ошибки

Часто клиентские библиотеки или обертки (например, Helm) скрывают детали ошибки. Используйте `-v=8` для просмотра сырого HTTP-ответа.

```bash
# Трейс запроса для получения точного кода
kubectl get pods -v=8 2>&1 | grep -E "HTTP/.* [45][0-9][0-9]"

# Результат:
# HTTP/1.1 401 Unauthorized → Переходите к Шагу 2
# HTTP/1.1 403 Forbidden    → Переходите к Шагу 3
```

### Шаг 2: Диагностика 401 Unauthorized (Аутентификация)

Проблема заключается в том, что API-сервер не смог опознать предъявленные учетные данные.

**Для пользователей (kubeconfig):**
```bash
# Проверка текущего контекста и данных пользователя
kubectl config current-context
kubectl config view --minify
```

**Для приложений (ServiceAccount):**
В Kubernetes 1.24+ секреты с токенами не создаются автоматически.
```bash
# Попытка сгенерировать токен вручную для проверки
kubectl create token <sa-name> -n <namespace>

# Проверка срока действия токена в поде (если примонтирован)
kubectl exec <pod-name> -- cat /var/run/secrets/kubernetes.io/serviceaccount/token | cut -d. -f2 | base64 -d
```

### Шаг 3: Диагностика 403 Forbidden (RBAC)

Если аутентификация прошла (субъект известен), проверьте наличие прав через имитацию (**impersonation**).

```bash
# Проверка прав конкретного ServiceAccount (SA)
kubectl auth can-i list pods \
  --as=system:serviceaccount:<namespace>:<sa-name> \
  -n <namespace>

# Если 'no', ищем соответствующие привязки
kubectl get rolebindings,clusterrolebindings -A -o wide | grep "<sa-name>"
```

### Шаг 4: Диагностика 403 Forbidden (Admission Control)

Если `auth can-i` возвращает `yes`, но запрос все равно отклоняется с кодом 403, виноваты механизмы контроля допуска.

**Проверка Pod Security Admission (PSA):**
```bash
# Проверка меток неймспейса на политики безопасности
kubectl get namespace <namespace> -o jsonpath='{.metadata.labels}' | grep "pod-security"
```

**Проверка квот и событий:**
```bash
# Проверка блокирующих событий в неймспейсе
kubectl get events -n <namespace> --sort-by='.lastTimestamp' | tail -n 20
```

### Шаг 5: Анализ логов API-сервера

Если причина остается скрытой (например, запрос блокирует внешний Webhook), необходимо смотреть логи управляющего слоя (Control Plane).

```bash
# Для кластеров на базе systemd
journalctl -u kube-apiserver --since "10m" | grep "Forbidden"

# Для кластеров с API-сервером в поде (статический под)
kubectl logs -n kube-system -l component=kube-apiserver --tail=100
```

## Дополнительная информация

### Автоматизированный скрипт экспресс-диагностики

```bash
#!/bin/bash
# Скрипт проверки прав доступа ServiceAccount

SA_NAME=${1:?Укажите имя ServiceAccount}
NAMESPACE=${2:-default}

echo "--- Диагностика SA: $SA_NAME в NS: $NAMESPACE ---"

# 1. Существует ли SA
kubectl get sa "$SA_NAME" -n "$NAMESPACE" || exit 1

# 2. Какие права имеет (основные)
RESOURCES=("pods" "secrets" "configmaps" "deployments")
for RES in "${RESOURCES[@]}"; do
    CAN=$(kubectl auth can-i get "$RES" --as=system:serviceaccount:"$NAMESPACE":"$SA_NAME" -n "$NAMESPACE")
    echo "Access to $RES: $CAN"
done

# 3. Поиск RoleBindings
echo "--- Поиск привязок ролей ---"
kubectl get rolebinding -n "$NAMESPACE" -o wide | grep "$SA_NAME"
```

### Связанные ресурсы

- [Определения ошибок и модель прохождения запроса](definitions.md)
- [Практические примеры RBAC для 403](common.md)
- [Методы аутентификации и отладка 401](authentication_methods.md)
- [Официальная документация по отладке прав](https://kubernetes.io/docs/reference/access-authn-authz/authorization/#checking-api-access)
