# Pod в состоянии `CrashLoopBackOff`: Распространенные случаи и решения

## 1. Ошибка в приложении (баг, исключение)

**Симптомы:**

- В логах stack trace, exception
- Exit Code: 1 или другой ненулевой

**Решение:**

- Исправить код приложения
- Добавить обработку исключений
- Проверить зависимости (библиотеки, модули)

---

## 2. Неверная конфигурация

**Симптомы:**

- Ошибка в логах: "config not found", "missing environment variable"
- Exit Code: 1

**Примеры:**

```yaml
# ❌ Ошибка: ConfigMap не существует
envFrom:
- configMapRef:
    name: missing-config

# ❌ Ошибка: Secret не найден
env:
- name: DB_PASSWORD
  valueFrom:
    secretKeyRef:
      name: missing-secret
      key: password
```

**Решение:**

```bash
# Создать недостающий ConfigMap
kubectl create configmap app-config --from-literal=key=value

# Или исправить ссылку в манифесте
```

---

## 3. Проблемы с зависимостями (БД, кэш, API)

**Симптомы:**

- В логах: "connection refused", "timeout", "cannot connect"
- Приложение падает при старте при проверке подключения

**Решение:**

```yaml
# Добавить проверку доступности зависимости перед стартом
initContainers:
- name: wait-for-db
  image: busybox
  command: ['sh', '-c', 'until nc -z db-service 5432; do sleep 2; done']

# Или использовать startupProbe для отсрочки проверки liveness
startupProbe:
  tcpSocket:
    port: 5432
  failureThreshold: 30
  periodSeconds: 10
```

---

## 4. Недостаточно прав RBAC

**Симптомы:**

- В логах: "Forbidden", "permission denied", "unauthorized"
- Приложение обращается к Kubernetes API

**Пример из практики:** Log shipper пытается читать логи других подов.

**Диагностика:**

```bash
# Проверка прав ServiceAccount
kubectl auth can-i get pods/log --as=system:serviceaccount:my-ns:my-sa
```

**Решение:**

```yaml
apiVersion: rbac.authorization.k8s.io/v1
kind: Role
metadata:
  name: pod-log-reader
  namespace: my-ns
rules:
- apiGroups: [""]
  resources: ["pods/log"]
  verbs: ["get", "list", "watch"]
---
apiVersion: rbac.authorization.k8s.io/v1
kind: RoleBinding
metadata:
  name: my-sa-pod-log-reader
  namespace: my-ns
subjects:
- kind: ServiceAccount
  name: my-sa
  namespace: my-ns
roleRef:
  kind: Role
  name: pod-log-reader
  apiGroup: rbac.authorization.k8s.io
```

> **См. также:** [`rbac_overview.md`](../../../Security/rbac/rbac_overview.md)

---

## 5. Неудачная livenessProbe

**Симптомы:**

- В `kubectl describe`: `Killing container ... Liveness probe failed`
- В логах приложения могут отсутствовать ошибки, так как оно работает корректно, но проба настроена неверно.

**Диагностика и решение:**

Частая причина — несоответствие порта, пути или схемы (HTTP/HTTPS) в `livenessProbe` и реального эндпоинта приложения.

1. **Стабилизируйте под**, временно отключив пробу через `kubectl edit deployment <name>` или используя паттерн "заморозки" (см. ниже).
2. **Подключитесь к поду** с помощью `kubectl debug`.
3. **Найдите реальный порт и путь** внутри контейнера:

    ```bash
    # Внутри debug-контейнера
    # Узнаем, какой порт слушает приложение
    netstat -tuln

    # Проверяем, отвечает ли эндпоинт
    wget -q -O - http://localhost:3333/health
    ```

4. **Исправьте `livenessProbe`** в манифесте, указав корректный порт и путь, и увеличьте `initialDelaySeconds`, если приложение стартует медленно.

    ```yaml
    livenessProbe:
      httpGet:
        path: /health # Убедитесь, что этот путь верен
        port: 3333      # Укажите порт, который слушает приложение
      initialDelaySeconds: 60
      periodSeconds: 10
    ```

5. **Для медленно стартующих приложений** используйте `startupProbe`, чтобы отложить проверку liveness:

    ```yaml
    # Используйте startupProbe для отсрочки проверки liveness
    startupProbe:
      httpGet:
        path: /health
        port: 3333
      failureThreshold: 30 # Дает приложению 300с (30*10) на старт
      periodSeconds: 10
    ```

---

## 6. OOMKilled

**Симптомы:**

- Exit Code: 137
- Reason: OOMKilled

**Решение:** См. [`oomkilled_pods.md`](../oomkilled_pods.md)

---

## Частные случаи

### `Init:CrashLoopBackOff`

Если в CrashLoopBackOff уходит `initContainer`:

```bash
# Логи init-контейнера
kubectl logs <pod-name> -c <init-container-name> --previous

# Описание пода
kubectl describe pod <pod-name>
```

**Частые причины:**

- Скрипт инициализации падает с ошибкой
- Недоступна зависимость (БД, миграции)
- Неверный syntax в shell-скрипте

> **Пример:** В оригинальном видео отсутствовало слово `then` после условия `if`, что приводило к `CrashLoopBackOff` у initContainer.

---

### `Completed` → `CrashLoopBackOff`

Если контейнер завершается с кодом 0, но Deployment ожидает долгоживущий процесс:

**Причина:** Контейнер предназначен для одноразовых задач (Jobs), а не для Deployments.

**Решение:** Изменить приложение на долгоживущий процесс или использовать `Job`/`CronJob`.

---

## Временная "заморозка" пода для отладки

При постоянных рестартах (`CrashLoopBackOff`) невозможно использовать `kubectl exec` или `kubectl debug`, так как для подключения требуется запущенный контейнер. Чтобы это обойти, можно "заморозить" под, временно переопределив его команду на `sleep`. Это стабилизирует контейнер в состоянии `Running`, позволяя провести диагностику.

**Команда для "заморозки":**

```bash
kubectl patch deployment <deployment-name> \
  -p '{"spec":{"template":{"spec":{"containers":[{"name":"<container-name>","command":["sleep","3600"]}]}}}}'
```

После этого можно безопасно подключаться к поду для исследования файловой системы, переменных окружения и сетевых настроек.

**После отладки:**

```bash
kubectl rollout undo deployment/<deployment-name>
```

> **См. также:** [`troubleshooting_overview.md`](../../troubleshooting_overview.md)

---

## Ссылки

- **[Диагностика](./diagnostics.md)** — пошаговый чек-лист
- **[Определения и концепции](./definitions_and_concepts.md)** — базовая информация
