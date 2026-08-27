# Ansible Collections: создание, публикация и управление

## Определения

- **Collection** — единый пакет контента Ansible (роли, модули, плагины, тесты, документация), распространяемый через Galaxy или внутренний реестр
- **Namespace** — пространство имён коллекции (например, `company` или `community`)
- **galaxy.yml** — манифест коллекции, описывающий метаданные, зависимости и версию
- **FQCN (Fully Qualified Collection Name)** — формат `namespace.collection.resource` для однозначной идентификации ресурсов
- **Collection artifacts** — tar.gz архивы, генерируемые `ansible-galaxy collection build`
- **Collection proxy** — внутренний прокси-сервер (например, Automation Hub) для доступа к коллекциям в изолированных средах
- **Content prefix** — префикс, указывающий тип контента (`roles/`, `plugins/`, `playbooks/`)

## Основные концепции

### Структура коллекции

Стандартная структура каталогов коллекции:

```
company.my_collection/
├── galaxy.yml              # Манифест коллекции
├── README.md               # Документация
├── roles/
│   └── my_role/
│       ├── tasks/main.yml
│       └── defaults/main.yml
├── plugins/
│   ├── modules/
│   │   └── my_module.py
│   ├── lookup/
│   │   └── my_lookup.py
│   └── callback/
│       └── my_callback.py
├── playbooks/
│   └── my_playbook.yml
├── tests/
│   ├── integration/
│   └── unit/
└── meta/
    └── runtime.yml
```

### Зависимости коллекций

Зависимости объявляются в `requirements.yml` или внутри `galaxy.yml`:

```yaml
# galaxy.yml
dependencies:
  ansible.posix: ">=1.0.0"
  community.general: "*"
```

```yaml
# requirements.yml (внешние зависимости)
collections:
  - name: community.docker
    version: ">=3.0.0"
  - name: community.mysql
    version: "2.0.0"
```

### Версионирование

Коллекции используют семантическое версионирование (`major.minor.patch`). Совместимость с ansible-core определяется в `galaxy.yml`:

```yaml
# galaxy.yml
version: 1.2.3
requires_ansible: ">=2.12,<2.17"
```

### Публикация

```bash
# Сборка архива
ansible-galaxy collection build

# Публикация в Galaxy
ansible-galaxy collection publish company-my_collection-1.2.3.tar.gz --token=<API_TOKEN>

# Публикация в Automation Hub
ansible-galaxy collection publish company-my_collection-1.2.3.tar.gz --server=automation_hub
```

### Внутренний реестр

- **Automation Hub** — официальный Red Hat каталог коллекций для Automation Platform
- **Nexus/Artifactory** — как private Galaxy через API
- **File-based collections** — локальные tar.gz для изолированных сред

## Практические сценарии

### Инициализация новой коллекции

```bash
# Создание структуры
ansible-galaxy collection init company.my_collection

# Результат:
# company.my_collection/
# ├── galaxy.yml
# ├── README.md
# ├── plugins/
# ├── roles/
# └── tests/
```

### Добавление контента в коллекцию

```bash
# Добавление роли
ansible-galaxy role init company.my_collection.roles.my_role

# Добавление модуля
mkdir -p company.my_collection/plugins/modules/
```

Кастомный модуль (`company.my_collection/plugins/modules/my_module.py`):

```python
#!/usr/bin/python
DOCUMENTATION = r'''
---
module: my_module
short_description: My custom module
description:
    - Description of the module
options:
    name:
        description: Name of the resource
        type: str
        required: true
'''

from ansible.module_utils.basic import AnsibleModule

def main():
    module = AnsibleModule(
        argument_spec=dict(
            name=dict(type='str', required=True),
            state=dict(type='str', default='present', choices=['absent', 'present']),
        ),
        supports_check_mode=True
    )

    result = dict(changed=False, name=module.params['name'])

    if module.params['state'] == 'present':
        result['changed'] = True

    module.exit_json(**result)

if __name__ == '__main__':
    main()
```

### Тестирование коллекции

```bash
# Запуск тестов
ansible-test integration my_module
ansible-test unit my_module

# Проверка документации
ansible-test sanity company.my_collection
```

### Сборка и публикация

```bash
# Сборка
ansible-galaxy collection build --force

# Публикация
ansible-galaxy collection publish company-my_collection-*.tar.gz

# Установка из requirements.yml
ansible-galaxy collection install -r requirements.yml
```

### Переход от roles к collections

```yaml
# Было (только роли):
# roles/
#   my_role/
#     tasks/main.yml

# Стало (коллекция):
# collections/
#   ansible_collections/
#     company/
#       my_collection/
#         galaxy.yml
#         roles/
#           my_role/
#         plugins/
#           modules/
```

```yaml
# Использование в плейбуке
---
- name: Пример использования коллекции
  hosts: webservers
  tasks:
    - name: Установка через коллекцию
      company.my_collection.my_module:
        name: my_resource
        state: present
```

## Дополнительная информация

- [Ansible Roles](./ansible_roles.md) — создание и управление ролями
- [Ansible Galaxy](./Roles/galaxy.md) — публикация и установка контента
- [Кастомные модули](./ansible_custom_modules.md) — разработка собственных модулей
- [Ansible Test](./ansible-test.md) — тестирование коллекций и модулей