# Ansible Vault: Практические примеры

## Определения

- **Практические примеры Vault**: Сборник прикладных сценариев применения Ansible Vault для защиты конфиденциальных данных (секретов) в различных окружениях: разработка (Development), непрерывная интеграция и доставка (CI/CD — Continuous Integration / Continuous Delivery) и эксплуатация (Production).
- **Тип переменной File (GitLab CI)**: Механизм CI/CD, при котором содержимое секретной переменной сохраняется во временный файл на диске раннера (Runner), а сама переменная содержит путь к этому файлу.
- **Инлайновое шифрование (Inline Encryption)**: Метод шифрования конкретных значений переменных, позволяющий оставлять структуру YAML-файла (YAML Ain't Markup Language — «YAML не язык разметки») открытой и читаемой для систем контроля версий.

## Основные концепции

### Уровни изоляции секретов

При выборе объекта шифрования следует придерживаться принципа гранулярности:
- **Шифрование значений (Рекомендуется)**: Используйте `ansible-vault encrypt_string`. Это сохраняет читаемость Git-диффов (разницы между версиями файлов) и упрощает разрешение конфликтов при слиянии веток.
- **Шифрование файлов**: Подходит для больших блоков данных (например, SSL-сертификатов — Secure Sockets Layer или приватных SSH-ключей — Secure Shell).
- **Метки доступа (Vault ID)**: Позволяют разграничивать доступ к секретам разных команд или окружений (например, `dev` и `prod`) в рамках одного репозитория.

## Практические сценарии

### Сценарий 1: Защита переменных окружения (Inventory Variables)

Типичный подход для хранения паролей баз данных и ключей доступа.

1. **Создание зашифрованного файла**:
    ```bash
    # Создание файла для группы хостов 'webservers'
    ansible-vault create group_vars/webservers/vault.yml
    ```

2. **Содержимое файла**:
    ```yaml
    # Внутри редактора задаются секреты
    vault_db_password: "MySuperSecretPassword"
    vault_api_token: "abc-123-def-456"
    ```

3. **Запуск с ручным вводом пароля**:
    ```bash
    ansible-playbook site.yml --ask-vault-pass
    ```

### Сценарий 2: Интеграция с Vagrant

Vagrant автоматически передает пароль Vault провижинеру (Provisioner) Ansible, обеспечивая безопасную локальную разработку.

1. **Создание файла пароля**:
    ```bash
    echo "local_dev_pass" > .vault_pass
    # ВАЖНО: Добавьте .vault_pass в .gitignore!
    ```

2. **Настройка `Vagrantfile`**:
    ```ruby
    Vagrant.configure("2") do |config|
      config.vm.provision "ansible" do |ansible|
        ansible.playbook = "playbook.yml"
        # Указание файла пароля для автоматизации
        ansible.vault_password_file = ".vault_pass"
      end
    end
    ```

### Сценарий 3: Современный CI/CD пайплайн (GitLab CI 2024-2025)

Использование переменной типа **File** — стандарт безопасности, исключающий утечку пароля через команды `echo` в логах.

1. **Настройка в GitLab UI**:
    - Перейдите в `Settings -> CI/CD -> Variables`.
    - Добавьте переменную `VAULT_PASS_FILE`.
    - Выберите **Type: File**.
    - Вставьте пароль в поле Value.
    - Включите **Protect variable** и **Mask variable**.

2. **Конфигурация `.gitlab-ci.yml`**:
    ```yaml
    deploy:
      stage: deploy
      image: alpine:latest
      before_script:
        - apk add ansible
        # Установка прав доступа (Ansible требует 0600 для файлов паролей)
        - chmod 600 "$VAULT_PASS_FILE"
      script:
        - ansible-playbook deploy.yml --vault-password-file "$VAULT_PASS_FILE"
      environment: production
    ```

### Сценарий 4: Шифрование строк в YAML-инвентаре

Применяется, когда параметры подключения (например, `ansible_ssh_pass`) специфичны для конкретного хоста.

1. **Генерация зашифрованной строки**:
    ```bash
    ansible-vault encrypt_string 'TargetHostPassword' --name 'ansible_ssh_pass'
    ```

2. **Вставка в инвентарь (`hosts.yml`)**:
    ```yaml
    all:
      hosts:
        db-node-01:
          ansible_host: 192.168.1.50
          ansible_user: deploy
          # Инлайновый секрет с заголовком версии 1.1 и алгоритмом AES256
          ansible_ssh_pass: !vault |
            $ANSIBLE_VAULT;1.1;AES256
            6633363365313835663738643633393165333066373238313437346132333036
    ```

### Сценарий 5: Валидация гигиены секретов с ansible-lint

Используйте статический анализ для предотвращения случайного коммита открытых секретов.

1. **Настройка правила**:
    `ansible-lint` автоматически проверяет наличие директивы `no_log: true` в задачах, использующих переменные с именами `password`, `secret`, `token`.

2. **Пример защищенной задачи**:
    ```yaml
    - name: Get secret from HashiCorp Vault via API
      ansible.builtin.uri:
        url: "https://vault.example.com/v1/secret/data/app"
        headers:
          X-Vault-Token: "{{ vault_token }}"
      register: vault_response
      # Обязательно для предотвращения утечки содержимого ответа в логи
      no_log: true 
    ```

## Дополнительная информация

### Связанные руководства
- [Ansible Vault: Основы](./basics.md) — базовые команды и версии заголовков.
- [Лучшие практики по безопасности](./best_practices.md) — глубокое погружение в `no_log` и эшелонированную защиту.

### Технический справочник
- [Управление паролями и источниками](./passwords.md) — детали работы с `--vault-id` и скриптами.
- [Алгоритмы и криптосхемы](./algorithms.md) — подробности шифрования AES-256-CTR (Advanced Encryption Standard).
