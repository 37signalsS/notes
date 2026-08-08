# Ошибки доступа к API: алгоритмы и методы диагностики

## Определения

**Диагностика ошибок доступа к API** — системный процесс выявления и устранения причин отказов с кодами 401 (Unauthorized) и 403 (Forbidden). Процесс охватывает все уровни контроля: аутентификацию (личность), авторизацию (RBAC) и контроль допуска (Admission).

**MTTD (Mean Time To Detect)** — среднее время обнаружения первопричины. Для API Kubernetes целью является локализация проблемы (AuthN vs AuthZ vs Admission) менее чем за 2 минуты с использованием стандартного инструментария.

**Audit ID** — уникальный идентификатор запроса, который возвращается в HTTP-заголовке `Audit-Id`. Позволяет сопоставить клиентскую ошибку с записями в логах API-сервера.

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

### Инструментарий инженера

| Инструмент | Команда / Метод | Назначение |
|------------|-----------------|------------|
| **Kubectl Verbosity** | `-v=8` или `-v=9` | Получение сырых HTTP-заголовков и Audit-Id. |
| **Auth Can-i** | `kubectl auth can-i` | Быстрая проверка прав с имитацией (`--as`). |
| **Events** | `kubectl get events` | Поиск блокировок от ResourceQuotas или PSA. |
| **API Server Logs** | `journalctl` / `kubectl logs` | Глубокий анализ (особенно для Webhooks). |
| **Direct API Call** | `curl -v -k` | Изоляция проблем, связанных с `kubectl`. |

## Практические сценарии

### Шаг 1: Получение Audit ID и кода ошибки

Если причина ошибки неочевидна, первым делом извлеките идентификатор запроса.

```bash
# Выполнение команды с максимальной детализацией
kubectl get secrets -v=8 2>&1 | grep -E "Audit-Id|HTTP/.* [45][0-9][0-9]"

# Пример вывода:
# HTTP/1.1 403 Forbidden
# Audit-Id: 2f7e4b51-7d9a-4e8c-b0f1-2d83a9e12345
```

### Шаг 2: Диагностика 401 Unauthorized (Аутентификация)

Ошибка означает, что сервер не принял ваши учетные данные.

1.  **Проверка сертификата (для админов):**
    ```bash
    # Проверка срока действия сертификата в kubeconfig
    grep 'client-certificate-data' ~/.kube/config | awk '{print $2}' | base64 -d | openssl x509 -noout -dates
    ```
2.  **Проверка токена (для приложений):**
    ```bash
    # Проверка, не протух ли токен ServiceAccount (JWT)
    TOKEN=$(kubectl exec <pod-name> -- cat /var/run/secrets/kubernetes.io/serviceaccount/token)
    echo $TOKEN | cut -d. -f2 | base64 -d | jq .exp
    ```
3.  **Анонимный доступ:** Если вы видите пользователя `system:anonymous`, значит ваши учетные данные не были переданы или не были распознаны ни одним аутентификатором.

### Шаг 3: Диагностика 403 Forbidden

#### 3.1 Ошибка RBAC (Авторизация)
Если `kubectl auth can-i` возвращает `no`, проблема в отсутствии `RoleBinding`.

```bash
# Проверка прав конкретного SA с имитацией
kubectl auth can-i list secrets \
  --as=system:serviceaccount:prod-ns:app-sa \
  -n prod-ns
```

#### 3.2 Ошибка Admission Control (Политики)
Если `auth can-i` возвращает `yes`, но запрос отклоняется, значит он блокируется на финальном этапе.

*   **Проверка таймаутов вебхуков:** Если API-сервер долго "думает" и возвращает 403 или 500, проверьте доступность вебхуков.
    ```bash
    # Поиск проблемных вебхуков
    kubectl get validatingwebhookconfigurations -o json | jq '.items[].webhooks[].clientConfig'
    ```
*   **Проверка квот:**
    ```bash
    # Проверка, не блокирует ли ResourceQuota создание объекта
    kubectl describe resourcequota -n <namespace>
    ```

### Шаг 4: Анализ логов по Audit ID

Если вы получили `Audit-Id` на Шаге 1, найдите соответствующую запись в логах API-сервера.

```bash
# Поиск причины отказа в логах (для систем на базе systemd)
journalctl -u kube-apiserver --since "10m" | grep "2f7e4b51-7d9a-4e8c-b0f1-2d83a9e12345"

# Поиск упоминаний внешних вебхуков (Kyverno, Gatekeeper)
kubectl logs -n kyverno -l app.kubernetes.io/name=kyverno | grep "2f7e4b51-7d9a-4e8c-b0f1-2d83a9e12345"
```

## Дополнительная информация

### Скрипт комплексной проверки доступа ServiceAccount

```bash
#!/bin/bash
# diagnostics_sa.sh — Расширенная проверка прав и токенов SA

SA_NAME=${1:?Укажите имя ServiceAccount}
NAMESPACE=${2:-default}

echo "=== Диагностика SA: $SA_NAME в NS: $NAMESPACE ==="

# 1. Существование и токены
kubectl get sa "$SA_NAME" -n "$NAMESPACE" -o json | jq -r '.secrets[].name' 2>/dev/null | xargs -I {} echo "Found Secret Token: {}"

# 2. Проверка базовых прав
RESOURCES=("pods" "secrets" "configmaps" "services")
for RES in "${RESOURCES[@]}"; do
    CAN=$(kubectl auth can-i get "$RES" --as=system:serviceaccount:"$NAMESPACE":"$SA_NAME" -n "$NAMESPACE")
    printf "Access to %-12s: %s\n" "$RES" "$CAN"
done

# 3. Поиск всех привязок
echo "--- Действующие RoleBindings ---"
kubectl get rolebindings -n "$NAMESPACE" -o wide | grep "$SA_NAME"

# 4. Проверка на наличие ClusterRoleBindings
echo "--- Действующие ClusterRoleBindings ---"
kubectl get clusterrolebindings -o wide | grep "$SA_NAME"
```

### Чек-лист "Белые пятна" диагностики

1.  **NodeRestriction:** Если вы отлаживаете `kubelet`, помните, что он может изменять только свои объекты. Попытка изменить чужой под вернет 403, даже если у SA узла есть права.
2.  **Webhook Failure Policy:** Проверьте, установлено ли в конфигурации вебхука `failurePolicy: Fail` (блокирует запрос при падении вебхука) или `Ignore`.
3.  **API Priority and Fairness (APF):** В редких случаях запросы могут отклоняться (429 или 403) из-за очередей приоритетов API-сервера. Проверьте `kubectl get flowschemas`.
4.  **Aggregation Layer:** Если 403 возникает при запросе к `metrics.k8s.io`, проблема может быть в сертификатах между основным API-сервером и `metrics-server`.

### Связанные ресурсы

- [Определения и модель безопасности API](definitions.md)
- [Практические примеры RBAC для 403](common.md)
- [Расширенные сценарии (Admission Control)](advanced.md)
- [Методы аутентификации и отладка 401](authentication_methods.md)
- [Объекты RBAC: структура и ошибки](rbac_objects.md)
