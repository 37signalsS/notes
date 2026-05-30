# Grafana: Плагины

## Определения

**Плагины (Plugins)** — пакеты, расширяющие функциональность Grafana: новые источники данных, типы визуализаций и комплексные приложения.

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

- **Официальные (Grafana Labs)** — разрабатываются и поддерживаются командой Grafana.
- **Сертифицированные** — проверенные плагины от технологических партнёров.
- **Community** — плагины от сообщества (требуют тщательной проверки перед использованием).

## Практические сценарии

### Управление плагинами

#### Автоматическая установка (Provisioning)

**Docker Compose (переменные окружения):**

```yaml
# docker-compose.yml
services:
  grafana:
    image: grafana/grafana:12.x
    environment:
      - GF_INSTALL_PLUGINS=grafana-piechart-panel,volkov-echarts-panel
```

**Kubernetes (Helm `values.yaml`):**

```yaml
# values.yaml
grafana:
  plugins:
    - grafana-piechart-panel
    - volkov-echarts-panel
```

#### Ручная установка через CLI

1. **Поиск:** Найдите необходимый плагин на [официальном маркетплейсе](https://grafana.com/grafana/plugins/).
2. **Установка:**

   ```bash
   grafana-cli plugins install <plugin-id>
   ```

3. **Перезапуск сервиса:**

   ```bash
   # Docker
   docker restart grafana

   # Kubernetes
   kubectl rollout restart deployment/grafana -n monitoring
   ```

4. **Проверка:** Статус и настройки доступны в разделе **Administration → Plugins**.

## Дополнительная информация

### Важные соображения

- **Устаревшие методы:** Файловый провиженинг через `provisioning/plugins.yaml` больше не рекомендуется к использованию.
- **Безопасность:** Рекомендуется устанавливать плагины только из доверенных источников и проверять уровень поддержки (Signature).
- **Совместимость:** Перед обновлением Grafana всегда проверяйте совместимость установленных плагинов с новой мажорной версией.

**Ссылки:**

- [Официальная документация по плагинам](https://grafana.com/docs/grafana/latest/plugins/)
- [Grafana Plugins Marketplace](https://grafana.com/grafana/plugins/)
