# Ansible Vault: Практические примеры

## 1. Шифрование плейбука

1. **Создадим простой плейбук `playbook.yml`:**

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

2. **Сохраним пароль в файл `vault_pass.txt`:**

    ```bash
    echo "MySuperSecretPassword" > vault_pass.txt
    chmod 600 vault_pass.txt # Важно защитить файл с паролем
    ```

3. **Зашифруем плейбук с ID "test_id":**

    ```bash
    ansible-vault encrypt playbook.yml --vault-id test_id@vault_pass.txt
    ```

    После шифрования `playbook.yml` будет выглядеть примерно так:

    ```
    $ANSIBLE_VAULT;1.1;AES256;test_id
    616562366138653664323265323... (много зашифрованных данных)
    ```

4. **Запустим зашифрованный плейбук:**

    ```bash
    ansible-playbook playbook.yml --vault-id test_id@vault_pass.txt
    ```

    Ansible прозрачно расшифрует плейбук и выполнит его.

## 2. Интеграция с Vagrant

1. **Создание зашифрованного файла секретов:**

    ```bash
    # Сначала создайте файл с паролем, если его нет (содержит только сам пароль)
    echo "your_vault_password" > .vault_password
    chmod 600 .vault_password

    # Затем создайте зашифрованный файл vars/secrets.yml
    ansible-vault create vars/secrets.yml --vault-password-file .vault_password
    ```

    В процессе выполнения команды `create` откроется редактор, в котором вы сможете добавить ваши секреты, например:

    ```yaml
    htpasswd_password: "MySecureWebPassword"
    admin_ip: "192.168.77.1"
    ```

    После сохранения и закрытия редактора файл `vars/secrets.yml` будет зашифрован.

* **`vars/secrets.yml`**: Файл, содержащий зашифрованные секреты (например, `htpasswd_password`, `admin_ip`). Ansible определяет, что файл зашифрован, по заголовку `$ANSIBLE_VAULT;1.1;AES256`. Этот файл безопасно хранить в Git.
* **`.vault_password`**: Простой текстовый файл, содержащий пароль для расшифровки `vars/secrets.yml`. **Этот файл никогда не должен попадать в Git.**
* **`.gitignore`**: Стандартный файл Git, который должен содержать строку `.vault_password`, чтобы гарантировать, что "ключ" случайно не попадет в репозиторий.

### Процесс работы: от `vagrant up` до Nginx

1. **`Vagrantfile`**: Vagrant читает `Vagrantfile` и находит блок запуска Ansible. Ключевая строка `ansible.vault_password_file = ".vault_password"` дает Vagrant прямую инструкцию, какой файл использовать в качестве пароля для Vault.

    ```ruby
    # Vagrantfile
    machine.vm.provision :ansible do |ansible|
      ansible.playbook = "playbook.yml"
      ansible.vault_password_file = ".vault_password" # <--- КЛЮЧЕВОЙ МОМЕНТ
    end
    ```

2. **Инструкция — `playbook.yml`**: Vagrant запускает Ansible, который читает плейбук. Директива `vars_files: - vars/secrets.yml` указывает, что нужно загрузить переменные из зашифрованного файла.

3. **Расшифровка "на лету"**:
    * Ansible видит заголовок `$ANSIBLE_VAULT` в `vars/secrets.yml`.
    * Используя путь к паролю (`.vault_password`), полученный от Vagrant, он читает пароль.
    * В оперативной памяти расшифровывает содержимое `vars/secrets.yml`. С этого момента переменные (например, `htpasswd_password`) доступны с их реальными значениями.

4. **Выполнение задач**: Ansible начинает выполнять задачи, подставляя в них расшифрованные "на лету" значения переменных. Вместо простого копирования шаблона, плейбук может содержать более сложную логику, как в примере ниже.

    ```yaml
    # playbook.yml
    - name: Generate htpasswd file from vault
      ansible.builtin.command: >
        htpasswd -cb /etc/nginx/htpasswd vagrant '{{ htpasswd_password }}'
      args:
        creates: /etc/nginx/htpasswd
      no_log: true # <-- См. нюанс ниже

    - name: Configure Nginx with Self-Signed Certificate
      ansible.builtin.copy:
        dest: /etc/nginx/sites-enabled/site1.local.conf
        content: |
          server {
              listen 80;
              # ... (перенаправление на HTTPS)
          }

          server {
              listen 443 ssl;
              # ... (конфигурация SSL)

              location /admin {
                  allow {{ admin_ip }}; # <-- Сюда подставляется '192.168.77.1'
                  deny all;
                  auth_basic "Admin Area";
                  auth_basic_user_file /etc/nginx/htpasswd;
              }        
          }
      notify: Restart Nginx
    ```

### Важные нюансы

* Vagrant автоматизирует вызов, который вам пришлось бы делать вручную: `ansible-playbook --vault-password-file .vault_password playbook.yml`.
