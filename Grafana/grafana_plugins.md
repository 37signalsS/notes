# Grafana: Плагины

**Версия (2026):** Grafana 13.x (переход на React 19, внешние плагины вместо встроенных data source, удаление устаревших команд `grafana-cli`/`grafana-server`).

## Определения

**Плагин (Plugin)** — модуль расширения Grafana, добавляющий новые источники данных, типы визуализаций (панели) и комплексные приложения (Apps). Распространяется как набор файлов с обязательным манифестом `plugin.json`.

**Plugin ID** — уникальный идентификатор плагина в формате `<org-id>-<plugin-name>` (например, `grafana-piechart-panel`, `alexanderzobnin-zabbix-app`). Используется при установке, в ссылках Plugin Catalog и в провиженинге.

**Frontend-компонент** — обязательная часть любого плагина: код интерфейса на TypeScript/React, загружаемый в браузер. Начиная с Grafana 13 требуется совместимость с React 19.

**Backend-компонент** — опциональный бинарный файл на Go. Grafana запускает его как отдельный подпроцесс и общается с ним по gRPC через Plugin SDK (библиотека-обёртка над HashiCorp go-plugin). Необходим для серверных запросов, кэширования, проксирования, проверки доступности (health checks) и алертинга. Система бэкенд-плагинов появилась в Grafana v7.0.

**Plugin SDK** — официальные библиотеки для разработки: `@grafana/data`, `@grafana/runtime`, `@grafana/ui` (фронтенд) и `grafana-plugin-sdk-go` (бэкенд).

**Private plugin** — локальный или корпоративный плагин, не опубликованный в публичном каталоге. Требует явного разрешения на загрузку (`allow_loading_unsigned_plugins`) либо подписи приватным ключом с совпадающим `root_url` (Enterprise).

**Подпись плагина (Plugin signature)** — цифровая подпись манифеста `MANIFEST.txt`, содержащего контрольные суммы всех файлов плагина. Grafana проверяет её при старте и не загружает неподписанные или изменённые (modified) плагины.

## Базовые концепции

### Типы плагинов

| Тип | Назначение | Примеры |
| :--- | :--- | :--- |
| **Data Source** | Подключение баз данных, API и систем мониторинга. | Prometheus, Loki, ClickHouse, Zabbix, Elasticsearch. |
| **Panel** | Новые способы визуализации (графики, диаграммы). | Apache ECharts, Clock Panel, Flowchart. |
| **App** | Пакетные решения: UI + Dashboards + Data Sources. | Kubernetes App, Zabbix App. |

### Архитектура плагина

Плагин разделён на две части, которые взаимодействуют через несколько обработчиков:

*   **Frontend** — React-компоненты (query editor, панель, страницы конфигурации). Загружается в контекст браузера вместе с основным приложением Grafana.
*   **Backend** — Go-бинарник, запускаемый ядром как отдельный процесс. Реализует `QueryDataHandler` (запросы данных), `CallResourceHandler` (собственные HTTP-эндпоинты) и `CheckHealthHandler` (проверка соединения). Бэкенд может делать внешние запросы, проксировать аутентификацию и хранить учётные данные в зашифрованном виде.

Вынос бэкенда в отдельный процесс даёт две гарантии: паника в плагине не роняет процесс Grafana, а плагин имеет доступ только к переданным ему интерфейсам и аргументам, но не ко всему адресному пространству сервера.

### Жизненный цикл плагина

1.  **Discovery:** Grafana сканирует каталог плагинов (`/var/lib/grafana/plugins/` по умолчанию, а также встроенный каталог `plugins-bundled`) при запуске.
2.  **Bootstrap:** читается `plugin.json`, создаётся объект плагина, разрешаются зависимости.
3.  **Validation:** проверяется цифровая подпись (`MANIFEST.txt`) и совместимость версии с ядром Grafana.
4.  **Initialization:** плагин регистрируется в системе, запускается бэкенд-процесс, регистрируются обработчики. ID становится доступным для провиженинга дашбордов и источников данных.
5.  **Termination:** при остановке Grafana бэкенд-плагины завершаются корректно (graceful shutdown).
6.  **Hot-Reload:** в режиме разработки (`app_mode = development`) Grafana может перезагрузить плагин без перезапуска сервиса.

### Безопасность и подпись (Plugin Signing)

Проверка подписи существует с Grafana 7.0 и обязательна по умолчанию во всех современных ветках, включая 13.x. При старте Grafana проверяет цифровую подпись каждого плагина в каталоге. Неподписанный плагин не загружается, а в серверный лог пишется ошибка вида `plugin is unsigned`.

**Статусы подписи:**

| Статус | Значение |
| :--- | :--- |
| `internal` | Встроенный плагин ядра, подпись не требуется. |
| `valid` | Подпись корректна, содержимое совпадает с манифестом. |
| `invalid` | Проверка подписи не прошла. |
| `modified` | Подпись валидна, но содержимое плагина изменено после подписи. Такой плагин не загружается даже при разрешённых неподписанных плагинах. |
| `unsigned` | Файл `MANIFEST.txt` отсутствует. |

**Уровни подписи (signature levels):** `grafana` (официальные плагины Grafana Labs), `commercial` (плагины Enterprise), `community` (плагины сообщества после ревью Grafana Labs), `private` (приватная подпись для внутреннего использования, `rootUrls` должны совпадать с `root_url` инстанса).

### Загрузка неподписанных и приватных плагинов

Для разрешения загрузки необходимо перечислить конкретные ID плагинов (через запятую) в `grafana.ini` или переменной окружения:

```ini
# grafana.ini
[plugins]
allow_loading_unsigned_plugins = custom-datasource-id,my-panel-id
```

```bash
# Переменная окружения (Docker/K8s)
GF_PLUGINS_ALLOW_LOADING_UNSIGNED_PLUGINS=custom-datasource-id,my-panel-id
```

**Важно:**
*   Значение `true` вместо списка ID не поддерживается из соображений безопасности.
*   Плагин со статусом `modified` не загрузится даже при наличии его ID в этом списке — корректнее удалить повреждённый `MANIFEST.txt`.
*   Для разработки удобнее включить режим `app_mode = development`, который разрешает все неподписанные плагины.

### Frontend Sandbox (изоляция фронтенда)

Frontend Sandbox — механизм безопасности, который запускает фронтенд-код плагина в отдельном JavaScript-контексте. Он предотвращает изменение глобальных объектов браузера, вмешательство в другие плагины и модификацию интерфейса Grafana за пределами области плагина.

```ini
# grafana.ini — перечислить ID плагинов, подлежащих изоляции
[security]
enable_frontend_sandbox_for_plugins = my-panel-id,my-datasource-id
```

*   Функция доступна с Grafana 11.5 (public preview) и стабилизирована в 12.x; по умолчанию **отключена** для всех плагинов.
*   Поддерживаются app-, panel- и data source-плагины.
*   Angular-плагины не поддерживаются.
*   Плагины, разработанные и подписанные Grafana Labs, изоляции не подлежат.
*   Включение sandbox может снизить производительность отдельных плагинов, поэтому его применяют к плагинам, исполняющим произвольный JavaScript (например, визуализации с пользовательским кодом).

### Версионирование и совместимость

Плагины используют собственное семантическое версионирование (MAJOR.MINOR.PATCH), независимое от версии Grafana. Манифест `plugin.json` содержит поле `grafanaDependency` — диапазон совместимых версий ядра. При обновлении Grafana проверяйте:

*   Чейнджлоги плагинов на поддержку новой версии ядра.
*   Совместимость с React 19 (начиная с Grafana 13).
*   Изменения в Plugin SDK API.

### Каталог плагинов

*   **Публичный Plugin Catalog** — плагины, прошедшие ревью и подписанные Grafana Labs. Доступен на [grafana.com/grafana/plugins](https://grafana.com/grafana/plugins/) и через UI Grafana (**Administration → Plugins and data → Plugins**).
*   **Private Catalog (Enterprise)** — публикация корпоративных плагинов внутри организации без их размещения в публичном каталоге.

## Практические сценарии

### Управление через Grafana CLI

В Grafana 13.0 старые команды `grafana-cli` и `grafana-server` **удалены**. Они были объявлены устаревшими ещё в v10.0. Во всех скриптах, systemd-юнитах, Docker-entrypoint и CI-пайплайнах используйте `grafana cli` и `grafana server`. Для установки и удаления плагинов на Linux может потребоваться `sudo`.

```bash
# Показать справку по CLI
grafana cli -h

# Список доступных для установки плагинов в каталоге
grafana cli plugins list-remote

# Установка последней версии
grafana cli plugins install <plugin-id>

# Установка конкретной версии
grafana cli plugins install grafana-clock-panel 2.1.5

# Список установленных плагинов
grafana cli plugins ls

# Обновить один плагин
grafana cli plugins update <plugin-id>

# Обновить все установленные плагины
grafana cli plugins update-all

# Удалить плагин
grafana cli plugins remove <plugin-id>
```

Глобальные опции позволяют переопределить расположение плагинов и источник загрузки для одной команды:

```bash
# Установка в нестандартный каталог
grafana cli --pluginsDir "/var/lib/grafana/devplugins" plugins install <plugin-id>

# Установка из локального ZIP-архива (air-gapped)
grafana cli --pluginUrl https://company.local/plugins/<id>-<version>.zip plugins install <plugin-id>
```

### Установка через конфигурацию (preinstall)

Начиная с Grafana 11.5 можно декларативно перечислить плагины в секции `plugins.preinstall`. Такие плагины Grafana не даёт случайно удалить и может автоматически обновлять.

```ini
# grafana.ini
[plugins]
; асинхронная установка — Grafana стартует сразу, плагины ставятся в фоне
preinstall = grafana-clock-panel,grafana-polystat-panel
; синхронная установка — плагины ставятся до запуска Grafana (безопаснее)
preinstall_sync = grafana-lokiexplore-app
```

Формат записи: `<plugin ID>@[<version>]@<url к zip>` (версия и URL опциональны).

### Установка в контейнеризированных средах

#### Docker Compose

Рекомендуемый способ — переменная `GF_PLUGINS_PREINSTALL_SYNC` (синхронная установка до старта). Легаси-переменная `GF_INSTALL_PLUGINS` формально ещё работает (внутри маппится на `preinstall_sync`), но считается устаревшей.

```yaml
services:
  grafana:
    image: grafana/grafana:13.2.3
    environment:
      - GF_PLUGINS_PREINSTALL_SYNC=grafana-clock-panel,alexanderzobnin-zabbix-app
      - GF_PLUGINS_ALLOW_LOADING_UNSIGNED_PLUGINS=my-custom-plugin
    volumes:
      - grafana_data:/var/lib/grafana
```

#### Kubernetes (Helm)

В чарте `grafana-community/grafana` плагины задаются списком в ключе `plugins` верхнего уровня. Формат элемента: `<plugin-id>@[<version>]@[<url>]`.

```yaml
# values.yaml
plugins:
  - grafana-piechart-panel@1.6.2
  - alexanderzobnin-zabbix-app

# Изоляция фронтенда для недоверенных плагинов
env:
  GF_PLUGINS_ALLOW_LOADING_UNSIGNED_PLUGINS: "my-custom-plugin"

# Обязательно для плагинов, вынесенных из ядра в Grafana 13 (elasticsearch, cloudwatch, zipkin, tempo),
# если они перечислены в plugins: — иначе установка упадёт на read-only каталоге plugins-bundled
shadowBundledPlugins: true
```

**Установка/обновление релиза:**

```bash
helm repo add grafana-community https://grafana-community.github.io/helm-charts
helm repo update

helm upgrade --install grafana grafana-community/grafana \
  --version 13.5.0 \
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

**Проверка после установки:**

```bash
# Список плагинов в поде
kubectl exec -n monitoring deploy/grafana -- grafana cli plugins ls

# Список загруженных плагинов через HTTP API
curl -s -u admin:<password> http://localhost:3000/api/plugins | jq '.[].id'
```

### Управление как код (IaC)

*   **Terraform:** у провайдера `grafana/grafana` **нет** ресурса для установки плагинов в self-hosted Grafana. Существует только `grafana_cloud_plugin_installation`, который управляет плагинами в Grafana Cloud (облачный сценарий — вне рамок этой базы). Для self-hosted плагины ставятся через preinstall, Grafana CLI или Helm.
*   **Grizzly (`grr`) и `grafanactl`** управляют дашбордами, источниками данных и другими ресурсами как кодом, но не установкой плагинов. Grizzly удалён и не поддерживается; `grafanactl`, пришедший ему на смену, сам выводится из эксплуатации в пользу `gcx`. Для декларативной настройки Grafana используйте [Провиженинг Grafana](./grafana_provisioning.md).

### Ручная установка (offline)

При отсутствии доступа к интернету плагин устанавливается распаковкой архива в каталог плагинов.

1.  Скачайте ZIP-архив плагина c [каталога](https://grafana.com/grafana/plugins/) либо через Grafana.com API (`https://grafana.com/api/plugins/<plugin-id>` → ссылка `download`).
2.  Распакуйте в каталог плагинов (по умолчанию `/var/lib/grafana/plugins/`). Каталог назначается опцией конфигурации `[paths] plugins` (`GF_PATHS_PLUGINS`).
3.  Убедитесь, что владелец каталога — пользователь `grafana`.
4.  Перезапустите сервис.

```bash
unzip my-plugin-0.2.0.zip -d /var/lib/grafana/plugins/my-plugin
chown -R grafana:grafana /var/lib/grafana/plugins
systemctl restart grafana-server
```

**Air-gapped Kubernetes:** используйте init-контейнер для распаковки плагинов в `emptyDir` либо локальный Helm-репозиторий с предварительно собранным образом Grafana.

```yaml
# values.yaml — air-gapped сценарий
extraInitContainers:
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
extraVolumeMounts:
  - name: grafana-plugins
    mountPath: /var/lib/grafana/plugins
  - name: plugins-src
    mountPath: /plugins
    readOnly: true
extraVolumes:
  - name: grafana-plugins
    emptyDir: {}
  - name: plugins-src
    configMap:
      name: grafana-plugin-archives
```

## Особенности Grafana 13.x

### Background Plugin Installer и каталог plugins-bundled

В Grafana 13 ряд data source вынесен из ядра (Elasticsearch, CloudWatch, Zipkin, Tempo) и поставляется как внешний плагин, автоматически устанавливаемый фоновым установщиком. Он пытается обновить плагин в каталоге `/usr/share/grafana/data/plugins-bundled/`, который в контейнере доступен только для чтения.

*   **Симптом:** в логе ошибка `plugin.backgroundinstaller: Failed to install plugin ... unlinkat .../plugins-bundled/<id>/...: permission denied`; соответствующие источники данных становятся недоступны после обновления Grafana 12 → 13.
*   **Решение (Helm):** включить `shadowBundledPlugins: true` — монтирует `emptyDir` поверх `plugins-bundled`, и плагины ставятся в `/var/lib/grafana/plugins`.
*   **Решение (Docker/standalone):** смонтировать writable-каталог (volume/emptyDir) поверх `/usr/share/grafana/data/plugins-bundled`. Побочный эффект: встроенный плагин из этого каталога исчезнет, и его нужно добавить в список устанавливаемых.
*   **Временный обход:** `plugin_admin_enabled = false` в `grafana.ini` останавливает попытки автообновления bundled-плагинов.
*   В deb/rpm-пакетах каталог `plugins-bundled` перенесён в `/var/lib/grafana/plugins-bundled`, чтобы он был доступен пользователю `grafana` для записи.

### Совместимость с React 19

Grafana 13 обновлена с React 18 до React 19 и использует единый инстанс React для ядра и всех плагинов. Плагины, не готовые к React 19, могут вызывать ошибку отрисовки («Application Error»).

*   **Проверка:** просканировать собранный JS инструментом `npx -y @grafana/react-detect@latest` и изучить `CHANGELOG.md` плагина.
*   **Типовые причины:** `ReactDOM.findDOMNode`, `ReactDOM.render`, `propTypes`/`defaultProps` на функциональных компонентах, `__SECRET_INTERNALS_DO_NOT_USE` — переименованы или удалены в React 19.
*   Порядок обновления: сначала обновить Grafana до последнего патча текущей ветки, затем обновить все плагины, и только потом переходить на 13.

### Удаление устаревших команд

`grafana-cli` и `grafana-server` удалены в Grafana 13.0. Обновите все скрипты, systemd-юниты, Docker-entrypoint и CI-пайплайны на `grafana cli` и `grafana server`.

### Ограничения ресурсов

Каждый бэкенд-плагин запускает отдельный процесс внутри пода/хоста Grafana. При большом числе установленных плагинов или высокой нагрузке:

*   Используйте `requests`/`limits` для контейнера Grafana — они охватывают все процессы плагинов.
*   Мониторьте потребление памяти и число процессов; удаляйте неиспользуемые плагины.
*   Помните, что фронтенд-плагин без бэкенда не создаёт отдельного серверного процесса, но загружается в браузер клиента.

## Устранение неполадок

| Проблема | Возможная причина | Решение |
| :--- | :--- | :--- |
| **Plugin not found / not registered** | Неверные права на каталог `/var/lib/grafana/plugins` | `chown -R grafana:grafana /var/lib/grafana/plugins` |
| **Failed to load: plugin is unsigned** | Попытка загрузить неподписанный плагин без разрешения | Добавьте ID плагина в `allow_loading_unsigned_plugins` / `GF_PLUGINS_ALLOW_LOADING_UNSIGNED_PLUGINS` |
| **Plugin signature is invalid / modified** | Файлы плагина изменены после подписи | Удалите повреждённый `MANIFEST.txt` и разрешите плагин явно, либо переустановите из каталога |
| **Datasource error: permission denied** | Ошибка RBAC (fine-grained access control, по умолчанию в 13.x) | Проверьте разрешения Service Account или роли пользователя |
| **Plugin process exited** | Падение бинарника бэкенд-плагина | Проверьте логи Grafana (`grep plugin <log_file>`) на ошибки архитектуры (amd64 vs arm64) |
| **Application Error (frontend)** | Плагин несовместим с React 19 | Обновите плагин до версии, поддерживающей Grafana 13.x |
| **Failed to install plugin ... plugins-bundled ... permission denied** | Read-only каталог `plugins-bundled` в контейнере | Helm: `shadowBundledPlugins: true`; Docker: смонтировать writable-каталог поверх `plugins-bundled` |
| **ConfigMap size exceeded (K8s)** | Попытка передать большой плагин через ConfigMap | Используйте init-контейнер + `emptyDir`, PersistentVolume или собственный образ |
| **Plugin not loading after upgrade** | Кэш фронтенда или несовместимость версии | Очистите кэш браузера, проверьте версию плагина через `grafana cli plugins ls` |
| **High memory usage** | Слишком много активных бэкенд-плагинов | Ограничьте число установленных плагинов, задайте `limits` для контейнера Grafana |
| **`grafana-cli: command not found`** | Команда удалена в Grafana 13.0 | Используйте `grafana cli` |

## Best Practices

### Версионирование

*   Фиксируйте версии плагинов в `values.yaml` (Helm) или манифестах — избегайте нефиксированного `latest` в production.
*   Используйте `helm show values grafana-community/grafana` для изучения доступных параметров перед установкой.
*   Перед мажорным апгрейдом Grafana сверяйте `grafanaDependency` плагина и порядок обновления (см. [Обновление и миграция](./grafana_upgrade_migration.md)).

### Безопасность

*   Не используйте `allow_loading_unsigned_plugins = true` в production — перечисляйте конкретные ID.
*   Для плагинов, исполняющих произвольный JavaScript, включайте Frontend Sandbox (`enable_frontend_sandbox_for_plugins`).
*   Для Enterprise используйте Private Catalog вместо установки из публичного каталога.
*   Регулярно обновляйте плагины, особенно после security advisories Grafana Labs.

### Эксплуатация

*   Удаляйте неиспользуемые плагины — каждый бэкенд-плагин потребляет память и CPU.
*   Мониторьте метрики плагинов: `grafana_plugin_request_duration_seconds` (гистограмма времени обработки), `grafana_plugin_request_total` (счётчик запросов), `grafana_plugin_build_info` (версии загруженных плагинов).
*   Для статичных источников данных и дашбордов предпочитайте провиженинг ([Провиженинг Grafana](./grafana_provisioning.md)) вместо ручной настройки.

### Очистка

**Удаление плагина:**

```bash
# CLI
grafana cli plugins remove <plugin-id>

# Helm — удалите плагин из списка plugins: и обновите релиз
helm upgrade --install grafana grafana-community/grafana \
  -f values.yaml --namespace monitoring
```

**Полная очистка Helm-релиза:**

```bash
helm uninstall grafana --namespace monitoring
# Удаление PVC, если не используется retention policy
kubectl delete pvc -l app.kubernetes.io/instance=grafana --namespace monitoring
```

## Edge Cases

### Air-gapped среды

*   Используйте init-контейнеры для распаковки плагинов в `emptyDir` или собственный образ Grafana с уже включёнными плагинами.
*   Скачивайте ZIP напрямую через Grafana.com API и переносите в закрытый контур.
*   Проверьте, какие внешние эндпоинты нужны для установки, и добавьте их в allow list, если установка из каталога разрешена.

### Архитектурная несовместимость

*   Бэкенд-плагины компилируются под конкретную архитектуру (amd64/arm64). Проверяйте `docker manifest`/`docker buildx imagetools inspect` для образа Grafana и плагина.
*   Проверить архитектуру образа: `docker buildx imagetools inspect grafana/grafana:13.2.3`.
*   В multi-arch кластерах используйте `nodeSelector` или `affinity` для узлов с нужной архитектурой.

### Конфликт версий

*   При обновлении плагина проверьте совместимость дашбордов: формат JSON панели может меняться между major-версиями плагина.
*   Используйте `grafana cli plugins ls` для аудита установленных версий.
*   При обновлении Grafana обновляйте плагины заранее: несовпадение версии — частая причина, по которой Grafana не стартует.

### Плагин через ConfigMap (Kubernetes)

*   ConfigMap ограничен ~1 MB. Для больших плагинов используйте init-контейнер, PersistentVolume или собственный образ Grafana.

**Связанные темы:**
*   [Обновление и миграция](./grafana_upgrade_migration.md) — совместимость плагинов с версией Grafana при апгрейде
*   [Настройка Helm-чарта](./Installation/grafana_helm_installation.md) — развёртывание Grafana в Kubernetes

## Дополнительная информация

### Рекомендации по эксплуатации

*   **Минимизация:** не устанавливайте неиспользуемые плагины — каждый бэкенд-плагин запускает отдельный процесс.
*   **Мониторинг:** метрики плагинов доступны на `/metrics`. Отслеживайте `grafana_plugin_request_duration_seconds` и `grafana_plugin_build_info`.
*   **Обновление:** обновляйте плагины перед обновлением самой Grafana.

**См. также:**
*   [Plugin Catalog](https://grafana.com/grafana/plugins/) — официальный каталог плагинов.
*   [Провиженинг Grafana](./grafana_provisioning.md) — декларативная настройка источников данных и дашбордов.
*   [Источники данных](./grafana_datasources.md) — подключение хранилищ телеметрии.
*   [Настройка Helm-чарта](./Installation/grafana_helm_installation.md) — развёртывание в Kubernetes.
*   [Безопасность Grafana](./grafana_security_hardening.md) — усиление защиты инстанса.
