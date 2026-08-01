# Секреты Kubernetes для Alertmanager

## Определения

**Kubernetes Secret (Opaque)** — объект для безопасного хранения конфиденциальной информации (паролей, токенов, ключей доступа) в кластере. В данном руководстве секреты используются для передачи учетных данных почтовых серверов и Telegram-ботов в процесс Alertmanager без их раскрытия в манифестах конфигурации.

> **См. также:** [Управление секретами в Prometheus Operator](../../operator/Security/secrets_best_practices.md).

---

## Основные концепции

### Типы данных в секрете

| Ключ | Формат | Назначение |
| :--- | :--- | :--- |
| `smtp.user` | `string` | Адрес электронной почты для авторизации на SMTP-сервере. |
| `smtp.password` | `string` | Пароль или токен приложения для отправки почты. |
| `telegram.token` | `string` | API-токен Telegram-бота, полученный от BotFather. |
| `telegram.chat_id` | `string` | Идентификатор чата или канала для получения уведомлений. |

### Безопасность и хранение

-   **Base64:** Kubernetes Secret кодирует данные в base64, что не является шифрованием. Для реальной защиты требуется шифрование etcd.
-   **RBAC:** Доступ к секретам должен быть ограничен только для системных компонентов (Оператор, Alertmanager) и администраторов.
-   **GitOps:** Никогда не храните манифесты с реальными секретами в публичных репозиториях. Используйте инструменты шифрования (Sealed Secrets, SOPS) или внешние хранилища (Vault).

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
stringData:
  smtp.user: "alerting@example.com"
  smtp.password: "secure-app-password"
  telegram.token: "123456:ABC-DEF-GHI"
  telegram.chat_id: "-100123456789"
```

### Создание секрета через CLI (kubectl)

Альтернативный способ без создания промежуточных файлов:

```bash
kubectl create secret generic alertmanager-secret \
  --from-literal=smtp.user='admin@example.com' \
  --from-literal=smtp.password='my-password' \
  --from-literal=telegram.token='bot-token' \
  --from-literal=telegram.chat_id='-123456' \
  -n monitoring
```

### Использование в StatefulSet

В современной архитектуре секреты подключаются напрямую в переменные окружения контейнера:

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

- **[Конфигурация (ConfigMap)](./alertmanager-config.md)** — использование переменных `${VAR}` в конфиге.
- **[Манифест StatefulSet](./alertmanager-statefulset.md)** — описание внедрения переменных в под.
- **[Внешние менеджеры секретов](../../../Kubernetes/Base/secrets/external_managers.md)** — SSoT по интеграции с Vault.
- **[Reliability Scores](../../../../GEMINI.md)** — методология оценки достоверности (Score: 10).
