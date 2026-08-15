# Динамический инвентарь в Ansible

## Определения

- **Динамический инвентарь** — это механизм Ansible, который формирует список управляемых узлов (хостов) и их переменные «на лету», обращаясь к внешнему источнику правды (Single Source of Truth, SSoT). В отличие от статического файла, он всегда отражает актуальное состояние инфраструктуры, что критично для облачных и эфемерных сред.
- **Плагин инвентаря (Inventory Plugin)** — современный, нативный и рекомендуемый способ реализации (Ansible 2.4+), использующий YAML-конфигурации и поддерживающий кэширование.

## Основные концепции

### Когда это необходимо

- **Эфемерные среды и автоскейлинг**: Облачные экземпляры создаются и удаляются автоматически, статический список моментально устаревает.
- **Мультиоблако и мультиаккаунты**: Необходимо объединять ресурсы из нескольких провайдеров (AWS, GCP, Azure) и учетных записей.
- **Теги и метки как источник групп**: Возможность формировать группы по метаданным (`Role`, `Environment`, `Stage`, `Owner`) без ручной правки инвентаря.
- **Контейнерные платформы**: Получение актуального списка узлов и сервисов через API кластеров (Kubernetes, Nomad).
- **Синхронизация с CMDB**: Автоматическое получение данных из корпоративных систем учета (NetBox, iTop).

### Способы реализации

1. **Плагины инвентаря (Inventory plugins)**: Предпочтительный, нативный способ. Ansible предоставляет плагины для большинства облаков и сервисов (например, `yandex.cloud.yandex_cloud`, `amazon.aws.aws_ec2`, `community.vmware.vmware_vm_inventory`, `kubernetes.core.k8s`). Конфигурируются через YAML-файлы.
2. **Исполняемые скрипты**: Любой исполняемый файл (на Python, Bash и др.), который при запуске с флагом `--list` возвращает **JSON** в специальном формате. Этот способ считается legacy и уступает место плагинам, но все еще используется для специфических самописных систем.
3. **Комбинированный подход (Directory Inventory)**: Директория `inventories/` может содержать несколько источников (статические файлы `hosts.ini` и динамические конфигурации `.yml`), которые Ansible объединяет в один логический инвентарь.

### Производительность и кэширование

Обращения к внешним API могут значительно замедлять генерацию инвентаря, особенно в крупных инфраструктурах. Для решения этой проблемы рекомендуется:

- **Включать кэширование** на уровне инвентарного плагина или глобально в `ansible.cfg`.
- **Использовать фильтры** в конфигурации плагина, чтобы ограничивать область поиска на стороне API (например, только `running` инстансы).
- **Использовать `compose`** для формирования хостовых переменных (**hostvars**) только из необходимых данных.
- **«Прогревать» кэш** в пайплайнах **CI/CD**, запуская `ansible-inventory` перед основным плейбуком.

**Пример настройки кэширования в `ansible.cfg`:**

```ini
[inventory]
# Включение нужных плагинов (порядок имеет значение)
enable_plugins = amazon.aws.aws_ec2, yandex.cloud.yandex_cloud, vmware.vmware.vmware_vm_inventory, yaml, ini, script
cache = True
cache_plugin = jsonfile
cache_timeout = 3600
cache_connection = ~/.ansible/cache/inventory
```

### Механизмы keyed_groups и compose

Это мощные инструменты плагинов для динамического формирования структуры инвентаря:

- **`keyed_groups`**: Создает группы на основе значений атрибутов хоста.
  - `key`: Путь к данным в словаре метаданных (Jinja2).
  - `prefix`: Префикс для имени группы (например, `tag_Role_web`).
- **`compose`**: Создает или переопределяет переменные хоста. Часто используется для установки `ansible_host` из конкретного интерфейса.

## Практические сценарии

### Сравнение статического и динамического подходов

| Критерий | Статический инвентарь | Динамический инвентарь |
| :--- | :--- | :--- |
| **Актуальность** | Требует ручного обновления | Вытягивается из источника правды |
| **Масштабируемость** | Ограничена размером файла | Горизонтально масштабируется |
| **Человеческий фактор**| Высокий риск ошибок | Снижается за счет автоматизации |
| **Группировка** | Ручные группы | Автоматически, по тегам/фильтрам |
| **Производительность**| Быстро локально | Требует кэширования для API |

### Инвентарь на основе состояния Terraform

Распространенным паттерном является использование данных Terraform как источника правды.

#### 1. Использование плагинов для Terraform State (Современный метод)
Использование специализированных плагинов (например, из коллекции `cloud.terraform`), которые читают файл состояния (`terraform.tfstate`) напрямую.

```yaml
plugin: cloud.terraform.terraform_provider
project_path: /path/to/terraform/project
# Плагин автоматически найдет ресурсы и создаст хосты на основе state-файла
```

#### 2. Генерация через промежуточный JSON (Legacy/Custom)
Подход с ручной генерацией на основе вывода `terraform output`, полезен при отсутствии подходящего плагина:

1. Terraform описывает данные (**IP-адреса**, имена хостов) в блоках `output`.

    ```hcl
    output "instance_ips" {
      value = {
        for vm in yandex_compute_instance.my_vms:
        vm.name => vm.network_interface.0.nat_ip_address
      }
    }
    ```

2. Вывод сохраняется в JSON-файл после применения (`terraform apply`).

    ```bash
    terraform output -json > tf_output.json
    ```

3. Кастомный скрипт (или плагин `file`) парсит этот JSON и генерирует инвентарь.

### Настройка динамического инвентаря AWS (EC2)

Для работы с AWS используется плагин `aws_ec2` из коллекции `amazon.aws`. Файл инвентаря должен заканчиваться на `aws_ec2.yml` или `aws_ec2.yaml`.

```yaml
plugin: amazon.aws.aws_ec2
regions:
  - eu-central-1
  - us-east-1
# Использование профиля AWS CLI для авторизации
profile: production_admin
# Фильтрация только запущенных инстансов с определенным тегом
filters:
  instance-state-name: running
  "tag:Environment": production
# Группировка хостов по тегам и зонам доступности
keyed_groups:
  - key: tags.Role
    prefix: role
  - key: placement.availability_zone
    prefix: az
# Динамическое определение IP для подключения
compose:
  ansible_host: public_ip_address | default(private_ip_address)
```

### Настройка динамического инвентаря Yandex Cloud

Необходимо установить коллекцию: `ansible-galaxy collection install yandex.cloud`. Файл инвентаря с расширением `.yc.yml`.

```yaml
plugin: yandex.cloud.yandex_cloud
folder_id: "b1g..." # ID каталога в Yandex Cloud
service_account_key_file: "./key.json" # Путь к JSON-ключу сервисного аккаунта
# Настройка имен хостов в инвентаре
hostnames:
  - "{{ labels.role }}-{{ name }}"
# Группировка хостов по метке 'role'
keyed_groups:
  - key: labels.role
    prefix: role
# Настройка IP-адреса для подключения
compose:
  ansible_host: network_interfaces[0].primary_v4_address.one_to_one_nat.address
```

### Настройка динамического инвентаря Kubernetes

Позволяет использовать поды как хосты для выполнения плейбуков. Полезно для задач обслуживания внутри контейнеров. Подробнее об автоматизации см.: **[Автоматизация Kubernetes через Ansible](./ansible-kubernetes-automation.md)**.

```yaml
# inventory_k8s.yml
plugin: kubernetes.core.k8s
connections:
  - namespaces:
      - production
    labels:
      app: web-server
# Создает группы на основе меток (labels) подов
keyed_groups:
  - key: metadata.labels
    prefix: label
```

### Интеграция с CMDB (NetBox)

NetBox часто выступает единым источником правды (SSoT) для всей инфраструктуры. Плагин `nb_inventory` из коллекции `netbox.netbox`.

См. также: [Автоматизация заполнения NetBox через API](../Networking/NetBox/netbox-automation-python.md).

```yaml
plugin: netbox.netbox.nb_inventory
api_endpoint: https://netbox.example.com
token: "YOUR_NETBOX_API_TOKEN" # Рекомендуется через env: {{ lookup('env', 'NETBOX_TOKEN') }}
validate_certs: true
# Фильтрация по статусу устройства
status:
  - Active
# Группировка устройств по ролям, сайтам и платформам
group_by:
  - device_roles
  - sites
  - platforms
# Формирование ansible_host из первичного IP-адреса в NetBox
compose:
  ansible_host: primary_ip4.address | regex_replace('/.*$', '')
```

### Интеграция с Service Discovery (Consul)

Использование Consul как источника инвентаря идеально подходит для динамических сред вне Kubernetes (например, классические ВМ с установленным Consul Agent). Плагин `consul` из коллекции `community.general` позволяет автоматически получать список хостов на основе зарегистрированных сервисов и их тегов.

```yaml
plugin: community.general.consul
consul_url: http://consul.example.com:8500
# Авторизация (рекомендуется использовать ACL токены)
token: "{{ lookup('env', 'CONSUL_HTTP_TOKEN') }}"

# Фильтрация хостов: только те, что прошли Health Checks
filter: "Service.Status == 'passing'"

# Группировка хостов
keyed_groups:
  - key: Service
    prefix: svc
  - key: Tags
    prefix: tag
  - key: Datacenter
    prefix: dc

# Сопоставление переменных хоста
compose:
  ansible_host: Address
  consul_node_name: Node
```

**Особенности:**
- **Health-aware**: Можно исключать хосты, которые помечены как `critical` или `warning` в Consul.
- **Гибкость**: Позволяет использовать метаданные сервисов (`ServiceMeta`) для формирования переменных Ansible.

### Интеграция с KV-хранилищами (Etcd)

Etcd (версии 3) может использоваться как низкоуровневое хранилище данных об инвентаре. Это полезно для кастомных систем оркестрации, где список хостов и их параметры хранятся в виде иерархии ключей. Используется плагин `etcd3` из коллекции `community.general`.

```yaml
plugin: community.general.etcd3
host: "etcd-cluster.example.com"
port: 2379
user: "ansible"
password: "password"

# Префикс ключей, под которыми хранится инвентарь
key_prefix: "/ansible/inventory/hosts/"

# Использование сертификатов (рекомендуется)
cert_file: "/path/to/cert.pem"
key_file: "/path/to/key.pem"
ca_cert: "/path/to/ca.pem"
```

**Особенности:**
- **Структура ключей**: Плагин ожидает, что данные в etcd хранятся в формате JSON или YAML.
- **Производительность**: Хорошо подходит для очень больших, но стабильных списков хостов, где Consul может быть избыточен.

### Безопасность и управление секретами

Конфигурации динамического инвентаря содержат токены и ключи доступа.
1. **Переменные окружения**: Плагины по умолчанию поддерживают переменные типа `AWS_ACCESS_KEY_ID` или `YC_TOKEN`. Это наиболее безопасный способ для CI/CD.
2. **Ansible Vault**: Если ключи хранятся в `.yml` файле инвентаря, его необходимо зашифровать:
   ```bash
   ansible-vault encrypt inventories/prod.aws_ec2.yml
   ```
3. **No Log**: При написании кастомных скриптов убедитесь, что они не выводят чувствительные данные в `stderr` или логи.

### Проверка и отладка динамического инвентаря

Для валидации работы плагинов используются следующие команды:

```bash
# 1. Вывести инвентарь в виде дерева групп (быстрая проверка структуры)
ansible-inventory -i <файл_инвентаря> --graph

# 2. Вывести полный JSON-объект со всеми хост-переменными (проверка hostvars)
ansible-inventory -i <файл_инвентаря> --list

# 3. Отладка конкретного хоста
ansible-inventory -i <файл_инвентаря> --host <имя_хоста>

# 4. Проверка с очисткой кэша
ansible-inventory -i <файл_инвентаря> --list --flush-cache

# 5. Режим отладки (показывает ошибки подключения к API)
ansible-inventory -i <файл_инвентаря> --list -vvvv
```

## Дополнительная информация

- [Установка и настройка Ansible](ansible_setup_and_config.md) — базовые концепции инвентаря.
- [Официальная документация по плагинам инвентаря](https://docs.ansible.com/ansible/latest/plugins/inventory.html)
- [Структура проекта](examples/example_project_layout.md) — организация файлов и каталогов.
- [Ansible Vault: Лучшие практики](Vault/best_practices.md) — шифрование конфигураций инвентаря.
- [Оптимизация производительности](ansible_performance_tuning.md) — тюнинг SSH и кэширования.
