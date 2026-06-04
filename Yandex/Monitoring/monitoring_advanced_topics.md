# Yandex Monitoring: Дополнительные темы

## 1. Определения

**Managed Service for Prometheus** — управляемый сервис Prometheus в Yandex Cloud. Совместим с open-source Prometheus, обеспечивает сбор метрик через ServiceMonitors и PodMonitors в Kubernetes.

Методологии мониторинга (RED, USE) являются фундаментальными подходами к выбору метрик. Их подробное описание приведено в файле **[Методологии мониторинга](../../Concepts/Observability_and_Monitoring/monitoring_methodologies.md)**.

## 2. Базовые концепции

### Интеграция с Grafana

**Вариант 1: Yandex Monitoring как источник данных**

1. Установите плагин Yandex Monitoring в Grafana.
2. Добавьте datasource с IAM-аутентификацией (сервисный аккаунт YC).
3. Используйте Query Editor для построения запросов к метрикам YC.

**Вариант 2: Managed Service for Prometheus**

1. Разверните MSP в Yandex Cloud.
2. Настройте скрейпинг метрик через ServiceMonitor/PodMonitor.
3. Подключите Prometheus как datasource в Grafana (PromQL).

**Вариант 3: Комбинированный**

- Yandex Monitoring для метрик облачных сервисов (CPU, память, диск ВМ).
- Prometheus для кастомных метрик приложений.
- Единый дашборд в Grafana с несколькими datasource.

### Хранение метрик

| Параметр | Значение | Примечание |
| :--- | :--- | :--- |
| **Хранение** | до 13 месяцев | Стандартный тариф |
| **Агрегация** | автоматическая | Детальные → часовые → дневные |
| **Retention** | настраиваемый | Через политики хранения |

### Безопасность

- **IAM-аутентификация** — через сервисные аккаунты YC.
- **Folder-level доступ** — метрики изолированы по каталогам.
- **Audit logging** — все операции записываются в Cloud Logging.
- **Шифрование** — данные шифруются at rest (KMS).

## 3. Практические сценарии

### Настройка сервисного аккаунта для Grafana

```bash
# Создание сервисного аккаунта
yc iam service-account create --name grafana-reader

# Назначение роли monitoring.viewer
yc resource-manager folder add-access-binding --id <folder_id> \
  --role monitoring.viewer \
  --subject serviceAccount:<sa_id>

# Создание статического ключа
yc iam key create --service-account-name grafana-reader \
  --output grafana-key.json
```

### Миграция с Prometheus на Yandex Monitoring

- Пользовательские метрики → API timeseries:write.
- ServiceMonitors → Managed Service for Prometheus.
- Alertmanager → встроенный алертинг Monitoring.
- Grafana datasource: Prometheus → Yandex Monitoring plugin.

## 4. Дополнительная информация

### Рекомендации (Best Practices)

**Метрики:**

- Используйте методологию RED для сервисов и USE для инфраструктуры.
- Избегайте высокой кардинальности меток (< 1000 уникальных значений на метку).

**Алерты:**

- Настраивайте многоуровневую эскалацию (warning → critical).
- Добавляйте контекст в уведомления (сервис, окружение, ссылка на дашборд).
- Регулярно пересматривайте пороги и используйте `for` для фильтрации шума.

**Дашборды:**

- Создавайте иерархию: общий вид → конкретный сервис → хост.
- Используйте переменные для динамической фильтрации.

### Актуальная информация (2025–2026)

- Добавлена вкладка Alerts для Managed Service for Prometheus (Q4 2025).
- Детальные метрики диска для Managed Databases (Q4 2025).
- Все сервисы YC публикуют метрики автоматически (мониторинг по умолчанию).

## Связанные документы

- **[Основные концепции](./monitoring_concepts.md)** — определения и модель данных
- **[Практические сценарии](./monitoring_practical_scenarios.md)** — отправка метрик, алертинг, дашборды
- **[Prometheus](../../Prometheus/overview.md)** — альтернативная система мониторинга
