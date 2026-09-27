# Секреты Kubernetes для Alertmanager

## Определения

**Kubernetes Secret (Opaque)** — основной объект для безопасного хранения конфиденциальной информации (паролей, токенов, ключей доступа) в кластере. В данном руководстве секреты используются для передачи учетных данных почтовых серверов и Telegram-ботов в процесс Alertmanager, исключая их хранение в открытом виде в ConfigMap или манифестах подов.

> **См. также:** [Управление секретами в Prometheus Operator](../../operator/Security/secrets_best_practices.md).

---

## Основные концепции

### Структура данных в секрете

| Ключ | Формат | Назначение |
| :--- | :--- | :--- |
| `smtp.user` | `string` | Логин для авторизации на SMTP-сервере. |
| `smtp.password` | `string` | Пароль или токен приложения (App Password) для отправки почты. |
| `telegram.token` | `string` | HTTP API токен Telegram-бота (от @BotFather). |
| `telegram.chat_id` | `string` | Числовой ID чата/группы для получения алертов. |

### Механизмы защиты и хранения

-   **Кодирование vs Шифрование:** Данные в Secret по умолчанию кодируются в `base64`. Для обеспечения реальной безопасности (Encryption at Rest) необходимо включить `EncryptionConfiguration` для etcd на уровне контрольной панели Kubernetes.
-   **Неизменяемые секреты (Immutable):** Начиная с K8s 1.21+, рекомендуется использовать поле `immutable: true`. Это снижает нагрузку на Kube-apiserver (отключает watch на объект) и предотвращает случайное изменение критических данных без пересоздания объекта.
-   **stringData vs data:** 
    -   `data`: значения должны быть предварительно закодированы в base64.
    -   `stringData`: позволяет писать значения в открытом виде (Kubernetes сам закодирует их при записи в etcd), что удобнее для ручного управления.
-   **RBAC:** Ограничьте доступ к секретам в namespace `monitoring`, разрешив `get` и `list` только поду Alertmanager и администраторам.

### Потребление секретов Alertmanager

Alertmanager получает значения из Secret двумя способами:
1.  **Переменные окружения (ENV):** через `env.valueFrom.secretKeyRef`. Используется в манифесте StatefulSet этого туториала.
2.  **Файлы томов (Volumes):** через `volumes.secret`. Подходит, если Alertmanager читает ключи из файлов (например, для `client_secret_file` в OAuth2-конфигурации — см. [Alertmanager](../../alertmanager.md#настройка-получателей-receivers)).

Для подстановки переменных прямо в `alertmanager.yml` используется флаг `--config.expand-external-variables` (Alertmanager v0.27+), что исключает необходимость инициализационного контейнера с `envsubst`.

### Рекомендации по именованию и организации

-   **Имена секретов:** используйте префикс `<app>-<component>`, например `alertmanager-secret`. В рамках namespace `monitoring` имя должно быть уникальным.
-   **Ключи внутри Secret:** используйте точечную нотацию (`smtp.user`, `smtp.password`) для группировки связанных данных. Это упрощает аудит и ротацию.
-   **Отделение сред:** для продакшена, стейджинга и разработки используйте разные namespace или разные имена секретов (`alertmanager-secret-prod`, `alertmanager-secret-staging`).

---

## Практические сценарии

### Создание секрета через манифест

**`alertmanager-secret.yaml`**

```yaml
apiVersion: v1
kind: Secret
metadata:
  name: alertmanager-secret
  namespace: monitoring
type: Opaque
immutable: true  # Рекомендуется для стабильных конфигураций
stringData:
  smtp.user: "alerting@example.com"
  smtp.password: "secure-app-password"
  telegram.token: "123456:ABC-DEF-GHI"
  telegram.chat_id: "-100123456789"
```

### Создание секрета через CLI (kubectl)

Императивный способ, исключающий хранение паролей в локальных файлах манифестов:

```bash
kubectl create secret generic alertmanager-secret \
  --from-literal=smtp.user='admin@example.com' \
  --from-literal=smtp.password='my-password' \
  --from-literal=telegram.token='bot-token' \
  --from-literal=telegram.chat_id='-123456' \
  -n monitoring
```

### Диагностика: Проверка переменных в контейнере

Чтобы убедиться, что секреты корректно проброшены в Alertmanager, используйте команду:

```bash
kubectl exec -n monitoring alertmanager-0 -c alertmanager -- env | grep -E 'SMTP|TELEGRAM'
```

### Использование в StatefulSet

Секреты подключаются как переменные окружения, которые затем считываются Alertmanager через синтаксис `${VAR}` в `alertmanager.yml`.

```yaml
env:
  - name: SMTP_PASSWORD
    valueFrom:
      secretKeyRef:
        name: alertmanager-secret
        key: smtp.password
  ```

### Валидация секрета

После создания секрета выполните проверку корректности:

```bash
# Список секретов в namespace monitoring
kubectl get secrets -n monitoring

# Описание секрета (без значений)
kubectl describe secret alertmanager-secret -n monitoring

# Проверка конкретного ключа (декодирование base64)
kubectl get secret alertmanager-secret -n monitoring -o jsonpath='{.data.smtp\.password}' | base64 -d
# → secure-app-password
```

> **Примечание:** При использовании `jsonpath` экранируйте точку в имени ключа (`smtp\.password`).

### Обновление и ротация секретов

Для обновления значения ключа:

```bash
# Если secret НЕ immutable
kubectl patch secret alertmanager-secret -n monitoring \
  -p '{"stringData":{"smtp.password":"new-secure-password"}}'

# Если secret immutable — удалите и создайте заново
kubectl delete secret alertmanager-secret -n monitoring
kubectl create secret generic alertmanager-secret \
  --from-literal=smtp.password='new-secure-password' \
  -n monitoring
```

После обновления секрета перезапустите StatefulSet, чтобы ENV-переменные обновились:

```bash
kubectl rollout restart statefulset/alertmanager -n monitoring
kubectl rollout status statefulset/alertmanager -n monitoring
```

### RBAC: Ограничение доступа к секретам

Создайте `ServiceAccount` и `Role` с минимальными привилегиями для Alertmanager:

**`alertmanager-rbac.yaml`**

```yaml
apiVersion: v1
kind: ServiceAccount
metadata:
  name: alertmanager
  namespace: monitoring
---
apiVersion: rbac.authorization.k8s.io/v1
kind: Role
metadata:
  name: alertmanager-secret-reader
  namespace: monitoring
rules:
- apiGroups: [""]
  resources: ["secrets"]
  resourceNames: ["alertmanager-secret"]
  verbs: ["get", "list"]
---
apiVersion: rbac.authorization.k8s.io/v1
kind: RoleBinding
metadata:
  name: alertmanager-secret-reader-binding
  namespace: monitoring
subjects:
- kind: ServiceAccount
  name: alertmanager
  namespace: monitoring
roleRef:
  kind: Role
  name: alertmanager-secret-reader
  apiGroup: rbac.authorization.k8s.io
```

Примените манифест:

```bash
kubectl apply -f alertmanager-rbac.yaml
```

### Устранение неисправностей

| Симптом | Причина | Диагностика | Решение |
| :--- | :--- | :--- | :--- |
| Alertmanager не отправляет email | Неверный пароль SMTP или недоступный сервер | `kubectl logs -n monitoring alertmanager-0 -c alertmanager \| grep -i smtp` | Проверить `smtp.password` в Secret и доступность SMTP-сервера |
| Telegram-бот не отвечает | Неверный `bot_token` или `chat_id` | `kubectl exec -n monitoring alertmanager-0 -c alertmanager -- env \| grep TELEGRAM` | Проверить токен через `@BotFather`, убедиться что бот добавлен в чат |
| Под в CrashLoopBackOff | Секрет не найден или нет прав на чтение | `kubectl describe pod -n monitoring alertmanager-0` — искать `Failed to create pod sandbox` или `forbidden` | Проверить имя Secret, namespace, RBAC-права |
| Изменения Secret не применяются | Secret immutable или Pod не перезапущен | `kubectl get secret alertmanager-secret -n monitoring -o jsonpath='{.immutable}'` | Снять `immutable` или перезапустить StatefulSet |

### Очистка ресурсов

```bash
# Удалить Secret
kubectl delete secret alertmanager-secret -n monitoring

# Удалить RBAC (если создавали)
kubectl delete rolebinding alertmanager-secret-reader-binding -n monitoring
kubectl delete role alertmanager-secret-reader -n monitoring
kubectl delete serviceaccount alertmanager -n monitoring

# Проверить отсутствие секретов
kubectl get secrets -n monitoring
```

---

## Дополнительная информация

-   **[Конфигурация (ConfigMap)](./alertmanager-config.md)** — использование переменных в основном конфиге.
-   **[Манифест StatefulSet](./alertmanager-statefulset.md)** — полная спецификация подов с монтированием секретов.
-   **[Внешние менеджеры секретов](../../../../Kubernetes/Base/secrets/external_managers.md)** — SSoT по интеграции с HashiCorp Vault, External Secrets Operator и Secrets Store CSI Driver.
-   **[Безопасность Secret в Kubernetes](../../../../Kubernetes/Base/secrets/security.md)** — SSoT по шифрованию at rest, immutable-секретам и RBAC.
-   **[Лучшие практики Prometheus Operator](../../operator/Security/secrets_best_practices.md)** — управление секретами в контексте Operator.
