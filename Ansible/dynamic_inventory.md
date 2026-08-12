# Динамический инвентарь в Ansible

## Определения

- **Динамический инвентарь**: Механизм Ansible, который формирует список хостов и их переменные «на лету», обращаясь к внешнему источнику правды (облачная платформа, **CMDB**, **API**). В отличие от статического файла, он всегда отражает актуальное состояние инфраструктуры.

## Основные концепции

### Когда это необходимо

- **Эфемерные среды и автоскейлинг**: Облачные экземпляры создаются и удаляются автоматически, статический список моментально устаревает.
- **Мультиоблако и мультиаккаунты**: Необходимо объединять ресурсы из нескольких провайдеров и учетных записей.
- **Теги и метки как источник групп**: Возможность формировать группы по метаданным (`Role`, `Environment`, `Stage`, `Owner`) без ручной правки инвентаря.
- **Контейнерные платформы**: Получение актуального списка узлов и сервисов через API кластеров (Kubernetes, Nomad).
- **Синхронизация с CMDB**: Автоматическое получение данных из корпоративных систем учета.

### Способы реализации

1. **Плагины инвентаря (Inventory plugins)**: Предпочтительный, нативный способ. Ansible предоставляет плагины для большинства облаков и сервисов (например, `yandex.cloud.yandex_cloud`, `community.vmware.vmware_vm_inventory`, `kubernetes.core.k8s`).
2. **Исполняемые скрипты**: Любой исполняемый файл (на Python, Bash и др.), который при запуске с флагом `--list` возвращает **JSON** в специальном формате. Этот способ считается legacy и уступает место плагинам инвентаря.
3. **Комбинированный подход**: Директория `inventories/` может содержать несколько источников (статические и динамические файлы), которые Ansible объединяет в один инвентарь.

### Производительность и кэширование

Обращения к внешним API могут замедлять генерацию инвентаря. Для решения этой проблемы рекомендуется:

- **Включать кэширование** на уровне инвентарного плагина или глобально в `ansible.cfg`.
- **Использовать фильтры** в конфигурации плагина, чтобы ограничивать область поиска.
- **Использовать `compose`** для хостовых переменных (**hostvars**) только для необходимых данных.
- **«Прогревать» кэш** в пайплайнах **CI/CD**, запуская `ansible-inventory` перед основным плейбуком.

**Пример настройки кэширования в `ansible.cfg`:**

```ini
[inventory]
enable_plugins = yandex.cloud.yandex_cloud, vmware.vmware.vmware_vm_inventory, yaml, ini, script
cache = True
cache_plugin = jsonfile
cache_timeout = 600
cache_connection = .cache/inventory
```

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

Распространенным паттерном является использование данных Terraform как источника правды. Существует два подхода:

#### 1. Использование плагинов для Terraform State
Современный способ — использование специализированных плагинов (например, из коллекции `cloud.terraform`), которые читают файл состояния (`terraform.tfstate`) напрямую.

```yaml
plugin: cloud.terraform.terraform_provider
project_path: /path/to/terraform/project
# Плагин автоматически найдет ресурсы и создаст хосты
```

#### 2. Генерация через промежуточный JSON (Legacy)
Подход с ручной генерацией на основе вывода `terraform output`:

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

3. Кастомный скрипт парсит этот JSON и генерирует инвентарь.

### Настройка динамического инвентаря AWS (EC2)

Для работы с AWS используется плагин `aws_ec2` из коллекции `amazon.aws`. Файл инвентаря должен заканчиваться на `aws_ec2.yml` или `aws_ec2.yaml` (например, `inventory_aws_ec2.yml`).

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
# Использовать публичный IP-адрес для подключения, если есть
compose:
  ansible_host: public_ip_address | default(private_ip_address)
```

### Настройка динамического инвентаря Yandex Cloud

Для работы необходимо установить коллекцию: `ansible-galaxy collection install yandex.cloud`. Создайте файл инвентаря с расширением `.yc.yml` (например, `hosts.yc.yml`):

```yaml
plugin: yandex.cloud.yandex_cloud
folder_id: "b1g..." # ID каталога в Yandex Cloud
service_account_key_file: "./key.json" # Путь к JSON-ключу сервисного аккаунта
# Группировка хостов по метке 'role'
hostnames:
  - "{{ labels.role }}-{{ name }}"
keyed_groups:
  - key: labels.role
    prefix: role
# Настройка IP-адреса для подключения
compose:
  ansible_host: network_interfaces[0].primary_v4_address.one_to_one_nat.address
```
### Интеграция с CMDB (NetBox)

NetBox часто выступает единым источником правды (SSoT) для сетевой инфраструктуры и DCIM. Коллекция `netbox.netbox` предоставляет плагин `nb_inventory`. Файл конфигурации обычно называется `netbox_inventory.yml`.

См. также: [Автоматизация заполнения NetBox через API](../Networking/NetBox/netbox-automation-python.md).

```yaml
plugin: netbox.netbox.nb_inventory
...
api_endpoint: https://netbox.example.com
token: "YOUR_NETBOX_API_TOKEN"
validate_certs: true
# Фильтрация по статусу устройства (только активные)
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

### Проверка динамического инвентаря

Проверка работы любого динамического инвентаря выполняется командами:
```bash
# Вывести инвентарь в виде дерева
ansible-inventory -i <файл_инвентаря> --graph

# Вывести полный JSON-объект со всеми хост-переменными
ansible-inventory -i <файл_инвентаря> --list
```

## Дополнительная информация

- [Установка и настройка Ansible](ansible_setup_and_config.md) — базовые концепции инвентаря.
- [Официальная документация по плагинам инвентаря](https://docs.ansible.com/ansible/latest/plugins/inventory.html)
- [Структура проекта](examples/example_project_layout.md) — организация файлов и каталогов.
