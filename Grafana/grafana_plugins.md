# Grafana: Плагины

## Определения

**Плагины (Plugins)** — пакеты, расширяющие функциональность Grafana: новые источники данных, типы визуализаций, комплексные приложения.

**Текущая версия (март 2026):** Grafana 12.x поддерживает плагины v10.x+

**Связанные темы:**
- [Обзор Grafana](./grafana_overview.md) — общая информация о платформе
- [Провиженинг](./grafana_provisioning.md) — автоматизация установки плагинов
- [Источники данных](./grafana_datasources.md) — плагины типа Data Source

## Базовые концепции

### Типы плагинов

| Тип | Назначение | Примеры |
| :--- | :--- | :--- |
| **Data Source** | Новые источники данных | Zabbix, ClickHouse, GitHub, Azure Monitor |
| **Panel** | Новые типы визуализаций | Pie Chart, Worldmap, Histogram |
| **App** | Комплексные решения | Zabbix App, Kubernetes App, IoT App |

### Категории плагинов

- **Официальные (Grafana Labs)** — поддерживаются командой Grafana
- **Сертифицированные** — проверенные партнёрами
- **Community** — от сообщества (требуют ручной проверки)

## Практические сценарии

### Управление плагинами

#### Автоматическая установка (Provisioning)

**Docker (переменные окружения):**

```yaml
# docker-compose.yml
services:
  grafana:
    image: grafana/grafana:11.4.0
    environment:
      - GF_INSTALL_PLUGINS=grafana-piechart-panel,volkov-echarts-panel
```

**Kubernetes (Helm):**

```yaml
# values.yaml
grafana:
  plugins:
    - grafana-piechart-panel
    - volkov-echarts-panel
```

#### Ручная установка

1. **Поиск:** Найдите плагин на [маркетплейсе](https://grafana.com/grafana/plugins/).
2. **Установка:**

   ```bash
   grafana-cli plugins install <plugin-id>
   ```

3. **Перезапуск:**

   ```bash
   # Docker
   docker restart grafana

   # Kubernetes
   kubectl rollout restart deployment/grafana -n monitoring
   ```

4. **Проверка:** **Administration → Plugins**.

## Дополнительная информация

### Важные замечания

- **Файловый провиженинг** через `provisioning/plugins.yaml` — устаревший метод, не рекомендуется.
- **Безопасность:** Проверяйте плагины community перед установкой в production.
- **Совместимость:** Убедитесь, что плагин совместим с вашей версией Grafana.

Подробная информация доступна в [документации по плагинам](https://grafana.com/docs/grafana/latest/plugins/) и на [Grafana Plugins Marketplace](https://grafana.com/grafana/plugins/).
