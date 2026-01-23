# Тестирование ролей Ansible с помощью Molecule

## Определения

**Molecule** — это фреймворк для автоматизированного тестирования ролей и плейбуков Ansible. Он позволяет создавать временные, изолированные окружения (с помощью Docker, Vagrant, облачных провайдеров), применять к ним ваш код и проверять, что он работает корректно. Это ключевой инструмент для внедрения практик CI/CD в разработку Ansible-автоматизации.

## Основные концепции

### Зачем нужен Molecule?

Тестирование сложной роли вручную требует: поднятия тестовых серверов, запуска плейбука, ручной проверки и повторения для разных ОС. Molecule автоматизирует этот процесс, позволяя:
*   **Инициализировать роль** со всей необходимой тестовой обвязкой.
*   **Интегрироваться в CI/CD пайплайны** (GitLab CI, Jenkins) для автоматического прогона тестов при каждом коммите.
*   **Создавать и уничтожать тестовые окружения** на лету, используя различные "драйверы" (Docker, Vagrant, OpenStack и др.).
*   **Проводить линтинг** кода (`ansible-lint`) как один из шагов тестирования.

### Установка
Molecule является Python-пакетом и устанавливается через `pip`. Рекомендуется устанавливать его вместе с драйвером (например, Docker) и линтером.

```bash
# Установка Molecule с поддержкой Docker и ansible-lint
pip install "molecule[docker,lint]"

# Иногда могут потребоваться системные зависимости
# sudo apt-get install python3-pip libssl-dev
```
> **Примечание о версиях:** Molecule тесно связан с версией Ansible. При ошибках совместимости может потребоваться установка конкретной версии Molecule.
> `pip install molecule==X.Y.Z`

## Практические сценарии

### Инициализация роли и структура тестов
Для создания новой роли вместе с тестовой структурой Molecule используется команда `init role`.

```bash
molecule init role my_new_role
```
Эта команда создаст стандартную структуру `ansible-galaxy` и добавит в нее директорию `molecule/` со сценарием тестирования `default`.

```
my_new_role/
└── molecule/
    └── default/
        ├── create.yml      # Плейбук для создания тестового инстанса
        ├── destroy.yml     # Плейбук для уничтожения инстанса
        ├── converge.yml    # Основной плейбук, применяющий вашу роль
        ├── molecule.yml    # Главный файл конфигурации сценария
        └── verify.yml      # Плейбук для проверки состояния системы после converge
```
Можно создавать несколько сценариев тестирования (например, для разных ОС) с помощью `molecule init scenario <scenario_name>`.

### Файл конфигурации `molecule.yml`
Это сердце тестового сценария, описывающее, как Molecule должен проводить тестирование.

**Пример `molecule.yml`:**
```yaml
---
dependency:
  name: galaxy
driver:
  name: docker
platforms:
  - name: instance
    image: "geerlingguy/docker-ubuntu2004-ansible:latest"
    pre_build_image: true
provisioner:
  name: ansible
verifier:
  name: ansible
```

**Ключевые секции:**
*   `dependency`: Управление зависимостями роли (например, через `ansible-galaxy`).
*   `driver`: Инструмент для создания тестовых окружений (`docker`, `vagrant`, `delegated`).
*   `platforms`: Описание тестовых инстансов (инвентарь для теста).
*   `provisioner`: Инструмент для применения конфигурации (обычно `ansible`).
*   `verifier`: Инструмент для проверки (`ansible` с `verify.yml`).

### Плейбуки сценария
*   **`create.yml` и `destroy.yml`:** Подготавливают и уничтожают окружение. Генерируются автоматически для `docker`/`vagrant` драйверов.
*   **`converge.yml`:** Основной плейбук для применения тестируемой роли к инстансу.
    ```yaml
    ---
    - name: Converge
      hosts: all
      tasks:
        - name: "Include my_new_role"
          include_role:
            name: "my_new_role"
    ```
*   **`verify.yml`:** Содержит тесты для проверки корректной работы роли.
    ```yaml
    ---
    - name: Verify
      hosts: all
      gather_facts: false
      tasks:
        - name: Check that Nginx is installed
          ansible.builtin.package:
            name: nginx
            state: present
          check_mode: true
          register: nginx_pkg
        
        - name: Assert that nginx package is present
          ansible.builtin.assert:
            that:
              - not nginx_pkg.changed
            fail_msg: "Nginx package was not installed"
            success_msg: "Nginx package is present"
    ```

### Жизненный цикл и команды
Molecule предоставляет набор команд для управления всем циклом тестирования.

*   **`molecule test`:** Запускает полный цикл тестирования:
    1.  `dependency`: Установка зависимостей.
    2.  `lint`: Проверка кода линтером.
    3.  `cleanup`: Очистка.
    4.  `destroy`: Уничтожение старых инстансов.
    5.  `syntax`: Проверка синтаксиса.
    6.  `create`: Создание инстансов.
    7.  `prepare`: Подготовка инстансов (если есть `prepare.yml`).
    8.  `converge`: Запуск основного плейбука.
    9.  `idempotence`: Проверка идемпотентности.
    10. `verify`: Запуск тестов из `verify.yml`.
    11. `destroy`: Уничтожение инстансов.

*   **Отдельные команды (для отладки):**
    *   `molecule create`: Создать окружение.
    *   `molecule converge`: Применить роль.
    *   `molecule login`: Подключиться к тестовому инстансу по SSH.
    *   `molecule verify`: Запустить тесты.
    *   `molecule destroy`: Уничтожить окружение.

> **Практический совет:** Если роль требует предварительной настройки серверов, используйте плейбук `prepare.yml` в сценарии. Molecule выполнит его после создания инстанса и до `converge`.
