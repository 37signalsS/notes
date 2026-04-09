# Kubernetes Secret для Alertmanager

## Definitions

**Kubernetes Secret (Opaque)** — объект Kubernetes для хранения чувствительных данных (токены, пароли, ключи) в закодированном виде (base64). В данном tutorial используется тип `Opaque` (произвольные данные) и поле `stringData` (автоматическое кодирование из plain text).

> **См. также:** [Secrets Best Practices](../../operator/Security/secrets_best_practices.md) (SSoT) — управление секретами в Prometheus Operator

## Basic Concepts

### Типы данных в Secret

| Ключ | Формат | Назначение |
|---|---|---|
| `smtp.user` | `string` | Логин SMTP-сервера (email-адрес) |
| `smtp.password` | `string` | Пароль приложения для SMTP-аутентификации |
| `telegram.token` | `string` | Токен Telegram-бота от BotFather |
| `telegram.chat_id` | `string` | ID Telegram-чата или канала (число или `-100...`) |

### `stringData` vs `data`

| Поле | Формат ввода | Кодирование | Когда использовать |
|---|---|---|---|
| `stringData` | Plain text | Автоматическое (base64) | Удобно для манифестов — Kubernetes сам закодирует |
| `data` | Base64 | Ручное | Когда данные уже закодированы или генерируются скриптом |

### Безопасность

| Аспект | Описание |
|---|---|
| **Хранение** | Secret хранится в etcd в base64 — не шифруется по умолчанию |
| **Шифрование etcd** | Требует включения `EncryptionConfiguration` в API-сервере |
| **RBAC** | Ограничьте доступ к Secret через Role/RoleBinding в namespace `monitoring` |
| **Git** | Файл с реальными секретами **не должен** попадать в Git — используйте `.gitignore` или внешние хранилища (Vault, SOPS) |

## Practical Scenarios

### Манифест Secret

**`alertmanager-secret.yaml`**

```yaml
apiVersion: v1
kind: Secret
metadata:
  name: alertmanager-secret
  namespace: monitoring
type: Opaque
stringData:
  # -- Данные для SMTP (почта) --
  smtp.user: "your-email@example.com"
  smtp.password: "your-app-password"

  # -- Данные для Telegram --
  telegram.token: "bot-token-from-botfather"
  telegram.chat_id: "your-chat-id"
```

### Пояснения к манифесту

| Поле | Описание |
|---|---|
| `type: Opaque` | Произвольные данные (не Service Account Token, не Docker Config) |
| `stringData` | Kubernetes автоматически закодирует значения в base64 при создании объекта |
| `smtp.user` / `smtp.password` | Используются в init-container для подстановки в `alertmanager.yml.tpl` |
| `telegram.token` / `telegram.chat_id` | Токен бота и ID чата для `telegram_configs` |

### Создание через kubectl (альтернатива манифесту)

```bash
kubectl create secret generic alertmanager-secret \
  --from-literal=smtp.user='your-email@example.com' \
  --from-literal=smtp.password='your-app-password' \
  --from-literal=telegram.token='bot-token-from-botfather' \
  --from-literal=telegram.chat_id='your-chat-id' \
  -n monitoring
```

### Проверка созданного Secret

```bash
# Просмотр ключей (без значений)
kubectl get secret alertmanager-secret -n monitoring -o jsonpath='{.data.keys()}'

# Просмотр декодированного значения
kubectl get secret alertmanager-secret -n monitoring \
  -o jsonpath='{.data.smtp\.password}' | base64 -d
```

### Использование в StatefulSet

Secret монтируется в init-container через `secretKeyRef`:

```yaml
env:
  - name: SMTP_USER
    valueFrom:
      secretKeyRef:
        name: alertmanager-secret
        key: smtp.user
```

Полный манифест: [alertmanager-statefulset.md](./alertmanager-statefulset.md)

## Additional Information

- [ConfigMap-шаблон](./alertmanager-config.md) — шаблон `alertmanager.yml` с плейсхолдерами для секретов
- [Alertmanager StatefulSet](./alertmanager-statefulset.md) — подстановка секретов через init-container
- [Secrets Best Practices](../../operator/Security/secrets_best_practices.md) — управление секретами в Prometheus Operator
