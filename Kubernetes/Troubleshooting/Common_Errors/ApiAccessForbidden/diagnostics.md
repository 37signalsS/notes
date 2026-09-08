# Ошибки доступа к API: алгоритмы и методы диагностики

## Определения

**Диагностика ошибок доступа к API** — системный процесс выявления и устранения причин отказов с кодами 401 (Unauthorized) и 403 (Forbidden). Процесс охватывает все уровни контроля: аутентификацию (личность), авторизацию (RBAC) и контроль допуска (Admission).

**MTTD (Mean Time To Detect)** — среднее время обнаружения первопричины. Для API Kubernetes целью является локализация проблемы (AuthN vs AuthZ vs Admission) менее чем за 2 минуты с использованием стандартного инструментария.

**MTTR (Mean Time To Resolve)** — среднее время устранения проблемы после обнаружения. Для API Kubernetes цель — восстановление работоспособности приложений менее чем за 15 минут через исправление RBAC-конфигурации или временные обходные пути.

**Audit ID** — уникальный идентификатор запроса, который возвращается в HTTP-заголовке `Audit-Id`. Позволяет сопоставить клиентскую ошибку с записями в логах API-сервера.

**Имперсонация (Impersonation)** — механизм проверки прав от имени другого субъекта без переключения контекста аутентификации. Используется через флаги `--as`, `--as-group`, `--as-uid` в `kubectl`.

> Концептуальные различия 401 vs 403: [definitions.md](definitions.md)
> Распространенные случаи 403 (RBAC): [common.md](common.md)
> Продвинутые сценарии (Admission): [advanced.md](advanced.md)

## Основные концепции

### Каскадный алгоритм локализации (Логика исключения)

Проверка выполняется по принципу "от простого к сложному", следуя пути прохождения запроса внутри API-сервера.

```text
КЛИЕНТСКАЯ ОШИБКА
    ↓
1. Идентификация кода (kubectl -v=8)
    ├── 401 Unauthorized → Сбой Аутентификации (Шаг 2)
    └── 403 Forbidden    → Сбой Авторизации или Политик (Шаг 3)
         ↓
    2. Проверка RBAC (kubectl auth can-i)
         ├── Результат: NO  → Ошибка RBAC (Шаг 3.1)
         └── Результат: YES → Ошибка Admission Control (Шаг 3.2)
              ↓
         3. Анализ Audit ID и логов (Шаг 4)
```

### Алгоритм устранения проблем с высокой доступностью

При возникновении ошибки 401/403 в production-среде:

```text
ПРОИЗВОДСТВЕННАЯ ОШИБКА
    ↓
1. Быстрая идентификация (MTTD < 2 мин)
   ├── Проверить kubectl logs -f kube-apiserver
   ├── Найти Audit-Id в HTTP-заголовке
   └── Определить тип ошибки (401/403)
    ↓
2. Временное решение (MTTR < 15 мин)
   ├── Для 401: Обновить сертификат/токен
   ├── Для 403: Временный ClusterRoleBinding
   └── Для Admission: Временно отключить webhook
    ↓
3. Корневой анализ (RCA)
   ├── Audit-log анализ
   ├── Проверка RBAC-манифестов
   └── Валидация Admission-политик
    ↓
4. Постоянное исправление
   ├── Исправленный манифест
   ├── Тест в staging
   └── Применение в production
```

### Инструментарий инженера

| Инструмент | Команда / Метод | Назначение | Когда использовать |
|------------|-----------------|------------|-------------------|
| **Kubectl Verbosity** | `-v=8` или `-v=9` | Получение сырых HTTP-заголовков и Audit-Id. | Первичная диагностика любого отказа API. |
| **Auth Can-i** | `kubectl auth can-i` | Быстрая проверка прав с имитацией (`--as`). | Быстрая проверка RBAC-гипотез. |
| **Events** | `kubectl get events` | Поиск блокировок от ResourceQuotas или PSA. | Поиск ошибок Admission Control. |
| **API Server Logs** | `journalctl` / `kubectl logs` | Глубокий анализ (особенно для Webhooks). | Сложные сценарии с audit-log. |
| **Direct API Call** | `curl -v -k` | Изоляция проблем, связанных с `kubectl`. | Отладка сетевых проблем. |
| **Audit-Log** | `grep` / `jq` | Анализ записей аудита по Audit-Id. | Корневой анализ (RCA). |
| **External Tools** | `kubectl-who-can`, `rbac-lookup` | Интерактивный анализ RBAC-связей. | Визуализация сложных разрешений. |

## Практические сценарии

### Шаг 1: Получение Audit ID и кода ошибки

Если причина ошибки неочевидна, первым делом извлеките идентификатор запроса.

```bash
# Выполнение команды с максимальной детализацией
kubectl get secrets -v=8 2>&1 | grep -E "Audit-Id|HTTP/.* [45][0-9][0-9]"

# Пример вывода:
# HTTP/1.1 403 Forbidden
# Audit-Id: 2f7e4b51-7d9a-4e8c-b0f1-2d83a9e12345

# Или через curl (для изоляции проблем с kubectl):
curl -k -v -H "Authorization: Bearer $TOKEN" \
  https://api-server:6443/api/v1/namespaces/default/pods 2>&1 | grep -E "Audit-Id|HTTP/"
```

### Шаг 2: Диагностика 401 Unauthorized (Аутентификация)

Ошибка означает, что сервер не принял ваши учетные данные.

1.  **Проверка сертификата (для админов):**
    ```bash
    # Проверка срока действия сертификата в kubeconfig
    grep 'client-certificate-data' ~/.kube/config | awk '{print $2}' | base64 -d | openssl x509 -noout -dates
    
    # Проверка цепочки сертификатов
    kubectl config view --raw -o jsonpath='{.users[0].user.client-certificate-data}' | base64 -d | openssl x509 -text -noout | head -20
    ```
2.  **Проверка токена (для приложений):**
    ```bash
    # Проверка, не протух ли токен ServiceAccount (JWT)
    TOKEN=$(kubectl exec <pod-name> -- cat /var/run/secrets/kubernetes.io/serviceaccount/token)
    echo $TOKEN | cut -d. -f2 | base64 -d | jq .exp
    
    # Проверка audience токена (для Bound Tokens)
    echo $TOKEN | cut -d. -f2 | base64 -d | jq .aud
    ```
3.  **Анонимный доступ:** Если вы видите пользователя `system:anonymous`, значит ваши учетные данные не были переданы или не были распознаны ни одним аутентификатором.
    ```bash
    # Проверка включения анонимного доступа
    kubectl get --raw /version | jq .serverGitCommit
    
    # Проверка статуса анонимного пользователя
    kubectl get --raw /api/v1/namespaces/default/pods -H "Authorization: Bearer " | jq .kind
    ```

### Шаг 3: Диагностика 403 Forbidden

#### 3.1 Ошибка RBAC (Авторизация)
Если `kubectl auth can-i` возвращает `no`, проблема в отсутствии `RoleBinding`.

```bash
# Проверка прав конкретного SA с имитацией
kubectl auth can-i list secrets \
  --as=system:serviceaccount:prod-ns:app-sa \
  -n prod-ns

# Проверка всех прав SA (детальный список)
kubectl auth can-i --list \
  --as=system:serviceaccount:prod-ns:app-sa \
  -n prod-ns

# Проверка прав с учетом групп
kubectl auth can-i create deployments \
  --as=user@example.com \
  --as-group=developers \
  -n prod-ns
```

#### 3.2 Ошибка Admission Control (Политики)
Если `auth can-i` возвращает `yes`, но запрос отклоняется, значит он блокируется на финальном этапе.

*   **Проверка таймаутов вебхуков:** Если API-сервер долго "думает" и возвращает 403 или 500, проверьте доступность вебхуков.
    ```bash
    # Поиск проблемных вебхуков
    kubectl get validatingwebhookconfigurations -o json | jq '.items[].webhooks[].clientConfig'
    
    # Проверка доступности webhook-сервисов
    kubectl get endpoints -A | grep -v "<none>"
    ```
*   **Проверка квот:**
    ```bash
    # Проверка, не блокирует ли ResourceQuota создание объекта
    kubectl describe resourcequota -n <namespace>
    
    # Проверка LimitRange (defaults для подов без ресурсов)
    kubectl get limitrange -n <namespace> -o yaml
    ```

### Шаг 4: Анализ логов по Audit ID

Если вы получили `Audit-Id` на Шаге 1, найдите соответствующую запись в логах API-сервера.

```bash
# Поиск причины отказа в логах (для систем на базе systemd)
journalctl -u kube-apiserver --since "10m" | grep "2f7e4b51-7d9a-4e8c-b0f1-2d83a9e12345"

# Поиск упоминаний внешних вебхуков (Kyverno, Gatekeeper)
kubectl logs -n kyverno -l app.kubernetes.io/name=kyverno | grep "2f7e4b51-7d9a-4e8c-b0f1-2d83a9e12345"

# Анализ audit-log с jq (если настроен файловый аудит)
grep "2f7e4b51-7d9a-4e8c-b0f1-2d83a9e12345" /var/log/kubernetes/audit.log | jq '.responseStatus.code, .user.username'
```

### Шаг 5: Отладка через прямые запросы API

Для изоляции проблем с `kubectl` используйте прямые запросы к API:

```bash
# Получение токена из kubeconfig
TOKEN=$(kubectl config view --minify -o jsonpath='{.users[0].user.token}')

# Или через service account
TOKEN=$(kubectl exec <pod-name> -- cat /var/run/secrets/kubernetes.io/serviceaccount/token)

# Прямой запрос к API
curl -k -H "Authorization: Bearer $TOKEN" \
  https://api-server:6443/api/v1/namespaces/default/pods

# Проверка версии API
curl -k -H "Authorization: Bearer $TOKEN" \
  https://api-server:6443/version
```

## Дополнительная информация

### Скрипт комплексной проверки доступа ServiceAccount

```bash
#!/bin/bash
# diagnostics_sa.sh — Расширенная проверка прав и токенов SA

set -euo pipefail

SA_NAME=${1:?Укажите имя ServiceAccount}
NAMESPACE=${2:-default}

echo "=== Диагностика SA: $SA_NAME в NS: $NAMESPACE ==="

# 1. Проверка существования SA
if ! kubectl get sa "$SA_NAME" -n "$NAMESPACE" &>/dev/null; then
    echo "❌ ServiceAccount $SA_NAME не найден в namespace $NAMESPACE"
    exit 1
fi

# 2. Существование и токены
echo "--- Токены SA ---"
kubectl get sa "$SA_NAME" -n "$NAMESPACE" -o json | jq -r '.secrets[].name' 2>/dev/null | xargs -I {} echo "✓ Secret Token: {}" || echo "⚠ Токены не найдены"

# 3. Проверка automountServiceAccountToken
AUTOMOUNT=$(kubectl get sa "$SA_NAME" -n "$NAMESPACE" -o jsonpath='{.automountServiceAccountToken}')
echo "--- automountServiceAccountToken: $AUTOMOUNT ---"

# 4. Проверка базовых прав
echo "--- Проверка прав ---"
RESOURCES=("pods" "secrets" "configmaps" "services" "deployments" "configmaps")
for RES in "${RESOURCES[@]}"; do
    CAN=$(kubectl auth can-i get "$RES" --as=system:serviceaccount:"$NAMESPACE":"$SA_NAME" -n "$NAMESPACE" 2>/dev/null || echo "no")
    printf "  %-15s: %s\n" "$RES" "$CAN"
done

# 5. Проверка特殊ых прав
echo "--- Проверка специальных прав ---"
kubectl auth can-i list secrets --as=system:serviceaccount:"$NAMESPACE":"$SA_NAME" -n "$NAMESPACE" 2>/dev/null && echo "  ⚠ SA может читать ВСЕ секреты!" || echo "  ✓ Доступ к секретам ограничен"
kubectl auth can-i create pods/exec --as=system:serviceaccount:"$NAMESPACE":"$SA_NAME" -n "$NAMESPACE" 2>/dev/null && echo "  ⚠ SA может выполнять exec в поды!" || echo "  ✓ Exec запрещен"

# 6. Поиск всех привязок
echo "--- RoleBindings в namespace ---"
kubectl get rolebindings -n "$NAMESPACE" -o wide | grep "$SA_NAME" || echo "  RoleBindings не найдены"

echo "--- ClusterRoleBindings (глобальные) ---"
kubectl get clusterrolebindings -o wide | grep "$SA_NAME" || echo "  ClusterRoleBindings не найдены"

# 7. Проверка кросс-неймспейс привязок
echo "--- Кросс-неймспейс RoleBindings ---"
kubectl get rolebindings -A -o json | jq -r --arg sa "$SA_NAME" --arg ns "$NAMESPACE" \
  '.items[] | select(.subjects[]? | .kind == "ServiceAccount" and .name == $sa and .namespace == $ns) | "\(.metadata.namespace)/\(.metadata.name) -> \(.roleRef.name)"' 2>/dev/null || echo "  Не найдены"

echo "=== Диагностика завершена ==="
```

### Чек-лист "Белые пятна" диагностики

1.  **NodeRestriction:** Если вы отлаживаете `kubelet`, помните, что он может изменять только свои объекты. Попытка изменить чужой под вернет 403, даже если у SA узла есть права.
    ```bash
    # Проверка прав kubelet на конкретный под
    kubectl auth can-i update pods --as=system:node:$(hostname) -n <ns>
    ```

2.  **Webhook Failure Policy:** Проверьте, установлено ли в конфигурации вебхука `failurePolicy: Fail` (блокирует запрос при падении вебхука) или `Ignore`.
    ```bash
    # Проверка failurePolicy всех webhook'ов
    kubectl get validatingwebhookconfigurations -o json | jq '.items[].webhooks[] | {name: .name, failurePolicy: .failurePolicy}'
    ```

3.  **API Priority and Fairness (APF):** В редких случаях запросы могут отклоняться (429 или 403) из-за очередей приоритетов API-сервера. Проверьте `kubectl get flowschemas`.
    ```bash
    # Проверка FlowSchema и PriorityLevelConfiguration
    kubectl get flowschemas -o custom-columns=NAME:.metadata.name,PRIORITY:.spec.priorityLevelConfiguration.name
    kubectl get prioritylevelconfigurations
    ```

4.  **Aggregation Layer:** Если 403 возникает при запросе к `metrics.k8s.io`, проблема может быть в сертификатах между основным API-сервером и `metrics-server`.
    ```bash
    # Проверка состояния APIService
    kubectl get apiservices | grep -E "metrics|custom"
    kubectl get apiservice v1beta1.metrics.k8s.io -o yaml | grep -A5 conditions
    ```

5.  **Имперсонация (Impersonation):** При использовании `--as` в `kubectl auth can-i` проверяется RBAC для имперсонируемого субъекта, но реальный запрос идет от текущего пользователя. Всегда проверяйте реальное выполнение команды.
    ```bash
    # Проверка имперсонации
    kubectl auth can-i list pods --as=user@example.com --as-group=developers
    kubectl get pods --as=user@example.com --as-group=developers  # Реальный запрос
    ```

6.  **Кросс-неймспейс доступ:** `RoleBinding` в одном namespace может ссылаться на `ServiceAccount` из другого namespace. Это валидный паттерн, но его легко пропустить при аудите.
    ```bash
    # Поиск кросс-неймспейс привязок
    kubectl get rolebindings -A -o json | jq '.items[] | select(.subjects[]? | .namespace != .metadata.namespace)'
    ```

7.  **Агрегированные API:** Некоторые ресурсы (metrics, custom metrics) требуют отдельных RBAC-прав. Стандартных прав cluster-admin может быть недостаточно.
    ```bash
    # Проверка доступа к агрегированным API
    kubectl get --raw /apis/metrics.k8s.io/v1beta1/nodes | jq .
    kubectl get --raw /apis/custom.metrics.k8s.io/v1beta1 | jq .
    ```

### Распространенные ловушки при отладке

| Ловушка | Описание | Решение |
|---------|----------|---------|
| **False positive от `can-i`** | `kubectl auth can-i create configmap/fluentd` может вернуть `yes`, но реальный `POST` на коллекцию вернет 403 | Всегда проверяйте реальное выполнение команды |
| **Immutable roleRef** | Изменение `roleRef` в RoleBinding/ClusterRoleBinding не работает через `kubectl apply` | Удалите и создайте биндинг заново |
| **Wildcard `*` vs resourceNames** | Wildcard `verbs: ["*"]` не работает с `resourceNames` для `create`/`deletecollection` | Используйте конкретные глаголы или проверяйте с field selector |
| **Смешанные группы API** | Опечатка в `apiGroups` (например, `""` вместо `"apps"`) приводит к 403 | Проверяйте группу через `kubectl api-resources` |
| **Case sensitivity** | Имена ресурсов и глаголы чувствительны к регистру | Всегда используйте нижний регистр |

### Производительность при отладке

При работе с большими кластерами учитывайте влияние отладочных команд:

```bash
# Избегайте полного сканирования audit-log на больших кластерах
# Вместо этого используйте фильтрацию по Audit-Id
grep "audit-id" /var/log/kubernetes/audit.log | head -100

# Ограничивайте область поиска в logs
kubectl logs -l app=nginx --tail=100 --since=10m

# Используйте кеширование для часто запрашиваемых данных
kubectl api-resources --cached=true
```

### Связанные ресурсы

- [Определения и модель безопасности API](definitions.md)
- [Практические примеры RBAC для 403](common.md)
- [Расширенные сценарии (Admission Control)](advanced.md)
- [Методы аутентификации и отладка 401](authentication_methods.md)
- [Объекты RBAC: структура и ошибки](rbac_objects.md)
