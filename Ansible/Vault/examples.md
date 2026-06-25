# Ansible Vault: Практические примеры

## Определения

- **Практические примеры Vault**: Готовые сценарии использования Ansible Vault для шифрования плейбуков, файлов переменных и интеграции с инструментами развёртывания.

## Основные концепции

### Типы шифрования

Ansible Vault позволяет шифровать различные объекты, помечая их специальным заголовком (подробнее в [алгоритмах](./algorithms.md)):

- **Файлы целиком**: Плейбуки, файлы переменных, inventory
- **Отдельные строки**: Переменные для вставки в обычные файлы формата YAML (YAML Ain't Markup Language)
- **Несколько хранилищ**: Разные пароли для разных окружений (dev, prod)

## Практические сценарии

### Сценарий 1: Шифрование плейбука

Шифрование всего плейбука полезно для защиты логики автоматизации, содержащей секреты.

1. **Создание плейбука**:

    ```yaml
    ---
    # playbook.yml
    - name: Test Encrypted Playbook
      hosts: localhost
      connection: local
      tasks:
        - name: Show secret message
          ansible.builtin.debug:
            msg: "This is a secret message!"
    ```

2. **Подготовка файла с паролем**:

    ```bash
    echo "MySuperSecretPassword" > vault_pass.txt # → (создание файла)
    chmod 600 vault_pass.txt # → (ограничение прав доступа)
    ```

3. **Шифрование с указанием Vault ID (Identifier)**:

    ```bash
    ansible-vault encrypt playbook.yml --vault-id test_id@vault_pass.txt
    # → Encryption successful
    ```

    После шифрования файл будет содержать заголовок:

    ```text
    $ANSIBLE_VAULT;1.1;AES256;test_id
    616562366138653664323265323...
    ```

4. **Запуск зашифрованного плейбука**:

    ```bash
    ansible-playbook playbook.yml --vault-id test_id@vault_pass.txt
    # → PLAY [Test Encrypted Playbook] ...
    # → TASK [Show secret message] ******************
    # → ok: [localhost] => { "msg": "This is a secret message!" }
    ```

### Сценарий 2: Интеграция с Vagrant

Автоматизация расшифровки секретов при развёртывании через Vagrant. В примере используются адреса IP (Internet Protocol), а также протоколы HTTPS (HyperText Transfer Protocol Secure) и SSL (Secure Sockets Layer).

1. **Создание зашифрованного файла секретов**:

    ```bash
    # Файл с паролем
    echo "your_vault_password" > .vault_password # → (создание файла)
    chmod 600 .vault_password # → (ограничение прав доступа)

    # Зашифрованный файл переменных
    ansible-vault create vars/secrets.yml --vault-password-file .vault_password
    # → Vault password: (пароль из файла будет использован автоматически)
    ```

    Содержимое `vars/secrets.yml` после редактирования:

    ```yaml
    htpasswd_password: "MySecureWebPassword"
    admin_ip: "192.168.77.1"
    ```

2. **Настройка Vagrantfile**:

    ```ruby
    machine.vm.provision :ansible do |ansible|
      ansible.playbook = "playbook.yml"
      ansible.vault_password_file = ".vault_password"
    end
    ```

3. **Использование секретов в плейбуке**:

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

Подробный пример шифрования отдельных строк (команда `encrypt_string`) описан в [Ansible Vault: Основы](./basics.md).

### Сценарий 4: Несколько хранилищ для разных окружений

Пример работы с Vault ID для разделения секретов разных окружений описан в [Использование нескольких хранилищ](./multi_vault.md).

## Дополнительная информация

- [Ansible Vault: Основы](./basics.md)
- [Рекомендации по безопасности](./best_practices.md)
- [Алгоритмы шифрования](./algorithms.md)
