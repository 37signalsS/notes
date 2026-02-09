# Ansible Vault: Управление паролями

Ansible должен получить пароль от Vault для расшифровки данных во время выполнения плейбука. Если Ansible встретит зашифрованное место и не сможет его расшифровать (не будет предоставлен пароль или он окажется неверным), он остановится с ошибкой.

* **Интерактивный ввод (`--ask-vault-pass`):**

    ```bash
    ansible-playbook my_playbook.yml --ask-vault-pass
    ```

    Ansible запросит пароль в консоли. Удобно для ручных запусков, но не подходит для автоматизации в CI/CD.

* **Файл с паролем (`--vault-password-file <file>`):**
    Пароль хранится в текстовом файле, путь к которому передается Ansible.

    ```bash
    # Файл ~/.vault_pass содержит одну строку с паролем
    ansible-playbook my_playbook.yml --vault-password-file ~/.vault_pass
    ```

    Этот метод подходит для CI/CD, но сам файл с паролем нужно защищать (например, установить права 0600).

* **Переменная окружения:**

    ```bash
    export ANSIBLE_VAULT_PASSWORD="MySecretPassword"
    ansible-playbook my_playbook.yml
    ```

    Ansible автоматически подхватит пароль из этой переменной.

* **Исполняемый скрипт (самый гибкий способ):**
    В качестве файла с паролем можно указать исполняемый скрипт (с флагом `+x`). Ansible выполнит его и будет использовать его стандартный вывод (STDOUT) в качестве пароля.
    Это позволяет интегрировать Ansible с внешними системами хранения секретов (HashiCorp Vault, 1Password, Keycloak и т.д.).

    ```bash
    # vault.sh
    #!/bin/bash
    # Команда для получения секрета из внешнего хранилища
    /usr/local/bin/get-secret --name ansible-vault-password
    ```

    ```bash
    # Запуск
    ansible-playbook my_playbook.yml --vault-password-file ./vault.sh
    ```
