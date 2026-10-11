# OpenSearch: Развертывание с помощью Ansible

**Актуально для:** OpenSearch 3.9.x (релиз 29 сентября 2026). Отличия ветки 2.x (2.12+, 2.15) отмечены в тексте.

> Эта заметка является частью обзора [OpenSearch](./opensearch_overview.md) и рассматривает автоматизированное развертывание кластера OpenSearch на выделенных серверах (bare metal / VM) с помощью Ansible: установку пакетов, системный тюнинг, конфигурацию, безопасность, rolling restart и балансировку нагрузки. Развертывание в Kubernetes описано в [Helm-ноте](./opensearch_helm_deployment.md); sizing кластера — в [capacity planning](./opensearch_capacity_planning.md).

## Определения

* **Ansible-роль OpenSearch**: набор декларативных сценариев (плейбуков), шаблонов и обработчиков для автоматизации установки, конфигурации и управления жизненным циклом OpenSearch.
* **Directory inventory**: инвентарь, организованный как каталог с `hosts.yml`, `group_vars/` и `host_vars/`; Ansible автоматически объединяет файлы в единый инвентарь. Паттерн multi-environment — отдельный каталог на окружение (`inventories/prod/`, `inventories/staging/`), детали в [Ansible — управление мультисредами](../../Ansible/ansible_multi_environment_management.md).
* **Cluster Manager (ранее Master)**: роль узла, отвечающего за координацию кластера. В Ansible настраивается через переменную `node.roles`.
* **securityadmin.sh**: утилита для инициализации и обновления индекса безопасности OpenSearch из YAML-файлов. В Ansible автоматизируется через модуль `command` с `run_once` и `delegate_to`.
* **Remote store (RBS)**: архитектура хранения данных в S3-совместимом объектном хранилище (в том числе on-prem: MinIO, Ceph) с сегментной репликацией; требует плагина `repository-s3` и настроек кластера на этапе bootstrap.
* **Ansible Vault**: встроенное шифрование секретов (пароли, ключи) в переменных и файлах; альтернатива plaintext-переменным.
* **Rolling restart**: поочередный перезапуск узлов кластера (по одному) с сохранением доступности; реализуется через `serial: 1` и управление настройкой `cluster.routing.allocation.enable`.
* **OPENSEARCH_INITIAL_ADMIN_PASSWORD**: переменная окружения, передаваемая при установке пакета (OpenSearch 2.12+), задает пароль пользователя `admin` для демо-конфигурации безопасности.
* **DISABLE_INSTALL_DEMO_CONFIG**: переменная окружения, запрещающая установщику пакета создавать демо-конфигурацию безопасности (для production со своими сертификатами).

## Основные концепции

### Архитектура развертывания

При проектировании Ansible-плейбуков узлы разделяют по ролям (полная таблица ролей и их ресурсных профилей — в [администрировании](./opensearch_administration.md#роли-узлов-node-roles) и [capacity planning](./opensearch_capacity_planning.md)):

* **cluster_manager**: минимум 3 выделенных узла для кворума.
* **data**: узлы хранения; выделенные диски под `path.data` (в Kubernetes — `volumeClaimTemplates`, см. Helm-ноту).
* **ingest**: узлы предварительной обработки при тяжелых пайплайнах.
* **coordinating**: узлы с пустым списком ролей — выделенные координаторы за балансировщиком.

Порты: **9200** (REST/HTTP, клиентский трафик) и **9300** (transport, межузловое взаимодействие: discovery, репликация). Транспортный порт никогда не проксируется через балансировщик — только 9200.

> Важно: параметры `discovery.seed_hosts` и `cluster.initial_cluster_manager_nodes` должны содержать физические IP-адреса узлов, но никогда — VIP из [Keepalived](./opensearch_high_availability_keepalived.md). Иначе при миграции VIP кластер начнет «переезжать» целиком и потеряет кворум.

### Официальный community-playbook

Проект OpenSearch поддерживает community-репозиторий [opensearch-project/ansible-playbook](https://github.com/opensearch-project/ansible-playbook): требования Ansible 2.9+ и Java 21 (в составе пакета OpenSearch 3.x поставляется bundled JDK); поддерживаемые дистрибутивы — CentOS 7, RHEL 7, Amazon Linux 2, Ubuntu 20.04 (для новых дистрибутивов и версий 3.x роль адаптируется); топология по умолчанию — 3 master + 5 data + 2 ingest узла (одиночный узел — через `cluster_type`); запуск — `ansible-playbook -i inventories/opensearch/hosts opensearch.yml --extra-vars "admin_password=..."` (или с `--become`).

Ниже — референсная структура собственной роли, покрывающая пробелы официального playbook (idempotency, Vault, rolling restart, валидация). Готовые роли на Galaxy (например, `debops.opensearch`, `clusterverse.opensearch`) — альтернатива, но перед использованием проверяйте поддержку версии 3.x.

### Системный тюнинг (System Tuning)

Ansible должен гарантировать применение настроек на целевых хостах:

* **Виртуальная память**: `vm.max_map_count=262144` (модуль `ansible.posix.sysctl`).
* **Лимиты ресурсов**: `nofile=65536` и `memlock=unlimited` в `/etc/security/limits.d/opensearch.conf`.
* **Swap**: полное отключение (`swapoff -a` + очистка `/etc/fstab`) для предотвращения деградации производительности JVM; `vm.swappiness=1` как компромисс, если swap отключить нельзя.
* **JVM Heap**: `-Xms` и `-Xmx` равными 50% RAM, но не более 31 ГБ (Compressed OOPs); подробности — в [capacity planning](./opensearch_capacity_planning.md#правило-heap-и-ram).
* **Синхронизация времени**: chrony/NTP обязателен — рассинхрон часов ломает discovery и репликацию.
* **Firewall**: TCP 9200 и 9300 между узлами кластера; 9200 — для клиентов.

### Модель конфигурации

Пакетная установка (RPM/DEB) создает: пользователя `opensearch`, конфигурацию в `/etc/opensearch/`, данные в `/var/lib/opensearch/`, логи в `/var/log/opensearch/`, systemd-юнит `opensearch.service`, bundled JDK в `/usr/share/opensearch/jdk`. Ansible-роль управляет тремя слоями:

1. **`opensearch.yml`** — статическая конфигурация (шаблон Jinja2, владелец `opensearch:opensearch`, режим 0640).
2. **`jvm.options.d/*.options`** — фрагменты JVM-настроек (heap, GC-логи).
3. **Keystore** (`/etc/opensearch/opensearch.keystore`) — секретные значения; создается автоматически при установке пакета. Изменения keystore применяются перезапуском узла или API `POST _nodes/reload-secure-settings`.

### Безопасность

* **TLS**: генерация и дистрибуция сертификатов (CA, node, admin) — через `openssl` или коллекцию; подходы описаны в [Ansible: управление сертификатами](../../Ansible/ansible_certificate_management.md).
* **Инициализация**: `securityadmin.sh` выполняется один раз на весь кластер после старта всех узлов. Кластер при этом может быть в состоянии **yellow** (скрипт по умолчанию требует как минимум yellow; для red — флаг `-arc/--accept-red-cluster`). Утверждение «запускать только после green» неверно: кластер не может стать green, пока не инициализирован индекс безопасности.
* **Автоинициализация**: `plugins.security.allow_default_init_securityindex: true` — плагин сам загрузит конфигурацию из `config/opensearch-security/` при первом старте первого узла; удобно для автоматизации, но не заменяет `securityadmin.sh` при последующих изменениях.
* **Предусловия securityadmin.sh**: TLS на HTTP-слое (`plugins.security.ssl.http.enabled: true`) и DN административного сертификата в `plugins.security.authcz.admin_dn`.
* **ВНИМАНИЕ**: повторный запуск `securityadmin.sh` перезаписывает изменения, внесенные через REST API. Перед запуском делайте бэкап флагом `-backup <dir>`.

### Rolling restart и обновление

Порядок rolling restart (по одному узлу, `serial: 1`): `PUT _cluster/settings` → `cluster.routing.allocation.enable: primaries` (остановить перемещение шардов на узел) → перезапуск сервиса → ожидание готовности (`_cluster/health?wait_for_status=yellow`) → `cluster.routing.allocation.enable: all`, ожидание green → следующий узел.

Полный restart (мажорные апгрейды): сначала снапшот, затем останов всех узлов, апгрейд, старт с настройками `gateway.recover_after_nodes` / `gateway.expected_nodes` / `gateway.recover_after_time`.

## Практические сценарии

### Prerequisites

* Control node: Ansible 2.15+ (ansible-core), коллекции `ansible.posix`, `community.general`:

```bash
ansible-galaxy collection install ansible.posix community.general
# → Process install dependency map... ok
```

* Managed nodes: RHEL/CentOS 8+ или Ubuntu 20.04+ (для пакетов OpenSearch 3.x), доступ по SSH, `become: true`.
* Сертификаты (CA, node, admin) — заранее или задачей генерации (см. [Ansible: управление сертификатами](../../Ansible/ansible_certificate_management.md)).

### 1. Inventory и переменные

Directory inventory с разделением переменных по ролям (паттерн multi-environment):

```yaml
# inventories/prod/hosts.yml
opensearch_cluster:
  children:
    cluster_managers:
      hosts:
        os-mg-01: { ansible_host: 10.0.1.10, ip: 10.0.1.10 }
        os-mg-02: { ansible_host: 10.0.1.11, ip: 10.0.1.11 }
        os-mg-03: { ansible_host: 10.0.1.12, ip: 10.0.1.12 }
    data_nodes:
      hosts:
        os-dt-01: { ansible_host: 10.0.1.20, ip: 10.0.1.20 }
        os-dt-02: { ansible_host: 10.0.1.21, ip: 10.0.1.21 }
```

```yaml
# inventories/prod/group_vars/all.yml
os_version: "3.9.0"
os_cluster_name: "prod-cluster"
os_home: /usr/share/opensearch
os_config_dir: /etc/opensearch
os_data_dir: /var/lib/opensearch
os_heap_size: "16g"
os_plugins:
  - repository-s3
  - opensearch-prometheus-exporter

# Remote store (опционально; работает с любым S3-совместимым хранилищем,
# включая on-prem MinIO/Ceph; требует сегментной репликации)
os_remote_store_enabled: false
os_remote_store_repository: "my-s3-repo"

# Секреты — только через Ansible Vault:
# ansible-vault encrypt_string 'StrongPass!1' --name 'os_admin_password'
os_admin_password: !vault |
          $ANSIBLE_VAULT;1.1;AES256
          613238...
```

```yaml
# inventories/prod/group_vars/cluster_managers.yml
os_node_roles: [cluster_manager]
# inventories/prod/group_vars/data_nodes.yml
os_node_roles: [data]
```

### 2. Установка пакета OpenSearch

RPM (RHEL/CentOS):

```yaml
- name: Import OpenSearch GPG key
  ansible.builtin.rpm_key:
    key: https://artifacts.opensearch.org/publickeys/opensearch-release.pgp
    state: present

- name: Add OpenSearch YUM repository
  ansible.builtin.get_url:
    url: https://artifacts.opensearch.org/releases/bundle/opensearch/3.x/opensearch-3.x.repo
    dest: /etc/yum.repos.d/opensearch-3.x.repo
    owner: root
    group: root
    mode: '0644'

- name: Install OpenSearch (pinned version)
  ansible.builtin.yum:
    name: "opensearch-{{ os_version }}"
    state: present
  environment:
    OPENSEARCH_INITIAL_ADMIN_PASSWORD: "{{ os_admin_password }}"
    # DISABLE_INSTALL_DEMO_CONFIG: "true"  # раскомментировать для своих сертификатов
```

APT (Ubuntu/Debian):

```yaml
- name: Add OpenSearch APT key
  ansible.builtin.apt_key:
    url: https://artifacts.opensearch.org/publickeys/opensearch-release.pgp
    keyring: /etc/apt/keyrings/opensearch.gpg
    state: present

- name: Add OpenSearch APT repository
  ansible.builtin.apt_repository:
    repo: "deb [signed-by=/etc/apt/keyrings/opensearch.gpg] https://artifacts.opensearch.org/releases/bundle/opensearch/3.x/apt stable main"
    state: present
    filename: opensearch-3.x
    update_cache: true

- name: Install OpenSearch (pinned version)
  ansible.builtin.apt:
    name: "opensearch={{ os_version }}"
    state: present
  environment:
    OPENSEARCH_INITIAL_ADMIN_PASSWORD: "{{ os_admin_password }}"
```

Проверка установки:

```bash
rpm -q opensearch
# → opensearch-3.9.0-1.x86_64
systemctl is-enabled opensearch
# → enabled
```

> Пининг версии (`opensearch-3.9.0`) обязателен: без него `yum update` подтянет следующий минорный релиз, что может сломать совместимость плагинов. Для RHEL — `yum versionlock add opensearch`; для APT — `apt-mark hold opensearch`.

### 3. Системный тюнинг хоста

```yaml
- name: OpenSearch kernel parameters
  ansible.posix.sysctl:
    name: "{{ item.name }}"
    value: "{{ item.value }}"
    sysctl_set: true
    state: present
    reload: true
  loop:
    - { name: vm.max_map_count, value: '262144' }
    - { name: vm.swappiness, value: '1' }
    - { name: net.ipv4.ip_nonlocal_bind, value: '1' }  # только при использовании Keepalived VIP

- name: OpenSearch resource limits
  ansible.builtin.copy:
    dest: /etc/security/limits.d/opensearch.conf
    content: |
      opensearch soft nofile 65536
      opensearch hard nofile 65536
      opensearch soft memlock unlimited
      opensearch hard memlock unlimited
    owner: root
    group: root
    mode: '0644'

- name: Disable swap
  ansible.builtin.command: swapoff -a
  when: ansible_swaptotal_mb > 0
  changed_when: true

- name: Remove swap entries from fstab
  ansible.builtin.lineinfile:
    path: /etc/fstab
    regexp: '^\s*[^#\s]+\s+swap\s+swap'
    state: absent

- name: Open firewall ports
  ansible.posix.firewalld:
    port: "{{ item }}/tcp"
    permanent: true
    state: enabled
    immediate: true
  loop:
    - 9200
    - 9300
```

Проверка:

```bash
sysctl vm.max_map_count
# → vm.max_map_count = 262144
grep opensearch /etc/security/limits.d/opensearch.conf
# → opensearch soft nofile 65536 ...
```

### 4. Шаблон opensearch.yml и JVM heap

```yaml
- name: Deploy opensearch.yml
  ansible.builtin.template:
    src: opensearch.yml.j2
    dest: "{{ os_config_dir }}/opensearch.yml"
    owner: opensearch
    group: opensearch
    mode: '0640'
  notify: restart opensearch
```

```yaml
# templates/opensearch.yml.j2
cluster.name: {{ os_cluster_name }}
node.name: {{ ansible_hostname }}
node.roles: {{ os_node_roles | to_json }}

path.data: {{ os_data_dir }}
path.logs: /var/log/opensearch

network.host: {{ ip }}
http.port: 9200
transport.port: 9300

discovery.seed_hosts: {{ groups['cluster_managers'] | map('extract', hostvars, ['ip']) | list | to_json }}
{% if os_bootstrap | default(false) %}
cluster.initial_cluster_manager_nodes: {{ groups['cluster_managers'] | to_json }}
{% endif %}

bootstrap.memory_lock: true
action.destructive_requires_name: true

plugins.security.ssl.transport.enabled: true
plugins.security.ssl.transport.pemcert_filepath: certs/node.pem
plugins.security.ssl.transport.pemkey_filepath: certs/node-key.pem
plugins.security.ssl.transport.pemtrustedcas_filepath: certs/root-ca.pem

plugins.security.ssl.http.enabled: true
plugins.security.ssl.http.pemcert_filepath: certs/node-http.pem
plugins.security.ssl.http.pemkey_filepath: certs/node-http-key.pem
plugins.security.ssl.http.pemtrustedcas_filepath: certs/root-ca.pem

plugins.security.authcz.admin_dn:
  - "CN=admin,OU=Ops,O=Example,C=RU"

plugins.security.allow_default_init_securityindex: true

{% if os_remote_store_enabled %}
cluster.remote_store.enabled: true
cluster.remote_store.repository: {{ os_remote_store_repository }}
cluster.remote_store.repository.state: {{ os_remote_store_repository }}
{% endif %}
```

```yaml
- name: Configure JVM heap
  ansible.builtin.copy:
    dest: "{{ os_config_dir }}/jvm.options.d/heap.options"
    content: |
      -Xms{{ os_heap_size }}
      -Xmx{{ os_heap_size }}
    owner: opensearch
    group: opensearch
    mode: '0644'
  notify: restart opensearch
```

Переменная `os_bootstrap` задается один раз при первом поднятии кластера (список начальных cluster manager узлов); после инициализации кластера её убирают — `cluster.initial_cluster_manager_nodes` не должен присутствовать в работающем кластере.

### 5. Плагины и keystore (идемпотентно)

```yaml
- name: Get installed plugins
  ansible.builtin.command: "bin/opensearch-plugin list"
  args:
    chdir: "{{ os_home }}"
  become_user: opensearch
  register: installed_plugins
  changed_when: false

- name: Install OpenSearch plugins
  ansible.builtin.command: "bin/opensearch-plugin install --batch {{ item }}"
  args:
    chdir: "{{ os_home }}"
  become_user: opensearch
  loop: "{{ os_plugins }}"
  when: item not in installed_plugins.stdout_lines
  notify: restart opensearch

- name: Add S3 credentials to Keystore
  ansible.builtin.shell: |
    echo "{{ s3_access_key }}" | bin/opensearch-keystore add --stdin --force s3.client.default.access_key
    echo "{{ s3_secret_key }}" | bin/opensearch-keystore add --stdin --force s3.client.default.secret_key
  args:
    chdir: "{{ os_home }}"
  become_user: opensearch
  no_log: true
  when: os_remote_store_enabled | bool
  notify: reload secure settings
```

```yaml
# handlers/main.yml
- name: restart opensearch
  ansible.builtin.systemd:
    name: opensearch
    state: restarted

- name: reload secure settings
  ansible.builtin.uri:
    url: "https://{{ ansible_host }}:9200/_nodes/reload-secure-settings"
    method: POST
    validate_certs: false
    force_basic_auth: true
    url_username: admin
    url_password: "{{ os_admin_password }}"
    status_code: 200
```

Ключевые моменты:

* `--batch` делает установку плагина неинтерактивной; проверка `opensearch-plugin list` обеспечивает идемпотентность (без неё задача будет «changed» при каждом прогоне).
* `--stdin` читает значение секрета из stdin (вместо промпта); `--force` перезаписывает существующее значение; `no_log: true` обязателен, секреты хранятся в Ansible Vault.
* `POST _nodes/reload-secure-settings` применяет изменения keystore без полного перезапуска узла.

### 6. Инициализация безопасности (securityadmin.sh)

```yaml
- name: Initialize OpenSearch security configuration
  ansible.builtin.command: >
    {{ os_home }}/plugins/opensearch-security/tools/securityadmin.sh
    -cd {{ os_config_dir }}/opensearch-security/
    -icl -nhnv
    -h {{ ansible_host }}
    -cacert {{ os_config_dir }}/root-ca.pem
    -cert {{ os_config_dir }}/admin.pem
    -key {{ os_config_dir }}/admin-key.pem
    -backup {{ os_config_dir }}/opensearch-security-backup
  become_user: opensearch
  run_once: true
  delegate_to: "{{ groups['cluster_managers'][0] }}"
```

Поведение скрипта (проверено по документации):

* Выполняется, только если кластер в состоянии **yellow или green**; для red — добавить `-arc` (`--accept-red-cluster`).
* `-icl` — игнорировать имя кластера; `-nhnv` — не проверять hostname в сертификате (для self-signed); `-h` — хост (по умолчанию localhost), порт по умолчанию 9200.
* `-cd <dir>` — применить все YAML из каталога; `-f <file> -t <type>` — один файл; `-backup <dir>` — выгрузить текущую живую конфигурацию перед перезаписью.
* Полный список флагов и модель безопасности — в [администрировании](./opensearch_administration.md#модель-конфигурации-безопасности).

Альтернатива для первого старта: `plugins.security.allow_default_init_securityindex: true` в `opensearch.yml` — плагин сам инициализирует индекс из файлов `config/opensearch-security/` при первом запуске.

### 7. Валидация кластера

```yaml
- name: Wait for OpenSearch API
  ansible.builtin.uri:
    url: "https://{{ ansible_host }}:9200/_cluster/health"
    validate_certs: false
    force_basic_auth: true
    url_username: admin
    url_password: "{{ os_admin_password }}"
    return_content: true
    status_code: 200
  register: health
  until: health.json.status is defined and health.json.status in ['yellow', 'green']
  retries: 30
  delay: 10

- name: Show cluster nodes
  ansible.builtin.uri:
    url: "https://{{ ansible_host }}:9200/_cat/nodes?v&format=json"
    validate_certs: false
    force_basic_auth: true
    url_username: admin
    url_password: "{{ os_admin_password }}"
    return_content: true
  register: nodes
```

Ожидаемый вывод проверочных команд на узле:

```bash
curl -k -u admin:password https://localhost:9200/_cluster/health?pretty
# → {
# →   "cluster_name" : "prod-cluster",
# →   "status" : "yellow",
# →   "number_of_nodes" : 5,
# →   ...
# → }

curl -k -u admin:password https://localhost:9200/_cat/allocation?v
# → node  shards disk.indices disk.used disk.total disk.percent
# → os-dt-01  20   15gb        40gb      1tb        4
```

### 8. Rolling restart

```yaml
- name: Drain node — stop shard allocation to it
  ansible.builtin.uri:
    url: "https://{{ ansible_host }}:9200/_cluster/settings"
    method: PUT
    body_format: json
    validate_certs: false
    force_basic_auth: true
    url_username: admin
    url_password: "{{ os_admin_password }}"
    body:
      transient:
        cluster.routing.allocation.enable: primaries
    status_code: 200

- name: Restart OpenSearch
  ansible.builtin.systemd:
    name: opensearch
    state: restarted

- name: Wait for node to rejoin
  ansible.builtin.uri:
    url: "https://{{ ansible_host }}:9200/_cluster/health?wait_for_status=yellow&timeout=50s"
    validate_certs: false
    force_basic_auth: true
    url_username: admin
    url_password: "{{ os_admin_password }}"
    status_code: 200

- name: Re-enable shard allocation
  ansible.builtin.uri:
    url: "https://{{ ansible_host }}:9200/_cluster/settings"
    method: PUT
    body_format: json
    validate_certs: false
    force_basic_auth: true
    url_username: admin
    url_password: "{{ os_admin_password }}"
    body:
      transient:
        cluster.routing.allocation.enable: all
    status_code: 200
```

Плейбук запускается с `serial: 1`, чтобы узлы перезапускались по одному:

```bash
ansible-playbook -i inventories/prod/hosts.yml restart.yml --serial 1
# → PLAY [opensearch_cluster] **************************************************
# → TASK [Drain node] ... changed: [os-dt-01]
# → ...
```

### 9. Балансировка трафика через Nginx

Nginx терминирует SSL и распределяет запросы к API (порт 9200). Транспортный порт 9300 через балансировщик не проксируется.

```nginx
upstream opensearch_api {
    server 10.0.1.20:9200;
    server 10.0.1.21:9200;
    keepalive 64;
}

server {
    listen 9200 ssl;
    http2 on;  # nginx 1.25.1+; в старых версиях — параметр http2 в listen
    server_name os-api.example.com;

    ssl_certificate /etc/nginx/ssl/os-api.crt;
    ssl_certificate_key /etc/nginx/ssl/os-api.key;

    location / {
        proxy_pass https://opensearch_api;
        proxy_http_version 1.1;
        proxy_set_header Connection "";
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_next_upstream error timeout http_502 http_503;

        # Увеличенные таймауты для тяжелых агрегаций
        proxy_read_timeout 180s;
    }
}
```

Проверка:

```bash
curl -k https://os-api.example.com:9200/_cluster/health
# → {"cluster_name":"prod-cluster","status":"yellow",...}
```

Альтернатива без прокси — плавающий VIP через Keepalived: [Отказоустойчивость с Keepalived](./opensearch_high_availability_keepalived.md). Конфигурация OpenSearch Dashboards (отдельный пакет `opensearch-dashboards`, `opensearch.hosts`, `opensearch.ssl.verificationMode`) — в [отдельной заметке](./opensearch_dashboards.md).

### 10. Обновление версии

Rolling upgrade (минорные версии, например 3.8.0 → 3.9.0):

1. Снапшот кластера (см. [администрирование](./opensearch_administration.md)).
2. Плейбук установки с новой версией в `os_version` + сценарий rolling restart (сценарий 8) — по одному узлу.
3. Валидация (сценарий 7).

Полный restart (мажорные апгрейды): снапшот → останов всех узлов → апгрейд пакетов (`yum update opensearch-<version>` / `rpm -Uvh opensearch-<version>-linux-x64.rpm`) → старт с настройками `gateway.recover_after_nodes: 2`, `gateway.expected_nodes: 5`, `gateway.recover_after_time: 5m` → ожидание green → удаление настроек gateway.

## Troubleshooting

| Симптом | Причина | Решение |
| :--- | :--- | :--- |
| `max virtual memory areas vm.max_map_count [65530] is too low` | sysctl не применен | Задача `ansible.posix.sysctl` с `sysctl_set: true, reload: true`; проверить `sysctl vm.max_map_count` |
| `memory locking requested... but memory is not locked` | лимит `memlock` не применен или `bootstrap.memory_lock: true` без `memlock unlimited` | Проверить `/etc/security/limits.d/opensearch.conf` и перелогиниться (лимиты PAM применяются при входе) |
| `OpenSearch Security not initialized` | `securityadmin.sh` не выполнен или упал | Проверить состояние кластера (нужно ≥ yellow); для red добавить `-arc`; проверить `admin_dn` и TLS на HTTP-слое |
| `Timed out while waiting for a green or yellow cluster state` | Неверное имя кластера или hostname в сертификате | Добавить `-icl -nhnv`; проверить `-h` и порт; запустить с `--diagnose` и разобрать trace-файл |
| `FileAlreadyExistsException: opensearch.keystore.tmp` | Сталый временный файл keystore | Удалить `.tmp`-файл; использовать `--force` при добавлении существующего ключа |
| Узел не стартует после правки конфига | Синтаксическая ошибка YAML или неверный владелец файлов | `journalctl -u opensearch -n 50`; владелец конфигов — `opensearch:opensearch`, режим 0640 |
| Кластер red после полного рестарта | Шарды не восстанавливаются автоматически | Настройки `gateway.recover_after_nodes` / `gateway.expected_nodes`; проверить `_cluster/allocation/explain` |
| Discovery не находит узлы | `discovery.seed_hosts` содержит VIP или неверные адреса | Только физические IP:9300; проверить firewall для 9300 |
| Плагин устанавливается бесконечно | Интерактивный промпт | Флаг `--batch` в `opensearch-plugin install` |

## Best Practices

* **Пининг версии** пакета и плагинов; `yum versionlock` / `apt-mark hold` против незапланированных апгрейдов.
* **Секреты только в Ansible Vault** (`ansible-vault encrypt_string`), `no_log: true` на задачах с секретами; детали — в [Ansible: рекомендации по безопасности](../../Ansible/ansible_security_best_practices.md).
* **Идемпотентность**: проверка `opensearch-plugin list` перед установкой, `creates`/`register` вместо слепого `command`.
* **Handlers и `serial: 1`** для rolling restart; никогда не перезапускать все узлы одновременно.
* **Бэкап перед securityadmin.sh** (`-backup <dir>`) — скрипт перезаписывает изменения из REST API.
* **Тестирование роли**: Molecule + ansible-lint перед прогоном в prod — [Ansible: тестирование с Molecule](../../Ansible/ansible_testing_with_molecule.md), [ansible-lint](../../Ansible/ansible_lint_guide.md).
* **Изоляция окружений**: отдельный directory inventory на dev/staging/prod — [Ansible — управление мультисредами](../../Ansible/ansible_multi_environment_management.md).
* **Конфиги в Git**: `/etc/opensearch/` (кроме секретов) как код; промоушен через окружения.
* **Структура роли** и антипаттерны — [Ansible: роли](../../Ansible/ansible_roles.md), [Ansible: плохие практики](../../Ansible/ansible_bad_practices.md).
* **Hardening хоста** за пределами OpenSearch — [Ansible: hardening ОС](../../Ansible/ansible-os-hardening.md).

## Дополнительная информация

* **[OpenSearch: Обзор системы](./opensearch_overview.md)** — архитектура и основные компоненты.
* **[Администрирование OpenSearch](./opensearch_administration.md)** — модель безопасности, securityadmin.sh, снапшоты, RBS.
* **[Capacity Planning](./opensearch_capacity_planning.md)** — sizing узлов, шардов, heap.
* **[Отказоустойчивость с Keepalived](./opensearch_high_availability_keepalived.md)** — плавающий VIP для API.
* **[OpenSearch Dashboards](./opensearch_dashboards.md)** — конфигурация веб-интерфейса.
* **[Helm-развертывание](./opensearch_helm_deployment.md)** — альтернатива для Kubernetes.
* **[Ansible: роли](../../Ansible/ansible_roles.md)**, **[мультисреды](../../Ansible/ansible_multi_environment_management.md)**, **[стратегии деплоя](../../Ansible/ansible_deployment_strategies.md)**, **[безопасность](../../Ansible/ansible_security_best_practices.md)**, **[Molecule](../../Ansible/ansible_testing_with_molecule.md)**, **[сертификаты](../../Ansible/ansible_certificate_management.md)**, **[hardening](../../Ansible/ansible-os-hardening.md)**.
* **[Официальный community-playbook](https://github.com/opensearch-project/ansible-playbook)** — репозиторий проекта OpenSearch.
* **[Документация: Ansible playbook](https://docs.opensearch.org/latest/install-and-configure/install-opensearch/ansible/)** — установка через официальный playbook.
* **[Документация: установка RPM/DEB](https://docs.opensearch.org/latest/install-and-configure/install-opensearch/rpm/)** — репозитории и пакеты.
