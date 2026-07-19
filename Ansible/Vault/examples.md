# Ansible Vault: Практические примеры

## Определения

- **Практические примеры Vault**: Сборник прикладных сценариев применения Ansible Vault для защиты конфиденциальных данных в различных окружениях (разработка, CI/CD, эксплуатация).

## Основные концепции

### Выбор объекта шифрования

В зависимости от задачи, шифрование применяется на разных уровнях:
- **Файлы переменных (`group_vars`, `host_vars`)**: Самый распространенный способ. Шифруется файл целиком, содержащий десятки секретов.
- **Инлайновое шифрование (`encrypt_string`)**: Удобно для точечной защиты отдельных значений в открытых файлах конфигурации.
- **Инвентарные файлы (Inventory)**: Позволяет защитить адреса хостов или специфические параметры доступа, если инвентарь содержит чувствительные данные.

## Практические сценарии

### Сценарий 1: Шифрование файла переменных для окружения

Обычно создается файл `vault.yml` внутри каталогов переменных.

1. **Создание зашифрованного файла**:
    ```bash
    ansible-vault create inventories/prod/group_vars/all/vault.yml
    ```

2. **Содержимое файла**:
    ```yaml
    ansible_become_pass: "admin_sudo_password"
    db_root_password: "complex_db_password"
    ```

3. **Использование в команде**:
    ```bash
    ansible-playbook site.yml -i inventories/prod --ask-vault-pass
    ```

### Сценарий 2: Интеграция с Vagrant

Vagrant позволяет автоматически передавать пароль Vault при развертывании локальных стендов.

1. **Подготовка файла пароля**:
    ```bash
    echo "vagrant_secret" > .vault_pass
    # Обязательно добавьте .vault_pass в .gitignore!
    ```

2. **Настройка `Vagrantfile`**:
    ```ruby
    Vagrant.configure("2") do |config|
      config.vm.provision "ansible" do |ansible|
        ansible.playbook = "playbook.yml"
        ansible.vault_password_file = ".vault_pass"
      end
    end
    ```

3. **Пример использования модуля `htpasswd`**:
    Вместо выполнения shell-команд используйте специализированные модули для безопасности.
    ```yaml
    - name: Set up web authentication
      community.general.htpasswd:
        path: /etc/nginx/.htpasswd
        name: admin
        password: "{{ web_admin_password }}"
        owner: root
        group: www-data
        mode: '0640'
      no_log: true
    ```

### Сценарий 3: Использование в CI/CD (GitLab CI)

В автоматизированных пайплайнах пароль передается через переменную окружения.

1. **Настройка переменной**:
    В настройках GitLab CI (Settings -> CI/CD -> Variables) создайте защищенную (Protected) переменную `ANSIBLE_VAULT_PASSWORD`.

2. **Конфигурация `.gitlab-ci.yml`**:
    ```yaml
    deploy:
      script:
        - echo "$ANSIBLE_VAULT_PASSWORD" > .vault_pass
        - ansible-playbook deploy.yml --vault-password-file .vault_pass
      after_script:
        - rm -f .vault_pass # Удаление временного файла пароля
    ```

### Сценарий 4: Шифрование переменных внутри инвентаря

Если вы используете YAML-инвентарь, вы можете вставлять зашифрованные строки прямо в него.

```yaml
all:
  hosts:
    db-server:
      ansible_host: 10.0.0.5
      # Зашифрованная строка, созданная через encrypt_string
      ansible_ssh_pass: !vault |
          $ANSIBLE_VAULT;1.1;AES256
          3534313261313739613131343734616238323631623562306339316432363737
```

## Дополнительная информация

- [Ansible Vault: Основы](./basics.md)
- [Рекомендации по безопасности (no_log и др.)](./best_practices.md)
- [Алгоритмы и криптосхемы](./algorithms.md)
- [Управление паролями](./passwords.md)
