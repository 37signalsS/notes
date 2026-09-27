# Ansible — управление мультисредами

## Определения

**Multi-environment (мультисреда)** — подход к организации кода, при котором для dev/staging/prod (и последующих окружений) используются отдельные инвентари, переменные и секреты, обеспечивая изоляцию конфигураций.

**Environment isolation (изоляция окружений)** — гарантия того, что изменения в одной среде не влияют на другие. Достигается через отдельные инвентари, групповые переменные и Vault ID.

**Environment parity (паритет окружений)** — принцип, согласно которому dev/staging/prod должны максимально совпадать по структуре, версиям ПО и конфигурации, чтобы минимизировать риск отказа при переходе в production.

**Environment overlay (оверлей окружения)** — механизм переопределения переменных через директории `group_vars/` и `host_vars/` на уровне конкретного окружения.

**Directory inventory (каталоговый инвентарь)** — инвентарь, организованный как директория с подкаталогами `hosts.yml`, `group_vars/`, `host_vars/`. Ansible автоматически объединяет все файлы в единый инвентарь.

**Namespace isolation (изоляция имён)** — разделение имён хостов, групп и переменных между окружениями, исключающее случайное переопределение.

**Environment promotion (промоушен окружения)** — процесс перемещения конфигурации и артефактов из dev в staging, а затем в prod с сохранением неизменности кода.

**Inventory per environment (инвентарь на окружение)** — паттерн, при котором каждое окружение имеет собственный корневой каталог инвентаря.

---

## Основные концепции

### Зачем отдельные окружения

В production-инфраструктуре ошибка в конфигурации на одном хосте может привести к простою сервиса. Multi-environment подход снижает риск:

- **Изоляция изменений**: разработчик может экспериментировать в dev, не затрагивая prod.
- **Разделение секретов**: пароли и ключи для prod недоступны в dev.
- **Поэтапное тестирование**: код проходит staged rollout: dev → staging → prod.
- **Аудит**: каждый запуск привязан к конкретному окружению и инвентарю.

### Паттерны организации окружений

Ansible поддерживает три основных паттерна:

| Паттерн | Описание | Когда использовать |
| :--- | :--- | :--- |
| **Inventory per environment** | Отдельный каталог `inventories/dev/`, `inventories/prod/` | Классический подход, подходит для большинства проектов |
| **Single inventory + groups** | Один инвентарь, группы `dev_`, `staging_`, `prod_` | Небольшой парк, когда окружения физически разделены |
| **Directory inventory overlay** | Один каталог, переменные переопределяются через файлы `group_vars/<group>/<env>.yml` | Продвинутый уровень, когда нужен inheritance |

### Иерархия переменных в multi-environment

Ansible разрешает конфликты переменных по строгой иерархии (variable precedence). При работе с несколькими окружениями важно понимать, откуда берётся финальное значение.

Приоритет переменных (от низшего к высшему):
1. Role defaults
2. Inventory vars (group) — `group_vars/all.yml`
3. Inventory vars (host) — `host_vars/host1.yml`
4. Play vars
5. Role vars
6. Include vars
7. Set facts / registered
8. Extra vars — `-e "var=value"` (абсолютный приоритет)

Для multi-environment ключевой момент: переменные из `group_vars/all.yml` внутри `inventories/dev/` переопределяют переменные из корневого `group_vars/all.yml`, но только если запуск выполняется с `-i inventories/dev`.

### Почему directory inventory

Directory inventory позволяет:
- Хранить все окружения в одном Git-репозитории.
- Использовать Git-директории как источник правды.
- Именовать каталоги явно: `dev/`, `staging/`, `prod/`.
- Не дублировать структуру: общие переменные выносятся в корневой `group_vars/`, окружение-специфичные — в каталог окружения.

### Взаимодействие с Vault и динамическим инвентарём

Для multi-environment обязательным является использование отдельных Vault ID для каждого окружения (multi-vault). Это исключает возможность случайного использования prod-секрета в dev-среде.

Динамический инвентарь (NetBox, Foreman, Consul) может формировать списки хостов per environment через фильтры по тегам, location или group. Подробнее о динамическом инвентаре: [dynamic_inventory.md](dynamic_inventory.md).

---

## Предварительные требования

### Версии ПО

- **ansible-core**: 2.20+
- **Python на контрольном узле**: 3.12+
- **Операционная система**: GNU/Linux (RHEL 9+, Debian 12+, Ubuntu 22.04+)

### Проверка окружения

```bash
# Проверка версии Ansible
ansible --version
# → ansible [core 2.20.0]

# Проверка доступных инвентарей
ls -la inventories/
# → drwxr-xr-x  dev/  staging/  prod/

# Проверка синтаксиса инвентаря
ansible-inventory -i inventories/dev --list | python3 -m json.tool > /dev/null && echo "OK"

# Проверка доступных Vault ID
ansible-vault list --vault-id dev@prompt --vault-id prod@prompt inventories/dev/group_vars/all/vault.yml
```

---

## Практические сценарии

### Структура каталогов для трёх окружений

```
project/
├── ansible.cfg
├── inventories/
│   ├── dev/
│   │   ├── hosts.yml
│   │   ├── group_vars/
│   │   │   ├── all.yml
│   │   │   ├── webservers.yml
│   │   │   └── dbservers.yml
│   │   └── host_vars/
│   │       └── db-dev-01.yml
│   ├── staging/
│   │   ├── hosts.yml
│   │   ├── group_vars/
│   │   │   ├── all.yml
│   │   │   ├── webservers.yml
│   │   │   └── dbservers.yml
│   │   └── host_vars/
│   └── prod/
│       ├── hosts.yml
│       ├── group_vars/
│       │   ├── all.yml
│       │   ├── webservers.yml
│       │   └── dbservers.yml
│       └── host_vars/
├── playbooks/
├── roles/
└── group_vars/
    └── all.yml          # общие переменные для всех окружений
```

### Пример инвентаря для dev

```yaml
# inventories/dev/hosts.yml
---
all:
  children:
    webservers:
      hosts:
        web-dev-01:
          ansible_host: 192.168.1.10
        web-dev-02:
          ansible_host: 192.168.1.11
    dbservers:
      hosts:
        db-dev-01:
          ansible_host: 192.168.1.20
          postgresql_version: 15
```

### Пример инвентаря для prod

```yaml
# inventories/prod/hosts.yml
---
all:
  children:
    webservers:
      hosts:
        web-prod-01:
          ansible_host: 10.0.1.10
        web-prod-02:
          ansible_host: 10.0.1.11
        web-prod-03:
          ansible_host: 10.0.1.12
    dbservers:
      hosts:
        db-prod-master:
          ansible_host: 10.0.1.20
          postgresql_version: 16
        db-prod-replica:
          ansible_host: 10.0.1.21
```

### Environment overlay через group_vars

Переменные, объявленные в `group_vars/all.yml` внутри каталога окружения, переопределяют глобальные переменные из корневого `group_vars/all.yml` при запуске с соответствующим инвентарём.

```yaml
# group_vars/all.yml (глобальные дефолты)
---
app_debug: false
app_replicas: 1
log_level: info
db_backup_enabled: false

# inventories/dev/group_vars/all.yml
---
app_debug: true
app_replicas: 1
log_level: debug
db_backup_enabled: false

# inventories/prod/group_vars/all.yml
---
app_debug: false
app_replicas: 3
log_level: warning
db_backup_enabled: true
db_backup_schedule: "0 2 * * *"
```

```yaml
# inventories/dev/group_vars/webservers.yml
---
nginx_worker_processes: 2
nginx_worker_connections: 512
app_port: 8080

# inventories/prod/group_vars/webservers.yml
---
nginx_worker_processes: auto
nginx_worker_connections: 4096
app_port: 8080
ssl_certificate: /etc/ssl/certs/app.crt
ssl_certificate_key: /etc/ssl/private/app.key
```

### Запуск плейбуков по окружениям

```bash
# Только dev окружение
ansible-playbook -i inventories/dev playbooks/deploy.yml

# Только staging с ограничением по группе
ansible-playbook -i inventories/staging playbooks/deploy.yml -l webservers

# Только конкретный хост в prod
ansible-playbook -i inventories/prod playbooks/deploy.yml --limit web-prod-01

# Проверка (dry-run) на prod
ansible-playbook -i inventories/prod playbooks/deploy.yml --check --diff

# Теги для dev
ansible-playbook -i inventories/dev playbooks/deploy.yml --tags "migrate,static"

# Конкретная задача на конкретных хостах в prod
ansible-playbook -i inventories/prod playbooks/deploy.yml -l "webservers" -t "restart"
```

### Промоушен окружения (environment promotion)

Промоушен — это перенос того же самого кода плейбуков и ролей из dev в staging и prod без изменений. Ключевые принципы:

1. **Одинаковый код**: плейбуки и роли не меняются при переходе между окружениями.
2. **Переменные хранятся в инвентарях**: только `inventories/dev/`, `inventories/prod/` отличаются.
3. **Секреты в Vault per env**: multi-vault обеспечивает изоляцию ключей.
4. **Валидация перед деплоем**: запуск `--check --diff` на staging перед prod.

```bash
# Промоушен: запуск на staging (предварительная проверка)
ansible-playbook -i inventories/staging playbooks/deploy.yml --check --diff

# Промоушен: запуск на prod после approval
ansible-playbook -i inventories/prod playbooks/deploy.yml --check --diff
```

### Цикл по окружениям

```bash
# Автоматический запуск по всем окружениям
for env in dev staging prod; do
  ansible-playbook -i "inventories/${env}" playbooks/deploy.yml \
    --vault-id "${env}@.vault_pass_${env}"
done
```

### Fact caching для разных окружений

Кэширование фактов ускоряет повторные запуски, особенно на больших парках. Для multi-environment важно использовать раздельные каталоги кэша, чтобы факты из prod не попали в dev и наоборот.

```ini
# ansible.cfg
[defaults]
fact_caching = jsonfile
fact_caching_connection = /tmp/ansible_facts_cache
fact_caching_timeout = 86400
```

Для разделения кэша по окружениям используйте отдельные `ansible.cfg` в каждом каталоге инвентаря или передавайте путь через переменную окружения:

```bash
# Dev
ANSIBLE_CACHE_PLUGIN_CONNECTION=/tmp/ansible_facts_cache_dev \
  ansible-playbook -i inventories/dev playbooks/deploy.yml

# Prod
ANSIBLE_CACHE_PLUGIN_CONNECTION=/tmp/ansible_facts_cache_prod \
  ansible-playbook -i inventories/prod playbooks/deploy.yml
```

Подробнее о fact caching: [Ansible: основные концепции](ansible_core_concepts.md).

### Динамический инвентарь per environment

Динамические источники (NetBox, Foreman) можно сегментировать по окружениям через теги, location или кастомные атрибуты. Конфигурация конкретных плагинов описана в [dynamic_inventory.md](dynamic_inventory.md).

```bash
# Запуск с динамическим инвентарём Foreman с фильтром по окружению
ansible-playbook -i inventory/foreman.yml playbooks/site.yml \
  --limit "environment=prod"

# Или используя переменную окружения для селекции
FOREMAN_ENVIRONMENT=production \
  ansible-playbook -i inventory/foreman.yml playbooks/site.yml
```

### Делегирование задач в multi-environment контексте

Делегирование (`delegate_to`) позволяет выполнять задачи не на целевом хосте, а на другом узле (например, на балансировщике, контрольном узле или сервере мониторинга). В multi-environment средах это используется для:

- Уведомления систем мониторинга о деплое в конкретном окружении.
- Обновления DNS-записей или конфигурации балансировщика после деплоя.
- Выполнения миграций базы данных на выделенном хосте.

```yaml
---
- name: Deploy application
  hosts: webservers
  become: true
  tasks:
    - name: Notify monitoring about deployment
      ansible.builtin.uri:
        url: "http://monitoring.internal:9090/api/deploy"
        method: POST
        body_format: json
        body:
          environment: "{{ env_name }}"
          host: "{{ inventory_hostname }}"
      delegate_to: localhost
      run_once: true

    - name: Run database migration on master
      ansible.builtin.command: /opt/app/manage.py migrate
      delegate_to: "{{ groups['dbservers'] | select('match', 'master') | list | first }}"
      run_once: true

    - name: Flush proxy cache after deploy
      ansible.builtin.command: nginx -s reload
      delegate_to: proxy-lb-01
      run_once: true
```

> **Примечание:** `delegate_to` работает на уровне задачи, а не всего плея. Для делегирования всех задач используйте `hosts: localhost`. Подробнее: [PlaybookStructure/advanced.md](PlaybookStructure/advanced.md).

### Multi-Vault: отдельные секреты на окружение

Для multi-environment каждый инвентарь должен использовать собственный Vault ID. Это предотвращает эскалацию привилегий: разработчик с доступом к dev-паролю не может расшифровать prod-данные.

```bash
# Шифрование переменных для разных сред
ansible-vault encrypt_string --vault-id dev@prompt \
  'dev_db_password' --name 'db_password'

ansible-vault encrypt_string --vault-id prod@prompt \
  'prod_db_password' --name 'db_password'
```

```yaml
# inventories/dev/group_vars/all/vault.yml
vault_db_password: !vault |
  $ANSIBLE_VAULT;1.2;AES256;dev
  65306262376163353931636634633530323065613038373164353362663434663735616436336362

# inventories/prod/group_vars/all/vault.yml
vault_db_password: !vault |
  $ANSIBLE_VAULT;1.2;AES256;prod
  65306262376163353931636634633530323065613038373164353362663434663735616436336362
```

```bash
# Запуск с multi-vault
ansible-playbook -i inventories/prod playbooks/deploy.yml \
  --vault-id prod@prompt

ansible-playbook -i inventories/dev playbooks/deploy.yml \
  --vault-id dev@prompt
```

> **Важно:** Метка Vault ID в заголовке файла (формат 1.2) хранится в открытом виде. Используйте нейтральные имена (`prod`, `db`, `app`). Подробнее о multi-vault: [Vault/multi_vault.md](Vault/multi_vault.md).

---

## Операции и команды

### Команды ansible-playbook для multi-environment

| Задача | Команда |
| :--- | :--- |
| Запуск на dev | `ansible-playbook -i inventories/dev playbooks/deploy.yml` |
| Запуск на staging | `ansible-playbook -i inventories/staging playbooks/deploy.yml` |
| Запуск на prod | `ansible-playbook -i inventories/prod playbooks/deploy.yml` |
| Ограничение по группе | `ansible-playbook -i inventories/prod playbooks/deploy.yml -l webservers` |
| Ограничение по хосту | `ansible-playbook -i inventories/prod playbooks/deploy.yml --limit web-prod-01` |
| Dry-run с диффом | `ansible-playbook -i inventories/prod playbooks/deploy.yml --check --diff` |
| Запуск с тегами | `ansible-playbook -i inventories/dev playbooks/deploy.yml --tags "migrate,static"` |
| Multi-vault prod | `ansible-playbook -i inventories/prod playbooks/deploy.yml --vault-id prod@prompt` |
| Multi-vault dev | `ansible-playbook -i inventories/dev playbooks/deploy.yml --vault-id dev@prompt` |
| Список хостов инвентаря | `ansible-inventory -i inventories/prod --list` |
| Граф инвентаря | `ansible-inventory -i inventories/prod --graph` |
| Проверка синтаксиса инвентаря | `ansible-inventory -i inventories/dev --list > /dev/null && echo "OK"` |

### Параметры ansible.cfg для multi-environment

```ini
[defaults]
# Пути поиска инвентаря
inventory = ./inventories/prod

# Callback-плагины
callback_enabled = timer, profile_tasks
stdout_callback = yaml

# Логирование
log_path = /var/log/ansible/playbook.log

# Fact caching
fact_caching = jsonfile
fact_caching_connection = /tmp/ansible_facts_cache
fact_caching_timeout = 86400
```

Для смены окружения без редактирования `ansible.cfg` используйте CLI-параметр `-i` или переменную окружения `ANSIBLE_INVENTORY`.

---

## Диагностика

### Типичные ошибки

| Ошибка | Вероятная причина | Решение |
| :--- | :--- | :--- |
| Переменная окружения не переопределяется | Запуск без `-i inventories/<env>` или неверный путь | Проверьте путь к инвентарю: `ansible-playbook -i inventories/prod ...` |
| Vault расшифровывает не тот секрет | Vault ID не соответствует метке в заголовке | Используйте `--vault-id prod@prompt` для prod-инвентаря |
| Переменная из prod попала в dev | Общий `group_vars/all.yml` переопределяет окружение-специфичный | Проверьте приоритет переменных: `ansible-playbook ... --list-variables -l host1` |
| Хост не найден в инвентаре | Неверное имя или отсутствие в `hosts.yml` | `ansible-inventory -i inventories/prod --list \| grep hostname` |
| Fact cache возвращает устаревшие данные | Таймаут кэша слишком большой или разделение кэша отсутствует | Уменьшите `fact_caching_timeout` или используйте разные каталоги |
| `delegate_to` обращается к неверному окружению | Делегируемый хст задан явно, но не существует в текущем инвентаре | Проверьте наличие хоста: `ansible-inventory -i inventories/prod --graph` |
| Динамический инвентарь не фильтрует по окружению | Отсутствует фильтр `environment=prod` в запросе к CMDB | Проверьте параметры запроса в конфигурации плагина |

### Диагностические команды

```bash
# Проверка структуры инвентаря
tree inventories/

# Валидация YAML-синтаксиса инвентаря
python3 -c "import yaml; yaml.safe_load(open('inventories/prod/hosts.yml'))"

# Просмотр списка хостов конкретного окружения
ansible-inventory -i inventories/prod --list | jq '.dev.hosts'

# Граф групп окружения
ansible-inventory -i inventories/prod --graph

# Проверка фактов хоста
ansible -i inventories/prod web-prod-01 -m setup -a 'filter=ansible_distribution*'

# Проверка итоговых переменных хоста
ansible-playbook -i inventories/prod playbooks/deploy.yml \
  --list-variables -l web-prod-01

# Проверка доступа к Vault
ansible-vault view --vault-id prod@prompt inventories/prod/group_vars/all/vault.yml

# Проверка работы fact caching
ls -la /tmp/ansible_facts_cache/
```

---

## Лучшие практики

1. **Один инвентарь на окружение** — каждый каталог `inventories/<env>/` должен быть самодостаточен. Никаких хардкодов путей к хостам из других окружений.
2. **Vault per environment** — используйте отдельный Vault ID для dev/staging/prod. Включите `vault_id_match = True` в `ansible.cfg` для строгого соответствия меток.
3. **Никаких секретов в Git** — файлы паролей (`.vault_pass_*`) добавьте в `.gitignore`. Используйте `chmod 600` для файлов паролей.
4. **Идемпотентность** — плейбуки должны давать одинаковый результат при многократном запуске на одном окружении. Используйте `--check --diff` для валидации.
5. **Environment parity** — dev и prod должны использовать одинаковые версии ролей и образов. Различия только в переменных.
6. **Изоляция fact caching** — для каждого окружения используйте отдельный каталог кэша, чтобы факты не смешивались.
7. **Делегирование с контекстом окружения** — при делегировании задач передавайте имя окружения в уведомления (например, Slack, monitoring API).
8. **CI/CD пайплайн** — автоматизируйте запуск через pipeline: lint → dev deploy → staging approval → prod approval. Никаких ручных деплоев на prod.
9. **Dry-run перед prod** — всегда запускайте `--check --diff` на staging перед применением в prod.
10. **Именование хостов** — используйте префиксы окружения в именах хостов (`web-dev-01`, `web-prod-01`). Это исключает человеческий фактор.
11. **Аудит запусков** — логируйте все запуски с указанием окружения, пользователя и версии кода. Используйте callback-плагины для отправки метаданных в централизованное хранилище логов.
12. **Валидация инвентаря в CI** — проверяйте синтаксис `hosts.yml` и `group_vars/` на каждом PR. Используйте `ansible-inventory --list` для проверки.
13. **Ограничение радиуса поражения** — используйте `--limit` для запуска на подмножестве хостов перед массовым применением. Комбинируйте с `serial` для постепенного rollout.
14. **Ротация Vault паролей** — периодически меняйте пароли Vault ID. Используйте `ansible-vault rekey` с `--vault-id old@source --new-vault-id new@source`.
15. **Резервное копирование инвентаря** — храните инвентарь в Git. Для продакшн-секретов используйте шифрование на уровне репозитория (e.g., git-crypt) в дополнение к Vault.

---

## Дополнительная информация

### Связанные разделы

- [Ansible: переменные и факты](PlaybookStructure/variables.md) — иерархия приоритетов, области видимости, переменные окружения.
- [Ansible: продвинутые возможности плейбуков](PlaybookStructure/advanced.md) — делегирование (`delegate_to`), асинхронные задачи.
- [Ansible Vault: Multi-Vault](Vault/multi_vault.md) — несколько хранилищ, Vault ID, строгое соответствие.
- [Динамический инвентарь в Ansible](dynamic_inventory.md) — плагины инвентаря, NetBox, Foreman, Consul.
- [Ansible: основные концепции](ansible_core_concepts.md) — жизненный цикл, выполнение, факт-кэширование.
- [Ansible: безопасные практики](ansible_security_best_practices.md) — управление секретами, аудит, шифрование.

### Документация

- [Ansible Inventory](https://docs.ansible.com/ansible/latest/inventory_guide/intro_inventory.html) — официальная документация по инвентарю.
- [Ansible Vault](https://docs.ansible.com/ansible/latest/vault_guide/index.html) — руководство по шифрованию.
- [Variable Precedence](https://docs.ansible.com/ansible/latest/playbook_guide/playbooks_variables.html#understanding-variable-precedence) — иерархия переменных.
