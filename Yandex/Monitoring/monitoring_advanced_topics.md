# Yandex Monitoring: Дополнительные темы

## 1. Интеграция с Grafana

### Вариант 1: Yandex Monitoring как источник данных

1. Установите плагин Yandex Monitoring
2. Добавьте datasource с IAM-аутентификацией
3. Используйте Query Editor для запросов

### Вариант 2: Managed Service for Prometheus

1. Разверните MSP в Yandex Cloud
2. Настройте скрейпинг метрик
3. Подключите Prometheus как datasource в Grafana

## 2. Best Practices

### Метрики

- Следуйте методологии **RED** (Rate, Errors, Duration) для сервисов
- Используйте **USE** (Utilization, Saturation, Errors) для инфраструктуры
- Избегайте высокой кардинальности меток

### Алерты

- Настраивайте многоуровневую эскалацию (warning → critical → page)
- Добавляйте контекст в уведомления (сервис, окружение, ссылка на дашборд)
- Регулярно пересматривайте пороги и окна

### Дашборды

- Создавайте иерархию: общий → сервис → хост
- Используйте переменные для фильтрации
- Документируйте метрики и пороги

## 3. Актуальная информация (2025–2026)

- **Q4 2025:** Добавлена вкладка Alerts для Managed Service for Prometheus
- **Q4 2025:** Детальные метрики диска для Managed Databases
- **Мониторинг по умолчанию:** все сервисы YC публикуют метрики автоматически

## Связанные документы

- **[Основные концепции](./monitoring_concepts.md)** — определения и модель данных
- **[Практические сценарии](./monitoring_practical_scenarios.md)** — отправка метрик, алертинг, дашборды
- **[Compute Cloud](../Compute-Cloud.md)** — метрики ВМ
- **[Managed Databases](../Managed-Databases.md)** — метрики БД
- **[VPC](../VPC.md)** — сетевые метрики
- **[Prometheus](../../Prometheus/overview.md)** — альтернативная система мониторинга
- **[Grafana](../../Grafana/grafana_overview.md)** — визуализация и дашборды
- **[Alertmanager](../../Prometheus/alertmanager.md)** — управление оповещениями
- **[Kubernetes](../../Kubernetes/)** — метрики кластеров и подов
