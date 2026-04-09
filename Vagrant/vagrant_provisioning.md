# Provisioning в Vagrant

## Определения

**Provisioning (провижининг)** — механизм автоматической установки ПО, настройки конфигураций и выполнения задач при создании ВМ. Ключевая особенность Vagrant для воспроизводимых окружений.

## Базовые концепции

### Когда выполняется provisioning

| Событие | Команда | Provisioning |
| --- | --- | --- |
| Первый запуск | `vagrant up` | ✅ Выполняется |
| Повторный запуск | `vagrant up` | ❌ Не выполняется |
| Принудительно | `vagrant provision` | ✅ Выполняется |
| Перезагрузка | `vagrant reload --provision` | ✅ Выполняется |
| Перезагрузка | `vagrant reload` | ❌ Не выполняется |

> **Важно:** Provisioning выполняется только один раз при первом `vagrant up`. Для повторного применения используйте `vagrant provision` или `vagrant reload --provision`.

### Типы провижинеров

| Провижинер | Описание | Сложность | Идемпотентность |
| --- | --- | --- | --- |
| **Shell** | Выполнение bash-скриптов | Низкая | ❌ (требует ручной проверки) |
| **Ansible** | Управление конфигурацией | Средняя | ✅ (встроенная) |
| **Docker** | Запуск контейнеров | Средняя | ✅ (образы декларативны) |
| **Puppet** | Декларативная конфигурация | Высокая | ✅ (встроенная) |

## Практические сценарии

### Сценарий 1: Shell-скрипты

**Встроенный скрипт (inline):**

```ruby
config.vm.provision "shell", inline: <<-SHELL
  apt-get update
  apt-get install -y nginx
  systemctl enable --now nginx
SHELL
```

**Внешний скрипт (рекомендуется):**

```ruby
config.vm.provision :shell, path: "scripts/provision.sh"
```

```bash
#!/bin/bash
# scripts/provision.sh
set -euo pipefail

apt-get update -y
apt-get install -y nginx
systemctl enable --now nginx

# Идемпотентность: добавлять строку только если её нет
grep -q "custom_config" /etc/nginx/nginx.conf || \
  echo "custom_config" >> /etc/nginx/nginx.conf
```

**Несколько скриптов:**

```ruby
config.vm.provision :shell, path: "scripts/base.sh"
config.vm.provision :shell, path: "scripts/nginx.sh"
config.vm.provision :shell, path: "scripts/app.sh"
```

### Сценарий 2: Ansible

**Базовая конфигурация:**

```ruby
config.vm.provision "ansible" do |ansible|
  ansible.playbook = "playbooks/site.yml"
  ansible.compatibility_mode = "2.0"
end
```

**С кастомным inventory:**

```ruby
config.vm.provision "ansible" do |ansible|
  ansible.playbook = "playbooks/site.yml"
  ansible.inventory_path = "inventory.ini"
  ansible.limit = "all"
end
```

> **Важно:** При указании `inventory_path` Vagrant не генерирует автоматический inventory и не добавляет `--limit`. Вы полностью управляете процессом.

**С дополнительными параметрами:**

```ruby
config.vm.provision "ansible" do |ansible|
  ansible.playbook = "playbooks/site.yml"
  ansible.verbose = "-vv"
  ansible.extra_vars = { nginx_port: 80, app_env: "development" }
  ansible.raw_arguments = ["--forks=10"]
end
```

**Интеграция с Ansible Vault:**

```ruby
config.vm.provision "ansible" do |ansible|
  ansible.playbook = "playbooks/site.yml"
  ansible.vault_password_file = ".vault_password"
end
```

Файл `.vault_password` должен быть в `.gitignore`. Подробнее: [Ansible Vault Examples](../Ansible/Vault/examples.md), [Ansible Playbook Execution](../Ansible/ansible_playbook_execution.md).

### Сценарий 3: Docker внутри ВМ

**Запуск контейнеров:**

```ruby
config.vm.provision "docker" do |d|
  d.run "nginx", image: "nginx:alpine", ports: ["80:80"]
  d.run "redis", image: "redis:7"
end
```

**С переменными окружения:**

```ruby
config.vm.provision "docker" do |d|
  d.run "app",
    image: "myapp:latest",
    ports: ["8080:8080"],
    env: {
      "DATABASE_URL" => "postgres://db:5432",
      "SECRET_KEY" => ENV['SECRET_KEY']
    }
end
```

**Установка Docker Compose:**

```ruby
config.vm.provision :shell, inline: <<-SHELL
  curl -L https://github.com/docker/compose/releases/latest/download/docker-compose-$(uname -s)-$(uname -m) -o /usr/local/bin/docker-compose
  chmod +x /usr/local/bin/docker-compose
SHELL

config.vm.provision "docker-compose" do |d|
  d.compose_files = ["docker-compose.yml"]
end
```

### Сценарий 4: Puppet

**Базовая конфигурация:**

```ruby
config.vm.provision "puppet" do |puppet|
  puppet.manifests_path = "manifests"
  puppet.manifest_file = "site.pp"
end
```

**С модулями:**

```ruby
config.vm.provision "puppet" do |puppet|
  puppet.manifests_path = "manifests"
  puppet.manifest_file = "site.pp"
  puppet.module_path = "modules"
  puppet.hiera_config_path = "hiera.yaml"
end
```

### Сценарий 5: Комбинирование провижинеров

```ruby
Vagrant.configure("2") do |config|
  config.vm.box = "bento/ubuntu-24.04"

  # 1. Базовая настройка
  config.vm.provision "shell", path: "scripts/base.sh"

  # 2. Установка Docker
  config.vm.provision "docker" do |d|
    d.run "nginx", image: "nginx:alpine"
  end

  # 3. Настройка через Ansible
  config.vm.provision "ansible" do |ansible|
    ansible.playbook = "playbooks/configure.yml"
  end
end
```

## Дополнительная информация

### Выбор провижинера

| Критерий | Shell | Ansible | Puppet/Docker |
| --- | --- | --- | --- |
| **Простота** | ✅ | ⚠️ | ❌ |
| **Идемпотентность** | ❌ | ✅ | ✅ |
| **Сложные сценарии** | ❌ | ✅ | ✅ |
| **Порог входа** | Низкий | Средний | Высокий |

**Рекомендации:**
- **Shell** — быстрые задачи, установка зависимостей, bootstrap
- **Ansible** — управление конфигурацией, идемпотентность, сложная логика
- **Docker** — тестирование контейнеров, микросервисы

### Лучшие практики

1. **Идемпотентность:** Скрипты должны выполняться многократно без побочных эффектов:

   ```bash
   # Плохо
   echo "line" >> /etc/config

   # Хорошо
   grep -q "line" /etc/config || echo "line" >> /etc/config
   ```

   Скрипты должны быть идемпотентными — повторный запуск не должен ломать систему.

2. **Модульность:** Разделяйте скрипты по функциям:
   - `base.sh` — базовая настройка ОС
   - `nginx.sh` — установка веб-сервера
   - `app.sh` — развёртывание приложения

3. **Версионирование:** Фиксируйте версии ПО:

   ```ruby
   d.run "nginx", image: "nginx:1.25-alpine"
   ```

4. **Секреты:** Не храните секреты в Vagrantfile, используйте `ENV`:

   ```ruby
   env: { "API_KEY" => ENV['API_KEY'] }
   ```

### Отладка provisioning

Уровни логирования: [Vagrant Troubleshooting](./vagrant_troubleshooting/basic_concepts.md).

```bash
vagrant provision --debug           # Подробный вывод
vagrant provision web-server        # Конкретная машина (multi-machine)
```

### См. также

- [Vagrantfile Reference](./vagrantfile.md) — синтаксис конфигурации
- [Vagrant Advanced Usage](./vagrant_advanced_usage.md) — сложные сценарии
