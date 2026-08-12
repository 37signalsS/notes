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

---

## Дополнительная информация

- **[Конфигурация (ConfigMap)](./alertmanager-config.md)** — использование переменных в основном конфиге.
- **[Манифест StatefulSet](./alertmanager-statefulset.md)** — полная спецификация подов с монтированием секретов.
- **[Внешние менеджеры секретов](../../../../Kubernetes/Base/secrets/external_managers.md)** — SSoT по интеграции с HashiCorp Vault и External Secrets Operator.
