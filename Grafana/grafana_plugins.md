# Grafana: Плагины

## Определения

**Плагины (Plugins)** — модули расширения, позволяющие добавлять в Grafana новые источники данных, типы визуализаций (панели) и комплексные приложения (Apps).

**Версия (2026):** Grafana 13.x (переход на React 19, строгий RBAC).

**Архитектурные компоненты:**
*   **Frontend-часть:** Интерфейс плагина на React. Начиная с v13, требуется совместимость с React 19.
*   **Backend-часть:** Бинарный файл на языке Go (опционально), выполняющий запросы к данным или сложную обработку на стороне сервера.

## Базовые концепции

### Типы плагинов

| Тип | Назначение | Примеры |
| :--- | :--- | :--- |
| **Data Source** | Подключение баз данных, API и систем мониторинга. | Prometheus, Loki, ClickHouse, Zabbix. |
| **Panel** | Новые способы визуализации (графики, диаграммы). | Apache ECharts, Clock Panel, Flowchart. |
| **App** | Пакетные решения: UI + Dashboards + Data Sources. | Kubernetes App, Zabbix App, SageMaker. |

### Безопасность и подпись (Plugin Signing)

В Grafana 13.x действует политика обязательной цифровой подписи. Неподписанные плагины блокируются ядром системы.

**Уровни подписи:**
1.  **Grafana Labs:** Официальные плагины от разработчиков Grafana.
2.  **Commercial:** Плагины для Enterprise-версий.
3.  **Community:** Плагины от сообщества, прошедшие проверку безопасности Grafana Labs.
4.  **Unsigned:** Локальные разработки или модифицированные плагины.

**Загрузка неподписанных плагинов:**
Для разрешения загрузки необходимо явно указать ID плагинов (через запятую) в `grafana.ini` или переменных окружения.
```ini
# grafana.ini
[plugins]
allow_loading_unsigned_plugins = custom-datasource-id,my-panel-id
```
**Важно:** Использование значения `true` вместо конкретных ID не поддерживается из соображений безопасности.

## Практические сценарии

### Управление через CLI (grafana-cli)

Основной инструмент для управления плагинами в standalone-инсталляциях. Требует перезапуска сервиса после изменений.

```bash
# Поиск плагина в официальном каталоге
grafana-cli plugins list-remote

# Установка (автоматически скачивает последнюю стабильную версию)
grafana-cli plugins install <plugin-id>

# Установка конкретной версии
grafana-cli plugins install grafana-piechart-panel 1.6.2

# Список установленных плагинов
grafana-cli plugins ls

# Удаление
grafana-cli plugins uninstall <plugin-id>
```

### Установка в контейнеризированных средах

#### Docker Compose
Плагины устанавливаются при старте контейнера через переменные окружения.

```yaml
services:
  grafana:
    image: grafana/grafana:13.1.1
    environment:
      - GF_INSTALL_PLUGINS=grafana-clock-panel,alexanderzobnin-zabbix-app
      - GF_PLUGINS_ALLOW_UNSIGNED_PLUGINS=my-custom-plugin
    volumes:
      - grafana_data:/var/lib/grafana
```

#### Kubernetes (Helm)
В Helm-чарте параметры плагинов передаются в секции `grafana`.

```yaml
# values.yaml
grafana:
  plugins:
    - grafana-piechart-panel
    - grafana-worldmap-panel
  env:
    GF_PLUGINS_ALLOW_UNSIGNED_PLUGINS: "my-custom-plugin"
```

### Ручная установка (Offline)

При отсутствии доступа к интернету плагины устанавливаются путем распаковки архива в директорию плагинов.

1.  Скачайте ZIP-архив плагина с [каталога](https://grafana.com/grafana/plugins/).
2.  Распакуйте в `/var/lib/grafana/plugins/` (для Linux).
3.  Убедитесь, что владелец директории — пользователь `grafana`.
4.  Перезапустите сервис.

## Особенности Grafana 13.x

### Background Plugin Installer
В версии 13.x введен фоновый установщик для "Bundled" плагинов (например, Elasticsearch).
*   **Проблема:** В Docker/Kubernetes директория `/usr/share/grafana/data/plugins-bundled/` часто доступна только для чтения.
*   **Решение:** Для корректного обновления встроенных плагинов монтируйте `emptyDir` (K8s) или `volume` (Docker) в этот путь.

### Совместимость с React 19
Плагины, не обновленные до поддержки React 19, могут вызывать ошибки отрисовки ("Application Error").
*   **Проверка:** Перед обновлением Grafana изучите `CHANGELOG.md` плагина на предмет поддержки React 19.

## Устранение неполадок

| Проблема | Возможная причина | Решение |
| :--- | :--- | :--- |
| **Plugin not found / not registered** | Неверные права на директорию `/var/lib/grafana/plugins` | `chown -R grafana:grafana /var/lib/grafana/plugins` |
| **Failed to load: plugin is unsigned** | Попытка загрузить неподписанный плагин без разрешения | Добавьте ID плагина в `allow_loading_unsigned_plugins` |
| **Datasource error: permission denied** | Ошибка RBAC (новое в v13) | Проверьте разрешения Service Account или роли пользователя |
| **Plugin process exited** | Падение бинарного файла бэкенд-плагина | Проверьте логи Grafana (`grep plugin <log_file>`) на ошибки архитектуры (amd64 vs arm64) |

## Дополнительная информация

### Рекомендации по эксплуатации
*   **Минимизация:** Не устанавливайте неиспользуемые плагины — каждый бэкенд-плагин запускает отдельный процесс.
*   **Мониторинг:** Метрики плагинов доступны через `/metrics`. Отслеживайте `grafana_plugin_request_duration_seconds`.
*   **Обновление:** Всегда обновляйте плагины перед обновлением самой Grafana.

**См. также:**
- [Grafana Marketplace](https://grafana.com/grafana/plugins/) — официальный каталог.
- [Провиженинг Grafana](./grafana_provisioning.md) — декларативная настройка.
- [Настройка Helm-чарта](./Installation/grafana_helm_installation.md) — развертывание в K8s.
