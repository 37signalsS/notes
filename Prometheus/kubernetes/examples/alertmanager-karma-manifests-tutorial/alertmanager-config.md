# Конфигурация Alertmanager: ConfigMap и маршрутизация

## Определения

**ConfigMap конфигурации Alertmanager** — ресурс Kubernetes, хранящий файл `alertmanager.yml`. Начиная с версии 0.27+, Alertmanager поддерживает прямое использование переменных окружения в конфигурационном файле, что позволяет избежать хранения чувствительных данных (паролей, токенов) в ConfigMap и обеспечивает безопасность при использовании GitOps.

> **См. также:** [Полная конфигурация Alertmanager](../../../alertmanager.md#конфигурация-alertmanageryml).

## Предварительные требования

- Namespace `monitoring` создан и активен.
- Alertmanager развёрнут через [StatefulSet](./alertmanager-statefulset.md) и доступен в namespace.
- Создан [Kubernetes Secret](./secrets.md) с реальными значениями для переменных окружения (`SMTP_USER`, `SMTP_PASSWORD`, `TELEGRAM_TOKEN`, `TELEGRAM_CHAT_ID`).
- Для валидации требуется установленный `kubectl` с доступом к кластеру и `amtool` (входит в состав образа Alertmanager).

## Основные концепции

### Использование переменных окружения

В файле конфигурации вместо реальных значений используются плейсхолдеры в формате `${VARIABLE_NAME}`. Значения этих переменных передаются в под Alertmanager через Kubernetes Secret.

| Компонент | Роль |
| :--- | :--- |
| **ConfigMap** | Хранит структуру `alertmanager.yml` с ссылками на переменные. Безопасен для Git. |
| **Kubernetes Secret** | Содержит реальные токены и пароли. |
| **Alertmanager** | Считывает переменные окружения при запуске (требуется флаг `--config.expand-external-variables`). |

### Структура файла конфигурации

Файл `alertmanager.yml` состоит из нескольких логических блоков, обрабатываемых последовательно.

1.  **Global:** Глобальные настройки (SMTP-серверы, интервалы, прокси, таймауты).
2.  **Route:** Дерево маршрутизации, определяющее, куда отправлять конкретные алерты.
3.  **Inhibit Rules:** Правила подавления, позволяющие отключать уведомления при наличии связанных критических алертов.
4.  **Receivers:** Описание способов доставки (Telegram, Email, Webhooks, PagerDuty).
5.  **Templates:** Пути к файлам визуального оформления уведомлений.

Детальное описание каждого раздела и допустимых параметров — в [Полной конфигурации Alertmanager](../../../alertmanager.md#конфигурация-alertmanageryml).

### Дерево маршрутизации и matchers

Маршрутизация работает как дерево: каждый алерт проверяется сверху вниз до первого совпадения. Если `continue: true`, проверка продолжается дальше.

- **`matchers`** — условия на основе меток алерта. Поддерживается старый формат `severity="critical"` и новый (v0.27+) с явным типом: `severity=~"critical|warning"`.
- **`mute_time_intervals`** — ссылка на именованный интервал в блоке `time_intervals`, позволяющая автоматически заглушать уведомления в определенные периоды (например, ночные дежурства).
- **`continue: true`** — не останавливается на совпадении, а продолжает проверять следующие правила. Используется, когда один алерт должен попасть в несколько каналов.

### Правила подавления (inhibit_rules)

Правила подавления позволяют отключать менее значимые алерты при наличии более критичных, сокращая шум в чатах. Каждое правило содержит:

- **`source_matchers`** — метки родительского (критичного) алерта.
- **`target_matchers`** — метки дочернего алерта, который нужно заглушить.
- **`equal`** — список меток, которые должны совпадать у source и target для срабатывания правила.

### Получатели (receivers)

Каждый receiver описывает конечный канал доставки. Внутри receiver могут быть:

- **Email:** `email_configs` — требуется настройка SMTP в глобальном блоке.
- **Telegram (нативный):** `telegram_configs` — доступен начиная с v0.24, использует bot_token и chat_id.
- **Slack:** `slack_configs` — через Webhook URL.
- **Webhook:** `webhook_configs` — универсальный механизм для любых HTTP-сервисов.
- **PagerDuty:** `pagerduty_configs` — интеграция с ключом сервиса.
- **Blackhole:** `blackhole_configs: [{}]` — «чёрная дыра» для тестовых или заглушаемых маршрутов.

### Шаблоны (templates)

Go-шаблоны форматируют текст уведомлений для конкретных каналов. Подключаются через блок `templates` и вызываются через `{{ template "имя" . }}`. Детали синтаксиса — в [Шаблоны сообщений](./alertmanager-templates.md).

### GitOps-паттерн: ConfigMap + Secret + StatefulSet

Современный production-паттерн безопасного развёртывания:

1. **ConfigMap** хранит логику маршрутизации и плейсхолдеры `${VAR}`. Хранится в Git.
2. **Secret** хранит реальные токены/пароли. Создаётся через `kubectl create secret` или External Secrets Operator.
3. **StatefulSet** монтирует ConfigMap и пробрасывает Secret как переменные окружения через `env.valueFrom.secretKeyRef`.
4. **Флаг `--config.expand-external-variables`** активирует подстановку ENV при старте пода.

Такой подход исключает хранение секретов в Git и позволяет использовать стандартные CI/CD-пайплайны.

## Практические сценарии

### Манифест ConfigMap

Пример конфигурации с нативной поддержкой переменных окружения и современной нотацией матчеров.

**`alertmanager-config.yaml`**

```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: alertmanager-config
  namespace: monitoring
data:
  alertmanager.yml: |
    global:
      smtp_smarthost: 'smtp.example.com:587'
      smtp_from: '${SMTP_USER}'
      smtp_auth_username: '${SMTP_USER}'
      smtp_auth_password: '${SMTP_PASSWORD}'

    route:
      group_by: ['alertname', 'job']
      group_wait: 30s
      group_interval: 5m
      repeat_interval: 12h
      receiver: 'default-receiver'
      routes:
        - receiver: 'telegram-receiver'
          matchers:
            - severity =~ "critical|warning"
          continue: true
        - receiver: 'email-receiver'
          matchers:
            - severity = "critical"

    # Правила подавления (например, не слать алерты о подах, если нода лежит)
    inhibit_rules:
      - source_matchers: [severity="critical", alertname="NodeDown"]
        target_matchers: [severity="warning"]
        equal: ['node', 'instance']

    receivers:
      - name: 'default-receiver'
        blackhole_configs:
          - {}

      - name: 'email-receiver'
        email_configs:
          - to: 'admin@example.com'
            send_resolved: true
            headers:
              subject: 'K8s-Alert: {{ .GroupLabels.alertname }}'

      - name: 'telegram-receiver'
        telegram_configs:
          - bot_token: '${TELEGRAM_TOKEN}'
            chat_id: ${TELEGRAM_CHAT_ID}
            parse_mode: 'HTML'
            message: '{{ template "telegram.default.html" . }}'

    templates:
      - '/etc/alertmanager/templates/*.tmpl'
```

### Применение и первичная валидация

```bash
# Применение ConfigMap
kubectl apply -f alertmanager-config.yaml
# → configmap/alertmanager-config created

# Проверка создания
kubectl get configmap -n monitoring alertmanager-config -o yaml
# → data:
# →   alertmanager.yml: |
# →     global:
# →       smtp_smarthost: 'smtp.example.com:587'...

# Проверка, что ConfigMap смонтирован в StatefulSet
kubectl get statefulset -n monitoring alertmanager
# → NAME        READY   AGE
# → alertmanager 3/3     10m
```

### Проверка конфигурации изнутри пода

```bash
# Получение имени пода
POD=$(kubectl get pods -n monitoring -l app=alertmanager -o jsonpath='{.items[0].metadata.name}')

# Просмотр смонтированного файла
kubectl exec -n monitoring $POD -c alertmanager -- cat /etc/alertmanager/alertmanager.yml
# → содержимое должно совпадать с ожидаемым (с подставленными ENV)

# Проверка логов на ошибки парсинга
kubectl logs -n monitoring $POD -c alertmanager | grep -i "config\|error\|parse"
# → (пусто, если ошибок нет)

# Проверка статуса пода
kubectl get pod -n monitoring $POD -o wide
# → NAME            READY   STATUS    RESTARTS   AGE   IP           NODE
# → alertmanager-0  2/2     Running   0          10m   10.244.x.x  <node>
```

### Обнаружение текущей конфигурации

```bash
# Получение активной конфигурации через API
kubectl exec -n monitoring $POD -c alertmanager -- curl -s http://localhost:9093/api/v1/status/config
# → YAML-фрагмент текущей конфигурации

# Или через amtool
kubectl exec -n monitoring $POD -c alertmanager -- amtool config routes show
# → Визуализированное дерево маршрутизации
```

### Горячая перезагрузка

Alertmanager поддерживает перезагрузку конфигурации без перезапуска пода.

```bash
# Через SIGHUP
kubectl exec -n monitoring $POD -c alertmanager -- kill -SIGHUP 1
# → (без вывода; проверяем логи)

# Через HTTP API
kubectl exec -n monitoring $POD -c alertmanager -- curl -X POST http://localhost:9093/-/reload
# → "Alert configuration reloaded"
```

> **Примечание:** При обновлении ConfigMap через `kubectl apply` поды **не перезапускаются автоматически**. Используйте `kubectl rollout restart statefulset/alertmanager -n monitoring` для последовательного обновления подов с новой конфигурацией.

### Управление через amtool

Утилита `amtool` входит в состав дистрибутива Alertmanager и позволяет автоматизировать диагностику и операционную работу. Синтаксическая валидация конфигурации описана в [Валидация конфигурации](#валидация-конфигурации).

```bash
# Визуализация дерева маршрутизации
kubectl exec -n monitoring $POD -c alertmanager -- amtool config routes show
# → route <receiver=default>
# →   ├── severity="critical" → pagerduty-critical
# →   └── severity="warning" → slack-warnings

# Создание сайленса (временное отключение алерта)
kubectl exec -n monitoring $POD -c alertmanager -- \
  amtool silence add alertname=NodeDown --comment="Patching" --duration=2h
# → silence_id: 12345678-1234-1234-1234-123456789012

# Просмотр активных алертов
kubectl exec -n monitoring $POD -c alertmanager -- amtool alert
# → alertname           ...  startedAt              labels
# → NodeDown            ...  2026-09-17T08:00:00Z  {node="worker-1",...}
```

Полный справочник команд — в [Полной конфигурации Alertmanager](../../../alertmanager.md#управление-через-cli-amtool).

### Валидация конфигурации

После применения ConfigMap рекомендуется проверить синтаксис внутри пода:

```bash
kubectl exec -n monitoring alertmanager-0 -c alertmanager -- \
  amtool check-config /etc/alertmanager/alertmanager.yml
```

### Устранение неисправностей

| Симптом | Возможная причина | Диагностика и решение |
| :--- | :--- | :--- |
| Pod в CrashLoopBackOff | Ошибка синтаксиса YAML или неверный флаг `--config.expand-external-variables` | `kubectl logs -n monitoring <pod> -c alertmanager`; проверить YAML и версию Alertmanager. |
| Pod в ImagePullBackOff | Неверный тег образа или недоступность реестра | `kubectl describe pod -n monitoring <pod>` → Events; проверить `imagePullPolicy`. |
| `amtool check-config` возвращает ошибку | Неподдерживаемая директива или неверный формат матчеров | Проверить версию Alertmanager (`kubectl exec ... -- alertmanager --version`) и синтаксис matchers. |
| ConfigMap не применяется к поду | ConfigMap смонтирован, но под не перезапущен | `kubectl rollout restart statefulset/alertmanager -n monitoring`. |
| Переменные окружения не подставляются | Отсутствует флаг `--config.expand-external-variables` | Проверить `args` в StatefulSet; убедиться, что Secret смонтирован как ENV. |
| Алерты не доставляются в Telegram | Неверный `bot_token` или `chat_id` | `kubectl logs -n monitoring <pod> -c alertmanager | grep -i telegram`; проверить токен через BotFather. |
| Дублирование алертов в Slack/Email | Неправильная группировка или несколько Alertmanager без кластеризации | Проверить `group_by` и наличие `--cluster.listen-address` в StatefulSet. |

### Рекомендации

- **Версионирование:** Храните `alertmanager-config.yaml` в Git-репозитории. Используйте `kubectl apply --dry-run=server -f alertmanager-config.yaml` в CI для проверки синтаксиса.
- **Immutable ConfigMap:** Для production рассмотрите `immutable: true` в metadata ConfigMap. При изменении конфигурации создавайте новый ConfigMap (например, `alertmanager-config-v2`) и обновляйте StatefulSet.
- **Labels:** Добавляйте стандартные labels в ConfigMap:
  ```yaml
  metadata:
    labels:
      app.kubernetes.io/name: alertmanager
      app.kubernetes.io/component: config
  ```
- **External Variables:** Используйте переменные окружения только для чувствительных данных (токены, пароли). Остальную конфигурацию храните прямо в ConfigMap.
- **Версия Alertmanager:** Перед обновлением образа ознакомьтесь с [CHANGELOG](https://github.com/prometheus/alertmanager/releases) и проверяйте совместимость `alertmanager.yml` с новой версией.
- **Тестирование маршрутизации:** Используйте [Routing Tree Editor](https://www.prometheus.io/webtools/alerting/routing-tree-editor/) для отладки дерева маршрутизации.

### Очистка ресурсов

```bash
# Удалить ConfigMap
kubectl delete configmap alertmanager-config -n monitoring

# Проверить отсутствие
kubectl get configmap -n monitoring -l app=alertmanager
# → (должен вернуть пустой результат)

# Примечание: Secret и StatefulSet не удаляются при удалении ConfigMap.
# Удалите их отдельно, если нужно полностью очистить namespace:
kubectl delete statefulset alertmanager -n monitoring
kubectl delete secret alertmanager-secret -n monitoring
```

## Дополнительная информация

- **[Шаблоны сообщений](./alertmanager-templates.md)** — Go-шаблоны для форматирования.
- **[Манифест StatefulSet](./alertmanager-statefulset.md)** — настройка запуска Alertmanager с флагами расширения переменных.
- **[Секреты Kubernetes](./secrets.md)** — подготовка учетных данных для ENV-подстановки.
- **[Alertmanager — управление оповещениями](../../../alertmanager.md)** — архитектура, конвейер обработки, HA-кластеризация, CLI (`amtool`), Telegram-интеграция, рекомендации SRE.
- **[Готовые шаблоны ConfigMap](../../../../Kubernetes/Base/ConfigMap/practical_templates.md)** — immutable ConfigMap, best practices монтирования, большие конфигурации.
