# Подготовка: Секреты

Перед развертыванием необходимо создать `Secret` в Kubernetes, который будет содержать все чувствительные данные.

**`alertmanager-secret.yaml`**

```yaml
apiVersion: v1
kind: Secret
metadata:
  name: alertmanager-secret
  namespace: monitoring # Укажите ваш namespace
type: Opaque
stringData:
  # -- Данные для SMTP (почта) --
  smtp.user: "your-email@example.com"
  smtp.password: "your-app-password"

  # -- Данные для Telegram --
  telegram.token: "bot-token-from-botfather"
  telegram.chat_id: "your-chat-id" # ID чата или канала
```

> **Важно:** Замените плейсхолдеры на реальные значения.

---

## Смотрите также

- [Alertmanager ConfigMap](./03-alertmanager-config.md) — шаблон конфигурации с переменными
- [Alertmanager StatefulSet](./05-alertmanager-statefulset.md) — подстановка секретов через init-container
