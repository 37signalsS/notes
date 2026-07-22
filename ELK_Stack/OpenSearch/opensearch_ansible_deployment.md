# Развертывание OpenSearch с помощью Ansible

## Определения

* **Ansible-роль OpenSearch**: набор автоматизированных сценариев (плейбуков), предназначенных для установки, конфигурации и управления жизненным циклом OpenSearch на узлах Linux.
* **Cluster Manager (ранее Master)**: роль узла, ответственного за координацию состояния кластера. В Ansible настраивается через переменную `roles: [cluster_manager]`.
* **Inventory (Инвентарь)**: файл конфигурации Ansible, описывающий хосты кластера, их IP-адреса и распределение ролей.
* **Group Vars**: переменные Ansible, применяемые к группам хостов для централизованной настройки параметров кластера (имя кластера, версия, лимиты памяти).

## Основные концепции

### Роли узлов в OpenSearch 2.x

При развертывании через Ansible важно четко разделять обязанности узлов для обеспечения стабильности:
* **cluster_manager**: управляет метаданными кластера. Рекомендуется иметь 3 выделенных узла для обеспечения кворума.
* **data**: отвечает за хранение данных и выполнение поисковых запросов.
* **ingest**: выполняет предварительную обработку данных (пайплайны) перед индексацией.

### Системные требования и тюнинг

Автоматизация через Ansible должна учитывать обязательные требования OpenSearch к операционной системе:
* **Виртуальная память (`vm.max_map_count`)**: должна быть не менее `262144` для корректной работы Lucene.
* **Лимиты дескрипторов файлов (`nofile`)**: минимальное значение — `65536`.
* **Блокировка памяти (`memlock`)**: рекомендуется установить `unlimited` и включить `bootstrap.memory_lock: true` для предотвращения свопирования процесса OpenSearch.
* **JVM Heap Size**: стандартное правило — 50% от оперативной памяти узла, но не более 32 ГБ.

## Практические сценарии

### 1. Развертывание кластера OpenSearch

#### Подготовка роли и инвентаря

Рекомендуется использовать официальный репозиторий с плейбуками:
```bash
git clone https://github.com/opensearch-project/ansible-playbook.git
cd ansible-playbook
```

Пример файла инвентаря `inventories/opensearch/hosts` для кластера из 3 узлов:

```ini
[os-cluster]
os-node-1 ansible_host=10.0.1.1 roles=cluster_manager,data
os-node-2 ansible_host=10.0.1.2 roles=cluster_manager,data
os-node-3 ansible_host=10.0.1.3 roles=cluster_manager,data

[dashboards]
os-node-web ansible_host=10.0.1.4
```

#### Настройка переменных кластера

Отредактируйте `inventories/opensearch/group_vars/all/all.yml`:

```yaml
os_cluster_name: "prod-cluster"
os_version: "2.14.0" # Используйте актуальную стабильную версию
os_dashboards_version: "2.14.0"

# Лимиты памяти Java (в ГБ)
xms_value: 4
xmx_value: 4

# Тип кластера: multi-node или single-node
cluster_type: multi-node

# Сохранение сертификатов (предотвращает их пересоздание при повторных запусках)
iac_enable: yes
```

#### Запуск установки

Запустите плейбук, передав необходимые пароли через `extra-vars`. **Важно**: используйте сложные пароли, иначе кластер не запустится.

```bash
ansible-playbook -i inventories/opensearch/hosts opensearch.yml \
  --extra-vars "admin_password=YourStrongPassword123! kibanaserver_password=DashboardsPass789! logstash_password=LogstashPass456!" \
  --become
```

**Описание системных пользователей:**
- `admin_password`: полный доступ к API и веб-интерфейсу.
- `kibanaserver_password`: для внутреннего взаимодействия Dashboards с OpenSearch.
- `logstash_password`: для отправки данных из Logstash/Fluentd.

---

### 2. Балансировка нагрузки через Nginx

Nginx используется как точка входа для API OpenSearch (порт 9200) для распределения запросов между узлами данных.

#### Конфигурация балансировщика

Пример настройки `/etc/nginx/conf.d/opensearch.conf`:

```nginx
upstream os_cluster {
    server 10.0.1.1:9200;
    server 10.0.1.2:9200;
    server 10.0.1.3:9200;
    keepalive 32;
}

server {
    listen 9200 ssl;
    server_name os-api.example.com;

    ssl_certificate /etc/nginx/ssl/os-api.crt;
    ssl_certificate_key /etc/nginx/ssl/os-api.key;

    location / {
        proxy_pass https://os_cluster;
        proxy_http_version 1.1;
        proxy_set_header Connection "";
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        
        # Настройка таймаутов для тяжелых запросов
        proxy_read_timeout 90s;
    }
}
```

Для работы балансировщика необходимо выпустить SSL-сертификаты и разместить их в `/etc/nginx/ssl/`. Если внутри OpenSearch включена обязательная проверка клиентских сертификатов, в секцию `location` необходимо добавить параметры `proxy_ssl_certificate` и `proxy_ssl_trusted_certificate`.

## Дополнительная информация

### Проверка состояния кластера

Доступ к OpenSearch Dashboards осуществляется по адресу `http://<IP-node-web>:5601`. Для проверки здоровья кластера используйте DevTools:

```http
GET _cluster/health
```

### См. также
- **[Обзор OpenSearch](./opensearch_overview.md)** — основные концепции и компоненты.
- **[Отказоустойчивость с Keepalived](./opensearch_high_availability_keepalived.md)** — настройка плавающего IP для кластера.
- **[Администрирование OpenSearch](./opensearch_administration.md)** — управление индексами и шардами.
