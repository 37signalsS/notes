# Валидация и тестирование плейбуков

## Определения

**Статический анализ** — проверка плейбуков без их выполнения: синтаксис YAML, имена модулей, соответствие best practices. Основные инструменты: `ansible-playbook --syntax-check`, `ansible-lint`, `yamllint`.

**Dry-run (Check Mode)** — режим выполнения, в котором Ansible прогнозирует изменения без фактического применения. Плейбук запускается с флагом `--check`, а для файловых операций добавляется `--diff` для просмотра разницы.

**Идемпотентность** — свойство повторного запуска плейбука не изменять систему, если она уже находится в целевом состоянии. Критично для production-деплоя и обязательна в CI/CD пайплайнах.

**Schema validation** — проверка типов, обязательности и диапазонов значений переменных перед выполнением задач. Реализуется через `ansible.builtin.assert` или `meta/argument_specs.yml` для ролей.

**Pre-commit hook** — скрипт, выполняемый перед коммитом в Git. Используется для блокировки плохих плейбуков на стороне разработчика до попадания кода в репозиторий.

**Quality Gate** — автоматическая проверка в CI/CD, блокирующая merge при обнаружении ошибок в плейбуках.

**Drift detection** — механизм выявления расхождений между фактическим состоянием инфраструктуры и состоянием, заданным плейбуком.

**Санкт-зона (Canary host)** — хост или группа из 1–2 узлов, на которых выполняется первый прогон плейбука в production перед полным rollout. Используется для контроля реального поведения под нагрузкой.

## Базовые концепции

### Уровни валидации плейбуков

Плейбук проходит несколько уровней проверки перед запуском на production:

| Уровень | Инструмент | Что проверяет | Когда выполняется |
| :--- | :--- | :--- | :--- |
| 1. Синтаксис | `ansible-playbook --syntax-check` | YAML, структура плейбука, FQCN | Перед коммитом / в CI |
| 2. Линтинг | `ansible-lint` | Best practices, security | Перед коммитом / в CI |
| 3. Dry-run | `ansible-playbook --check --diff` | Идемпотентность, изменения | На staging перед prod |
| 4. Интеграционное тестирование | Тестовый инвентарь, Molecule | Корректность итогового состояния | На изолированном стенде |
| 5. Production canary | `serial: 1` + health check | Реальное поведение под нагрузкой | На production |

### Жизненный цикл валидации

```
Код изменен
    ↓
pre-commit hook (yamllint, ansible-lint, vault-check)
    ↓
Push в ветку
    ↓
CI: syntax-check → ansible-lint → molecule test (если затронуты роли)
    ↓
Merge в main/staging
    ↓
Staging: --check --diff → health check → manual approval
    ↓
Production: canary (serial: 1) → health check → full rollout
```

### Жизненный цикл плейбука

Плейбук проходит следующие этапы с точки зрения валидации:

1. **Parsing** — Ansible парсит YAML, проверяет синтаксис, разрешает переменные. Ошибки на этом этапе: неверные отступы, двоеточия, фигурные скобки в `when`.
2. **Task loading** — загрузка задач, проверка имен модулей, обработчиков, тегов. Ошибки: несуществующие модули, неверные FQCN.
3. **Variable resolution** — подстановка переменных из `group_vars`, `host_vars`, `extra vars`. Ошибки: неопределенные переменные, неверные типы.
4. **Playbook execution** — выполнение задач на хостах в соответствии с `strategy` (`linear`, `free`) и ограничениями (`serial`, `throttle`). Ошибки: нехватка прав, недоступные хосты, таймауты.
5. **Handler execution** — запуск обработчиков, зарегистрированных через `notify`. Ошибки: обработчики, не запускающиеся из-за `listen` или `listen_to_` в новых версиях.

### Инструменты статического анализа

**ansible-lint** — основной инструмент. Проверяет:
- Использование FQCN модулей
- Наличие `no_log` для секретов
- Отсутствие `shell`/`command` без необходимости
- Правильность тегов и обработчиков
- Соответствие security-профилю

```bash
# Базовая проверка
ansible-lint playbooks/ roles/

# С security-профилем
ansible-lint --profile security playbooks/

# Автоисправление некоторых проблем
ansible-lint --fix playbooks/
```

**yamllint** — проверка стиля YAML:

```bash
# Конфигурация .yamllint
---
extends: default
rules:
  line-length:
    max: 120
  truthy:
    allowed-values: ["true", "false"]
  braces:
    min-spaces-inside: 0
    max-spaces-inside: 0
```

### Профили ansible-lint

| Профиль | Назначение | Где использовать |
| :--- | :--- | :--- |
| `min` | Базовый набор правил | Локальная разработка |
| `safety` | Безопасность и стабильность | Pre-commit hook |
| `shared` | Общие best practices | Pull Request |
| `production` | Полный набор правил | CI/CD pipeline |
| `security` | Аудит безопасности | Compliance-проверки |

### Важность валидации для SRE

Для команд SRE и системных администраторов валидация плейбуков — это не формальность, а механизм снижения рисков:

- **MTTR (Mean Time To Repair)** — непройденная валидация увеличивает время восстановления из-за непредсказуемого поведения плейбука на production.
- **Change failure rate** — плохо протестированные плейбуки увеличивают процент сбоев при деплое.
- **Audit trail** — прохождение всех уровней валидации создает audit trail, необходимый для compliance (PCI-DSS, SOC2, внутренние политики).
- **Canary rollout** — без dry-run и canary-проверки массивный деплой может привести к каскадному отказу инфраструктуры.

## Практические сценарии

### Сценарий 1: Полный pipeline валидации в CI/CD

```yaml
# .github/workflows/ansible-validate.yml
name: Ansible Validation
on: [push, pull_request]

jobs:
  validate:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - name: Install dependencies
        run: |
          pip install ansible-core ansible-lint yamllint
          ansible-galaxy collection install -r collections/requirements.yml

      - name: YAML lint
        run: yamllint playbooks/ roles/

      - name: Syntax check all playbooks
        run: |
          for pb in playbooks/*.yml; do
            echo "Checking $pb"
            ansible-playbook "$pb" --syntax-check
          done

      - name: Ansible lint
        run: ansible-lint playbooks/ roles/ --profile security
```

### Сценарий 2: Тестирование идемпотентности плейбука

Идемпотентность — ключевое свойство production-плейбуков. Проверка:

```bash
# Первый запуск
ansible-playbook -i inventory/prod/hosts.yml playbooks/site.yml
# → changed=5

# Второй запуск (должен быть без изменений)
ansible-playbook -i inventory/prod/hosts.yml playbooks/site.yml
# → changed=0
```

Для автоматизации проверки используйте сценарий с `assert`:

```yaml
# playbooks/idempotence_test.yml
---
- name: Idempotence test
  hosts: localhost
  gather_facts: false
  tasks:
    - name: First run
      ansible.builtin.command: >
        ansible-playbook -i inventory/staging/hosts.yml
        playbooks/site.yml --connection=local
      register: first_run
      changed_when: false

    - name: Second run
      ansible.builtin.command: >
        ansible-playbook -i inventory/staging/hosts.yml
        playbooks/site.yml --connection=local
      register: second_run
      changed_when: false

    - name: Assert idempotence
      ansible.builtin.assert:
        that:
          - "'changed=0' in second_run.stdout"
        fail_msg: "Playbook is not idempotent: {{ second_run.stdout }}"
        success_msg: "Playbook is idempotent"
```

### Сценарий 3: Валидация переменных через assert и argument_specs

```yaml
# Валидация в плейбуке
- name: Проверка обязательных переменных
  ansible.builtin.assert:
    that:
      - app_name is defined
      - app_name | length > 0
      - app_port is defined
      - app_port | int >= 1024
      - app_port | int <= 65535
      - db_host is defined
      - env in ['dev', 'staging', 'production']
    fail_msg: "Некорректные переменные для деплоя"
    success_msg: "Все переменные прошли валидацию"

# Валидация через argument_specs (meta/argument_specs.yml)
---
argument_specs:
  main:
    short_description: Основная конфигурация приложения
    options:
      app_name:
        type: str
        required: true
        description: Имя приложения
      app_port:
        type: int
        required: true
        description: Порт приложения
      env:
        type: str
        choices: ['dev', 'staging', 'production']
        default: 'dev'
```

### Сценарий 4: Pre-commit hooks для блокировки плохих плейбуков

```yaml
# .pre-commit-config.yaml
---
repos:
  - repo: local
    hooks:
      - id: yamllint
        name: YAML lint
        entry: yamllint
        language: system
        types: [yaml]

      - id: ansible-lint
        name: Ansible lint
        entry: ansible-lint --profile security
        language: system
        files: \.(yml|yaml)$
        exclude: ^(molecule|tests)/

      - id: ansible-syntax-check
        name: Ansible syntax check
        entry: bash -c 'for f in "$@"; do ansible-playbook "$f" --syntax-check || exit 1; done' --
        language: system
        files: \.yml$
        exclude: ^(molecule|tests)/

      - id: detect-secrets
        name: Detect secrets
        entry: detect-secrets
        language: system
        args: ['--baseline', '.secrets.baseline']
```

```bash
# Установка hooks
pre-commit install

# Ручной запуск
pre-commit run --all-files
```

### Сценарий 5: Drift detection как тест

```yaml
# playbooks/drift_detection.yml
---
- name: Configuration drift detection
  hosts: all
  gather_facts: true
  tasks:
    - name: Сбор чексум критичных файлов
      ansible.builtin.stat:
        path: "{{ item }}"
        checksum_algorithm: sha256
      register: file_checksums
      loop:
        - /etc/ssh/sshd_config
        - /etc/nginx/nginx.conf
        - /etc/sysctl.d/99-custom.conf

    - name: Сравнение с эталоном
      ansible.builtin.assert:
        that:
          - item.stat.checksum == expected_checksums[item.item] | default('')
        fail_msg: "Дрейф: {{ item.item }} имеет чексумму {{ item.stat.checksum }}"
        loop: "{{ file_checksums.results }}"
        loop_control:
          label: "{{ item.item }}"

    - name: Отчет о дрейфе
      ansible.builtin.debug:
        msg: "Дрейф обнаружен на {{ inventory_hostname }}"
      when: file_checksums.results | selectattr('changed') | list | length > 0
```

### Сценарий 6: Валидация через callback plugins

Ansible предоставляет встроенные callback plugins для сбора информации во время выполнения. Используйте их для валидации и отладки:

```bash
# Включение callback plugins в ansible.cfg
[defaults]
stdout_callback = yaml
bin_ansible_callbacks = true
callback_whitelist = profile_tasks, timer, yaml
```

```ini
# ansible.cfg
[defaults]
# Время выполнения каждой задачи
stdout_callback = yaml
callback_whitelist = profile_tasks, timer

# Или используйте новый формат (ansible-core 2.13+)
[callback_ansible_collections]
enable = [profile_tasks, timer]
```

```bash
# Запуск с подробным выводом
ansible-playbook -i inventory/prod/hosts.yml playbooks/site.yml -vvv

# Просмотр задач без выполнения
ansible-playbook -i inventory/prod/hosts.yml playbooks/site.yml --list-tasks

# Просмотр тегов
ansible-playbook -i inventory/prod/hosts.yml playbooks/site.yml --list-tags

# Просмотр хостов
ansible-playbook -i inventory/prod/hosts.yml playbooks/site.yml --list-hosts --limit web_servers

# Просмотр итоговых переменных
ansible-playbook playbooks/site.yml --list-variables -l web01
```

### Сценарий 7: Юнит-тестирование кастомных модулей и фильтров

```python
# test_custom_module.py
import pytest
from ansible.module_utils.basic import AnsibleModule

def test_module_success():
    result = run_module("hello", {"name": "world"})
    assert result["changed"] is False
    assert result["message"] == "Hello, world"

def test_module_failure():
    result = run_module("hello", {"name": ""})
    assert result["failed"] is True
    assert "name is required" in result["msg"]
```

```bash
# Запуск тестов
pytest test_custom_module.py -v
```

### Сценарий 8: Тестирование import/include композиции

Для плейбуков, использующих `import_playbook` или `include_playbook`, проверяйте корректность композиции:

```yaml
# playbooks/site.yml
---
- name: Provision
  import_playbook: provision.yml

- name: Deploy application
  import_playbook: deploy_app.yml

- name: Run migrations
  import_playbook: deploy_db.yml

- name: Health check
  import_playbook: health_check.yml
```

```bash
# Проверка композиции
ansible-playbook playbooks/site.yml --syntax-check

# Просмотр итогового списка задач
ansible-playbook playbooks/site.yml --list-tasks

# Просмотр тегов во всех вложенных плейбуках
ansible-playbook playbooks/site.yml --list-tags
```

## Операции и команды

### Статический анализ

```bash
# Проверка синтаксиса
ansible-playbook playbooks/site.yml --syntax-check
# → syntax check: ok!

# Линтинг
ansible-lint playbooks/ roles/ --profile security

# YAML lint
yamllint playbooks/ roles/

# Проверка всех плейбуков в каталоге
for pb in playbooks/*.yml; do
  ansible-playbook "$pb" --syntax-check
done
```

### Dry-run и проверка изменений

```bash
# Проверка без изменений
ansible-playbook -i inventories/prod/hosts.yml playbooks/site.yml --check

# Dry-run с показом diff
ansible-playbook -i inventories/prod/hosts.yml playbooks/site.yml --check --diff

# Ограничение по группе хостов
ansible-playbook -i inventories/prod/hosts.yml playbooks/site.yml --check --limit web_servers

# Просмотр задач без выполнения
ansible-playbook -i inventories/prod/hosts.yml playbooks/site.yml --list-tasks
```

### Проверка идемпотентности

```bash
# Первый запуск
ansible-playbook -i inventory/hosts.yml playbooks/site.yml
# → changed=5

# Второй запуск (должен быть без изменений)
ansible-playbook -i inventory/hosts.yml playbooks/site.yml
# → changed=0
```

### Molecule тестирование

```bash
# Запуск всех сценариев роли
molecule test

# Отдельный сценарий
molecule converge -s default

# Проверка идемпотентности
molecule idempotence

# Линтинг внутри Molecule
molecule lint
```

Подробное тестирование ролей с Molecule описано в [Тестирование ролей Ansible с помощью Molecule](../ansible_testing_with_molecule.md).

### Проверка переменных

```bash
# Просмотр итоговых переменных
ansible-playbook playbooks/site.yml --list-variables -l web01

# Проверка типа переменной
ansible localhost -m ansible.builtin.debug -a "msg={{ '{{ app_port | type_debug }}' }}"

# Валидация обязательных переменных
ansible-playbook playbooks/site.yml -e "app_name=test app_port=8080" --tags validate
```

### ansible-test для коллекций

Для тестирования коллекций, модулей и плагинов используйте `ansible-test`. Подробности в [Тестирование контента Ansible через ansible-test](../ansible-test.md).

```bash
# Запуск sanity-тестов
ansible-test sanity --docker default

# Unit-тесты
ansible-test units --docker --python 3.12

# Интеграционные тесты
ansible-test integration --docker default
```

## Типичные ошибки и troubleshooting

### Ошибка: "syntax check: ERROR!"

**Причина:** Ошибка в YAML-синтаксисе (отступы, кавычки, двоеточия).

**Решение:**
```bash
# Проверка конкретного файла
ansible-playbook playbooks/site.yml --syntax-check

# Использование yamllint для локализации
yamllint playbooks/site.yml
# → playbooks/site.yml:10:1: [error] syntax error: mapping values are not allowed here
```

### Ошибка: Molecule падает с "permission denied"

**Причина:** Пользователь не добавлен в группу `docker` или `podman`.

**Решение:**
```bash
# Добавление в группу docker
sudo usermod -aG docker $USER
newgrp docker

# Или запуск с sudo (не рекомендуется)
sudo molecule test
```

### Ошибка: "assert" падает на production, но проходит на staging

**Причина:** Переменная определена в `group_vars/staging/`, но отсутствует в `group_vars/prod/`.

**Решение:** Используйте `default()` в плейбуках или добавьте обязательные переменные в `group_vars/all/`:

```yaml
# Безопасное обращение с default
- name: Проверка
  ansible.builtin.assert:
    that:
      - app_port | default(8080) | int >= 1024
```

### Ошибка: ansible-lint находит ошибки, которые не критичны

**Причина:** Слишком строгий профиль или устаревшие правила.

**Решение:** Используйте `.ansible-lint` для кастомизации:

```yaml
# .ansible-lint
---
profile: security
exclude_paths:
  - molecule/
  - tests/
rules:
  command-instead-of-module:
    enabled: false
  fqcn-builtins:
    enabled: false  # Если используете старые модули без FQCN
```

### Ошибка: Drift detection падает из-за различий в окружениях

**Причина:** staging и production имеют разные версии конфигураций, но используются одни и те же чексуммы.

**Решение:** Храните эталонные чексуммы в `group_vars/` per-environment:

```yaml
# group_vars/staging/expected_checksums.yml
expected_checksums:
  /etc/nginx/nginx.conf: "abc123..."

# group_vars/prod/expected_checksums.yml
expected_checksums:
  /etc/nginx/nginx.conf: "def456..."
```

### Ошибка: Идемпотентность нарушена при использовании command/shell

**Причина:** Задачи с `ansible.builtin.command` или `ansible.builtin.shell` без явного указания `changed_when` возвращают `changed: true` при каждом запуске.

**Решение:** Добавьте `changed_when: false` или используйте `creates`/`removes`:

```yaml
- name: Run setup script
  ansible.builtin.command: /opt/scripts/setup.sh
  args:
    creates: /opt/app/.initialized
  register: setup_result

- name: Another approach
  ansible.builtin.shell: |
    if [ ! -f /opt/app/.initialized ]; then
      /opt/scripts/setup.sh
      touch /opt/app/.initialized
    fi
  changed_when: false
```

### Ошибка: Переменные окружения теряются между задачами

**Причина:** Использование `environment` на уровне play вместо задачи, или настройка `ansible.cfg` переопределяет переменные.

**Решение:** Используйте `environment` на уровне задачи или проверьте `ansible.cfg`:

```yaml
- name: Task with environment
  ansible.builtin.command: ./script.sh
  environment:
    PATH: "/opt/custom/bin:{{ ansible_env.PATH }}"
```

## Лучшие практики

### Валидация

1. **Всегда используйте `--syntax-check`.** Добавьте в pre-commit hook.
2. **`ansible-lint --profile security` в CI.** Блокируйте merge при ошибках.
3. **Dry-run на staging перед production.** `--check --diff` обязателен для любых изменений.
4. **Идемпотентность.** Второй запуск плейбука не должен давать `changed > 0`.
5. **Schema validation.** Используйте `assert` или `argument_specs` для проверки переменных.
6. **Drift detection в CI.** Регулярно проверяйте соответствие production-состояния коду.
7. **Тестируйте композицию.** Для плейбуков с `import_playbook` проверяйте итоговый список задач через `--list-tags` и `--list-tasks`.

### Тестирование

8. **Изоляция тестов.** Используйте Docker/Podman для Molecule. Не тестируйте на production-хостах.
9. **Матрица ОС.** Тестируйте роли на всех поддерживаемых дистрибутивах (Ubuntu, RHEL, Debian).
10. **Секреты в тестах.** Используйте фиктивные секреты (`test-only-not-a-real-secret`). Никогда не тестируйте на production-секретах.
11. **Idempotence test.** Включайте сценарий `idempotence` в Molecule для каждой роли.

### CI/CD

12. **Quality Gates.** Настройте блокирование merge при ошибках линтинга.
13. **Canary перед полным rollout.** Запускайте на 1 хосте (`serial: 1`) перед массовым деплоем.
14. **Артефакты.** Сохраняйте логи, reports и status codes как артефакты CI/CD.
15. **Автоматический откат.** Настройте автоматический rollback при падении health check.
16. **Fail-fast.** Прерывайте пайплайн на sanity-тестах, чтобы не тратить время на integration при критических ошибках.

### SRE-практики

17. **Измеримость:** каждый failing-тест должен давать actionable-сообщение с причиной и местом.
18. **Воспроизводимость:** тесты должны проходить на любом инженерном хосте за <10 минут для sanity/unit.
19. **Наблюдаемость:** собирайте метрики длительности тестов, выделите аутлаеры (flaky tests).
20. **Безопасность:** не запускайте integration-тесты на uncontrolled хостах; изолируйте сеть контейнера.
21. **Документация:** каждый failing-тест — это баг в модуле или в тесте; ведите реестр ignored sanity-ошибок с причиной и планом дальнейшего удаления.

## Дополнительная информация

* [Основы структуры плейбуков](basics.md) — компоненты плейбука и их назначение.
* [Продвинутые возможности](advanced.md) — делегирование, асинхронные задачи, обработка ошибок.
* [Стратегии деплоя и rolling updates](../ansible_deployment_strategies.md) — canary, blue-green, rolling update.
* [Тестирование ролей с Molecule](../ansible_testing_with_molecule.md) — изолированное тестирование ролей.
* [Тестирование коллекций через ansible-test](../ansible-test.md) — для модулей и плагинов.
* [Оптимизация производительности](../ansible_performance_tuning.md) — тюнинг для больших инвентарей.
* [Антипаттерны Ansible](../ansible_bad_practices.md) — типичные ошибки при проектировании плейбуков.
* [Официальная документация по testing](https://docs.ansible.com/projects/ansible/latest/dev_guide/testing.html)
