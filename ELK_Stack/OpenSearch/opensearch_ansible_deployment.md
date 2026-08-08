# OpenSearch: Развертывание с помощью Ansible

> Эта заметка является частью обзора [OpenSearch](./opensearch_overview.md) и рассматривает процесс автоматизированного развертывания кластера OpenSearch на выделенных серверах с использованием Ansible, включая системный тюнинг, настройку безопасности и балансировку нагрузки.

## Определения

* **Ansible-роль OpenSearch**: набор декларативных сценариев (плейбуков) и шаблонов для автоматизации установки, конфигурации и управления жизненным циклом OpenSearch.
* **Inventory (Инвентарь)**: файл, описывающий инфраструктуру (хосты, группы) и распределение ролей между узлами кластера.
* **Cluster Manager (ранее Master)**: роль узла, ответственного за координацию кластера. В Ansible настраивается через переменную `node.roles`.
* **securityadmin.sh**: утилита для инициализации и обновления индекса безопасности OpenSearch. В Ansible автоматизируется через модули `shell` или `command` с запуском `run_once`.
* **Remote-Backed Storage (RBS)**: технология хранения данных в объектном хранилище (S3/GCS), требующая настройки плагинов и параметров кластера на этапе bootstrap через Ansible.

## Основные концепции

### Архитектура развертывания

При проектировании Ansible-плейбуков следует разделять узлы по ролям для обеспечения масштабируемости:
* **cluster_manager**: минимум 3 выделенных узла для обеспечения кворума.
* **data**: узлы для хранения данных. Рекомендуется использовать `volumeClaimTemplates` (в контексте K8s) или выделенные диски в Ansible.
* **ingest**: узлы для предварительной обработки данных.

### Системная оптимизация (System Tuning)

Ansible должен гарантировать применение следующих настроек на целевых хостах:
* **Виртуальная память**: `vm.max_map_count=262144` (модуль `ansible.posix.sysctl`).
* **Лимиты ресурсов**: `nofile=65536` и `memlock=unlimited` в `/etc/security/limits.conf`.
* **Swap**: полное отключение (`swapoff -a`) для предотвращения деградации производительности JVM.
* **JVM Heap**: установка `-Xms` и `-Xmx` равными 50% RAM, но не более 31.5 ГБ (для эффективного использования Compressed OOPs).

### Автоматизация безопасности

* **Keystore**: использование Ansible для добавления секретов (например, ключей S3) в зашифрованное хранилище OpenSearch (`opensearch-keystore`).
* **TLS**: автоматическая генерация (через `openssl` или `easy-rsa`) и дистрибуция сертификатов на все узлы кластера.
* **Инициализация**: запуск `securityadmin.sh` только на одном узле после того, как весь кластер перейдет в состояние `green`.

## Практические сценарии

### 1. Настройка Inventory и переменных

Пример `inventories/prod/hosts.yml` (YAML-формат предпочтителен для сложных структур):

```yaml
opensearch_cluster:
  children:
    cluster_managers:
      hosts:
        os-mg-01: { ansible_host: 10.0.1.10 }
        os-mg-02: { ansible_host: 10.0.1.11 }
        os-mg-03: { ansible_host: 10.0.1.12 }
    data_nodes:
      hosts:
        os-dt-01: { ansible_host: 10.0.1.20 }
        os-dt-02: { ansible_host: 10.0.1.21 }
```

Пример `group_vars/all.yml` с поддержкой RBS (OpenSearch 2.15+):

```yaml
os_version: "2.15.0"
os_cluster_name: "prod-cluster"

# Настройки Remote-Backed Storage
os_remote_store_enabled: true
os_remote_store_repository: "my-s3-repo"
os_replication_strategy: "SEGMENT"

# Лимиты JVM
os_heap_size: "4g"

# Список плагинов для установки
os_plugins:
  - repository-s3
  - opensearch-prometheus-exporter
```

### 2. Автоматизация установки плагинов и Keystore

Пример задач в Ansible-роли:

```yaml
- name: Install OpenSearch plugins
  command: "bin/opensearch-plugin install {{ item }} --batch"
  args:
    chdir: "{{ os_home }}"
  loop: "{{ os_plugins }}"
  notify: restart opensearch

- name: Add S3 credentials to Keystore
  shell: |
    echo "{{ s3_access_key }}" | bin/opensearch-keystore add --stdin s3.client.default.access_key
    echo "{{ s3_secret_key }}" | bin/opensearch-keystore add --stdin s3.client.default.secret_key
  args:
    chdir: "{{ os_home }}"
  no_log: true
```

### 3. Инициализация безопасности (securityadmin.sh)

Задача должна выполняться один раз на весь кластер:

```yaml
- name: Initialize OpenSearch security
  shell: >
    ./plugins/opensearch-security/tools/securityadmin.sh
    -cd ./plugins/opensearch-security/securityconfig/
    -icl -nhnv
    -cacert {{ os_config }}/root-ca.pem
    -cert {{ os_config }}/admin.pem
    -key {{ os_config }}/admin-key.pem
  args:
    chdir: "{{ os_home }}"
  run_once: true
  delegate_to: "{{ groups['cluster_managers'][0] }}"
```

### 4. Балансировка трафика через Nginx

Nginx терминирует SSL и распределяет запросы к API (порт 9200).

```nginx
upstream opensearch_api {
    server 10.0.1.20:9200;
    server 10.0.1.21:9200;
    keepalive 64;
}

server {
    listen 9200 ssl http2;
    server_name os-api.example.com;

    ssl_certificate /etc/nginx/ssl/os-api.crt;
    ssl_certificate_key /etc/nginx/ssl/os-api.key;

    location / {
        proxy_pass https://opensearch_api;
        proxy_http_version 1.1;
        proxy_set_header Connection "";
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        
        # Увеличенные таймауты для тяжелых агрегаций
        proxy_read_timeout 180s;
    }
}
```

## Дополнительная информация

* **[OpenSearch: Обзор системы](./opensearch_overview.md)** — архитектура и основные компоненты.
* **[Администрирование OpenSearch](./opensearch_administration.md)** — управление индексами, шардами и RBS.
* **[Отказоустойчивость с Keepalived](./opensearch_high_availability_keepalived.md)** — настройка плавающего IP для API.
* **[Ansible: Лучшие практики](../ansible_bad_practices.md)** — рекомендации по написанию качественных ролей.
