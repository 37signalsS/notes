# Grafana: Плагины

## Определения

**Плагины (Plugins)** — модули расширения, которые позволяют добавлять в Grafana новые источники данных, типы визуализаций и комплексные приложения. Архитектурно плагины могут быть чисто фронтенд-компонентами (React) или включать бэкенд-часть (бинарный файл на Go).

**Текущая версия (июль 2026):** Grafana 13.x (рекомендуется 13.1.x)

**Связанные темы:**

- [Обзор Grafana](./grafana_overview.md) — общая информация о платформе
- [Провиженинг](./grafana_provisioning.md) — автоматизация установки плагинов
- [Источники данных](./grafana_datasources.md) — плагины типа Data Source

## Базовые концепции

### Типы плагинов

| Тип | Назначение | Примеры |
| :--- | :--- | :--- |
| **Data Source** | Подключение новых баз данных и API | Prometheus, ClickHouse, Zabbix, BigQuery |
| **Panel** | Новые способы визуализации данных | Apache ECharts, Candlestick, Flowchart |
| **App** | Полнофункциональные расширения (UI + API + Dashboards) | Kubernetes App, Zabbix App, SageMaker |

### Безопасность и подпись (Plugin Signing)

В Grafana 13.x строгая политика безопасности требует наличия цифровой подписи для всех плагинов.

**Уровни подписи:**
- **Grafana Labs**: Плагины, разработанные командой Grafana.
- **Commercial**: Плагины от официальных партнеров (Enterprise).
- **Community**: Плагины, проверенные сообществом и опубликованные на маркетплейсе.
- **Unsigned**: Неподписанные или модифицированные плагины (требуют явного разрешения).

**Работа с неподписанными плагинами:**
Для использования приватных или разрабатываемых плагинов необходимо добавить их ID в переменную окружения или конфигурацию:
```bash
GF_PLUGINS_ALLOW_UNSIGNED_PLUGINS=my-custom-plugin,another-plugin
```

## Практические сценарии

### Управление через CLI (grafana-cli)

Инструмент командной строки для управления жизненным циклом плагинов. После каждой операции требуется перезапуск Grafana.

```bash
# Поиск плагина (выводит список всех доступных)
grafana-cli plugins list-remote

# Установка конкретной версии
grafana-cli plugins install grafana-piechart-panel 1.6.2

# Обновление всех установленных плагинов
grafana-cli plugins update-all

# Проверка установленных плагинов
grafana-cli plugins ls

# Удаление плагина
grafana-cli plugins uninstall <plugin-id>
```

### Автоматизированная установка (Provisioning)

#### Docker Compose

Наиболее частый способ для контейнеризированных сред.

```yaml
services:
  grafana:
    image: grafana/grafana:13.1.1
    environment:
      - GF_INSTALL_PLUGINS=grafana-clock-panel,alexanderzobnin-zabbix-app
      - GF_PLUGINS_ALLOW_UNSIGNED_PLUGINS=my-local-datasource
```

#### Kubernetes (Helm)

В современных инсталляциях (v13+) рекомендуется использовать `Git Sync` для дашбордов, но сами плагины устанавливаются через `initContainers` или параметры чарта.

```yaml
# values.yaml
grafana:
  plugins:
    - grafana-piechart-panel
    - grafana-worldmap-panel
```

### Настройка приватного репозитория

Если Grafana находится в закрытом контуре без доступа к интернету, можно развернуть локальный сервер плагинов.

**Конфигурация `grafana.ini`:**
```ini
[plugins]
plugin_repo_url = https://my-internal-repo.example.com/plugins
```

## Дополнительная информация

### Особенности бэкенд-плагинов

Плагины с бэкенд-компонентом (например, ClickHouse или SQL Server) запускаются как отдельные процессы.
- **Производительность**: Бэкенд-плагины могут потреблять значительную память.
- **Логирование**: Ошибки таких плагинов отображаются в основном логе Grafana с префиксом `plugin.id`.
- **Архитектура**: Требуют наличия бинарного файла, совместимого с архитектурой ОС (amd64, arm64).

### Рекомендации по эксплуатации

- **Версионность**: При обновлении Grafana с v12 на v13 проверьте совместимость через `Suggested Upgrades` в UI.
- **Мониторинг**: Используйте встроенные метрики (`/metrics`) для отслеживания здоровья процессов бэкенд-плагинов.
- **Очистка**: Удаляйте неиспользуемые плагины, так как они могут замедлять время старта Grafana.

**Ссылки:**

- [Grafana Plugins Marketplace](https://grafana.com/grafana/plugins/) — каталог плагинов
- [Документация по подписыванию плагинов](https://grafana.com/docs/grafana/latest/developers/plugins/sign-a-plugin/)
- [Grafana GitHub](https://github.com/grafana/grafana) — репозиторий проекта
