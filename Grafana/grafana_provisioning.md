# Grafana Провиженинг

Провиженинг в Grafana позволяет управлять конфигурациями (источниками данных, дашбордами, плагинами) как кодом, обеспечивая автоматизацию, версионирование и согласованность между различными экземплярами Grafana. Это особенно актуально в средах Kubernetes, где Grafana часто развертывается с использованием Helm.

## Принципы провиженинга

Grafana поддерживает провиженинг через конфигурационные файлы (например, JSON для дашбордов, YAML для источников данных), которые могут быть расположены в специальной директории `provisioning`. При запуске Grafana автоматически подхватывает эти файлы и применяет описанные в них конфигурации, создавая необходимые дашборды и источники данных в системе. Это позволяет инициализировать Grafana с предустановленными конфигурациями.

Механизм провиженинга является центральным для автоматизированного развертывания Grafana в различных средах:

*   **Standalone-установка:** Файлы провиженинга размещаются в специальной директории (по умолчанию `/etc/grafana/provisioning`).
*   **Docker-контейнер:** Директория с файлами провиженинга монтируется как том в соответствующий путь внутри контейнера.
*   **Kubernetes (Helm-чарты):** Конфигурационные файлы часто встраиваются в Helm `values.yaml` или ConfigMaps и развертываются вместе с Grafana. Переменные в Helm-чарте могут использоваться для динамической настройки путей или содержимого.

В контексте Kubernetes и Helm, эти конфигурационные файлы часто встраиваются в Helm `values.yaml` и развертываются вместе с Grafana. Также для управления конфигурациями Grafana как кодом активно используются инструменты Infrastructure as Code, такие как Terraform или Pulumi, которые позволяют менеджить дашборды и источники данных, изменяя `values` и распространяя конфигурации через CI/CD пайплайны.

Стоит отметить, что в будущих версиях Grafana (например, начиная с версии 12) ожидается появление более глубокой интеграции с Git-репозиториями, что позволит реализовать подход, аналогичный GitOps, где Grafana будет автоматически отслеживать изменения в репозитории и применять их.

## Провиженинг источников данных (Data Sources)

Источники данных могут быть определены в файле `values.yaml` Helm-чарта Grafana. Это позволяет автоматически создавать и настраивать источники данных при развертывании Grafana.

Пример конфигурации источника данных Prometheus через `values.yaml`:

```yaml
grafana:
  datasources:
    datasources.yaml:
      apiVersion: 1
      datasources:
      - name: Prometheus1
        type: prometheus
        url: http://prometheus-server.monitoring.svc.cluster.local
        access: proxy
        isDefault: true
        version: 1
        editable: false
```

**Важные замечания по провиженингу источников данных:**

*   Источники данных, созданные вручную через UI Grafana, сохраняются даже после провиженинга новых источников данных.
*   Провизионированный источник данных может переопределить "defaultность" другого источника данных, если в его конфигурации `isDefault` установлено в `true`.
*   Источники данных, добавленные через провиженинг, не могут быть изменены через UI Grafana, о чем обычно сообщается в интерфейсе ("Please contact your server admin to update this data source").

**Пояснения:**

*   `name`: Уникальное имя источника данных.
*   `type`: Тип источника данных (например, `prometheus`, `loki`, `influxdb`).
*   `url`: URL-адрес сервера источника данных.
*   `access`: Метод доступа (`proxy` для серверного прокси, `direct` для прямого доступа из браузера).
*   `isDefault`: Указывает, является ли этот источник данных по умолчанию.
*   `editable`: Если `false`, источник данных нельзя будет изменить через UI Grafana.

## Провиженинг дашбордов (Dashboards)

Дашборды также могут быть провижены с помощью Helm. Grafana может загружать дашборды из файлов JSON, из библиотеки Grafana.com, напрямую из встроенного JSON в `values.yaml`, или из Kubernetes ConfigMaps.

Пример конфигурации провиженинга дашбордов через `values.yaml`:

```yaml
grafana:
  dashboardProviders:
    dashboardproviders.yaml:
      apiVersion: 1
      providers:
      - name: monitoring
        orgId: 1
        folder: ''
        type: file
        disableDeletion: false
        editable: true
        options:
          path: /var/lib/grafana/dashboards/monitoring
  dashboards:
    monitoring:
      node-exporter-full:
        gnetId: 1860
        revision: 21
        datasource: Prometheus1
      new-dash:
        json: |-
          # ... (JSON-модель дашборда) ...
```

### Файловый провиженинг на практике

Помимо встраивания конфигураций в Helm `values`, можно использовать более прямой файловый подход, который особенно удобен при работе с Docker-контейнерами.

Grafana при старте сканирует директорию `/etc/grafana/provisioning/`. В ней можно создать поддиректории для разных типов ресурсов:

*   `datasources/`
*   `dashboards/`
*   `plugins/`
*   `notifiers/` (устарело, сейчас используются `alerting`)

**Пример структуры:**

```
/path/to/your/grafana/provisioning/
├── datasources/
│   └── datasources.yaml
└── dashboards/
    ├── dashboards.yaml
    └── rotation/
        ├── rotation-dash-1.json
        └── rotation-dash-2.json
```

1.  **Провиженинг источников данных (`datasources.yaml`):**

    Этот файл определяет один или несколько источников данных.

    ```yaml
    apiVersion: 1
    datasources:
    - name: InfluxDB
      type: influxdb
      url: http://influxdb:8086
      database: telegraf # Пример из транскрипта
      user: telegraf
      password: your_password # Используйте безопасное хранилище секретов
      access: proxy
      isDefault: true
    ```

2.  **Провиженинг дашбордов (`dashboards.yaml`):**

    Этот файл указывает Grafana, где искать JSON-модели дашбордов.

    ```yaml
    apiVersion: 1
    providers:
    - name: 'rotation'
      orgId: 1
      folder: 'Rotation' # Дашборды будут помещены в папку 'Rotation' в UI
      type: file
      options:
        path: /etc/grafana/provisioning/dashboards/rotation # Путь внутри контейнера
    ```

2.  **JSON-модели (`rotation-dash-1.json`):**

    Это обычные JSON-файлы дашбордов, которые можно получить, экспортировав существующий дашборд.

3.  **Провиженинг плейлистов:**

    Точно так же можно автоматически создать и плейлист для ротации этих дашбордов.
    *   `provisioning/playlists.yaml`:

    ```yaml
    apiVersion: 1
    playlists:
      - name: 'Rotation Playlist'
        interval: '1m'
        orgId: 1
        items:
          - type: dashboard_by_folder
            value:
              folderName: 'Rotation' # Указываем папку, все дашборды из которой попадут в плейлист
            title: 'Dashboards from Rotation Folder'
    ```

При таком подходе, примонтировав локальную директорию `provisioning` в `/etc/grafana/provisioning/` в контейнере, вы получите полностью настроенную Grafana с источниками данных, дашбордами и плейлистами при первом же запуске.

**Важное замечание по провиженингу дашбордов:**

*   Имя дашборда не должно совпадать с именем директории, в которой он находится. В противном случае Grafana может выдать ошибку при провиженинге.

**Пояснения:**

*   **`dashboardProviders`**: Определяет, откуда Grafana будет загружать дашборды.
    *   `name`: Имя провайдера.
    *   `type: file`: Указывает, что дашборды будут загружаться из файлов.
    *   `options.path`: Путь в контейнере Grafana, где будут находиться файлы дашбордов.
*   **`dashboards`**: Определяет сами дашборды.
    *   `node-exporter-full`: Пример импорта дашборда из Grafana.com.
        *   `gnetId`: ID дашборда на Grafana.com (например, 1860 для Node Exporter Full).
        *   `revision`: Версия дашборда.
        *   `datasource`: Имя источника данных, который будет использоваться дашбордом.
    *   `new-dash`: Пример дашборда, встроенного напрямую в `values.yaml` в формате JSON.
        *   `json`: Сырой JSON-объект дашборда.

## Провиженинг плагинов (Plugins)

Плагины Grafana также могут быть установлены автоматически при развертывании через Helm.

Пример конфигурации плагинов через `values.yaml`:

```yaml
grafana:
  plugins:
    - grafana-piechart-panel
    - trafficlight-panel
```

**Пояснения:**

*   `plugins`: Список плагинов, которые Grafana должна установить при запуске. Grafana CLI будет использовать эти имена для установки плагинов из официального репозитория Grafana.

## Преимущества провиженинга

*   **Автоматизация:** Устраняет ручные операции по настройке Grafana.
*   **Версионирование:** Конфигурации хранятся в системе контроля версий (например, Git), что позволяет отслеживать изменения и откатываться к предыдущим версиям.
*   **Согласованность:** Обеспечивает одинаковую конфигурацию Grafana в различных средах (разработка, тестирование, продакшн).
*   **GitOps:** Идеально подходит для реализации подхода GitOps, где желаемое состояние инфраструктуры описывается в Git.

## Автоматизация дашбордов с помощью Ansible

Ansible может быть использован для автоматического создания, обновления и удаления дашбордов Grafana через её API. Это позволяет интегрировать управление дашбордами в CI/CD пайплайны и хранить их конфигурацию в системе контроля версий.

### Динамическая генерация дашбордов

Для создания типовых дашбордов с небольшими отличиями (например, для разных сервисов или окружений) можно использовать шаблонизатор **Jinja2** в связке с Ansible. Это позволяет генерировать множество похожих дашбордов из одного файла-шаблона.

1.  **Создание шаблона**: Экспортируйте существующий дашборд Grafana в JSON-файл. Затем разработайте JSON-шаблон дашборда (например, `dashboard.json.j2`), заменяя специфические для инстанса Grafana ID (например, `uid`, `id` панелей, `datasourceId`) и динамические значения (например, имена команд, ID сервисов) на переменные Jinja2 (например, `{{ team_name }}`, `{{ service_uid }}`). Это позволяет создать универсальный шаблон, который будет адаптироваться под различные окружения.

2.  **Определение переменных**: В Ansible определите список переменных, по которому будет производиться итерация.

    ```yaml
    vars:
      dashboards_to_create:
        - name: "Dashboard for Team A"
          uid: "team_a_abc"
          team: "Team A"
        - name: "Dashboard for Team B"
          uid: "team_b_xyz"
          team: "Team B"
    ```

3.  **Генерация и развертывание в цикле**: Используйте цикл (`loop`) в плейбуке Ansible, чтобы для каждого набора переменных сгенерировать финальный JSON и сразу же развернуть его с помощью модуля `community.grafana.grafana_dashboard` через API Grafana.

    ```yaml
    - name: Generate and deploy dashboards in a loop
      ansible.builtin.template:
        src: dashboard.json.j2
        dest: "/tmp/dashboard_{{ item.uid }}.json"
      loop: "{{ dashboards_to_create }}"
      register: generated_dashboards

    - name: Deploy generated dashboards to Grafana
      community.grafana.grafana_dashboard:
        grafana_url: "https://grafana.example.com"
        grafana_api_key: "{{ grafana_api_key }}"
        state: present
        path: "{{ item.path }}"
      loop: "{{ generated_dashboards.results | map(attribute='path') | list }}"
    ```

### Модуль `grafana_dashboard`

Ansible предоставляет модуль `grafana_dashboard` (из коллекции `community.grafana`), который позволяет взаимодействовать с Grafana API для управления дашбордами.

*   **`grafana_url`**: URL вашей Grafana.
*   **`grafana_api_key`**: API-ключ с соответствующими правами (например, Editor или Admin). API-ключи можно создать в Grafana в разделе `Configuration -> API Keys`. Рекомендуется хранить API-ключи в безопасном хранилище (например, Ansible Vault). Подробнее см. в [документе по управлению пользователями](./grafana_user_management_and_authentication.md).
*   **`state`**: `present` (создать/обновить) или `absent` (удалить).
*   **`path`**: Путь к JSON-файлу дашборда (или сгенерированному из шаблона).

Пример использования Ansible для развертывания дашборда:

```yaml
- name: Deploy Grafana Dashboard
  community.grafana.grafana_dashboard:
    grafana_url: "https://grafana.example.com"
    grafana_api_key: "{{ grafana_api_key }}" # API-ключ из Vault или другого безопасного хранилища
    state: present
    path: "/path/to/generated_dashboard.json"
```


