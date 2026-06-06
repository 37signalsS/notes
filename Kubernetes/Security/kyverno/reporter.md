# Policy Reporter

## Определения

**Policy Reporter** — специализированное приложение для визуализации и мониторинга отчетов безопасности в Kubernetes. Оно предоставляет графический интерфейс, генерирует метрики для систем мониторинга и отправляет уведомления о нарушениях политик.

---

## Основные концепции

### Возможности инструмента

| Компонент | Назначение |
|-----------|------------|
| **Web UI** (User Interface, пользовательский интерфейс) | Панель управления для поиска, фильтрации и группировки отчетов по категориям. |
| **Метрики** | Формирование данных для Prometheus и Grafana (система визуализации метрик). |
| **REST API** (Representational State Transfer Application Programming Interface) | Программный интерфейс для извлечения данных внешними системами. |
| **Централизация** | Сбор отчетов из всех пространств имен (namespaces) кластера в единую точку. |
| **Уведомления** | Рассылка алертов в Slack, Telegram, Microsoft Teams, Discord. |

### Архитектура взаимодействия

Данные передаются по следующей цепочке:

1. **Kyverno** генерирует отчеты в формате Custom Resources (пользовательские ресурсы) в кластере.
2. **Policy Reporter** (Core компонент) считывает эти ресурсы через Kubernetes API.
3. **Core компонент** распределяет данные:
   - В **UI** для отображения пользователю.
   - В **Prometheus** в виде числовых метрик.
   - Во внешние системы через **Webhook** (вебхуки) или мессенджеры.

---

## Практические сценарии

### Установка через Helm

```bash
# Добавление репозитория
helm repo add policy-reporter https://kyverno.github.io/policy-reporter
# → "policy-reporter" has been added to your repositories

helm repo update
# → Hang tight while we grab the latest from your chart repositories...

# Установка с базовыми настройками (UI и метрики включены)
helm install policy-reporter policy-reporter/policy-reporter \
  --namespace policy-reporter \
  --create-namespace \
  --set ui.enabled=true \
  --set ui.plugins.kyverno=true \
  --set metrics.enabled=true \
  --set prometheus.enabled=true
# → NAME: policy-reporter, STATUS: deployed
```

### Настройка уведомлений

Пример конфигурации `values.yaml` (Yet Another Markup Language манифест) для отправки алертов:

```yaml
# Уведомления в Slack
slack:
  enabled: true
  webhook: "https://hooks.slack.com/services/XXX/YYY/ZZZ"
  minimumPriority: "high"

# Уведомления в Telegram
telegram:
  enabled: true
  token: "BOT_TOKEN" # Токен бота
  chatID: "CHAT_ID"  # ID чата или канала
  minimumPriority: "critical"

# Фильтрация по пространствам имен
filter:
  namespaces:
    include: ["production", "staging"]
    exclude: ["kube-system"]
```

### Проверка работоспособности

```bash
# Проверка состояния компонентов
kubectl get pods -n policy-reporter
# → NAME                                READY   STATUS    RESTARTS   AGE
# → policy-reporter-5f8c9d7b9c-abc12    1/1     Running   0          5m
# → policy-reporter-ui-6d9f8e7c8d-def34 1/1     Running   0          5m

# Доступ к интерфейсу (проброс портов)
kubectl port-forward svc/policy-reporter-ui -n policy-reporter 8080:80
# → Forwarding from 127.0.0.1:8080 -> 80
```

После выполнения команды интерфейс будет доступен по адресу `http://localhost:8080`.

### Использование REST API

```bash
# Получение всех отчетов в формате JSON
curl http://localhost:8080/api/v1/policy-reports
# → [{"name":"pol-rep-1", "namespace":"default", "results": [...]}]

# Получение только критических нарушений
curl "http://localhost:8080/api/v1/policy-reports?result=fail"
```

---

## Дополнительная информация

### Мониторинг ресурсов (Производительность)

| Ресурс | Потребление (ориентировочно) |
|--------|-----------------------------|
| **RAM** (Random Access Memory, оперативная память) | 150–250 MB |
| **CPU** (Central Processing Unit, центральный процессор) | 0.1–0.2 ядра |

Инструмент эффективно работает в кластерах до 200–300 пространств имен. При большем масштабе рекомендуется увеличить интервал сканирования.

### Поиск и устранение неисправностей (Troubleshooting)

| Проблема | Решение |
|----------|---------|
| Интерфейс не отображает данные | Проверьте права ClusterRole для Policy Reporter (нужен доступ к `policyreports`). |
| Метрики отсутствуют в Prometheus | Убедитесь, что параметр `metrics.enabled` установлен в `true`. |
| Уведомления не приходят | Проверьте валидность URL (Uniform Resource Locator) вебхука и сетевую доступность. |

### Полезные ссылки

- [Отчеты Kyverno](./reports.md) — структура и типы генерируемых данных.
- [Установка Kyverno](./install.md) — настройка основного движка политик.
- [Официальный репозиторий](https://github.com/kyverno/policy-reporter) — документация и исходный код.
