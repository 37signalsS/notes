# Архитектура Ansible для безопасного CI/CD в мультипроектной среде

## Определения

**Безопасная архитектура Ansible для CI/CD** — это подход к организации кода и процессов, который позволяет автоматизировать управление конфигурацией множества независимых проектов, обеспечивая при этом строгую изоляцию секретов (SSH-ключей) и разделение между логикой автоматизации (ролями) и конфигурацией конкретных окружений (инвентарем).

## Основные концепции

- **Разделение кода и конфигурации**: Это фундаментальный принцип.

  - **Код (Логика)**: Общая логика автоматизации (например, как установить Nginx) выносится в централизованный репозиторий с общими [Ansible-ролями](../ansible_roles.md) (`CORE`). Это "КАК" мы делаем.

  - **Конфигурация (Данные)**: Параметры для каждого конкретного проекта (список серверов, [переменные](../ansible_playbook_structure.md), версии пакетов) хранятся в отдельных, изолированных Git-репозиториях. Это "ЧТО" мы настраиваем.

- **Выделенный Control Node**: Существует единственный, хорошо защищенный сервер, который выступает в роли Ansible Control Node. Только у этого сервера есть SSH-доступ ко всей управляемой инфраструктуре. Доступ к самому Control Node строго ограничен.

- **Безопасность через делегирование (Wrapper Script)**: Чтобы защитить SSH-ключи на Control Node от окружения CI/CD (например, GitLab Runner), прямой вызов `ansible-playbook` запрещается. Вместо этого используется скрипт-обертка с ограниченными правами `sudo`. GitLab Runner может запустить только этот скрипт и ничего более, что предотвращает утечку ключей и выполнение произвольных команд.

## Практические сценарии

### Сценарий: Построение безопасного CI/CD пайплайна

#### Часть 1: Структура репозиториев

1. **Центральный репозиторий с общими ролями (`ansible-roles-repo`)**

    - Содержит общие, переиспользуемые [роли](../ansible_roles.md).

    ```
    ansible-roles-repo/
    └── roles/
        ├── nginx/
        ├── postgres/
        └── common/
    ```

2. **Репозиторий для каждого проекта (`project-A-inventory`)**

    - Содержит только данные, специфичные для проекта A: [инвентарь](../ansible_setup_and_config.md#определение-хостов-inventory), [переменные](ansible_playbook_structure.md) и [плейбуки](../ansible_playbook_structure.md).

    ```
    project-A-inventory/
    ├── group_vars/
    ├── host_vars/
    ├── inventory.ini
    ├── site.yml
    └── .gitlab-ci.yml
    ```

#### Часть 2: Архитектура выполнения CI/CD

Процесс запускается автоматически при `git push` в репозиторий инвентаря проекта.

**Цепочка выполнения:**

1. `git push` в `project-A-inventory`.
2. **GitLab CI** триггерит пайплайн.
3. **GitLab Runner** на Control Node получает задачу и клонирует оба репозитория: с ролями и с инвентарем.
4. Runner **не вызывает `ansible-playbook` напрямую**. Вместо этого он выполняет команду:

    ```bash
    sudo /usr/local/bin/ansible_runner_script.sh --playbook site.yml --inventory ./inventory.ini --limit ${ANSIBLE_LIMIT:-all}
    ```

5. **Скрипт-обертка** под правами `root` (у которого есть доступ к SSH-ключам) [выполняет `ansible-playbook`](../ansible_playbook_execution.md).
6. Скрипт анализирует лог выполнения и при ошибке создает задачу в системе трекинга.

#### Часть 3: Пример скрипта-обертки (`ansible_runner_script.sh`)

Это упрощенный пример, демонстрирующий основную логику. Он принимает аргументы командной строки и безопасно передает их в `ansible-playbook`.

```bash
#!/bin/bash
# Путь к директории с общими ролями
ROLES_PATH="/path/to/cloned/ansible-roles-repo"
# Всегда запускать плейбуки от пользователя с SSH-ключами (например, root)
# Валидация и очистка входных параметров - обязательна в реальной среде!
ANSIBLE_ARGS="$@"
LOG_FILE="/var/log/ansible/ansible-run-$(date +%Y-%m-%d-%H-%M-%S).log"
# Запускаем ansible-playbook, указывая путь к ролям и логируя вывод
ansible-playbook --roles-path "$ROLES_PATH" $ANSIBLE_ARGS | tee "$LOG_FILE"
# Проверяем exit code последней команды в пайпе
if [ ${PIPESTATUS[0]} -ne 0 ]; then
    echo "Ansible playbook failed. Creating a Jira ticket..."
    # Здесь логика вызова API Jira/CRM с передачей $LOG_FILE
    # curl -X POST -u user:token -H 'Content-Type: application/json' ...
    exit 1
fi
echo "Ansible playbook finished successfully."
exit 0
```

#### Часть 4: Настройка безопасности (`/etc/sudoers.d/gitlab-runner`)

Ключевой элемент безопасности — это жесткое ограничение прав для пользователя `gitlab-runner`. Ему разрешено выполнять без пароля только один конкретный скрипт.

```sudoers
# Предоставляем пользователю gitlab-runner право выполнять
# ТОЛЬКО /usr/local/bin/ansible_runner_script.sh от имени любого пользователя
gitlab-runner ALL=(ALL) NOPASSWD: /usr/local/bin/ansible_runner_script.sh
```

#### Часть 5: Пример `.gitlab-ci.yml`

```yaml
stages:
  - deploy

apply-configuration:
  stage: deploy
  script:
    # Запускаем обертку через sudo с нужными параметрами
    - sudo /usr/local/bin/ansible_runner_script.sh --inventory ./inventory.ini --playbook site.yml --limit ${ANSIBLE_LIMIT:-all}

  rules:
    # Запускать только для main ветки
    - if: '$CI_COMMIT_BRANCH == "main"'

  variables:
    # Администратор может переопределить эту переменную в GitLab
    # для запуска на конкретной группе хостов
    ANSIBLE_LIMIT: "all"

```
