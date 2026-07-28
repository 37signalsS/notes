# Провижининг в Vagrant

## Определения

**Provisioning (провижининг)** — механизм автоматической установки программного обеспечения, настройки конфигураций и выполнения задач при развёртывании виртуальной машины. Это ключевая особенность Vagrant, обеспечивающая создание идентичных и воспроизводимых окружений для всей команды разработки.

## Базовые концепции

### Жизненный цикл провижининга

По умолчанию провижининг выполняется только один раз — при первом выполнении команды `vagrant up`.

| Событие | Команда | Запуск провижининга |
| :--- | :--- | :--- |
| Первое создание ВМ | `vagrant up` | Да |
| Повторный запуск | `vagrant up` | Нет |
| Принудительный запуск | `vagrant provision` | Да |
| Перезагрузка с обновлением | `vagrant reload --provision` | Да |
| Обычная перезагрузка | `vagrant reload` | Нет |

> **Примечание:** Для повторного применения настроек без перезагрузки используйте `vagrant provision`.

### Типы провижинеров

Vagrant поддерживает широкий спектр инструментов, от простых скриптов до систем управления конфигурациями:

| Провижинер | Описание | Идемпотентность | Сценарии использования |
| :--- | :--- | :--- | :--- |
| **Shell** | Bash/PowerShell скрипты | Нет (требует проверок) | Bootstrap, простые задачи, установка зависимостей |
| **Ansible** | Управление конфигурацией | Да (встроенная) | Сложная настройка ОС, кластеры, мульти-машины |
| **Docker** | Запуск контейнеров | Да (через образы) | Тестирование микросервисов, изоляция приложений |
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
  # Встроенный скрипт с аргументами
  config.vm.provision "shell", 
    inline: "echo Hello $1", 
    args: ["Vagrant-User"]

  # Внешний скрипт (рекомендуется для сложных задач)
  config.vm.provision "shell", path: "scripts/bootstrap.sh"
end
```

### Сценарий 2: Интеграция с Ansible

Ansible — наиболее популярный выбор для Vagrant благодаря отсутствию агента и декларативному подходу.

**Варианты использования:**
1.  **`ansible`**: Запуск с хост-машины (требует установленного Ansible на хосте).
2.  **`ansible_local`**: Запуск внутри ВМ (Ansible устанавливается автоматически в гостевую ОС).

```ruby
config.vm.provision "ansible" do |ansible|
  ansible.playbook = "ansible/site.yml"
  ansible.extra_vars = { 
    db_port: 5432,
    app_env: "dev" 
  }
  # Использование кастомного инвентаря (отключает автогенерацию)
  ansible.inventory_path = "ansible/hosts.ini"
  ansible.limit = "all"
end
```

Подробнее об использовании секретов: [Ansible Vault в Vagrant](../Ansible/Vault/examples.md).

### Сценарий 3: Docker-провижининг

Позволяет подготовить среду для запуска контейнеров или собрать образы непосредственно при развертывании ВМ.

```ruby
config.vm.provision "docker" do |d|
  # Сборка образа из Dockerfile
  d.build_image "/vagrant/app", args: "-t my-web-app:v1"
  
  # Запуск контейнеров
  d.run "nginx", image: "nginx:alpine", ports: ["8080:80"]
  d.run "db", image: "postgres:16-alpine", env: { "POSTGRES_PASSWORD" => "pass" }
  
  # Предварительная загрузка образов
  d.pull_images "redis:latest"
end
```

### Сценарий 4: Совмещение нескольких провижинеров

Провижинеры выполняются в порядке их описания в `Vagrantfile`.

```ruby
Vagrant.configure("2") do |config|
  # 1. Подготовка системы (Shell)
  config.vm.provision "shell", inline: "apt-get update"
  
  # 2. Установка инфраструктуры (Ansible)
  config.vm.provision "ansible", playbook: "infra.yml"
  
  # 3. Запуск приложений (Docker)
  config.vm.provision "docker", run: "nginx"
end
```

Параметр `run: "always"` позволяет запускать провижинер при каждом старте (`up` или `reload`), даже если флаг `--provision` не указан.

## Дополнительная информация

### Использование триггеров

Триггеры позволяют выполнять действия до или после этапа провижининга.

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

Подробнее о триггерах: [Vagrant Advanced Usage](./vagrant_advanced_usage.md#триггеры).

### Лучшие практики

1.  **Идемпотентность:** Гарантируйте, что повторный запуск провижининга не приведет к ошибкам или дублированию данных.
    *   В Shell используйте `grep -q` перед записью в файлы.
    *   В Ansible используйте декларативные модули вместо `command`/`shell`.
2.  **Безопасность:** Не храните пароли в `Vagrantfile`. Используйте переменные окружения или Ansible Vault.
    ```ruby
    env: { "DB_PASS" => ENV['DB_PASSWORD'] }
    ```
3.  **Логирование:** Для отладки используйте флаг `--debug`.
    ```bash
    vagrant provision --debug
    ```

### См. также

- [Vagrantfile: Справочник параметров](./vagrantfile.md) — детальное описание синтаксиса.
- [Vagrant Advanced Usage](./vagrant_advanced_usage.md) — мульти-машины и триггеры.
- [Vagrant Troubleshooting](./vagrant_troubleshooting/practical_scenarios.md) — решение проблем при настройке.
- [Ansible Playbook Execution](../Ansible/ansible_playbook_execution.md) — подробнее о работе Ansible.