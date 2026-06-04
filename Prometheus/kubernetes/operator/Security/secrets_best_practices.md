# Управление секретами в Prometheus Operator

## Определения

**Управление секретами** — комплекс мер по безопасному хранению и использованию чувствительных данных в экосистеме Prometheus Operator: токенов webhook, ключей маршрутизации (routing keys), паролей и TLS-сертификатов.

> **Навигация:** [Главная Security](./index.md) | [Контроль доступа](./access_control.md)

---

## Основные концепции

### Типы секретов в Prometheus Operator

| Тип | Примеры | Где используются |
|---|---|---|
| **Учётные данные получателей** | Slack webhook, PagerDuty key, SMTP password | `AlertmanagerConfig` (receivers) |
| **TLS-сертификаты** | CA, клиентские cert/key | `ServiceMonitor` (tlsConfig), Ingress TLS |
| **Учётные данные администратора** | Grafana admin user/password | Grafana Deployment |
| **Basic Auth** | Файл htpasswd, пары логин/пароль | Ingress (Prometheus / Alertmanager) |

### Механизмы хранения и безопасность

Безопасность секретов в Prometheus Operator базируется на стандартных механизмах Kubernetes, дополненных инструментами автоматизации.

- **Kubernetes Secret:** Базовый объект хранения. По умолчанию данные кодируются в base64.
- **Внешние менеджеры:** Для production рекомендуется использование внешних хранилищ (HashiCorp Vault, AWS Secrets Manager) с интеграцией через **External Secrets Operator**.
- **Шифрование и аудит:** Безопасность на уровне кластера обеспечивается шифрованием etcd и контролем доступа через RBAC.

> **Подробно:** [Безопасность Secret в Kubernetes](../../../Kubernetes/Base/secrets/security.md) — SSoT по защите и использованию секретов в кластере.

---

## Практические сценарии

### Создание секретов для алертинга

Секреты должны создаваться в том же неймспейсе, где находится ресурс `AlertmanagerConfig` (или в неймспейсе оператора, в зависимости от настроек прав).

```bash
# Создание секрета для Slack Webhook
kubectl create secret generic slack-webhook \
  --from-literal=url='https://hooks.slack.com/services/T000/B000/XXXX' \
  -n monitoring
# → secret/slack-webhook created
```

### Использование секретов в AlertmanagerConfig

Prometheus Operator позволяет ссылаться на секреты через `secretKeyRef`, что исключает попадание паролей в конфигурационные файлы.

```yaml
apiVersion: monitoring.coreos.com/v1alpha1
kind: AlertmanagerConfig
metadata:
  name: slack-config
  namespace: monitoring
spec:
  receivers:
    - name: 'slack-notifications'
      slackConfigs:
        - channel: '#alerts'
          apiURL:
            name: slack-webhook
            key: url
```

### Настройка TLS для ServiceMonitor

Для сбора метрик с защищённых эндпоинтов сертификаты монтируются в под Prometheus через секреты.

```yaml
apiVersion: monitoring.coreos.com/v1
kind: ServiceMonitor
metadata:
  name: secure-app
spec:
  endpoints:
    - port: https
      scheme: https
      tlsConfig:
        ca:
          secret:
            name: app-tls-ca
            key: ca.crt
        cert:
          secret:
            name: app-tls-client
            key: tls.crt
        keySecret:
          name: app-tls-client
          key: tls.key
```

---

## Рекомендации по безопасности

### Хранение и передача

1. **Запрет Plain Text:** Никогда не храните пароли в YAML-манифестах. Используйте `kubectl create secret` или GitOps-инструменты с шифрованием (Sealed Secrets, SOPS).
2. **Разделение секретов:** Создавайте отдельные секреты для каждого типа интеграции (Slack, PagerDuty, SMTP). Это упрощает ротацию и минимизирует радиус поражения при компрометации.
3. **RBAC:** Ограничивайте доступ к секретам в неймспейсе `monitoring`. Только оператор и администраторы должны иметь право на чтение.

### Эксплуатация

1. **Ротация:** Установите график ротации секретов (например, раз в 90 дней). Автоматизируйте процесс через Vault или внешние менеджеры.
2. **Мониторинг доступа:** Включите аудит-логирование Kubernetes API для отслеживания обращений к объектам `secrets`.
3. **Использование `secretKeyRef`:** В CRD Prometheus Operator всегда предпочитайте ссылки на секреты прямому указанию значений.

---

## Дополнительная информация

> **См. также:**
>
> - [Безопасность Secret в Kubernetes](../../../Kubernetes/Base/secrets/security.md) — общие принципы защиты
> - [Внешние менеджеры секретов](../../../Kubernetes/Base/secrets/external_managers.md) — Vault, External Secrets
> - [Network Policies](./access_control.md) — ограничение сетевого доступа к компонентам
