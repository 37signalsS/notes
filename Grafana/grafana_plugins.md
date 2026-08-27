# Grafana: Плагины

## Определения

**Плагины (Plugins)** — модули расширения, позволяющие добавлять в Grafana новые источники данных, типы визуализаций (панели) и комплексные приложения (Apps).

**Plugin ID** — уникальный идентификатор плагина в формате `<org-id>-<plugin-name>` (например, `grafana-piechart-panel`), используемый для установки и ссылок в Marketplace.

**Версия (2026):** Grafana 13.x (переход на React 19, строгий RBAC, обязательная подпись плагинов).

**Архитектурные компоненты:**
*   **Frontend-часть:** Интерфейс плагина на React. Начиная с v13, требуется совместимость с React 19.
*   **Backend-часть:** Бинарный файл на языке Go (опционально), выполняющий запросы к данным или сложную обработку на стороне сервера.
*   **Plugin SDK:** Набор библиотек и API для разработки плагинов, обеспечивающий взаимодействие с ядром Grafana.

**Private plugins** — локальные или корпоративные плагины, не опубликованные в Marketplace. Требуют явного разрешения через `allow_loading_unsigned_plugins` или корпоративного реестра подписи (Enterprise).

## Базовые концепции

### Типы плагинов

| Тип | Назначение | Примеры |
| :--- | :--- | :--- |
| **Data Source** | Подключение баз данных, API и систем мониторинга. | Prometheus, Loki, ClickHouse, Zabbix. |
| **Panel** | Новые способы визуализации (графики, диаграммы). | Apache ECharts, Clock Panel, Flowchart. |
| **App** | Пакетные решения: UI + Dashboards + Data Sources. | Kubernetes App, Zabbix App, SageMaker. |

### Жизненный цикл плагина

1.  **Discovery:** Grafana сканирует директорию плагинов (`/var/lib/grafana/plugins/` или встроенный каталог) при запуске.
2.  **Validation:** Проверяется цифровая подпись и совместимость версии с ядром Grafana.
3.  **Registration:** Плагин регистрируется в системе; его ID становится доступным для провиженинга дашбордов и источников данных.
4.  **Execution:** Frontend-компонент загружается в интерфейс; backend-компонент (если есть) запускает отдельный процесс.
5.  **Hot-Reload:** При изменении файлов плагина (в разработке) Grafana может перезагрузить его без перезапуска сервиса.

### Безопасность и подпись (Plugin Signing)

В Grafana 13.x действует политика обязательной цифровой подписи. Неподписанные плагины блокируются ядром системы.

**Уровни подписи:**
1.  **Grafana Labs:** Официальные плагины от разработчиков Grafana.
2.  **Commercial:** Плагины для Enterprise-версий, подписанные корпоративным ключом.
3.  **Community:** Плагины от сообщества, прошедшие проверку безопасности Grafana Labs.
4.  **Unsigned:** Локальные разработки или модифицированные плагины. В Enterprise могут использоваться внутренние реестры подписи.

**Загрузка неподписанных плагинов:**
Для разрешения загрузки необходимо явно указать ID плагинов (через запятую) в `grafana.ini` или переменных окружения.
```ini
# grafana.ini
[plugins]
allow_loading_unsigned_plugins = custom-datasource-id,my-panel-id
```
**Важно:** Использование значения `true` вместо конкретных ID не поддерживается из соображений безопасности.

### Версионирование и совместимость

Плагины имеют собственный семантический версионирование (MAJOR.MINOR.PATCH), независимое от версии Grafana. При обновлении Grafana проверяйте:
- Чанжлоги плагинов на поддержку новой версии ядра.
- Совместимость с React 19 (начиная с Grafana 13.x).
- Изменения в Plugin SDK API.

### Sandboxing и изоляция

Начиная с Grafana 13.x, плагины выполняются в изолированном окружении (sandbox):
- **Frontend sandbox:** ограничивает доступ к DOM и глобальным переменным.
- **Backend sandbox:** изолирует файловую систему и сетевые вызовы плагина.
- **Resource limits:** можно задать лимиты CPU/памяти для бэкенд-плагинов через конфигурацию ядра (требует Enterprise для некоторых параметров).

### Управление через Marketplace и Catalog

- **Public Marketplace:** плагины, прошедшие ревью и подписанные Grafana Labs.
- **Private Catalog:** Enterprise-фича для публикации корпоративных плагинов внутри организации без публичного размещения.

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
В Helm-чарте параметры плагинов передаются в секции `grafana`. Начиная с версии чарта 8.x/9.x, поддерживается фиксация версий и порядок установки.

```yaml
# values.yaml
grafana:
  plugins:
    - grafana-piechart-panel@1.6.2
    - alexanderzobnin-zabbix-app@latest
  env:
    GF_PLUGINS_ALLOW_UNSIGNED_PLUGINS: "my-custom-plugin"
```

**Установка/обновление релиза:**
```bash
# Фиксация версии чарта и плагинов
helm upgrade --install grafana grafana-community/grafana \
  --namespace monitoring \
  --create-namespace \
  -f values.yaml \
  --atomic --wait
```

**Валидация перед применением:**
```bash
# Проверка синтаксиса values.yaml
helm lint grafana-community/grafana -f values.yaml

# Dry-run манифестов
helm upgrade --install grafana grafana-community/grafana \
  -f values.yaml --dry-run --debug
```

### Управление через IaC (Terraform / Grizzly)

Для Infrastructure as Code используйте официальные провайдеры:

**Terraform (Grafana Provider):**
```hcl
resource "grafana_plugin" "piechart" {
  plugin_id = "grafana-piechart-panel"
  version   = "1.6.2"
  depends_on = [grafana_data_source.prometheus]
}
```

**Grizzly (Grafana CLI для GitOps):**
```bash
# Применение провиженинга через GRC
grr apply -f dashboards/
grc apply -f datasources/
```

### Ручная установка (Offline)

При отсутствии доступа к интернету плагины устанавливаются путем распаковки архива в директорию плагинов.

1.  Скачайте ZIP-архив плагина с [каталога](https://grafana.com/grafana/plugins/).
2.  Распакуйте в `/var/lib/grafana/plugins/` (для Linux).
3.  Убедитесь, что владелец директории — пользователь `grafana`.
4.  Перезапустите сервис.

**Offline в Kubernetes:**
Для air-gapped сред используйте Init Container для распаковки плагинов в `emptyDir` или используйте локальный Helm-репозиторий с плагинами.

```yaml
# values.yaml — air-gapped сценарий
grafana:
  plugins:
    - /plugins/grafana-piechart-panel
  env:
    GF_PLUGINS_ALLOW_UNSIGNED_PLUGINS: "local-custom-plugin"
  podInitContainers:
    - name: init-plugins
      image: alpine:3.19
      command: ["/bin/sh", "-c"]
      args:
        - |
          mkdir -p /var/lib/grafana/plugins;
          unzip -o /plugins/grafana-piechart-panel.zip -d /var/lib/grafana/plugins/;
      volumeMounts:
        - name: grafana-plugins
          mountPath: /var/lib/grafana/plugins
  volumes:
    - name: grafana-plugins
      emptyDir: {}
```

## Особенности Grafana 13.x

### Background Plugin Installer
В версии 13.x введен фоновый установщик для "Bundled" плагинов (например, Elasticsearch).
*   **Проблема:** В Docker/Kubernetes директория `/usr/share/grafana/data/plugins-bundled/` часто доступна только для чтения.
*   **Решение:** Для корректного обновления встроенных плагинов монтируйте `emptyDir` (K8s) или `volume` (Docker) в этот путь.

### Совместимость с React 19
Плагины, не обновленные до поддержки React 19, могут вызывать ошибки отрисовки ("Application Error").
*   **Проверка:** Перед обновлением Grafana изучите `CHANGELOG.md` плагина на предмет поддержки React 19.

### Ограничения ресурсов
Каждый бэкенд-плагин запускает отдельный процесс. При большом количестве плагинов или высокой нагрузке:
- Используйте `requests`/`limits` для пода Grafana.
- В Enterprise-версии можно задавать лимиты на уровне плагинов через конфигурацию.

## Устранение неполадок

| Проблема | Возможная причина | Решение |
| :--- | :--- | :--- |
| **Plugin not found / not registered** | Неверные права на директорию `/var/lib/grafana/plugins` | `chown -R grafana:grafana /var/lib/grafana/plugins` |
| **Failed to load: plugin is unsigned** | Попытка загрузить неподписанный плагин без разрешения | Добавьте ID плагина в `allow_loading_unsigned_plugins` |
| **Datasource error: permission denied** | Ошибка RBAC (новое в v13) | Проверьте разрешения Service Account или роли пользователя |
| **Plugin process exited** | Падение бинарного файла бэкенд-плагина | Проверьте логи Grafana (`grep plugin <log_file>`) на ошибки архитектуры (amd64 vs arm64) |
| **Application Error (frontend)** | Плагин несовместим с React 19 | Обновите плагин до версии, поддерживающей Grafana 13.x |
| **ConfigMap size exceeded (K8s)** | Попытка передать слишком большой плагин через ConfigMap | Используйте Init Container + emptyDir или внешний образ |
| **Plugin not loading after upgrade** | Кэш фронтенда или несовместимость версии | Очистите кэш браузера, проверьте версию плагина |
| **High memory usage** | Слишком много активных бэкенд-плагинов | Ограничьте количество установленных плагинов, задайте лимиты ресурсов пода |

## Best Practices

### Версионирование
- Фиксируйте версии плагинов в `values.yaml` (Helm) или manifests (Kubernetes). Избегайте тегов `latest` в production.
- Используйте `helm show values` для изучения доступных параметров перед установкой.

### Безопасность
- Не используйте `allow_loading_unsigned_plugins = true` в production. Указывайте конкретные ID.
- Для Enterprise используйте Private Catalog вместо установки через `GF_INSTALL_PLUGINS`.
- Регулярно обновляйте плагины, особенно после security advisories Grafana Labs.

### Эксплуатация
- Удаляйте неиспользуемые плагины — каждый бэкенд-плагин потребляет память и CPU.
- Мониторьте метрики `grafana_plugin_request_duration_seconds` и `grafana_plugin_build_info`.
- Используйте Provisioning ([Провиженинг Grafana](./grafana_provisioning.md)) для статичных источников данных и дашбордов вместо плагинов там, где это возможно.

### Очистка

**Удаление плагина:**
```bash
# CLI
grafana-cli plugins uninstall <plugin-id>

# Helm — обновите values.yaml, удалив плагин из списка
helm upgrade --install grafana grafana-community/grafana \
  -f values.yaml --namespace monitoring
```

**Полная очистка Helm-релиза:**
```bash
helm uninstall grafana --namespace monitoring
# Удаление PVC (если не используется retention policy)
kubectl delete pvc -l app.kubernetes.io/instance=grafana --namespace monitoring
```

## Edge Cases

### Air-gapped среды
- Используйте Init Containers для распаковки плагинов в `emptyDir`.
- Создайте локальный Helm-репозиторий с кастомным образом Grafana, включающим плагины.

### Архитектурная несовместимость
- Бэкенд-плагины компилируются под конкретную архитектуру (amd64/arm64). Проверяйте `docker manifest` образа Grafana и плагина.
- В multi-arch кластерах используйте `nodeSelector` или `affinity` для выбора узлов.

### Конфликт версий
- При обновлении плагина проверьте совместимость дашбордов (формат JSON может меняться между major-версиями).
- Используйте `grafana-cli plugins list` для аудита установленных версий.

### Конфигурация через ConfigMap (Kubernetes)
- ConfigMap с содержимым плагина ограничен 1 MB. Для больших плагинов используйте Init Container или монтирование PersistentVolume.

**Связанные темы:**
- [Обновление и миграция](./grafana_upgrade_migration.md) — совместимость плагинов с версией Grafana при апгрейде

## Дополнительная информация

### Рекомендации по эксплуатации
*   **Минимизация:** Не устанавливайте неиспользуемые плагины — каждый бэкенд-плагин запускает отдельный процесс.
*   **Мониторинг:** Метрики плагинов доступны через `/metrics`. Отслеживайте `grafana_plugin_request_duration_seconds`.
*   **Обновление:** Всегда обновляйте плагины перед обновлением самой Grafana.

**См. также:**
- [Grafana Marketplace](https://grafana.com/grafana/plugins/) — официальный каталог.
- [Провиженинг Grafana](./grafana_provisioning.md) — декларативная настройка.
- [Настройка Helm-чарта](./Installation/grafana_helm_installation.md) — развертывание в K8s.
