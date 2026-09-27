# Провижининг в Vagrant

## Определения

**Provisioning (провижининг)** — механизм автоматической установки программного обеспечения, настройки конфигураций и выполнения произвольных задач при развёртывании виртуальной машины (ВМ). Это ключевая особенность Vagrant, обеспечивающая создание идентичных и воспроизводимых окружений (Infrastructure as Code) для всей команды разработки.

## Базовые концепции

### Жизненный цикл провижининга

По умолчанию провижининг выполняется только один раз — при первом создании ВМ. В дальнейшем запуск требует явного указания флагов.

| Событие | Команда | Запуск по умолчанию |
| :--- | :--- | :--- |
| Первое создание ВМ | `vagrant up` | Да |
| Повторный запуск | `vagrant up` | Нет |
| Принудительный запуск | `vagrant provision` | Да |
| Перезагрузка с обновлением | `vagrant reload --provision` | Да |
| Обычная перезагрузка | `vagrant reload` | Нет |

> **Примечание:** Для повторного применения настроек без перезагрузки используйте `vagrant provision`.

### Управление запуском (Параметр run)

Вы можете изменить стандартное поведение провижинера с помощью параметра `run`:

- `run: "once"` (по умолчанию): Выполняется только один раз при первом `up`.
- `run: "always"`: Выполняется при каждом `up` и `reload`. Полезно для задач синхронизации (например, обновление системного времени или проверка монтирования дисков).
- `run: "never"`: Провижинер никогда не запускается автоматически. Его можно вызвать только явно: `vagrant provision --provision-with <name>`.

### Типы провижинеров

| Провижинер | Описание | Идемпотентность | Сценарии использования |
| :--- | :--- | :--- | :--- |
| **Shell** | Bash/PowerShell скрипты | Нет (требует проверок) | Bootstrap, простые задачи, установка зависимостей |
| **Ansible** | Управление конфигурацией | Да (встроенная) | Сложная настройка ОС, кластеры, мульти-машины |
| **Docker** | Запуск контейнеров | Да (через образы) | Тестирование микросервисов, изоляция приложений |
| **File** | Копирование файлов | Да | Перенос конфигов, ключей или бинарных файлов |
| **Puppet / Chef**| Декларативная настройка | Да | Корпоративные стандарты инфраструктуры |

## Практические сценарии

### Сценарий 1: Использование Shell-скриптов

Поддерживает как встроенные команды (inline), так и внешние файлы.

**Основные параметры:**
- `privileged`: `true` (по умолчанию) — выполнение от `root`.
- `args`: Аргументы, передаваемые скрипту.
- `upload_path`: Путь временной загрузки скрипта в ВМ (по умолчанию `/tmp/vagrant-shell`).
- `env`: Хэш переменных окружения для скрипта.

```ruby
Vagrant.configure("2") do |config|
  # Встроенный скрипт с аргументами и переменными окружения
  config.vm.provision "shell", 
    inline: "echo Hello $1, version $APP_VER", 
    args: ["Vagrant-User"],
    env: { "APP_VER" => "1.0.0" }

  # Внешний скрипт (рекомендуется для сложных задач)
  config.vm.provision "shell", path: "scripts/bootstrap.sh"
end
```

**Совет по написанию скриптов:** Используйте `set -e` в начале bash-скрипта, чтобы прерывать выполнение при любой ошибке.

### Сценарий 2: Интеграция с Ansible (Remote и Local)

**Варианты использования:**
1.  **`ansible`** (remote): запуск playbook с хост-машины (требуется установленный Ansible на хосте). Поддерживает **мульти-машины за один проход**: Vagrant генерирует инвентарь со всеми машинами окружения (`.vagrant/provisioners/ansible/inventory`) и выполняет playbook один раз сразу для всех узлов.
2.  **`ansible_local`**: запуск внутри ВМ (Ansible автоматически ставится в гостевую ОС при `ansible.install = true`). Выполняется по-машинно; полезен, когда Ansible нет на хосте (в т.ч. на Windows-хостах).

```ruby
config.vm.provision "ansible" do |ansible|
  ansible.playbook = "ansible/site.yml"
  ansible.extra_vars = {
    db_port: 5432,
    app_env: "dev"
  }
  # Кастомный инвентарь (отключает автогенерацию Vagrant)
  ansible.inventory_path = "ansible/hosts.ini"
  ansible.limit = "all"
  ansible.become = true
  ansible.become_user = "root"
  ansible.verbose = "vvv"          # показывает реальную ansible-playbook команду и инвентарь
end
```

**Группы и host-переменные через Vagrantfile** (работает при автосгенерированном инвентаре):

```ruby
config.vm.provision "ansible" do |ansible|
  ansible.playbook = "provisioning/site.yml"
  ansible.groups = {
    "db"  => ["db"],
    "web" => ["web", "web2"],
    "all:vars" => { "ansible_python_interpreter" => "/usr/bin/python3" }
  }
  ansible.host_vars = {
    "web" => { "http_port" => 8080 },
    "db"  => { "max_connections" => 200 }
  }
end
```

**Работа с секретами:** пароль Vault передаётся файлом, а не встраивается в конфигурацию:

```ruby
config.vm.provision "ansible" do |ansible|
  ansible.playbook = "site.yml"
  ansible.vault_password_file = "ansible/.vault_pass"   # файл с паролем, в .gitignore
  # или: ansible.ask_vault_pass = true
  ansible.compatibility_mode = "2.0"   # переменные инвентаря для новых Ansible (ansible_host)
end
```

**`ansible_local` детально:**

```ruby
config.vm.provision "ansible_local" do |ansible|
  ansible.playbook = "ansible/site.yml"
  ansible.install = true          # доставить Ansible в гостя
  ansible.version = "latest"      # или "2.15.x" для пина версии
  ansible.install_mode = "default"  # для pip установки: "pip"
  ansible.playbook_command = "ansible-playbook"
end
```

Подробнее об использовании секретов: [Ansible Vault в Vagrant](../Ansible/Vault/examples.md), о самих playbook и инвентаре — [Ansible Playbook Execution](../Ansible/ansible_playbook_execution.md).

### Сценарий 3: Docker-провижининг

Позволяет подготовить среду для запуска контейнеров или собрать образы непосредственно при развертывании ВМ.

```ruby
config.vm.provision "docker" do |d|
  # Сборка образа из Dockerfile
  d.build_image "/vagrant/app", args: "-t my-web-app:v2"
  
  # Запуск контейнеров
  d.run "nginx", image: "nginx:alpine", ports: ["8080:80"]
  d.run "db", image: "postgres:17-alpine", env: { "POSTGRES_PASSWORD" => "pass" }
  
  # Предварительная загрузка образов
  d.pull_images "redis:7-alpine"
end
```

### Сценарий 4: Копирование файлов (File Provisioner)

Простой способ перенести файлы без настройки общих папок.

```ruby
config.vm.provision "file", source: "~/.ssh/id_rsa.pub", destination: "~/.ssh/authorized_keys"
```

### Сценарий 5: Совмещение нескольких провижинеров

Провижинеры выполняются в строгом порядке их описания в `Vagrantfile`.

```ruby
Vagrant.configure("2") do |config|
  # 1. Подготовка системы (Shell)
  config.vm.provision "prep", type: "shell", inline: "apt-get update"
  
  # 2. Установка инфраструктуры (Ansible)
  config.vm.provision "ansible", playbook: "infra.yml"
  
  # 3. Запуск приложений (Docker)
  config.vm.provision "docker", run: "always" do |d|
    d.run "app", image: "myapp:latest"
  end
end
```

## Дополнительная информация

### Использование триггеров

Триггеры позволяют выполнять действия до или после этапа провижининга на хосте или в ВМ.

```ruby
Vagrant.configure("2") do |config|
  config.trigger.before :provision do |t|
    t.info = "Очистка логов перед новым провижинингом..."
    t.run_remote = { inline: "rm -rf /var/log/app/*" }
  end

  config.trigger.after :provision do |t|
    t.info = "Проверка доступности сервиса..."
    t.run_local = { inline: "curl -sI http://localhost:8080 | grep 200" }
  end
end
```

### Имена провижинеров и выборочный запуск

Если дать провижинеру имя (первый аргумент), его можно запускать отдельно:
```bash
# Запустить только провижинер с именем 'prep'
vagrant provision --provision-with prep
```

### Отладка провижининга

Для глубокого анализа процесса разбора и выполнения используйте переменную окружения `VAGRANT_LOG`:
```bash
VAGRANT_LOG=debug vagrant provision
```

### Лучшие практики

1.  **Идемпотентность:** Гарантируйте, что повторный запуск провижининга не приведет к ошибкам или дублированию данных.
    *   В Shell используйте `grep -q` или `if [ ! -f ... ]` перед внесением изменений.
    *   В Ansible используйте декларативные модули (`template`, `file`) вместо `command`/`shell`.
2.  **Безопасность:** Не храните пароли в `Vagrantfile`. Используйте переменные окружения или Ansible Vault.
    ```ruby
    env: { "DB_PASS" => ENV['DB_PASSWORD'] }
    ```
3.  **Логирование:** Для отладки используйте флаг `--debug`.
4.  **Разделение ответственности:** Используйте Shell для базовой подготовки (bootstrap), а Ansible/Docker — для настройки приложения.

### См. также

- [Vagrantfile: Справочник параметров](./vagrantfile.md) — детальное описание синтаксиса.
- [Vagrant Advanced Usage](./vagrant_advanced_usage.md) — мульти-машины и триггеры.
- [Vagrant Troubleshooting](./vagrant_troubleshooting/practical_scenarios.md) — решение проблем при настройке.
- [Ansible Playbook Execution](../Ansible/ansible_playbook_execution.md) — подробнее о работе Ansible.
