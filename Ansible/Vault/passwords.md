# Ansible Vault: Управление паролями

Ansible должен получить пароль от Vault для расшифровки данных во время выполнения плейбука. Если Ansible встретит зашифрованное место и не сможет его расшифровать (не будет предоставлен пароль или он окажется неверным), он остановится с ошибкой.

Существует несколько способов передать пароль:

- **Интерактивный ввод (`--ask-vault-pass` или `--vault-id @prompt`):**

    ```bash
    # Запросить пароль для хранилища по умолчанию
    ansible-playbook my_playbook.yml --ask-vault-pass

    # Интерактивно запросить пароль для конкретного vault-id
    ansible-playbook site.yml --vault-id dev@prompt
    ```
    Удобно для ручных запусков, но не подходит для автоматизации.

- **Файл с паролем (`--vault-password-file` или `--vault-id @<file>`):**
    Пароль хранится в текстовом файле, путь к которому передается Ansible.

    ```bash
    # Файл ~/.vault_pass содержит одну строку с паролем
    ansible-playbook my_playbook.yml --vault-password-file ~/.vault_pass
    ```
    Этот метод подходит для CI/CD. **Важно:** защищайте файл с паролем, установив права `chmod 600`. Для удобства путь к файлу можно задать через переменную окружения `ANSIBLE_VAULT_PASSWORD_FILE`.

- **Переменная окружения (`ANSIBLE_VAULT_PASSWORD`):**

    ```bash
    export ANSIBLE_VAULT_PASSWORD="MySecretPassword"
    ansible-playbook my_playbook.yml
    ```
    Ansible автоматически подхватит пароль из этой переменной для хранилища по умолчанию.

- **Исполняемый скрипт (самый гибкий способ):**
    В качестве файла с паролем можно указать исполняемый скрипт (с флагом `+x`). Ansible выполнит его и будет использовать стандартный вывод (STDOUT) в качестве пароля. Это позволяет интегрировать Ansible с внешними системами хранения секретов (HashiCorp Vault, 1Password и т.д.).

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

### Указание нескольких паролей

При работе с разными окружениями (dev, prod) можно указать несколько источников паролей. Ansible сам выберет нужный, исходя из `vault-id` в зашифрованном файле.
```bash
ansible-playbook site.yml \
  --vault-id dev@prompt \
  --vault-id prod@~/.vault-pass-prod
```
