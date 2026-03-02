# Создание и использование ролей

## Создание каркаса роли

Утилита `ansible-galaxy` автоматически создает всю необходимую структуру директорий для новой роли.

```bash
# Команда создает директорию my_new_role с полной структурой
ansible-galaxy init my_new_role
```

## Наполнение роли логикой

Основная работа происходит в файле `tasks/main.yml`.

**Пример: роль `set_time`**

1. **Создаем роль:**

    ```bash
    ansible-galaxy init set_time
    ```

2. **Добавляем задачу в `roles/set_time/tasks/main.yml`:**

    ```yaml
    ---
    # tasks file for set_time
    - name: Set timezone to Europe/Moscow
      ansible.builtin.timezone:
        name: Europe/Moscow
    ```

    *Важно: не удаляйте `---` в начале файла.*

## Подключение роли в плейбуке

Роли применяются к хостам с помощью ключевого слова `roles` в плейбуке. Ansible автоматически ищет роли в директории `roles/` рядом с плейбуком.

**Пример `playbook.yml`:**

```yaml
---
- name: Configure servers
  hosts: webservers
  become: true
  roles:
    - set_time # Указываем имя роли
```

При запуске этого плейбука для всех хостов из группы `webservers` будет применена роль `set_time`, которая установит часовой пояс `Europe/Moscow`.

**Более сложные примеры подключения:**

```yaml
- name: Example playbook using roles
  hosts: webservers
  become: true

  roles:
    - common      # Простая роль по имени
    - geerlingguy.nginx       # Роль из коллекции
    - { role: my_app.memcached, port: 11211, tags: ["memcached"] } # Передача параметров и тегов
```
