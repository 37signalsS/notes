# Управление ролями с Ansible Galaxy

Ansible Galaxy — это официальный репозиторий ([galaxy.ansible.com](https://galaxy.ansible.com)) и утилита командной строки для поиска, обмена и управления контентом Ansible.

* **Создание каркаса роли:**

    ```bash
    ansible-galaxy role init my_new_role
    ```

* **Установка ролей и коллекций:**

    ```bash
    # Установить роль
    ansible-galaxy install geerlingguy.postgresql

    # Установить коллекцию
    ansible-galaxy collection install community.postgresql
    ```

* **Просмотр установленных компонентов:**

    ```bash
    ansible-galaxy role list
    ansible-galaxy collection list
    ```

## Управление зависимостями через `requirements.yml`

Лучшая практика — определять все внешние роли и коллекции в файле `requirements.yml`.

**Пример `requirements.yml`:**

```yaml
roles:
  # 1. Установка роли из Ansible Galaxy
  - name: geerlingguy.postgresql
    version: 1.8.0 # Можно указать версию

  # 2. Установка роли из Git-репозитория
  - src: https://github.com/geerlingguy/ansible-role-nginx.git
    scm: git
    name: nginx # Имя, которое будет у роли локально

collections:
  # 3. Установка коллекции из Ansible Galaxy
  - name: community.postgresql
    version: 2.3.0

  # 4. Установка коллекции из Git-репозитория
  - name: https://github.com/ansible-collections/community.docker.git
    type: git
    version: main # Ветка, тег или коммит
```

**Установка зависимостей из файла:**

К сожалению, `ansible-galaxy` требует раздельного вызова для установки ролей и коллекций.

```bash
# Установить роли
ansible-galaxy role install -r requirements.yml

# Установить коллекции
ansible-galaxy collection install -r requirements.yml
```

## Пути установки и приватный Galaxy

По умолчанию `ansible-galaxy` устанавливает контент в `~/.ansible/` или системные директории. Эти пути можно переопределить в `ansible.cfg`. Для крупных организаций стандартной практикой является развертывание собственного, приватного сервера Ansible Galaxy, адрес которого настраивается в `ansible.cfg`:

```ini
[galaxy]
server_list = my_company_galaxy

[galaxy_server.my_company_galaxy]
url = https://galaxy.mycompany.com/
```
