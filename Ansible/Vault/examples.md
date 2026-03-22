# Ansible Vault: Практические примеры

## Определения

- **Практические примеры Vault**: Готовые сценарии использования Ansible Vault для шифрования плейбуков, файлов переменных и интеграции с инструментами развёртывания.

## Основные концепции

### Типы шифрования

Ansible Vault поддерживает шифрование различных объектов:

- **Файлы целиком**: Плейбуки, файлы переменных, inventory
- **Отдельные строки**: Переменные для вставки в обычные YAML-файлы
- **Несколько хранилищ**: Разные пароли для разных окружений (dev, prod)

### Формат зашифрованных данных

Все зашифрованные файлы содержат заголовок вида `$ANSIBLE_VAULT;1.1;AES256`, по которому Ansible распознаёт тип содержимого. Детали формата описаны в [algorithms.md](./algorithms.md).

## Практические сценарии

### Сценарий 1: Шифрование плейбука

Шифрование всего плейбука полезно для защиты логики автоматизации, содержащей секреты.

**Шаг 1: Создание плейбука**

```yaml
---
- name: Test Encrypted Playbook
  hosts: localhost
  connection: local
  tasks:
    - name: Show secret message
      ansible.builtin.debug:
        msg: "This is a secret message!"
```

**Шаг 2: Подготовка файла с паролем**

```bash
echo "MySuperSecretPassword" > vault_pass.txt
chmod 600 vault_pass.txt
```

**Шаг 3: Шифрование с указанием Vault ID**

```bash
ansible-vault encrypt playbook.yml --vault-id test_id@vault_pass.txt
```

После шифрования файл будет содержать заголовок:

```
$ANSIBLE_VAULT;1.1;AES256;test_id
616562366138653664323265323...
```

**Шаг 4: Запуск зашифрованного плейбука**

```bash
ansible-playbook playbook.yml --vault-id test_id@vault_pass.txt
```

### Сценарий 2: Интеграция с Vagrant

Автоматизация расшифровки секретов при развёртывании через Vagrant.

**Шаг 1: Создание зашифрованного файла секретов**

```bash
# Файл с паролем
echo "your_vault_password" > .vault_password
chmod 600 .vault_password

# Зашифрованный файл переменных
ansible-vault create vars/secrets.yml --vault-password-file .vault_password
```

Содержимое `vars/secrets.yml` после редактирования:

```yaml
htpasswd_password: "MySecureWebPassword"
admin_ip: "192.168.77.1"
```

**Шаг 2: Настройка Vagrantfile**

```ruby
machine.vm.provision :ansible do |ansible|
  ansible.playbook = "playbook.yml"
  ansible.vault_password_file = ".vault_password"
end
```

**Шаг 3: Использование секретов в плейбуке**

```yaml
- name: Generate htpasswd file from vault
  ansible.builtin.command: >
    htpasswd -cb /etc/nginx/htpasswd vagrant '{{ htpasswd_password }}'
  args:
    creates: /etc/nginx/htpasswd
  no_log: true

- name: Configure Nginx with Self-Signed Certificate
  ansible.builtin.copy:
    dest: /etc/nginx/sites-enabled/site1.local.conf
    content: |
      server {
          listen 80;
          # Перенаправление на HTTPS
      }

      server {
          listen 443 ssl;
          # Конфигурация SSL

          location /admin {
              allow {{ admin_ip }};
              deny all;
              auth_basic "Admin Area";
              auth_basic_user_file /etc/nginx/htpasswd;
          }
      }
  notify: Restart Nginx
```

**Важные нюансы:**

- Vagrant автоматически передаёт `--vault-password-file` при запуске Ansible
- Файл `.vault_password` должен быть исключён из Git через `.gitignore`
- Все задачи с секретами должны использовать `no_log: true` (см. [best_practices.md](./best_practices.md))

### Сценарий 3: Шифрование отдельных переменных

Использование `encrypt_string` для вставки зашифрованных значений в обычные файлы.

**Шаг 1: Шифрование строки**

```bash
ansible-vault encrypt_string --stdin-name 'db_password'
# Введите пароль и секретное значение (Ctrl+D для завершения)
```

Результат:

```yaml
db_password: !vault |
  $ANSIBLE_VAULT;1.1;AES256
  3534...
```

**Шаг 2: Вставка в файл переменных**

```yaml
# group_vars/prod/vars.yml
app_name: "MyApp"
db_password: !vault |
  $ANSIBLE_VAULT;1.1;AES256
  3534...
```

Детали работы с `encrypt_string` описаны в [basics.md](./basics.md).

### Сценарий 4: Несколько хранилищ для разных окружений

Использование разных паролей для dev и prod.

**Шаг 1: Шифрование файлов с разными Vault ID**

```bash
# Prod-окружение
ansible-vault encrypt group_vars/prod/secrets.yml --vault-id prod@prompt

# Dev-окружение
ansible-vault encrypt group_vars/dev/secrets.yml --vault-id dev@./dev_pass.txt
```

**Шаг 2: Запуск с несколькими паролями**

```bash
ansible-playbook my_playbook.yml \
  --vault-id prod@~/.prod_vault_pass \
  --vault-id dev@prompt
```

Ansible автоматически выбирает правильный пароль для каждого файла по его Vault ID. Подробнее в [multi_vault.md](./multi_vault.md).

## Дополнительная информация

Базовые команды Vault описаны в [basics.md](./basics.md), управление паролями — в [passwords.md](./passwords.md), рекомендации по безопасности — в [best_practices.md](./best_practices.md), технические детали шифрования — в [algorithms.md](./algorithms.md).
